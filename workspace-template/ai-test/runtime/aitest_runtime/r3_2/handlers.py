from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent

from .contracts import (
    CHANGE_IMPACT_DERIVED,
    DERIVE_CHANGE_IMPACT_RECONCILIATION,
    RECONCILIATION_CREATED,
    RECONCILIATION_REUSED,
    ChangeImpactDerivation,
    R32Error,
    R32State,
    ReconciliationSnapshot,
)


def _state(composed: ComposedRuntimeState) -> R32State:
    value = composed.extension_state("r3_2_change_impact_reconciliation")
    if not isinstance(value, R32State):
        raise R32Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.2 extension state")
    return value


def _payload(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R32Error("R3_2_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _event_payload(value: Any, required: set[str], event_name: str) -> dict[str, Any]:
    payload = _payload(value, event_name)
    if set(payload) != required:
        raise R32Error("R3_2_EVENT_INVALID", f"{event_name} payload contains unknown or missing fields")
    return payload


def handle(command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
    if command.type != DERIVE_CHANGE_IMPACT_RECONCILIATION:
        raise R32Error("UNSUPPORTED_COMMAND_TYPE", f"unsupported R3.2 command: {command.type}")
    payload = _payload(command.payload, "command.payload")
    if set(payload) != {"derivation", "reconciliation"}:
        raise R32Error("R3_2_SCHEMA_INVALID", "R3.2 command payload must contain derivation and reconciliation only")
    derivation = ChangeImpactDerivation.from_dict(payload["derivation"])
    reconciliation = ReconciliationSnapshot.from_dict(payload["reconciliation"])
    if derivation.identity.mission_id != command.mission_id:
        raise R32Error("R3_2_MISSION_IDENTITY_MISMATCH", "derivation mission does not match command mission")
    if reconciliation.derivation_fingerprint != derivation.derivation_fingerprint:
        raise R32Error("R3_2_RECONCILIATION_INVALID", "reconciliation fingerprint does not match derivation")
    if command.idempotency_key != derivation.idempotency_key:
        raise R32Error("R3_2_IDEMPOTENCY_KEY_MISMATCH", "command idempotency_key must match derivation request")
    state = _state(composed)
    existing = state.derivation(derivation.derivation_fingerprint)
    if existing is not None:
        return [
            PendingEvent(
                RECONCILIATION_REUSED,
                "R3_2_RECONCILIATION_REUSE",
                f"r3.2:reuse:{command.command_id}",
                {
                    "derivation_version_id": existing.derivation_version_id,
                    "derivation_fingerprint": existing.derivation_fingerprint,
                    "idempotency_key": derivation.idempotency_key,
                },
                session_id=command.session_id,
            )
        ]
    return [
        PendingEvent(
            CHANGE_IMPACT_DERIVED,
            "R3_2_CHANGE_IMPACT_DERIVATION",
            derivation.derivation_version_id,
            {"derivation": derivation.to_dict()},
            session_id=command.session_id,
        ),
        PendingEvent(
            RECONCILIATION_CREATED,
            "R3_2_RECONCILIATION",
            reconciliation.reconciliation_id,
            {"reconciliation": reconciliation.to_dict(), "derivation_fingerprint": derivation.derivation_fingerprint},
            session_id=command.session_id,
        ),
    ]


class R32CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        return handle(command, composed)
