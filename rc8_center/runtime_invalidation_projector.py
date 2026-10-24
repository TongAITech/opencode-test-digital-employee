"""Replay R1 invalidation facts into the N5/N6 runtime state machine.

The canonical R1 ledger is the source of mutation truth. This projector does
not accept a worker-side state transition: it replays persisted
INVALIDATION_RECORDED events and asks the Center-owned invalidation coordinator
to quarantine the current PreparedAttempt and invalidate its bound
ExecutableSpec.

Projection is deliberately restart-safe. Successful projection receipts are
persisted back into R1, so a Center restart can reconstruct the projection
cursor from runtime truth rather than trusting process-local memory.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Optional, Tuple

from rc8_runtime import CentralR1RuntimeLedger, RuntimeProducerKind, runtime_event

from .runtime_invalidation import CenterRuntimeInvalidationCoordinator, RuntimeInvalidationResult


PROJECTION_RECEIPT_EVENT_TYPE = "N5_N6_INVALIDATION_PROJECTED"
PROJECTION_NODE_ID = "center-runtime-invalidation-projector"


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

    A receipt is persisted only after both N5 and N6 transitions complete. A
    malformed or currently-unprojectable event therefore remains retryable and
    cannot be mistaken for a handled mutation. Durable R1 receipts make replay
    idempotent across Center process restarts.
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
        self._restore_durable_receipts()

    def _restore_durable_receipts(self) -> None:
        for event in self.ledger.runtime_events(node_id=PROJECTION_NODE_ID):
            if str(event.get("event_type") or "") != PROJECTION_RECEIPT_EVENT_TYPE:
                continue
            data = event.get("data")
            if not isinstance(data, dict):
                continue
            source_event_id = str(data.get("source_event_id") or "").strip()
            if not source_event_id:
                continue
            self.receipts[source_event_id] = {
                "status": "PROJECTED",
                "prepared_attempt_id": data.get("prepared_attempt_id"),
                "executable_spec_id": data.get("executable_spec_id"),
                "reason": data.get("reason"),
                "durable_receipt_event_id": event.get("event_id"),
            }

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
                ignored += 1
                continue
            receipt = {
                "status": "PROJECTED",
                "prepared_attempt_id": result.prepared_attempt.prepared_attempt_id if result.prepared_attempt else None,
                "executable_spec_id": result.executable_spec.executable_spec_id if result.executable_spec else None,
                "reason": result.reason,
            }
            try:
                durable_event_id = self._persist_receipt(event, receipt)
            except Exception as exc:
                pending += 1
                errors.append({"event_id": event_id, "error": "PROJECTION_RECEIPT_PERSISTENCE_FAILED:%s" % exc})
                continue
            receipt["durable_receipt_event_id"] = durable_event_id
            self.receipts[event_id] = receipt
            projected += 1
        return {"status": "REPLAY_COMPLETE" if not errors else "REPLAY_WITH_PENDING", "projected": projected, "pending": pending, "ignored": ignored, "errors": errors}

    def _persist_receipt(self, source_event: Mapping[str, Any], receipt: Mapping[str, Any]) -> str:
        source_event_id = _required(source_event.get("event_id"), "source_event_id")
        test_run_id = _required(source_event.get("test_run_id"), "test_run_id")
        work_item_id = _required(source_event.get("work_item_id"), "work_item_id")
        event_id = "n5-n6-invalidation-projected:%s" % source_event_id
        sequence = self.ledger.latest_node_sequence(test_run_id=test_run_id, node_id=PROJECTION_NODE_ID) + 1
        envelope = runtime_event(
            event_id=event_id,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            node_id=PROJECTION_NODE_ID,
            producer_kind=RuntimeProducerKind.TOOL,
            producer_ref="rc8_center.runtime_invalidation_projector",
            event_type=PROJECTION_RECEIPT_EVENT_TYPE,
            sequence=sequence,
            case_id=source_event.get("case_id"),
            attempt_id=source_event.get("attempt_id"),
            refs=[source_event_id],
            data={
                "source_event_id": source_event_id,
                "prepared_attempt_id": receipt.get("prepared_attempt_id"),
                "executable_spec_id": receipt.get("executable_spec_id"),
                "reason": receipt.get("reason"),
            },
        )
        self.ledger.assert_next_node_sequence(envelope)
        self.ledger.append_runtime(envelope)
        return event_id

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
