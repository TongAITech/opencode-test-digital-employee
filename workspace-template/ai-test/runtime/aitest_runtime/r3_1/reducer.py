from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import EventEnvelope, RuntimeState

from .contracts import (
    DERIVATION_CREATED,
    DERIVATION_REUSED,
    CoverageSnapshot,
    DerivationIdentity,
    DerivationVersion,
    R31Error,
    R31State,
    ReuseReference,
)


def _payload(event: EventEnvelope, required: set[str]) -> dict[str, Any]:
    payload = dict(event.payload)
    if set(payload) != required:
        raise R31Error("R3_1_EVENT_INVALID", f"{event.event_type} payload contains unknown or missing fields")
    return payload


class R31ReducerContribution:
    def reduce(self, state: R31State, event: EventEnvelope, core_state: RuntimeState) -> R31State:
        if not isinstance(state, R31State):
            raise R31Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.1 state")
        if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id:
            raise R31Error("R3_1_EVENT_INVALID", "R3.1 Event Mission identity mismatch")
        if core_state.seq != event.seq:
            raise R31Error("R3_1_EVENT_INVALID", "R3.1 Event does not share the Core sequence")
        if event.event_type == DERIVATION_CREATED:
            payload = _payload(event, {"derivation", "snapshot"})
            derivation_raw = dict(payload["derivation"])
            snapshot_raw = dict(payload["snapshot"])
            identity = DerivationIdentity.from_dict(derivation_raw["identity"])
            if identity.mission_id != event.mission_id:
                raise R31Error("R3_1_EVENT_INVALID", "derivation identity Mission mismatch")
            if derivation_raw.get("derivation_fingerprint") != identity.fingerprint:
                raise R31Error("R3_1_FINGERPRINT_MISMATCH", "derivation fingerprint does not match identity")
            if snapshot_raw.get("snapshot_id") != derivation_raw.get("coverage_snapshot_id"):
                raise R31Error("R3_1_EVENT_INVALID", "snapshot identity does not match derivation")
            derivation = DerivationVersion.from_dict({
                **derivation_raw, "created_seq": event.seq, "created_at": event.created_at,
                "correlation_id": event.correlation_id,
            })
            snapshot = CoverageSnapshot.from_dict({
                **snapshot_raw, "created_seq": event.seq, "created_at": event.created_at,
            })
            if state.derivation(derivation.derivation_fingerprint) is not None:
                raise R31Error("R3_1_EVENT_INVALID", "derivation fingerprint is not immutable")
            if state.snapshot(snapshot.snapshot_id) is not None:
                raise R31Error("R3_1_EVENT_INVALID", "coverage snapshot identity is not immutable")
            if f"r1-event:{event.correlation_id}" not in derivation.evidence_references:
                raise R31Error("R3_1_EVIDENCE_REFERENCE_MISSING", "evidence chain does not reference R1 Event correlation")
            return replace(
                state,
                derivations=state.derivations + (derivation,),
                snapshots=state.snapshots + (snapshot,),
            )
        if event.event_type == DERIVATION_REUSED:
            payload = _payload(event, {"derivation_version_id", "derivation_fingerprint", "idempotency_key"})
            existing = state.derivation(payload["derivation_fingerprint"])
            if existing is None or existing.derivation_version_id != payload["derivation_version_id"]:
                raise R31Error("R3_1_EVENT_INVALID", "reuse references a missing or mismatched derivation")
            reuse = ReuseReference(
                reuse_id=event.entity_id,
                derivation_version_id=payload["derivation_version_id"],
                derivation_fingerprint=payload["derivation_fingerprint"],
                idempotency_key=payload["idempotency_key"],
                created_seq=event.seq,
                created_at=event.created_at,
                correlation_id=event.correlation_id,
            )
            if any(item.reuse_id == reuse.reuse_id for item in state.reuses):
                raise R31Error("R3_1_EVENT_INVALID", "reuse identity is not immutable")
            return replace(state, reuses=state.reuses + (reuse,))
        raise R31Error("R3_1_EVENT_NOT_OWNED", f"unsupported R3.1 event: {event.event_type}")
