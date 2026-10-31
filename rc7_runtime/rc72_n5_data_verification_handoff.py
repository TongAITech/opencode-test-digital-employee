"""RC7.2 N5 independent data-candidate verification handoff.

The DATA_PREPARER discovery artifact is advisory candidate truth only.  A fresh,
independent DATA_VERIFIER must re-observe the real system with task-scoped tools
before a physical candidate can even be named.  The verifier emits the V2 raw
candidate contract with a non-canonical ``candidate://`` locator and resource
properties.  This layer persists runtime lineage only; it does not persist the
V2 semantic payload, register a verified DataRef, bind a DataRequirement,
acquire a DataLease, pass N5, or release N6.  Raw verifier bytes must be hash-
anchored by the next trust boundary before any of those transitions are legal.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher, WorkerInvocation
from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadReader
from .models import ContractError
from .rc72_authority import DATA_VERIFIER, RC72AuthorityRuntime
from .rc72_n5_data_discovery_anchor import install_rc72_n5_data_discovery_anchor_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n5_data_verification_attempt"
_EVENT = "RC72_N5_DATA_VERIFICATION_ATTEMPT_UPSERTED"
_BUCKET = "rc72_n5_data_verification_attempts"
_NODE_TYPE = "N5_TEST_DATA"
_NEXT_NODE = "N6_EXECUTABLE_READINESS"
_AGENT_ID = "data-verifier"
_PHASE = "DATA_VERIFICATION"
_CANDIDATE_SCHEMA = "RC72_N5_DATA_VERIFICATION_CANDIDATE_V2"
_ATTEMPT_STATE = "VERIFIER_COMPLETED_PENDING_RAW_ANCHOR"
_PROCESS_OUTCOME = "SUCCEEDED"
_DECISIONS = {"VERIFIED_CANDIDATE", "REPAIR_REQUIRED"}
_STRATEGIES = {"DISCOVER_EXISTING", "CONSTRUCT_NEW"}
_INSTALLED = False


class N5DataVerificationHandoffError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N5DataVerificationHandoffError(
            "RC72_N5_DATA_VERIFY_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _strings(value: Any, name: str, *, allow_empty: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise N5DataVerificationHandoffError(
            "RC72_N5_DATA_VERIFY_%s_LIST_REQUIRED" % name.upper()
        )
    result = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(result) != len(value) or len(result) != len(set(result)):
        raise N5DataVerificationHandoffError(
            "RC72_N5_DATA_VERIFY_%s_INVALID" % name.upper()
        )
    if not allow_empty and not result:
        raise N5DataVerificationHandoffError(
            "RC72_N5_DATA_VERIFY_%s_REQUIRED" % name.upper()
        )
    return result


def _tool_calls(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_VERIFY_TOOL_CALLS_REQUIRED"
        )
    result: List[Dict[str, str]] = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_VERIFY_TOOL_CALL_INVALID"
            )
        call_ref = raw.get("call_ref")
        tool_name = raw.get("tool_name")
        if not isinstance(call_ref, str) or not call_ref.strip():
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_VERIFY_TOOL_CALL_REF_REQUIRED"
            )
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_VERIFY_TOOL_NAME_REQUIRED"
            )
        key = (call_ref.strip(), tool_name.strip())
        if key in seen:
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_VERIFY_TOOL_CALL_DUPLICATE"
            )
        seen.add(key)
        result.append({"call_ref": key[0], "tool_name": key[1]})
    return result


def validate_rc72_n5_data_verification_attempt(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "verification_attempt_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "mission_node_id", "data_requirement_id",
        "resolution_plan_id", "source_case_sha256", "requirement_id", "sst_id",
        "obligation_id", "case_id", "workitem_id", "candidate_artifact_id",
        "candidate_content_hash", "producer_worker_id", "producer_dsh_session_id",
        "verifier_worker_id", "verifier_dsh_session_id", "runtime_assignment_id",
        "authority_lease_id", "candidate_output_ref", "candidate_schema", "state",
        "process_outcome",
    ):
        out[name] = _contracts._require_str(out, name)
    if not out["source_case_sha256"].startswith("sha256:"):
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_VERIFY_CASE_HASH_INVALID"
        )
    if not out["candidate_content_hash"].startswith("sha256:"):
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_VERIFY_CANDIDATE_HASH_INVALID"
        )
    if not out["producer_dsh_session_id"].startswith("session-") or not out[
        "verifier_dsh_session_id"
    ].startswith("session-"):
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_VERIFY_DSH_SESSION_INVALID"
        )
    if out["producer_worker_id"] == out["verifier_worker_id"]:
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_VERIFY_WORKER_INDEPENDENCE_FAIL"
        )
    if out["producer_dsh_session_id"] == out["verifier_dsh_session_id"]:
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_VERIFY_SESSION_INDEPENDENCE_FAIL"
        )
    if out["candidate_schema"] != _CANDIDATE_SCHEMA:
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_VERIFY_SCHEMA_INVALID"
        )
    if out["state"] != _ATTEMPT_STATE or out["process_outcome"] != _PROCESS_OUTCOME:
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_VERIFY_ATTEMPT_STATE_INVALID"
        )
    allowed = _strings(out.get("allowed_tools"), "allowed_tools")
    out["allowed_tools"] = allowed
    out["input_refs"] = _strings(out.get("input_refs"), "input_refs")
    out["runtime_evidence_refs"] = _strings(
        out.get("runtime_evidence_refs"), "runtime_evidence_refs"
    )
    out["observed_tool_calls"] = _tool_calls(out.get("observed_tool_calls"))
    if not {row["tool_name"] for row in out["observed_tool_calls"]}.issubset(set(allowed)):
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_VERIFY_UNAUTHORIZED_TOOL_OBSERVED"
        )
    if not any(ref.startswith("file://") for ref in out["runtime_evidence_refs"]):
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_VERIFY_RAW_RUNTIME_EVIDENCE_REQUIRED"
        )
    for name in ("verifier_started_at", "verifier_finished_at", "created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_VERIFY_%s_INVALID" % name.upper()
            )
    if out["verifier_finished_at"] < out["verifier_started_at"]:
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_VERIFY_TIME_ORDER_INVALID"
        )
    for forbidden in (
        "semantic_payload", "decision", "candidate_ref", "data_domain", "mutable",
        "source_or_constructor", "verification", "validity_window", "cleanup_policy",
        "precondition_refs", "data_ref", "resource_metadata_ref", "binding_id",
        "verified", "data_lease_id", "node_delivery_id", "node_gate_id", "node_pass",
        "n5_pass", "n6_ready", "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_VERIFY_PREMATURE_TRUTH_FORBIDDEN:%s" % forbidden
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_VERIFY_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n5_data_verification_handoff_overlay() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    install_rc7_truth_overlay()
    install_rc72_n5_data_discovery_anchor_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n5_data_verification_attempt
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "verification_attempt_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "verification_attempt_id")
    _INSTALLED = True


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class N5DataVerificationDshHandoffService:
    """Launch one fresh independent verifier for one promoted N5 candidate."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        mission_id: str,
        source_commit: str,
        launcher: DshHeadlessWorkerLauncher,
        allowed_tools: Sequence[str],
    ) -> None:
        install_rc72_n5_data_verification_handoff_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.release_id = _required(release_id, "release_id")
        self.mission_id = _required(mission_id, "mission_id")
        self.source_commit = _required(source_commit, "source_commit")
        self.launcher = launcher
        tools = tuple(
            item.strip() for item in allowed_tools if isinstance(item, str) and item.strip()
        )
        if not tools or len(tools) != len(set(tools)):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_ALLOWED_TOOLS_INVALID"
            )
        self.allowed_tools = tools
        if not isinstance(self.launcher.authority, RC72AuthorityRuntime):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_RC72_AUTHORITY_REQUIRED"
            )
        self.reader = CandidatePayloadReader()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    @staticmethod
    def _verification_attempt_id(artifact_id: str, content_hash: str) -> str:
        return _stable_id("N5DATAVER", artifact_id, content_hash, "INDEPENDENT_VERIFY_V2")

    @staticmethod
    def _precondition_refs(requirement: Mapping[str, Any]) -> List[str]:
        data_requirement_id = str(requirement["data_requirement_id"])
        preconditions = list(requirement.get("case_preconditions") or [])
        if not preconditions:
            return ["data-requirement://%s" % data_requirement_id]
        return [
            "data-requirement://%s/precondition/%d" % (data_requirement_id, index)
            for index, _value in enumerate(preconditions)
        ]

    def _candidate(
        self, release_batch_id: str, data_requirement_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        requirement = self._one(
            "rc72_n5_data_requirement", data_requirement_id=data_requirement_id
        )
        if (
            requirement.get("release_id") != self.release_id
            or requirement.get("mission_id") != self.mission_id
            or requirement.get("release_batch_id") != release_batch_id
            or requirement.get("source_commit") != self.source_commit
            or requirement.get("status") != "UNRESOLVED"
        ):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_REQUIREMENT_LINEAGE_INVALID"
            )
        plans = [
            row for row in self.truth.query(
                "rc72_n5_data_resolution_plan", release_batch_id=release_batch_id
            )
            if row.get("data_requirement_id") == data_requirement_id
            and row.get("source_commit") == self.source_commit
        ]
        if len(plans) != 1 or plans[0].get("status") != "DISCOVERY_REQUIRED":
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_DISCOVERY_PLAN_REQUIRED"
            )
        plan = plans[0]
        if plan.get("binding_id") not in (None, "") or plan.get("data_ref") not in (None, ""):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_PREMATURE_BINDING_FOUND"
            )

        workitem_id = _stable_id("WI-N5-DATA-DISCOVERY", self.mission_id, data_requirement_id)
        task = self._one("rc7_task", task_id=workitem_id)
        if (
            task.get("mission_id") != self.mission_id
            or task.get("node") != "TEST_DATA"
            or task.get("state") != "OUTPUT_PRODUCED"
        ):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_OUTPUT_PRODUCED_REQUIRED"
            )
        outputs = list(task.get("output_artifact_refs") or [])
        if len(outputs) != 1:
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_SINGLE_CANDIDATE_REQUIRED"
            )
        artifact = self._one("rc7_artifact", artifact_id=str(outputs[0]))
        if (
            artifact.get("artifact_type_name") != "DATA_DISCOVERY_CANDIDATE"
            or artifact.get("producer_task_id") != workitem_id
            or artifact.get("state") != "VALID"
        ):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_DISCOVERY_CANDIDATE_INVALID"
            )
        durable = self.reader.load(
            self.truth,
            str(artifact["artifact_id"]),
            expected_mission_id=self.mission_id,
            expected_task_id=workitem_id,
        )
        semantic = dict(durable.semantic_payload)
        expected_semantic = {
            "candidate_kind": "DATA_DISCOVERY_CANDIDATE",
            "release_batch_id": release_batch_id,
            "data_requirement_id": data_requirement_id,
            "resolution_plan_id": str(plan["plan_id"]),
            "case_id": str(requirement["case_id"]),
        }
        for field, expected in expected_semantic.items():
            if semantic.get(field) != expected:
                raise N5DataVerificationHandoffError(
                    "RC72_N5_DATA_VERIFY_CANDIDATE_LINEAGE_MISMATCH:%s" % field
                )
        if list(semantic.get("candidate_unknowns") or []) or list(
            semantic.get("candidate_gaps") or []
        ):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_PRODUCER_GAPS_REQUIRE_REPAIR"
            )
        if not list(semantic.get("observations") or []) or not list(
            semantic.get("verification_plan") or []
        ):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_DISCOVERY_CANDIDATE_INCOMPLETE"
            )
        runtime = durable.envelope.get("runtime_lineage")
        if not isinstance(runtime, dict):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_RUNTIME_LINEAGE_REQUIRED"
            )
        if runtime.get("source_commit") != self.source_commit:
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_SOURCE_COMMIT_MISMATCH"
            )
        anchor = self._one(
            "rc72_n5_data_discovery_evidence_anchor",
            anchor_id=str(runtime.get("evidence_anchor_id") or ""),
        )
        expected_anchor = {
            "mission_id": self.mission_id,
            "release_batch_id": release_batch_id,
            "source_commit": self.source_commit,
            "data_requirement_id": data_requirement_id,
            "resolution_plan_id": str(plan["plan_id"]),
            "case_id": str(requirement["case_id"]),
            "workitem_id": workitem_id,
            "raw_output_sha256": runtime.get("raw_output_sha256"),
            "dsh_session_id": runtime.get("dsh_session_id"),
        }
        for field, expected in expected_anchor.items():
            if anchor.get(field) != expected:
                raise N5DataVerificationHandoffError(
                    "RC72_N5_DATA_VERIFY_ANCHOR_LINEAGE_MISMATCH:%s" % field
                )
        producer_attempt = self._one(
            "rc72_n5_data_discovery_attempt", attempt_id=str(anchor["attempt_id"])
        )
        if producer_attempt.get("worker_instance_id") != task.get("lease_owner"):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_PRODUCER_WORKER_MISMATCH"
            )
        n5 = self._one(
            "rc72_mission_node", mission_id=self.mission_id, node_type=_NODE_TYPE
        )
        n6 = self._one(
            "rc72_mission_node", mission_id=self.mission_id, node_type=_NEXT_NODE
        )
        if n5.get("state") != "RUNNING" or n6.get("state") != "NOT_STARTED":
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_NODE_BOUNDARY_INVALID"
            )
        if self.truth.query("rc72_n5_data_binding", data_requirement_id=data_requirement_id):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_BINDING_ALREADY_EXISTS"
            )
        return requirement, plan, task, artifact, {
            "durable": durable,
            "semantic": semantic,
            "anchor": anchor,
            "producer_attempt": producer_attempt,
        }

    def _input_refs(
        self,
        requirement: Mapping[str, Any],
        plan: Mapping[str, Any],
        artifact: Mapping[str, Any],
    ) -> List[str]:
        return [
            str(artifact["content_ref"]),
            "artifact://%s" % str(artifact["artifact_id"]),
            "data-requirement://%s" % str(requirement["data_requirement_id"]),
            "data-resolution-plan://%s" % str(plan["plan_id"]),
            "case://%s" % str(requirement["case_id"]),
        ]

    def _validate_v2_candidate(
        self,
        value: Mapping[str, Any],
        *,
        requirement: Mapping[str, Any],
        plan: Mapping[str, Any],
        artifact: Mapping[str, Any],
        producer_semantic: Mapping[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(value, Mapping):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_V2_OBJECT_REQUIRED"
            )
        expected_keys = {
            "status", "release_batch_id", "data_requirement_id", "resolution_plan_id",
            "case_id", "candidate_artifact_id", "strategy", "candidate_ref",
            "data_domain", "mutable", "source_or_constructor", "verification",
            "validity_window", "cleanup_policy", "precondition_refs", "unknowns", "gaps",
        }
        if set(value.keys()) != expected_keys:
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_V2_TOP_LEVEL_CONTRACT_INVALID"
            )
        decision = _required(value.get("status"), "v2_status").upper()
        if decision not in _DECISIONS:
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_V2_STATUS_INVALID"
            )
        expected = {
            "release_batch_id": str(requirement["release_batch_id"]),
            "data_requirement_id": str(requirement["data_requirement_id"]),
            "resolution_plan_id": str(plan["plan_id"]),
            "case_id": str(requirement["case_id"]),
            "candidate_artifact_id": str(artifact["artifact_id"]),
            "strategy": str(producer_semantic["strategy"]),
        }
        for field, target in expected.items():
            if value.get(field) != target:
                raise N5DataVerificationHandoffError(
                    "RC72_N5_DATA_VERIFY_V2_LINEAGE_MISMATCH:%s" % field
                )
        precondition_refs = _strings(value.get("precondition_refs"), "precondition_refs")
        if precondition_refs != self._precondition_refs(requirement):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_V2_PRECONDITION_SCOPE_MISMATCH"
            )
        unknowns = _strings(value.get("unknowns"), "unknowns", allow_empty=True)
        gaps = _strings(value.get("gaps"), "gaps", allow_empty=True)
        verification = _required(value.get("verification"), "verification")
        if decision == "VERIFIED_CANDIDATE":
            candidate_ref = _required(value.get("candidate_ref"), "candidate_ref")
            if not candidate_ref.startswith("candidate://"):
                raise N5DataVerificationHandoffError(
                    "RC72_N5_DATA_VERIFY_V2_CANDIDATE_REF_MUST_BE_NONCANONICAL"
                )
            _required(value.get("data_domain"), "data_domain")
            if not isinstance(value.get("mutable"), bool):
                raise N5DataVerificationHandoffError(
                    "RC72_N5_DATA_VERIFY_V2_MUTABLE_BOOL_REQUIRED"
                )
            _required(value.get("source_or_constructor"), "source_or_constructor")
            _required(value.get("validity_window"), "validity_window")
            _required(value.get("cleanup_policy"), "cleanup_policy")
            if unknowns or gaps:
                raise N5DataVerificationHandoffError(
                    "RC72_N5_DATA_VERIFY_V2_VERIFIED_CANNOT_HAVE_GAPS"
                )
        else:
            if not unknowns and not gaps:
                raise N5DataVerificationHandoffError(
                    "RC72_N5_DATA_VERIFY_V2_REPAIR_REASON_REQUIRED"
                )
            for name in (
                "candidate_ref", "data_domain", "source_or_constructor",
                "validity_window", "cleanup_policy",
            ):
                if value.get(name) not in (None, ""):
                    raise N5DataVerificationHandoffError(
                        "RC72_N5_DATA_VERIFY_V2_REPAIR_CANNOT_CLAIM_RESOURCE:%s" % name
                    )
            if value.get("mutable") is not None:
                raise N5DataVerificationHandoffError(
                    "RC72_N5_DATA_VERIFY_V2_REPAIR_CANNOT_CLAIM_MUTABILITY"
                )
        # Exact-key contract excludes canonical data_ref/binding/lease/node claims.
        return dict(value)

    def _prompt(
        self,
        *,
        requirement: Mapping[str, Any],
        plan: Mapping[str, Any],
        artifact: Mapping[str, Any],
        producer_semantic: Mapping[str, Any],
    ) -> str:
        context = {
            "mission_id": self.mission_id,
            "release_batch_id": requirement["release_batch_id"],
            "data_requirement_id": requirement["data_requirement_id"],
            "resolution_plan_id": plan["plan_id"],
            "case_id": requirement["case_id"],
            "requirement_text": requirement["requirement_text"],
            "case_preconditions": list(requirement.get("case_preconditions") or []),
            "case_code_trace": list(requirement.get("case_code_trace") or []),
            "precondition_refs": self._precondition_refs(requirement),
            "producer_candidate_artifact_id": artifact["artifact_id"],
            "producer_candidate": dict(producer_semantic),
            "authorized_tools": list(self.allowed_tools),
        }
        shape = {
            "status": "VERIFIED_CANDIDATE|REPAIR_REQUIRED",
            "release_batch_id": requirement["release_batch_id"],
            "data_requirement_id": requirement["data_requirement_id"],
            "resolution_plan_id": plan["plan_id"],
            "case_id": requirement["case_id"],
            "candidate_artifact_id": artifact["artifact_id"],
            "strategy": producer_semantic["strategy"],
            "candidate_ref": "candidate://physical-locator or null on repair",
            "data_domain": "domain or null on repair",
            "mutable": "boolean or null on repair",
            "source_or_constructor": "real source/constructor or null on repair",
            "verification": "what was independently verified with real tool evidence",
            "validity_window": "validity description or null on repair",
            "cleanup_policy": "cleanup description or null on repair",
            "precondition_refs": self._precondition_refs(requirement),
            "unknowns": [],
            "gaps": [],
        }
        return (
            "You are the independent RC7.2 N5 DATA_VERIFIER. Do not trust the DATA_PREPARER's prose as proof. "
            "Use at least one real tool from authorized_tools to independently locate and verify a physical candidate that satisfies the exact DataRequirement and every precondition_ref. "
            "If verified, name it only with a non-canonical candidate:// locator; never emit data_ref, binding_id, data_lease_id, reservation, N5 PASS, N6 READY, field_verified or BANK_FINAL. "
            "If independent verification cannot prove the resource, return REPAIR_REQUIRED with null resource fields and non-empty unknowns/gaps. "
            "Return exactly one strict top-level JSON object matching RequiredShape and no markdown. Context="
            + json.dumps(context, ensure_ascii=False, sort_keys=True)
            + " RequiredShape=" + json.dumps(shape, ensure_ascii=False, sort_keys=True)
        )

    def _prior_attempts(self, verification_attempt_id: str) -> List[Dict[str, Any]]:
        return self.truth.query(_ARTIFACT, verification_attempt_id=verification_attempt_id)

    def _raw_candidate_from_event(
        self,
        event: Mapping[str, Any],
        *,
        requirement: Mapping[str, Any],
        plan: Mapping[str, Any],
        artifact: Mapping[str, Any],
        producer_semantic: Mapping[str, Any],
    ) -> Dict[str, Any]:
        refs = [
            ref for ref in list(event.get("evidence_refs") or [])
            if isinstance(ref, str) and ref.startswith("file://")
        ]
        if len(refs) != 1:
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_RAW_EVIDENCE_NOT_UNIQUE"
            )
        path = Path(refs[0][len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.launcher.state_root)
        except ValueError as exc:
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_RAW_EVIDENCE_OUTSIDE_STATE_ROOT"
            ) from exc
        if not path.is_file():
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_RAW_EVIDENCE_MISSING"
            )
        events = tuple(
            DshHeadlessWorkerLauncher._parse_json_lines(
                path.read_text(encoding="utf-8", errors="strict")
            )
        )
        output = DshHeadlessWorkerLauncher._final_json(events)
        return self._validate_v2_candidate(
            output,
            requirement=requirement,
            plan=plan,
            artifact=artifact,
            producer_semantic=producer_semantic,
        )

    def _persist(
        self,
        *,
        verification_attempt_id: str,
        requirement: Mapping[str, Any],
        plan: Mapping[str, Any],
        task: Mapping[str, Any],
        artifact: Mapping[str, Any],
        anchor: Mapping[str, Any],
        invocation: WorkerInvocation,
        runtime_event: Mapping[str, Any],
        candidate: Mapping[str, Any],
        validate_live_authority: bool,
    ) -> Dict[str, Any]:
        producer_worker_id = _required(anchor.get("worker_instance_id"), "producer_worker_id")
        producer_session_id = _required(anchor.get("dsh_session_id"), "producer_dsh_session_id")
        if invocation.worker_instance_id == producer_worker_id:
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_VERIFIER_NOT_INDEPENDENT"
            )
        verifier_session_id = _required(invocation.dsh_session_id, "verifier_dsh_session_id")
        if verifier_session_id == producer_session_id:
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_SESSION_REUSED_FROM_PRODUCER"
            )
        for row in self.truth.query(_ARTIFACT):
            if (
                row.get("verification_attempt_id") != verification_attempt_id
                and row.get("verifier_dsh_session_id") == verifier_session_id
            ):
                raise N5DataVerificationHandoffError(
                    "RC72_N5_DATA_VERIFY_VERIFIER_SESSION_REUSED"
                )
        if invocation.result != "PASS" or invocation.exit_code != 0:
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_DSH_PROCESS_NOT_SUCCESSFUL"
            )
        if not invocation.tool_calls or not invocation.output_refs:
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_REAL_TOOL_AND_OUTPUT_REQUIRED"
            )
        observed: List[Dict[str, str]] = []
        for raw in invocation.tool_calls:
            call_ref = _required(raw.get("call_ref"), "tool_call_ref")
            tool_name = _required(raw.get("tool_name"), "tool_name")
            if tool_name not in self.allowed_tools:
                raise N5DataVerificationHandoffError(
                    "RC72_N5_DATA_VERIFY_UNAUTHORIZED_TOOL:%s" % tool_name
                )
            if validate_live_authority:
                self.launcher.authority.authorize_tool(
                    invocation.worker_instance_id, invocation.lease_id, tool_name
                )
            observed.append({"call_ref": call_ref, "tool_name": tool_name})
        self._validate_v2_candidate(
            candidate,
            requirement=requirement,
            plan=plan,
            artifact=artifact,
            producer_semantic=self.reader.load(
                self.truth,
                str(artifact["artifact_id"]),
                expected_mission_id=self.mission_id,
                expected_task_id=str(task["task_id"]),
            ).semantic_payload,
        )
        if (
            runtime_event.get("worker_instance_id") != invocation.worker_instance_id
            or runtime_event.get("attempt_id") != verification_attempt_id
            or runtime_event.get("assignment_id") != invocation.assignment_id
            or runtime_event.get("dsh_session_id") != verifier_session_id
        ):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_RUNTIME_EVENT_LINEAGE_MISMATCH"
            )
        raw_refs = list(dict.fromkeys(invocation.evidence_refs))
        if not any(ref.startswith("file://") for ref in raw_refs):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_RAW_RUNTIME_EVIDENCE_REQUIRED"
            )
        payload = {
            "verification_attempt_id": verification_attempt_id,
            "release_id": self.release_id,
            "mission_id": self.mission_id,
            "release_batch_id": str(requirement["release_batch_id"]),
            "source_commit": self.source_commit,
            "mission_node_id": str(requirement["mission_node_id"]),
            "data_requirement_id": str(requirement["data_requirement_id"]),
            "resolution_plan_id": str(plan["plan_id"]),
            "source_case_sha256": str(requirement["source_case_sha256"]),
            "requirement_id": str(requirement["requirement_id"]),
            "sst_id": str(requirement["sst_id"]),
            "obligation_id": str(requirement["obligation_id"]),
            "case_id": str(requirement["case_id"]),
            "workitem_id": str(task["task_id"]),
            "candidate_artifact_id": str(artifact["artifact_id"]),
            "candidate_content_hash": str(artifact["content_hash"]),
            "producer_worker_id": producer_worker_id,
            "producer_dsh_session_id": producer_session_id,
            "verifier_worker_id": str(invocation.worker_instance_id),
            "verifier_dsh_session_id": verifier_session_id,
            "runtime_assignment_id": str(invocation.assignment_id),
            "authority_lease_id": str(invocation.lease_id),
            "candidate_output_ref": str(invocation.output_refs[-1]),
            "candidate_schema": _CANDIDATE_SCHEMA,
            "allowed_tools": list(self.allowed_tools),
            "input_refs": list(invocation.input_refs),
            "observed_tool_calls": observed,
            "runtime_evidence_refs": raw_refs,
            "verifier_started_at": int(invocation.started_at),
            "verifier_finished_at": int(invocation.finished_at),
            "state": _ATTEMPT_STATE,
            "process_outcome": _PROCESS_OUTCOME,
        }
        existing = self._prior_attempts(verification_attempt_id)
        if existing:
            if len(existing) != 1:
                raise N5DataVerificationHandoffError(
                    "RC72_N5_DATA_VERIFY_ATTEMPT_NOT_UNIQUE"
                )
            immutable = (
                "release_id", "mission_id", "release_batch_id", "source_commit",
                "data_requirement_id", "resolution_plan_id", "workitem_id",
                "candidate_artifact_id", "candidate_content_hash", "producer_worker_id",
                "producer_dsh_session_id", "verifier_worker_id", "verifier_dsh_session_id",
                "runtime_assignment_id", "candidate_schema", "state", "process_outcome",
            )
            for field in immutable:
                if existing[0].get(field) != payload.get(field):
                    raise N5DataVerificationHandoffError(
                        "RC72_N5_DATA_VERIFY_ATTEMPT_CONFLICT:%s" % field
                    )
            return existing[0]
        now = _now()
        payload.update({"created_at": now, "updated_at": now, "artifact_version": 1})
        self.truth.append_atomic(_EVENT, payload)
        rows = self._prior_attempts(verification_attempt_id)
        if len(rows) != 1:
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_ATTEMPT_PERSISTENCE_FAILED"
            )
        return rows[0]

    def verify(
        self, *, release_batch_id: str, data_requirement_id: str
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        data_requirement_id = _required(data_requirement_id, "data_requirement_id")
        requirement, plan, task, artifact, extra = self._candidate(
            release_batch_id, data_requirement_id
        )
        durable = extra["durable"]
        semantic = extra["semantic"]
        anchor = extra["anchor"]
        verification_attempt_id = self._verification_attempt_id(
            str(artifact["artifact_id"]), str(artifact["content_hash"])
        )
        existing = self._prior_attempts(verification_attempt_id)
        if existing:
            if len(existing) != 1:
                raise N5DataVerificationHandoffError(
                    "RC72_N5_DATA_VERIFY_ATTEMPT_NOT_UNIQUE"
                )
            row = existing[0]
            if row.get("source_commit") != self.source_commit:
                raise N5DataVerificationHandoffError(
                    "RC72_N5_DATA_VERIFY_ATTEMPT_SOURCE_MISMATCH"
                )
            return {
                "status": "RESUMED",
                "verification_attempt_id": verification_attempt_id,
                "data_requirement_id": data_requirement_id,
                "candidate_artifact_id": str(artifact["artifact_id"]),
                "producer_worker_id": row["producer_worker_id"],
                "producer_dsh_session_id": row["producer_dsh_session_id"],
                "verifier_worker_id": row["verifier_worker_id"],
                "verifier_dsh_session_id": row["verifier_dsh_session_id"],
                "attempt_state": row["state"],
                "workitem_state": str(task["state"]),
            }

        prior_events = [
            row for row in self.truth.query("agent_runtime_event", mission_id=self.mission_id)
            if row.get("event_name") == "HANDOFF_RETURNED"
            and row.get("attempt_id") == verification_attempt_id
            and row.get("agent_id") == _AGENT_ID
        ]
        if len(prior_events) > 1:
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_RUNTIME_EVENT_NOT_UNIQUE"
            )
        if prior_events:
            event = prior_events[0]
            invocation = WorkerInvocation(
                worker_instance_id=str(event.get("worker_instance_id") or ""),
                agent_id=str(event.get("agent_id") or ""),
                mission_id=str(event.get("mission_id") or ""),
                attempt_id=str(event.get("attempt_id") or ""),
                assignment_id=str(event.get("assignment_id") or ""),
                lease_id=str(event.get("lease_id") or ""),
                parent_worker_id=str(event.get("parent_worker_id") or ""),
                scope=str(event.get("scope") or ""),
                input_refs=list(event.get("input_refs") or []),
                tool_calls=list(event.get("tool_calls") or []),
                output_refs=list(event.get("output_refs") or []),
                evidence_refs=list(event.get("evidence_refs") or []),
                started_at=int(event.get("started_at") or 0),
                finished_at=int(event.get("finished_at") or 0),
                result=str(event.get("result") or ""),
                dsh_session_id=str(event.get("dsh_session_id") or "") or None,
                exit_code=event.get("exit_code") if isinstance(event.get("exit_code"), int) else None,
            )
            candidate = self._raw_candidate_from_event(
                event,
                requirement=requirement,
                plan=plan,
                artifact=artifact,
                producer_semantic=semantic,
            )
            row = self._persist(
                verification_attempt_id=verification_attempt_id,
                requirement=requirement,
                plan=plan,
                task=task,
                artifact=artifact,
                anchor=anchor,
                invocation=invocation,
                runtime_event=event,
                candidate=candidate,
                validate_live_authority=False,
            )
            return {
                "status": "RECOVERED",
                "verification_attempt_id": verification_attempt_id,
                "data_requirement_id": data_requirement_id,
                "candidate_artifact_id": str(artifact["artifact_id"]),
                "producer_worker_id": row["producer_worker_id"],
                "producer_dsh_session_id": row["producer_dsh_session_id"],
                "verifier_worker_id": row["verifier_worker_id"],
                "verifier_dsh_session_id": row["verifier_dsh_session_id"],
                "attempt_state": row["state"],
                "workitem_state": str(task["state"]),
            }

        input_refs = self._input_refs(requirement, plan, artifact)
        assignment = self.launcher.assign(
            agent_id=_AGENT_ID,
            role=DATA_VERIFIER,
            phase=_PHASE,
            mission_id=self.mission_id,
            attempt_id=verification_attempt_id,
            scope="artifact:%s" % str(artifact["artifact_id"]),
            input_refs=tuple(input_refs),
            allowed_artifact_types=(),
            allowed_tools=self.allowed_tools,
            parent_worker_id=self.launcher.coordinator_instance_id,
        )
        if assignment.worker_instance_id == anchor.get("worker_instance_id"):
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_VERIFIER_NOT_INDEPENDENT"
            )
        invocation, candidate = self.launcher.execute(
            assignment,
            self._prompt(
                requirement=requirement,
                plan=plan,
                artifact=artifact,
                producer_semantic=semantic,
            ),
        )
        self._validate_v2_candidate(
            candidate,
            requirement=requirement,
            plan=plan,
            artifact=artifact,
            producer_semantic=semantic,
        )
        events = [
            row for row in self.truth.query("agent_runtime_event", mission_id=self.mission_id)
            if row.get("event_name") == "HANDOFF_RETURNED"
            and row.get("attempt_id") == verification_attempt_id
            and row.get("assignment_id") == invocation.assignment_id
        ]
        if len(events) != 1:
            raise N5DataVerificationHandoffError(
                "RC72_N5_DATA_VERIFY_HANDOFF_RETURNED_REQUIRED:%d" % len(events)
            )
        row = self._persist(
            verification_attempt_id=verification_attempt_id,
            requirement=requirement,
            plan=plan,
            task=task,
            artifact=artifact,
            anchor=anchor,
            invocation=invocation,
            runtime_event=events[0],
            candidate=candidate,
            validate_live_authority=True,
        )
        return {
            "status": "VERIFIER_SESSION_OBSERVED",
            "verification_attempt_id": verification_attempt_id,
            "data_requirement_id": data_requirement_id,
            "candidate_artifact_id": str(artifact["artifact_id"]),
            "producer_worker_id": row["producer_worker_id"],
            "producer_dsh_session_id": row["producer_dsh_session_id"],
            "verifier_worker_id": row["verifier_worker_id"],
            "verifier_dsh_session_id": row["verifier_dsh_session_id"],
            "attempt_state": row["state"],
            "workitem_state": str(task["state"]),
        }


install_rc72_n5_data_verification_handoff_overlay()

__all__ = [
    "N5DataVerificationDshHandoffService",
    "N5DataVerificationHandoffError",
    "install_rc72_n5_data_verification_handoff_overlay",
    "validate_rc72_n5_data_verification_attempt",
]
