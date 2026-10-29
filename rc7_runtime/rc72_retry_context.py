"""RC7.2 retry-context lineage and R1 audit.

This module does not decide whether a test must run.  It only makes retry
context economy auditable: a real child Attempt is related to its immutable
parent Attempt, and an observed RetryDelta is recorded in canonical R1 truth.

Mission completion stays primary.  If a child Attempt exists but no RetryDelta
has been resolved yet, the condition is persisted as UNKNOWN and execution is
not blocked merely to save model tokens.  Structural lineage contradictions
remain hard failures because they would corrupt Attempt truth.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Optional, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .attempt_lineage import LineageAwareAttemptHistory
from .models import ContractError, Task
from .rc72_context_economy import RetryDelta, SemanticWorkDescriptor
from .truth_overlay import install_rc7_truth_overlay


_RETRY_CONTEXT = "rc72_retry_context"
_RETRY_CONTEXT_EVENT = "RC72_RETRY_CONTEXT_COMPILED"
_RETRY_CONTEXT_BUCKET = "rc72_retry_contexts"

_OBSERVED = "OBSERVED"
_UNKNOWN = "UNKNOWN"

_CONTEXT_MODES = {
    "RETRY_DELTA",
    "FULL_CONTEXT_RETRY",
    "RETRY_DELTA_UNKNOWN",
}


def _now() -> int:
    return int(time.time())


def _required(out: Dict[str, Any], name: str) -> str:
    return _contracts._require_str(out, name)


def _string_list(out: Dict[str, Any], name: str) -> None:
    value = out.get(name)
    if isinstance(value, tuple):
        out[name] = list(value)
    _contracts._require_string_list(out, name)


def _optional_nonempty(out: Dict[str, Any], name: str) -> None:
    value = out.get(name)
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise _contracts.DomainValidationError("INVALID_%s" % name.upper())


def validate_rc72_retry_context(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "retry_context_id",
        "release_id",
        "mission_id",
        "workitem_id",
        "attempt_id",
        "parent_attempt_id",
        "assignment_id",
        "observation_status",
        "context_mode",
    ):
        out[name] = _required(out, name)
    if out["attempt_id"] == out["parent_attempt_id"]:
        raise _contracts.DomainValidationError("RETRY_CONTEXT_PARENT_MUST_DIFFER")

    out["observation_status"] = out["observation_status"].upper()
    if out["observation_status"] not in {_OBSERVED, _UNKNOWN}:
        raise _contracts.DomainValidationError("RETRY_CONTEXT_OBSERVATION_STATUS_INVALID")
    out["context_mode"] = out["context_mode"].upper()
    if out["context_mode"] not in _CONTEXT_MODES:
        raise _contracts.DomainValidationError("RETRY_CONTEXT_MODE_INVALID")

    for name in (
        "canonical_gap_refs",
        "explicit_gap_refs",
        "delta_evidence_refs",
        "changed_dependency_refs",
        "canonical_lineage_refs_not_in_delta",
    ):
        _string_list(out, name)

    for name in (
        "previous_attempt_summary_ref",
        "full_context_reason",
        "retry_delta_sha256",
    ):
        _optional_nonempty(out, name)

    if out["observation_status"] == _OBSERVED:
        if not out.get("previous_attempt_summary_ref") or not out.get("retry_delta_sha256"):
            raise _contracts.DomainValidationError("OBSERVED_RETRY_CONTEXT_REQUIRES_DELTA_IDENTITY")
        if out["context_mode"] == "RETRY_DELTA_UNKNOWN":
            raise _contracts.DomainValidationError("OBSERVED_RETRY_CONTEXT_CANNOT_BE_UNKNOWN_MODE")
    else:
        if out["context_mode"] != "RETRY_DELTA_UNKNOWN":
            raise _contracts.DomainValidationError("UNKNOWN_RETRY_CONTEXT_REQUIRES_UNKNOWN_MODE")
        if out.get("retry_delta_sha256") is not None:
            raise _contracts.DomainValidationError("UNKNOWN_RETRY_CONTEXT_CANNOT_CLAIM_DELTA_DIGEST")

    if out["context_mode"] == "FULL_CONTEXT_RETRY" and not out.get("full_context_reason"):
        raise _contracts.DomainValidationError("FULL_CONTEXT_RETRY_REQUIRES_REASON")
    if out["context_mode"] == "RETRY_DELTA" and out.get("full_context_reason") is not None:
        raise _contracts.DomainValidationError("DELTA_RETRY_CANNOT_CLAIM_FULL_CONTEXT_REASON")

    version = out.get("artifact_version", 1)
    if not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RETRY_CONTEXT_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    recorded_at = out.get("recorded_at")
    if not isinstance(recorded_at, int) or recorded_at < 0:
        raise _contracts.DomainValidationError("RETRY_CONTEXT_RECORDED_AT_INVALID")
    out["artifact_type"] = _RETRY_CONTEXT
    return out


def install_rc72_retry_context_overlay() -> None:
    install_rc7_truth_overlay()
    _contracts.VALIDATORS[_RETRY_CONTEXT] = validate_rc72_retry_context
    _truth.BUCKETS[_RETRY_CONTEXT] = _RETRY_CONTEXT_BUCKET
    _truth.IDENTITY_FIELDS[_RETRY_CONTEXT] = "retry_context_id"
    _truth.EVENT_TYPES[_RETRY_CONTEXT_EVENT] = (_RETRY_CONTEXT, "retry_context_id")


def _ensure_projection_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _RETRY_CONTEXT_BUCKET):
        setattr(projection, _RETRY_CONTEXT_BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_RETRY_CONTEXT, {})


def _dedupe(values: Tuple[str, ...]) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if isinstance(value, str) and value.strip()))


def _retry_delta_digest(retry: RetryDelta) -> str:
    payload = {
        "previous_attempt_summary_ref": retry.previous_attempt_summary_ref,
        "explicit_gap_refs": list(retry.explicit_gap_refs),
        "delta_evidence_refs": list(retry.delta_evidence_refs),
        "changed_dependency_refs": list(retry.changed_dependency_refs),
        "full_context_reason": retry.full_context_reason,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _retry_context_id(release_id: str, mission_id: str, workitem_id: str, attempt_id: str) -> str:
    raw = "\x1f".join((release_id, mission_id, workitem_id, attempt_id))
    return "RETRYCTX-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class RetryContextAuditService:
    """Bind retry context to real Attempt lineage and persist it in R1.

    Absence of a resolved delta is an observability/economy gap, not permission
    to cancel required testing.  It is therefore persisted as UNKNOWN.  A
    supplied delta without a real parent Attempt is a lineage contradiction and
    is rejected.
    """

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        attempt_history: LineageAwareAttemptHistory,
    ) -> None:
        install_rc72_retry_context_overlay()
        _ensure_projection_bucket(truth)
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("RETRY_CONTEXT_RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()
        self.attempt_history = attempt_history

    def _parent_attempt_id(self, attempt_id: str) -> Optional[str]:
        planned_parent = self.attempt_history.planned_parent(attempt_id)
        if planned_parent:
            return planned_parent
        entry = self.attempt_history.get(attempt_id)
        if entry is None:
            return None
        return entry.parent_attempt_id

    @staticmethod
    def _assert_descriptor_lineage(task: Task, descriptor: SemanticWorkDescriptor) -> None:
        if descriptor.workitem_id != task.task_id:
            raise ContractError("RETRY_CONTEXT_WORKITEM_MISMATCH")
        if descriptor.mission_id != task.mission_id:
            raise ContractError("RETRY_CONTEXT_MISSION_MISMATCH")
        if tuple(descriptor.gap_refs) != tuple(dict.fromkeys(task.gap_refs)):
            raise ContractError("RETRY_CONTEXT_CANONICAL_GAP_LINEAGE_MISMATCH")

    def _persist(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        existing = self.truth.query(_RETRY_CONTEXT, retry_context_id=payload["retry_context_id"])
        if len(existing) > 1:
            raise ContractError("RETRY_CONTEXT_TRUTH_NOT_UNIQUE")
        if existing:
            row = existing[0]
            old_status = row.get("observation_status")
            new_status = payload.get("observation_status")
            if old_status == _OBSERVED:
                if new_status == _UNKNOWN:
                    return row
                immutable_fields = (
                    "mission_id",
                    "workitem_id",
                    "attempt_id",
                    "parent_attempt_id",
                    "assignment_id",
                    "retry_delta_sha256",
                    "context_mode",
                )
                if all(row.get(name) == payload.get(name) for name in immutable_fields):
                    return row
                raise ContractError("RETRY_CONTEXT_IMMUTABLE")
            if old_status == _UNKNOWN and new_status == _UNKNOWN:
                return row
            if old_status != _UNKNOWN or new_status != _OBSERVED:
                raise ContractError("RETRY_CONTEXT_STATE_TRANSITION_INVALID")
            payload["artifact_version"] = int(row.get("artifact_version", 1)) + 1
        else:
            payload["artifact_version"] = 1
        self.truth.append_atomic(_RETRY_CONTEXT_EVENT, payload)
        rows = self.truth.query(_RETRY_CONTEXT, retry_context_id=payload["retry_context_id"])
        if len(rows) != 1:
            raise ContractError("RETRY_CONTEXT_PERSISTENCE_FAILED")
        return rows[0]

    def observe(
        self,
        *,
        task: Task,
        attempt_id: str,
        assignment_id: str,
        descriptor: SemanticWorkDescriptor,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(attempt_id, str) or not attempt_id.strip():
            raise ContractError("RETRY_CONTEXT_ATTEMPT_ID_REQUIRED")
        if not isinstance(assignment_id, str) or not assignment_id.strip():
            raise ContractError("RETRY_CONTEXT_ASSIGNMENT_ID_REQUIRED")
        self._assert_descriptor_lineage(task, descriptor)
        parent_attempt_id = self._parent_attempt_id(attempt_id)
        retry = descriptor.retry_delta

        if parent_attempt_id is None:
            if retry is not None:
                raise ContractError("RETRY_DELTA_REQUIRES_REAL_PARENT_ATTEMPT")
            return None
        if self.attempt_history.get(parent_attempt_id) is None:
            raise ContractError("RETRY_CONTEXT_PARENT_ATTEMPT_NOT_RECORDED")

        retry_context_id = _retry_context_id(
            self.release_id,
            task.mission_id,
            task.task_id,
            attempt_id,
        )
        base = {
            "retry_context_id": retry_context_id,
            "release_id": self.release_id,
            "mission_id": task.mission_id,
            "workitem_id": task.task_id,
            "attempt_id": attempt_id,
            "parent_attempt_id": parent_attempt_id,
            "assignment_id": assignment_id,
            "canonical_gap_refs": list(dict.fromkeys(task.gap_refs)),
            "recorded_at": _now(),
        }

        if retry is None:
            return self._persist(
                {
                    **base,
                    "observation_status": _UNKNOWN,
                    "context_mode": "RETRY_DELTA_UNKNOWN",
                    "previous_attempt_summary_ref": None,
                    "explicit_gap_refs": [],
                    "delta_evidence_refs": [],
                    "changed_dependency_refs": [],
                    "canonical_lineage_refs_not_in_delta": [],
                    "full_context_reason": None,
                    "retry_delta_sha256": None,
                }
            )

        canonical_gaps = set(task.gap_refs)
        if any(ref not in canonical_gaps for ref in retry.explicit_gap_refs):
            raise ContractError("RETRY_DELTA_GAP_NOT_IN_CANONICAL_TASK_LINEAGE")
        delta_refs = set(retry.refs())
        canonical_lineage = _dedupe(tuple(descriptor.input_refs) + tuple(descriptor.gap_refs))
        context_mode = "FULL_CONTEXT_RETRY" if retry.requires_full_context else "RETRY_DELTA"
        return self._persist(
            {
                **base,
                "observation_status": _OBSERVED,
                "context_mode": context_mode,
                "previous_attempt_summary_ref": retry.previous_attempt_summary_ref,
                "explicit_gap_refs": list(retry.explicit_gap_refs),
                "delta_evidence_refs": list(retry.delta_evidence_refs),
                "changed_dependency_refs": list(retry.changed_dependency_refs),
                "canonical_lineage_refs_not_in_delta": [
                    ref for ref in canonical_lineage if ref not in delta_refs
                ],
                "full_context_reason": retry.full_context_reason,
                "retry_delta_sha256": _retry_delta_digest(retry),
            }
        )
