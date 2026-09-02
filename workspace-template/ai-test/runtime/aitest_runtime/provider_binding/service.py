from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import (
    ActorRef,
    CommandEnvelope,
    CommandResult,
    RuntimeError,
    RuntimeService,
    SessionStatus,
    canonical_sha256,
)
from aitest_runtime.execution_context import EventCursor
from aitest_runtime.execution_resume import EXTENSION_ID as EXECUTION_RESUME_EXTENSION_ID
from aitest_runtime.execution_resume import ExecutionResumeState

from .contracts import (
    EXTENSION_ID,
    BindProviderAttemptRequest,
    LogicalProviderBindingResult,
    ProviderBindingState,
    RehydrateProviderBindingRequest,
    RehydratedProviderBinding,
)


class ProviderBindingApplicationService:
    def __init__(self, runtime_service: RuntimeService) -> None:
        if runtime_service is None:
            raise ValueError("runtime_service is required")
        runtime_service.extension_registry.manifest(EXECUTION_RESUME_EXTENSION_ID)
        runtime_service.extension_registry.manifest(EXTENSION_ID)
        self._runtime_service = runtime_service

    def rehydrate(self, request: RehydrateProviderBindingRequest) -> RehydratedProviderBinding:
        if not isinstance(request, RehydrateProviderBindingRequest):
            raise RuntimeError("PROVIDER_BINDING_SCHEMA_INVALID", "request has an invalid type")
        head_seq = self._runtime_service.get_head_seq(request.mission_id)
        if request.cursor.through_seq > head_seq:
            raise RuntimeError(
                "RUNTIME_REHYDRATION_CURSOR_MISMATCH",
                "Requested cursor is ahead of the Mission head",
                {"requested_seq": request.cursor.through_seq, "head_seq": head_seq},
            )
        composed = self._runtime_service.replay_composed(
            request.mission_id,
            through_seq=request.cursor.through_seq,
        )
        if composed.seq != request.cursor.through_seq:
            raise RuntimeError(
                "RUNTIME_REHYDRATION_CURSOR_MISMATCH",
                "Fixed-cursor replay did not reach the requested cursor",
                {"requested_seq": request.cursor.through_seq, "replayed_seq": composed.seq},
            )
        binding_state = composed.extension_state(EXTENSION_ID)
        if not isinstance(binding_state, ProviderBindingState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Provider Binding state")
        return RehydratedProviderBinding(
            mission_id=request.mission_id,
            cursor=request.cursor,
            composed_state=composed,
            binding_state=binding_state,
            state_digest=canonical_sha256(composed.to_dict()),
        )

    def bind(self, request: BindProviderAttemptRequest | Mapping[str, Any]) -> LogicalProviderBindingResult:
        if isinstance(request, Mapping):
            request = self._request_from_mapping(request)
        if not isinstance(request, BindProviderAttemptRequest):
            raise RuntimeError("PROVIDER_BINDING_SCHEMA_INVALID", "request has an invalid type")
        cursor = EventCursor(request.mission_id, request.expected_seq, 1)
        rehydrated = self.rehydrate(RehydrateProviderBindingRequest(request.mission_id, cursor))
        self._validate_preconditions(request, rehydrated)
        command = CommandEnvelope(
            command_id=request.command_id,
            type="BIND_PROVIDER_ATTEMPT",
            mission_id=request.mission_id,
            session_id=request.runtime_session_id,
            expected_seq=request.expected_seq,
            actor=request.actor,
            payload={
                "attempt_id": request.attempt_id,
                "provider": request.provider,
                "model": request.model,
                "configuration": request.configuration.to_dict(),
            },
            idempotency_key=request.idempotency_key,
            correlation_id=request.correlation_id,
            schema_version=1,
        )
        result = self._runtime_service.execute(command)
        if not result.ok:
            if result.error is not None:
                raise result.error
            raise RuntimeError("PROVIDER_BINDING_REJECTED", "Provider Binding command was rejected")
        return self._post_commit_verify(request, result)

    bind_provider_attempt = bind

    def _validate_preconditions(
        self,
        request: BindProviderAttemptRequest,
        rehydrated: RehydratedProviderBinding,
    ) -> None:
        core = rehydrated.composed_state.core_state
        session = core.session(request.runtime_session_id)
        if session is None or session.status != SessionStatus.OPEN:
            raise RuntimeError("EXECUTION_SESSION_NOT_OPEN", f"Session is not OPEN: {request.runtime_session_id}")
        execution_state = rehydrated.composed_state.extension_state(EXECUTION_RESUME_EXTENSION_ID)
        if not isinstance(execution_state, ExecutionResumeState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Execution Resume state")
        attempt = execution_state.attempt(request.attempt_id)
        if attempt is None:
            raise RuntimeError("PROVIDER_BINDING_ATTEMPT_NOT_FOUND", f"Attempt not found: {request.attempt_id}")
        if attempt.runtime_session_id != request.runtime_session_id:
            raise RuntimeError("PROVIDER_BINDING_SESSION_MISMATCH", "Binding session does not match Attempt session")
        latest = execution_state.latest_attempt(attempt.task_id)
        if latest is None or latest.attempt_id != request.attempt_id:
            raise RuntimeError(
                "PROVIDER_BINDING_ATTEMPT_NOT_LATEST",
                "Provider Binding must target the latest Attempt for the Task",
            )
        if rehydrated.binding_state.binding(request.attempt_id) is not None:
            raise RuntimeError(
                "PROVIDER_BINDING_ALREADY_EXISTS",
                f"Attempt already has a successful Provider Binding: {request.attempt_id}",
            )

    @staticmethod
    def _request_from_mapping(value: Mapping[str, Any]) -> BindProviderAttemptRequest:
        try:
            actor_raw = value["actor"]
            actor = actor_raw if isinstance(actor_raw, ActorRef) else ActorRef(actor_raw["type"], actor_raw["id"])
            return BindProviderAttemptRequest(
                command_id=value["command_id"],
                idempotency_key=value.get("idempotency_key"),
                mission_id=value["mission_id"],
                runtime_session_id=value["runtime_session_id"],
                expected_seq=value["expected_seq"],
                actor=actor,
                correlation_id=value.get("correlation_id"),
                attempt_id=value["attempt_id"],
                provider=value["provider"],
                model=value["model"],
                configuration=value["configuration"],
            )
        except (KeyError, TypeError) as exc:
            raise RuntimeError("PROVIDER_BINDING_SCHEMA_INVALID", "request contains missing fields") from exc

    def _post_commit_verify(
        self,
        request: BindProviderAttemptRequest,
        result: CommandResult,
    ) -> LogicalProviderBindingResult:
        if result.first_seq is None or result.last_seq is None or result.first_seq != result.last_seq:
            raise RuntimeError("PROVIDER_BINDING_SEQUENCE_MISMATCH", "Provider Binding must append exactly one Event")
        event_seq = result.last_seq
        events = self._runtime_service.list_events(
            request.mission_id,
            after_seq=event_seq - 1,
            through_seq=event_seq,
        )
        if len(events) != 1:
            raise RuntimeError("PROVIDER_BINDING_EVENT_NOT_FOUND", "Persisted Provider Binding Event was not found")
        event = events[0]
        original_command_id = result.duplicate_of or result.command_id
        if (
            event.command_id != original_command_id
            or event.event_type != "provider.binding_bound.v1"
            or event.mission_id != request.mission_id
            or event.entity_type != "PROVIDER_BINDING"
            or event.entity_id != request.attempt_id
            or event.session_id != request.runtime_session_id
        ):
            raise RuntimeError("PROVIDER_BINDING_EVENT_MISMATCH", "Persisted Provider Binding Event identity mismatch")
        if event.payload != {
            "attempt_id": request.attempt_id,
            "mission_id": request.mission_id,
            "provider": request.provider,
            "model": request.model,
            "configuration": request.configuration.to_dict(),
        }:
            raise RuntimeError("PROVIDER_BINDING_EVENT_MISMATCH", "Persisted Provider Binding Event fact mismatch")
        persisted = self.rehydrate(
            RehydrateProviderBindingRequest(
                request.mission_id,
                EventCursor(request.mission_id, event_seq, 1),
            )
        ).binding_state.binding(request.attempt_id)
        if persisted is None:
            raise RuntimeError("PROVIDER_BINDING_EVENT_MISMATCH", "Persisted Provider Binding was not rehydrated")
        if (
            persisted.provider != request.provider
            or persisted.model != request.model
            or persisted.configuration != request.configuration
        ):
            raise RuntimeError("PROVIDER_BINDING_EVENT_MISMATCH", "Persisted Provider Binding differs from request")
        return LogicalProviderBindingResult(
            outcome=result.outcome,
            command_result=result,
            binding=persisted,
            event_cursor=EventCursor(request.mission_id, event_seq, 1),
        )


__all__ = ["ProviderBindingApplicationService"]
