from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent

from .contracts import *
from .errors import R47_COMMAND_INVALID, R47_IDENTITY_CONFLICT, R47_REFERENCE_INVALID, R47Error


def _state(composed: ComposedRuntimeState) -> R47State:
    if not isinstance(composed, ComposedRuntimeState):
        raise R47Error(R47_COMMAND_INVALID, "R4.7 commands require composed runtime state")
    if composed.core_state.mission is None:
        raise R47Error("R4_7_SCOPE_MISMATCH", "R4.7 commands require an existing Mission")
    value = composed.extension_state(EXTENSION_ID)
    if not isinstance(value, R47State):
        raise R47Error(R47_COMMAND_INVALID, "R4.7 extension state is not registered")
    return value


def _payload(command: Any, key: str) -> dict[str, Any]:
    if command.session_id is not None or not command.idempotency_key:
        raise R47Error(R47_COMMAND_INVALID, "R4.7 commands are session-independent and require idempotency_key")
    raw = command.payload.get(key)
    if not isinstance(raw, Mapping):
        raise R47Error(R47_COMMAND_INVALID, f"payload.{key} must be an object")
    return dict(raw)


def _materialize(raw: Mapping[str, Any], composed: ComposedRuntimeState, command: Any, *, owner_stream_key: str | None = None) -> dict[str, Any]:
    value = dict(raw)
    value["owner_mission_id"] = command.mission_id
    value["owner_stream_key"] = owner_stream_key or value.get("owner_stream_key") or f"r4.7:{command.mission_id}"
    value["created_seq"] = composed.seq + 1
    value["created_at"] = f"seq:{composed.seq + 1}"
    value["correlation_id"] = command.correlation_id
    value["causation_id"] = command.command_id
    value["created_by"] = command.actor.to_dict()
    value["as_of_seq"] = int(value.get("as_of_seq", composed.seq))
    value["record_digest"] = None
    return value


def _record_event(command: Any, composed: ComposedRuntimeState, state: R47State, key: str, cls: type[Any], event_type: str, entity_type: str, identity: str, *, existing: Any | None = None) -> list[PendingEvent]:
    value = cls.from_dict(_materialize(_payload(command, key), composed, command))
    if existing is not None:
        if existing.to_dict() == value.to_dict() or existing.record_digest == value.record_digest:
            raise R47Error(R47_IDENTITY_CONFLICT, "immutable identity already exists; service should return DUPLICATE")
        raise R47Error(R47_IDENTITY_CONFLICT, "immutable identity owns a different digest")
    return [PendingEvent(event_type, entity_type, identity, {key: value.to_dict()})]


class R47CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        state = _state(composed)
        if command.type == R4_7_RECORD_LEGACY_SOURCE_OBSERVATION:
            raw = _payload(command, "observation")
            value = LegacySourceObservation.from_dict(_materialize(raw, composed, command))
            existing = state.observation(value.observation_id)
            if existing is not None:
                raise R47Error(R47_IDENTITY_CONFLICT, "observation identity already exists")
            return [PendingEvent(R47_LEGACY_SOURCE_OBSERVATION_RECORDED, "R4_7_LEGACY_SOURCE_OBSERVATION", value.observation_id, {"observation": value.to_dict()})]
        if command.type == R4_7_RECORD_RECONCILIATION_ASSESSMENT:
            raw = _payload(command, "assessment")
            value = ReconciliationAssessment.from_dict(_materialize(raw, composed, command))
            if state.assessment(value.assessment_id) is not None:
                raise R47Error(R47_IDENTITY_CONFLICT, "assessment identity already exists")
            observation = value.observation_ref or {}
            source = state.observation(str(observation.get("object_id", "")))
            if source is None or source.record_digest != value.observation_digest:
                raise R47Error(R47_REFERENCE_INVALID, "assessment observation reference is not exact")
            return [PendingEvent(R47_RECONCILIATION_ASSESSMENT_RECORDED, "R4_7_RECONCILIATION_ASSESSMENT", value.assessment_id, {"assessment": value.to_dict()})]
        if command.type == R4_7_RECORD_LEGACY_CANONICAL_MAPPING:
            raw = _payload(command, "mapping")
            value = LegacyCanonicalMapping.from_dict(_materialize(raw, composed, command))
            if state.mapping(value.mapping_id) is not None:
                raise R47Error(R47_IDENTITY_CONFLICT, "mapping identity already exists")
            observation = value.observation_ref or {}
            source = state.observation(str(observation.get("object_id", "")))
            if source is None or source.record_digest != value.observation_digest:
                raise R47Error(R47_REFERENCE_INVALID, "mapping observation reference is not exact")
            return [PendingEvent(R47_LEGACY_CANONICAL_MAPPING_RECORDED, "R4_7_LEGACY_CANONICAL_MAPPING", value.mapping_id, {"mapping": value.to_dict()})]
        if command.type == R4_7_RECORD_RECONCILIATION_DECISION:
            raw = _payload(command, "decision")
            value = ReconciliationDecision.from_dict(_materialize(raw, composed, command))
            if state.decision(value.decision_id) is not None:
                raise R47Error(R47_IDENTITY_CONFLICT, "decision identity already exists")
            assessment = value.assessment_ref or {}
            mapping = value.mapping_ref or {}
            av = state.assessment(str(assessment.get("object_id", "")))
            mv = state.mapping(str(mapping.get("object_id", "")))
            if av is None or av.record_digest != value.assessment_digest or mv is None or mv.record_digest != value.mapping_digest:
                raise R47Error(R47_REFERENCE_INVALID, "decision lineage is not exact")
            return [PendingEvent(R47_RECONCILIATION_DECISION_RECORDED, "R4_7_RECONCILIATION_DECISION", value.decision_id, {"decision": value.to_dict()})]
        if command.type == R4_7_CREATE_CANONICAL_HANDOFF:
            raw = _payload(command, "handoff")
            value = CanonicalHandoffLinkage.from_dict(_materialize(raw, composed, command))
            if value.state is not HandoffState.READY:
                raise R47Error(R47_COMMAND_INVALID, "new handoff must be READY")
            if state.handoff(value.handoff_id) is not None:
                raise R47Error(R47_IDENTITY_CONFLICT, "handoff identity already exists")
            decision = value.decision_ref or {}
            prior = state.decision(str(decision.get("object_id", "")))
            if prior is None or prior.record_digest != value.decision_digest:
                raise R47Error(R47_REFERENCE_INVALID, "handoff decision lineage is not exact")
            if prior.decision is not DecisionKind.REQUEST_CANONICAL_HANDOFF and value.handoff_kind is not HandoffKind.REFERENCE_ONLY:
                raise R47Error(R47_COMMAND_INVALID, "canonical handoff requires REQUEST_CANONICAL_HANDOFF")
            return [PendingEvent(R47_CANONICAL_HANDOFF_CREATED, "R4_7_CANONICAL_HANDOFF", value.handoff_id, {"handoff": value.to_dict()})]
        if command.type == R4_7_SUBMIT_CANONICAL_HANDOFF:
            raw = _payload(command, "handoff")
            handoff_id = str(raw.get("handoff_id") or "")
            previous = state.handoff(handoff_id)
            if previous is None:
                raise R47Error(R47_REFERENCE_INVALID, "handoff does not exist")
            if raw.get("handoff_digest") not in (None, previous.record_digest):
                raise R47Error(R47_REFERENCE_INVALID, "handoff digest is stale")
            terminal = raw.get("handoff")
            if previous.state is HandoffState.READY:
                if terminal is not None:
                    raise R47Error(R47_COMMAND_INVALID, "READY handoff submission cannot include a terminal revision")
                value = replace(previous, revision=previous.revision + 1, state=HandoffState.SUBMITTED, created_seq=composed.seq + 1, created_at=f"seq:{composed.seq + 1}", causation_id=command.command_id, correlation_id=command.correlation_id, created_by=command.actor, as_of_seq=composed.seq, record_digest=None)
            elif previous.state is HandoffState.SUBMITTED:
                if not isinstance(terminal, Mapping):
                    raise R47Error(R47_COMMAND_INVALID, "SUBMITTED handoff completion requires a terminal revision")
                candidate = CanonicalHandoffLinkage.from_dict(_materialize(terminal, composed, command))
                if candidate.handoff_id != handoff_id or candidate.state is not HandoffState.COMPLETED:
                    raise R47Error(R47_SCHEMA_INVALID, "handoff completion identity/state mismatch")
                for field in (
                    "decision_ref", "decision_digest", "target_authority", "target_scope_ref", "target_object_ref",
                    "target_object_digest", "handoff_kind", "request_ref", "authority_command_id",
                    "authority_idempotency_key", "source_observation_ref", "source_observation_digest",
                    "assessment_ref", "mapping_ref", "policy_snapshot_ref", "source_cursor",
                ):
                    if getattr(candidate, field) != getattr(previous, field):
                        raise R47Error(R47_REFERENCE_INVALID, "handoff completion changed immutable linkage")
                value = replace(
                    previous,
                    revision=previous.revision + 1,
                    state=HandoffState.COMPLETED,
                    authority_result_ref=candidate.authority_result_ref,
                    authority_result_digest=candidate.authority_result_digest,
                    created_seq=composed.seq + 1,
                    created_at=f"seq:{composed.seq + 1}",
                    causation_id=command.command_id,
                    correlation_id=command.correlation_id,
                    created_by=command.actor,
                    as_of_seq=composed.seq,
                    record_digest=None,
                )
            else:
                raise R47Error(R47_COMMAND_INVALID, "only READY or SUBMITTED handoffs may advance")
            return [PendingEvent(R47_CANONICAL_HANDOFF_SUBMITTED, "R4_7_CANONICAL_HANDOFF", handoff_id, {"handoff_id": handoff_id, "handoff_digest": previous.record_digest, "handoff": value.to_dict()})]
        if command.type == R4_7_RECORD_RECONCILIATION_RECEIPT:
            raw = _payload(command, "receipt")
            value = ReconciliationReceipt.from_dict(_materialize(raw, composed, command))
            if state.receipt(value.receipt_id) is not None:
                raise R47Error(R47_IDENTITY_CONFLICT, "receipt identity already exists")
            handoff_ref = value.handoff_ref or {}
            handoff = state.handoff(str(handoff_ref.get("object_id", "")))
            if handoff is None or handoff.record_digest != value.handoff_digest:
                raise R47Error(R47_REFERENCE_INVALID, "receipt handoff lineage is not exact")
            if handoff.state is not HandoffState.COMPLETED:
                raise R47Error(R47_COMMAND_INVALID, "receipt requires an independent COMPLETED handoff revision")
            return [PendingEvent(R47_RECONCILIATION_RECEIPT_RECORDED, "R4_7_RECONCILIATION_RECEIPT", value.receipt_id, {"receipt": value.to_dict()})]
        raise R47Error(R47_COMMAND_INVALID, f"unsupported R4.7 command: {command.type}")


SUPPORTED_COMMANDS = COMMAND_TYPES

__all__ = ["R47CommandContribution", "SUPPORTED_COMMANDS"]
