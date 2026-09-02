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
from aitest_runtime.execution_resume import EXTENSION_ID as EXECUTION_RESUME_EXTENSION_ID
from aitest_runtime.execution_resume import ExecutionResumeState

from .contracts import EXTENSION_ID, ProviderBindingState, ProviderConfiguration


COMMAND_TYPES = frozenset({"BIND_PROVIDER_ATTEMPT"})
EVENT_TYPES = frozenset({"provider.binding_bound.v1"})


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("COMMAND_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value


def _execution_state(composed: ComposedRuntimeState) -> ExecutionResumeState:
    value = composed.extension_state(EXECUTION_RESUME_EXTENSION_ID)
    if not isinstance(value, ExecutionResumeState):
        raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Execution Resume extension state")
    return value


def _binding_state(composed: ComposedRuntimeState) -> ProviderBindingState:
    value = composed.extension_state(EXTENSION_ID)
    if not isinstance(value, ProviderBindingState):
        raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Provider Binding extension state")
    return value


def _require_runtime_session(composed: ComposedRuntimeState, command: CommandEnvelope) -> None:
    mission = composed.core_state.mission
    if mission is None:
        raise RuntimeError("MISSION_NOT_FOUND", f"Mission not found: {command.mission_id}")
    if mission.status != MissionStatus.ACTIVE:
        raise RuntimeError("INVALID_STATE_TRANSITION", "Provider Binding requires ACTIVE Mission")
    if not command.session_id:
        raise RuntimeError("PROVIDER_BINDING_SESSION_REQUIRED", "Provider Binding requires a runtime session")
    session = composed.core_state.session(command.session_id)
    if session is None or session.mission_id != command.mission_id or session.status != SessionStatus.OPEN:
        raise RuntimeError("EXECUTION_SESSION_NOT_OPEN", f"Session is not OPEN: {command.session_id}")


def _command_payload(command: CommandEnvelope) -> tuple[str, str, str, ProviderConfiguration]:
    required = {"attempt_id", "provider", "model", "configuration"}
    if set(command.payload) != required:
        raise RuntimeError(
            "COMMAND_SCHEMA_INVALID",
            "Provider Binding payload contains unknown or missing fields",
        )
    attempt_id = _text(command.payload.get("attempt_id"), "payload.attempt_id")
    provider = _text(command.payload.get("provider"), "payload.provider")
    model = _text(command.payload.get("model"), "payload.model")
    configuration = ProviderConfiguration.from_dict(command.payload.get("configuration"))
    if any(character in provider or character in model for character in ("*", "?")):
        raise RuntimeError("PROVIDER_BINDING_EXPLICIT_REQUIRED", "provider and model must be explicit identities")
    if provider.upper() in {"AUTO", "LATEST"} or model.upper() in {"AUTO", "LATEST"}:
        raise RuntimeError("PROVIDER_BINDING_EXPLICIT_REQUIRED", "provider and model must be explicit identities")
    return attempt_id, provider, model, configuration


def _handle(command: CommandEnvelope, composed: ComposedRuntimeState) -> list[PendingEvent]:
    if command.type not in COMMAND_TYPES:
        raise RuntimeError("EXTENSION_COMMAND_NOT_OWNED", f"unsupported Provider Binding command: {command.type}")
    _require_runtime_session(composed, command)
    attempt_id, provider, model, configuration = _command_payload(command)
    execution_state = _execution_state(composed)
    attempt = execution_state.attempt(attempt_id)
    if attempt is None:
        raise RuntimeError("PROVIDER_BINDING_ATTEMPT_NOT_FOUND", f"Attempt not found: {attempt_id}")
    if attempt.mission_id != command.mission_id:
        raise RuntimeError("PROVIDER_BINDING_LINEAGE_MISMATCH", "Attempt Mission mismatch")
    if attempt.runtime_session_id != command.session_id:
        raise RuntimeError("PROVIDER_BINDING_SESSION_MISMATCH", "Binding session does not match Attempt session")
    latest = execution_state.latest_attempt(attempt.task_id)
    if latest is None or latest.attempt_id != attempt_id:
        raise RuntimeError(
            "PROVIDER_BINDING_ATTEMPT_NOT_LATEST",
            "Provider Binding must target the latest Attempt for the Task",
        )
    if _binding_state(composed).binding(attempt_id) is not None:
        raise RuntimeError(
            "PROVIDER_BINDING_ALREADY_EXISTS",
            f"Attempt already has a successful Provider Binding: {attempt_id}",
        )
    return [
        PendingEvent(
            "provider.binding_bound.v1",
            "PROVIDER_BINDING",
            attempt_id,
            {
                "attempt_id": attempt_id,
                "mission_id": command.mission_id,
                "provider": provider,
                "model": model,
                "configuration": configuration.to_dict(),
            },
            session_id=command.session_id,
        )
    ]


class ProviderBindingCommandContribution:
    def handle(self, command: CommandEnvelope, composed: ComposedRuntimeState) -> list[PendingEvent]:
        return _handle(command, composed)


__all__ = ["COMMAND_TYPES", "EVENT_TYPES", "ProviderBindingCommandContribution"]
