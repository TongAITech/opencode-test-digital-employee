"""RC7.2 N5 data-discovery assignment -> fresh DSH DATA_PREPARER handoff.

This bridge consumes exactly one governed N5 discovery assignment, adopts its
pre-allocated worker identity, grants only task-scoped tool authority, and
observes a fresh real DSH session. The returned JSON remains an untrusted raw
candidate: this layer does not create DataRef/binding/DataLease truth, does not
complete N5, and never releases N6. Raw bytes are anchored and promoted by
later evidence-bound stages.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher, WorkerAssignment, WorkerInvocation
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_authority import DATA_PREPARER, RC72AuthorityRuntime
from .rc72_n5_data_discovery_assignment import install_rc72_n5_data_discovery_assignment_overlay
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n5_data_discovery_attempt"
_EVENT = "RC72_N5_DATA_DISCOVERY_ATTEMPT_UPSERTED"
_BUCKET = "rc72_n5_data_discovery_attempts"
_NODE_TYPE = "N5_TEST_DATA"
_NEXT_NODE = "N6_EXECUTABLE_READINESS"
_STAGE = "TEST_DATA"
_TEAM_ROLE = DATA_PREPARER
_AGENT_ID = "data-preparer"
_PHASE = "MISSION_NODE_EXECUTION"
_ASSIGNMENT_STATUS = "LEASED_FOR_HANDOFF"
_ATTEMPT_STATE = "WORKER_COMPLETED_PENDING_RAW_ANCHOR"
_HANDOFF_STATUS = "DSH_SESSION_OBSERVED"
_PROCESS_OUTCOME = "SUCCEEDED"
_CANDIDATE_SCHEMA = "RC72_N5_DATA_DISCOVERY_CANDIDATE_V1"
_STRATEGIES = {"DISCOVER_EXISTING", "CONSTRUCT_NEW"}
_INSTALLED = False


class N5DataDiscoveryHandoffError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N5DataDiscoveryHandoffError(
            "RC72_N5_DISCOVERY_HANDOFF_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _strings(value: Any, name: str, *, required: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_%s_INVALID" % name.upper()
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_%s_INVALID" % name.upper()
        )
    out = [item.strip() for item in value]
    if len(out) != len(set(out)):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_%s_DUPLICATE" % name.upper()
        )
    if required and not out:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_%s_REQUIRED" % name.upper()
        )
    return out


def _tool_calls(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_OBSERVED_TOOL_CALLS_REQUIRED"
        )
    out: List[Dict[str, str]] = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise _contracts.DomainValidationError(
                "RC72_N5_DISCOVERY_HANDOFF_TOOL_CALL_INVALID"
            )
        call_ref = _required(raw.get("call_ref"), "tool_call_ref")
        tool_name = _required(raw.get("tool_name"), "tool_name")
        key = (call_ref, tool_name)
        if key in seen:
            raise _contracts.DomainValidationError(
                "RC72_N5_DISCOVERY_HANDOFF_TOOL_CALL_DUPLICATE"
            )
        seen.add(key)
        out.append({"call_ref": call_ref, "tool_name": tool_name})
    return out


def validate_rc72_n5_data_discovery_attempt(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "attempt_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "assignment_id", "dispatch_id", "mission_node_id",
        "node_type", "stage", "data_requirement_id", "resolution_plan_id",
        "source_case_sha256", "requirement_id", "sst_id", "obligation_id",
        "case_id", "workitem_id", "worker_instance_id", "team_role",
        "agent_id", "runtime_assignment_id", "authority_lease_id",
        "dsh_session_id", "runtime_event_id", "candidate_output_ref",
        "candidate_schema", "state", "handoff_status", "process_outcome",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["node_type"] != _NODE_TYPE or out["stage"] != _STAGE:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_NODE_INVALID"
        )
    if out["team_role"] != _TEAM_ROLE or out["agent_id"] != _AGENT_ID:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_ROLE_INVALID"
        )
    if not out["source_case_sha256"].startswith("sha256:"):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_CASE_HASH_INVALID"
        )
    if not out["dsh_session_id"].startswith("session-"):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_DSH_SESSION_INVALID"
        )
    if out["candidate_schema"] != _CANDIDATE_SCHEMA:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_CANDIDATE_SCHEMA_INVALID"
        )
    if out["state"] != _ATTEMPT_STATE:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_ATTEMPT_STATE_INVALID"
        )
    if out["handoff_status"] != _HANDOFF_STATUS:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_STATUS_INVALID"
        )
    if out["process_outcome"] != _PROCESS_OUTCOME:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_PROCESS_OUTCOME_INVALID"
        )
    generation = out.get("assignment_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation != 1:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_ASSIGNMENT_GENERATION_INVALID"
        )
    out["assignment_generation"] = generation
    out["authorized_tools"] = _strings(
        out.get("authorized_tools"), "authorized_tools", required=True
    )
    out["required_capabilities"] = _strings(
        out.get("required_capabilities"), "required_capabilities", required=True
    )
    out["input_refs"] = _strings(out.get("input_refs"), "input_refs", required=True)
    out["runtime_evidence_refs"] = _strings(
        out.get("runtime_evidence_refs"), "runtime_evidence_refs", required=True
    )
    out["observed_tool_calls"] = _tool_calls(out.get("observed_tool_calls"))
    observed = {item["tool_name"] for item in out["observed_tool_calls"]}
    if not observed.issubset(set(out["authorized_tools"])):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_UNAUTHORIZED_TOOL_OBSERVED"
        )
    if not any(str(ref).startswith("file://") for ref in out["runtime_evidence_refs"]):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_RAW_RUNTIME_EVIDENCE_REQUIRED"
        )
    for name in ("worker_started_at", "worker_finished_at", "created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N5_DISCOVERY_HANDOFF_%s_INVALID" % name.upper()
            )
    if out["worker_finished_at"] < out["worker_started_at"]:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_TIME_ORDER_INVALID"
        )
    for forbidden in (
        "semantic_payload", "data_ref", "binding_id", "verification", "verified",
        "reserved", "data_lease_id", "raw_evidence_sha256", "canonical_evidence_id",
        "node_delivery_id", "node_gate", "node_gate_id", "node_pass", "n5_pass",
        "n6_ready", "q7_pass", "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N5_DISCOVERY_HANDOFF_BUSINESS_CLAIM_FORBIDDEN:%s" % forbidden
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_HANDOFF_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n5_data_discovery_handoff_overlay() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_n5_data_discovery_assignment_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n5_data_discovery_attempt
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "attempt_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "attempt_id")
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


class N5DataDiscoveryDshHandoffService:
    """Run one assigned N5 DataRequirement in a fresh DATA_PREPARER DSH session."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        source_commit: str,
        launcher: DshHeadlessWorkerLauncher,
        allowed_tools: Sequence[str],
    ) -> None:
        install_rc72_n5_data_discovery_handoff_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.launcher = launcher
        tools = [str(item).strip() for item in allowed_tools if isinstance(item, str) and item.strip()]
        if not tools or len(tools) != len(set(tools)):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_ALLOWED_TOOLS_INVALID"
            )
        self.allowed_tools = tuple(tools)
        if not isinstance(self.launcher.authority, RC72AuthorityRuntime):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_RC72_AUTHORITY_REQUIRED"
            )

    @staticmethod
    def _attempt_id(assignment_id: str) -> str:
        raw = "\x1f".join((assignment_id, "N5_DATA_DISCOVERY_DSH_ATTEMPT"))
        return "N5DATAATT-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _runtime_assignment_id(assignment_id: str) -> str:
        raw = "\x1f".join((assignment_id, "N5_DATA_DISCOVERY_DSH_HANDOFF"))
        return "N5DATADSH-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    @staticmethod
    def _expected_input_refs(dispatch: Mapping[str, Any]) -> List[str]:
        refs = [
            "data-requirement://%s" % str(dispatch["data_requirement_id"]),
            "data-resolution-plan://%s" % str(dispatch["resolution_plan_id"]),
            "requirement://%s" % str(dispatch["requirement_id"]),
            "sst://%s" % str(dispatch["sst_id"]),
            "obligation://%s" % str(dispatch["obligation_id"]),
            "case://%s" % str(dispatch["case_id"]),
        ]
        refs.extend(
            "artifact://%s" % str(item)
            for item in list(dispatch.get("parent_artifact_refs") or [])
        )
        return refs

    def _preflight(
        self, release_batch_id: str, data_requirement_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        exact = [
            row for row in self.truth.query(
                "rc72_n5_data_discovery_assignment", release_batch_id=release_batch_id
            )
            if row.get("source_commit") == self.source_commit
            and row.get("data_requirement_id") == data_requirement_id
            and row.get("status") == _ASSIGNMENT_STATUS
            and row.get("stage") == _STAGE
            and row.get("team_role") == _TEAM_ROLE
            and row.get("agent_id") == _AGENT_ID
        ]
        if len(exact) != 1:
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_EXACT_ASSIGNMENT_REQUIRED:%d" % len(exact)
            )
        assignment = exact[0]
        mission_id = _required(assignment.get("mission_id"), "mission_id")
        release_id = _required(assignment.get("release_id"), "release_id")
        node_id = _required(assignment.get("mission_node_id"), "mission_node_id")
        workitem_id = _required(assignment.get("workitem_id"), "workitem_id")
        worker_id = _required(assignment.get("worker_instance_id"), "worker_instance_id")

        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        if batch.get("mission_id") != mission_id or batch.get("release_id") != release_id:
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_RELEASE_BATCH_LINEAGE_MISMATCH"
            )

        dispatch = self._one(
            "rc72_n5_data_discovery_dispatch",
            dispatch_id=str(assignment["dispatch_id"]),
        )
        immutable = (
            "release_id", "mission_id", "release_batch_id", "source_commit",
            "mission_node_id", "data_requirement_id", "resolution_plan_id",
            "source_case_sha256", "requirement_id", "sst_id", "obligation_id",
            "case_id", "workitem_id", "stage", "team_role",
            "execution_substrate", "worker_policy",
        )
        for field in immutable:
            if dispatch.get(field) != assignment.get(field):
                raise N5DataDiscoveryHandoffError(
                    "RC72_N5_DISCOVERY_HANDOFF_DISPATCH_LINEAGE_MISMATCH:%s" % field
                )
        if dispatch.get("status") != "READY_FOR_ASSIGNMENT":
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_DISPATCH_NOT_READY"
            )
        if list(assignment.get("required_capabilities") or []) != list(
            dispatch.get("required_capabilities") or []
        ):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_CAPABILITY_LINEAGE_MISMATCH"
            )
        if list(assignment.get("input_refs") or []) != self._expected_input_refs(dispatch):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_INPUT_LINEAGE_MISMATCH"
            )

        plan = self._one(
            "rc72_n5_data_resolution_plan",
            plan_id=str(assignment["resolution_plan_id"]),
        )
        if (
            plan.get("release_id") != release_id
            or plan.get("mission_id") != mission_id
            or plan.get("release_batch_id") != release_batch_id
            or plan.get("source_commit") != self.source_commit
            or plan.get("data_requirement_id") != data_requirement_id
            or plan.get("source_case_sha256") != assignment.get("source_case_sha256")
            or plan.get("status") != "DISCOVERY_REQUIRED"
            or plan.get("binding_id") not in (None, "")
            or plan.get("data_ref") not in (None, "")
        ):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_RESOLUTION_PLAN_INVALID"
            )
        requirement = self._one(
            "rc72_n5_data_requirement", data_requirement_id=data_requirement_id
        )
        for field in (
            "release_id", "mission_id", "release_batch_id", "source_commit",
            "source_case_sha256", "requirement_id", "sst_id", "obligation_id", "case_id",
        ):
            if requirement.get(field) != assignment.get(field):
                raise N5DataDiscoveryHandoffError(
                    "RC72_N5_DISCOVERY_HANDOFF_DATA_REQUIREMENT_LINEAGE_MISMATCH:%s"
                    % field
                )
        if requirement.get("status") != "UNRESOLVED":
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_DATA_REQUIREMENT_NOT_UNRESOLVED"
            )
        if self.truth.query("rc72_n5_data_binding", data_requirement_id=data_requirement_id):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_BINDING_ALREADY_EXISTS"
            )

        node = self._one("rc72_mission_node", mission_node_id=node_id)
        if (
            node.get("mission_id") != mission_id
            or node.get("node_type") != _NODE_TYPE
            or node.get("state") != "RUNNING"
        ):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_N5_NOT_RUNNING"
            )
        n6 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE
        )
        if n6.get("state") != "NOT_STARTED":
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_N6_ALREADY_RELEASED"
            )

        task = self._one("rc7_task", task_id=workitem_id)
        if (
            task.get("mission_id") != mission_id
            or task.get("node") != _STAGE
            or task.get("task_type") != "RC72_NODE_WORK"
            or task.get("state") != "LEASED"
            or task.get("lease_owner") != worker_id
        ):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_WORKITEM_LEASE_MISMATCH"
            )
        if list(task.get("required_capabilities") or []) != list(
            assignment.get("required_capabilities") or []
        ):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_WORKITEM_CAPABILITY_MISMATCH"
            )
        if list(task.get("input_artifact_refs") or []) != list(
            dispatch.get("parent_artifact_refs") or []
        ):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_PARENT_ARTIFACT_DRIFT"
            )
        if set(task.get("dependency_task_ids") or []) != set(
            dispatch.get("dependency_workitem_refs") or []
        ):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_DEPENDENCY_DRIFT"
            )
        return assignment, dispatch, task

    @staticmethod
    def _validate_candidate(
        candidate: Mapping[str, Any], assignment: Mapping[str, Any]
    ) -> Dict[str, Any]:
        if not isinstance(candidate, Mapping):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_CANDIDATE_OBJECT_REQUIRED"
            )
        expected_keys = {
            "status", "release_batch_id", "data_requirement_id",
            "resolution_plan_id", "case_id", "strategy", "observations",
            "verification_plan", "unknowns", "gaps",
        }
        if set(candidate.keys()) != expected_keys:
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_CANDIDATE_TOP_LEVEL_CONTRACT_INVALID"
            )
        if candidate.get("status") != "CANDIDATE":
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_CANDIDATE_STATUS_INVALID"
            )
        for field in (
            "release_batch_id", "data_requirement_id", "resolution_plan_id", "case_id"
        ):
            if candidate.get(field) != assignment.get(field):
                raise N5DataDiscoveryHandoffError(
                    "RC72_N5_DISCOVERY_HANDOFF_CANDIDATE_%s_MISMATCH" % field.upper()
                )
        strategy = _required(candidate.get("strategy"), "candidate_strategy").upper()
        if strategy not in _STRATEGIES:
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_CANDIDATE_STRATEGY_INVALID"
            )
        observations = candidate.get("observations")
        if not isinstance(observations, list) or not observations:
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_CANDIDATE_OBSERVATIONS_REQUIRED"
            )
        for index, item in enumerate(observations):
            if not isinstance(item, Mapping) or set(item.keys()) != {"kind", "summary"}:
                raise N5DataDiscoveryHandoffError(
                    "RC72_N5_DISCOVERY_HANDOFF_OBSERVATION_CONTRACT_INVALID:%d" % index
                )
            _required(item.get("kind"), "observation_kind")
            _required(item.get("summary"), "observation_summary")
        verification_plan = candidate.get("verification_plan")
        if not isinstance(verification_plan, list) or not verification_plan or not all(
            isinstance(item, str) and item.strip() for item in verification_plan
        ):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_VERIFICATION_PLAN_REQUIRED"
            )
        for field in ("unknowns", "gaps"):
            value = candidate.get(field)
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise N5DataDiscoveryHandoffError(
                    "RC72_N5_DISCOVERY_HANDOFF_CANDIDATE_%s_INVALID" % field.upper()
                )
        return dict(candidate)

    def _handoff_events(
        self, mission_id: str, runtime_assignment_id: str
    ) -> List[Dict[str, Any]]:
        return [
            row for row in self.truth.query("agent_runtime_event", mission_id=mission_id)
            if row.get("event_name") == "HANDOFF_RETURNED"
            and row.get("assignment_id") == runtime_assignment_id
        ]

    def _assert_fresh_session(
        self, session_id: str, *, attempt_id: str, runtime_assignment_id: str
    ) -> None:
        for row in self.truth.query(_ARTIFACT):
            if row.get("attempt_id") != attempt_id and row.get("dsh_session_id") == session_id:
                raise N5DataDiscoveryHandoffError(
                    "RC72_N5_DISCOVERY_HANDOFF_DSH_SESSION_REUSED"
                )
        for row in self.truth.query("agent_runtime_event"):
            if (
                row.get("event_name") == "HANDOFF_RETURNED"
                and row.get("assignment_id") != runtime_assignment_id
                and row.get("dsh_session_id") == session_id
            ):
                raise N5DataDiscoveryHandoffError(
                    "RC72_N5_DISCOVERY_HANDOFF_DSH_SESSION_REUSED"
                )

    def _candidate_from_raw_evidence(
        self, invocation: WorkerInvocation, assignment: Mapping[str, Any]
    ) -> Dict[str, Any]:
        raw_refs = [
            ref for ref in invocation.evidence_refs
            if isinstance(ref, str) and ref.startswith("file://")
        ]
        if len(raw_refs) != 1:
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_RAW_EVIDENCE_NOT_UNIQUE"
            )
        path = Path(raw_refs[0][len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.launcher.state_root)
        except ValueError as exc:
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_RAW_EVIDENCE_OUTSIDE_STATE_ROOT"
            ) from exc
        if not path.is_file():
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_RAW_EVIDENCE_MISSING"
            )
        events = tuple(
            self.launcher._parse_json_lines(
                path.read_text(encoding="utf-8", errors="replace")
            )
        )
        return self._validate_candidate(self.launcher._final_json(events), assignment)

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        scalars = (
            "release_id", "mission_id", "release_batch_id", "source_commit",
            "assignment_id", "dispatch_id", "mission_node_id", "node_type",
            "stage", "data_requirement_id", "resolution_plan_id",
            "source_case_sha256", "requirement_id", "sst_id", "obligation_id",
            "case_id", "workitem_id", "worker_instance_id", "team_role",
            "agent_id", "assignment_generation", "runtime_assignment_id",
            "dsh_session_id", "candidate_output_ref", "candidate_schema",
            "state", "handoff_status", "process_outcome",
        )
        out = {name: payload.get(name) for name in scalars}
        for name in ("authorized_tools", "required_capabilities", "input_refs"):
            out[name] = list(payload.get(name) or [])
        return out

    def _persist_from_invocation(
        self,
        *,
        assignment: Mapping[str, Any],
        attempt_id: str,
        runtime_assignment_id: str,
        invocation: WorkerInvocation,
        runtime_event: Mapping[str, Any],
        candidate: Mapping[str, Any],
        authority_lease_id: str,
        validate_live_authority: bool,
    ) -> Dict[str, Any]:
        self._validate_candidate(candidate, assignment)
        worker_id = str(assignment["worker_instance_id"])
        mission_id = str(assignment["mission_id"])
        scope_ref = "task:%s" % str(assignment["workitem_id"])
        if (
            invocation.worker_instance_id != worker_id
            or invocation.agent_id != _AGENT_ID
            or invocation.mission_id != mission_id
            or invocation.attempt_id != attempt_id
            or invocation.assignment_id != runtime_assignment_id
            or invocation.scope != scope_ref
            or list(invocation.input_refs) != list(assignment.get("input_refs") or [])
        ):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_RUNTIME_LINEAGE_MISMATCH"
            )
        session_id = _required(invocation.dsh_session_id, "dsh_session_id")
        if not session_id.startswith("session-"):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_DSH_SESSION_INVALID"
            )
        if invocation.result != "PASS" or invocation.exit_code != 0:
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_DSH_PROCESS_NOT_SUCCESSFUL"
            )
        if not invocation.output_refs or not invocation.tool_calls:
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_REAL_OUTPUT_AND_TOOL_REQUIRED"
            )
        observed: List[Dict[str, str]] = []
        for raw in invocation.tool_calls:
            call_ref = _required(raw.get("call_ref"), "tool_call_ref")
            tool_name = _required(raw.get("tool_name"), "tool_name")
            if tool_name not in self.allowed_tools:
                raise N5DataDiscoveryHandoffError(
                    "RC72_N5_DISCOVERY_HANDOFF_UNAUTHORIZED_TOOL:%s" % tool_name
                )
            observed.append({"call_ref": call_ref, "tool_name": tool_name})
        if not any(
            isinstance(ref, str) and ref.startswith("file://")
            for ref in invocation.evidence_refs
        ):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_RAW_RUNTIME_EVIDENCE_REQUIRED"
            )
        if (
            runtime_event.get("worker_instance_id") != worker_id
            or runtime_event.get("mission_id") != mission_id
            or runtime_event.get("attempt_id") != attempt_id
            or runtime_event.get("assignment_id") != runtime_assignment_id
            or runtime_event.get("dsh_session_id") != session_id
            or runtime_event.get("scope") != scope_ref
            or list(runtime_event.get("input_refs") or [])
            != list(assignment.get("input_refs") or [])
        ):
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_RUNTIME_EVENT_LINEAGE_MISMATCH"
            )
        if validate_live_authority:
            authority = self.launcher.authority
            control_session = "control-assignment://%s" % str(assignment["assignment_id"])
            authority.validate_identity(
                worker_id,
                role=_TEAM_ROLE,
                phase=_PHASE,
                generation=int(assignment["assignment_generation"]),
                session_id=control_session,
            )
            authority.validate_lease(
                worker_id,
                authority_lease_id,
                scope_ref=scope_ref,
                allowed_artifact_types=(),
                allowed_tools=self.allowed_tools,
            )
            for item in observed:
                authority.authorize_tool(worker_id, authority_lease_id, item["tool_name"])
        self._assert_fresh_session(
            session_id,
            attempt_id=attempt_id,
            runtime_assignment_id=runtime_assignment_id,
        )
        payload = {
            "attempt_id": attempt_id,
            "release_id": str(assignment["release_id"]),
            "mission_id": mission_id,
            "release_batch_id": str(assignment["release_batch_id"]),
            "source_commit": self.source_commit,
            "assignment_id": str(assignment["assignment_id"]),
            "dispatch_id": str(assignment["dispatch_id"]),
            "mission_node_id": str(assignment["mission_node_id"]),
            "node_type": _NODE_TYPE,
            "stage": _STAGE,
            "data_requirement_id": str(assignment["data_requirement_id"]),
            "resolution_plan_id": str(assignment["resolution_plan_id"]),
            "source_case_sha256": str(assignment["source_case_sha256"]),
            "requirement_id": str(assignment["requirement_id"]),
            "sst_id": str(assignment["sst_id"]),
            "obligation_id": str(assignment["obligation_id"]),
            "case_id": str(assignment["case_id"]),
            "workitem_id": str(assignment["workitem_id"]),
            "worker_instance_id": worker_id,
            "team_role": _TEAM_ROLE,
            "agent_id": _AGENT_ID,
            "assignment_generation": int(assignment["assignment_generation"]),
            "runtime_assignment_id": runtime_assignment_id,
            "authority_lease_id": authority_lease_id,
            "dsh_session_id": session_id,
            "runtime_event_id": _required(runtime_event.get("id"), "runtime_event_id"),
            "candidate_output_ref": str(invocation.output_refs[-1]),
            "candidate_schema": _CANDIDATE_SCHEMA,
            "authorized_tools": list(self.allowed_tools),
            "required_capabilities": list(assignment.get("required_capabilities") or []),
            "input_refs": list(assignment.get("input_refs") or []),
            "observed_tool_calls": observed,
            "runtime_evidence_refs": list(dict.fromkeys(invocation.evidence_refs)),
            "worker_started_at": int(invocation.started_at),
            "worker_finished_at": int(invocation.finished_at),
            "state": _ATTEMPT_STATE,
            "handoff_status": _HANDOFF_STATUS,
            "process_outcome": _PROCESS_OUTCOME,
        }
        existing = self.truth.query(_ARTIFACT, attempt_id=attempt_id)
        if existing:
            if len(existing) != 1 or self._signature(existing[0]) != self._signature(payload):
                raise N5DataDiscoveryHandoffError(
                    "RC72_N5_DISCOVERY_HANDOFF_ATTEMPT_IDENTITY_CONFLICT"
                )
            return existing[0]
        now = _now()
        payload.update({"created_at": now, "updated_at": now, "artifact_version": 1})
        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, attempt_id=attempt_id)
        if len(rows) != 1:
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_ATTEMPT_PERSISTENCE_FAILED"
            )
        return rows[0]

    def _recover_handoff(
        self,
        *,
        assignment: Mapping[str, Any],
        attempt_id: str,
        runtime_assignment_id: str,
        event: Mapping[str, Any],
    ) -> Dict[str, Any]:
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
        candidate = self._candidate_from_raw_evidence(invocation, assignment)
        return self._persist_from_invocation(
            assignment=assignment,
            attempt_id=attempt_id,
            runtime_assignment_id=runtime_assignment_id,
            invocation=invocation,
            runtime_event=event,
            candidate=candidate,
            authority_lease_id=invocation.lease_id,
            validate_live_authority=False,
        )

    def _prompt(self, assignment: Mapping[str, Any], dispatch: Mapping[str, Any]) -> str:
        context = {
            "mission_id": assignment["mission_id"],
            "release_batch_id": assignment["release_batch_id"],
            "mission_node_id": assignment["mission_node_id"],
            "data_requirement_id": assignment["data_requirement_id"],
            "resolution_plan_id": assignment["resolution_plan_id"],
            "requirement_id": assignment["requirement_id"],
            "sst_id": assignment["sst_id"],
            "obligation_id": assignment["obligation_id"],
            "case_id": assignment["case_id"],
            "source_case_sha256": assignment["source_case_sha256"],
            "case_preconditions": list(dispatch.get("case_preconditions") or []),
            "case_code_trace": list(dispatch.get("case_code_trace") or []),
            "workitem_id": assignment["workitem_id"],
            "input_refs": list(assignment.get("input_refs") or []),
            "authorized_tools": list(self.allowed_tools),
        }
        shape = {
            "status": "CANDIDATE",
            "release_batch_id": assignment["release_batch_id"],
            "data_requirement_id": assignment["data_requirement_id"],
            "resolution_plan_id": assignment["resolution_plan_id"],
            "case_id": assignment["case_id"],
            "strategy": "DISCOVER_EXISTING|CONSTRUCT_NEW",
            "observations": [
                {"kind": "REAL_TOOL_OBSERVATION", "summary": "what the real tool observed"}
            ],
            "verification_plan": ["how a later stage must independently verify the candidate"],
            "unknowns": [],
            "gaps": [],
        }
        return (
            "You are the dsh-agent-teams DATA_PREPARER for canonical RC7.2 N5. "
            "Work on exactly one assigned DataRequirement and its immutable Case/Requirement/SST lineage. "
            "You MUST invoke at least one real tool from authorized_tools; prose that merely claims a DB/API/tool check is invalid. "
            "Discover an existing candidate or propose a construction path, but do NOT create or claim canonical data_ref, binding_id, verification, reservation, data_lease_id, N5 PASS, N6 READY, field_verified or BANK_FINAL. "
            "This output is raw candidate material only; later stages hash the raw bytes, verify the observations, promote a resource/binding, and acquire any DataLease. "
            "Return one strict top-level JSON object with exactly RequiredShape keys and no markdown fences. Context="
            + json.dumps(context, ensure_ascii=False, sort_keys=True)
            + " RequiredShape=" + json.dumps(shape, ensure_ascii=False, sort_keys=True)
        )

    def handoff(
        self, *, release_batch_id: str, data_requirement_id: str
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        data_requirement_id = _required(data_requirement_id, "data_requirement_id")
        assignment, dispatch, task = self._preflight(
            release_batch_id, data_requirement_id
        )
        attempt_id = self._attempt_id(str(assignment["assignment_id"]))
        runtime_assignment_id = self._runtime_assignment_id(
            str(assignment["assignment_id"])
        )
        existing = self.truth.query(_ARTIFACT, attempt_id=attempt_id)
        if existing:
            if len(existing) != 1:
                raise N5DataDiscoveryHandoffError(
                    "RC72_N5_DISCOVERY_HANDOFF_ATTEMPT_NOT_UNIQUE"
                )
            row = existing[0]
            if row.get("source_commit") != self.source_commit:
                raise N5DataDiscoveryHandoffError(
                    "RC72_N5_DISCOVERY_HANDOFF_ATTEMPT_SOURCE_COMMIT_MISMATCH"
                )
            if row.get("worker_instance_id") != assignment.get("worker_instance_id"):
                raise N5DataDiscoveryHandoffError(
                    "RC72_N5_DISCOVERY_HANDOFF_ATTEMPT_WORKER_MISMATCH"
                )
            return {
                "status": "RESUMED",
                "attempt_id": attempt_id,
                "data_requirement_id": data_requirement_id,
                "worker_instance_id": row["worker_instance_id"],
                "dsh_session_id": row["dsh_session_id"],
                "candidate_output_ref": row["candidate_output_ref"],
                "attempt_state": row["state"],
                "workitem_state": str(task["state"]),
            }
        recovered = self._handoff_events(
            str(assignment["mission_id"]), runtime_assignment_id
        )
        if len(recovered) > 1:
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_RUNTIME_EVENT_NOT_UNIQUE"
            )
        if recovered:
            row = self._recover_handoff(
                assignment=assignment,
                attempt_id=attempt_id,
                runtime_assignment_id=runtime_assignment_id,
                event=recovered[0],
            )
            return {
                "status": "RECOVERED",
                "attempt_id": attempt_id,
                "data_requirement_id": data_requirement_id,
                "worker_instance_id": row["worker_instance_id"],
                "dsh_session_id": row["dsh_session_id"],
                "candidate_output_ref": row["candidate_output_ref"],
                "attempt_state": row["state"],
                "workitem_state": str(task["state"]),
            }

        authority = self.launcher.authority
        worker_id = str(assignment["worker_instance_id"])
        control_session = "control-assignment://%s" % str(assignment["assignment_id"])
        identity = authority.adopt_identity(
            worker_id=worker_id,
            role=_TEAM_ROLE,
            phase=_PHASE,
            layer=None,
            generation=int(assignment["assignment_generation"]),
            session_id=control_session,
        )
        scope_ref = "task:%s" % str(assignment["workitem_id"])
        authority_lease = authority.issue_lease(
            worker_id,
            scope_ref,
            (),
            self.allowed_tools,
            ttl_seconds=max(self.launcher.timeout_seconds + 120, 300),
        )
        runtime_assignment = WorkerAssignment(
            identity=identity,
            lease=authority_lease,
            worker_instance_id=worker_id,
            agent_id=_AGENT_ID,
            mission_id=str(assignment["mission_id"]),
            attempt_id=attempt_id,
            assignment_id=runtime_assignment_id,
            parent_worker_id=self.launcher.coordinator_instance_id,
            scope=scope_ref,
            input_refs=tuple(assignment.get("input_refs") or []),
            allowed_artifact_types=(),
            allowed_tools=tuple(self.allowed_tools),
        )
        invocation, candidate = self.launcher.execute(
            runtime_assignment, self._prompt(assignment, dispatch)
        )
        self._validate_candidate(candidate, assignment)
        events = self._handoff_events(
            str(assignment["mission_id"]), runtime_assignment_id
        )
        if len(events) != 1:
            raise N5DataDiscoveryHandoffError(
                "RC72_N5_DISCOVERY_HANDOFF_HANDOFF_RETURNED_REQUIRED:%d" % len(events)
            )
        row = self._persist_from_invocation(
            assignment=assignment,
            attempt_id=attempt_id,
            runtime_assignment_id=runtime_assignment_id,
            invocation=invocation,
            runtime_event=events[0],
            candidate=candidate,
            authority_lease_id=authority_lease.lease_id,
            validate_live_authority=True,
        )
        return {
            "status": "SESSION_OBSERVED",
            "attempt_id": attempt_id,
            "data_requirement_id": data_requirement_id,
            "worker_instance_id": row["worker_instance_id"],
            "dsh_session_id": row["dsh_session_id"],
            "candidate_output_ref": row["candidate_output_ref"],
            "attempt_state": row["state"],
            "workitem_state": str(task["state"]),
        }


install_rc72_n5_data_discovery_handoff_overlay()
