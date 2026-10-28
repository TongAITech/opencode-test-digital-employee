"""RC7.2 Journey Replay orchestration.

This module executes only COMPILED_CANDIDATE Journey IR through an explicit
browser replay adapter. Runtime owns lineage, Attempt/BrowserLease validation,
ordered step dispatch, Actual/Evidence persistence and fail-fast semantics.
The adapter owns real browser actions. CI contract adapters are never treated as
Field evidence unless their adapter kind is explicitly trusted by Runtime.

Replay success does not promote a Journey Candidate to executable/official.
Benchmark and independent human review are later Phase-9 slices.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Set

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_browser_resources import BrowserAccessMode, BrowserPool
from .rc72_journey_compiler import JourneyCandidateState, install_rc72_journey_compiler_overlay

_REPLAY = "rc72_journey_replay"
_REPLAY_STEP = "rc72_journey_replay_step"
_EVENT_TYPES = {
    "RC72_JOURNEY_REPLAY_UPSERTED": (_REPLAY, "replay_id"),
    "RC72_JOURNEY_REPLAY_STEP_UPSERTED": (_REPLAY_STEP, "replay_step_id"),
}
_BUCKETS = {
    _REPLAY: "rc72_journey_replays",
    _REPLAY_STEP: "rc72_journey_replay_steps",
}


class JourneyReplayState(str, Enum):
    STARTED = "STARTED"
    PASSED = "PASSED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class JourneyReplayResult:
    replay_id: str
    state: JourneyReplayState


def _now() -> int:
    return int(time.time())


def _required(out: Dict[str, Any], name: str) -> str:
    return _contracts._require_str(out, name)


def _string_list(out: Dict[str, Any], name: str, *, allow_empty: bool = True) -> None:
    value = out.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    if not allow_empty and not value:
        raise _contracts.DomainValidationError("%s_REQUIRED" % name.upper())
    out[name] = list(value)


def _validate_replay(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "replay_id", "candidate_id", "mission_id", "release_id", "release_batch_id",
        "requirement_id", "sst_id", "obligation_id", "workitem_id", "attempt_id",
        "worker_id", "session_id", "browser_lease_id", "adapter_kind", "state",
    ):
        out[name] = _required(out, name)
    out["artifact_type"] = _REPLAY
    out["artifact_version"] = _contracts._artifact_version(out)
    try:
        out["state"] = JourneyReplayState(out["state"].upper()).value
    except ValueError as exc:
        raise _contracts.DomainValidationError("JOURNEY_REPLAY_STATE_INVALID") from exc
    if not isinstance(out.get("field_verified"), bool):
        raise _contracts.DomainValidationError("JOURNEY_REPLAY_FIELD_VERIFIED_INVALID")
    for name in ("total_step_count", "executed_step_count"):
        if not isinstance(out.get(name), int) or out[name] < 0:
            raise _contracts.DomainValidationError("JOURNEY_REPLAY_%s_INVALID" % name.upper())
    if out["executed_step_count"] > out["total_step_count"]:
        raise _contracts.DomainValidationError("JOURNEY_REPLAY_STEP_COUNT_INVALID")
    if not isinstance(out.get("started_at"), int) or out["started_at"] < 0:
        raise _contracts.DomainValidationError("JOURNEY_REPLAY_STARTED_AT_INVALID")
    completed_at = out.get("completed_at")
    if completed_at is not None and (not isinstance(completed_at, int) or completed_at < 0):
        raise _contracts.DomainValidationError("JOURNEY_REPLAY_COMPLETED_AT_INVALID")
    failure_code = out.get("failure_code")
    if failure_code is not None and (not isinstance(failure_code, str) or not failure_code.strip()):
        raise _contracts.DomainValidationError("JOURNEY_REPLAY_FAILURE_CODE_INVALID")
    if out["state"] == JourneyReplayState.STARTED.value:
        if completed_at is not None or failure_code is not None or out["executed_step_count"] != 0:
            raise _contracts.DomainValidationError("JOURNEY_REPLAY_STARTED_STATE_INVALID")
    elif out["state"] == JourneyReplayState.PASSED.value:
        if completed_at is None or failure_code is not None:
            raise _contracts.DomainValidationError("JOURNEY_REPLAY_PASS_AUDIT_INVALID")
        if out["total_step_count"] < 1 or out["executed_step_count"] != out["total_step_count"]:
            raise _contracts.DomainValidationError("JOURNEY_REPLAY_PASS_STEP_COUNT_INVALID")
    elif out["state"] == JourneyReplayState.FAILED.value:
        if completed_at is None or not failure_code or out["executed_step_count"] < 1:
            raise _contracts.DomainValidationError("JOURNEY_REPLAY_FAIL_AUDIT_INVALID")
    return out


def _validate_replay_step(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "replay_step_id", "replay_id", "candidate_id", "mission_id", "source_step_id",
        "action_type", "status",
    ):
        out[name] = _required(out, name)
    out["artifact_type"] = _REPLAY_STEP
    out["artifact_version"] = _contracts._artifact_version(out)
    if not isinstance(out.get("sequence"), int) or out["sequence"] < 1:
        raise _contracts.DomainValidationError("JOURNEY_REPLAY_STEP_SEQUENCE_INVALID")
    out["status"] = out["status"].upper()
    if out["status"] not in {"PASSED", "FAILED"}:
        raise _contracts.DomainValidationError("JOURNEY_REPLAY_STEP_STATUS_INVALID")
    _string_list(out, "actual_refs", allow_empty=False)
    _string_list(out, "evidence_refs", allow_empty=False)
    failure_code = out.get("failure_code")
    if failure_code is not None and (not isinstance(failure_code, str) or not failure_code.strip()):
        raise _contracts.DomainValidationError("JOURNEY_REPLAY_STEP_FAILURE_CODE_INVALID")
    if out["status"] == "FAILED" and not failure_code:
        raise _contracts.DomainValidationError("JOURNEY_REPLAY_STEP_FAILURE_CODE_REQUIRED")
    if out["status"] == "PASSED" and failure_code is not None:
        raise _contracts.DomainValidationError("JOURNEY_REPLAY_STEP_PASS_FAILURE_CODE_FORBIDDEN")
    if not isinstance(out.get("completed_at"), int) or out["completed_at"] < 0:
        raise _contracts.DomainValidationError("JOURNEY_REPLAY_STEP_COMPLETED_AT_INVALID")
    return out


def install_rc72_journey_replay_overlay() -> None:
    install_rc72_journey_compiler_overlay()
    _contracts.VALIDATORS[_REPLAY] = _validate_replay
    _contracts.VALIDATORS[_REPLAY_STEP] = _validate_replay_step
    for artifact_type, bucket in _BUCKETS.items():
        _truth.BUCKETS[artifact_type] = bucket
    for event_type, (artifact_type, identity) in _EVENT_TYPES.items():
        _truth.EVENT_TYPES[event_type] = (artifact_type, identity)
        _truth.IDENTITY_FIELDS[artifact_type] = identity


def _ensure_projection_buckets(truth: TruthRuntime) -> None:
    for artifact_type, bucket in _BUCKETS.items():
        if not hasattr(truth.projection, bucket):
            setattr(truth.projection, bucket, {})
        truth.projection._versions.setdefault(artifact_type, {})


def _clean_refs(value: Any, name: str) -> Sequence[str]:
    if not isinstance(value, (list, tuple)):
        raise ContractError("JOURNEY_REPLAY_ADAPTER_%s_INVALID" % name.upper())
    refs = [str(item).strip() for item in value if isinstance(item, str) and str(item).strip()]
    if not refs or len(refs) != len(value):
        raise ContractError("JOURNEY_REPLAY_ADAPTER_%s_REQUIRED" % name.upper())
    return refs


class JourneyReplayService:
    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        browser_pool: BrowserPool,
        adapter: Any,
        trusted_field_adapter_kinds: Sequence[str] = (),
    ) -> None:
        install_rc72_journey_replay_overlay()
        _ensure_projection_buckets(truth)
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("JOURNEY_REPLAY_RELEASE_ID_REQUIRED")
        if not isinstance(browser_pool, BrowserPool):
            raise ContractError("JOURNEY_REPLAY_BROWSER_POOL_REQUIRED")
        adapter_kind = getattr(adapter, "adapter_kind", None)
        if not isinstance(adapter_kind, str) or not adapter_kind.strip():
            raise ContractError("JOURNEY_REPLAY_ADAPTER_KIND_REQUIRED")
        if not callable(getattr(adapter, "execute_step", None)):
            raise ContractError("JOURNEY_REPLAY_ADAPTER_EXECUTOR_REQUIRED")
        trusted: Set[str] = {
            str(kind).strip() for kind in trusted_field_adapter_kinds
            if isinstance(kind, str) and str(kind).strip()
        }
        self.truth = truth
        self.release_id = release_id.strip()
        self.browser_pool = browser_pool
        self.adapter = adapter
        self.adapter_kind = adapter_kind.strip()
        self.trusted_field_adapter_kinds = trusted

    def install_overlay(self) -> None:
        install_rc72_journey_replay_overlay()

    def _append(self, event_type: str, payload: Dict[str, Any]):
        out = dict(payload)
        out["release_id"] = self.release_id
        out.setdefault("artifact_version", 1)
        return self.truth.append_atomic(event_type, out)

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise ContractError("JOURNEY_REPLAY_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows)))
        return rows[0]

    def _binding(
        self,
        *,
        mission_id: str,
        workitem_id: str,
        attempt_id: str,
        worker_id: str,
        session_id: str,
    ) -> Dict[str, Any]:
        rows = self.truth.query("rc72_workitem_attempt_binding", workitem_id=workitem_id)
        rows = [row for row in rows if row.get("mission_id") == mission_id]
        rows = [row for row in rows if row.get("attempt_id") == attempt_id]
        rows = [row for row in rows if row.get("worker_id") == worker_id]
        rows = [row for row in rows if row.get("session_id") == session_id]
        if len(rows) != 1:
            raise ContractError("JOURNEY_REPLAY_ATTEMPT_BINDING_MISMATCH")
        if rows[0].get("state") not in {"PREPARED", "RUNNING", "EVIDENCE_READY"}:
            raise ContractError("JOURNEY_REPLAY_ATTEMPT_NOT_ACTIVE")
        return rows[0]

    def _field_verified(self) -> bool:
        return (
            self.adapter_kind in self.trusted_field_adapter_kinds
            and bool(getattr(self.adapter, "field_verified", False))
        )

    def _adapter_outcome(self, step: Mapping[str, Any], context: Mapping[str, Any]) -> Dict[str, Any]:
        try:
            raw = self.adapter.execute_step(dict(step), dict(context))
        except Exception as exc:  # adapter failures are replay failures, never PASS
            return {
                "status": "FAILED",
                "actual_refs": ["adapter-error://%s" % step["sequence"]],
                "evidence_refs": ["adapter-error://%s" % step["sequence"]],
                "failure_code": "ADAPTER_EXCEPTION:%s" % exc.__class__.__name__,
            }
        if not isinstance(raw, Mapping):
            raise ContractError("JOURNEY_REPLAY_ADAPTER_RESULT_INVALID")
        status = str(raw.get("status") or "").upper()
        if status not in {"PASSED", "FAILED"}:
            raise ContractError("JOURNEY_REPLAY_ADAPTER_STATUS_INVALID")
        actual_refs = list(_clean_refs(raw.get("actual_refs"), "actual_refs"))
        evidence_refs = list(_clean_refs(raw.get("evidence_refs"), "evidence_refs"))
        failure_code = raw.get("failure_code")
        if status == "FAILED":
            if not isinstance(failure_code, str) or not failure_code.strip():
                failure_code = "STEP_FAILED"
            else:
                failure_code = failure_code.strip()
        else:
            failure_code = None
        return {
            "status": status,
            "actual_refs": actual_refs,
            "evidence_refs": evidence_refs,
            "failure_code": failure_code,
        }

    def _update_candidate_replay_status(self, candidate: Mapping[str, Any], status: str) -> None:
        updated = dict(candidate)
        updated.pop("artifact_type", None)
        updated["artifact_version"] = int(candidate.get("artifact_version", 1)) + 1
        updated["replay_status"] = status
        self.truth.append_atomic("RC72_JOURNEY_CANDIDATE_UPSERTED", updated)

    def replay(
        self,
        *,
        replay_id: str,
        candidate_id: str,
        workitem_id: str,
        attempt_id: str,
        worker_id: str,
        session_id: str,
        browser_lease_id: str,
    ) -> JourneyReplayResult:
        for value, name in (
            (replay_id, "replay_id"), (candidate_id, "candidate_id"),
            (workitem_id, "workitem_id"), (attempt_id, "attempt_id"),
            (worker_id, "worker_id"), (session_id, "session_id"),
            (browser_lease_id, "browser_lease_id"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ContractError("%s_REQUIRED" % name.upper())
        if self.truth.query(_REPLAY, replay_id=replay_id):
            raise ContractError("JOURNEY_REPLAY_ALREADY_EXISTS")
        candidate = self._one("rc72_journey_candidate", candidate_id=candidate_id)
        if candidate.get("state") != JourneyCandidateState.COMPILED_CANDIDATE.value:
            raise ContractError("JOURNEY_REPLAY_REQUIRES_COMPILED_CANDIDATE")
        if candidate.get("executable") is not False or candidate.get("official") is not False:
            raise ContractError("JOURNEY_REPLAY_CANDIDATE_PROMOTION_INVALID")
        steps = list(candidate.get("steps") or [])
        if not steps:
            raise ContractError("JOURNEY_REPLAY_STEPS_REQUIRED")
        mission_id = str(candidate["mission_id"])
        self._binding(
            mission_id=mission_id, workitem_id=workitem_id, attempt_id=attempt_id,
            worker_id=worker_id, session_id=session_id,
        )
        self.browser_pool.assert_usable(
            browser_lease_id=browser_lease_id,
            mission_id=mission_id,
            workitem_id=workitem_id,
            attempt_id=attempt_id,
            worker_id=worker_id,
            access_mode=BrowserAccessMode.WRITE,
        )
        field_verified = self._field_verified()
        started_at = _now()
        base = {
            "replay_id": replay_id,
            "candidate_id": candidate_id,
            "mission_id": mission_id,
            "release_batch_id": candidate["release_batch_id"],
            "requirement_id": candidate["requirement_id"],
            "sst_id": candidate["sst_id"],
            "obligation_id": candidate["obligation_id"],
            "workitem_id": workitem_id,
            "attempt_id": attempt_id,
            "worker_id": worker_id,
            "session_id": session_id,
            "browser_lease_id": browser_lease_id,
            "adapter_kind": self.adapter_kind,
            "field_verified": field_verified,
            "state": JourneyReplayState.STARTED.value,
            "total_step_count": len(steps),
            "executed_step_count": 0,
            "failure_code": None,
            "started_at": started_at,
            "completed_at": None,
        }
        self._append("RC72_JOURNEY_REPLAY_UPSERTED", base)

        final_state = JourneyReplayState.PASSED
        final_failure: Optional[str] = None
        executed = 0
        for step in sorted(steps, key=lambda item: int(item.get("sequence") or 0)):
            context = {
                "replay_id": replay_id,
                "candidate_id": candidate_id,
                "mission_id": mission_id,
                "workitem_id": workitem_id,
                "attempt_id": attempt_id,
                "worker_id": worker_id,
                "session_id": session_id,
                "browser_lease_id": browser_lease_id,
                "adapter_kind": self.adapter_kind,
                "field_verified": field_verified,
            }
            outcome = self._adapter_outcome(step, context)
            executed += 1
            replay_step_id = "%s:%d" % (replay_id, int(step["sequence"]))
            self._append(
                "RC72_JOURNEY_REPLAY_STEP_UPSERTED",
                {
                    "replay_step_id": replay_step_id,
                    "replay_id": replay_id,
                    "candidate_id": candidate_id,
                    "mission_id": mission_id,
                    "source_step_id": step["source_step_id"],
                    "sequence": int(step["sequence"]),
                    "action_type": str(step["action_type"]),
                    "status": outcome["status"],
                    "actual_refs": outcome["actual_refs"],
                    "evidence_refs": outcome["evidence_refs"],
                    "failure_code": outcome["failure_code"],
                    "completed_at": _now(),
                },
            )
            if outcome["status"] == "FAILED":
                final_state = JourneyReplayState.FAILED
                final_failure = str(outcome["failure_code"])
                break

        final = dict(base)
        final["artifact_version"] = 2
        final["state"] = final_state.value
        final["executed_step_count"] = executed
        final["failure_code"] = final_failure
        final["completed_at"] = _now()
        self._append("RC72_JOURNEY_REPLAY_UPSERTED", final)
        self._update_candidate_replay_status(candidate, final_state.value)
        return JourneyReplayResult(replay_id=replay_id, state=final_state)


install_rc72_journey_replay_overlay()
