from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import (
    CommandEnvelope,
    CommandResult,
    ComposedRuntimeState,
    RuntimeError,
    RuntimeService,
    SessionStatus,
    canonical_sha256,
)
from aitest_runtime.execution_context import EventCursor
from aitest_runtime.execution_resume import EXTENSION_ID as EXECUTION_RESUME_EXTENSION_ID
from aitest_runtime.execution_resume import ExecutionResumeState
from aitest_runtime.provider_binding import (
    EXTENSION_ID as PROVIDER_BINDING_EXTENSION_ID,
    ProviderBindingApplicationService,
    ProviderBindingRecord,
    RehydrateProviderBindingRequest,
)

from .contracts import (
    EVENT_TYPE,
    EXTENSION_ID,
    LogicalOpenCodeBridgeResult,
    OpenCodeBridgeRequest,
    OpenCodeBridgeState,
    RehydrateOpenCodeBridgeRequest,
    RehydratedOpenCodeBridge,
    TransportObservation,
    TransportObservationRecord,
    TransportOperation,
)
from .transport import (
    FakeOpenCodeTransport,
    OpenCodeTransport,
    TransportCall,
    TransportDuplicate,
    TransportFailure,
    TransportTimeout,
    TransportUnknown,
)


class OpenCodeBridgeApplicationService:
    """Application boundary between Runtime facts and the fake transport."""

    def __init__(self, runtime_service: RuntimeService, transport: OpenCodeTransport | None = None) -> None:
        if runtime_service is None:
            raise ValueError("runtime_service is required")
        runtime_service.extension_registry.manifest(EXECUTION_RESUME_EXTENSION_ID)
        runtime_service.extension_registry.manifest(PROVIDER_BINDING_EXTENSION_ID)
        runtime_service.extension_registry.manifest(EXTENSION_ID)
        self._runtime_service = runtime_service
        self._transport = transport or FakeOpenCodeTransport()

    @property
    def transport(self) -> OpenCodeTransport:
        return self._transport

    def rehydrate(self, request: RehydrateOpenCodeBridgeRequest) -> RehydratedOpenCodeBridge:
        if not isinstance(request, RehydrateOpenCodeBridgeRequest):
            raise RuntimeError("OPENCODE_BRIDGE_SCHEMA_INVALID", "request has an invalid type")
        head_seq = self._runtime_service.get_head_seq(request.mission_id)
        if request.cursor.through_seq > head_seq:
            raise RuntimeError(
                "RUNTIME_REHYDRATION_CURSOR_MISMATCH",
                "Requested bridge cursor is ahead of the Mission head",
                {"requested_seq": request.cursor.through_seq, "head_seq": head_seq},
            )
        composed = self._runtime_service.replay_composed(
            request.mission_id,
            through_seq=request.cursor.through_seq,
        )
        if composed.seq != request.cursor.through_seq:
            raise RuntimeError(
                "RUNTIME_REHYDRATION_CURSOR_MISMATCH",
                "Fixed-cursor bridge replay did not reach the requested cursor",
                {"requested_seq": request.cursor.through_seq, "replayed_seq": composed.seq},
            )
        bridge_state = composed.extension_state(EXTENSION_ID)
        if not isinstance(bridge_state, OpenCodeBridgeState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid OpenCode Bridge state")
        return RehydratedOpenCodeBridge(
            mission_id=request.mission_id,
            cursor=request.cursor,
            composed_state=composed,
            bridge_state=bridge_state,
            state_digest=canonical_sha256(composed.to_dict()),
        )

    rehydrate_bridge = rehydrate
    rehydrate_transport = rehydrate

    def execute(self, request: OpenCodeBridgeRequest | Mapping[str, Any]) -> LogicalOpenCodeBridgeResult:
        if isinstance(request, Mapping):
            request = OpenCodeBridgeRequest.from_dict(request)
        if not isinstance(request, OpenCodeBridgeRequest):
            raise RuntimeError("OPENCODE_BRIDGE_SCHEMA_INVALID", "request has an invalid type")

        composed, binding, attempt = self._rehydrate_runtime_facts(request)
        bridge_state = composed.extension_state(EXTENSION_ID)
        if not isinstance(bridge_state, OpenCodeBridgeState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid OpenCode Bridge state")
        existing = bridge_state.by_bridge_request_id(request.bridge_request_id)
        if existing is None and self._runtime_service.get_head_seq(request.mission_id) > request.expected_seq:
            current_cursor = EventCursor(request.mission_id, self._runtime_service.get_head_seq(request.mission_id), 1)
            current = self.rehydrate(RehydrateOpenCodeBridgeRequest(request.mission_id, current_cursor))
            existing = current.bridge_state.by_bridge_request_id(request.bridge_request_id)
            if existing is not None:
                if self._same_intent(existing, request):
                    return self._duplicate_result(existing, current.composed_state, binding, attempt, request)
                raise RuntimeError(
                    "OPENCODE_BRIDGE_SAME_KEY_CONFLICT",
                    f"bridge_request_id already owns different intent: {request.bridge_request_id}",
                )
        if existing is not None:
            if self._same_intent(existing, request):
                return self._duplicate_result(existing, composed, binding, attempt, request)
            raise RuntimeError(
                "OPENCODE_BRIDGE_SAME_KEY_CONFLICT",
                f"bridge_request_id already owns different intent: {request.bridge_request_id}",
            )
        if request.provider_request_id is not None:
            provider_owner = bridge_state.by_provider_request_id(request.provider_request_id)
            if provider_owner is not None:
                raise RuntimeError(
                    "OPENCODE_BRIDGE_SAME_KEY_CONFLICT",
                    f"provider_request_id already belongs to another bridge request: {request.provider_request_id}",
                )

        self._assert_head_unchanged(request.expected_seq, request.mission_id)
        call = TransportCall(
            operation=request.operation,
            bridge_request_id=request.bridge_request_id,
            attempt_id=attempt.attempt_id,
            runtime_session_id=request.runtime_session_id,
            correlation_id=request.effective_correlation_id,
            context_cursor=attempt.context_cursor,
            context_semantic_digest=attempt.context_semantic_digest,
            provider_request_id=request.provider_request_id,
            external_transport_handle=request.external_transport_handle,
            provider=binding.provider,
            model=binding.model,
        )
        observation = self._invoke_transport(call)
        self._validate_observation(observation, request, attempt)
        self._assert_head_unchanged(request.expected_seq, request.mission_id)

        command = CommandEnvelope(
            command_id=request.command_id,
            type="OPENCODE_TRANSPORT",
            mission_id=request.mission_id,
            session_id=request.runtime_session_id,
            expected_seq=request.expected_seq,
            actor=request.actor,
            payload=observation.to_dict(),
            idempotency_key=request.idempotency_key,
            correlation_id=request.effective_correlation_id,
            schema_version=1,
        )
        command_result = self._runtime_service.execute(command)
        if not command_result.ok:
            if command_result.error is not None:
                raise command_result.error
            raise RuntimeError("OPENCODE_BRIDGE_REJECTED", "OpenCode Bridge command was rejected")
        return self._post_commit_verify(request, command_result, observation, binding, attempt)

    open = execute
    send = execute
    transport = execute

    def new(self, request: OpenCodeBridgeRequest | Mapping[str, Any]) -> LogicalOpenCodeBridgeResult:
        value = OpenCodeBridgeRequest.from_dict(request) if isinstance(request, Mapping) else request
        if not isinstance(value, OpenCodeBridgeRequest):
            raise RuntimeError("OPENCODE_BRIDGE_SCHEMA_INVALID", "request has an invalid type")
        return self.execute(value.with_operation(TransportOperation.NEW))

    def reconnect(self, request: OpenCodeBridgeRequest | Mapping[str, Any]) -> LogicalOpenCodeBridgeResult:
        value = OpenCodeBridgeRequest.from_dict(request) if isinstance(request, Mapping) else request
        if not isinstance(value, OpenCodeBridgeRequest):
            raise RuntimeError("OPENCODE_BRIDGE_SCHEMA_INVALID", "request has an invalid type")
        return self.execute(value.with_operation(TransportOperation.RECONNECT))

    connect = reconnect

    def _rehydrate_runtime_facts(self, request: OpenCodeBridgeRequest) -> tuple[ComposedRuntimeState, ProviderBindingRecord, Any]:
        current_cursor = EventCursor(request.mission_id, request.expected_seq, 1)
        binding_result = ProviderBindingApplicationService(self._runtime_service).rehydrate(
            RehydrateProviderBindingRequest(request.mission_id, current_cursor)
        )
        composed = binding_result.composed_state
        if composed.seq != request.expected_seq:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "Runtime replay did not reach request sequence")
        session = composed.core_state.session(request.runtime_session_id)
        if session is None or session.status != SessionStatus.OPEN or session.mission_id != request.mission_id:
            raise RuntimeError("EXECUTION_SESSION_NOT_OPEN", f"Runtime Session is not OPEN: {request.runtime_session_id}")
        execution_state = composed.extension_state(EXECUTION_RESUME_EXTENSION_ID)
        if not isinstance(execution_state, ExecutionResumeState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Execution Resume state")
        attempt = execution_state.attempt(request.attempt_id)
        if attempt is None:
            raise RuntimeError("OPENCODE_BRIDGE_ATTEMPT_NOT_FOUND", f"Attempt not found: {request.attempt_id}")
        task_attempts = execution_state.attempts_for_task(attempt.task_id)
        current_attempt = task_attempts[-1] if task_attempts else None
        if current_attempt is None or current_attempt.attempt_id != attempt.attempt_id:
            raise RuntimeError("OPENCODE_BRIDGE_ATTEMPT_LINEAGE_INVALID", "Bridge requires the current Attempt")
        binding = binding_result.binding_state.binding(request.attempt_id)
        if binding is None:
            raise RuntimeError("OPENCODE_BRIDGE_BINDING_NOT_REHYDRATED", "ProviderBinding was not found in Runtime replay")
        if (
            binding.mission_id != request.mission_id
            or binding.runtime_session_id != request.runtime_session_id
            or attempt.mission_id != request.mission_id
            or attempt.runtime_session_id != request.runtime_session_id
        ):
            raise RuntimeError("OPENCODE_BRIDGE_LINEAGE_MISMATCH", "Attempt, Binding and Runtime Session do not agree")
        if attempt.context_cursor != request.context_cursor or attempt.context_semantic_digest != request.context_semantic_digest:
            raise RuntimeError("OPENCODE_BRIDGE_CONTEXT_MISMATCH", "request context does not match rehydrated Attempt")
        return composed, binding, attempt

    @staticmethod
    def _same_intent(existing: TransportObservationRecord, request: OpenCodeBridgeRequest) -> bool:
        return (
            existing.operation == request.operation
            and existing.attempt_id == request.attempt_id
            and existing.runtime_session_id == request.runtime_session_id
            and existing.context_cursor == request.context_cursor
            and existing.context_semantic_digest == request.context_semantic_digest
            and existing.correlation_id == request.effective_correlation_id
            and (request.provider_request_id is None or existing.provider_request_id == request.provider_request_id)
            and (request.external_transport_handle is None or existing.external_transport_handle == request.external_transport_handle)
        )

    @staticmethod
    def _duplicate_result(
        existing: TransportObservationRecord,
        composed: ComposedRuntimeState,
        binding: ProviderBindingRecord,
        attempt: Any,
        request: OpenCodeBridgeRequest,
    ) -> LogicalOpenCodeBridgeResult:
        command_result = CommandResult(
            "DUPLICATE",
            request.command_id,
            request.mission_id,
            first_seq=existing.created_seq,
            last_seq=existing.created_seq,
            duplicate_of=existing.command_id,
            state_hash=canonical_sha256(composed.to_dict()),
        )
        return LogicalOpenCodeBridgeResult(
            "DUPLICATE",
            command_result,
            existing,
            EventCursor(request.mission_id, existing.created_seq, 1),
            binding=binding,
            attempt=attempt,
        )

    def _assert_head_unchanged(self, expected_seq: int, mission_id: str) -> None:
        if self._runtime_service.get_head_seq(mission_id) != expected_seq:
            raise RuntimeError("EXPECTED_SEQ_MISMATCH", "Runtime head changed during bridge operation")

    def _invoke_transport(self, call: TransportCall) -> TransportObservation:
        try:
            value = self._transport.request(call)
        except TransportFailure:
            raise
        except TimeoutError as exc:
            raise TransportTimeout() from exc
        except RuntimeError:
            raise
        except BaseException as exc:
            raise TransportUnknown("fake transport failed without a classified result") from exc
        if isinstance(value, Mapping):
            try:
                value = TransportObservation.from_dict(value)
            except RuntimeError as exc:
                raise RuntimeError("OPENCODE_BRIDGE_UNKNOWN", "transport returned an unrecognized observation") from exc
        if not isinstance(value, TransportObservation):
            raise RuntimeError("OPENCODE_BRIDGE_UNKNOWN", "transport returned an unrecognized observation")
        return value

    @staticmethod
    def _validate_observation(
        observation: TransportObservation,
        request: OpenCodeBridgeRequest,
        attempt: Any,
    ) -> None:
        status = observation.status.upper()
        if status == "TIMEOUT":
            raise RuntimeError("OPENCODE_BRIDGE_TIMEOUT", "transport observation timed out")
        if status == "UNKNOWN":
            raise RuntimeError("OPENCODE_BRIDGE_UNKNOWN", "transport observation is UNKNOWN")
        if status == "DUPLICATE":
            raise RuntimeError("OPENCODE_BRIDGE_DUPLICATE", "transport observation is a duplicate")
        if observation.status != "ACCEPTED":
            raise RuntimeError("OPENCODE_BRIDGE_UNKNOWN", f"unsupported transport status: {observation.status}")
        if observation.operation != request.operation:
            raise RuntimeError("OPENCODE_BRIDGE_OPERATION_MISMATCH", "transport operation differs from request")
        if observation.bridge_request_id != request.bridge_request_id:
            raise RuntimeError("OPENCODE_BRIDGE_CORRELATION_MISMATCH", "transport bridge_request_id differs from request")
        if observation.attempt_id != request.attempt_id or observation.runtime_session_id != request.runtime_session_id:
            raise RuntimeError("OPENCODE_BRIDGE_LINEAGE_MISMATCH", "transport lineage differs from request")
        if observation.context_cursor != attempt.context_cursor or observation.context_semantic_digest != attempt.context_semantic_digest:
            raise RuntimeError("OPENCODE_BRIDGE_CONTEXT_MISMATCH", "transport context differs from Attempt")
        if observation.correlation_id != request.effective_correlation_id:
            raise RuntimeError("OPENCODE_BRIDGE_CORRELATION_MISMATCH", "transport correlation differs from request")
        if request.provider_request_id is not None and observation.provider_request_id != request.provider_request_id:
            raise RuntimeError("OPENCODE_BRIDGE_PROVIDER_REQUEST_MISMATCH", "provider_request_id differs from request")
        if request.operation == TransportOperation.RECONNECT and observation.external_transport_handle != request.external_transport_handle:
            raise RuntimeError("OPENCODE_BRIDGE_HANDLE_MISMATCH", "RECONNECT changed the external transport handle")

    def _post_commit_verify(
        self,
        request: OpenCodeBridgeRequest,
        result: CommandResult,
        observation: TransportObservation,
        binding: ProviderBindingRecord,
        attempt: Any,
    ) -> LogicalOpenCodeBridgeResult:
        if result.first_seq is None or result.last_seq is None or result.first_seq != result.last_seq:
            raise RuntimeError("OPENCODE_BRIDGE_SEQUENCE_MISMATCH", "bridge operation must append exactly one Event")
        event_seq = result.last_seq
        events = self._runtime_service.list_events(request.mission_id, after_seq=event_seq - 1, through_seq=event_seq)
        if len(events) != 1:
            raise RuntimeError("OPENCODE_BRIDGE_EVENT_NOT_FOUND", "persisted bridge Event was not found")
        event = events[0]
        expected_command_id = result.duplicate_of or result.command_id
        if (
            event.command_id != expected_command_id
            or event.event_type != EVENT_TYPE
            or event.entity_type != "OPENCODE_BRIDGE_REQUEST"
            or event.entity_id != request.bridge_request_id
            or event.mission_id != request.mission_id
            or event.session_id != request.runtime_session_id
            or event.correlation_id != request.effective_correlation_id
            or event.payload != observation.to_dict()
        ):
            raise RuntimeError("OPENCODE_BRIDGE_EVENT_MISMATCH", "persisted bridge Event identity or fact mismatch")
        rehydrated = self.rehydrate(
            RehydrateOpenCodeBridgeRequest(request.mission_id, EventCursor(request.mission_id, event_seq, 1))
        )
        persisted = rehydrated.bridge_state.by_bridge_request_id(request.bridge_request_id)
        if persisted is None or persisted.to_dict() != {
            **observation.to_dict(),
            "command_id": expected_command_id,
            "mission_id": request.mission_id,
            "created_seq": event_seq,
            "created_at": event.created_at,
            "created_by": {"type": event.initiator_type, "id": event.initiator_id},
        }:
            raise RuntimeError("OPENCODE_BRIDGE_EVENT_MISMATCH", "persisted bridge Event was not rehydrated")
        return LogicalOpenCodeBridgeResult(
            "DUPLICATE" if result.outcome == "DUPLICATE" else "APPLIED",
            result,
            persisted,
            EventCursor(request.mission_id, event_seq, 1),
            binding=binding,
            attempt=attempt,
        )


OpenCodeBridgeService = OpenCodeBridgeApplicationService
OpenCodeTransportApplicationService = OpenCodeBridgeApplicationService


__all__ = [
    "OpenCodeBridgeApplicationService",
    "OpenCodeBridgeService",
    "OpenCodeTransportApplicationService",
]
