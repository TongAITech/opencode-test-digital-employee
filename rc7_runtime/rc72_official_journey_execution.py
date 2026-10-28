"""RC7.2 Official Journey worker consumption.

This is the final repository-side Phase-9 consumption slice.  It executes an
immutable Official Journey asset only from an L4/L5 ETU, bound to the canonical
WorkItem/Attempt/Worker/Session and an ACTIVE WRITE BrowserLease.  Runtime owns
orchestration and R1 Actual/Evidence truth; the adapter owns browser actions.
Execution never mutates the Official Journey asset.
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
from .rc72_journey_promotion import install_rc72_journey_promotion_overlay

_EXECUTION = "rc72_official_journey_execution"
_STEP = "rc72_official_journey_execution_step"
_EXECUTION_EVENT = "RC72_OFFICIAL_JOURNEY_EXECUTION_UPSERTED"
_STEP_EVENT = "RC72_OFFICIAL_JOURNEY_EXECUTION_STEP_UPSERTED"
_EXECUTION_BUCKET = "rc72_official_journey_executions"
_STEP_BUCKET = "rc72_official_journey_execution_steps"


class OfficialJourneyExecutionState(str, Enum):
    STARTED = "STARTED"
    PASSED = "PASSED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class OfficialJourneyExecutionResult:
    execution_id: str
    state: OfficialJourneyExecutionState


def _now() -> int:
    return int(time.time())


def _required(out: Dict[str, Any], name: str) -> str:
    return _contracts._require_str(out, name)


def _refs(out: Dict[str, Any], name: str) -> None:
    value = out.get(name)
    if not isinstance(value, list) or not value or not all(isinstance(x, str) and x.strip() for x in value):
        raise _contracts.DomainValidationError("%s_REQUIRED" % name.upper())
    out[name] = list(value)


def _validate_execution(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "execution_id", "official_asset_id", "mission_id", "release_id", "release_batch_id",
        "requirement_id", "sst_id", "obligation_id", "etu_id", "workitem_id", "attempt_id",
        "worker_id", "session_id", "browser_lease_id", "adapter_kind", "state",
    ):
        out[name] = _required(out, name)
    out["artifact_type"] = _EXECUTION
    out["artifact_version"] = _contracts._artifact_version(out)
    try:
        out["state"] = OfficialJourneyExecutionState(out["state"].upper()).value
    except ValueError as exc:
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_STATE_INVALID") from exc
    if out.get("test_level") not in {"L4", "L5"}:
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_LEVEL_INVALID")
    if not isinstance(out.get("field_verified"), bool):
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_FIELD_VERIFIED_INVALID")
    for name in ("total_step_count", "executed_step_count"):
        if not isinstance(out.get(name), int) or out[name] < 0:
            raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_%s_INVALID" % name.upper())
    if out["executed_step_count"] > out["total_step_count"]:
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_STEP_COUNT_INVALID")
    if not isinstance(out.get("started_at"), int) or out["started_at"] < 0:
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_STARTED_AT_INVALID")
    completed_at = out.get("completed_at")
    failure_code = out.get("failure_code")
    if completed_at is not None and (not isinstance(completed_at, int) or completed_at < 0):
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_COMPLETED_AT_INVALID")
    if failure_code is not None and (not isinstance(failure_code, str) or not failure_code.strip()):
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_FAILURE_CODE_INVALID")
    if out["state"] == "STARTED":
        if completed_at is not None or failure_code is not None or out["executed_step_count"] != 0:
            raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_STARTED_INVALID")
    elif out["state"] == "PASSED":
        if completed_at is None or failure_code is not None or out["executed_step_count"] != out["total_step_count"] or out["total_step_count"] < 1:
            raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_PASS_INVALID")
    else:
        if completed_at is None or not failure_code or out["executed_step_count"] < 1:
            raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_FAIL_INVALID")
    return out


def _validate_step(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "execution_step_id", "execution_id", "official_asset_id", "mission_id",
        "source_step_id", "action_type", "status",
    ):
        out[name] = _required(out, name)
    out["artifact_type"] = _STEP
    out["artifact_version"] = _contracts._artifact_version(out)
    if not isinstance(out.get("sequence"), int) or out["sequence"] < 1:
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_STEP_SEQUENCE_INVALID")
    out["status"] = out["status"].upper()
    if out["status"] not in {"PASSED", "FAILED"}:
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_STEP_STATUS_INVALID")
    _refs(out, "actual_refs")
    _refs(out, "evidence_refs")
    failure_code = out.get("failure_code")
    if out["status"] == "FAILED":
        if not isinstance(failure_code, str) or not failure_code.strip():
            raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_STEP_FAILURE_CODE_REQUIRED")
    elif failure_code is not None:
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_STEP_PASS_FAILURE_FORBIDDEN")
    if not isinstance(out.get("completed_at"), int) or out["completed_at"] < 0:
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_EXECUTION_STEP_COMPLETED_AT_INVALID")
    return out


def install_rc72_official_journey_execution_overlay() -> None:
    install_rc72_journey_promotion_overlay()
    _contracts.VALIDATORS[_EXECUTION] = _validate_execution
    _contracts.VALIDATORS[_STEP] = _validate_step
    _truth.BUCKETS[_EXECUTION] = _EXECUTION_BUCKET
    _truth.BUCKETS[_STEP] = _STEP_BUCKET
    _truth.EVENT_TYPES[_EXECUTION_EVENT] = (_EXECUTION, "execution_id")
    _truth.EVENT_TYPES[_STEP_EVENT] = (_STEP, "execution_step_id")
    _truth.IDENTITY_FIELDS[_EXECUTION] = "execution_id"
    _truth.IDENTITY_FIELDS[_STEP] = "execution_step_id"


def _ensure_buckets(truth: TruthRuntime) -> None:
    for artifact_type, bucket in ((_EXECUTION, _EXECUTION_BUCKET), (_STEP, _STEP_BUCKET)):
        if not hasattr(truth.projection, bucket):
            setattr(truth.projection, bucket, {})
        truth.projection._versions.setdefault(artifact_type, {})


def _clean_refs(value: Any, name: str) -> Sequence[str]:
    if not isinstance(value, (list, tuple)):
        raise ContractError("OFFICIAL_JOURNEY_ADAPTER_%s_INVALID" % name.upper())
    refs = [str(x).strip() for x in value if isinstance(x, str) and str(x).strip()]
    if not refs or len(refs) != len(value):
        raise ContractError("OFFICIAL_JOURNEY_ADAPTER_%s_REQUIRED" % name.upper())
    return refs


class OfficialJourneyExecutionService:
    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        browser_pool: BrowserPool,
        adapter: Any,
        trusted_field_adapter_kinds: Sequence[str] = (),
    ) -> None:
        install_rc72_official_journey_execution_overlay()
        _ensure_buckets(truth)
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("OFFICIAL_JOURNEY_RELEASE_ID_REQUIRED")
        if not isinstance(browser_pool, BrowserPool):
            raise ContractError("OFFICIAL_JOURNEY_BROWSER_POOL_REQUIRED")
        adapter_kind = getattr(adapter, "adapter_kind", None)
        if not isinstance(adapter_kind, str) or not adapter_kind.strip():
            raise ContractError("OFFICIAL_JOURNEY_ADAPTER_KIND_REQUIRED")
        if not callable(getattr(adapter, "execute_step", None)):
            raise ContractError("OFFICIAL_JOURNEY_ADAPTER_EXECUTOR_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()
        self.browser_pool = browser_pool
        self.adapter = adapter
        self.adapter_kind = adapter_kind.strip()
        self.trusted_field_adapter_kinds: Set[str] = {
            str(x).strip() for x in trusted_field_adapter_kinds if isinstance(x, str) and str(x).strip()
        }

    def install_overlay(self) -> None:
        install_rc72_official_journey_execution_overlay()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise ContractError("OFFICIAL_JOURNEY_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows)))
        return rows[0]

    def _binding(self, *, mission_id: str, workitem_id: str, attempt_id: str, worker_id: str, session_id: str) -> Dict[str, Any]:
        rows = self.truth.query("rc72_workitem_attempt_binding", workitem_id=workitem_id)
        rows = [row for row in rows if row.get("mission_id") == mission_id]
        rows = [row for row in rows if row.get("attempt_id") == attempt_id]
        rows = [row for row in rows if row.get("worker_id") == worker_id]
        rows = [row for row in rows if row.get("session_id") == session_id]
        if len(rows) != 1:
            raise ContractError("OFFICIAL_JOURNEY_ATTEMPT_BINDING_MISMATCH")
        if rows[0].get("state") not in {"PREPARED", "RUNNING", "EVIDENCE_READY"}:
            raise ContractError("OFFICIAL_JOURNEY_ATTEMPT_NOT_ACTIVE")
        return rows[0]

    def _adapter_outcome(self, step: Mapping[str, Any], context: Mapping[str, Any]) -> Dict[str, Any]:
        try:
            raw = self.adapter.execute_step(dict(step), dict(context))
        except Exception as exc:
            return {
                "status": "FAILED",
                "actual_refs": ["adapter-error://%s" % step["sequence"]],
                "evidence_refs": ["adapter-error://%s" % step["sequence"]],
                "failure_code": "ADAPTER_EXCEPTION:%s" % exc.__class__.__name__,
            }
        if not isinstance(raw, Mapping):
            raise ContractError("OFFICIAL_JOURNEY_ADAPTER_RESULT_INVALID")
        status = str(raw.get("status") or "").upper()
        if status not in {"PASSED", "FAILED"}:
            raise ContractError("OFFICIAL_JOURNEY_ADAPTER_STATUS_INVALID")
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

    def _field_verified(self) -> bool:
        return self.adapter_kind in self.trusted_field_adapter_kinds and bool(getattr(self.adapter, "field_verified", False))

    def _append(self, event_type: str, payload: Dict[str, Any]) -> None:
        out = dict(payload)
        out["release_id"] = self.release_id
        out.setdefault("artifact_version", 1)
        self.truth.append_atomic(event_type, out)

    def execute(
        self,
        *,
        execution_id: str,
        official_asset_id: str,
        workitem_id: str,
        attempt_id: str,
        worker_id: str,
        session_id: str,
        browser_lease_id: str,
    ) -> OfficialJourneyExecutionResult:
        for value, name in (
            (execution_id, "execution_id"), (official_asset_id, "official_asset_id"),
            (workitem_id, "workitem_id"), (attempt_id, "attempt_id"), (worker_id, "worker_id"),
            (session_id, "session_id"), (browser_lease_id, "browser_lease_id"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ContractError("OFFICIAL_JOURNEY_%s_REQUIRED" % name.upper())
        if self.truth.query(_EXECUTION, execution_id=execution_id):
            raise ContractError("OFFICIAL_JOURNEY_EXECUTION_ALREADY_EXISTS")
        asset = self._one("rc72_official_journey_asset", official_asset_id=official_asset_id)
        if asset.get("status") != "OFFICIAL" or asset.get("official") is not True or asset.get("executable") is not True:
            raise ContractError("OFFICIAL_JOURNEY_ASSET_NOT_EXECUTABLE")
        mission_id = str(asset["mission_id"])
        binding = self._binding(
            mission_id=mission_id, workitem_id=workitem_id, attempt_id=attempt_id,
            worker_id=worker_id, session_id=session_id,
        )
        etu = self._one("rc72_etu", etu_id=binding["etu_id"])
        test_level = str(etu.get("test_level") or "").upper()
        if test_level not in {"L4", "L5"}:
            raise ContractError("OFFICIAL_JOURNEY_REQUIRES_L4_L5_ETU")
        if etu.get("mission_id") != mission_id or etu.get("release_batch_id") != asset.get("release_batch_id"):
            raise ContractError("OFFICIAL_JOURNEY_ETU_SCOPE_MISMATCH")
        if etu.get("obligation_id") != asset.get("obligation_id"):
            raise ContractError("OFFICIAL_JOURNEY_ETU_OBLIGATION_MISMATCH")
        task = self._one("rc7_task", task_id=workitem_id)
        if task.get("mission_id") != mission_id or official_asset_id not in list(task.get("input_artifact_refs") or []):
            raise ContractError("OFFICIAL_JOURNEY_WORKITEM_SCOPE_MISMATCH")
        self.browser_pool.assert_usable(
            browser_lease_id=browser_lease_id, mission_id=mission_id,
            workitem_id=workitem_id, attempt_id=attempt_id, worker_id=worker_id,
            access_mode=BrowserAccessMode.WRITE,
        )
        steps = list(asset.get("steps") or [])
        if not steps:
            raise ContractError("OFFICIAL_JOURNEY_STEPS_REQUIRED")
        field_verified = self._field_verified()
        started_at = _now()
        base = {
            "execution_id": execution_id.strip(),
            "official_asset_id": official_asset_id.strip(),
            "mission_id": mission_id,
            "release_batch_id": asset["release_batch_id"],
            "requirement_id": asset["requirement_id"],
            "sst_id": asset["sst_id"],
            "obligation_id": asset["obligation_id"],
            "etu_id": binding["etu_id"],
            "test_level": test_level,
            "workitem_id": workitem_id,
            "attempt_id": attempt_id,
            "worker_id": worker_id,
            "session_id": session_id,
            "browser_lease_id": browser_lease_id,
            "adapter_kind": self.adapter_kind,
            "field_verified": field_verified,
            "state": "STARTED",
            "total_step_count": len(steps),
            "executed_step_count": 0,
            "failure_code": None,
            "started_at": started_at,
            "completed_at": None,
        }
        self._append(_EXECUTION_EVENT, base)
        state = OfficialJourneyExecutionState.PASSED
        failure_code: Optional[str] = None
        executed = 0
        for step in sorted(steps, key=lambda row: int(row.get("sequence") or 0)):
            context = {
                "execution_id": execution_id,
                "official_asset_id": official_asset_id,
                "mission_id": mission_id,
                "workitem_id": workitem_id,
                "attempt_id": attempt_id,
                "worker_id": worker_id,
                "session_id": session_id,
                "browser_lease_id": browser_lease_id,
                "test_level": test_level,
                "adapter_kind": self.adapter_kind,
                "field_verified": field_verified,
            }
            outcome = self._adapter_outcome(step, context)
            executed += 1
            self._append(
                _STEP_EVENT,
                {
                    "execution_step_id": "%s:%d" % (execution_id, int(step["sequence"])),
                    "execution_id": execution_id,
                    "official_asset_id": official_asset_id,
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
                state = OfficialJourneyExecutionState.FAILED
                failure_code = str(outcome["failure_code"])
                break
        final = dict(base)
        final["artifact_version"] = 2
        final["state"] = state.value
        final["executed_step_count"] = executed
        final["failure_code"] = failure_code
        final["completed_at"] = _now()
        self._append(_EXECUTION_EVENT, final)
        return OfficialJourneyExecutionResult(execution_id=execution_id.strip(), state=state)


install_rc72_official_journey_execution_overlay()
