from __future__ import annotations

from dataclasses import replace
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
from aitest_runtime.execution_resume import EXTENSION_ID as EXECUTION_RESUME_EXTENSION_ID, ExecutionResumeState
from aitest_runtime.provider_binding import EXTENSION_ID as PROVIDER_BINDING_EXTENSION_ID, ProviderBindingState
from aitest_runtime.work_graph import EXTENSION_ID as WORK_GRAPH_EXTENSION_ID, PlanLifecycleState, TaskLifecycleState, WorkGraphState

from .adapter import (
    FakeToolAdapter,
    ToolAdapter,
    ToolAdapterFailure,
    ToolExecutionRejected,
    ToolExecutionTimeout,
    ToolExecutionUnknown,
)
from .contracts import (
    EVIDENCE_COMMAND,
    EVIDENCE_EVENT,
    ExecutionFact,
    EvidenceInput,
    EvidenceRecord,
    LogicalEvidenceResult,
    LogicalToolExecutionResult,
    OUTCOME_COMMAND,
    OUTCOME_EVENT,
    RECONCILE_COMMAND,
    RECONCILE_EVENT,
    REQUEST_COMMAND,
    REQUEST_EVENT,
    ReconcileToolExecutionRequest,
    RecordEvidenceRequest,
    RecordToolExecutionOutcomeRequest,
    RehydrateToolExecutionRequest,
    RehydratedToolExecution,
    SideEffectPolicy,
    SideEffectState,
    ToolCall,
    ToolExecutionOutcomeRequest,
    ToolExecutionRecord,
    ToolExecutionRequest,
    ToolExecutionState,
    ToolObservation,
)
from .evidence import build_evidence


class ToolExecutionApplicationService:
    """Application boundary around the shared Runtime and a constrained adapter.

    The REQUEST command is committed before ``adapter.invoke``.  The adapter
    call is deliberately outside the Runtime transaction; its classified
    result is committed by a second command.
    """

    def __init__(self, runtime_service: RuntimeService, adapter: ToolAdapter | None = None) -> None:
        if runtime_service is None:
            raise ValueError("runtime_service is required")
        for extension_id in (WORK_GRAPH_EXTENSION_ID, EXECUTION_RESUME_EXTENSION_ID, PROVIDER_BINDING_EXTENSION_ID, "r1_4_tool_execution"):
            runtime_service.extension_registry.manifest(extension_id)
        self._runtime_service = runtime_service
        self._adapter = adapter or FakeToolAdapter()

    @property
    def runtime_service(self) -> RuntimeService:
        return self._runtime_service

    @property
    def adapter(self) -> ToolAdapter:
        return self._adapter

    def rehydrate(self, request: RehydrateToolExecutionRequest) -> RehydratedToolExecution:
        if not isinstance(request, RehydrateToolExecutionRequest):
            raise RuntimeError("TOOL_EXECUTION_SCHEMA_INVALID", "rehydration request has an invalid type")
        head_seq = self._runtime_service.get_head_seq(request.mission_id)
        if request.cursor.through_seq > head_seq:
            raise RuntimeError(
                "RUNTIME_REHYDRATION_CURSOR_MISMATCH",
                "Requested Tool Execution cursor is ahead of Mission head",
                {"requested_seq": request.cursor.through_seq, "head_seq": head_seq},
            )
        composed = self._runtime_service.replay_composed(request.mission_id, through_seq=request.cursor.through_seq)
        if composed.seq != request.cursor.through_seq:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "fixed-cursor replay did not reach the requested cursor")
        state = composed.extension_state("r1_4_tool_execution")
        if not isinstance(state, ToolExecutionState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Tool Execution state")
        return RehydratedToolExecution(
            request.mission_id,
            request.cursor,
            composed,
            state,
            canonical_sha256(composed.to_dict()),
        )

    def request(self, request: ToolExecutionRequest) -> LogicalToolExecutionResult:
        request = self._coerce_request(request)
        normalized, composed = self._prepare_request(request)
        existing = self._existing_result(normalized, composed)
        if existing is not None:
            return existing
        command = CommandEnvelope(
            command_id=normalized.command_id,
            type=REQUEST_COMMAND,
            mission_id=normalized.mission_id,
            session_id=normalized.runtime_session_id,
            expected_seq=normalized.expected_seq,
            actor=normalized.actor,
            payload=self._request_payload(normalized),
            idempotency_key=normalized.idempotency_key,
            correlation_id=normalized.correlation_id,
            schema_version=1,
        )
        result = self._runtime_service.execute(command)
        self._raise_rejected(result, "Tool Execution request was rejected")
        if result.last_seq is None:
            raise RuntimeError("TOOL_EXECUTION_EVENT_NOT_FOUND", "Tool Execution request did not append an Event")
        return self._result_at(normalized, result, result.last_seq, outcome="APPLIED")

    request_execution = request
    begin = request

    def execute(self, request: ToolExecutionRequest) -> LogicalToolExecutionResult:
        request = self._coerce_request(request)
        started = self.request(request)
        if started.outcome == "DUPLICATE":
            return started
        normalized = self._normalize_request(request, started.record.intent.context_semantic_digest)
        self._assert_adapter_allowed(normalized)
        call = ToolCall(
            tool_execution_id=normalized.tool_execution_id,
            capability_id=normalized.capability_id,
            capability_version=normalized.capability_version,
            provider_binding_id=normalized.provider_binding_id,
            provider_binding_digest=normalized.provider_binding_digest,
            context_cursor=normalized.context_cursor,
            input_digest=normalized.input_digest,
            side_effect_policy=normalized.side_effect_policy,
            input_reference=normalized.input_reference,
            redacted_input=normalized.redacted_input,
            authorization_id=normalized.authorization_id,
        )
        observation = self._invoke_adapter(call, normalized.side_effect_policy)
        self._assert_head_unchanged(started.command_result.last_seq or normalized.expected_seq, normalized.mission_id)
        outcome_request = ToolExecutionOutcomeRequest(
            command_id=f"{normalized.command_id}:outcome",
            idempotency_key=f"{normalized.idempotency_key}:outcome" if normalized.idempotency_key else None,
            mission_id=normalized.mission_id,
            runtime_session_id=normalized.runtime_session_id,
            expected_seq=self._runtime_service.get_head_seq(normalized.mission_id),
            actor=normalized.actor,
            correlation_id=normalized.effective_correlation_id,
            tool_execution_id=normalized.tool_execution_id,
            observation=observation,
        )
        outcome = self.record_outcome(outcome_request)
        final_outcome = "UNKNOWN" if observation.status == SideEffectState.UNKNOWN else "APPLIED"
        return replace(outcome, outcome=final_outcome)  # type: ignore[arg-type]

    run = execute

    @staticmethod
    def _coerce_request(request: ToolExecutionRequest | Mapping[str, Any]) -> ToolExecutionRequest:
        if isinstance(request, Mapping):
            return ToolExecutionRequest.from_dict(request)
        return request

    def record_outcome(self, request: ToolExecutionOutcomeRequest) -> LogicalToolExecutionResult:
        if not isinstance(request, ToolExecutionOutcomeRequest):
            raise RuntimeError("TOOL_EXECUTION_SCHEMA_INVALID", "outcome request has an invalid type")
        command = CommandEnvelope(
            command_id=request.command_id,
            type=OUTCOME_COMMAND,
            mission_id=request.mission_id,
            session_id=request.runtime_session_id,
            expected_seq=request.expected_seq,
            actor=request.actor,
            payload={"tool_execution_id": request.tool_execution_id, "observation": request.observation.to_dict()},
            idempotency_key=request.idempotency_key,
            correlation_id=request.correlation_id,
            schema_version=1,
        )
        result = self._runtime_service.execute(command)
        self._raise_rejected(result, "Tool Execution outcome was rejected")
        if result.last_seq is None:
            raise RuntimeError("TOOL_EXECUTION_EVENT_NOT_FOUND", "Tool Execution outcome did not append an Event")
        return self._result_at(request, result, result.last_seq, outcome="APPLIED")

    observe = record_outcome
    record_tool_execution_outcome = record_outcome

    def reconcile(self, request: ReconcileToolExecutionRequest) -> LogicalToolExecutionResult:
        if not isinstance(request, ReconcileToolExecutionRequest):
            raise RuntimeError("TOOL_EXECUTION_SCHEMA_INVALID", "reconciliation request has an invalid type")
        command = CommandEnvelope(
            command_id=request.command_id,
            type=RECONCILE_COMMAND,
            mission_id=request.mission_id,
            session_id=request.runtime_session_id,
            expected_seq=request.expected_seq,
            actor=request.actor,
            payload={
                "tool_execution_id": request.tool_execution_id,
                "reconciliation_id": request.reconciliation_id,
                "observation": request.observation.to_dict(),
            },
            idempotency_key=request.idempotency_key,
            correlation_id=request.correlation_id,
            schema_version=1,
        )
        result = self._runtime_service.execute(command)
        self._raise_rejected(result, "Tool Execution reconciliation was rejected")
        if result.last_seq is None:
            raise RuntimeError("TOOL_EXECUTION_EVENT_NOT_FOUND", "Tool Execution reconciliation did not append an Event")
        return self._result_at(request, result, result.last_seq, outcome="APPLIED")

    reconcile_tool_execution = reconcile

    def record_evidence(self, request: RecordEvidenceRequest) -> LogicalEvidenceResult:
        if not isinstance(request, RecordEvidenceRequest):
            raise RuntimeError("TOOL_EXECUTION_SCHEMA_INVALID", "evidence request has an invalid type")
        current = self._runtime_service.replay_composed(request.mission_id)
        state = current.extension_state("r1_4_tool_execution")
        if not isinstance(state, ToolExecutionState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Tool Execution state")
        existing_record = state.execution(request.evidence.tool_execution_id)
        if existing_record is None:
            raise RuntimeError("TOOL_EXECUTION_NOT_FOUND", "evidence has no prior Tool Execution")
        existing = next((item for item in existing_record.evidence if item.evidence_id == request.evidence.evidence_id), None)
        if existing is not None:
            if existing.content_digest != request.evidence.content_digest:
                raise RuntimeError("EVIDENCE_INTENT_CONFLICT", "evidence_id already owns a different digest")
            return LogicalEvidenceResult(
                "DUPLICATE",
                CommandResult("DUPLICATE", request.command_id, request.mission_id, existing.created_seq, existing.created_seq, duplicate_of=existing.command_id, state_hash=canonical_sha256(current.to_dict())),
                existing,
                EventCursor(request.mission_id, existing.created_seq, 1),
            )
        command = CommandEnvelope(
            command_id=request.command_id,
            type=EVIDENCE_COMMAND,
            mission_id=request.mission_id,
            session_id=request.runtime_session_id,
            expected_seq=request.expected_seq,
            actor=request.actor,
            payload={
                "evidence": {
                    **request.evidence.to_dict(),
                    "mission_id": request.mission_id,
                    "command_id": request.command_id,
                    "created_seq": request.expected_seq + 1,
                    "created_at": "pending",
                    "created_by": {"type": request.actor.type, "id": request.actor.id},
                }
            },
            idempotency_key=request.idempotency_key,
            correlation_id=request.correlation_id,
            schema_version=1,
        )
        result = self._runtime_service.execute(command)
        self._raise_rejected(result, "Evidence command was rejected")
        if result.last_seq is None:
            raise RuntimeError("EVIDENCE_EVENT_NOT_FOUND", "Evidence command did not append an Event")
        composed = self._runtime_service.replay_composed(request.mission_id, through_seq=result.last_seq)
        state = composed.extension_state("r1_4_tool_execution")
        record = state.execution(request.evidence.tool_execution_id) if isinstance(state, ToolExecutionState) else None
        evidence = next((item for item in record.evidence if item.evidence_id == request.evidence.evidence_id), None) if record else None
        if evidence is None:
            raise RuntimeError("EVIDENCE_EVENT_NOT_FOUND", "Evidence Event was not rehydrated")
        return LogicalEvidenceResult("APPLIED", result, evidence, EventCursor(request.mission_id, result.last_seq, 1))

    attach_evidence = record_evidence
    record = record_evidence

    def evidence(self, request: RecordEvidenceRequest) -> LogicalEvidenceResult:
        return self.record_evidence(request)

    def _prepare_request(self, request: ToolExecutionRequest) -> tuple[ToolExecutionRequest, Any]:
        if not isinstance(request, ToolExecutionRequest):
            raise RuntimeError("TOOL_EXECUTION_SCHEMA_INVALID", "request has an invalid type")
        cursor_request = RehydrateToolExecutionRequest(
            request.mission_id,
            EventCursor(request.mission_id, request.expected_seq, 1),
        )
        rehydrated = self.rehydrate(cursor_request)
        self._validate_preconditions(request, rehydrated)
        attempt = rehydrated.composed_state.extension_state(EXECUTION_RESUME_EXTENSION_ID).attempt(request.attempt_id)
        normalized = self._normalize_request(request, attempt.context_semantic_digest)
        return normalized, rehydrated.composed_state

    @staticmethod
    def _normalize_request(request: ToolExecutionRequest, context_semantic_digest: str | None) -> ToolExecutionRequest:
        return replace(request, context_semantic_digest=request.context_semantic_digest or context_semantic_digest)

    def _validate_preconditions(self, request: ToolExecutionRequest, rehydrated: RehydratedToolExecution) -> None:
        composed = rehydrated.composed_state
        core = composed.core_state
        mission = core.mission
        if mission is None:
            raise RuntimeError("MISSION_NOT_FOUND", f"Mission not found: {request.mission_id}")
        if mission.status.value != "ACTIVE":
            raise RuntimeError("INVALID_STATE_TRANSITION", "Tool Execution requires an ACTIVE Mission")
        session = core.session(request.runtime_session_id)
        if session is None or session.mission_id != request.mission_id or session.status != SessionStatus.OPEN:
            raise RuntimeError("EXECUTION_SESSION_NOT_OPEN", f"Runtime Session is not OPEN: {request.runtime_session_id}")
        graph = composed.extension_state(WORK_GRAPH_EXTENSION_ID)
        if not isinstance(graph, WorkGraphState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Work Graph state")
        plan = graph.plan(request.plan_id)
        if plan is None or plan.lifecycle_state != PlanLifecycleState.OPEN or plan.current_revision_id != request.plan_revision_id:
            raise RuntimeError("TOOL_EXECUTION_PLAN_NOT_CURRENT", "Tool Execution requires the current OPEN Plan Revision")
        task = graph.task(request.task_id)
        if task is None or task.plan_id != request.plan_id or task.plan_revision_id != request.plan_revision_id:
            raise RuntimeError("TOOL_EXECUTION_LINEAGE_MISMATCH", "Task does not belong to the Plan Revision")
        if task.lifecycle_state != TaskLifecycleState.ACTIVE:
            raise RuntimeError("TOOL_EXECUTION_TASK_NOT_ACTIVE", "Tool Execution requires an ACTIVE Task")
        attempts = composed.extension_state(EXECUTION_RESUME_EXTENSION_ID)
        if not isinstance(attempts, ExecutionResumeState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Execution Resume state")
        attempt = attempts.attempt(request.attempt_id)
        if attempt is None:
            raise RuntimeError("TOOL_EXECUTION_ATTEMPT_NOT_FOUND", f"Attempt not found: {request.attempt_id}")
        if attempt.task_id != request.task_id or attempt.runtime_session_id != request.runtime_session_id or attempts.latest_attempt(request.task_id) != attempt:
            raise RuntimeError("TOOL_EXECUTION_LINEAGE_MISMATCH", "Attempt does not match Task or Runtime Session")
        if request.context_cursor != attempt.context_cursor:
            raise RuntimeError("TOOL_EXECUTION_CONTEXT_MISMATCH", "fixed context cursor does not match Attempt")
        bindings = composed.extension_state(PROVIDER_BINDING_EXTENSION_ID)
        if not isinstance(bindings, ProviderBindingState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Provider Binding state")
        binding = bindings.binding(request.attempt_id)
        if binding is None or request.provider_binding_id != binding.attempt_id or request.provider_binding_digest != canonical_sha256(binding.to_dict()):
            raise RuntimeError("TOOL_EXECUTION_PROVIDER_BINDING_MISMATCH", "ProviderBinding identity or digest does not match Runtime")
        if request.side_effect_policy == SideEffectPolicy.IRREVERSIBLE and not request.authorization_id:
            raise RuntimeError("TOOL_EXECUTION_AUTHORIZATION_REQUIRED", "IRREVERSIBLE side effects require explicit authorization")

    def _existing_result(self, request: ToolExecutionRequest, composed: Any) -> LogicalToolExecutionResult | None:
        state = composed.extension_state("r1_4_tool_execution")
        if not isinstance(state, ToolExecutionState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Tool Execution state")
        existing = state.execution(request.tool_execution_id)
        if existing is None and request.idempotency_key is not None:
            existing = state.by_idempotency_key(request.idempotency_key)
        if existing is None:
            return None
        if existing.intent.intent_digest != request.intent_digest:
            raise RuntimeError("TOOL_EXECUTION_SAME_KEY_CONFLICT", "Tool Execution idempotency key owns a different intent")
        sequence = existing.intent.created_seq
        command = CommandResult(
            "DUPLICATE", request.command_id, request.mission_id, sequence, sequence,
            duplicate_of=existing.intent.command_id, state_hash=canonical_sha256(composed.to_dict()),
        )
        return LogicalToolExecutionResult("DUPLICATE", command, existing, EventCursor(request.mission_id, sequence, 1))

    @staticmethod
    def _request_payload(request: ToolExecutionRequest) -> dict[str, Any]:
        return {
            "tool_execution_id": request.tool_execution_id, "plan_id": request.plan_id, "plan_revision_id": request.plan_revision_id,
            "task_id": request.task_id, "attempt_id": request.attempt_id, "runtime_session_id": request.runtime_session_id,
            "capability_id": request.capability_id, "capability_version": request.capability_version,
            "provider_binding_id": request.provider_binding_id, "provider_binding_digest": request.provider_binding_digest,
            "context_cursor": request.context_cursor.to_dict(), "context_semantic_digest": request.context_semantic_digest,
            "input_digest": request.input_digest, "side_effect_policy": request.side_effect_policy.value,
            "intent_digest": request.intent_digest, "idempotency_key": request.idempotency_key,
            "input_reference": request.input_reference, "redacted_input": dict(request.redacted_input),
            "authorization_id": request.authorization_id,
        }

    def _result_at(self, request: Any, result: CommandResult, sequence: int, *, outcome: str) -> LogicalToolExecutionResult:
        state = self.rehydrate(RehydrateToolExecutionRequest(request.mission_id, EventCursor(request.mission_id, sequence, 1))).tool_execution_state
        record = state.execution(request.tool_execution_id)
        if record is None:
            raise RuntimeError("TOOL_EXECUTION_EVENT_NOT_FOUND", "Tool Execution Event was not rehydrated")
        return LogicalToolExecutionResult(outcome, result, record, EventCursor(request.mission_id, sequence, 1))  # type: ignore[arg-type]

    @staticmethod
    def _raise_rejected(result: CommandResult, message: str) -> None:
        if not result.ok:
            raise result.error or RuntimeError("TOOL_EXECUTION_REJECTED", message)

    def _assert_adapter_allowed(self, request: ToolExecutionRequest) -> None:
        if request.side_effect_policy != SideEffectPolicy.NONE and not bool(getattr(self._adapter, "constrained", False)):
            raise RuntimeError("TOOL_EXECUTION_ADAPTER_NOT_CONSTRAINED", "only constrained adapters may create side effects")
        checker = getattr(self._adapter, "can_execute", None)
        call = ToolCall(
            request.tool_execution_id, request.capability_id, request.capability_version,
            request.provider_binding_id, request.provider_binding_digest, request.context_cursor,
            request.input_digest, request.side_effect_policy, request.input_reference, request.redacted_input,
            request.authorization_id,
        )
        if callable(checker) and not checker(call):
            raise RuntimeError("TOOL_EXECUTION_ADAPTER_NOT_ALLOWED", "adapter is not allowed for this capability")

    def _invoke_adapter(self, call: ToolCall, policy: SideEffectPolicy) -> ToolObservation:
        try:
            method = getattr(self._adapter, "invoke", None) or getattr(self._adapter, "execute", None) or getattr(self._adapter, "request", None)
            if not callable(method):
                raise RuntimeError("TOOL_EXECUTION_ADAPTER_SCHEMA_INVALID", "adapter has no invoke method")
            value = method(call)
            if isinstance(value, Mapping):
                value = ToolObservation.from_dict(value)
            if not isinstance(value, ToolObservation):
                raise ToolExecutionUnknown("adapter returned an unrecognized observation")
            if policy == SideEffectPolicy.NONE and value.side_effect_state in {SideEffectState.ATTEMPTED, SideEffectState.CONFIRMED}:
                raise ToolExecutionRejected("NONE policy received a side-effecting observation")
            return value
        except ToolExecutionRejected as exc:
            return ToolObservation(SideEffectState.REJECTED, SideEffectState.REJECTED, error_code=exc.code)
        except (ToolExecutionTimeout, ToolExecutionUnknown, TimeoutError) as exc:
            return ToolObservation(SideEffectState.UNKNOWN, SideEffectState.UNKNOWN, error_code=getattr(exc, "code", "TOOL_EXECUTION_UNKNOWN"))
        except ToolAdapterFailure as exc:
            return ToolObservation(SideEffectState.UNKNOWN, SideEffectState.UNKNOWN, error_code=exc.code)
        except RuntimeError as exc:
            # A malformed or unclassified adapter response is an UNKNOWN
            # external result.  Persist only its stable error code; never
            # persist the adapter's raw message or payload.
            code = exc.code if exc.code.startswith("TOOL_EXECUTION_") else "TOOL_EXECUTION_UNKNOWN"
            return ToolObservation(SideEffectState.UNKNOWN, SideEffectState.UNKNOWN, error_code=code)
        except BaseException:
            return ToolObservation(SideEffectState.UNKNOWN, SideEffectState.UNKNOWN, error_code="TOOL_EXECUTION_UNKNOWN")

    def _assert_head_unchanged(self, expected_seq: int, mission_id: str) -> None:
        if self._runtime_service.get_head_seq(mission_id) != expected_seq:
            raise RuntimeError("EXPECTED_SEQ_MISMATCH", "Runtime head changed during Tool Execution adapter call")


ToolExecutionService = ToolExecutionApplicationService
ToolExecutionApplicationBoundary = ToolExecutionApplicationService


__all__ = ["ToolExecutionApplicationBoundary", "ToolExecutionApplicationService", "ToolExecutionService"]
