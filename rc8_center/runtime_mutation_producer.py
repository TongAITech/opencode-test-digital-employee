"""Automatic Center producer for N5/N6 invalidation from runtime mutation facts."""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from rc8_runtime import CentralR1RuntimeLedger, RuntimeEventEnvelope, RuntimeProducerKind
from rc8_runtime.governance import AttemptStatus

from .control_plane import CenterControlError
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
_TERMINAL_ATTEMPT_EVENT_TYPES = {"ATTEMPT_COMPLETED", "ATTEMPT_FAILED_RUNTIME", "ATTEMPT_BLOCKED"}


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
    normalized = tuple(dict.fromkeys(_required(value, "evidence_ref") for value in refs))
    if not normalized:
        raise RuntimeMutationProductionError("RUNTIME_MUTATION_EVIDENCE_REQUIRED")
    return normalized


def _case_id_from_scope_refs(scope_refs: Sequence[str]) -> Optional[str]:
    values = [
        str(ref).split(":", 1)[1].strip()
        for ref in scope_refs
        if str(ref).startswith("case:") and str(ref).split(":", 1)[1].strip()
    ]
    values = list(dict.fromkeys(values))
    if len(values) > 1:
        raise CenterControlError("WORK_ITEM_CASE_SCOPE_AMBIGUOUS")
    return values[0] if values else None


class CenterRuntimeMutationProducer:
    def __init__(self, *, ledger: CentralR1RuntimeLedger, invalidation_service: CenterRuntimeInvalidationService, executable_readiness: CenterExecutableReadinessService) -> None:
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
                    raise RuntimeMutationProductionError("RUNTIME_MUTATION_DID_NOT_CHANGE_FROZEN_AUTHORITY")
                produced += 1
            except Exception as exc:
                pending += 1
                errors.append({"event_id": str(event.get("event_id") or ""), "error": str(exc)})
        return {"status": "REPLAY_COMPLETE" if not errors else "REPLAY_WITH_PENDING", "produced": produced, "already_recorded": already_recorded, "pending": pending, "ignored": ignored, "errors": errors}

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
            raise RuntimeMutationProductionError("RUNTIME_MUTATION_REQUIRES_TOOL_PRODUCER")
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
            current = self.executable_readiness.repository.current_for_attempt(test_run_id, case_id, attempt_id)
            if current is None:
                raise RuntimeMutationProductionError("CASE_REVISION_MUTATION_REQUIRES_CURRENT_EXECUTABLE_SPEC")
            event_id = self.invalidation_service.record_case_revision_change(
                test_run_id=test_run_id, work_item_id=work_item_id, case_id=case_id, attempt_id=attempt_id,
                frozen_case_revision_ref=current.frozen_case_ref, observed_case_revision_ref=observed_ref,
                evidence_refs=evidence_refs, source_runtime_event_id=source_event_id,
            )
        else:
            event_id = self.invalidation_service.record_runtime_binding_change(
                test_run_id=test_run_id, work_item_id=work_item_id, case_id=case_id, attempt_id=attempt_id,
                binding=_BINDING_EVENT_TYPES[event_type], observed_ref=observed_ref,
                evidence_refs=evidence_refs, source_runtime_event_id=source_event_id,
            )
        if event_id is None:
            raise RuntimeMutationProductionError("RUNTIME_MUTATION_DID_NOT_CHANGE_FROZEN_AUTHORITY")
        return event_id

    def _existing_invalidation(self, source_event: object) -> Optional[str]:
        source_event_id = _required(_field(source_event, "event_id"), "source_runtime_event_id")
        test_run_id = _required(_field(source_event, "test_run_id"), "test_run_id")
        work_item_id = _required(_field(source_event, "work_item_id"), "work_item_id")
        case_id = _required(_field(source_event, "case_id"), "case_id")
        attempt_id = _required(_field(source_event, "attempt_id"), "attempt_id")
        for event in self.ledger.runtime_events(test_run_id=test_run_id):
            if str(event.get("event_type") or "") != "INVALIDATION_RECORDED":
                continue
            data = event.get("data")
            if not isinstance(data, dict) or str(data.get("source_runtime_event_id") or "") != source_event_id:
                continue
            identity_matches = (
                str(event.get("work_item_id") or "") == work_item_id
                and str(event.get("case_id") or "") == case_id
                and str(event.get("attempt_id") or "") == attempt_id
            )
            if not identity_matches:
                raise RuntimeMutationProductionError("SOURCE_RUNTIME_EVENT_INVALIDATION_IDENTITY_CONFLICT")
            return _required(event.get("event_id"), "invalidation_event_id")
        return None


class RuntimeMutationAwareFormalCenterControlPlane:
    """Center-owned invalidation and Attempt-start authority."""
    def __init__(self, control_plane: object, mutation_producer: CenterRuntimeMutationProducer) -> None:
        self._control_plane = control_plane
        self.runtime_mutation_producer = mutation_producer

    def __getattr__(self, name: str) -> Any:
        return getattr(self._control_plane, name)

    def start_work_item(self, work_item_id: str, node_id: str, lease_id: str):
        work = self._control_plane._require_active_lease(work_item_id, node_id, lease_id)
        self._ensure_center_attempt_started(work, node_id=node_id, lease_id=lease_id)
        return self._control_plane.start_work_item(work_item_id, node_id, lease_id)

    def append_runtime_event(self, event: RuntimeEventEnvelope, *, lease_id: str) -> Dict[str, object]:
        work = self._control_plane.authorize_work_item_write(test_run_id=event.test_run_id, work_item_id=event.work_item_id, node_id=event.node_id, lease_id=lease_id)
        self._validate_attempt_event(work, event)
        result = self._control_plane.append_runtime_event(event, lease_id=lease_id)
        invalidation_event_id = self.runtime_mutation_producer.process_runtime_event(event)
        if invalidation_event_id is not None:
            result = dict(result)
            result["runtime_invalidation"] = {"status": "PROJECTED", "invalidation_event_id": invalidation_event_id, "source_runtime_event_id": event.event_id}
        return result

    def _ensure_center_attempt_started(self, work: object, *, node_id: str, lease_id: str) -> None:
        stage_instance_id = self._control_plane.stage_instance_id_for_work_item(work.identity.work_item_id)
        if stage_instance_id is None:
            return
        governance_repository = getattr(self._control_plane.projector, "governance_repository", None)
        if governance_repository is None:
            raise CenterControlError("GOVERNANCE_REPOSITORY_REQUIRED_FOR_ATTEMPT_START")
        stage = governance_repository.get_stage(stage_instance_id)
        if stage is None:
            raise CenterControlError("MISSION_STAGE_REQUIRED_FOR_ATTEMPT_START")
        if str(stage.test_run_id) != str(work.identity.test_run_id):
            raise CenterControlError("WORK_ITEM_STAGE_TEST_RUN_MISMATCH")
        input_snapshot_ref = str(stage.scope_version or "").strip()
        if not input_snapshot_ref:
            raise CenterControlError("ATTEMPT_INPUT_SNAPSHOT_REQUIRED")
        case_id = _case_id_from_scope_refs(work.identity.scope_refs)
        event_id = "center-attempt-started:%s:%s" % (work.identity.work_item_id, lease_id)
        existing = None
        for item in self._control_plane.runtime_ledger.runtime_events(test_run_id=work.identity.test_run_id, work_item_id=work.identity.work_item_id, node_id=node_id):
            if str(item.get("event_id") or "") == event_id:
                existing = item
                break
        if existing is None:
            started_at = int(self._control_plane._now())
            sequence = self._control_plane.runtime_ledger.latest_node_sequence(test_run_id=work.identity.test_run_id, node_id=node_id) + 1
            event = RuntimeEventEnvelope(
                event_id=event_id, test_run_id=work.identity.test_run_id, work_item_id=work.identity.work_item_id,
                node_id=node_id, producer_kind=RuntimeProducerKind.NODE_AGENT, producer_ref="rc8-center-attempt-authority",
                event_type="ATTEMPT_STARTED", sequence=sequence, case_id=case_id, attempt_id=lease_id, refs=[],
                data={"stage_instance_id": stage_instance_id, "input_snapshot_ref": input_snapshot_ref, "started_at": started_at,
                      "action_refs": [], "assertion_refs": [], "evidence_refs": [], "coverage_refs": [], "gap_refs": [],
                      "defect_refs": [], "authority_ref": "lease:%s" % lease_id}, occurred_at=started_at,
            )
            self._control_plane.runtime_ledger.assert_next_node_sequence(event)
            self._control_plane.runtime_ledger.append_runtime(event)
        else:
            data = existing.get("data") if isinstance(existing.get("data"), dict) else {}
            existing_case_id = existing.get("case_id")
            identity_matches = (
                str(existing.get("event_type") or "") == "ATTEMPT_STARTED"
                and str(existing.get("attempt_id") or "") == str(lease_id)
                and str(existing.get("node_id") or "") == str(node_id)
                and str(existing.get("producer_ref") or "") == "rc8-center-attempt-authority"
                and (str(existing_case_id) if existing_case_id is not None else None) == case_id
                and str(data.get("stage_instance_id") or "") == str(stage_instance_id)
                and str(data.get("input_snapshot_ref") or "") == input_snapshot_ref
            )
            if not identity_matches:
                raise CenterControlError("CENTER_ATTEMPT_START_EVENT_CONFLICT")
        projection = self._control_plane.projector.ingest({"event_id": event_id})
        projected = projection.get("projection") if isinstance(projection, dict) else None
        status = str(projected.get("status") or "") if isinstance(projected, dict) else ""
        if status != "PROJECTED":
            detail = str(projected.get("detail") or "UNKNOWN") if isinstance(projected, dict) else "UNKNOWN"
            raise CenterControlError("ATTEMPT_START_PROJECTION_REQUIRED:%s" % detail)

    def _validate_attempt_event(self, work: object, event: RuntimeEventEnvelope) -> None:
        event_type = str(event.event_type or "").strip().upper()
        if not event_type.startswith("ATTEMPT_"):
            return
        stage_instance_id = self._control_plane.stage_instance_id_for_work_item(work.identity.work_item_id)
        if stage_instance_id is None:
            return
        if event_type == "ATTEMPT_STARTED":
            raise CenterControlError("CENTER_OWNS_ATTEMPT_START")
        if event_type not in _TERMINAL_ATTEMPT_EVENT_TYPES:
            raise CenterControlError("ATTEMPT_EVENT_TYPE_INVALID:%s" % event_type)
        active_attempt_id = str(work.lease_id or "").strip()
        if not active_attempt_id or str(event.attempt_id or "").strip() != active_attempt_id:
            raise CenterControlError("ATTEMPT_ID_MUST_MATCH_ACTIVE_LEASE")
        governance_repository = getattr(self._control_plane.projector, "governance_repository", None)
        if governance_repository is None:
            raise CenterControlError("GOVERNANCE_REPOSITORY_REQUIRED_FOR_ATTEMPT_EVENT")
        current = governance_repository.get_attempt(active_attempt_id)
        if current is None or current.status != AttemptStatus.STARTED:
            raise CenterControlError("CENTER_STARTED_ATTEMPT_REQUIRED")
        if current.test_run_id != work.identity.test_run_id:
            raise CenterControlError("ATTEMPT_TEST_RUN_AUTHORITY_MISMATCH")
        if current.work_item_id != work.identity.work_item_id:
            raise CenterControlError("ATTEMPT_WORK_ITEM_AUTHORITY_MISMATCH")
        if current.stage_instance_id != stage_instance_id:
            raise CenterControlError("ATTEMPT_STAGE_AUTHORITY_MISMATCH")
        if current.producer_node_id != event.node_id:
            raise CenterControlError("ATTEMPT_NODE_AUTHORITY_MISMATCH")
        if current.case_id is None:
            if event.case_id is not None:
                raise CenterControlError("ATTEMPT_CASE_AUTHORITY_MISMATCH")
        elif event.case_id != current.case_id:
            raise CenterControlError("ATTEMPT_CASE_AUTHORITY_MISMATCH")
        data = event.data if isinstance(event.data, dict) else {}
        supplied_stage = data.get("stage_instance_id")
        if supplied_stage is not None and str(supplied_stage) != current.stage_instance_id:
            raise CenterControlError("ATTEMPT_STAGE_AUTHORITY_MISMATCH")
        supplied_snapshot = data.get("input_snapshot_ref")
        if supplied_snapshot is not None and str(supplied_snapshot) != current.input_snapshot_ref:
            raise CenterControlError("ATTEMPT_INPUT_SNAPSHOT_AUTHORITY_MISMATCH")
