from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import (
    CommandEnvelope,
    CommandResult,
    ComposedRuntimeState,
    EventEnvelope,
    RuntimeError,
    RuntimeService,
    SessionStatus,
    canonical_sha256,
)
from aitest_runtime.execution_context import (
    BuildExecutionContextRequest,
    ContextTarget,
    ContextTargetType,
    EventCursor,
    ExecutionContext,
    ExecutionContextApplicationService,
)
from aitest_runtime.work_graph import (
    EXTENSION_ID as WORK_GRAPH_EXTENSION_ID,
    PlanLifecycleState,
    TaskLifecycleState,
    WorkGraphState,
)

from .contracts import (
    EXTENSION_ID,
    ExecutionAttemptRecord,
    ExecutionRequest,
    ExecutionResumeState,
    LogicalExecutionResult,
    RehydrateRuntimeRequest,
    RehydratedRuntime,
    ResumeExecutionRequest,
    StartExecutionRequest,
)


class ExecutionResumeApplicationService:
    def __init__(
        self,
        runtime_service: RuntimeService,
        context_service: ExecutionContextApplicationService | None = None,
    ) -> None:
        if runtime_service is None:
            raise ValueError("runtime_service is required")
        runtime_service.extension_registry.manifest(WORK_GRAPH_EXTENSION_ID)
        runtime_service.extension_registry.manifest(EXTENSION_ID)
        self._runtime_service = runtime_service
        self._context_service = context_service or ExecutionContextApplicationService(runtime_service)
        if getattr(self._context_service, "_runtime_service", runtime_service) is not runtime_service:
            raise RuntimeError("RUNTIME_SERVICE_MISMATCH", "Context service must use the same RuntimeService")

    def rehydrate(self, request: RehydrateRuntimeRequest) -> RehydratedRuntime:
        if not isinstance(request, RehydrateRuntimeRequest):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "request has an invalid type")
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
        if composed.seq != request.cursor.through_seq or composed.core_state.seq != request.cursor.through_seq:
            raise RuntimeError(
                "RUNTIME_REHYDRATION_CURSOR_MISMATCH",
                "Fixed-cursor replay did not reach the requested cursor",
                {"requested_seq": request.cursor.through_seq, "replayed_seq": composed.seq},
            )
        execution_state = composed.extension_state(EXTENSION_ID)
        if not isinstance(execution_state, ExecutionResumeState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Execution Resume state")
        return RehydratedRuntime(
            mission_id=request.mission_id,
            cursor=request.cursor,
            composed_state=composed,
            execution_state=execution_state,
            state_digest=canonical_sha256(composed.to_dict()),
        )

    def start(self, request: StartExecutionRequest) -> LogicalExecutionResult:
        if not isinstance(request, StartExecutionRequest):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "request has an invalid type")
        return self._execute(request, "START")

    def resume(self, request: ResumeExecutionRequest) -> LogicalExecutionResult:
        if not isinstance(request, ResumeExecutionRequest):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "request has an invalid type")
        return self._execute(request, "RESUME")

    def _execute(self, request: ExecutionRequest, kind: str) -> LogicalExecutionResult:
        cursor = EventCursor(
            mission_id=request.mission_id,
            through_seq=request.expected_seq,
            stream_schema_version=1,
        )
        rehydrated = self.rehydrate(RehydrateRuntimeRequest(request.mission_id, cursor))
        self._validate_preconditions(request, rehydrated, kind)
        context = self._build_context(request, cursor)
        payload = self._command_payload(request, context, kind)
        command = CommandEnvelope(
            command_id=request.command_id,
            type="START_EXECUTION_ATTEMPT" if kind == "START" else "RESUME_EXECUTION_ATTEMPT",
            mission_id=request.mission_id,
            session_id=request.runtime_session_id,
            expected_seq=request.expected_seq,
            actor=request.actor,
            payload=payload,
            idempotency_key=request.idempotency_key,
            correlation_id=request.correlation_id,
            schema_version=1,
        )
        result = self._runtime_service.execute(command)
        if not result.ok:
            if result.error is not None:
                raise result.error
            raise RuntimeError("EXECUTION_RESUME_REJECTED", "Execution Attempt command was rejected")
        return self._post_commit_verify(request, kind, context, result)

    def _validate_preconditions(
        self,
        request: ExecutionRequest,
        rehydrated: RehydratedRuntime,
        kind: str,
    ) -> None:
        core = rehydrated.composed_state.core_state
        mission = core.mission
        if mission is None:
            raise RuntimeError("MISSION_NOT_FOUND", f"Mission not found: {request.mission_id}")
        if mission.status.value != "ACTIVE":
            raise RuntimeError("INVALID_STATE_TRANSITION", "Execution Attempt requires ACTIVE Mission")
        session = core.session(request.runtime_session_id)
        if session is None or session.mission_id != request.mission_id or session.status != SessionStatus.OPEN:
            raise RuntimeError("EXECUTION_SESSION_NOT_OPEN", f"Session is not OPEN: {request.runtime_session_id}")
        work_graph = rehydrated.composed_state.extension_state(WORK_GRAPH_EXTENSION_ID)
        if not isinstance(work_graph, WorkGraphState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Work Graph state")
        plan = work_graph.plan(request.plan_id)
        if plan is None:
            raise RuntimeError("PLAN_NOT_FOUND", f"Plan not found: {request.plan_id}")
        if plan.lifecycle_state != PlanLifecycleState.OPEN:
            raise RuntimeError("PLAN_NOT_OPEN", f"Plan is not OPEN: {request.plan_id}")
        if plan.current_revision_id != request.plan_revision_id:
            raise RuntimeError("TASK_REVISION_NOT_CURRENT", "Task must belong to the current Plan Revision")
        task = work_graph.task(request.task_id)
        if task is None:
            raise RuntimeError("TASK_NOT_FOUND", f"Task not found: {request.task_id}")
        if task.plan_id != request.plan_id or task.plan_revision_id != request.plan_revision_id:
            raise RuntimeError("REVISION_PLAN_MISMATCH", "Task identity does not match Plan Revision")
        if task.lifecycle_state != TaskLifecycleState.ACTIVE:
            raise RuntimeError("EXECUTION_TASK_NOT_ACTIVE", f"Task is not ACTIVE: {request.task_id}")
        attempts = rehydrated.execution_state
        if attempts.attempt(request.execution_attempt_id) is not None:
            raise RuntimeError("EXECUTION_ATTEMPT_ID_CONFLICT", "Attempt ID already exists")
        if kind == "START":
            if attempts.attempts_for_task(request.task_id):
                raise RuntimeError("EXECUTION_ATTEMPT_ALREADY_EXISTS", "Task already has an Attempt")
        else:
            if not isinstance(request, ResumeExecutionRequest):
                raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "RESUME requires ResumeExecutionRequest")
            predecessor = attempts.attempt(request.resume_from_attempt_id)
            if predecessor is None:
                raise RuntimeError("EXECUTION_ATTEMPT_NOT_FOUND", "Resume source Attempt not found")
            if (
                predecessor.mission_id != request.mission_id
                or predecessor.plan_id != request.plan_id
                or predecessor.plan_revision_id != request.plan_revision_id
                or predecessor.task_id != request.task_id
            ):
                raise RuntimeError("EXECUTION_LINEAGE_MISMATCH", "Resume source does not belong to target Task")
            latest = attempts.latest_attempt(request.task_id)
            if latest is None or latest.attempt_id != request.resume_from_attempt_id:
                raise RuntimeError("EXECUTION_RESUME_SOURCE_NOT_LATEST", "Resume source must be latest")

    def _build_context(self, request: ExecutionRequest, cursor: EventCursor) -> ExecutionContext:
        target = ContextTarget(
            ContextTargetType.TASK,
            plan_id=request.plan_id,
            plan_revision_id=request.plan_revision_id,
            task_id=request.task_id,
        )
        return self._context_service.build(
            BuildExecutionContextRequest(
                execution_attempt_id=request.execution_attempt_id,
                mission_id=request.mission_id,
                cursor=cursor,
                target=target,
                knowledge_set=request.knowledge_set,
                policy_id=request.policy_id,
                policy_version=request.policy_version,
                knowledge_scope=request.knowledge_scope,
            )
        )

    @staticmethod
    def _command_payload(
        request: ExecutionRequest,
        context: ExecutionContext,
        kind: str,
    ) -> dict[str, Any]:
        payload = {
            "attempt_id": request.execution_attempt_id,
            "plan_id": request.plan_id,
            "plan_revision_id": request.plan_revision_id,
            "task_id": request.task_id,
            "context_cursor": context.cursor.to_dict(),
            "context_semantic_digest": context.semantic_digest,
            "context_schema_version": context.execution_context_schema_version,
            "context_builder_version": context.builder_version,
            "context_canonicalization_version": context.canonicalization_version,
            "policy_id": context.policy_id,
            "policy_version": context.policy_version,
            "knowledge_set_digest": context.knowledge_set_digest,
        }
        if kind == "RESUME":
            if not isinstance(request, ResumeExecutionRequest):
                raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "RESUME requires ResumeExecutionRequest")
            payload["resume_from_attempt_id"] = request.resume_from_attempt_id
        return payload

    def _post_commit_verify(
        self,
        request: ExecutionRequest,
        kind: str,
        context: ExecutionContext,
        result: CommandResult,
    ) -> LogicalExecutionResult:
        if result.first_seq is None or result.last_seq is None or result.first_seq != result.last_seq:
            raise RuntimeError("EXECUTION_CONTEXT_ANCHOR_MISMATCH", "Execution Attempt command must append exactly one Event")
        event_seq = result.last_seq
        events = self._runtime_service.list_events(
            request.mission_id,
            after_seq=event_seq - 1,
            through_seq=event_seq,
        )
        if len(events) != 1:
            raise RuntimeError("EXECUTION_CONTEXT_ANCHOR_MISMATCH", "Persisted Attempt Event was not found")
        event = events[0]
        original_command_id = result.duplicate_of or result.command_id
        expected_event_type = "execution.attempt_started.v1" if kind == "START" else "execution.attempt_resumed.v1"
        if (
            event.command_id != original_command_id
            or event.event_type != expected_event_type
            or event.mission_id != request.mission_id
            or event.entity_type != "EXECUTION_ATTEMPT"
            or event.entity_id != request.execution_attempt_id
            or event.session_id != request.runtime_session_id
        ):
            raise RuntimeError("EXECUTION_CONTEXT_ANCHOR_MISMATCH", "Persisted Attempt Event identity mismatch")
        persisted = self.rehydrate(
            RehydrateRuntimeRequest(
                request.mission_id,
                EventCursor(request.mission_id, event_seq, 1),
            )
        ).execution_state.attempt(request.execution_attempt_id)
        if persisted is None:
            raise RuntimeError("EXECUTION_CONTEXT_ANCHOR_MISMATCH", "Persisted Attempt was not rehydrated")
        self._verify_anchor(request, kind, context, persisted, event)
        return LogicalExecutionResult(
            outcome=result.outcome,
            command_result=result,
            attempt=persisted,
            context=context,
            event_cursor=persisted.context_cursor,
        )

    @staticmethod
    def _verify_anchor(
        request: ExecutionRequest,
        kind: str,
        context: ExecutionContext,
        persisted: ExecutionAttemptRecord,
        event: EventEnvelope,
    ) -> None:
        if (
            persisted.attempt_id != request.execution_attempt_id
            or persisted.mission_id != request.mission_id
            or persisted.runtime_session_id != request.runtime_session_id
            or persisted.plan_id != request.plan_id
            or persisted.plan_revision_id != request.plan_revision_id
            or persisted.task_id != request.task_id
            or persisted.context_cursor != context.cursor
            or persisted.context_semantic_digest != context.semantic_digest
            or persisted.context_schema_version != context.execution_context_schema_version
            or persisted.context_builder_version != context.builder_version
            or persisted.context_canonicalization_version != context.canonicalization_version
            or persisted.policy_id != context.policy_id
            or persisted.policy_version != context.policy_version
            or persisted.knowledge_set_digest != context.knowledge_set_digest
            or persisted.attempt_kind != kind
            or (kind == "START" and persisted.predecessor_attempt_id is not None)
            or (
                kind == "RESUME"
                and (
                    not isinstance(request, ResumeExecutionRequest)
                    or persisted.predecessor_attempt_id != request.resume_from_attempt_id
                )
            )
            or event.seq != context.cursor.through_seq + 1
        ):
            raise RuntimeError("EXECUTION_CONTEXT_DIGEST_MISMATCH", "Persisted Attempt anchor differs from Context")
