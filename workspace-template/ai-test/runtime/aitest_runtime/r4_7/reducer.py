from __future__ import annotations

from dataclasses import replace
from typing import Any

from aitest_runtime.durable_core import ComposedRuntimeState, EventEnvelope, RuntimeState

from .contracts import *
from .errors import R47_REFERENCE_INVALID, R47_SCHEMA_INVALID, R47_UNKNOWN_EVENT, R47Error


def _append(values: tuple[Any, ...], value: Any, identity: str, *, revisioned: bool = False) -> tuple[Any, ...]:
    same_identity = [item for item in values if getattr(item, identity, None) == getattr(value, identity, None)]
    if not revisioned and same_identity:
        if any(item.to_dict() == value.to_dict() for item in same_identity):
            return values
        raise R47Error("R4_7_IDENTITY_CONFLICT", f"{identity} already owns a different value")
    if revisioned and any(item.to_dict() == value.to_dict() for item in same_identity):
        return values
    return values + (value,)


def _context(state: R47State, event: EventEnvelope, core_state: RuntimeState) -> None:
    if event.schema_version != SCHEMA_VERSION or event.event_type not in EVENT_TYPES:
        raise R47Error(R47_UNKNOWN_EVENT, f"unsupported R4.7 event: {event.event_type}")
    if event.mission_id != state.mission_id or event.mission_id != core_state.mission_id:
        raise R47Error("R4_7_SCOPE_MISMATCH", "event Mission differs from R4.7 state")
    if event.seq != core_state.seq or event.session_id is not None:
        raise R47Error("R4_7_SEQUENCE_MISMATCH", "R4.7 events share the core sequence and are session-independent")
    if not event.entity_id or not event.command_id or not event.correlation_id:
        raise R47Error(R47_SCHEMA_INVALID, "R4.7 event identity is required")


def _materialize_event(value: Any, event: EventEnvelope) -> Any:
    """Bind R4.7 durable record metadata to the actual EventEnvelope."""
    return replace(value, created_seq=event.seq, created_at=event.created_at, record_digest=None)


def _handoff_state(status: ReceiptStatus) -> HandoffState:
    return {
        ReceiptStatus.REFERENCE_ONLY: HandoffState.COMPLETED,
        ReceiptStatus.ACCEPTED: HandoffState.COMPLETED,
        ReceiptStatus.DUPLICATE: HandoffState.COMPLETED,
        ReceiptStatus.RECONCILIATION_REQUIRED: HandoffState.RECONCILIATION_REQUIRED,
        ReceiptStatus.REJECTED: HandoffState.REJECTED,
        ReceiptStatus.BLOCKED: HandoffState.BLOCKED,
        ReceiptStatus.CONFLICT: HandoffState.CONFLICT,
    }[status]


class R47ReducerContribution:
    """Pure event replay. It never scans legacy files or invokes an authority."""

    def reduce(self, state: R47State, event: EventEnvelope, core_state: RuntimeState) -> R47State:
        _context(state, event, core_state)
        if event.event_type == R47_LEGACY_SOURCE_OBSERVATION_RECORDED:
            value = _materialize_event(LegacySourceObservation.from_dict(event.payload["observation"]), event)
            if event.entity_id != value.observation_id or value.owner_mission_id != state.mission_id:
                raise R47Error(R47_SCHEMA_INVALID, "observation event identity/ownership mismatch")
            return replace(state, observations=_append(state.observations, value, "observation_id"))
        if event.event_type == R47_RECONCILIATION_ASSESSMENT_RECORDED:
            value = _materialize_event(ReconciliationAssessment.from_dict(event.payload["assessment"]), event)
            if event.entity_id != value.assessment_id:
                raise R47Error(R47_SCHEMA_INVALID, "assessment event identity mismatch")
            ref = value.observation_ref or {}
            if not state.observation(str(ref.get("object_id", ""))):
                raise R47Error(R47_REFERENCE_INVALID, "assessment references missing observation")
            return replace(state, assessments=_append(state.assessments, value, "assessment_id"))
        if event.event_type == R47_LEGACY_CANONICAL_MAPPING_RECORDED:
            value = _materialize_event(LegacyCanonicalMapping.from_dict(event.payload["mapping"]), event)
            if event.entity_id != value.mapping_id:
                raise R47Error(R47_SCHEMA_INVALID, "mapping event identity mismatch")
            ref = value.observation_ref or {}
            if not state.observation(str(ref.get("object_id", ""))):
                raise R47Error(R47_REFERENCE_INVALID, "mapping references missing observation")
            return replace(state, mappings=_append(state.mappings, value, "mapping_id"))
        if event.event_type == R47_RECONCILIATION_DECISION_RECORDED:
            value = _materialize_event(ReconciliationDecision.from_dict(event.payload["decision"]), event)
            if event.entity_id != value.decision_id:
                raise R47Error(R47_SCHEMA_INVALID, "decision event identity mismatch")
            assessment = value.assessment_ref or {}
            mapping = value.mapping_ref or {}
            if not state.assessment(str(assessment.get("object_id", ""))):
                raise R47Error(R47_REFERENCE_INVALID, "decision references missing assessment")
            if not state.mapping(str(mapping.get("object_id", ""))):
                raise R47Error(R47_REFERENCE_INVALID, "decision references missing mapping")
            return replace(state, decisions=_append(state.decisions, value, "decision_id"))
        if event.event_type == R47_CANONICAL_HANDOFF_CREATED:
            value = _materialize_event(CanonicalHandoffLinkage.from_dict(event.payload["handoff"]), event)
            if event.entity_id != value.handoff_id or value.state is not HandoffState.READY:
                raise R47Error(R47_SCHEMA_INVALID, "handoff creation must start in READY")
            ref = value.decision_ref or {}
            if not state.decision(str(ref.get("object_id", ""))):
                raise R47Error(R47_REFERENCE_INVALID, "handoff references missing decision")
            return replace(state, handoffs=_append(state.handoffs, value, "handoff_id", revisioned=True))
        if event.event_type == R47_CANONICAL_HANDOFF_SUBMITTED:
            raw = dict(event.payload)
            previous = state.handoff(str(raw.get("handoff_id", "")))
            if previous is None or previous.record_digest != raw.get("handoff_digest") or previous.state not in {HandoffState.READY, HandoffState.SUBMITTED}:
                raise R47Error(R47_REFERENCE_INVALID, "handoff submission is stale or not READY/SUBMITTED")
            value = _materialize_event(CanonicalHandoffLinkage.from_dict(raw["handoff"]), event)
            expected_state = HandoffState.SUBMITTED if previous.state is HandoffState.READY else HandoffState.COMPLETED
            if value.handoff_id != previous.handoff_id or value.state is not expected_state or value.revision != previous.revision + 1:
                raise R47Error(R47_SCHEMA_INVALID, "handoff submission identity/state mismatch")
            if previous.state is HandoffState.SUBMITTED:
                for field in (
                    "decision_ref", "decision_digest", "target_authority", "target_scope_ref", "target_object_ref",
                    "target_object_digest", "handoff_kind", "request_ref", "authority_command_id",
                    "authority_idempotency_key", "source_observation_ref", "source_observation_digest",
                    "assessment_ref", "mapping_ref", "policy_snapshot_ref", "source_cursor",
                ):
                    if getattr(value, field) != getattr(previous, field):
                        raise R47Error(R47_REFERENCE_INVALID, "handoff completion changed immutable linkage")
            return replace(state, handoffs=_append(state.handoffs, value, "handoff_id", revisioned=True))
        if event.event_type == R47_RECONCILIATION_RECEIPT_RECORDED:
            value = _materialize_event(ReconciliationReceipt.from_dict(event.payload["receipt"]), event)
            if event.entity_id != value.receipt_id:
                raise R47Error(R47_SCHEMA_INVALID, "receipt event identity mismatch")
            handoff_ref = value.handoff_ref or {}
            handoff = state.handoff(str(handoff_ref.get("object_id", "")))
            if handoff is None or handoff.record_digest != value.handoff_digest:
                raise R47Error(R47_REFERENCE_INVALID, "receipt handoff lineage is stale")
            prior = next((item for item in state.receipts if item.handoff_ref and (item.handoff_ref.get("object_id") if isinstance(item.handoff_ref, dict) else None) == handoff.handoff_id), None)
            if prior is not None and prior.record_digest != value.record_digest:
                # A second different authority result is a durable conflict, never LWW.
                raise R47Error("R4_7_RECEIPT_CONFLICT", "same handoff has a different receipt")
            return replace(
                state,
                receipts=_append(state.receipts, value, "receipt_id"),
            )
        raise R47Error(R47_UNKNOWN_EVENT, f"unsupported R4.7 event: {event.event_type}")


SUPPORTED_EVENTS = EVENT_TYPES

__all__ = ["R47State", "R47ReducerContribution", "SUPPORTED_EVENTS"]
