"""Replay R1 invalidation facts into the N5/N6 runtime state machine.

The canonical R1 ledger is the source of mutation truth.  This projector does
not accept a worker-side state transition: it replays persisted
INVALIDATION_RECORDED events and asks the Center-owned invalidation coordinator
to quarantine the current PreparedAttempt and invalidate its bound
ExecutableSpec.

Projection is deliberately idempotent.  Receipts are local projection cursors,
not truth; R1 remains replayable after Center restart.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Optional, Sequence, Tuple

from rc8_runtime import CentralR1RuntimeLedger

from .runtime_invalidation import CenterRuntimeInvalidationCoordinator, RuntimeInvalidationResult


class RuntimeInvalidationProjectionError(ValueError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeInvalidationProjectionError("%s_REQUIRED" % name.upper())
    return value.strip()


def _refs(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise RuntimeInvalidationProjectionError("INVALIDATION_EVIDENCE_REFS_MUST_BE_LIST")
    refs = tuple(dict.fromkeys(_required(item, "evidence_ref") for item in value))
    if not refs:
        raise RuntimeInvalidationProjectionError("INVALIDATION_EVIDENCE_REQUIRED")
    return refs


class CenterRuntimeInvalidationProjector:
    """Apply relevant canonical R1 invalidations to current N5/N6 state.

    A receipt is written only after both N5 and N6 transitions complete.  A
    malformed or currently-unprojectable event therefore remains retryable and
    cannot be mistaken for a handled mutation.
    """

    def __init__(
        self,
        ledger: CentralR1RuntimeLedger,
        coordinator: CenterRuntimeInvalidationCoordinator,
        receipts: Optional[MutableMapping[str, Dict[str, Any]]] = None,
    ) -> None:
        self.ledger = ledger
        self.coordinator = coordinator
        self.receipts = receipts if receipts is not None else {}

    def replay(self) -> Dict[str, Any]:
        projected = 0
        ignored = 0
        pending = 0
        errors = []
        for event in self.ledger.runtime_events():
            event_id = str(event.get("event_id") or "")
            if not event_id or event_id in self.receipts:
                continue
            if str(event.get("event_type") or "") != "INVALIDATION_RECORDED":
                ignored += 1
                continue
            try:
                result = self._apply(event)
            except Exception as exc:
                pending += 1
                errors.append({"event_id": event_id, "error": str(exc)})
                continue
            if result is None:
                self.receipts[event_id] = {"status": "IGNORED", "reason": "NOT_N5_N6_RUNTIME_INVALIDATION"}
                ignored += 1
                continue
            self.receipts[event_id] = {
                "status": "PROJECTED",
                "prepared_attempt_id": result.prepared_attempt.prepared_attempt_id if result.prepared_attempt else None,
                "executable_spec_id": result.executable_spec.executable_spec_id if result.executable_spec else None,
                "reason": result.reason,
            }
            projected += 1
        return {"status": "REPLAY_COMPLETE" if not errors else "REPLAY_WITH_PENDING", "projected": projected, "pending": pending, "ignored": ignored, "errors": errors}

    def _apply(self, event: Mapping[str, Any]) -> Optional[RuntimeInvalidationResult]:
        data = event.get("data")
        if not isinstance(data, dict):
            raise RuntimeInvalidationProjectionError("INVALIDATION_EVENT_DATA_OBJECT_REQUIRED")
        reason = _required(data.get("reason"), "reason")
        supported = {
            "FROZEN_CASE_REVISION_CHANGED",
            "DATA_BINDING_CHANGED",
            "AUTH_BINDING_CHANGED",
            "ENVIRONMENT_BINDING_CHANGED",
            "ROUTE_BINDING_CHANGED",
            "REALITY_SNAPSHOT_BINDING_CHANGED",
        }
        if reason not in supported:
            return None
        test_run_id = _required(event.get("test_run_id"), "test_run_id")
        case_id = _required(event.get("case_id"), "case_id")
        attempt_id = _required(event.get("attempt_id"), "attempt_id")
        evidence_refs = _refs(data.get("evidence_refs"))
        if reason == "FROZEN_CASE_REVISION_CHANGED":
            return self.coordinator.invalidate_for_case_revision(
                test_run_id=test_run_id,
                case_id=case_id,
                attempt_id=attempt_id,
                evidence_refs=evidence_refs,
            )
        binding = reason[: -len("_BINDING_CHANGED")]
        return self.coordinator.invalidate_for_runtime_binding_change(
            binding=binding,
            test_run_id=test_run_id,
            case_id=case_id,
            attempt_id=attempt_id,
            evidence_refs=evidence_refs,
        )
