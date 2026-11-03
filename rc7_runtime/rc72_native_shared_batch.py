"""C10: one REAL native DSH call for a compatible N7 ExecutionBatch.

This is a semantic execution *candidate* and never an N7 PASS. Exactly one
real native launcher executes the batch, and each independent WorkItem/Attempt
must cite distinct actually-observed native tool_call refs. The output is
persisted into an additive R1 UNVERIFIED batch-candidate receipt; only N7's
existing deterministic runner/oracle/evidence/reviewer can make business truth.

The A-owned Mission Factory/ReleaseBatchDriver and common R1 schema remain
untouched. The host must supply a genuine scoped WorkerAssignment and bind
the batch launcher through bind_production_model_economy using
canonical_batch_metadata_resolver below. Never auto-infer authorization.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_context_economy import ExecutionBatch
from .rc72_safe_execution_batch import SafeExecutionBatchService
from .rc72_truth import install_rc72_truth_overlay


_ARTIFACT = "rc72_native_batch_candidate"
_EVENT = "RC72_NATIVE_BATCH_CANDIDATE_RECORDED"
_BUCKET = "rc72_native_batch_candidates"


class NativeSharedBatchError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NativeSharedBatchError("NATIVE_BATCH_%s_REQUIRED" % name.upper())
    return value.strip()


def _validate(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("NATIVE_BATCH_CANDIDATE_OBJECT_REQUIRED")
    out = dict(payload)
    for name in (
        "candidate_id", "release_id", "mission_id", "batch_id",
        "batch_receipt_id", "assignment_id", "attempt_id",
        "worker_instance_id", "dsh_session_id", "raw_output_ref",
        "output_sha256", "status", "token_call_id",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["status"] != "UNVERIFIED":
        raise _contracts.DomainValidationError("NATIVE_BATCH_PASS_CANNOT_BE_INFERRED")
    if not out["raw_output_ref"].startswith("file://"):
        raise _contracts.DomainValidationError("NATIVE_BATCH_RAW_DSH_EVIDENCE_REQUIRED")
    if len(out["output_sha256"]) != 64:
        raise _contracts.DomainValidationError("NATIVE_BATCH_OUTPUT_DIGEST_INVALID")
    members = out.get("members")
    if not isinstance(members, list) or len(members) < 2:
        raise _contracts.DomainValidationError("NATIVE_BATCH_MULTI_MEMBER_REQUIRED")
    for member in members:
        if not isinstance(member, dict) or set(member) != {
            "workitem_id", "attempt_id", "observed_tool_refs",
            "proposed_observation", "gaps", "unknowns",
        }:
            raise _contracts.DomainValidationError("NATIVE_BATCH_CANDIDATE_FIELDS_INVALID")
        for name in ("workitem_id", "attempt_id", "proposed_observation"):
            _contracts._require_str(member, name)
        refs = member.get("observed_tool_refs")
        if not isinstance(refs, list) or not refs:
            raise _contracts.DomainValidationError("NATIVE_BATCH_MEMBER_TOOL_REFS_REQUIRED")
        if not all(isinstance(ref, str) and ref.startswith("dsh-event://tool-call/") for ref in refs):
            raise _contracts.DomainValidationError("NATIVE_BATCH_UNOBSERVED_TOOL_REF")
        if len(refs) != len(set(refs)):
            raise _contracts.DomainValidationError("NATIVE_BATCH_MEMBER_TOOL_REFS_REQUIRED")
        for name in ("gaps", "unknowns"):
            if not isinstance(member.get(name), list):
                raise _contracts.DomainValidationError("NATIVE_BATCH_MEMBER_%s_INVALID" % name.upper())
    for name in ("workitem_id", "attempt_id"):
        if len({member[name] for member in members}) != len(members):
            raise _contracts.DomainValidationError("NATIVE_BATCH_MEMBER_%s_NOT_UNIQUE" % name.upper())
    all_refs = [ref for member in members for ref in member["observed_tool_refs"]]
    if len(set(all_refs)) != len(all_refs):
        raise _contracts.DomainValidationError("NATIVE_BATCH_TOOL_REF_SHARED_ACROSS_MEMBERS")
    out["members"] = members
    out["member_count"] = len(members)
    if isinstance(out.get("recorded_at"), bool) or not isinstance(out.get("recorded_at"), int) or out["recorded_at"] < 0:
        raise _contracts.DomainValidationError("NATIVE_BATCH_TIMESTAMP_INVALID")
    version = out.get("artifact_version", 1)
    if type(version) is not int or version < 1:
        raise _contracts.DomainValidationError("NATIVE_BATCH_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_native_batch_candidate_overlay() -> None:
    install_rc72_truth_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = _validate
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "candidate_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "candidate_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    if not hasattr(truth.projection, _BUCKET):
        setattr(truth.projection, _BUCKET, {})
    truth.projection._versions.setdefault(_ARTIFACT, {})


def _one(truth: TruthRuntime, kind: str, **filters: str) -> Dict[str, Any]:
    rows = truth.query(kind, **filters)
    if len(rows) != 1:
        raise NativeSharedBatchError("NATIVE_BATCH_%s_NOT_UNIQUE" % kind.upper())
    return rows[0]


def _candidate_id(release_id: str, receipt_id: str, assignment_id: str) -> str:
    digest = hashlib.sha256(
        ("\x1f".join((release_id, receipt_id, assignment_id))).encode("utf-8")
    ).hexdigest()
    return "NATIVEBATCH-" + digest[:24]


def canonical_batch_metadata_resolver(
    truth: TruthRuntime, *, release_id: str, mission_id: str, review: bool = False,
):
    """One native model billing receipt per BATCH, never per member as a proxy.

    Each business member stays in the SafeExecutionBatch R1 receipt. The
    synthetic model-call workitem_id is deliberately namespaced as a BATCH.
    """
    _required(release_id, "release_id")
    _required(mission_id, "mission_id")
    scope_prefix = "evaluation-batch:" if review else "execution-batch:"

    def resolve(assignment: Any) -> Dict[str, Any]:
        if getattr(assignment, "mission_id", None) != mission_id:
            raise NativeSharedBatchError("NATIVE_BATCH_MISSION_SCOPE_MISMATCH")
        scope = _required(getattr(assignment, "scope", None), "scope")
        if not scope.startswith(scope_prefix):
            raise NativeSharedBatchError("NATIVE_BATCH_SCOPED_LEASE_REQUIRED")
        batch_id = _required(scope[len(scope_prefix):], "batch_id")
        receipt = _one(
            truth, "rc72_execution_batch_receipt",
            release_id=release_id, mission_id=mission_id, batch_id=batch_id,
        )
        if receipt.get("state") not in {"ADMITTED", "RESULTS_RECORDED"}:
            raise NativeSharedBatchError("NATIVE_BATCH_ADMISSION_REQUIRED")
        if review:
            _one(
                truth, _ARTIFACT, release_id=release_id,
                mission_id=mission_id, batch_id=batch_id,
            )
        return {
            "mission_id": mission_id,
            "attempt_id": _required(getattr(assignment, "attempt_id", None), "attempt_id"),
            "agent_id": _required(getattr(assignment, "agent_id", None), "agent_id"),
            "workitem_id": ("EVALUATOR_BATCH:" if review else "EXECUTION_BATCH:") + batch_id,
            "node": receipt["mission_node_type"],
            "stage": receipt["stage"],
            "call_class": "LLM_REQUIRED",
            "retry": False,
        }

    return resolve


class NativeSharedExecutionBatch:
    """Dispatch one independently authorized native DSH session for >=2 WorkItems."""

    def __init__(
        self, truth: TruthRuntime, *, release_id: str,
        launcher: DshHeadlessWorkerLauncher,
    ) -> None:
        install_native_batch_candidate_overlay()
        _ensure_bucket(truth)
        if not isinstance(launcher, DshHeadlessWorkerLauncher):
            raise NativeSharedBatchError("NATIVE_BATCH_DSH_LAUNCHER_REQUIRED")
        if (launcher.truth is not truth or launcher.release_id != release_id
                or not getattr(launcher, "_rc72_production_economy_bound", False)):
            raise NativeSharedBatchError("NATIVE_BATCH_METERED_NATIVE_DSH_REQUIRED")
        self.truth = truth
        self.release_id = _required(release_id, "release_id")
        self.launcher = launcher
        self.safe_batch = SafeExecutionBatchService(truth, release_id=release_id)

    @staticmethod
    def _member_candidates(output: Any, receipt: Mapping[str, Any], invocation: Any) -> list:
        if not isinstance(output, dict) or set(output) != {"status", "members"}:
            raise NativeSharedBatchError("NATIVE_BATCH_STRICT_OUTPUT_REQUIRED")
        if output["status"] != "CANDIDATE":
            raise NativeSharedBatchError("NATIVE_BATCH_MODEL_CANNOT_ASSERT_PASS")
        expected = {
            (member["workitem_id"], member["attempt_id"]): member
            for member in receipt["members"]
        }
        rows = output["members"]
        if not isinstance(rows, list) or len(rows) != len(expected):
            raise NativeSharedBatchError("NATIVE_BATCH_OUTPUT_DENOMINATOR_MISMATCH")
        real_calls = {
            call["call_ref"] for call in getattr(invocation, "tool_calls", ())
            if isinstance(call, dict) and isinstance(call.get("call_ref"), str)
        }
        observed = set()
        separated = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "workitem_id", "attempt_id", "observed_tool_refs",
                "proposed_observation", "gaps", "unknowns",
            }:
                raise NativeSharedBatchError("NATIVE_BATCH_MEMBER_STRICT_FIELDS_REQUIRED")
            if any(
                not isinstance(row.get(name), str) or not row[name].strip()
                for name in ("workitem_id", "attempt_id")
            ):
                raise NativeSharedBatchError("NATIVE_BATCH_MEMBER_IDENTITY_INVALID")
            identity = (row["workitem_id"], row["attempt_id"])
            if identity not in expected or identity in separated:
                raise NativeSharedBatchError("NATIVE_BATCH_MEMBER_LINEAGE_MISMATCH")
            refs = row["observed_tool_refs"]
            if (
                not isinstance(refs, list) or not refs
                or any(not isinstance(ref, str) for ref in refs)
                or len(set(refs)) != len(refs)
                or any(ref not in real_calls or ref in observed for ref in refs)
            ):
                raise NativeSharedBatchError("NATIVE_BATCH_MEMBER_TOOL_PROOF_REQUIRED")
            observed.update(refs)
            if not isinstance(row["proposed_observation"], str) or not row["proposed_observation"].strip():
                raise NativeSharedBatchError("NATIVE_BATCH_MEMBER_OBSERVATION_REQUIRED")
            for key in ("gaps", "unknowns"):
                if not isinstance(row[key], list):
                    raise NativeSharedBatchError("NATIVE_BATCH_MEMBER_%s_INVALID" % key.upper())
            separated[identity] = dict(row)
        if set(separated) != set(expected):
            raise NativeSharedBatchError("NATIVE_BATCH_OUTPUT_NOT_EXACT")
        return [separated[(member["workitem_id"], member["attempt_id"])] for member in receipt["members"]]

    def dispatch(
        self, batch: ExecutionBatch, *, attempt_ids_by_workitem: Mapping[str, str],
        assignment: Any,
    ) -> Dict[str, Any]:
        if not isinstance(batch, ExecutionBatch) or len(batch.workitem_ids) < 2:
            raise NativeSharedBatchError("NATIVE_BATCH_MULTI_MEMBER_REQUIRED")
        if getattr(assignment, "mission_id", None) != batch.mission_id:
            raise NativeSharedBatchError("NATIVE_BATCH_MISSION_SCOPE_MISMATCH")
        if getattr(assignment, "scope", None) != "execution-batch:" + batch.batch_id:
            raise NativeSharedBatchError("NATIVE_BATCH_SCOPED_LEASE_REQUIRED")
        # Every member requires an explicit R1 semantic-only classification.
        # A model batch must NEVER swallow a deterministic WorkItem or infer
        # from a planner label that DSH is permitted for a source case.
        for workitem_id in batch.workitem_ids:
            semantic_rows = self.truth.query(
                "rc72_work_schedule_semantics",
                mission_id=batch.mission_id, workitem_id=workitem_id,
            )
            if len(semantic_rows) != 1:
                raise NativeSharedBatchError("NATIVE_BATCH_R1_SEMANTIC_PROOF_REQUIRED:%s" % workitem_id)
            semantic = semantic_rows[0]
            if semantic.get("release_id") != self.release_id:
                raise NativeSharedBatchError("NATIVE_BATCH_SEMANTIC_RELEASE_MISMATCH")
            if semantic.get("execution_mode") != "SEMANTIC":
                raise NativeSharedBatchError("NATIVE_BATCH_DETERMINISTIC_OR_HYBRID_TOOL_FIRST:%s" % workitem_id)
        if getattr(assignment, "attempt_id", None) in set(attempt_ids_by_workitem.values()):
            raise NativeSharedBatchError("NATIVE_BATCH_MODEL_ATTEMPT_CANNOT_REPLACE_BUSINESS_ATTEMPT")
        authorized = getattr(assignment, "allowed_tools", None)
        if not isinstance(authorized, (list, tuple)) or not authorized:
            raise NativeSharedBatchError("NATIVE_BATCH_TOOLS_NOT_AUTHORIZED")

        expected_refs = set(batch.context_envelope.shared_refs)
        for refs in batch.context_envelope.workitem_refs.values():
            expected_refs.update(refs)
        actual_refs = getattr(assignment, "input_refs", None)
        if (
            not isinstance(actual_refs, (tuple, list))
            or any(not isinstance(ref, str) or not ref for ref in actual_refs)
            or len(set(actual_refs)) != len(actual_refs)
            or set(actual_refs) != expected_refs
        ):
            raise NativeSharedBatchError("NATIVE_BATCH_INPUT_LEASE_REFS_MISMATCH")

        receipt = self.safe_batch.admit(
            batch, attempt_ids_by_workitem=attempt_ids_by_workitem,
        )
        candidate_id = _candidate_id(
            self.release_id, receipt["batch_receipt_id"],
            _required(getattr(assignment, "assignment_id", None), "assignment_id"),
        )
        existing = self.truth.query(_ARTIFACT, candidate_id=candidate_id)
        if len(existing) > 1:
            raise NativeSharedBatchError("NATIVE_BATCH_CANDIDATE_NOT_UNIQUE")
        if existing:
            return existing[0]
        if receipt.get("state") != "ADMITTED":
            raise NativeSharedBatchError("NATIVE_BATCH_PREVIOUS_FORMAL_RESULTS_MUST_NOT_BE_REPLACED")
        # A previous model attempt with no durable candidate must be retried
        # with a fresh (authorized) assignment, never silently respawned.
        if self.truth.query(
            "rc72_token_call", mission_id=batch.mission_id,
            attempt_id=_required(getattr(assignment, "attempt_id", None), "attempt_id"),
        ):
            raise NativeSharedBatchError("NATIVE_BATCH_PREVIOUS_ATTEMPT_REQUIRES_FRESH_ASSIGNMENT")

        prompt_context = {
            "mission_id": batch.mission_id,
            "batch_id": batch.batch_id,
            "context_envelope": batch.context_envelope.as_prompt_projection(),
            "members": [
                {
                    "workitem_id": member["workitem_id"],
                    "attempt_id": member["attempt_id"],
                    "etu_id": member["etu_id"],
                    "case_id": member["case_id"],
                }
                for member in receipt["members"]
            ],
            "authorized_tools": list(authorized),
        }
        required_shape = {
            "status": "CANDIDATE",
            "members": [
                {
                    "workitem_id": member["workitem_id"],
                    "attempt_id": member["attempt_id"],
                    "observed_tool_refs": ["real dsh-event://tool-call/N ref for THIS member"],
                    "proposed_observation": "non-empty raw tool-grounded observation only",
                    "gaps": [],
                    "unknowns": [],
                }
                for member in receipt["members"]
            ],
        }
        prompt = (
            "You are an approved RC7.2 N7 shared semantic worker. One authorized "
            "native DSH invocation may share source context, but EACH Case/ETU/"
            "WorkItem/Attempt must invoke its own actual approved tool and cite "
            "a DISTINCT native dsh-event://tool-call/N ref from this DSH session. "
            "Report exactly one CANDIDATE entry for each listed member. Never "
            "claim PASS, verified Oracle, N7 delivery, N8/N9/N10 convergence or "
            "bank final; the canonical deterministic N7 runner and independent "
            "Evidence Review must independently validate business outcomes. "
            "If a tool is unavailable, record the Gap/Unknown and do not invent "
            "tool results. Context="
            + json.dumps(prompt_context, ensure_ascii=False, sort_keys=True)
            + " RequiredShape=" + json.dumps(required_shape, ensure_ascii=False, sort_keys=True)
        )
        invocation, output = self.launcher.execute(assignment, prompt)
        session = _required(getattr(invocation, "dsh_session_id", None), "dsh_session_id")
        raw_refs = [
            ref for ref in getattr(invocation, "evidence_refs", ())
            if isinstance(ref, str) and ref.startswith("file://")
        ]
        if len(raw_refs) != 1:
            raise NativeSharedBatchError("NATIVE_BATCH_RAW_DSH_EVIDENCE_NOT_UNIQUE")
        members = self._member_candidates(output, receipt, invocation)
        # One actual native DSH process/model-call receipt for the whole batch,
        # never fabricate N measured calls from N business members.
        metering = _one(
            self.truth, "rc72_token_call",
            mission_id=batch.mission_id,
            workitem_id="EXECUTION_BATCH:" + batch.batch_id,
            attempt_id=_required(getattr(assignment, "attempt_id", None), "attempt_id"),
        )
        if metering.get("process_outcome") != "RETURNED":
            raise NativeSharedBatchError("NATIVE_BATCH_REAL_DSH_CALL_PROOF_REQUIRED")
        encoded = json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload = {
            "candidate_id": candidate_id,
            "release_id": self.release_id,
            "mission_id": batch.mission_id,
            "batch_id": batch.batch_id,
            "batch_receipt_id": receipt["batch_receipt_id"],
            "assignment_id": assignment.assignment_id,
            "attempt_id": assignment.attempt_id,
            "worker_instance_id": assignment.worker_instance_id,
            "dsh_session_id": session,
            "raw_output_ref": raw_refs[0],
            "output_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            "token_call_id": metering["call_id"],
            "status": "UNVERIFIED",
            "members": members,
            "member_count": len(members),
            "recorded_at": int(time.time()),
            "artifact_version": 1,
        }
        self.truth.append_atomic(_EVENT, payload)
        return _one(self.truth, _ARTIFACT, candidate_id=candidate_id)
