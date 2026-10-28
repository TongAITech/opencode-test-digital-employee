"""RC7.2 fresh Worker/Session lifecycle, reviewer isolation and Captain handoff.

This layer is control-plane lifecycle truth only. It reuses canonical ETU,
rc7_task, NodeDelivery and the inherited R1. It does not implement Capability,
Browser, Data or Model leasing; those remain Phase 7 concerns.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
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
    "etu_refs", "executable_contract_refs", "data_refs", "evidence_refs",
    "gap_refs", "coverage_refs", "lease_refs",
}
_CANONICAL_REF_KEYS = {
    "etu_refs", "executable_contract_refs", "data_refs", "evidence_refs",
    "gap_refs", "coverage_refs", "lease_refs",
}
_SESSION_STATES = {"ACTIVE", "CLOSED"}
_SESSION_PURPOSES = {"EXECUTION", "REVIEW"}


def _now() -> int:
    return int(time.time())


def _new(prefix: str) -> str:
    return "%s-%s" % (prefix, uuid.uuid4().hex[:20])


def _require_string(out: Dict[str, Any], name: str) -> None:
    out[name] = _contracts._require_str(out, name)


def _require_string_list(out: Dict[str, Any], name: str) -> None:
    _contracts._require_string_list(out, name)


def _base(payload: Dict[str, Any], artifact_type: str, identity: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (identity, "mission_id", "release_id"):
        _require_string(out, name)
    out["artifact_type"] = artifact_type
    out["artifact_version"] = _contracts._artifact_version(out)
    return out


def _validate_worker_session(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _WORKER_SESSION, "session_id")
    for name in ("worker_id", "release_batch_id", "team_id", "role", "purpose", "state"):
        _require_string(out, name)
    out["purpose"] = out["purpose"].upper()
    out["state"] = out["state"].upper()
    if out["purpose"] not in _SESSION_PURPOSES:
        raise _contracts.DomainValidationError("WORKER_SESSION_PURPOSE_INVALID")
    if out["state"] not in _SESSION_STATES:
        raise _contracts.DomainValidationError("WORKER_SESSION_STATE_INVALID")
    context = out.get("context_bundle")
    if not isinstance(context, dict):
        raise _contracts.DomainValidationError("WORKER_SESSION_CONTEXT_MUST_BE_OBJECT")
    forbidden = {"chat_history", "messages", "previous_session_transcript"}.intersection(context)
    if forbidden:
        raise _contracts.DomainValidationError("WORKER_SESSION_CHAT_HISTORY_FORBIDDEN")
    if out["purpose"] == "EXECUTION":
        for name in ("etu_id", "workitem_id"):
            _require_string(out, name)
        if set(context).difference(_ALLOWED_CONTEXT_KEYS):
            raise _contracts.DomainValidationError("WORKER_SESSION_CONTEXT_KEY_NOT_ALLOWED")
    else:
        for name in ("mission_node_id", "delivery_id"):
            _require_string(out, name)
    for name in ("parent_session_id", "checkpoint_id", "close_reason"):
        value = out.get(name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    created_at = out.get("created_at")
    if not isinstance(created_at, int) or created_at < 0:
        raise _contracts.DomainValidationError("WORKER_SESSION_CREATED_AT_INVALID")
    closed_at = out.get("closed_at")
    if closed_at is not None and (not isinstance(closed_at, int) or closed_at < 0):
        raise _contracts.DomainValidationError("WORKER_SESSION_CLOSED_AT_INVALID")
    if out["state"] == "CLOSED" and not out.get("checkpoint_id"):
        raise _contracts.DomainValidationError("CLOSED_WORKER_SESSION_REQUIRES_CHECKPOINT")
    return out


def _validate_checkpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _WORKER_CHECKPOINT, "checkpoint_id")
    for name in ("session_id", "worker_id", "team_id", "role", "purpose", "reason"):
        _require_string(out, name)
    for name in ("etu_id", "workitem_id", "rotation_decision_id"):
        value = out.get(name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    context = out.get("context_bundle")
    if not isinstance(context, dict):
        raise _contracts.DomainValidationError("WORKER_CHECKPOINT_CONTEXT_MUST_BE_OBJECT")
    created_at = out.get("created_at")
    if not isinstance(created_at, int) or created_at < 0:
        raise _contracts.DomainValidationError("WORKER_CHECKPOINT_CREATED_AT_INVALID")
    return out


def _validate_rotation(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _WORKER_ROTATION, "decision_id")
    for name in ("session_id", "worker_id", "team_id", "decision"):
        _require_string(out, name)
    out["decision"] = out["decision"].upper()
    if out["decision"] not in {"ROTATE", "KEEP"}:
        raise _contracts.DomainValidationError("WORKER_ROTATION_DECISION_INVALID")
    _require_string_list(out, "reasons")
    if not isinstance(out.get("metrics"), dict):
        raise _contracts.DomainValidationError("WORKER_ROTATION_METRICS_MUST_BE_OBJECT")
    created_at = out.get("created_at")
    if not isinstance(created_at, int) or created_at < 0:
        raise _contracts.DomainValidationError("WORKER_ROTATION_CREATED_AT_INVALID")
    return out


def _validate_reviewer(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _REVIEWER_ASSIGNMENT, "review_id")
    for name in ("worker_id", "session_id", "team_id", "mission_node_id", "delivery_id"):
        _require_string(out, name)
    for name in ("criteria", "evidence_refs"):
        _require_string_list(out, name)
    if not isinstance(out.get("context_bundle"), dict):
        raise _contracts.DomainValidationError("REVIEWER_CONTEXT_MUST_BE_OBJECT")
    created_at = out.get("created_at")
    if not isinstance(created_at, int) or created_at < 0:
        raise _contracts.DomainValidationError("REVIEWER_CREATED_AT_INVALID")
    return out


def _validate_handoff(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _CAPTAIN_HANDOFF, "checkpoint_id")
    for name in ("release_batch_id", "team_id", "old_captain_session_id"):
        _require_string(out, name)
    for name in (
        "current_node_refs", "latest_delivery_refs", "latest_gate_refs", "next_workitem_ids",
        "active_worker_session_ids", "active_workitem_ids", "blocked_workitem_ids",
        "completed_workitem_ids",
    ):
        _require_string_list(out, name)
    if not isinstance(out.get("resumable_from_r1"), bool):
        raise _contracts.DomainValidationError("CAPTAIN_HANDOFF_RESUMABLE_INVALID")
    created_at = out.get("created_at")
    if not isinstance(created_at, int) or created_at < 0:
        raise _contracts.DomainValidationError("CAPTAIN_HANDOFF_CREATED_AT_INVALID")
    return out


def _validate_takeover(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _CAPTAIN_TAKEOVER, "takeover_id")
    for name in ("checkpoint_id", "release_batch_id", "team_id", "new_captain_session_id"):
        _require_string(out, name)
    for name in ("active_worker_session_ids", "next_workitem_ids"):
        _require_string_list(out, name)
    for name in ("ready", "resumable_from_r1"):
        if not isinstance(out.get(name), bool):
            raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    created_at = out.get("created_at")
    if not isinstance(created_at, int) or created_at < 0:
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
            "max_workitems", "max_steps", "max_tokens", "max_tool_calls",
            "max_compactions", "max_retries", "max_age_seconds",
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
            "workitem_count", "step_count", "token_usage", "tool_call_count",
            "compaction_count", "retry_count", "age_seconds",
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

    def _append(self, event_type: str, payload: Dict[str, Any]):
        payload = dict(payload)
        payload["release_id"] = self.release_id
        payload.setdefault("artifact_version", 1)
        return self.truth.append_atomic(event_type, payload)

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise ContractError("WORKER_LIFECYCLE_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows)))
        return rows[0]

    def _batch_for_mission(self, mission_id: str) -> Dict[str, Any]:
        return self._one("rc72_release_batch", mission_id=mission_id)

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
        worker_id = _new("WRK")
        session_id = _new("SES")
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
        # Phase 5 default is one ETU per session. Rebinding to another ETU is
        # intentionally forbidden even while the old session is active.
        if session.get("etu_id") != etu_id or session.get("workitem_id") != workitem_id:
            raise ContractError("WORKER_SESSION_REUSE_FORBIDDEN")
        refs = self._canonical_refs(canonical_refs)
        context = dict(session["context_bundle"])
        for key in _CANONICAL_REF_KEYS:
            if context.get(key, []) != refs[key]:
                raise ContractError("WORKER_SESSION_CONTEXT_DRIFT")
        return FreshWorkerAssignment(session["worker_id"], session_id, context)

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
        checkpoint = {
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
            "reason": reason,
            "context_bundle": dict(session["context_bundle"]),
            "created_at": _now(),
        }
        # Order is a safety invariant: durable checkpoint first, then close.
        self._append("RC72_WORKER_CHECKPOINT_UPSERTED", checkpoint)
        closed = dict(session)
        closed["state"] = "CLOSED"
        closed["checkpoint_id"] = checkpoint_id
        closed["close_reason"] = reason
        closed["closed_at"] = _now()
        closed["artifact_version"] = int(session.get("artifact_version", 1)) + 1
        closed.pop("artifact_type", None)
        self._append("RC72_WORKER_SESSION_UPSERTED", closed)
        return WorkerCheckpointResult(checkpoint_id, session_id)

    def evaluate_rotation(self, session_id: str, metrics: WorkerSessionMetrics) -> RotationDecision:
        session = self._one(_WORKER_SESSION, session_id=session_id)
        if session.get("state") != "ACTIVE":
            raise ContractError("WORKER_SESSION_NOT_ACTIVE")
        reasons: List[str] = []
        checks = (
            (metrics.workitem_count >= self.policy.max_workitems, "MAX_WORKITEMS"),
            (metrics.step_count > self.policy.max_steps, "MAX_STEPS"),
            (metrics.token_usage > self.policy.max_tokens, "MAX_TOKENS"),
            (metrics.tool_call_count > self.policy.max_tool_calls, "MAX_TOOL_CALLS"),
            (metrics.compaction_count >= self.policy.max_compactions, "MAX_COMPACTIONS"),
            (metrics.retry_count >= self.policy.max_retries, "MAX_RETRIES"),
            (metrics.age_seconds > self.policy.max_age_seconds, "MAX_AGE"),
            (float(metrics.context_pressure) >= float(self.policy.max_context_pressure), "CONTEXT_PRESSURE"),
        )
        for triggered, reason in checks:
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
        required = [
            row for row in self.truth.query(_WORKER_ROTATION, session_id=session_id)
            if row.get("decision") == "ROTATE" and row.get("metrics") == metrics.as_dict()
        ]
        if required:
            decision = sorted(required, key=lambda row: int(row.get("created_at", 0)))[-1]
            decision_id = decision["decision_id"]
        else:
            fresh_decision = self.evaluate_rotation(session_id, metrics)
            if not fresh_decision.required:
                raise ContractError("WORKER_ROTATION_NOT_REQUIRED")
            decision_id = fresh_decision.decision_id
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
        criteria_list = list(criteria)
        evidence_list = list(evidence_refs)
        if not criteria_list or not all(isinstance(v, str) and v.strip() for v in criteria_list):
            raise ContractError("REVIEWER_CRITERIA_REQUIRED")
        if not all(isinstance(v, str) and v.strip() for v in evidence_list):
            raise ContractError("REVIEWER_EVIDENCE_REFS_INVALID")
        excluded = set(excluded_session_ids)
        session_id = _new("REVSES")
        while session_id in excluded:
            session_id = _new("REVSES")
        worker_id = _new("REVWRK")
        review_id = _new("REV")
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
        active_states = {"READY", "LEASED", "RUNNING"}
        blocked_states = {"BLOCKED"}
        completed_states = {"COMPLETED", "CANCELLED"}
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
                "active_workitem_ids": sorted(row["task_id"] for row in tasks if str(row.get("state")) in active_states),
                "blocked_workitem_ids": sorted(row["task_id"] for row in tasks if str(row.get("state")) in blocked_states),
                "completed_workitem_ids": sorted(row["task_id"] for row in tasks if str(row.get("state")) in completed_states),
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
        payload = {
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
        }
        self._append("RC72_CAPTAIN_TAKEOVER_UPSERTED", payload)
        return CaptainTakeoverReadiness(
            takeover_id=takeover_id,
            ready=True,
            mission_id=expected_mission_id,
            team_id=expected_team_id,
            resumable_from_r1=True,
        )


install_rc72_worker_lifecycle_overlay()
