from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import EventEnvelope, MissionStatus, RuntimeError, RuntimeState

from .contracts import ProviderBindingRecord, ProviderBindingState, ProviderConfiguration
from .handlers import EVENT_TYPES


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", f"{name} must be a non-empty string")
    return value


def _payload(event: EventEnvelope) -> Mapping[str, Any]:
    if event.event_type not in EVENT_TYPES:
        raise RuntimeError("EXTENSION_EVENT_NOT_OWNED", f"unsupported Provider Binding event: {event.event_type}")
    if event.entity_type != "PROVIDER_BINDING" or event.session_id is None:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Provider Binding Event identity is invalid")
    payload = dict(event.payload)
    required = {"attempt_id", "mission_id", "provider", "model", "configuration"}
    if set(payload) != required:
        raise RuntimeError(
            "RUNTIME_INVARIANT_VIOLATION",
            "Provider Binding Event payload contains unknown or missing fields",
        )
    if payload["attempt_id"] != event.entity_id or payload["mission_id"] != event.mission_id:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Provider Binding Event identity mismatch")
    _text(payload["provider"], "provider")
    _text(payload["model"], "model")
    ProviderConfiguration.from_dict(payload["configuration"])
    return payload


class ProviderBindingReducerContribution:
    def reduce(
        self,
        state: ProviderBindingState,
        event: EventEnvelope,
        core_state: RuntimeState,
    ) -> ProviderBindingState:
        if not isinstance(state, ProviderBindingState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Provider Binding state")
        if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Provider Binding Mission identity mismatch")
        if core_state.seq != event.seq:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Provider Binding Event does not share Core seq")
        if core_state.mission is None or core_state.mission.status in {
            MissionStatus.COMPLETED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        }:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "terminal or missing Mission cannot accept Provider Binding facts")
        payload = _payload(event)
        attempt_id = str(payload["attempt_id"])
        if state.binding(attempt_id) is not None:
            raise RuntimeError(
                "PROVIDER_BINDING_ALREADY_EXISTS",
                f"Attempt already has a successful Provider Binding: {attempt_id}",
            )
        record = ProviderBindingRecord(
            attempt_id=attempt_id,
            mission_id=event.mission_id,
            runtime_session_id=event.session_id or "",
            provider=payload["provider"],
            model=payload["model"],
            configuration=ProviderConfiguration.from_dict(payload["configuration"]),
            command_id=event.command_id,
            created_seq=event.seq,
            created_at=event.created_at,
            created_by={"type": event.initiator_type, "id": event.initiator_id},
        )
        return replace(state, bindings=state.bindings + (record,))


__all__ = ["ProviderBindingReducerContribution"]
