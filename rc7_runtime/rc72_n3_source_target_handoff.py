"""RC7.2 N3 source-target assignment -> real DSH discovery Attempt bridge.

Each governed per-application assignment runs in its own fresh DSH session
under a task-scoped authority lease. Attempt admission requires a successful
process, a fresh session, at least one authorized real tool call, durable raw
runtime evidence and a strict source-target candidate contract.

The candidate is not canonical source truth. This layer does not promote a
repository/revision mapping, create CODE_ANALYSIS WorkItems, decide an N3
NodeGate, release N4, or claim field/BANK_FINAL status.

Important parsing boundary: the inherited DSH launcher accepts the last JSON
object it can find in final text. That is intentionally broad for legacy agent
outputs, but a nested N3 target object can therefore be mistaken for the whole
candidate. N3 re-parses the raw final event as one strict top-level JSON object
before any candidate or Attempt truth is admitted. Live and crash-recovery
paths use the same parser.
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
from .rc72_authority import RC72AuthorityRuntime, SOURCE_TARGET_DISCOVERY_WORKER
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_n3_source_target_assignment import install_rc72_n3_source_target_assignment_overlay
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n3_source_target_attempt"
_EVENT = "RC72_N3_SOURCE_TARGET_ATTEMPT_UPSERTED"
_BUCKET = "rc72_n3_source_target_attempts"
_NODE_TYPE = AutonomousMissionNode.N3_CODE_ANALYSIS.value
_NEXT_NODE = AutonomousMissionNode.N4_TEST_DESIGN.value
_STAGE = "SOURCE_TARGET_DISCOVERY"
_TEAM_ROLE = SOURCE_TARGET_DISCOVERY_WORKER
_AGENT_ID = "source-target-discovery"
_PHASE = "MISSION_NODE_EXECUTION"
_ASSIGNMENT_STATUS = "LEASED_FOR_HANDOFF"
_ATTEMPT_STATE = "WORKER_COMPLETED_PENDING_DELIVERY"
_HANDOFF_STATUS = "DSH_SESSION_OBSERVED"
_PROCESS_OUTCOME = "SUCCEEDED"
_CANDIDATE_SCHEMA = "RC72_N3_SOURCE_TARGET_CANDIDATE_V1"


class N3SourceTargetHandoffError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3SourceTargetHandoffError(
            "RC72_N3_SOURCE_HANDOFF_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _strings(value: Any, name: str, *, required: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_HANDOFF_%s_INVALID" % name.upper()
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_HANDOFF_%s_INVALID" % name.upper()
        )
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_HANDOFF_%s_DUPLICATE" % name.upper()
        )
    if required and not value:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_HANDOFF_%s_REQUIRED" % name.upper()
        )
    return list(value)


def _tool_calls(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_HANDOFF_OBSERVED_TOOL_CALLS_REQUIRED"
        )
    out: List[Dict[str, str]] = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise _contracts.DomainValidationError(
                "RC72_N3_SOURCE_HANDOFF_TOOL_CALL_INVALID"
            )
        call_ref = _required(raw.get("call_ref"), "tool_call_ref")
        tool_name = _required(raw.get("tool_name"), "tool_name")
        key = (call_ref, tool_name)
        if key in seen:
            raise _contracts.DomainValidationError(
                "RC72_N3_SOURCE_HANDOFF_TOOL_CALL_DUPLICATE"
            )
        seen.add(key)
        out.append({"call_ref": call_ref, "tool_name": tool_name})
    return out


def validate_rc72_n3_source_target_attempt(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "attempt_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "assignment_id", "dispatch_id", "mission_node_id",
        "node_type", "stage", "application_id", "workitem_id",
        "worker_instance_id", "team_role", "agent_id", "runtime_assignment_id",
        "authority_lease_id", "dsh_session_id", "runtime_event_id",
        "candidate_output_ref", "candidate_schema", "state", "handoff_status",
        "process_outcome",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["node_type"] != _NODE_TYPE:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_HANDOFF_NODE_INVALID")
    if out["stage"] != _STAGE:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_HANDOFF_STAGE_INVALID")
    if out["team_role"] != _TEAM_ROLE:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_HANDOFF_TEAM_ROLE_INVALID")
    if out["agent_id"] != _AGENT_ID:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_HANDOFF_AGENT_ID_INVALID")
    if not out["dsh_session_id"].startswith("session-"):
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_HANDOFF_DSH_SESSION_INVALID")
    if out["candidate_schema"] != _CANDIDATE_SCHEMA:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_HANDOFF_CANDIDATE_SCHEMA_INVALID")
    if out["state"] != _ATTEMPT_STATE:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_HANDOFF_ATTEMPT_STATE_INVALID")
    if out["handoff_status"] != _HANDOFF_STATUS:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_HANDOFF_STATUS_INVALID")
    if out["process_outcome"] != _PROCESS_OUTCOME:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_HANDOFF_PROCESS_OUTCOME_INVALID")
    out["authorized_tools"] = _strings(
        out.get("authorized_tools"), "authorized_tools", required=True
    )
    out["runtime_evidence_refs"] = _strings(
        out.get("runtime_evidence_refs"), "runtime_evidence_refs", required=True
    )
    out["observed_tool_calls"] = _tool_calls(out.get("observed_tool_calls"))
    observed = {item["tool_name"] for item in out["observed_tool_calls"]}
    if not observed.issubset(set(out["authorized_tools"])):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_HANDOFF_UNAUTHORIZED_TOOL_OBSERVED"
        )
    if not any(str(ref).startswith("file://") for ref in out["runtime_evidence_refs"]):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_HANDOFF_RAW_RUNTIME_EVIDENCE_REQUIRED"
        )
    for name in ("worker_started_at", "worker_finished_at", "created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N3_SOURCE_HANDOFF_%s_INVALID" % name.upper()
            )
    if out["worker_finished_at"] < out["worker_started_at"]:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_HANDOFF_TIME_ORDER_INVALID"
        )
    for forbidden in (
        "targets", "repository", "repository_ref", "source_revision",
        "base_revision", "head_revision", "target_id", "changed_files",
        "changed_symbols", "codegraph_result", "source_mapping_accepted",
        "evaluation", "node_delivery_id", "node_gate", "node_pass",
        "code_analysis_task_ids", "n4_started", "q7_pass", "field_verified",
        "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N3_SOURCE_HANDOFF_SOURCE_TRUTH_CLAIM_FORBIDDEN:%s"
                % forbidden
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_HANDOFF_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n3_source_target_handoff_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_n3_source_target_assignment_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n3_source_target_attempt
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


class N3SourceTargetDshHandoffService:
    """Run one assigned application source-discovery WorkItem in fresh DSH."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        source_commit: str,
        launcher: DshHeadlessWorkerLauncher,
        allowed_tools: Sequence[str],
    ) -> None:
        install_rc72_n3_source_target_handoff_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.launcher = launcher
        tools = [
            str(item).strip() for item in allowed_tools
            if isinstance(item, str) and item.strip()
        ]
        if not tools or len(set(tools)) != len(tools):
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_ALLOWED_TOOLS_INVALID"
            )
        self.allowed_tools = tuple(tools)
        if not isinstance(self.launcher.authority, RC72AuthorityRuntime):
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_RC72_AUTHORITY_REQUIRED"
            )

    @staticmethod
    def _attempt_id(assignment_id: str) -> str:
        raw = "\x1f".join((assignment_id, "N3_SOURCE_TARGET_DSH_ATTEMPT"))
        return "N3SRCATT-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _runtime_assignment_id(assignment_id: str) -> str:
        raw = "\x1f".join((assignment_id, "N3_SOURCE_TARGET_DSH_HANDOFF"))
        return "N3SRCDSH-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _preflight(
        self, release_batch_id: str, application_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        assignments = self.truth.query(
            "rc72_n3_source_target_assignment", release_batch_id=release_batch_id
        )
        exact = [
            row for row in assignments
            if row.get("source_commit") == self.source_commit
            and row.get("application_id") == application_id
            and row.get("status") == _ASSIGNMENT_STATUS
            and row.get("node_type") == _NODE_TYPE
            and row.get("stage") == _STAGE
            and row.get("team_role") == _TEAM_ROLE
            and row.get("agent_id") == _AGENT_ID
        ]
        if len(exact) != 1:
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_EXACT_ASSIGNMENT_REQUIRED:%d" % len(exact)
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
            or application_id not in list(batch.get("application_ids") or [])
        ):
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_RELEASE_BATCH_LINEAGE_MISMATCH"
            )
        dispatch = self._one(
            "rc72_n3_source_target_dispatch", dispatch_id=str(assignment["dispatch_id"])
        )
        if (
            dispatch.get("mission_id") != mission_id
            or dispatch.get("release_batch_id") != release_batch_id
            or dispatch.get("mission_node_id") != node_id
            or dispatch.get("application_id") != application_id
            or dispatch.get("workitem_id") != workitem_id
            or dispatch.get("source_commit") != self.source_commit
            or dispatch.get("status") != "READY_FOR_ASSIGNMENT"
        ):
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_DISPATCH_LINEAGE_MISMATCH"
            )
        node = self._one("rc72_mission_node", mission_node_id=node_id)
        if (
            node.get("mission_id") != mission_id
            or node.get("node_type") != _NODE_TYPE
            or node.get("state") != MissionNodeState.RUNNING.value
        ):
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_N3_NOT_RUNNING"
            )
        n4 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE
        )
        if n4.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_N4_ALREADY_RELEASED"
            )
        task = self._one("rc7_task", task_id=workitem_id)
        if (
            task.get("mission_id") != mission_id
            or task.get("node") != _STAGE
            or task.get("state") != "LEASED"
            or task.get("lease_owner") != worker_id
        ):
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_WORKITEM_LEASE_MISMATCH"
            )
        return assignment, dispatch, task

    @staticmethod
    def _validate_candidate(
        candidate: Mapping[str, Any], application_id: str
    ) -> Dict[str, Any]:
        if not isinstance(candidate, Mapping):
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_CANDIDATE_OBJECT_REQUIRED"
            )
        if set(candidate.keys()) != {"status", "application_id", "targets", "unknowns", "gaps"}:
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_CANDIDATE_TOP_LEVEL_CONTRACT_INVALID"
            )
        if candidate.get("status") != "CANDIDATE":
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_CANDIDATE_STATUS_INVALID"
            )
        if candidate.get("application_id") != application_id:
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_CANDIDATE_APPLICATION_MISMATCH"
            )
        targets = candidate.get("targets")
        unknowns = candidate.get("unknowns")
        gaps = candidate.get("gaps")
        if not isinstance(targets, list) or not isinstance(unknowns, list) or not isinstance(gaps, list):
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_CANDIDATE_COLLECTION_INVALID"
            )
        seen = set()
        for index, target in enumerate(targets):
            if not isinstance(target, Mapping):
                raise N3SourceTargetHandoffError(
                    "RC72_N3_SOURCE_HANDOFF_TARGET_INVALID:%d" % index
                )
            if set(target.keys()) != {
                "target_id", "repository_ref", "source_revision", "evidence_refs"
            }:
                raise N3SourceTargetHandoffError(
                    "RC72_N3_SOURCE_HANDOFF_TARGET_CONTRACT_INVALID:%d" % index
                )
            target_id = _required(target.get("target_id"), "target_id")
            repository_ref = _required(target.get("repository_ref"), "repository_ref")
            source_revision = _required(target.get("source_revision"), "source_revision")
            if target_id in seen:
                raise N3SourceTargetHandoffError(
                    "RC72_N3_SOURCE_HANDOFF_TARGET_DUPLICATE:%s" % target_id
                )
            seen.add(target_id)
            if "://" not in repository_ref:
                raise N3SourceTargetHandoffError(
                    "RC72_N3_SOURCE_HANDOFF_REPOSITORY_REF_NOT_LOCATOR:%s"
                    % target_id
                )
            if not source_revision.strip():
                raise N3SourceTargetHandoffError(
                    "RC72_N3_SOURCE_HANDOFF_SOURCE_REVISION_REQUIRED:%s"
                    % target_id
                )
            evidence_refs = target.get("evidence_refs")
            if (
                not isinstance(evidence_refs, list)
                or not evidence_refs
                or not all(isinstance(ref, str) and ref.strip() and "://" in ref for ref in evidence_refs)
                or len(set(evidence_refs)) != len(evidence_refs)
            ):
                raise N3SourceTargetHandoffError(
                    "RC72_N3_SOURCE_HANDOFF_TARGET_EVIDENCE_REQUIRED:%s"
                    % target_id
                )
        if not targets and not gaps:
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_DISCOVERY_GAP_REQUIRED"
            )
        return dict(candidate)

    @staticmethod
    def _strict_top_level_final_json(
        events: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Parse exactly one top-level JSON object from a final DSH event.

        Do not recursively walk the string looking for JSON objects: source
        targets/gaps are themselves objects and must never replace the envelope.
        """
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
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_STRICT_TOP_LEVEL_FINAL_JSON_REQUIRED"
            )
        return candidates[-1]

    def _handoff_events(
        self, mission_id: str, runtime_assignment_id: str
    ) -> List[Dict[str, Any]]:
        return [
            row for row in self.truth.query("agent_runtime_event", mission_id=mission_id)
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
            if row.get("attempt_id") != attempt_id and row.get("dsh_session_id") == session_id:
                raise N3SourceTargetHandoffError(
                    "RC72_N3_SOURCE_HANDOFF_DSH_SESSION_REUSED"
                )
        for row in self.truth.query("agent_runtime_event"):
            if (
                row.get("event_name") == "HANDOFF_RETURNED"
                and row.get("assignment_id") != runtime_assignment_id
                and row.get("dsh_session_id") == session_id
            ):
                raise N3SourceTargetHandoffError(
                    "RC72_N3_SOURCE_HANDOFF_DSH_SESSION_REUSED"
                )

    def _candidate_from_raw_evidence(
        self, invocation: WorkerInvocation, application_id: str
    ) -> Dict[str, Any]:
        raw_refs = [
            ref for ref in invocation.evidence_refs
            if isinstance(ref, str) and ref.startswith("file://")
        ]
        if len(raw_refs) != 1:
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_RECOVERY_RAW_EVIDENCE_NOT_UNIQUE"
            )
        path = Path(raw_refs[0][len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.launcher.state_root)
        except ValueError as exc:
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_RECOVERY_RAW_EVIDENCE_OUTSIDE_STATE_ROOT"
            ) from exc
        if not path.is_file():
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_RECOVERY_RAW_EVIDENCE_MISSING"
            )
        text = path.read_text(encoding="utf-8", errors="replace")
        events = tuple(self.launcher._parse_json_lines(text))
        candidate = self._strict_top_level_final_json(events)
        return self._validate_candidate(candidate, application_id)

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        keys = (
            "release_id", "mission_id", "release_batch_id", "source_commit",
            "assignment_id", "dispatch_id", "mission_node_id", "node_type",
            "stage", "application_id", "workitem_id", "worker_instance_id",
            "team_role", "agent_id", "runtime_assignment_id", "dsh_session_id",
            "candidate_output_ref", "candidate_schema", "state", "handoff_status",
            "process_outcome",
        )
        out = {key: payload.get(key) for key in keys}
        out["authorized_tools"] = list(payload.get("authorized_tools") or [])
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
        worker_id = str(assignment["worker_instance_id"])
        mission_id = str(assignment["mission_id"])
        application_id = str(assignment["application_id"])
        self._validate_candidate(candidate, application_id)
        if invocation.worker_instance_id != worker_id or invocation.mission_id != mission_id:
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_RUNTIME_IDENTITY_MISMATCH"
            )
        if invocation.attempt_id != attempt_id or invocation.assignment_id != runtime_assignment_id:
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_RUNTIME_ATTEMPT_MISMATCH"
            )
        session_id = _required(invocation.dsh_session_id, "dsh_session_id")
        if invocation.result != "PASS" or invocation.exit_code != 0:
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_DSH_PROCESS_NOT_SUCCESSFUL"
            )
        if not invocation.output_refs:
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_CANDIDATE_OUTPUT_REQUIRED"
            )
        if not invocation.tool_calls:
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_TOOL_CALL_REQUIRED"
            )
        observed = []
        for raw in invocation.tool_calls:
            call_ref = _required(raw.get("call_ref"), "tool_call_ref")
            tool_name = _required(raw.get("tool_name"), "tool_name")
            if tool_name not in self.allowed_tools:
                raise N3SourceTargetHandoffError(
                    "RC72_N3_SOURCE_HANDOFF_UNAUTHORIZED_TOOL:%s" % tool_name
                )
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
            "application_id": application_id,
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
                raise N3SourceTargetHandoffError(
                    "RC72_N3_SOURCE_HANDOFF_ATTEMPT_IDENTITY_CONFLICT"
                )
            return existing[0]
        now = _now()
        payload.update({"created_at": now, "updated_at": now, "artifact_version": 1})
        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, attempt_id=attempt_id)
        if len(rows) != 1:
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_ATTEMPT_PERSISTENCE_FAILED"
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
        candidate = self._candidate_from_raw_evidence(
            invocation, str(assignment["application_id"])
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

    def _prompt(self, assignment: Mapping[str, Any]) -> str:
        application_id = str(assignment["application_id"])
        context = {
            "mission_id": assignment["mission_id"],
            "release_batch_id": assignment["release_batch_id"],
            "mission_node_id": assignment["mission_node_id"],
            "application_id": application_id,
            "workitem_id": assignment["workitem_id"],
            "input_refs": list(assignment.get("input_refs") or []),
            "authorized_tools": list(self.allowed_tools),
        }
        shape = {
            "status": "CANDIDATE",
            "application_id": application_id,
            "targets": [
                {
                    "target_id": "stable source target id",
                    "repository_ref": "real repository locator",
                    "source_revision": "evidence-backed exact revision",
                    "evidence_refs": ["real tool/source locator"],
                }
            ],
            "unknowns": [],
            "gaps": [],
        }
        return (
            "You are the dsh-agent-teams SOURCE_TARGET_DISCOVERY_WORKER for canonical RC7.2 N3. "
            "Discover source repository target(s) and exact source revision for exactly one application "
            "using only authorized real tools and evidence. Never infer a repository name from the "
            "application id. If no mapping can be proven, return targets=[] and at least one explicit gap. "
            "Do not run CODE_ANALYSIS, do not claim NodeGate/PASS/N4/field_verified/BANK_FINAL. "
            "Return one strict top-level JSON object only, with exactly "
            "status,application_id,targets,unknowns,gaps and no markdown fences. Context="
            + json.dumps(context, ensure_ascii=False, sort_keys=True)
            + " RequiredShape="
            + json.dumps(shape, ensure_ascii=False, sort_keys=True)
        )

    def handoff(
        self, *, release_batch_id: str, application_id: str
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        application_id = _required(application_id, "application_id")
        assignment, _dispatch, task = self._preflight(release_batch_id, application_id)
        attempt_id = self._attempt_id(str(assignment["assignment_id"]))
        runtime_assignment_id = self._runtime_assignment_id(str(assignment["assignment_id"]))
        existing = self.truth.query(_ARTIFACT, attempt_id=attempt_id)
        if existing:
            if len(existing) != 1:
                raise N3SourceTargetHandoffError(
                    "RC72_N3_SOURCE_HANDOFF_ATTEMPT_NOT_UNIQUE"
                )
            row = existing[0]
            if row.get("source_commit") != self.source_commit:
                raise N3SourceTargetHandoffError(
                    "RC72_N3_SOURCE_HANDOFF_ATTEMPT_SOURCE_COMMIT_MISMATCH"
                )
            if row.get("worker_instance_id") != assignment.get("worker_instance_id"):
                raise N3SourceTargetHandoffError(
                    "RC72_N3_SOURCE_HANDOFF_ATTEMPT_WORKER_MISMATCH"
                )
            return {
                "status": "RESUMED",
                "attempt_id": attempt_id,
                "application_id": application_id,
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
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_RUNTIME_EVENT_NOT_UNIQUE"
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
                "application_id": application_id,
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
        invocation, _launcher_candidate = self.launcher.execute(
            runtime_assignment, self._prompt(assignment)
        )
        # Re-parse the exact persisted raw DSH output. The inherited launcher
        # intentionally uses a permissive "last JSON object" extractor and can
        # return a nested target/gap object instead of the N3 envelope.
        candidate = self._candidate_from_raw_evidence(invocation, application_id)
        events = self._handoff_events(
            str(assignment["mission_id"]), runtime_assignment_id
        )
        if len(events) != 1:
            raise N3SourceTargetHandoffError(
                "RC72_N3_SOURCE_HANDOFF_HANDOFF_RETURNED_REQUIRED:%d" % len(events)
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
            "application_id": application_id,
            "worker_instance_id": row["worker_instance_id"],
            "dsh_session_id": row["dsh_session_id"],
            "candidate_output_ref": row["candidate_output_ref"],
            "attempt_state": row["state"],
            "workitem_state": str(task["state"]),
        }


install_rc72_n3_source_target_handoff_overlay()
