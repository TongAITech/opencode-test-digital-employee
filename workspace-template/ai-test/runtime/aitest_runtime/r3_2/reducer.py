from __future__ import annotations

from dataclasses import replace

from aitest_runtime.durable_core import EventEnvelope, RuntimeState

from .contracts import (
    CHANGE_IMPACT_DERIVED,
    RECONCILIATION_CREATED,
    RECONCILIATION_REUSED,
    ChangeImpactDerivation,
    R32Error,
    R32State,
    ReconciliationSnapshot,
    ReuseReference,
)


def _payload(event: EventEnvelope, required: set[str]) -> dict:
    payload = dict(event.payload)
    if set(payload) != required:
        raise R32Error("R3_2_EVENT_INVALID", f"{event.event_type} payload contains unknown or missing fields")
    return payload


class R32ReducerContribution:
    def reduce(self, state: R32State, event: EventEnvelope, core_state: RuntimeState) -> R32State:
        if not isinstance(state, R32State):
            raise R32Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.2 state")
        if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id:
            raise R32Error("R3_2_EVENT_INVALID", "R3.2 Event Mission identity mismatch")
        if core_state.seq != event.seq:
            raise R32Error("R3_2_EVENT_INVALID", "R3.2 Event does not share the Core sequence")
        if event.event_type == CHANGE_IMPACT_DERIVED:
            raw = dict(_payload(event, {"derivation"})["derivation"])
            raw.update({"created_seq": event.seq, "created_at": event.created_at})
            derivation = ChangeImpactDerivation.from_dict(raw)
            if derivation.identity.mission_id != event.mission_id:
                raise R32Error("R3_2_EVENT_INVALID", "derivation mission mismatch")
            if f"r1-event:{event.correlation_id}" not in derivation.evidence_references:
                raise R32Error("R3_2_EVIDENCE_REFERENCE_MISSING", "derivation does not reference R1 Event correlation")
            if state.derivation(derivation.derivation_fingerprint) is not None:
                raise R32Error("R3_2_EVENT_INVALID", "derivation fingerprint is not immutable")
            if any(item.derivation_version_id == derivation.derivation_version_id for item in state.derivations):
                raise R32Error("R3_2_EVENT_INVALID", "derivation version identity is not immutable")
            return replace(state, derivations=state.derivations + (derivation,))
        if event.event_type == RECONCILIATION_CREATED:
            payload = _payload(event, {"reconciliation", "derivation_fingerprint"})
            raw = dict(payload["reconciliation"])
            raw.update({"created_seq": event.seq, "created_at": event.created_at})
            reconciliation = ReconciliationSnapshot.from_dict(raw)
            if reconciliation.derivation_fingerprint != payload["derivation_fingerprint"]:
                raise R32Error("R3_2_EVENT_INVALID", "reconciliation fingerprint mismatch")
            if state.derivation(reconciliation.derivation_fingerprint) is None:
                raise R32Error("R3_2_EVENT_INVALID", "reconciliation references a missing derivation")
            if state.reconciliation(reconciliation.reconciliation_id) is not None:
                raise R32Error("R3_2_EVENT_INVALID", "reconciliation identity is not immutable")
            return replace(state, reconciliations=state.reconciliations + (reconciliation,))
        if event.event_type == RECONCILIATION_REUSED:
            payload = _payload(event, {"derivation_version_id", "derivation_fingerprint", "idempotency_key"})
            existing = state.derivation(payload["derivation_fingerprint"])
            if existing is None or existing.derivation_version_id != payload["derivation_version_id"]:
                raise R32Error("R3_2_EVENT_INVALID", "reuse references a missing or mismatched derivation")
            reuse = ReuseReference(
                reuse_id=event.entity_id, derivation_version_id=payload["derivation_version_id"],
                derivation_fingerprint=payload["derivation_fingerprint"], idempotency_key=payload["idempotency_key"],
                created_seq=event.seq, created_at=event.created_at, correlation_id=event.correlation_id,
            )
            if any(item.reuse_id == reuse.reuse_id for item in state.reuses):
                raise R32Error("R3_2_EVENT_INVALID", "reuse identity is not immutable")
            return replace(state, reuses=state.reuses + (reuse,))
        raise R32Error("R3_2_EVENT_NOT_OWNED", f"unsupported R3.2 event: {event.event_type}")
