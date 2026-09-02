from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import (
    CommandEnvelope,
    ComposedRuntimeState,
    MissionStatus,
    PendingEvent,
    RuntimeError,
    SessionStatus,
)
from aitest_runtime.execution_context import EventCursor
from aitest_runtime.execution_resume import EXTENSION_ID as EXECUTION_RESUME_EXTENSION_ID
from aitest_runtime.execution_resume import ExecutionResumeState
from aitest_runtime.provider_binding import EXTENSION_ID as PROVIDER_BINDING_EXTENSION_ID
from aitest_runtime.provider_binding import ProviderBindingState

from .contracts import (
    COMMAND_TYPE,
    EVENT_TYPE,
    EXTENSION_ID,
    OpenCodeBridgeState,
    TransportOperation,
)


COMMAND_TYPES = frozenset({COMMAND_TYPE})
EVENT_TYPES = frozenset({EVENT_TYPE})
PAYLOAD_FIELDS = frozenset(
    {
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
)


def _text(value: Any, name: str, code: str = "COMMAND_SCHEMA_INVALID") -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(code, f"{name} must be a non-empty string")
    return value


def _state(composed: ComposedRuntimeState) -> OpenCodeBridgeState:
    value = composed.extension_state(EXTENSION_ID)
    if not isinstance(value, OpenCodeBridgeState):
        raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid OpenCode Bridge state")
    return value


def _execution_state(composed: ComposedRuntimeState) -> ExecutionResumeState:
    value = composed.extension_state(EXECUTION_RESUME_EXTENSION_ID)
    if not isinstance(value, ExecutionResumeState):
        raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Execution Resume state")
    return value


def _binding_state(composed: ComposedRuntimeState) -> ProviderBindingState:
    value = composed.extension_state(PROVIDER_BINDING_EXTENSION_ID)
    if not isinstance(value, ProviderBindingState):
        raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Provider Binding state")
    return value


def _require_runtime(composed: ComposedRuntimeState, command: CommandEnvelope) -> None:
    mission = composed.core_state.mission
    if mission is None:
        raise RuntimeError("MISSION_NOT_FOUND", f"Mission not found: {command.mission_id}")
    if mission.status != MissionStatus.ACTIVE:
        raise RuntimeError("INVALID_STATE_TRANSITION", "OpenCode Bridge requires an ACTIVE Mission")
    if command.session_id is None:
        raise RuntimeError("OPENCODE_BRIDGE_SESSION_REQUIRED", "OpenCode Bridge requires a Runtime Session")
    session = composed.core_state.session(command.session_id)
    if session is None or session.mission_id != command.mission_id or session.status != SessionStatus.OPEN:
        raise RuntimeError("EXECUTION_SESSION_NOT_OPEN", f"Runtime Session is not OPEN: {command.session_id}")


def _payload(command: CommandEnvelope) -> Mapping[str, Any]:
    if command.type not in COMMAND_TYPES:
        raise RuntimeError("EXTENSION_COMMAND_NOT_OWNED", f"unsupported OpenCode Bridge command: {command.type}")
    if set(command.payload) != PAYLOAD_FIELDS:
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "OpenCode Bridge payload contains unknown or missing fields")
    if command.payload["status"] != "ACCEPTED":
        raise RuntimeError("OPENCODE_BRIDGE_STATUS_INVALID", "only an ACCEPTED observation can become a Runtime fact")
    operation = command.payload["operation"]
    try:
        operation = operation if isinstance(operation, TransportOperation) else TransportOperation(operation)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("OPENCODE_BRIDGE_OPERATION_INVALID", "operation must be NEW or RECONNECT") from exc
    bridge_request_id = _text(command.payload["bridge_request_id"], "bridge_request_id")
    attempt_id = _text(command.payload["attempt_id"], "attempt_id")
    runtime_session_id = _text(command.payload["runtime_session_id"], "runtime_session_id")
    correlation_id = _text(command.payload["correlation_id"], "correlation_id")
    if correlation_id != command.correlation_id:
        raise RuntimeError("OPENCODE_BRIDGE_CORRELATION_MISMATCH", "payload correlation does not match Command")
    provider_request_id = _text(command.payload["provider_request_id"], "provider_request_id")
    handle = command.payload["external_transport_handle"]
    if handle is not None:
        handle = _text(handle, "external_transport_handle")
    if operation == TransportOperation.RECONNECT and handle is None:
        raise RuntimeError("OPENCODE_BRIDGE_HANDLE_REQUIRED", "RECONNECT requires an external transport handle")
    cursor = EventCursor.from_dict(command.payload["context_cursor"])
    if cursor.mission_id != command.mission_id or cursor.stream_schema_version != 1 or cursor.through_seq > command.expected_seq:
        raise RuntimeError("OPENCODE_BRIDGE_CONTEXT_MISMATCH", "context cursor is not a valid Runtime anchor")
    digest = _text(command.payload["context_semantic_digest"], "context_semantic_digest")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise RuntimeError("OPENCODE_BRIDGE_CONTEXT_MISMATCH", "context_semantic_digest is not a SHA-256 digest")
    if command.mission_id != cursor.mission_id or runtime_session_id != command.session_id:
        raise RuntimeError("OPENCODE_BRIDGE_LINEAGE_MISMATCH", "Runtime Session or Mission identity mismatch")
    return {
        "status": "ACCEPTED",
        "operation": operation,
        "bridge_request_id": bridge_request_id,
        "attempt_id": attempt_id,
        "runtime_session_id": runtime_session_id,
        "context_cursor": cursor,
        "context_semantic_digest": digest,
        "correlation_id": correlation_id,
        "provider_request_id": provider_request_id,
        "external_transport_handle": handle,
    }


def _handle(command: CommandEnvelope, composed: ComposedRuntimeState) -> list[PendingEvent]:
    _require_runtime(composed, command)
    payload = _payload(command)
    execution_state = _execution_state(composed)
    binding_state = _binding_state(composed)
    bridge_state = _state(composed)

    attempt = execution_state.attempt(payload["attempt_id"])
    if attempt is None:
        raise RuntimeError("OPENCODE_BRIDGE_ATTEMPT_NOT_FOUND", f"Attempt not found: {payload['attempt_id']}")
    task_attempts = execution_state.attempts_for_task(attempt.task_id)
    current_attempt = task_attempts[-1] if task_attempts else None
    if current_attempt is None or current_attempt.attempt_id != attempt.attempt_id:
        raise RuntimeError("OPENCODE_BRIDGE_ATTEMPT_LINEAGE_INVALID", "Bridge requires the current Attempt")
    binding = binding_state.binding(attempt.attempt_id)
    if binding is None:
        raise RuntimeError("OPENCODE_BRIDGE_BINDING_NOT_REHYDRATED", "ProviderBinding was not found in Runtime replay")
    if (
        attempt.mission_id != command.mission_id
        or attempt.runtime_session_id != command.session_id
        or binding.mission_id != command.mission_id
        or binding.runtime_session_id != command.session_id
        or binding.attempt_id != attempt.attempt_id
    ):
        raise RuntimeError("OPENCODE_BRIDGE_LINEAGE_MISMATCH", "Attempt, Binding and Runtime Session do not agree")
    if attempt.context_cursor != payload["context_cursor"] or attempt.context_semantic_digest != payload["context_semantic_digest"]:
        raise RuntimeError("OPENCODE_BRIDGE_CONTEXT_MISMATCH", "context cursor or digest differs from Attempt")
    if bridge_state.by_bridge_request_id(payload["bridge_request_id"]) is not None:
        raise RuntimeError("OPENCODE_BRIDGE_DUPLICATE", "bridge_request_id was already observed")
    if bridge_state.by_provider_request_id(payload["provider_request_id"]) is not None:
        raise RuntimeError("OPENCODE_BRIDGE_DUPLICATE", "provider_request_id was already observed")

    event_payload = {
        "status": "ACCEPTED",
        "operation": payload["operation"].value,
        "bridge_request_id": payload["bridge_request_id"],
        "attempt_id": payload["attempt_id"],
        "runtime_session_id": payload["runtime_session_id"],
        "context_cursor": payload["context_cursor"].to_dict(),
        "context_semantic_digest": payload["context_semantic_digest"],
        "correlation_id": payload["correlation_id"],
        "provider_request_id": payload["provider_request_id"],
        "external_transport_handle": payload["external_transport_handle"],
    }
    return [
        PendingEvent(
            EVENT_TYPE,
            "OPENCODE_BRIDGE_REQUEST",
            payload["bridge_request_id"],
            event_payload,
            session_id=command.session_id,
        )
    ]


class OpenCodeBridgeCommandContribution:
    def handle(self, command: CommandEnvelope, composed: ComposedRuntimeState) -> list[PendingEvent]:
        return _handle(command, composed)


OpenCodeTransportCommandContribution = OpenCodeBridgeCommandContribution


__all__ = [
    "COMMAND_TYPES",
    "EVENT_TYPES",
    "OpenCodeBridgeCommandContribution",
    "OpenCodeTransportCommandContribution",
    "PAYLOAD_FIELDS",
]
