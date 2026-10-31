"""RC7.2 N4 per-Requirement x SST assignment -> fresh DSH design Attempt.

Each governed N4 design assignment executes in its own fresh DSH session under
a task-scoped RC7.2 authority lease.  The worker may only propose a strict Test
Design candidate.  Canonical TestObligations/TestCases, independent review,
NodeDelivery, NodeGate and N4 PASS remain downstream responsibilities.

The raw candidate is intentionally richer than the inherited generic design
shape: every case must already carry Requirement/SST identity, L1-L7 layer,
preconditions, data, ordered steps, expected results, Oracle, evidence
requirements, code trace and coverage links.  Missing knowledge belongs in
unknowns/gaps; "TBD" and execution-time guessing are not accepted as design.
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
from .rc72_authority import RC72AuthorityRuntime, TEST_DESIGN_WORKER
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_n4_test_design_assignment import install_rc72_n4_test_design_assignment_overlay
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n4_test_design_attempt"
_EVENT = "RC72_N4_TEST_DESIGN_ATTEMPT_UPSERTED"
_BUCKET = "rc72_n4_test_design_attempts"
_NODE_TYPE = AutonomousMissionNode.N4_TEST_DESIGN.value
_STAGE = "TEST_DESIGN"
_TEAM_ROLE = TEST_DESIGN_WORKER
_AGENT_ID = "test-design"
_PHASE = "MISSION_NODE_EXECUTION"
_ASSIGNMENT_STATUS = "LEASED_FOR_HANDOFF"
_ATTEMPT_STATE = "WORKER_COMPLETED_PENDING_PROMOTION"
_HANDOFF_STATUS = "DSH_SESSION_OBSERVED"
_PROCESS_OUTCOME = "SUCCEEDED"
_CANDIDATE_SCHEMA = "RC72_N4_TEST_DESIGN_CANDIDATE_V1"
_LAYERS = {"L%d" % index for index in range(1, 8)}
_RISKS = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
_KINDS = {
    "REQUIREMENT_ASSERTION", "BUSINESS_RULE", "PRECONDITION",
    "POSITIVE_PATH", "NEGATIVE_PATH", "BOUNDARY", "STATE_TRANSITION",
    "ROLE_PERMISSION", "DATA_CONDITION", "DEPENDENCY", "CODE_IMPACT",
    "SIDE_EFFECT", "REGRESSION", "HIGH_RISK_HYPOTHESIS",
}
_FORBIDDEN_PLACEHOLDERS = {
    "TBD", "TODO", "TO_BE_DEFINED", "GUESS_DURING_EXECUTION",
    "FIND_DATA_LATER", "PLACEHOLDER_ORACLE",
}


class N4TestDesignHandoffError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N4TestDesignHandoffError("RC72_N4_HANDOFF_%s_REQUIRED" % name.upper())
    return value.strip()


def _strings(value: Any, name: str, *, required: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise N4TestDesignHandoffError("RC72_N4_HANDOFF_%s_INVALID" % name.upper())
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_%s_INVALID" % name.upper())
        text = item.strip()
        if text.upper().replace(" ", "_") in _FORBIDDEN_PLACEHOLDERS:
            raise N4TestDesignHandoffError(
                "RC72_N4_HANDOFF_%s_PLACEHOLDER_FORBIDDEN" % name.upper()
            )
        out.append(text)
    if len(out) != len(set(out)):
        raise N4TestDesignHandoffError("RC72_N4_HANDOFF_%s_DUPLICATE" % name.upper())
    if required and not out:
        raise N4TestDesignHandoffError("RC72_N4_HANDOFF_%s_REQUIRED" % name.upper())
    return out


def _tool_calls(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise _contracts.DomainValidationError("RC72_N4_HANDOFF_OBSERVED_TOOL_CALLS_REQUIRED")
    out: List[Dict[str, str]] = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise _contracts.DomainValidationError("RC72_N4_HANDOFF_TOOL_CALL_INVALID")
        call_ref = raw.get("call_ref")
        tool_name = raw.get("tool_name")
        if not isinstance(call_ref, str) or not call_ref.strip():
            raise _contracts.DomainValidationError("RC72_N4_HANDOFF_TOOL_CALL_REF_REQUIRED")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise _contracts.DomainValidationError("RC72_N4_HANDOFF_TOOL_NAME_REQUIRED")
        key = (call_ref.strip(), tool_name.strip())
        if key in seen:
            raise _contracts.DomainValidationError("RC72_N4_HANDOFF_TOOL_CALL_DUPLICATE")
        seen.add(key)
        out.append({"call_ref": key[0], "tool_name": key[1]})
    return out


def validate_rc72_n4_test_design_attempt(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "attempt_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "assignment_id", "dispatch_id", "mission_node_id",
        "node_type", "stage", "requirement_id", "sst_id", "workitem_id",
        "worker_instance_id", "team_role", "agent_id", "runtime_assignment_id",
        "authority_lease_id", "dsh_session_id", "runtime_event_id",
        "candidate_output_ref", "candidate_schema", "state", "handoff_status",
        "process_outcome",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["node_type"] != _NODE_TYPE:
        raise _contracts.DomainValidationError("RC72_N4_HANDOFF_NODE_INVALID")
    if out["stage"] != _STAGE:
        raise _contracts.DomainValidationError("RC72_N4_HANDOFF_STAGE_INVALID")
    if out["team_role"] != _TEAM_ROLE:
        raise _contracts.DomainValidationError("RC72_N4_HANDOFF_TEAM_ROLE_INVALID")
    if out["agent_id"] != _AGENT_ID:
        raise _contracts.DomainValidationError("RC72_N4_HANDOFF_AGENT_ID_INVALID")
    if not out["dsh_session_id"].startswith("session-"):
        raise _contracts.DomainValidationError("RC72_N4_HANDOFF_DSH_SESSION_INVALID")
    if out["candidate_schema"] != _CANDIDATE_SCHEMA:
        raise _contracts.DomainValidationError("RC72_N4_HANDOFF_CANDIDATE_SCHEMA_INVALID")
    if out["state"] != _ATTEMPT_STATE:
        raise _contracts.DomainValidationError("RC72_N4_HANDOFF_ATTEMPT_STATE_INVALID")
    if out["handoff_status"] != _HANDOFF_STATUS:
        raise _contracts.DomainValidationError("RC72_N4_HANDOFF_STATUS_INVALID")
    if out["process_outcome"] != _PROCESS_OUTCOME:
        raise _contracts.DomainValidationError("RC72_N4_HANDOFF_PROCESS_OUTCOME_INVALID")
    out["authorized_tools"] = _strings(out.get("authorized_tools"), "authorized_tools", required=True)
    out["runtime_evidence_refs"] = _strings(
        out.get("runtime_evidence_refs"), "runtime_evidence_refs", required=True
    )
    out["observed_tool_calls"] = _tool_calls(out.get("observed_tool_calls"))
    observed = {item["tool_name"] for item in out["observed_tool_calls"]}
    if not observed.issubset(set(out["authorized_tools"])):
        raise _contracts.DomainValidationError("RC72_N4_HANDOFF_UNAUTHORIZED_TOOL_OBSERVED")
    if not any(str(ref).startswith("file://") for ref in out["runtime_evidence_refs"]):
        raise _contracts.DomainValidationError("RC72_N4_HANDOFF_RAW_RUNTIME_EVIDENCE_REQUIRED")
    for name in ("worker_started_at", "worker_finished_at", "created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError("RC72_N4_HANDOFF_%s_INVALID" % name.upper())
    if out["worker_finished_at"] < out["worker_started_at"]:
        raise _contracts.DomainValidationError("RC72_N4_HANDOFF_TIME_ORDER_INVALID")
    for forbidden in (
        "canonical_test_cases", "canonical_obligations", "node_delivery_id",
        "node_gate", "node_gate_id", "node_pass", "evaluation",
        "evaluation_result", "n4_pass", "n5_ready", "q7_pass",
        "field_verified", "bank_final", "actual_result", "assertion_result",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N4_HANDOFF_BUSINESS_CLAIM_FORBIDDEN:%s" % forbidden
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_N4_HANDOFF_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n4_test_design_handoff_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_n4_test_design_assignment_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n4_test_design_attempt
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "attempt_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "attempt_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


def _require_object_list(value: Any, name: str) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise N4TestDesignHandoffError("RC72_N4_HANDOFF_%s_REQUIRED" % name.upper())
    if not all(isinstance(item, dict) for item in value):
        raise N4TestDesignHandoffError("RC72_N4_HANDOFF_%s_INVALID" % name.upper())
    return [dict(item) for item in value]


def _contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        normalized = value.strip().upper().replace(" ", "_")
        return normalized in _FORBIDDEN_PLACEHOLDERS
    if isinstance(value, list):
        return any(_contains_placeholder(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_placeholder(item) for item in value.values())
    return False


class N4TestDesignDshHandoffService:
    """Run one assigned N4 Requirement x SST design WorkItem in a fresh DSH session."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        source_commit: str,
        launcher: DshHeadlessWorkerLauncher,
        allowed_tools: Sequence[str],
    ) -> None:
        install_rc72_n4_test_design_handoff_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.launcher = launcher
        tools = [str(item).strip() for item in allowed_tools if isinstance(item, str) and item.strip()]
        if not tools or len(set(tools)) != len(tools):
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_ALLOWED_TOOLS_INVALID")
        self.allowed_tools = tuple(tools)
        if not isinstance(self.launcher.authority, RC72AuthorityRuntime):
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_RC72_AUTHORITY_REQUIRED")

    @staticmethod
    def _attempt_id(assignment_id: str) -> str:
        raw = "\x1f".join((assignment_id, "N4_TEST_DESIGN_DSH_ATTEMPT"))
        return "N4ATT-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _runtime_assignment_id(assignment_id: str) -> str:
        raw = "\x1f".join((assignment_id, "N4_DSH_RUNTIME_HANDOFF"))
        return "N4DSH-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N4TestDesignHandoffError(
                "RC72_N4_HANDOFF_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows))
            )
        return rows[0]

    def _preflight(
        self, release_batch_id: str, requirement_id: str, sst_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        exact = [
            row for row in self.truth.query(
                "rc72_n4_test_design_assignment", release_batch_id=release_batch_id
            )
            if row.get("source_commit") == self.source_commit
            and row.get("requirement_id") == requirement_id
            and row.get("sst_id") == sst_id
            and row.get("status") == _ASSIGNMENT_STATUS
            and row.get("node_type") == _NODE_TYPE
            and row.get("stage") == _STAGE
            and row.get("team_role") == _TEAM_ROLE
            and row.get("agent_id") == _AGENT_ID
        ]
        if len(exact) != 1:
            raise N4TestDesignHandoffError(
                "RC72_N4_HANDOFF_EXACT_ASSIGNMENT_REQUIRED:%d" % len(exact)
            )
        assignment = exact[0]
        mission_id = _required(assignment.get("mission_id"), "mission_id")
        release_id = _required(assignment.get("release_id"), "release_id")
        node_id = _required(assignment.get("mission_node_id"), "mission_node_id")
        workitem_id = _required(assignment.get("workitem_id"), "workitem_id")
        worker_id = _required(assignment.get("worker_instance_id"), "worker_instance_id")
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        if (
            batch.get("mission_id") != mission_id
            or batch.get("release_id") != release_id
            or requirement_id not in list(batch.get("requirement_ids") or [])
        ):
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_RELEASE_BATCH_LINEAGE_MISMATCH")
        dispatch = self._one(
            "rc72_n4_test_design_dispatch", dispatch_id=str(assignment["dispatch_id"])
        )
        if (
            dispatch.get("mission_id") != mission_id
            or dispatch.get("release_batch_id") != release_batch_id
            or dispatch.get("mission_node_id") != node_id
            or dispatch.get("requirement_id") != requirement_id
            or dispatch.get("sst_id") != sst_id
            or dispatch.get("workitem_id") != workitem_id
            or dispatch.get("source_commit") != self.source_commit
            or dispatch.get("status") != "READY_FOR_ASSIGNMENT"
        ):
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_DISPATCH_LINEAGE_MISMATCH")
        node = self._one("rc72_mission_node", mission_node_id=node_id)
        if (
            node.get("mission_id") != mission_id
            or node.get("node_type") != _NODE_TYPE
            or node.get("state") != MissionNodeState.RUNNING.value
        ):
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_N4_NOT_RUNNING")
        n5 = self._one(
            "rc72_mission_node",
            mission_id=mission_id,
            node_type=AutonomousMissionNode.N5_TEST_DATA.value,
        )
        if n5.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_N5_ALREADY_RELEASED")
        task = self._one("rc7_task", task_id=workitem_id)
        if (
            task.get("mission_id") != mission_id
            or task.get("node") != _STAGE
            or task.get("state") != "LEASED"
            or task.get("lease_owner") != worker_id
            or set(task.get("input_artifact_refs") or [])
            != set(dispatch.get("parent_artifact_refs") or [])
        ):
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_WORKITEM_LEASE_MISMATCH")
        return assignment, dispatch, task

    def _handoff_events(self, mission_id: str, runtime_assignment_id: str) -> List[Dict[str, Any]]:
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
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_DSH_SESSION_REUSED")
        for row in self.truth.query("agent_runtime_event"):
            if (
                row.get("event_name") == "HANDOFF_RETURNED"
                and row.get("assignment_id") != runtime_assignment_id
                and row.get("dsh_session_id") == session_id
            ):
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_DSH_SESSION_REUSED")

    @staticmethod
    def _validate_candidate(
        candidate: Mapping[str, Any],
        *,
        release_batch_id: str,
        requirement_id: str,
        sst_id: str,
    ) -> Dict[str, Any]:
        if not isinstance(candidate, Mapping):
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_CANDIDATE_OBJECT_REQUIRED")
        if set(candidate.keys()) != {
            "status", "release_batch_id", "requirement_id", "sst_id",
            "obligations", "cases", "unknowns", "gaps",
        }:
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_CANDIDATE_TOP_LEVEL_CONTRACT_INVALID")
        if candidate.get("status") != "CANDIDATE":
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_CANDIDATE_STATUS_INVALID")
        if candidate.get("release_batch_id") != release_batch_id:
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_RELEASE_BATCH_MISMATCH")
        if candidate.get("requirement_id") != requirement_id:
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_REQUIREMENT_MISMATCH")
        if candidate.get("sst_id") != sst_id:
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_SST_MISMATCH")
        unknowns = candidate.get("unknowns")
        gaps = candidate.get("gaps")
        if not isinstance(unknowns, list) or not isinstance(gaps, list):
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_UNKNOWN_GAP_LIST_REQUIRED")
        if _contains_placeholder(candidate):
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_PLACEHOLDER_FORBIDDEN")

        obligations = _require_object_list(candidate.get("obligations"), "obligations")
        obligation_ids = set()
        obligation_layer: Dict[str, str] = {}
        for index, item in enumerate(obligations):
            required_keys = {
                "obligation_id", "requirement_id", "sst_id", "kind",
                "business_scope", "change_slice", "risk", "layer",
                "oracle_types", "evidence_refs", "required",
            }
            if set(item.keys()) != required_keys:
                raise N4TestDesignHandoffError(
                    "RC72_N4_HANDOFF_OBLIGATION_CONTRACT_INVALID:%d" % index
                )
            obligation_id = _required(item.get("obligation_id"), "obligation_id")
            if obligation_id in obligation_ids:
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_OBLIGATION_ID_DUPLICATE")
            obligation_ids.add(obligation_id)
            if item.get("requirement_id") != requirement_id or item.get("sst_id") != sst_id:
                raise N4TestDesignHandoffError(
                    "RC72_N4_HANDOFF_OBLIGATION_SCOPE_MISMATCH:%s" % obligation_id
                )
            kind = _required(item.get("kind"), "obligation_kind").upper()
            layer = _required(item.get("layer"), "obligation_layer").upper()
            risk = _required(item.get("risk"), "obligation_risk").upper()
            if kind not in _KINDS:
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_OBLIGATION_KIND_INVALID:%s" % kind)
            if layer not in _LAYERS:
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_OBLIGATION_LAYER_INVALID:%s" % layer)
            if risk not in _RISKS:
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_OBLIGATION_RISK_INVALID:%s" % risk)
            _required(item.get("business_scope"), "business_scope")
            _required(item.get("change_slice"), "change_slice")
            _strings(item.get("oracle_types"), "oracle_types", required=True)
            _strings(item.get("evidence_refs"), "evidence_refs", required=True)
            if not isinstance(item.get("required"), bool):
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_OBLIGATION_REQUIRED_FLAG_INVALID")
            obligation_layer[obligation_id] = layer

        cases = _require_object_list(candidate.get("cases"), "cases")
        case_ids = set()
        covered = set()
        for index, item in enumerate(cases):
            required_keys = {
                "tc_id", "release_batch_id", "requirement_id", "sst_id",
                "obligation_id", "layer", "risk", "preconditions",
                "data_requirements", "steps", "expected_results", "oracle",
                "evidence_requirements", "code_trace", "action_semantics",
                "coverage_links", "status",
            }
            if set(item.keys()) != required_keys:
                raise N4TestDesignHandoffError(
                    "RC72_N4_HANDOFF_CASE_CONTRACT_INVALID:%d" % index
                )
            tc_id = _required(item.get("tc_id"), "tc_id")
            if tc_id in case_ids:
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_CASE_ID_DUPLICATE")
            case_ids.add(tc_id)
            if (
                item.get("release_batch_id") != release_batch_id
                or item.get("requirement_id") != requirement_id
                or item.get("sst_id") != sst_id
            ):
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_CASE_SCOPE_MISMATCH:%s" % tc_id)
            primary_obligation = _required(item.get("obligation_id"), "case_obligation_id")
            if primary_obligation not in obligation_ids:
                raise N4TestDesignHandoffError(
                    "RC72_N4_HANDOFF_CASE_OBLIGATION_UNKNOWN:%s" % primary_obligation
                )
            layer = _required(item.get("layer"), "case_layer").upper()
            risk = _required(item.get("risk"), "case_risk").upper()
            if layer not in _LAYERS or risk not in _RISKS:
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_CASE_LAYER_RISK_INVALID:%s" % tc_id)
            if obligation_layer[primary_obligation] != layer:
                raise N4TestDesignHandoffError(
                    "RC72_N4_HANDOFF_CASE_PRIMARY_OBLIGATION_LAYER_MISMATCH:%s" % tc_id
                )
            _strings(item.get("preconditions"), "preconditions", required=True)
            _strings(item.get("data_requirements"), "data_requirements", required=True)
            _strings(item.get("steps"), "steps", required=True)
            _strings(item.get("expected_results"), "expected_results", required=True)
            _strings(item.get("evidence_requirements"), "evidence_requirements", required=True)
            _strings(item.get("code_trace"), "code_trace", required=True)
            if str(item.get("status") or "").upper() != "CANDIDATE":
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_CASE_STATUS_INVALID:%s" % tc_id)
            action = item.get("action_semantics")
            if not isinstance(action, dict) or set(action.keys()) != {
                "state_changing", "negative", "authorization_sensitive"
            } or not all(isinstance(action[key], bool) for key in action):
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_ACTION_SEMANTICS_INVALID:%s" % tc_id)
            oracle = item.get("oracle")
            if not isinstance(oracle, dict) or set(oracle.keys()) != {"checks"}:
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_ORACLE_INVALID:%s" % tc_id)
            checks = _require_object_list(oracle.get("checks"), "oracle_checks")
            for check in checks:
                if set(check.keys()) != {"type", "evidence_ref"}:
                    raise N4TestDesignHandoffError("RC72_N4_HANDOFF_ORACLE_CHECK_CONTRACT_INVALID:%s" % tc_id)
                _required(check.get("type"), "oracle_type")
                _required(check.get("evidence_ref"), "oracle_evidence_ref")
            links = _require_object_list(item.get("coverage_links"), "coverage_links")
            link_ids = set()
            for link in links:
                if set(link.keys()) != {"subject_id", "evidence_ref"}:
                    raise N4TestDesignHandoffError("RC72_N4_HANDOFF_COVERAGE_LINK_CONTRACT_INVALID:%s" % tc_id)
                subject_id = _required(link.get("subject_id"), "coverage_subject_id")
                _required(link.get("evidence_ref"), "coverage_evidence_ref")
                if subject_id not in obligation_ids:
                    raise N4TestDesignHandoffError(
                        "RC72_N4_HANDOFF_COVERAGE_SUBJECT_UNKNOWN:%s" % subject_id
                    )
                if obligation_layer[subject_id] != layer:
                    raise N4TestDesignHandoffError(
                        "RC72_N4_HANDOFF_COVERAGE_LAYER_MISMATCH:%s:%s" % (tc_id, subject_id)
                    )
                if subject_id in link_ids:
                    raise N4TestDesignHandoffError(
                        "RC72_N4_HANDOFF_COVERAGE_SUBJECT_DUPLICATE:%s:%s" % (tc_id, subject_id)
                    )
                link_ids.add(subject_id)
                covered.add(subject_id)
            if primary_obligation not in link_ids:
                raise N4TestDesignHandoffError(
                    "RC72_N4_HANDOFF_PRIMARY_OBLIGATION_NOT_LINKED:%s" % tc_id
                )
        # Handoff must not silently return a happy-path-only partial set while
        # pretending there are no gaps.  If any required obligation is not yet
        # represented by a case, it must be explicit as a design gap.
        required_ids = {
            item["obligation_id"] for item in obligations if item.get("required") is True
        }
        if required_ids.difference(covered) and not gaps:
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_UNCOVERED_OBLIGATION_GAP_REQUIRED")
        return dict(candidate)

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        keys = (
            "release_id", "mission_id", "release_batch_id", "source_commit",
            "assignment_id", "dispatch_id", "mission_node_id", "node_type",
            "stage", "requirement_id", "sst_id", "workitem_id",
            "worker_instance_id", "team_role", "agent_id", "runtime_assignment_id",
            "dsh_session_id", "candidate_output_ref", "candidate_schema", "state",
            "handoff_status", "process_outcome",
        )
        result = {key: payload.get(key) for key in keys}
        result["authorized_tools"] = list(payload.get("authorized_tools") or [])
        return result

    def _candidate_from_raw_evidence(
        self,
        invocation: WorkerInvocation,
        *,
        release_batch_id: str,
        requirement_id: str,
        sst_id: str,
    ) -> Dict[str, Any]:
        raw_refs = [
            ref for ref in invocation.evidence_refs
            if isinstance(ref, str) and ref.startswith("file://")
        ]
        if len(raw_refs) != 1:
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_RECOVERY_RAW_EVIDENCE_NOT_UNIQUE")
        path = Path(raw_refs[0][len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.launcher.state_root)
        except ValueError as exc:
            raise N4TestDesignHandoffError(
                "RC72_N4_HANDOFF_RECOVERY_RAW_EVIDENCE_OUTSIDE_STATE_ROOT"
            ) from exc
        if not path.is_file():
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_RECOVERY_RAW_EVIDENCE_MISSING")
        text = path.read_text(encoding="utf-8", errors="replace")
        events = tuple(self.launcher._parse_json_lines(text))
        candidate = self.launcher._final_json(events)
        return self._validate_candidate(
            candidate,
            release_batch_id=release_batch_id,
            requirement_id=requirement_id,
            sst_id=sst_id,
        )

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
        worker_id = str(assignment["worker_instance_id"])
        mission_id = str(assignment["mission_id"])
        requirement_id = str(assignment["requirement_id"])
        sst_id = str(assignment["sst_id"])
        self._validate_candidate(
            candidate,
            release_batch_id=str(assignment["release_batch_id"]),
            requirement_id=requirement_id,
            sst_id=sst_id,
        )
        if invocation.worker_instance_id != worker_id or invocation.mission_id != mission_id:
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_RUNTIME_IDENTITY_MISMATCH")
        if invocation.attempt_id != attempt_id or invocation.assignment_id != runtime_assignment_id:
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_RUNTIME_ATTEMPT_MISMATCH")
        session_id = _required(invocation.dsh_session_id, "dsh_session_id")
        if not session_id.startswith("session-"):
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_DSH_SESSION_INVALID")
        if invocation.result != "PASS" or invocation.exit_code != 0:
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_DSH_PROCESS_NOT_SUCCESSFUL")
        if not invocation.output_refs:
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_CANDIDATE_OUTPUT_REQUIRED")
        if not invocation.tool_calls:
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_TOOL_CALL_REQUIRED")
        observed = []
        for raw in invocation.tool_calls:
            call_ref = _required(raw.get("call_ref"), "tool_call_ref")
            tool_name = _required(raw.get("tool_name"), "tool_name")
            if tool_name not in self.allowed_tools:
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_UNAUTHORIZED_TOOL:%s" % tool_name)
            observed.append({"call_ref": call_ref, "tool_name": tool_name})
        scope_ref = "task:%s" % str(assignment["workitem_id"])
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
            "requirement_id": requirement_id,
            "sst_id": sst_id,
            "workitem_id": str(assignment["workitem_id"]),
            "worker_instance_id": worker_id,
            "team_role": _TEAM_ROLE,
            "agent_id": _AGENT_ID,
            "runtime_assignment_id": runtime_assignment_id,
            "authority_lease_id": authority_lease_id,
            "dsh_session_id": session_id,
            "runtime_event_id": _required(runtime_event.get("id"), "runtime_event_id"),
            "candidate_output_ref": str(invocation.output_refs[-1]),
            "candidate_schema": _CANDIDATE_SCHEMA,
            "authorized_tools": list(self.allowed_tools),
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
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_ATTEMPT_IDENTITY_CONFLICT")
            return existing[0]
        now = _now()
        payload.update({"created_at": now, "updated_at": now, "artifact_version": 1})
        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, attempt_id=attempt_id)
        if len(rows) != 1:
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_ATTEMPT_PERSISTENCE_FAILED")
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
        candidate = self._candidate_from_raw_evidence(
            invocation,
            release_batch_id=str(assignment["release_batch_id"]),
            requirement_id=str(assignment["requirement_id"]),
            sst_id=str(assignment["sst_id"]),
        )
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
        requirement_id = str(assignment["requirement_id"])
        sst_id = str(assignment["sst_id"])
        context = {
            "mission_id": assignment["mission_id"],
            "release_batch_id": assignment["release_batch_id"],
            "mission_node_id": assignment["mission_node_id"],
            "requirement_id": requirement_id,
            "sst_id": sst_id,
            "workitem_id": assignment["workitem_id"],
            "parent_artifact_refs": list(dispatch.get("parent_artifact_refs") or []),
            "parent_obligation_source_refs": list(dispatch.get("parent_obligation_source_refs") or []),
            "authorized_tools": list(self.allowed_tools),
        }
        schema = {
            "status": "CANDIDATE",
            "release_batch_id": assignment["release_batch_id"],
            "requirement_id": requirement_id,
            "sst_id": sst_id,
            "obligations": [{
                "obligation_id": "stable id",
                "requirement_id": requirement_id,
                "sst_id": sst_id,
                "kind": "parent-derived obligation kind",
                "business_scope": "specific rule/scenario",
                "change_slice": "specific impacted change or regression slice",
                "risk": "CRITICAL|HIGH|MEDIUM|LOW",
                "layer": "L1|L2|L3|L4|L5|L6|L7",
                "oracle_types": ["required concrete oracle types"],
                "evidence_refs": ["real tool/source refs"],
                "required": True,
            }],
            "cases": [{
                "tc_id": "stable id",
                "release_batch_id": assignment["release_batch_id"],
                "requirement_id": requirement_id,
                "sst_id": sst_id,
                "obligation_id": "primary obligation id",
                "layer": "L1|L2|L3|L4|L5|L6|L7",
                "risk": "CRITICAL|HIGH|MEDIUM|LOW",
                "preconditions": ["concrete prerequisite"],
                "data_requirements": ["concrete data requirement"],
                "steps": ["ordered executable step"],
                "expected_results": ["observable expected result"],
                "oracle": {"checks": [{"type": "concrete oracle type", "evidence_ref": "real evidence ref"}]},
                "evidence_requirements": ["evidence to collect during execution"],
                "code_trace": ["changed symbol/file/source trace"],
                "action_semantics": {"state_changing": False, "negative": False, "authorization_sensitive": False},
                "coverage_links": [{"subject_id": "obligation id", "evidence_ref": "real evidence ref"}],
                "status": "CANDIDATE",
            }],
            "unknowns": [],
            "gaps": [],
        }
        return (
            "You are the dsh-agent-teams TEST_DESIGN_WORKER for canonical RC7.2 N4. "
            "Design exactly one Requirement x SST scope. Derive the denominator from the provided PASS N2/N3 parent artifacts and parent_obligation_source_refs; never replace it with a self-authored smaller scope or case count target. "
            "Use real source reads and CodeGraph where code impact exists. Cover positive, negative, boundary, state, role/permission, data, dependency, side effect, change impact, regression and integration risks where applicable. "
            "L1-L7 applicability must be explicit through obligations/cases; when evidence is insufficient, record unknowns/gaps instead of inventing a case. "
            "No TBD, TODO, guess during execution, find data later, placeholder oracle, PASS, NodeGate, N5 READY, Q7 PASS, field_verified or BANK_FINAL. "
            "Return strict JSON with exactly the shown top-level and nested contracts. Context="
            + json.dumps(context, ensure_ascii=False, sort_keys=True)
            + " RequiredShape=" + json.dumps(schema, ensure_ascii=False, sort_keys=True)
        )

    def handoff(
        self, *, release_batch_id: str, requirement_id: str, sst_id: str
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        requirement_id = _required(requirement_id, "requirement_id")
        sst_id = _required(sst_id, "sst_id")
        assignment, dispatch, task = self._preflight(release_batch_id, requirement_id, sst_id)
        attempt_id = self._attempt_id(str(assignment["assignment_id"]))
        runtime_assignment_id = self._runtime_assignment_id(str(assignment["assignment_id"]))
        existing = self.truth.query(_ARTIFACT, attempt_id=attempt_id)
        if existing:
            if len(existing) != 1:
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_ATTEMPT_NOT_UNIQUE")
            row = existing[0]
            if row.get("source_commit") != self.source_commit:
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_ATTEMPT_SOURCE_COMMIT_MISMATCH")
            if row.get("worker_instance_id") != assignment.get("worker_instance_id"):
                raise N4TestDesignHandoffError("RC72_N4_HANDOFF_ATTEMPT_WORKER_MISMATCH")
            return {
                "status": "RESUMED", "attempt_id": attempt_id,
                "requirement_id": requirement_id, "sst_id": sst_id,
                "worker_instance_id": row["worker_instance_id"],
                "dsh_session_id": row["dsh_session_id"],
                "candidate_output_ref": row["candidate_output_ref"],
                "attempt_state": row["state"], "workitem_state": str(task["state"]),
            }
        recovered = self._handoff_events(str(assignment["mission_id"]), runtime_assignment_id)
        if len(recovered) > 1:
            raise N4TestDesignHandoffError("RC72_N4_HANDOFF_RUNTIME_EVENT_NOT_UNIQUE")
        if recovered:
            row = self._recover_handoff(
                assignment=assignment, attempt_id=attempt_id,
                runtime_assignment_id=runtime_assignment_id, event=recovered[0],
            )
            return {
                "status": "RECOVERED", "attempt_id": attempt_id,
                "requirement_id": requirement_id, "sst_id": sst_id,
                "worker_instance_id": row["worker_instance_id"],
                "dsh_session_id": row["dsh_session_id"],
                "candidate_output_ref": row["candidate_output_ref"],
                "attempt_state": row["state"], "workitem_state": str(task["state"]),
            }
        authority = self.launcher.authority
        worker_id = str(assignment["worker_instance_id"])
        control_session = "control-assignment://%s" % str(assignment["assignment_id"])
        identity = authority.adopt_identity(
            worker_id=worker_id, role=_TEAM_ROLE, phase=_PHASE, layer=None,
            generation=int(assignment["assignment_generation"]), session_id=control_session,
        )
        scope_ref = "task:%s" % str(assignment["workitem_id"])
        authority_lease = authority.issue_lease(
            worker_id, scope_ref, (), self.allowed_tools,
            ttl_seconds=max(self.launcher.timeout_seconds + 120, 300),
        )
        runtime_assignment = WorkerAssignment(
            identity=identity, lease=authority_lease, worker_instance_id=worker_id,
            agent_id=_AGENT_ID, mission_id=str(assignment["mission_id"]),
            attempt_id=attempt_id, assignment_id=runtime_assignment_id,
            parent_worker_id=self.launcher.coordinator_instance_id, scope=scope_ref,
            input_refs=tuple(assignment.get("input_refs") or []),
            allowed_artifact_types=(), allowed_tools=tuple(self.allowed_tools),
        )
        invocation, candidate = self.launcher.execute(
            runtime_assignment, self._prompt(assignment, dispatch)
        )
        self._validate_candidate(
            candidate, release_batch_id=release_batch_id,
            requirement_id=requirement_id, sst_id=sst_id,
        )
        events = self._handoff_events(str(assignment["mission_id"]), runtime_assignment_id)
        if len(events) != 1:
            raise N4TestDesignHandoffError(
                "RC72_N4_HANDOFF_HANDOFF_RETURNED_REQUIRED:%d" % len(events)
            )
        row = self._persist_from_invocation(
            assignment=assignment, attempt_id=attempt_id,
            runtime_assignment_id=runtime_assignment_id, invocation=invocation,
            runtime_event=events[0], candidate=candidate,
            authority_lease_id=authority_lease.lease_id, validate_live_authority=True,
        )
        return {
            "status": "SESSION_OBSERVED", "attempt_id": attempt_id,
            "requirement_id": requirement_id, "sst_id": sst_id,
            "worker_instance_id": row["worker_instance_id"],
            "dsh_session_id": row["dsh_session_id"],
            "candidate_output_ref": row["candidate_output_ref"],
            "attempt_state": row["state"], "workitem_state": str(task["state"]),
        }


install_rc72_n4_test_design_handoff_overlay()

__all__ = [
    "N4TestDesignDshHandoffService",
    "N4TestDesignHandoffError",
    "install_rc72_n4_test_design_handoff_overlay",
    "validate_rc72_n4_test_design_attempt",
]
