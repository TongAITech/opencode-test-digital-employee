"""Automatic Center producer for N5/N6 invalidation from runtime mutation facts.

Execution nodes may report observed mutation facts, but they do not choose which
Center state becomes invalid. A lease-authorized source fact is first persisted
to canonical R1 by the formal control plane. This producer then resolves the
current Center-owned N5/N6 authority, records a canonical INVALIDATION_RECORDED
fact, and requires its durable projection before execution may continue.

Replay scans canonical R1 so a crash after the source mutation write cannot
restore stale PREPARED/READY state on Center restart.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from rc8_runtime import CentralR1RuntimeLedger, RuntimeEventEnvelope

from .executable_readiness import CenterExecutableReadinessService
from .runtime_invalidation_service import CenterRuntimeInvalidationService


class RuntimeMutationProductionError(ValueError):
    pass


_BINDING_EVENT_TYPES = {
    "AUTH_CHANGED": "AUTH",
    "DATA_CHANGED": "DATA",
    "ENVIRONMENT_CHANGED": "ENVIRONMENT",
    "ROUTE_CHANGED": "ROUTE",
    "REALITY_CHANGED": "REALITY_SNAPSHOT",
}
_CASE_REVISION_EVENT_TYPE = "CASE_REVISION_CHANGED"
_SUPPORTED_EVENT_TYPES = set(_BINDING_EVENT_TYPES) | {_CASE_REVISION_EVENT_TYPE}


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeMutationProductionError("%s_REQUIRED" % name.upper())
    return value.strip()


def _field(event: object, name: str) -> Any:
    if isinstance(event, Mapping):
        return event.get(name)
    return getattr(event, name, None)


def _data(event: object) -> Mapping[str, Any]:
    value = _field(event, "data")
    if not isinstance(value, Mapping):
        raise RuntimeMutationProductionError("RUNTIME_MUTATION_DATA_OBJECT_REQUIRED")
    return value


def _evidence_refs(event: object) -> Tuple[str, ...]:
    refs = _field(event, "refs")
    if not isinstance(refs, (list, tuple)):
        raise RuntimeMutationProductionError("RUNTIME_MUTATION_EVIDENCE_REFS_MUST_BE_LIST")
    normalized = tuple(
        dict.fromkeys(_required(value, "evidence_ref") for value in refs)
    )
    if not normalized:
        raise RuntimeMutationProductionError("RUNTIME_MUTATION_EVIDENCE_REQUIRED")
    return normalized


class CenterRuntimeMutationProducer:
    """Derive canonical invalidation from already-persisted runtime mutation facts."""

    def __init__(
        self,
        *,
        ledger: CentralR1RuntimeLedger,
        invalidation_service: CenterRuntimeInvalidationService,
        executable_readiness: CenterExecutableReadinessService,
    ) -> None:
        self.ledger = ledger
        self.invalidation_service = invalidation_service
        self.executable_readiness = executable_readiness

    def replay(self) -> Dict[str, object]:
        produced = 0
        already_recorded = 0
        ignored = 0
        pending = 0
        errors = []
        for event in self.ledger.runtime_events():
            event_type = str(event.get("event_type") or "").strip().upper()
            if event_type not in _SUPPORTED_EVENT_TYPES:
                ignored += 1
                continue
            try:
                existing = self._existing_invalidation(event)
                if existing is not None:
                    self.invalidation_service.ensure_projected(existing)
                    already_recorded += 1
                    continue
                event_id = self.process_runtime_event(event)
                if event_id is None:
                    raise RuntimeMutationProductionError(
                        "RUNTIME_MUTATION_DID_NOT_CHANGE_FROZEN_AUTHORITY"
                    )
                produced += 1
            except Exception as exc:
                pending += 1
                errors.append(
                    {
                        "event_id": str(event.get("event_id") or ""),
                        "error": str(exc),
                    }
                )
        return {
            "status": "REPLAY_COMPLETE" if not errors else "REPLAY_WITH_PENDING",
            "produced": produced,
            "already_recorded": already_recorded,
            "pending": pending,
            "ignored": ignored,
            "errors": errors,
        }

    def process_runtime_event(self, event: object) -> Optional[str]:
        if not isinstance(event, (RuntimeEventEnvelope, Mapping)):
            raise RuntimeMutationProductionError("RUNTIME_EVENT_ENVELOPE_REQUIRED")
        event_type = _required(_field(event, "event_type"), "event_type").upper()
        if event_type not in _SUPPORTED_EVENT_TYPES:
            return None

        source_event_id = _required(_field(event, "event_id"), "source_runtime_event_id")
        producer_kind = _field(event, "producer_kind")
        producer_kind_value = getattr(producer_kind, "value", producer_kind)
        if str(producer_kind_value or "").strip().upper() != "TOOL":
            raise RuntimeMutationProductionError(
                "RUNTIME_MUTATION_REQUIRES_TOOL_PRODUCER"
            )
        existing = self._existing_invalidation(event)
        if existing is not None:
            return self.invalidation_service.ensure_projected(existing)

        test_run_id = _required(_field(event, "test_run_id"), "test_run_id")
        work_item_id = _required(_field(event, "work_item_id"), "work_item_id")
        case_id = _required(_field(event, "case_id"), "case_id")
        attempt_id = _required(_field(event, "attempt_id"), "attempt_id")
        evidence_refs = _evidence_refs(event)
        observed_ref = _required(_data(event).get("observed_ref"), "observed_ref")

        if event_type == _CASE_REVISION_EVENT_TYPE:
            current = self.executable_readiness.repository.current_for_attempt(
                test_run_id,
                case_id,
                attempt_id,
            )
            if current is None:
                raise RuntimeMutationProductionError(
                    "CASE_REVISION_MUTATION_REQUIRES_CURRENT_EXECUTABLE_SPEC"
                )
            event_id = self.invalidation_service.record_case_revision_change(
                test_run_id=test_run_id,
                work_item_id=work_item_id,
                case_id=case_id,
                attempt_id=attempt_id,
                frozen_case_revision_ref=current.frozen_case_ref,
                observed_case_revision_ref=observed_ref,
                evidence_refs=evidence_refs,
                source_runtime_event_id=source_event_id,
            )
        else:
            event_id = self.invalidation_service.record_runtime_binding_change(
                test_run_id=test_run_id,
                work_item_id=work_item_id,
                case_id=case_id,
                attempt_id=attempt_id,
                binding=_BINDING_EVENT_TYPES[event_type],
                observed_ref=observed_ref,
                evidence_refs=evidence_refs,
                source_runtime_event_id=source_event_id,
            )
        if event_id is None:
            raise RuntimeMutationProductionError(
                "RUNTIME_MUTATION_DID_NOT_CHANGE_FROZEN_AUTHORITY"
            )
        return event_id

    def _existing_invalidation(self, source_event: object) -> Optional[str]:
        source_event_id = _required(
            _field(source_event, "event_id"),
            "source_runtime_event_id",
        )
        test_run_id = _required(_field(source_event, "test_run_id"), "test_run_id")
        work_item_id = _required(_field(source_event, "work_item_id"), "work_item_id")
        case_id = _required(_field(source_event, "case_id"), "case_id")
        attempt_id = _required(_field(source_event, "attempt_id"), "attempt_id")
        for event in self.ledger.runtime_events(test_run_id=test_run_id):
            if str(event.get("event_type") or "") != "INVALIDATION_RECORDED":
                continue
            data = event.get("data")
            if not isinstance(data, dict):
                continue
            if str(data.get("source_runtime_event_id") or "") != source_event_id:
                continue
            identity_matches = (
                str(event.get("work_item_id") or "") == work_item_id
                and str(event.get("case_id") or "") == case_id
                and str(event.get("attempt_id") or "") == attempt_id
            )
            if not identity_matches:
                raise RuntimeMutationProductionError(
                    "SOURCE_RUNTIME_EVENT_INVALIDATION_IDENTITY_CONFLICT"
                )
            return _required(event.get("event_id"), "invalidation_event_id")
        return None


class RuntimeMutationAwareFormalCenterControlPlane:
    """Composition wrapper that derives invalidation only after canonical source persistence."""

    def __init__(
        self,
        control_plane: object,
        mutation_producer: CenterRuntimeMutationProducer,
    ) -> None:
        self._control_plane = control_plane
        self.runtime_mutation_producer = mutation_producer

    def __getattr__(self, name: str) -> Any:
        return getattr(self._control_plane, name)

    def append_runtime_event(
        self,
        event: RuntimeEventEnvelope,
        *,
        lease_id: str,
    ) -> Dict[str, object]:
        result = self._control_plane.append_runtime_event(event, lease_id=lease_id)
        invalidation_event_id = self.runtime_mutation_producer.process_runtime_event(event)
        if invalidation_event_id is not None:
            result = dict(result)
            result["runtime_invalidation"] = {
                "status": "PROJECTED",
                "invalidation_event_id": invalidation_event_id,
                "source_runtime_event_id": event.event_id,
            }
        return result
