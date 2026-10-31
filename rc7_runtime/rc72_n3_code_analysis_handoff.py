"""RC7.2 N3 CODE_ANALYSIS assignment -> real DSH analyzer Attempt bridge.

The bridge adopts the already-governed per-target AgentTeams worker, issues one
task-scoped authority lease, launches a fresh DSH session, and persists only
observed execution lineage plus the raw analyzer candidate reference.

Repository and revision are immutable accepted source-mapping inputs. They are
never inferred by the analyzer. A successful process is not a code-analysis
PASS: candidate promotion, independent review, deterministic sufficiency, N3
NodeGate, N4 release, Q7/field/BANK_FINAL remain downstream responsibilities.
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
from .rc72_authority import CODE_ANALYSIS_WORKER, RC72AuthorityRuntime
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_n3_code_analysis_assignment import install_rc72_n3_code_analysis_assignment_overlay
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n3_code_analysis_attempt"
_EVENT = "RC72_N3_CODE_ANALYSIS_ATTEMPT_UPSERTED"
_BUCKET = "rc72_n3_code_analysis_attempts"
_NODE_TYPE = AutonomousMissionNode.N3_CODE_ANALYSIS.value
_NEXT_NODE = AutonomousMissionNode.N4_TEST_DESIGN.value
_STAGE = "CODE_ANALYSIS"
_TEAM_ROLE = CODE_ANALYSIS_WORKER
_AGENT_ID = "code-analysis"
_PHASE = "MISSION_NODE_EXECUTION"
_ASSIGNMENT_STATUS = "LEASED_FOR_HANDOFF"
_ATTEMPT_STATE = "WORKER_COMPLETED_PENDING_PROMOTION"
_HANDOFF_STATUS = "DSH_SESSION_OBSERVED"
_PROCESS_OUTCOME = "SUCCEEDED"
_CANDIDATE_SCHEMA = "RC72_N3_CODE_ANALYSIS_CANDIDATE_V1"
_REQUIRED_TOOLS = ("git", "codegraph")


class N3CodeAnalysisHandoffError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_HANDOFF_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _strings(value: Any, name: str, *, required: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_%s_INVALID" % name.upper()
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_%s_INVALID" % name.upper()
        )
    out = [item.strip() for item in value]
    if len(set(out)) != len(out):
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_%s_DUPLICATE" % name.upper()
        )
    if required and not out:
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_%s_REQUIRED" % name.upper()
        )
    return out


def _tool_calls(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_OBSERVED_TOOL_CALLS_REQUIRED"
        )
    out: List[Dict[str, str]] = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise _contracts.DomainValidationError(
                "RC72_N3_CODE_HANDOFF_TOOL_CALL_INVALID"
            )
        call_ref = _required(raw.get("call_ref"), "tool_call_ref")
        tool_name = _required(raw.get("tool_name"), "tool_name")
        key = (call_ref, tool_name)
        if key in seen:
            raise _contracts.DomainValidationError(
                "RC72_N3_CODE_HANDOFF_TOOL_CALL_DUPLICATE"
            )
        seen.add(key)
        out.append({"call_ref": call_ref, "tool_name": tool_name})
    return out


def validate_rc72_n3_code_analysis_attempt(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "attempt_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "assignment_id", "dispatch_id", "mission_node_id",
        "node_type", "stage", "application_id", "target_id", "repository_ref",
        "source_revision", "source_mapping_task_id", "source_mapping_artifact_id",
        "source_mapping_evaluation_id", "workitem_id", "worker_instance_id",
        "team_role", "agent_id", "runtime_assignment_id", "authority_lease_id",
        "dsh_session_id", "runtime_event_id", "candidate_output_ref",
        "candidate_schema", "state", "handoff_status", "process_outcome",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["node_type"] != _NODE_TYPE or out["stage"] != _STAGE:
        raise _contracts.DomainValidationError("RC72_N3_CODE_HANDOFF_NODE_INVALID")
    if out["team_role"] != _TEAM_ROLE or out["agent_id"] != _AGENT_ID:
        raise _contracts.DomainValidationError("RC72_N3_CODE_HANDOFF_ROLE_INVALID")
    if not out["repository_ref"].startswith("git://"):
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_REPOSITORY_REF_INVALID"
        )
    if not out["dsh_session_id"].startswith("session-"):
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_DSH_SESSION_INVALID"
        )
    if out["candidate_schema"] != _CANDIDATE_SCHEMA:
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_CANDIDATE_SCHEMA_INVALID"
        )
    if out["state"] != _ATTEMPT_STATE:
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_ATTEMPT_STATE_INVALID"
        )
    if out["handoff_status"] != _HANDOFF_STATUS:
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_STATUS_INVALID"
        )
    if out["process_outcome"] != _PROCESS_OUTCOME:
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_PROCESS_OUTCOME_INVALID"
        )
    generation = out.get("assignment_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation != 1:
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_ASSIGNMENT_GENERATION_INVALID"
        )
    out["assignment_generation"] = generation
    mapping_generation = out.get("source_mapping_generation")
    if (
        isinstance(mapping_generation, bool)
        or not isinstance(mapping_generation, int)
        or mapping_generation < 1
    ):
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_MAPPING_GENERATION_INVALID"
        )
    out["source_mapping_generation"] = mapping_generation
    out["authorized_tools"] = _strings(
        out.get("authorized_tools"), "authorized_tools", required=True
    )
    if tuple(out["authorized_tools"]) != _REQUIRED_TOOLS:
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_AUTHORIZED_TOOLS_INVALID"
        )
    out["runtime_evidence_refs"] = _strings(
        out.get("runtime_evidence_refs"), "runtime_evidence_refs", required=True
    )
    out["source_evidence_refs"] = _strings(
        out.get("source_evidence_refs"), "source_evidence_refs", required=True
    )
    out["canonical_evidence_ids"] = _strings(
        out.get("canonical_evidence_ids"), "canonical_evidence_ids", required=True
    )
    out["source_mapping_evidence_refs"] = _strings(
        out.get("source_mapping_evidence_refs"),
        "source_mapping_evidence_refs",
        required=True,
    )
    out["observed_tool_calls"] = _tool_calls(out.get("observed_tool_calls"))
    observed = {item["tool_name"] for item in out["observed_tool_calls"]}
    if not observed.issubset(set(out["authorized_tools"])):
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_UNAUTHORIZED_TOOL_OBSERVED"
        )
    if "git" not in observed:
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_REAL_GIT_CALL_REQUIRED"
        )
    if not any(
        str(ref).startswith("file://") for ref in out["runtime_evidence_refs"]
    ):
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_RAW_RUNTIME_EVIDENCE_REQUIRED"
        )
    for name in ("worker_started_at", "worker_finished_at", "created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N3_CODE_HANDOFF_%s_INVALID" % name.upper()
            )
    if out["worker_finished_at"] < out["worker_started_at"]:
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_TIME_ORDER_INVALID"
        )
    for forbidden in (
        "semantic_payload", "analysis_id", "graph_evidence", "git_result",
        "codegraph_result", "evaluation", "evaluation_id", "review",
        "review_decision", "code_analysis_pass", "node_delivery_id", "node_gate",
        "node_pass", "n4_started", "q7_pass", "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N3_CODE_HANDOFF_ACCEPTANCE_CLAIM_FORBIDDEN:%s" % forbidden
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_HANDOFF_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n3_code_analysis_handoff_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_n3_code_analysis_assignment_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n3_code_analysis_attempt
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


class N3CodeAnalysisDshHandoffService:
    """Launch one accepted per-target CODE_ANALYSIS assignment in fresh DSH."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        source_commit: str,
        launcher: DshHeadlessWorkerLauncher,
    ) -> None:
        install_rc72_n3_code_analysis_handoff_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.launcher = launcher
        self.allowed_tools = _REQUIRED_TOOLS
        if not isinstance(self.launcher.authority, RC72AuthorityRuntime):
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_RC72_AUTHORITY_REQUIRED"
            )

    @staticmethod
    def _attempt_id(assignment_id: str) -> str:
        raw = "\x1f".join((assignment_id, "N3_CODE_ANALYSIS_DSH_ATTEMPT"))
        return "N3CODEATT-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _runtime_assignment_id(assignment_id: str) -> str:
        raw = "\x1f".join((assignment_id, "N3_CODE_ANALYSIS_DSH_HANDOFF"))
        return "N3CODEDSH-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _preflight(
        self, release_batch_id: str, target_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        assignments = self.truth.query(
            "rc72_n3_code_analysis_assignment",
            release_batch_id=release_batch_id,
        )
        exact = [
            row for row in assignments
            if row.get("source_commit") == self.source_commit
            and row.get("target_id") == target_id
            and row.get("status") == _ASSIGNMENT_STATUS
            and row.get("node_type") == _NODE_TYPE
            and row.get("stage") == _STAGE
            and row.get("team_role") == _TEAM_ROLE
            and row.get("agent_id") == _AGENT_ID
        ]
        if len(exact) != 1:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_EXACT_ASSIGNMENT_REQUIRED:%d" % len(exact)
            )
        assignment = exact[0]
        mission_id = _required(assignment.get("mission_id"), "mission_id")
        release_id = _required(assignment.get("release_id"), "release_id")
        node_id = _required(assignment.get("mission_node_id"), "mission_node_id")
        workitem_id = _required(assignment.get("workitem_id"), "workitem_id")
        worker_id = _required(
            assignment.get("worker_instance_id"), "worker_instance_id"
        )
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        if (
            batch.get("mission_id") != mission_id
            or batch.get("release_id") != release_id
            or str(assignment.get("application_id")) not in list(
                batch.get("application_ids") or []
            )
        ):
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_RELEASE_BATCH_LINEAGE_MISMATCH"
            )
        dispatch = self._one(
            "rc72_n3_code_analysis_dispatch",
            dispatch_id=str(assignment["dispatch_id"]),
        )
        immutable = (
            "mission_id", "release_batch_id", "mission_node_id", "application_id",
            "target_id", "repository_ref", "source_revision",
            "source_mapping_generation", "source_mapping_task_id",
            "source_mapping_artifact_id", "source_mapping_evaluation_id",
            "workitem_id", "source_commit",
        )
        for field in immutable:
            if dispatch.get(field) != assignment.get(field):
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_HANDOFF_DISPATCH_LINEAGE_MISMATCH:%s" % field
                )
        node = self._one("rc72_mission_node", mission_node_id=node_id)
        if (
            node.get("mission_id") != mission_id
            or node.get("node_type") != _NODE_TYPE
            or node.get("state") != MissionNodeState.RUNNING.value
        ):
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_N3_NOT_RUNNING"
            )
        n4 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE
        )
        if n4.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_N4_ALREADY_RELEASED"
            )
        task = self._one("rc7_task", task_id=workitem_id)
        if (
            task.get("mission_id") != mission_id
            or task.get("node") != _STAGE
            or task.get("state") != "LEASED"
            or task.get("lease_owner") != worker_id
        ):
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_WORKITEM_LEASE_MISMATCH"
            )
        if list(task.get("required_capabilities") or []) != [
            "code_reasoning", "code_reality"
        ]:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_WORKITEM_CAPABILITIES_MISMATCH"
            )
        return assignment, dispatch, task

    @staticmethod
    def _validate_candidate(
        candidate: Mapping[str, Any], assignment: Mapping[str, Any]
    ) -> Dict[str, Any]:
        if not isinstance(candidate, Mapping):
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_CANDIDATE_OBJECT_REQUIRED"
            )
        expected_keys = {
            "status", "application_id", "target_id", "repository_ref",
            "source_revision", "requirement_ids", "source_revisions",
            "changed_files", "changed_symbols", "symbol_explanations",
            "reverse_requirement_mappings", "evidence_refs",
            "codegraph_required", "unknowns", "gaps",
        }
        if set(candidate.keys()) != expected_keys:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_CANDIDATE_TOP_LEVEL_CONTRACT_INVALID"
            )
        if candidate.get("status") != "CANDIDATE":
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_CANDIDATE_STATUS_INVALID"
            )
        for field in (
            "application_id", "target_id", "repository_ref", "source_revision"
        ):
            if candidate.get(field) != assignment.get(field):
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_HANDOFF_CANDIDATE_%s_MISMATCH" % field.upper()
                )
        if not str(candidate["repository_ref"]).startswith("git://"):
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_CANDIDATE_REPOSITORY_REF_INVALID"
            )
        collection_fields = (
            "requirement_ids", "source_revisions", "changed_files",
            "changed_symbols", "symbol_explanations",
            "reverse_requirement_mappings", "evidence_refs", "unknowns", "gaps",
        )
        for field in collection_fields:
            if not isinstance(candidate.get(field), list):
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_HANDOFF_CANDIDATE_%s_INVALID" % field.upper()
                )
        if candidate["source_revisions"] != [assignment["source_revision"]]:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_CANDIDATE_SOURCE_REVISIONS_MISMATCH"
            )
        if not all(
            isinstance(value, str) and value.strip()
            for value in candidate["requirement_ids"]
        ):
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_CANDIDATE_REQUIREMENT_IDS_INVALID"
            )
        if not all(
            isinstance(value, str) and value.strip()
            for value in candidate["changed_files"]
        ):
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_CANDIDATE_CHANGED_FILES_INVALID"
            )
        if not all(
            isinstance(value, str) and value.strip()
            for value in candidate["changed_symbols"]
        ):
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_CANDIDATE_CHANGED_SYMBOLS_INVALID"
            )
        if not isinstance(candidate.get("codegraph_required"), bool):
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_CANDIDATE_CODEGRAPH_REQUIRED_INVALID"
            )
        java_changed = any(
            str(path).lower().endswith(".java") for path in candidate["changed_files"]
        )
        if java_changed and candidate["codegraph_required"] is not True:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_JAVA_MUST_REQUIRE_CODEGRAPH"
            )
        if not candidate["evidence_refs"] or not all(
            isinstance(ref, str) and ref.strip() for ref in candidate["evidence_refs"]
        ):
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_CANDIDATE_EVIDENCE_REQUIRED"
            )
        for item in candidate["symbol_explanations"]:
            if not isinstance(item, Mapping):
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_HANDOFF_SYMBOL_EXPLANATION_INVALID"
                )
            refs = item.get("evidence_refs")
            if not isinstance(refs, list) or not refs or not all(
                isinstance(ref, str) and ref.strip() for ref in refs
            ):
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_HANDOFF_SYMBOL_EXPLANATION_EVIDENCE_REQUIRED"
                )
        for item in candidate["reverse_requirement_mappings"]:
            if not isinstance(item, Mapping):
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_HANDOFF_REVERSE_MAPPING_INVALID"
                )
            ref = item.get("evidence_ref")
            if not isinstance(ref, str) or not ref.strip():
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_HANDOFF_REVERSE_MAPPING_EVIDENCE_REQUIRED"
                )
        return dict(candidate)

    @staticmethod
    def _strict_top_level_final_json(
        events: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        candidates: List[Dict[str, Any]] = []
        for event in events:
            kind = str(
                event.get("type") or event.get("event") or event.get("kind") or ""
            ).lower()
            if not (
                kind in {"text", "final", "message", "assistant"}
                or "final" in kind
                or "text" in kind
            ):
                continue
            for key in ("text", "content", "message", "output"):
                value = event.get(key)
                if isinstance(value, Mapping):
                    candidates.append(dict(value))
                    continue
                if not isinstance(value, str) or not value.strip():
                    continue
                try:
                    parsed = json.loads(value.strip())
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    candidates.append(parsed)
        if not candidates:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_STRICT_TOP_LEVEL_FINAL_JSON_REQUIRED"
            )
        return candidates[-1]

    def _handoff_events(
        self, mission_id: str, runtime_assignment_id: str
    ) -> List[Dict[str, Any]]:
        return [
            row for row in self.truth.query(
                "agent_runtime_event", mission_id=mission_id
            )
            if row.get("event_name") == "HANDOFF_RETURNED"
            and row.get("assignment_id") == runtime_assignment_id
        ]

    def _assert_fresh_session(
        self,
        session_id: str,
        *,
        attempt_id: str,
        runtime_assignment_id: str,
    ) -> None:
        for row in self.truth.query(_ARTIFACT):
            if (
                row.get("attempt_id") != attempt_id
                and row.get("dsh_session_id") == session_id
            ):
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_HANDOFF_DSH_SESSION_REUSED"
                )
        for row in self.truth.query("agent_runtime_event"):
            if (
                row.get("event_name") == "HANDOFF_RETURNED"
                and row.get("assignment_id") != runtime_assignment_id
                and row.get("dsh_session_id") == session_id
            ):
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_HANDOFF_DSH_SESSION_REUSED"
                )

    def _candidate_from_raw_evidence(
        self, invocation: WorkerInvocation, assignment: Mapping[str, Any]
    ) -> Dict[str, Any]:
        raw_refs = [
            ref for ref in invocation.evidence_refs
            if isinstance(ref, str) and ref.startswith("file://")
        ]
        if len(raw_refs) != 1:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_RECOVERY_RAW_EVIDENCE_NOT_UNIQUE"
            )
        path = Path(raw_refs[0][len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.launcher.state_root)
        except ValueError as exc:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_RECOVERY_RAW_EVIDENCE_OUTSIDE_STATE_ROOT"
            ) from exc
        if not path.is_file():
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_RECOVERY_RAW_EVIDENCE_MISSING"
            )
        text = path.read_text(encoding="utf-8", errors="replace")
        events = tuple(self.launcher._parse_json_lines(text))
        candidate = self._strict_top_level_final_json(events)
        return self._validate_candidate(candidate, assignment)

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        keys = (
            "release_id", "mission_id", "release_batch_id", "source_commit",
            "assignment_id", "dispatch_id", "mission_node_id", "node_type",
            "stage", "application_id", "target_id", "repository_ref",
            "source_revision", "source_mapping_generation",
            "source_mapping_task_id", "source_mapping_artifact_id",
            "source_mapping_evaluation_id", "workitem_id", "worker_instance_id",
            "team_role", "agent_id", "runtime_assignment_id", "dsh_session_id",
            "candidate_output_ref", "candidate_schema", "state",
            "handoff_status", "process_outcome",
        )
        out = {key: payload.get(key) for key in keys}
        out["authorized_tools"] = list(payload.get("authorized_tools") or [])
        out["source_evidence_refs"] = list(
            payload.get("source_evidence_refs") or []
        )
        out["canonical_evidence_ids"] = list(
            payload.get("canonical_evidence_ids") or []
        )
        out["source_mapping_evidence_refs"] = list(
            payload.get("source_mapping_evidence_refs") or []
        )
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
        if (
            invocation.worker_instance_id != worker_id
            or invocation.mission_id != mission_id
        ):
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_RUNTIME_IDENTITY_MISMATCH"
            )
        if (
            invocation.attempt_id != attempt_id
            or invocation.assignment_id != runtime_assignment_id
        ):
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_RUNTIME_ATTEMPT_MISMATCH"
            )
        session_id = _required(invocation.dsh_session_id, "dsh_session_id")
        if invocation.result != "PASS" or invocation.exit_code != 0:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_DSH_PROCESS_NOT_SUCCESSFUL"
            )
        if not invocation.output_refs:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_CANDIDATE_OUTPUT_REQUIRED"
            )
        if not invocation.tool_calls:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_TOOL_CALL_REQUIRED"
            )
        observed: List[Dict[str, str]] = []
        categories = set()
        for raw in invocation.tool_calls:
            call_ref = _required(raw.get("call_ref"), "tool_call_ref")
            tool_name = _required(raw.get("tool_name"), "tool_name")
            if tool_name not in self.allowed_tools:
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_HANDOFF_UNAUTHORIZED_TOOL:%s" % tool_name
                )
            observed.append({"call_ref": call_ref, "tool_name": tool_name})
            categories.add(tool_name)
        if "git" not in categories:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_REAL_GIT_CALL_REQUIRED"
            )
        java_changed = any(
            str(path).lower().endswith(".java")
            for path in list(candidate.get("changed_files") or [])
        )
        if java_changed and "codegraph" not in categories:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_JAVA_CODEGRAPH_CALL_REQUIRED"
            )
        scope_ref = "task:%s" % str(assignment["workitem_id"])
        if validate_live_authority:
            authority = self.launcher.authority
            control_session = "control-assignment://%s" % str(
                assignment["assignment_id"]
            )
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
                authority.authorize_tool(
                    worker_id, authority_lease_id, item["tool_name"]
                )
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
            "application_id": str(assignment["application_id"]),
            "target_id": str(assignment["target_id"]),
            "repository_ref": str(assignment["repository_ref"]),
            "source_revision": str(assignment["source_revision"]),
            "source_mapping_generation": int(
                assignment["source_mapping_generation"]
            ),
            "source_mapping_task_id": str(
                assignment["source_mapping_task_id"]
            ),
            "source_mapping_artifact_id": str(
                assignment["source_mapping_artifact_id"]
            ),
            "source_mapping_evaluation_id": str(
                assignment["source_mapping_evaluation_id"]
            ),
            "workitem_id": str(assignment["workitem_id"]),
            "worker_instance_id": worker_id,
            "team_role": _TEAM_ROLE,
            "agent_id": _AGENT_ID,
            "assignment_generation": int(assignment["assignment_generation"]),
            "runtime_assignment_id": runtime_assignment_id,
            "authority_lease_id": authority_lease_id,
            "dsh_session_id": session_id,
            "runtime_event_id": _required(
                runtime_event.get("id"), "runtime_event_id"
            ),
            "candidate_output_ref": str(invocation.output_refs[-1]),
            "candidate_schema": _CANDIDATE_SCHEMA,
            "authorized_tools": list(self.allowed_tools),
            "observed_tool_calls": observed,
            "runtime_evidence_refs": list(
                dict.fromkeys(invocation.evidence_refs)
            ),
            "source_evidence_refs": list(
                assignment.get("source_evidence_refs") or []
            ),
            "canonical_evidence_ids": list(
                assignment.get("canonical_evidence_ids") or []
            ),
            "source_mapping_evidence_refs": list(
                assignment.get("source_mapping_evidence_refs") or []
            ),
            "worker_started_at": int(invocation.started_at),
            "worker_finished_at": int(invocation.finished_at),
            "state": _ATTEMPT_STATE,
            "handoff_status": _HANDOFF_STATUS,
            "process_outcome": _PROCESS_OUTCOME,
        }
        existing = self.truth.query(_ARTIFACT, attempt_id=attempt_id)
        if existing:
            if (
                len(existing) != 1
                or self._signature(existing[0]) != self._signature(payload)
            ):
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_HANDOFF_ATTEMPT_IDENTITY_CONFLICT"
                )
            return existing[0]
        now = _now()
        payload.update(
            {"created_at": now, "updated_at": now, "artifact_version": 1}
        )
        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, attempt_id=attempt_id)
        if len(rows) != 1:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_ATTEMPT_PERSISTENCE_FAILED"
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
            exit_code=(
                event.get("exit_code")
                if isinstance(event.get("exit_code"), int)
                else None
            ),
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

    def _prompt(self, assignment: Mapping[str, Any]) -> str:
        context = {
            "mission_id": assignment["mission_id"],
            "release_batch_id": assignment["release_batch_id"],
            "mission_node_id": assignment["mission_node_id"],
            "application_id": assignment["application_id"],
            "target_id": assignment["target_id"],
            "repository_ref": assignment["repository_ref"],
            "source_revision": assignment["source_revision"],
            "source_mapping_generation": assignment[
                "source_mapping_generation"
            ],
            "source_mapping_task_id": assignment["source_mapping_task_id"],
            "source_mapping_artifact_id": assignment[
                "source_mapping_artifact_id"
            ],
            "source_mapping_evaluation_id": assignment[
                "source_mapping_evaluation_id"
            ],
            "source_evidence_refs": list(
                assignment.get("source_evidence_refs") or []
            ),
            "canonical_evidence_ids": list(
                assignment.get("canonical_evidence_ids") or []
            ),
            "source_mapping_evidence_refs": list(
                assignment.get("source_mapping_evidence_refs") or []
            ),
            "workitem_id": assignment["workitem_id"],
            "input_refs": list(assignment.get("input_refs") or []),
            "authorized_tools": list(self.allowed_tools),
        }
        shape = {
            "status": "CANDIDATE",
            "application_id": assignment["application_id"],
            "target_id": assignment["target_id"],
            "repository_ref": assignment["repository_ref"],
            "source_revision": assignment["source_revision"],
            "requirement_ids": [],
            "source_revisions": [assignment["source_revision"]],
            "changed_files": ["path/from/real/git"],
            "changed_symbols": ["symbol/from/real-analysis"],
            "symbol_explanations": [
                {
                    "symbol": "changed symbol",
                    "explanation": "impact explanation",
                    "evidence_refs": ["real git/codegraph call ref"],
                }
            ],
            "reverse_requirement_mappings": [
                {
                    "requirement_id": "requirement id",
                    "symbol": "affected symbol",
                    "evidence_ref": "real git/codegraph call ref",
                }
            ],
            "evidence_refs": ["real git/codegraph call ref"],
            "codegraph_required": True,
            "unknowns": [],
            "gaps": [],
        }
        return (
            "You are the dsh-agent-teams CODE_ANALYSIS_WORKER for canonical RC7.2 N3. "
            "Analyze exactly the accepted source target; never infer or switch repository, "
            "branch, or revision. The repository_ref and source_revision in Context are "
            "immutable source truth. You MUST invoke the real git tool and use its observed "
            "result to establish changed files/symbols. If any changed file is Java, you "
            "MUST invoke the real codegraph tool and use its structured result for symbol "
            "relationships/impact; text claiming that a tool was used is invalid. "
            "Do not declare PASS, do not emit Evaluation/NodeGate/N4/Q7/field/BANK_FINAL. "
            "Return one strict top-level JSON object only with exactly the RequiredShape "
            "keys and no markdown fences. Context="
            + json.dumps(context, ensure_ascii=False, sort_keys=True)
            + " RequiredShape="
            + json.dumps(shape, ensure_ascii=False, sort_keys=True)
        )

    def handoff(
        self, *, release_batch_id: str, target_id: str
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        target_id = _required(target_id, "target_id")
        assignment, _dispatch, task = self._preflight(
            release_batch_id, target_id
        )
        attempt_id = self._attempt_id(str(assignment["assignment_id"]))
        runtime_assignment_id = self._runtime_assignment_id(
            str(assignment["assignment_id"])
        )
        existing = self.truth.query(_ARTIFACT, attempt_id=attempt_id)
        if existing:
            if len(existing) != 1:
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_HANDOFF_ATTEMPT_NOT_UNIQUE"
                )
            row = existing[0]
            if row.get("source_commit") != self.source_commit:
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_HANDOFF_ATTEMPT_SOURCE_COMMIT_MISMATCH"
                )
            if row.get("worker_instance_id") != assignment.get(
                "worker_instance_id"
            ):
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_HANDOFF_ATTEMPT_WORKER_MISMATCH"
                )
            return {
                "status": "RESUMED",
                "attempt_id": attempt_id,
                "application_id": row["application_id"],
                "target_id": target_id,
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
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_RUNTIME_EVENT_NOT_UNIQUE"
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
                "application_id": row["application_id"],
                "target_id": target_id,
                "worker_instance_id": row["worker_instance_id"],
                "dsh_session_id": row["dsh_session_id"],
                "candidate_output_ref": row["candidate_output_ref"],
                "attempt_state": row["state"],
                "workitem_state": str(task["state"]),
            }
        authority = self.launcher.authority
        worker_id = str(assignment["worker_instance_id"])
        control_session = "control-assignment://%s" % str(
            assignment["assignment_id"]
        )
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
        invocation, _launcher_candidate = self.launcher.execute(
            runtime_assignment, self._prompt(assignment)
        )
        candidate = self._candidate_from_raw_evidence(
            invocation, assignment
        )
        events = self._handoff_events(
            str(assignment["mission_id"]), runtime_assignment_id
        )
        if len(events) != 1:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_HANDOFF_HANDOFF_RETURNED_REQUIRED:%d"
                % len(events)
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
            "application_id": row["application_id"],
            "target_id": target_id,
            "worker_instance_id": row["worker_instance_id"],
            "dsh_session_id": row["dsh_session_id"],
            "candidate_output_ref": row["candidate_output_ref"],
            "attempt_state": row["state"],
            "workitem_state": str(task["state"]),
        }


install_rc72_n3_code_analysis_handoff_overlay()
