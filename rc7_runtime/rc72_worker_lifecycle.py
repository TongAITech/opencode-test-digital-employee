"""RC7.2 Fresh Worker lifecycle, runtime binding, reviewer isolation and Captain handoff.

Lifecycle state is persisted in the inherited R1.  This module reuses existing
ETU, rc7_task, WorkerAssignment/TaskLease and WorkItemAttemptBinding truth.  It
does not implement Phase-7 resource/capability leasing.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import WorkerAssignment, WorkerInvocation
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from .rc72_repository import CanonicalRC72Repository
from .truth_overlay import install_rc7_truth_overlay


_WORKER_SESSION = "rc72_worker_session"
_WORKER_CHECKPOINT = "rc72_worker_checkpoint"
_WORKER_ROTATION = "rc72_worker_rotation"
_REVIEWER_ASSIGNMENT = "rc72_reviewer_assignment"
_CAPTAIN_HANDOFF = "rc72_captain_handoff"
_CAPTAIN_TAKEOVER = "rc72_captain_takeover"

_EVENT_TYPES = {
    "RC72_WORKER_SESSION_UPSERTED": (_WORKER_SESSION, "session_id"),
    "RC72_WORKER_CHECKPOINT_UPSERTED": (_WORKER_CHECKPOINT, "checkpoint_id"),
    "RC72_WORKER_ROTATION_UPSERTED": (_WORKER_ROTATION, "decision_id"),
    "RC72_REVIEWER_ASSIGNMENT_UPSERTED": (_REVIEWER_ASSIGNMENT, "review_id"),
    "RC72_CAPTAIN_HANDOFF_UPSERTED": (_CAPTAIN_HANDOFF, "checkpoint_id"),
    "RC72_CAPTAIN_TAKEOVER_UPSERTED": (_CAPTAIN_TAKEOVER, "takeover_id"),
}
_BUCKETS = {
    _WORKER_SESSION: "rc72_worker_sessions",
    _WORKER_CHECKPOINT: "rc72_worker_checkpoints",
    _WORKER_ROTATION: "rc72_worker_rotations",
    _REVIEWER_ASSIGNMENT: "rc72_reviewer_assignments",
    _CAPTAIN_HANDOFF: "rc72_captain_handoffs",
    _CAPTAIN_TAKEOVER: "rc72_captain_takeovers",
}
_ALLOWED_CONTEXT_KEYS = {
    "mission_id", "release_batch_id", "team_id", "role", "etu_id", "workitem_id",
    "etu_refs", "executable_contract_refs", "data_refs", "evidence_refs", "gap_refs",
    "coverage_refs", "lease_refs",
}
_CANONICAL_REF_KEYS = {
    "etu_refs", "executable_contract_refs", "data_refs", "evidence_refs", "gap_refs",
    "coverage_refs", "lease_refs",
}


def _now() -> int:
    return int(time.time())


def _new(prefix: str) -> str:
    return "%s-%s" % (prefix, uuid.uuid4().hex[:20])


def _base(payload: Dict[str, Any], artifact_type: str, identity: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (identity, "mission_id", "release_id"):
        out[name] = _contracts._require_str(out, name)
    out["artifact_type"] = artifact_type
    out["artifact_version"] = _contracts._artifact_version(out)
    return out


def _optional_string(out: Dict[str, Any], name: str) -> None:
    value = out.get(name)
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise _contracts.DomainValidationError("%s_INVALID" % name.upper())


def _validate_worker_session(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _WORKER_SESSION, "session_id")
    for name in ("worker_id", "release_batch_id", "team_id", "role", "purpose", "state"):
        out[name] = _contracts._require_str(out, name)
    out["purpose"] = out["purpose"].upper()
    out["state"] = out["state"].upper()
    if out["purpose"] not in {"EXECUTION", "REVIEW"}:
        raise _contracts.DomainValidationError("WORKER_SESSION_PURPOSE_INVALID")
    if out["state"] not in {"ACTIVE", "CLOSED"}:
        raise _contracts.DomainValidationError("WORKER_SESSION_STATE_INVALID")
    context = out.get("context_bundle")
    if not isinstance(context, dict):
        raise _contracts.DomainValidationError("WORKER_SESSION_CONTEXT_MUST_BE_OBJECT")
    if {"chat_history", "messages", "previous_session_transcript"}.intersection(context):
        raise _contracts.DomainValidationError("WORKER_SESSION_CHAT_HISTORY_FORBIDDEN")
    if out["purpose"] == "EXECUTION":
        out["etu_id"] = _contracts._require_str(out, "etu_id")
        out["workitem_id"] = _contracts._require_str(out, "workitem_id")
        if set(context).difference(_ALLOWED_CONTEXT_KEYS):
            raise _contracts.DomainValidationError("WORKER_SESSION_CONTEXT_KEY_NOT_ALLOWED")
    else:
        out["mission_node_id"] = _contracts._require_str(out, "mission_node_id")
        out["delivery_id"] = _contracts._require_str(out, "delivery_id")
    for name in (
        "parent_session_id", "checkpoint_id", "close_reason", "runtime_worker_id",
        "runtime_assignment_id", "task_lease_ref", "runtime_attempt_id", "dsh_session_id",
        "binding_id",
    ):
        _optional_string(out, name)
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("WORKER_SESSION_CREATED_AT_INVALID")
    if out.get("closed_at") is not None and (not isinstance(out["closed_at"], int) or out["closed_at"] < 0):
        raise _contracts.DomainValidationError("WORKER_SESSION_CLOSED_AT_INVALID")
    if out["state"] == "CLOSED" and not out.get("checkpoint_id"):
        raise _contracts.DomainValidationError("CLOSED_WORKER_SESSION_REQUIRES_CHECKPOINT")
    if out.get("dsh_session_id") and not out.get("runtime_worker_id"):
        raise _contracts.DomainValidationError("DSH_SESSION_REQUIRES_RUNTIME_WORKER")
    return out


def _validate_checkpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _WORKER_CHECKPOINT, "checkpoint_id")
    for name in ("session_id", "worker_id", "team_id", "role", "purpose", "reason"):
        out[name] = _contracts._require_str(out, name)
    for name in ("etu_id", "workitem_id", "rotation_decision_id", "dsh_session_id", "runtime_worker_id"):
        _optional_string(out, name)
    if not isinstance(out.get("context_bundle"), dict):
        raise _contracts.DomainValidationError("WORKER_CHECKPOINT_CONTEXT_MUST_BE_OBJECT")
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("WORKER_CHECKPOINT_CREATED_AT_INVALID")
    return out


def _validate_rotation(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _WORKER_ROTATION, "decision_id")
    for name in ("session_id", "worker_id", "team_id", "decision"):
        out[name] = _contracts._require_str(out, name)
    out["decision"] = out["decision"].upper()
    if out["decision"] not in {"ROTATE", "KEEP"}:
        raise _contracts.DomainValidationError("WORKER_ROTATION_DECISION_INVALID")
    _contracts._require_string_list(out, "reasons")
    if not isinstance(out.get("metrics"), dict):
        raise _contracts.DomainValidationError("WORKER_ROTATION_METRICS_MUST_BE_OBJECT")
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("WORKER_ROTATION_CREATED_AT_INVALID")
    return out


def _validate_reviewer(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _REVIEWER_ASSIGNMENT, "review_id")
    for name in ("worker_id", "session_id", "team_id", "mission_node_id", "delivery_id"):
        out[name] = _contracts._require_str(out, name)
    for name in ("criteria", "evidence_refs"):
        _contracts._require_string_list(out, name)
    if not isinstance(out.get("context_bundle"), dict):
        raise _contracts.DomainValidationError("REVIEWER_CONTEXT_MUST_BE_OBJECT")
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("REVIEWER_CREATED_AT_INVALID")
    return out


def _validate_handoff(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _CAPTAIN_HANDOFF, "checkpoint_id")
    for name in ("release_batch_id", "team_id", "old_captain_session_id"):
        out[name] = _contracts._require_str(out, name)
    for name in (
        "current_node_refs", "latest_delivery_refs", "latest_gate_refs", "next_workitem_ids",
        "active_worker_session_ids", "active_workitem_ids", "blocked_workitem_ids",
        "completed_workitem_ids",
    ):
        _contracts._require_string_list(out, name)
    if not isinstance(out.get("resumable_from_r1"), bool):
        raise _contracts.DomainValidationError("CAPTAIN_HANDOFF_RESUMABLE_INVALID")
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("CAPTAIN_HANDOFF_CREATED_AT_INVALID")
    return out


def _validate_takeover(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _CAPTAIN_TAKEOVER, "takeover_id")
    for name in ("checkpoint_id", "release_batch_id", "team_id", "new_captain_session_id"):
        out[name] = _contracts._require_str(out, name)
    for name in ("active_worker_session_ids", "next_workitem_ids"):
        _contracts._require_string_list(out, name)
    for name in ("ready", "resumable_from_r1"):
        if not isinstance(out.get(name), bool):
            raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("CAPTAIN_TAKEOVER_CREATED_AT_INVALID")
    return out


def install_rc72_worker_lifecycle_overlay() -> None:
    install_rc7_truth_overlay()
    validators = {
        _WORKER_SESSION: _validate_worker_session,
        _WORKER_CHECKPOINT: _validate_checkpoint,
        _WORKER_ROTATION: _validate_rotation,
        _REVIEWER_ASSIGNMENT: _validate_reviewer,
        _CAPTAIN_HANDOFF: _validate_handoff,
        _CAPTAIN_TAKEOVER: _validate_takeover,
    }
    for artifact_type, validator in validators.items():
        _contracts.VALIDATORS[artifact_type] = validator
        _truth.BUCKETS[artifact_type] = _BUCKETS[artifact_type]
    for event_type, (artifact_type, identity) in _EVENT_TYPES.items():
        _truth.EVENT_TYPES[event_type] = (artifact_type, identity)
        _truth.IDENTITY_FIELDS[artifact_type] = identity


@dataclass(frozen=True)
class WorkerLifecyclePolicy:
    max_workitems: int = 1
    max_steps: int = 100
    max_tokens: int = 50000
    max_tool_calls: int = 50
    max_compactions: int = 2
    max_retries: int = 3
    max_age_seconds: int = 1800
    max_context_pressure: float = 0.80

    def __post_init__(self) -> None:
        for name in (
            "max_workitems", "max_steps", "max_tokens", "max_tool_calls", "max_compactions",
            "max_retries", "max_age_seconds",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 1:
                raise ContractError("WORKER_POLICY_%s_INVALID" % name.upper())
        if not isinstance(self.max_context_pressure, (int, float)) or not 0 < float(self.max_context_pressure) <= 1.0:
            raise ContractError("WORKER_POLICY_CONTEXT_PRESSURE_INVALID")


@dataclass(frozen=True)
class WorkerSessionMetrics:
    workitem_count: int
    step_count: int
    token_usage: int
    tool_call_count: int
    compaction_count: int
    retry_count: int
    age_seconds: int
    context_pressure: float

    def __post_init__(self) -> None:
        for name in (
            "workitem_count", "step_count", "token_usage", "tool_call_count", "compaction_count",
            "retry_count", "age_seconds",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ContractError("WORKER_METRICS_%s_INVALID" % name.upper())
        if not isinstance(self.context_pressure, (int, float)) or not 0.0 <= float(self.context_pressure) <= 1.0:
            raise ContractError("WORKER_METRICS_CONTEXT_PRESSURE_INVALID")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "workitem_count": self.workitem_count,
            "step_count": self.step_count,
            "token_usage": self.token_usage,
            "tool_call_count": self.tool_call_count,
            "compaction_count": self.compaction_count,
            "retry_count": self.retry_count,
            "age_seconds": self.age_seconds,
            "context_pressure": float(self.context_pressure),
        }


@dataclass(frozen=True)
class FreshWorkerAssignment:
    worker_id: str
    session_id: str
    context_bundle: Dict[str, Any]


@dataclass(frozen=True)
class WorkerCheckpointResult:
    checkpoint_id: str
    session_id: str


@dataclass(frozen=True)
class RotationDecision:
    decision_id: str
    required: bool
    reasons: List[str]


@dataclass(frozen=True)
class RotationResult:
    checkpoint_id: str
    new_assignment: FreshWorkerAssignment


@dataclass(frozen=True)
class FreshReviewerAssignment:
    review_id: str
    worker_id: str
    session_id: str
    context_bundle: Dict[str, Any]


@dataclass(frozen=True)
class CaptainHandoffCheckpoint:
    checkpoint_id: str
    mission_id: str
    team_id: str
    active_worker_session_ids: List[str]


@dataclass(frozen=True)
class CaptainTakeoverReadiness:
    takeover_id: str
    ready: bool
    mission_id: str
    team_id: str
    resumable_from_r1: bool


@dataclass(frozen=True)
class RuntimeAssignmentBinding:
    binding_id: str
    runtime_worker_id: str
    task_lease_ref: str
    attempt_id: str


@dataclass(frozen=True)
class DshRuntimeBinding:
    binding_id: str
    dsh_session_id: str


class WorkerLifecycleService:
    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        policy: Optional[WorkerLifecyclePolicy] = None,
    ) -> None:
        install_rc72_worker_lifecycle_overlay()
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("WORKER_LIFECYCLE_RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()
        self.policy = policy or WorkerLifecyclePolicy()
        self.repository = CanonicalRC72Repository(truth, release_id=self.release_id)

    def _append(self, event_type: str, payload: Dict[str, Any]):
        out = dict(payload)
        out["release_id"] = self.release_id
        out.setdefault("artifact_version", 1)
        return self.truth.append_atomic(event_type, out)

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise ContractError("WORKER_LIFECYCLE_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows)))
        return rows[0]

    def _batch_for_mission(self, mission_id: str) -> Dict[str, Any]:
        return self._one("rc72_release_batch", mission_id=mission_id)

    def _update_session(self, session: Mapping[str, Any], **changes: Any) -> Dict[str, Any]:
        updated = dict(session)
        updated.pop("artifact_type", None)
        updated.update(changes)
        updated["artifact_version"] = int(session.get("artifact_version", 1)) + 1
        self._append("RC72_WORKER_SESSION_UPSERTED", updated)
        return self._one(_WORKER_SESSION, session_id=str(session["session_id"]))

    @staticmethod
    def _canonical_refs(refs: Mapping[str, Any]) -> Dict[str, List[str]]:
        if not isinstance(refs, Mapping):
            raise ContractError("WORKER_CANONICAL_REFS_MUST_BE_OBJECT")
        unknown = set(refs).difference(_CANONICAL_REF_KEYS)
        if unknown:
            raise ContractError("WORKER_CANONICAL_REF_KEY_FORBIDDEN:%s" % sorted(unknown)[0])
        result: Dict[str, List[str]] = {}
        for key in sorted(_CANONICAL_REF_KEYS):
            values = refs.get(key, [])
            if not isinstance(values, list) or not all(isinstance(v, str) and v.strip() for v in values):
                raise ContractError("WORKER_CANONICAL_REF_INVALID:%s" % key)
            result[key] = list(values)
        return result

    def assign_fresh_worker(
        self,
        *,
        mission_id: str,
        team_id: str,
        role: str,
        etu_id: str,
        workitem_id: str,
        canonical_refs: Mapping[str, Any],
        parent_session_id: Optional[str] = None,
    ) -> FreshWorkerAssignment:
        batch = self._batch_for_mission(mission_id)
        etu = self._one("rc72_etu", etu_id=etu_id)
        task = self._one("rc7_task", task_id=workitem_id)
        if etu.get("mission_id") != mission_id or etu.get("release_batch_id") != batch.get("release_batch_id"):
            raise ContractError("WORKER_ETU_LINEAGE_MISMATCH")
        if task.get("mission_id") != mission_id:
            raise ContractError("WORKER_TASK_LINEAGE_MISMATCH")
        refs = self._canonical_refs(canonical_refs)
        if etu_id not in refs["etu_refs"]:
            raise ContractError("WORKER_ETU_REF_REQUIRED")
        worker_id, session_id = _new("WRK"), _new("SES")
        context = {
            "mission_id": mission_id,
            "release_batch_id": batch["release_batch_id"],
            "team_id": team_id,
            "role": role,
            "etu_id": etu_id,
            "workitem_id": workitem_id,
        }
        context.update(refs)
        self._append(
            "RC72_WORKER_SESSION_UPSERTED",
            {
                "session_id": session_id,
                "worker_id": worker_id,
                "mission_id": mission_id,
                "release_batch_id": batch["release_batch_id"],
                "team_id": team_id,
                "role": role,
                "purpose": "EXECUTION",
                "etu_id": etu_id,
                "workitem_id": workitem_id,
                "state": "ACTIVE",
                "context_bundle": context,
                "parent_session_id": parent_session_id,
                "checkpoint_id": None,
                "close_reason": None,
                "runtime_worker_id": None,
                "runtime_assignment_id": None,
                "task_lease_ref": None,
                "runtime_attempt_id": None,
                "dsh_session_id": None,
                "binding_id": None,
                "created_at": _now(),
                "closed_at": None,
            },
        )
        return FreshWorkerAssignment(worker_id, session_id, context)

    def bind_existing_session(
        self,
        *,
        session_id: str,
        etu_id: str,
        workitem_id: str,
        canonical_refs: Mapping[str, Any],
    ) -> FreshWorkerAssignment:
        session = self._one(_WORKER_SESSION, session_id=session_id)
        if session.get("state") == "CLOSED":
            raise ContractError("WORKER_SESSION_CLOSED")
        if session.get("purpose") != "EXECUTION":
            raise ContractError("WORKER_SESSION_NOT_EXECUTION")
        if session.get("etu_id") != etu_id or session.get("workitem_id") != workitem_id:
            raise ContractError("WORKER_SESSION_REUSE_FORBIDDEN")
        refs = self._canonical_refs(canonical_refs)
        for key in _CANONICAL_REF_KEYS:
            if session["context_bundle"].get(key, []) != refs[key]:
                raise ContractError("WORKER_SESSION_CONTEXT_DRIFT")
        return FreshWorkerAssignment(session["worker_id"], session_id, dict(session["context_bundle"]))

    def bind_signed_runtime_assignment(
        self,
        *,
        lifecycle_session_id: str,
        assignment: WorkerAssignment,
        case_id: str,
    ) -> RuntimeAssignmentBinding:
        session = self._one(_WORKER_SESSION, session_id=lifecycle_session_id)
        if session.get("state") != "ACTIVE" or session.get("purpose") != "EXECUTION":
            raise ContractError("WORKER_SESSION_NOT_ACTIVE_EXECUTION")
        if assignment.mission_id != session.get("mission_id"):
            raise ContractError("RUNTIME_ASSIGNMENT_MISSION_MISMATCH")
        if assignment.scope != session.get("etu_id"):
            raise ContractError("RUNTIME_ASSIGNMENT_SCOPE_MISMATCH")
        if assignment.lease.worker_id != assignment.worker_instance_id:
            raise ContractError("RUNTIME_ASSIGNMENT_LEASE_WORKER_MISMATCH")
        if assignment.lease.scope_ref != assignment.scope:
            raise ContractError("RUNTIME_ASSIGNMENT_LEASE_SCOPE_MISMATCH")
        if not assignment.lease.signature:
            raise ContractError("RUNTIME_ASSIGNMENT_UNSIGNED_LEASE")
        etu = self._one("rc72_etu", etu_id=str(session["etu_id"]))
        if case_id not in list(etu.get("case_ids") or []):
            raise ContractError("RUNTIME_ASSIGNMENT_CASE_OUTSIDE_ETU")
        binding_id = _new("WAB")
        binding = WorkItemAttemptBinding(
            binding_id=binding_id,
            mission_id=str(session["mission_id"]),
            etu_id=str(session["etu_id"]),
            workitem_id=str(session["workitem_id"]),
            case_id=case_id,
            attempt_id=assignment.attempt_id,
            worker_id=assignment.worker_instance_id,
            session_id=lifecycle_session_id,
            task_lease_ref=assignment.lease.lease_id,
            state=WorkItemAttemptState.PREPARED,
        )
        self.repository.persist(binding)
        self._update_session(
            session,
            runtime_worker_id=assignment.worker_instance_id,
            runtime_assignment_id=assignment.assignment_id,
            task_lease_ref=assignment.lease.lease_id,
            runtime_attempt_id=assignment.attempt_id,
            binding_id=binding_id,
        )
        return RuntimeAssignmentBinding(
            binding_id=binding_id,
            runtime_worker_id=assignment.worker_instance_id,
            task_lease_ref=assignment.lease.lease_id,
            attempt_id=assignment.attempt_id,
        )

    def record_dsh_session(
        self,
        *,
        lifecycle_session_id: str,
        invocation: WorkerInvocation,
    ) -> DshRuntimeBinding:
        session = self._one(_WORKER_SESSION, session_id=lifecycle_session_id)
        if session.get("state") != "ACTIVE":
            raise ContractError("WORKER_SESSION_NOT_ACTIVE")
        if not session.get("binding_id") or not session.get("runtime_worker_id"):
            raise ContractError("RUNTIME_ASSIGNMENT_NOT_BOUND")
        expected = {
            "worker": session.get("runtime_worker_id"),
            "mission": session.get("mission_id"),
            "assignment": session.get("runtime_assignment_id"),
            "attempt": session.get("runtime_attempt_id"),
            "lease": session.get("task_lease_ref"),
            "scope": session.get("etu_id"),
        }
        if invocation.worker_instance_id != expected["worker"]:
            raise ContractError("RUNTIME_WORKER_IDENTITY_MISMATCH")
        if invocation.mission_id != expected["mission"]:
            raise ContractError("RUNTIME_MISSION_IDENTITY_MISMATCH")
        if invocation.assignment_id != expected["assignment"]:
            raise ContractError("RUNTIME_ASSIGNMENT_IDENTITY_MISMATCH")
        if invocation.attempt_id != expected["attempt"]:
            raise ContractError("RUNTIME_ATTEMPT_IDENTITY_MISMATCH")
        if invocation.lease_id != expected["lease"]:
            raise ContractError("RUNTIME_LEASE_IDENTITY_MISMATCH")
        if invocation.scope != expected["scope"]:
            raise ContractError("RUNTIME_SCOPE_IDENTITY_MISMATCH")
        if not isinstance(invocation.dsh_session_id, str) or not invocation.dsh_session_id.strip():
            raise ContractError("RUNTIME_DSH_SESSION_REQUIRED")
        previous = self._one("rc72_workitem_attempt_binding", binding_id=str(session["binding_id"]))
        running = WorkItemAttemptBinding(
            binding_id=previous["binding_id"],
            mission_id=previous["mission_id"],
            etu_id=previous["etu_id"],
            workitem_id=previous["workitem_id"],
            case_id=previous["case_id"],
            attempt_id=previous["attempt_id"],
            worker_id=invocation.worker_instance_id,
            session_id=invocation.dsh_session_id,
            task_lease_ref=invocation.lease_id,
            capability_lease_refs=tuple(previous.get("capability_lease_refs") or []),
            resource_lease_refs=tuple(previous.get("resource_lease_refs") or []),
            parent_attempt_id=previous.get("parent_attempt_id"),
            state=WorkItemAttemptState.RUNNING,
        )
        self.repository.persist(running, artifact_version=int(previous.get("artifact_version", 1)) + 1)
        self._update_session(session, dsh_session_id=invocation.dsh_session_id)
        return DshRuntimeBinding(str(session["binding_id"]), invocation.dsh_session_id)

    def checkpoint_and_close(
        self,
        session_id: str,
        *,
        reason: str,
        rotation_decision_id: Optional[str] = None,
    ) -> WorkerCheckpointResult:
        session = self._one(_WORKER_SESSION, session_id=session_id)
        if session.get("state") == "CLOSED":
            raise ContractError("WORKER_SESSION_CLOSED")
        checkpoint_id = _new("WCP")
        self._append(
            "RC72_WORKER_CHECKPOINT_UPSERTED",
            {
                "checkpoint_id": checkpoint_id,
                "mission_id": session["mission_id"],
                "session_id": session_id,
                "worker_id": session["worker_id"],
                "team_id": session["team_id"],
                "role": session["role"],
                "purpose": session["purpose"],
                "etu_id": session.get("etu_id"),
                "workitem_id": session.get("workitem_id"),
                "rotation_decision_id": rotation_decision_id,
                "dsh_session_id": session.get("dsh_session_id"),
                "runtime_worker_id": session.get("runtime_worker_id"),
                "reason": reason,
                "context_bundle": dict(session["context_bundle"]),
                "created_at": _now(),
            },
        )
        self._update_session(
            session,
            state="CLOSED",
            checkpoint_id=checkpoint_id,
            close_reason=reason,
            closed_at=_now(),
        )
        return WorkerCheckpointResult(checkpoint_id, session_id)

    def evaluate_rotation(self, session_id: str, metrics: WorkerSessionMetrics) -> RotationDecision:
        session = self._one(_WORKER_SESSION, session_id=session_id)
        if session.get("state") != "ACTIVE":
            raise ContractError("WORKER_SESSION_NOT_ACTIVE")
        reasons: List[str] = []
        for triggered, reason in (
            (metrics.workitem_count >= self.policy.max_workitems, "MAX_WORKITEMS"),
            (metrics.step_count > self.policy.max_steps, "MAX_STEPS"),
            (metrics.token_usage > self.policy.max_tokens, "MAX_TOKENS"),
            (metrics.tool_call_count > self.policy.max_tool_calls, "MAX_TOOL_CALLS"),
            (metrics.compaction_count >= self.policy.max_compactions, "MAX_COMPACTIONS"),
            (metrics.retry_count >= self.policy.max_retries, "MAX_RETRIES"),
            (metrics.age_seconds > self.policy.max_age_seconds, "MAX_AGE"),
            (float(metrics.context_pressure) >= float(self.policy.max_context_pressure), "CONTEXT_PRESSURE"),
        ):
            if triggered:
                reasons.append(reason)
        decision_id = _new("ROT")
        self._append(
            "RC72_WORKER_ROTATION_UPSERTED",
            {
                "decision_id": decision_id,
                "mission_id": session["mission_id"],
                "session_id": session_id,
                "worker_id": session["worker_id"],
                "team_id": session["team_id"],
                "decision": "ROTATE" if reasons else "KEEP",
                "reasons": reasons,
                "metrics": metrics.as_dict(),
                "created_at": _now(),
            },
        )
        return RotationDecision(decision_id, bool(reasons), reasons)

    def rotate_to_fresh_worker(
        self,
        *,
        session_id: str,
        metrics: WorkerSessionMetrics,
        next_etu_id: str,
        next_workitem_id: str,
        canonical_refs: Mapping[str, Any],
    ) -> RotationResult:
        session = self._one(_WORKER_SESSION, session_id=session_id)
        if session.get("state") != "ACTIVE":
            raise ContractError("WORKER_SESSION_NOT_ACTIVE")
        candidates = [
            row for row in self.truth.query(_WORKER_ROTATION, session_id=session_id)
            if row.get("decision") == "ROTATE" and row.get("metrics") == metrics.as_dict()
        ]
        if candidates:
            decision_id = sorted(candidates, key=lambda row: (int(row.get("created_at", 0)), row["decision_id"]))[-1]["decision_id"]
        else:
            decision = self.evaluate_rotation(session_id, metrics)
            if not decision.required:
                raise ContractError("WORKER_ROTATION_NOT_REQUIRED")
            decision_id = decision.decision_id
        closed = self.checkpoint_and_close(
            session_id,
            reason="ROTATION_REQUIRED",
            rotation_decision_id=decision_id,
        )
        new_assignment = self.assign_fresh_worker(
            mission_id=session["mission_id"],
            team_id=session["team_id"],
            role=session["role"],
            etu_id=next_etu_id,
            workitem_id=next_workitem_id,
            canonical_refs=canonical_refs,
            parent_session_id=session_id,
        )
        return RotationResult(closed.checkpoint_id, new_assignment)

    def assign_fresh_reviewer(
        self,
        *,
        mission_id: str,
        team_id: str,
        mission_node_id: str,
        delivery_id: str,
        criteria: Sequence[str],
        evidence_refs: Sequence[str],
        excluded_session_ids: Sequence[str] = (),
    ) -> FreshReviewerAssignment:
        batch = self._batch_for_mission(mission_id)
        delivery = self._one("rc72_node_delivery", delivery_id=delivery_id)
        if delivery.get("mission_id") != mission_id or delivery.get("mission_node_id") != mission_node_id:
            raise ContractError("REVIEWER_DELIVERY_LINEAGE_MISMATCH")
        criteria_list, evidence_list = list(criteria), list(evidence_refs)
        if not criteria_list or not all(isinstance(v, str) and v.strip() for v in criteria_list):
            raise ContractError("REVIEWER_CRITERIA_REQUIRED")
        if not all(isinstance(v, str) and v.strip() for v in evidence_list):
            raise ContractError("REVIEWER_EVIDENCE_REFS_INVALID")
        excluded = set(excluded_session_ids)
        session_id = _new("REVSES")
        while session_id in excluded:
            session_id = _new("REVSES")
        worker_id, review_id = _new("REVWRK"), _new("REV")
        context = {
            "mission_id": mission_id,
            "team_id": team_id,
            "mission_node_id": mission_node_id,
            "delivery_id": delivery_id,
            "criteria": criteria_list,
            "evidence_refs": evidence_list,
        }
        self._append(
            "RC72_WORKER_SESSION_UPSERTED",
            {
                "session_id": session_id,
                "worker_id": worker_id,
                "mission_id": mission_id,
                "release_batch_id": batch["release_batch_id"],
                "team_id": team_id,
                "role": "quality-reviewer",
                "purpose": "REVIEW",
                "mission_node_id": mission_node_id,
                "delivery_id": delivery_id,
                "state": "ACTIVE",
                "context_bundle": context,
                "parent_session_id": None,
                "checkpoint_id": None,
                "close_reason": None,
                "runtime_worker_id": None,
                "runtime_assignment_id": None,
                "task_lease_ref": None,
                "runtime_attempt_id": None,
                "dsh_session_id": None,
                "binding_id": None,
                "created_at": _now(),
                "closed_at": None,
            },
        )
        self._append(
            "RC72_REVIEWER_ASSIGNMENT_UPSERTED",
            {
                "review_id": review_id,
                "mission_id": mission_id,
                "worker_id": worker_id,
                "session_id": session_id,
                "team_id": team_id,
                "mission_node_id": mission_node_id,
                "delivery_id": delivery_id,
                "criteria": criteria_list,
                "evidence_refs": evidence_list,
                "context_bundle": context,
                "created_at": _now(),
            },
        )
        return FreshReviewerAssignment(review_id, worker_id, session_id, context)

    def create_captain_handoff(
        self,
        *,
        mission_id: str,
        team_id: str,
        old_captain_session_id: str,
        current_node_refs: Sequence[str],
        latest_delivery_refs: Sequence[str],
        latest_gate_refs: Sequence[str],
        next_workitem_ids: Sequence[str],
    ) -> CaptainHandoffCheckpoint:
        batch = self._batch_for_mission(mission_id)
        for workitem_id in next_workitem_ids:
            task = self._one("rc7_task", task_id=workitem_id)
            if task.get("mission_id") != mission_id:
                raise ContractError("CAPTAIN_HANDOFF_WORKITEM_MISSION_MISMATCH")
        active_sessions = [
            row for row in self.truth.query(_WORKER_SESSION, mission_id=mission_id, team_id=team_id)
            if row.get("state") == "ACTIVE"
        ]
        active_ids = sorted(row["session_id"] for row in active_sessions)
        tasks = self.truth.query("rc7_task", mission_id=mission_id)
        checkpoint_id = _new("CAPHO")
        self._append(
            "RC72_CAPTAIN_HANDOFF_UPSERTED",
            {
                "checkpoint_id": checkpoint_id,
                "mission_id": mission_id,
                "release_batch_id": batch["release_batch_id"],
                "team_id": team_id,
                "old_captain_session_id": old_captain_session_id,
                "current_node_refs": list(current_node_refs),
                "latest_delivery_refs": list(latest_delivery_refs),
                "latest_gate_refs": list(latest_gate_refs),
                "next_workitem_ids": list(next_workitem_ids),
                "active_worker_session_ids": active_ids,
                "active_workitem_ids": sorted(row["task_id"] for row in tasks if str(row.get("state")) in {"READY", "LEASED", "RUNNING"}),
                "blocked_workitem_ids": sorted(row["task_id"] for row in tasks if str(row.get("state")) == "BLOCKED"),
                "completed_workitem_ids": sorted(row["task_id"] for row in tasks if str(row.get("state")) in {"COMPLETED", "CANCELLED"}),
                "resumable_from_r1": True,
                "created_at": _now(),
            },
        )
        return CaptainHandoffCheckpoint(checkpoint_id, mission_id, team_id, active_ids)

    def takeover_captain(
        self,
        *,
        checkpoint_id: str,
        new_captain_session_id: str,
        expected_mission_id: str,
        expected_team_id: str,
    ) -> CaptainTakeoverReadiness:
        handoff = self._one(_CAPTAIN_HANDOFF, checkpoint_id=checkpoint_id)
        if handoff.get("mission_id") != expected_mission_id or handoff.get("team_id") != expected_team_id:
            raise ContractError("CAPTAIN_HANDOFF_IDENTITY_MISMATCH")
        batch = self._batch_for_mission(expected_mission_id)
        if batch.get("release_batch_id") != handoff.get("release_batch_id"):
            raise ContractError("CAPTAIN_HANDOFF_RELEASE_BATCH_MISMATCH")
        for workitem_id in handoff.get("next_workitem_ids", []):
            task = self._one("rc7_task", task_id=workitem_id)
            if task.get("mission_id") != expected_mission_id:
                raise ContractError("CAPTAIN_HANDOFF_WORKITEM_MISSION_MISMATCH")
        takeover_id = _new("CAPTO")
        self._append(
            "RC72_CAPTAIN_TAKEOVER_UPSERTED",
            {
                "takeover_id": takeover_id,
                "mission_id": expected_mission_id,
                "checkpoint_id": checkpoint_id,
                "release_batch_id": batch["release_batch_id"],
                "team_id": expected_team_id,
                "new_captain_session_id": new_captain_session_id,
                "active_worker_session_ids": list(handoff.get("active_worker_session_ids", [])),
                "next_workitem_ids": list(handoff.get("next_workitem_ids", [])),
                "ready": True,
                "resumable_from_r1": True,
                "created_at": _now(),
            },
        )
        return CaptainTakeoverReadiness(takeover_id, True, expected_mission_id, expected_team_id, True)


install_rc72_worker_lifecycle_overlay()
