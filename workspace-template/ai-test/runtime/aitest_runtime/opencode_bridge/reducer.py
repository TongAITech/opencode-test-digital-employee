from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import EventEnvelope, MissionStatus, RuntimeError, RuntimeState
from aitest_runtime.execution_context import EventCursor

from .contracts import (
    EVENT_TYPES,
    EXTENSION_ID,
    OpenCodeBridgeState,
    TransportObservationRecord,
    TransportOperation,
)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", f"{name} must be a non-empty string")
    return value


def _payload(event: EventEnvelope) -> Mapping[str, Any]:
    if event.event_type not in EVENT_TYPES:
        raise RuntimeError("EXTENSION_EVENT_NOT_OWNED", f"unsupported OpenCode Bridge event: {event.event_type}")
    if event.entity_type != "OPENCODE_BRIDGE_REQUEST" or event.session_id is None:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "OpenCode Bridge Event identity is invalid")
    payload = dict(event.payload)
    required = {
        "status",
        "operation",
        "bridge_request_id",
        "attempt_id",
        "runtime_session_id",
        "context_cursor",
        "context_semantic_digest",
        "correlation_id",
        "provider_request_id",
        "external_transport_handle",
    }
    if set(payload) != required:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "OpenCode Bridge Event payload contains unknown or missing fields")
    if payload["status"] != "ACCEPTED":
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "only an ACCEPTED observation may be replayed")
    if payload["bridge_request_id"] != event.entity_id or payload["runtime_session_id"] != event.session_id:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "OpenCode Bridge Event identity mismatch")
    if payload["correlation_id"] != event.correlation_id:
        raise RuntimeError("OPENCODE_BRIDGE_CORRELATION_MISMATCH", "Event correlation does not match observation correlation")
    try:
        operation = TransportOperation(payload["operation"])
        cursor = EventCursor.from_dict(payload["context_cursor"])
    except (TypeError, ValueError, RuntimeError) as exc:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "OpenCode Bridge Event contains an invalid operation or cursor") from exc
    if cursor.mission_id != event.mission_id or cursor.stream_schema_version != 1 or cursor.through_seq > event.seq - 1:
        raise RuntimeError("OPENCODE_BRIDGE_CONTEXT_MISMATCH", "Event context cursor is not a prior Runtime cursor")
    digest = _text(payload["context_semantic_digest"], "context_semantic_digest")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Event context digest is not a lowercase SHA-256 digest")
    provider_request_id = _text(payload["provider_request_id"], "provider_request_id")
    handle = payload["external_transport_handle"]
    if handle is not None:
        handle = _text(handle, "external_transport_handle")
    if operation == TransportOperation.RECONNECT and handle is None:
        raise RuntimeError("OPENCODE_BRIDGE_HANDLE_REQUIRED", "RECONNECT observation has no external handle")
    return {
        "status": "ACCEPTED",
        "operation": operation,
        "bridge_request_id": _text(payload["bridge_request_id"], "bridge_request_id"),
        "attempt_id": _text(payload["attempt_id"], "attempt_id"),
        "runtime_session_id": _text(payload["runtime_session_id"], "runtime_session_id"),
        "context_cursor": cursor,
        "context_semantic_digest": digest,
        "correlation_id": _text(payload["correlation_id"], "correlation_id"),
        "provider_request_id": provider_request_id,
        "external_transport_handle": handle,
    }


class OpenCodeBridgeReducerContribution:
    def reduce(
        self,
        state: OpenCodeBridgeState,
        event: EventEnvelope,
        core_state: RuntimeState,
    ) -> OpenCodeBridgeState:
        if not isinstance(state, OpenCodeBridgeState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid OpenCode Bridge state")
        if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "OpenCode Bridge Mission identity mismatch")
        if core_state.seq != event.seq:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "OpenCode Bridge Event does not share Core seq")
        if core_state.mission is None or core_state.mission.status in {
            MissionStatus.COMPLETED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        }:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "terminal or missing Mission cannot accept bridge observations")
        payload = _payload(event)
        if state.by_bridge_request_id(payload["bridge_request_id"]) is not None:
            raise RuntimeError("OPENCODE_BRIDGE_DUPLICATE", "bridge_request_id is already present in Event replay")
        if state.by_provider_request_id(payload["provider_request_id"]) is not None:
            raise RuntimeError("OPENCODE_BRIDGE_DUPLICATE", "provider_request_id is already present in Event replay")
        record = TransportObservationRecord(
            status=payload["status"],
            operation=payload["operation"],
            bridge_request_id=payload["bridge_request_id"],
            attempt_id=payload["attempt_id"],
            runtime_session_id=payload["runtime_session_id"],
            context_cursor=payload["context_cursor"],
            context_semantic_digest=payload["context_semantic_digest"],
            correlation_id=payload["correlation_id"],
            provider_request_id=payload["provider_request_id"],
            external_transport_handle=payload["external_transport_handle"],
            command_id=event.command_id,
            mission_id=event.mission_id,
            created_seq=event.seq,
            created_at=event.created_at,
            created_by={"type": event.initiator_type, "id": event.initiator_id},
        )
        return replace(state, observations=state.observations + (record,))


OpenCodeTransportReducerContribution = OpenCodeBridgeReducerContribution


__all__ = ["OpenCodeBridgeReducerContribution", "OpenCodeTransportReducerContribution"]
