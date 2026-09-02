from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, CommandEnvelope, CommandResult, RuntimeError, RuntimeService, SessionStatus, canonical_sha256
from aitest_runtime.durable_core.schema import connect
from aitest_runtime.execution_context import EventCursor, KnowledgeSetInput
from aitest_runtime.execution_resume import (
    ExecutionResumeApplicationService,
    ExecutionResumeState,
    ResumeExecutionRequest,
)
from aitest_runtime.work_graph import TaskLifecycleState, WorkGraphState

from .contracts import (
    BIND_LOGICAL_AGENT,
    CLOSE,
    CLOSE_PREDECESSOR,
    JOIN_CHILD_RESULT,
    OPEN_SUCCESSOR,
    PREDECESSOR_ALREADY_TERMINAL,
    RECORD_CHILD_RESULT,
    REGISTER_DELEGATION,
    R25Error,
    R25OperationResult,
    SessionContextEnvelope,
    SessionOrchestrationState,
    SUSPEND,
    SUSPEND_PREDECESSOR,
    RotationResult,
    command_id_for,
    default_idempotency_key,
)


DEFAULT_MAX_TOTAL_CHILDREN = 100
DEFAULT_MAX_ACTIVE_CHILDREN = 1


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R25Error("R2_5_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value


def _mapping(value: Any, name: str = "request") -> dict[str, Any]:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise R25Error("R2_5_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _actor(value: Any) -> ActorRef:
    if isinstance(value, ActorRef):
        return value
    raw = _mapping(value or {"type": "SYSTEM", "id": "r2.5"}, "actor")
    return ActorRef(_text(raw.get("type"), "actor.type"), _text(raw.get("id"), "actor.id"))


class DispatchBoundaryResult:
    def __init__(self, readiness: Any, dispatch: Any = None, activation: CommandResult | None = None) -> None:
        self.readiness = readiness
        self.dispatch = dispatch
        self.activation = activation

    @property
    def status(self) -> str:
        return self.readiness.next_state

    @property
    def dispatch_result(self) -> Any:
        return self.dispatch


class SessionOrchestrationService:
    """R2.5 application boundary over one RuntimeService.

    The service has no durable state of its own. Rotation progress is recovered
    from the shared command store, shared event stream and extension replay.
    """

    def __init__(
        self,
        runtime_service: RuntimeService,
        *,
        execution_service: ExecutionResumeApplicationService | None = None,
        dispatcher: Any = None,
    ) -> None:
        if runtime_service is None:
            raise ValueError("runtime_service is required")
        runtime_service.extension_registry.manifest("r2_5_session_orchestration")
        self._runtime = runtime_service
        self._execution_service = execution_service or ExecutionResumeApplicationService(runtime_service)
        if getattr(self._execution_service, "_runtime_service", runtime_service) is not runtime_service:
            raise R25Error("RUNTIME_SERVICE_MISMATCH", "Execution Resume service must use the same RuntimeService")
        self._dispatcher = dispatcher

    @property
    def runtime_service(self) -> RuntimeService:
        return self._runtime

    def state(self, mission_id: str) -> SessionOrchestrationState:
        value = self._runtime.replay_composed(_text(mission_id, "mission_id")).extension_state("r2_5_session_orchestration")
        if not isinstance(value, SessionOrchestrationState):
            raise R25Error("EXTENSION_SCHEMA_MISMATCH", "invalid R2.5 extension state")
        return value

    get_state = state
    get_extension_state = state

    def _command_row(self, command_id: str) -> sqlite3.Row | None:
        conn = connect(self._runtime.db_path)
        try:
            return conn.execute("SELECT * FROM commands WHERE command_id=?", (command_id,)).fetchone()
        finally:
            conn.close()

    @staticmethod
    def _row_envelope(row: sqlite3.Row) -> CommandEnvelope:
        return CommandEnvelope(
            command_id=row["command_id"], type=row["command_type"], mission_id=row["mission_id"],
            session_id=row["session_id"], expected_seq=int(row["expected_seq"]),
            actor=ActorRef(row["actor_type"], row["actor_id"]),
            payload=json.loads(row["payload_json"]), idempotency_key=row["idempotency_key"],
            correlation_id=row["correlation_id"], schema_version=int(row["schema_version"]),
        )

    def _raise_result(self, result: CommandResult) -> CommandResult:
        if not result.ok:
            if result.error is not None:
                raise result.error
            raise R25Error("R2_5_COMMAND_REJECTED", "R2.5 command was rejected")
        if result.last_seq is None:
            raise R25Error("R2_5_RECONCILIATION_REQUIRED", "successful R2.5 step has no durable last_seq")
        return result

    def _verify_persisted_step(self, result: CommandResult, command_id: str) -> None:
        if result.first_seq is None or result.last_seq is None:
            raise R25Error("R2_5_RECONCILIATION_REQUIRED", "completed command has no Event range")
        events = self._runtime.list_events(result.mission_id, after_seq=result.first_seq - 1, through_seq=result.last_seq)
        if not events or any(event.command_id != command_id for event in events):
            raise R25Error(
                "R2_5_RECONCILIATION_REQUIRED",
                "Command Store result cannot be reconciled with the shared Event Stream",
            )

    def _run_step(
        self,
        *,
        command_id: str,
        command_type: str,
        mission_id: str,
        cursor: int,
        actor: ActorRef,
        payload: Mapping[str, Any],
        session_id: str | None = None,
        correlation_id: str | None = None,
        expected_seq: int | None = None,
        replay_only: bool = False,
    ) -> CommandResult:
        row = self._command_row(command_id)
        if row is not None:
            original = self._row_envelope(row)
            # Exact replay intentionally uses the original expected_seq and
            # immutable payload; passing a new cursor here would change the
            # command fingerprint and violate the retry contract.
            result = self._runtime.execute(original)
            result = self._raise_result(result)
            self._verify_persisted_step(result, command_id)
            return result
        head = self._runtime.get_head_seq(mission_id)
        if expected_seq is not None and head != expected_seq:
            raise R25Error(
                "EXPECTED_SEQ_MISMATCH",
                f"external sequence advance before R2.5 step: expected {expected_seq}, observed {head}",
                {"expected_seq": expected_seq, "observed_seq": head, "command_id": command_id},
            )
        if head != cursor:
            raise R25Error(
                "EXPECTED_SEQ_MISMATCH",
                f"R2.5 cursor {cursor} does not match external stream head {head}",
                {"expected_seq": cursor, "observed_seq": head, "command_id": command_id},
            )
        envelope = CommandEnvelope(
            command_id=command_id,
            type=command_type,
            mission_id=mission_id,
            session_id=session_id,
            expected_seq=cursor,
            actor=actor,
            payload=dict(payload),
            idempotency_key=default_idempotency_key(command_id),
            correlation_id=correlation_id or command_id,
            schema_version=1,
        )
        result = self._runtime.execute(envelope)
        result = self._raise_result(result)
        self._verify_persisted_step(result, command_id)
        return result

    @staticmethod
    def _request(value: Any, kwargs: Mapping[str, Any]) -> dict[str, Any]:
        raw = _mapping(value or {}, "request")
        raw.update(kwargs)
        return raw

    def _replay_if_present(self, command_id: str, command_type: str, mission_id: str) -> CommandResult | None:
        if self._command_row(command_id) is None:
            return None
        return self._run_step(
            command_id=command_id, command_type=command_type, mission_id=mission_id,
            cursor=self._runtime.get_head_seq(mission_id), actor=ActorRef("SYSTEM", "r2.5-replay"),
            payload={}, replay_only=True,
        )

    def bind_logical_agent(self, request: Any = None, **kwargs: Any) -> R25OperationResult:
        raw = self._request(request, kwargs)
        mission_id = _text(raw.get("mission_id"), "mission_id")
        binding_id = _text(raw.get("binding_id"), "binding_id")
        command_id = command_id_for(binding_id, "BIND_LOGICAL_AGENT")
        if raw.get("command_id") is not None and raw["command_id"] != command_id:
            raise R25Error("DETERMINISTIC_IDENTITY_MISMATCH", "BIND_LOGICAL_AGENT command_id is not deterministic")
        state = self.state(mission_id)
        replayed = self._replay_if_present(command_id, BIND_LOGICAL_AGENT, mission_id)
        if replayed is not None:
            binding = state.binding(binding_id)
            if binding is None:
                raise R25Error("R2_5_RECONCILIATION_REQUIRED", "binding replay has no Binding fact")
            return R25OperationResult(replayed.outcome, replayed, binding)
        composed = self._runtime.replay_composed(mission_id)
        execution = composed.extension_state("r1_3b_execution_resume")
        if not isinstance(execution, ExecutionResumeState):
            raise R25Error("EXTENSION_DEPENDENCY_MISSING", "R2.5 requires R1.3B")
        attempt_id = _text(raw.get("attempt_id") or raw.get("execution_attempt_id"), "attempt_id")
        attempt = execution.attempt(attempt_id)
        if attempt is None:
            raise R25Error("ATTEMPT_NOT_FOUND", f"Attempt not found: {attempt_id}")
        payload = {
            "binding_id": binding_id,
            "logical_agent_id": _text(raw.get("logical_agent_id") or raw.get("agent_id"), "logical_agent_id"),
            "root_attempt_id": _text(raw.get("root_attempt_id") or attempt.root_attempt_id, "root_attempt_id"),
            "attempt_id": attempt_id,
            "task_id": _text(raw.get("task_id") or attempt.task_id, "task_id"),
            "session_id": _text(raw.get("session_id") or attempt.runtime_session_id, "session_id"),
        }
        result = self._run_step(
            command_id=command_id, command_type=BIND_LOGICAL_AGENT, mission_id=mission_id,
            cursor=self._runtime.get_head_seq(mission_id), actor=_actor(raw.get("actor")), payload=payload,
            session_id=payload["session_id"], correlation_id=raw.get("correlation_id"),
            expected_seq=raw.get("expected_seq"),
        )
        binding = self.state(mission_id).binding(binding_id)
        if binding is None:
            raise R25Error("R2_5_RECONCILIATION_REQUIRED", "binding command completed without a Binding fact")
        return R25OperationResult(result.outcome, result, binding)

    def register_delegation(self, request: Any = None, **kwargs: Any) -> R25OperationResult:
        raw = self._request(request, kwargs)
        mission_id = _text(raw.get("mission_id"), "mission_id")
        delegation_id = _text(raw.get("delegation_id"), "delegation_id")
        command_id = command_id_for(delegation_id, "REGISTER_DELEGATION")
        if raw.get("command_id") is not None and raw["command_id"] != command_id:
            raise R25Error("DETERMINISTIC_IDENTITY_MISMATCH", "REGISTER_DELEGATION command_id is not deterministic")
        root = _text(raw.get("parent_root_attempt_id") or raw.get("root_attempt_id"), "parent_root_attempt_id")
        state = self.state(mission_id)
        replayed = self._replay_if_present(command_id, REGISTER_DELEGATION, mission_id)
        if replayed is not None:
            delegation = state.delegation(delegation_id)
            if delegation is None:
                raise R25Error("R2_5_RECONCILIATION_REQUIRED", "delegation replay has no Delegation fact")
            return R25OperationResult(replayed.outcome, replayed, delegation)
        composed = self._runtime.replay_composed(mission_id)
        execution = composed.extension_state("r1_3b_execution_resume")
        if not isinstance(execution, ExecutionResumeState):
            raise R25Error("EXTENSION_DEPENDENCY_MISSING", "R2.5 requires R1.3B")
        parent = execution.attempt(raw.get("parent_attempt_id")) if raw.get("parent_attempt_id") else next(
            (item for item in reversed(execution.attempts) if item.root_attempt_id == root), None
        )
        if parent is None or parent.root_attempt_id != root:
            raise R25Error("PARENT_ATTEMPT_NOT_FOUND", f"Parent root Attempt not found: {root}")
        child_task_id = _text(raw.get("child_task_id") or raw.get("task_id"), "child_task_id")
        max_total = raw.get("max_total_children_per_parent", DEFAULT_MAX_TOTAL_CHILDREN)
        max_active = raw.get("max_active_children_per_parent", DEFAULT_MAX_ACTIVE_CHILDREN)
        payload = {
            "delegation_id": delegation_id,
            "parent_root_attempt_id": root,
            "parent_attempt_id": parent.attempt_id,
            "parent_task_id": parent.task_id,
            "child_task_id": child_task_id,
            "child_root_attempt_id": raw.get("child_root_attempt_id"),
            "logical_agent_id": raw.get("logical_agent_id"),
            "expected_delegation_version": raw.get("expected_delegation_version", state.delegation_version(root)),
            "expected_active_child_count": raw.get("expected_active_child_count", state.active_child_count(root)),
            "max_total_children_per_parent": max_total,
            "max_active_children_per_parent": max_active,
        }
        result = self._run_step(
            command_id=command_id, command_type=REGISTER_DELEGATION, mission_id=mission_id,
            cursor=self._runtime.get_head_seq(mission_id), actor=_actor(raw.get("actor")), payload=payload,
            session_id=raw.get("session_id") or parent.runtime_session_id, correlation_id=raw.get("correlation_id"),
            expected_seq=raw.get("expected_seq"),
        )
        delegation = self.state(mission_id).delegation(delegation_id)
        if delegation is None:
            raise R25Error("R2_5_RECONCILIATION_REQUIRED", "delegation command completed without a Delegation fact")
        return R25OperationResult(result.outcome, result, delegation)

    def record_child_result(self, request: Any = None, **kwargs: Any) -> R25OperationResult:
        raw = self._request(request, kwargs)
        mission_id = _text(raw.get("mission_id"), "mission_id")
        child_result_id = _text(raw.get("child_result_id"), "child_result_id")
        command_id = command_id_for(child_result_id, "RECORD_CHILD_RESULT")
        if raw.get("command_id") is not None and raw["command_id"] != command_id:
            raise R25Error("DETERMINISTIC_IDENTITY_MISMATCH", "RECORD_CHILD_RESULT command_id is not deterministic")
        state = self.state(mission_id)
        replayed = self._replay_if_present(command_id, RECORD_CHILD_RESULT, mission_id)
        if replayed is not None:
            child_result = state.child_result(child_result_id)
            if child_result is None:
                raise R25Error("R2_5_RECONCILIATION_REQUIRED", "ChildResult replay has no fact")
            return R25OperationResult(replayed.outcome, replayed, child_result)
        delegation_id = _text(raw.get("delegation_id"), "delegation_id")
        delegation = state.delegation(delegation_id)
        if delegation is None:
            raise R25Error("DELEGATION_NOT_FOUND", f"Delegation not found: {delegation_id}")
        child_attempt_id = _text(raw.get("child_attempt_id") or raw.get("execution_attempt_id"), "child_attempt_id")
        child_root = _text(raw.get("child_root_attempt_id") or raw.get("root_attempt_id"), "child_root_attempt_id")
        terminal_state = _text(raw.get("terminal_state") or raw.get("task_terminal_state"), "terminal_state")
        composed = self._runtime.replay_composed(mission_id)
        work_graph = composed.extension_state("r1_2_work_graph")
        task = work_graph.task(delegation.child_task_id) if isinstance(work_graph, WorkGraphState) else None
        canonical_outcome = None if task is None or task.outcome is None else dict(task.outcome)
        if "outcome" in raw:
            outcome = raw["outcome"]
        elif "result" in raw or "result_payload" in raw:
            # Legacy input is an assertion only; it is never persisted as the
            # ChildResult fact and is compared with canonical Task truth.
            outcome = raw.get("result", raw.get("result_payload"))
        else:
            outcome = canonical_outcome
        if outcome is not None and not isinstance(outcome, Mapping):
            raise R25Error("R2_5_SCHEMA_INVALID", "outcome must be an object or null")
        plan_revision_id = _text(
            raw.get("plan_revision_id") or (task.plan_revision_id if task is not None else "missing-plan-revision"),
            "plan_revision_id",
        )
        canonical_source_seq = raw.get("canonical_source_seq")
        if canonical_source_seq is None:
            canonical_source_seq = task.updated_seq if task is not None else 0
        result_ref = raw.get("result_ref")
        if result_ref is None:
            result_ref = {
                "kind": "R1.2_TASK_OUTCOME",
                "task_id": delegation.child_task_id,
                "attempt_id": child_attempt_id,
                "source_seq": canonical_source_seq,
            }
        if not isinstance(result_ref, Mapping):
            raise R25Error("R2_5_SCHEMA_INVALID", "result_ref must be an object")
        result_digest = raw.get("result_digest")
        if result_digest is None and task is not None:
            result_digest = canonical_sha256({
                "task_id": task.task_id,
                "plan_revision_id": task.plan_revision_id,
                "terminal_state": task.lifecycle_state.value,
                "outcome": canonical_outcome,
            })
        payload = {
            "child_result_id": child_result_id,
            "delegation_id": delegation_id,
            "parent_root_attempt_id": delegation.parent_root_attempt_id,
            "child_task_id": _text(raw.get("child_task_id") or delegation.child_task_id, "child_task_id"),
            "child_attempt_id": child_attempt_id,
            "child_root_attempt_id": child_root,
            "plan_revision_id": plan_revision_id,
            "terminal_state": terminal_state,
            "result_ref": dict(result_ref),
            "result_digest": result_digest,
            "canonical_source_seq": canonical_source_seq,
            "outcome": None if outcome is None else dict(outcome),
        }
        result = self._run_step(
            command_id=command_id, command_type=RECORD_CHILD_RESULT, mission_id=mission_id,
            cursor=self._runtime.get_head_seq(mission_id), actor=_actor(raw.get("actor")), payload=payload,
            session_id=raw.get("session_id"), correlation_id=raw.get("correlation_id"), expected_seq=raw.get("expected_seq"),
        )
        child_result = self.state(mission_id).child_result(child_result_id)
        if child_result is None:
            raise R25Error("R2_5_RECONCILIATION_REQUIRED", "ChildResult command completed without a fact")
        return R25OperationResult(result.outcome, result, child_result)

    def join_child_result(self, request: Any = None, **kwargs: Any) -> R25OperationResult:
        raw = self._request(request, kwargs)
        mission_id = _text(raw.get("mission_id"), "mission_id")
        join_id = _text(raw.get("join_id"), "join_id")
        delegation_id = _text(raw.get("delegation_id"), "delegation_id")
        command_id = command_id_for(join_id, "JOIN_CHILD_RESULT")
        if raw.get("command_id") is not None and raw["command_id"] != command_id:
            raise R25Error("DETERMINISTIC_IDENTITY_MISMATCH", "JOIN_CHILD_RESULT command_id is not deterministic")
        state = self.state(mission_id)
        replayed = self._replay_if_present(command_id, JOIN_CHILD_RESULT, mission_id)
        if replayed is not None:
            join = state.join(join_id)
            if join is None:
                raise R25Error("R2_5_RECONCILIATION_REQUIRED", "Join replay has no fact")
            return R25OperationResult(replayed.outcome, replayed, join)
        delegation = state.delegation(delegation_id)
        if delegation is None:
            raise R25Error("DELEGATION_NOT_FOUND", f"Delegation not found: {delegation_id}")
        root = _text(raw.get("parent_root_attempt_id") or delegation.parent_root_attempt_id, "parent_root_attempt_id")
        payload = {
            "join_id": join_id,
            "parent_root_attempt_id": root,
            "delegation_id": delegation_id,
            "child_result_id": _text(raw.get("child_result_id"), "child_result_id"),
            "expected_join_version": raw.get("expected_join_version", state.join_version(delegation_id)),
            "metadata": dict(raw.get("metadata") or {}),
        }
        result = self._run_step(
            command_id=command_id, command_type=JOIN_CHILD_RESULT, mission_id=mission_id,
            cursor=self._runtime.get_head_seq(mission_id), actor=_actor(raw.get("actor")), payload=payload,
            session_id=raw.get("session_id"), correlation_id=raw.get("correlation_id"), expected_seq=raw.get("expected_seq"),
        )
        join = self.state(mission_id).join(join_id)
        if join is None:
            raise R25Error("R2_5_RECONCILIATION_REQUIRED", "Join command completed without a Join fact")
        return R25OperationResult(result.outcome, result, join)

    def _resume_request(
        self,
        raw: Mapping[str, Any],
        *,
        mission_id: str,
        successor_session_id: str,
        rotation_operation_id: str,
        expected_seq: int,
    ) -> ResumeExecutionRequest:
        source = raw.get("resume_request", raw.get("resume"))
        if isinstance(source, ResumeExecutionRequest):
            return replace(
                source,
                command_id=command_id_for(rotation_operation_id, "RESUME_ATTEMPT"),
                idempotency_key=command_id_for(rotation_operation_id, "RESUME_ATTEMPT"),
                mission_id=mission_id,
                runtime_session_id=successor_session_id,
                expected_seq=expected_seq,
                correlation_id=source.correlation_id or rotation_operation_id,
            )
        nested = dict(source) if isinstance(source, Mapping) else {}
        merged = dict(raw)
        merged.update(nested)
        composed = self._runtime.replay_composed(mission_id)
        execution = composed.extension_state("r1_3b_execution_resume")
        if not isinstance(execution, ExecutionResumeState):
            raise R25Error("EXTENSION_DEPENDENCY_MISSING", "R2.5 requires R1.3B")
        predecessor = merged.get("resume_from_attempt_id", merged.get("predecessor_attempt_id"))
        if predecessor is None:
            root = merged.get("root_attempt_id")
            candidate = next((item for item in reversed(execution.attempts) if root and item.root_attempt_id == root), None)
            predecessor = candidate.attempt_id if candidate is not None else None
        predecessor = _text(predecessor, "resume_from_attempt_id")
        source_attempt = execution.attempt(predecessor)
        if source_attempt is None:
            raise R25Error("ATTEMPT_NOT_FOUND", f"Resume source Attempt not found: {predecessor}")
        attempt_id = _text(
            merged.get("execution_attempt_id", merged.get("attempt_id", merged.get("resume_attempt_id", command_id_for(rotation_operation_id, "ATTEMPT")))),
            "execution_attempt_id",
        )
        knowledge = merged.get("knowledge_set", merged.get("knowledge", KnowledgeSetInput([])))
        if not isinstance(knowledge, KnowledgeSetInput):
            knowledge = KnowledgeSetInput.from_dict(knowledge) if isinstance(knowledge, Mapping) else KnowledgeSetInput(knowledge)
        actor = _actor(merged.get("actor"))
        return ResumeExecutionRequest(
            command_id=command_id_for(rotation_operation_id, "RESUME_ATTEMPT"),
            idempotency_key=command_id_for(rotation_operation_id, "RESUME_ATTEMPT"),
            mission_id=mission_id,
            runtime_session_id=successor_session_id,
            expected_seq=expected_seq,
            actor=actor,
            correlation_id=merged.get("correlation_id") or rotation_operation_id,
            execution_attempt_id=attempt_id,
            plan_id=_text(merged.get("plan_id") or source_attempt.plan_id, "plan_id"),
            plan_revision_id=_text(merged.get("plan_revision_id") or source_attempt.plan_revision_id, "plan_revision_id"),
            task_id=_text(merged.get("task_id") or source_attempt.task_id, "task_id"),
            knowledge_set=knowledge,
            policy_id=_text(merged.get("policy_id", "r1.3a.structural"), "policy_id"),
            policy_version=merged.get("policy_version", 1),
            knowledge_scope=merged.get("knowledge_scope", {}),
            resume_from_attempt_id=predecessor,
        )

    def _run_resume_step(
        self,
        raw: Mapping[str, Any],
        *,
        mission_id: str,
        successor_session_id: str,
        rotation_operation_id: str,
        cursor: int,
    ) -> tuple[CommandResult, Any, SessionContextEnvelope]:
        command_id = command_id_for(rotation_operation_id, "RESUME_ATTEMPT")
        row = self._command_row(command_id)
        if row is not None:
            result = self._run_step(
                command_id=command_id, command_type="RESUME_EXECUTION_ATTEMPT", mission_id=mission_id,
                cursor=cursor, actor=_actor(raw.get("actor")), payload={}, session_id=successor_session_id,
                replay_only=True,
            )
            attempt_id = json.loads(row["payload_json"])["attempt_id"]
            attempt = self.state(mission_id)  # force Event Stream replay after exact command replay
            execution = self._runtime.replay_composed(mission_id).extension_state("r1_3b_execution_resume")
            persisted = execution.attempt(attempt_id)
            if persisted is None:
                raise R25Error("R2_5_RECONCILIATION_REQUIRED", "Resume replay has no canonical Attempt")
            envelope = SessionContextEnvelope(
                mission_id, persisted.context_cursor.mission_id and raw.get("predecessor_session_id"),
                successor_session_id, persisted.root_attempt_id, persisted.attempt_id,
                EventCursor(mission_id, result.last_seq or 0, 1), None,
            )
            return result, persisted, envelope
        request = self._resume_request(
            raw, mission_id=mission_id, successor_session_id=successor_session_id,
            rotation_operation_id=rotation_operation_id, expected_seq=cursor,
        )
        logical = self._execution_service.resume(request)
        result = self._raise_result(logical.command_result)
        if result.command_id != command_id:
            raise R25Error("R2_5_RECONCILIATION_REQUIRED", "R1.3B Resume command identity is not deterministic")
        envelope = SessionContextEnvelope(
            mission_id, raw.get("predecessor_session_id"), successor_session_id,
            logical.attempt.root_attempt_id, logical.attempt.attempt_id,
            EventCursor(mission_id, result.last_seq or 0, 1), logical.context,
        )
        return result, logical.attempt, envelope

    def rotate_session(self, request: Any = None, **kwargs: Any) -> RotationResult:
        raw = self._request(request, kwargs)
        mission_id = _text(raw.get("mission_id"), "mission_id")
        operation_id = _text(raw.get("rotation_operation_id") or raw.get("operation_id"), "rotation_operation_id")
        predecessor_session_id = _text(raw.get("predecessor_session_id") or raw.get("session_id"), "predecessor_session_id")
        successor_session_id = _text(raw.get("successor_session_id"), "successor_session_id")
        if predecessor_session_id == successor_session_id:
            raise R25Error("ROTATION_IDENTITY_CONFLICT", "successor_session_id must be distinct")
        composed = self._runtime.replay_composed(mission_id)
        predecessor = composed.core_state.session(predecessor_session_id)
        if predecessor is None:
            raise R25Error("SESSION_NOT_FOUND", f"Session not found: {predecessor_session_id}")
        suspend_command_id = command_id_for(operation_id, f"{SUSPEND}_PREDECESSOR")
        close_command_id = command_id_for(operation_id, f"{CLOSE}_PREDECESSOR")
        stored_suspend = self._command_row(suspend_command_id)
        stored_close = self._command_row(close_command_id)
        if stored_suspend is not None and stored_close is not None:
            raise R25Error("ROTATION_RECONCILIATION_REQUIRED", "rotation operation has two predecessor transitions")
        durable_transition = SUSPEND if stored_suspend is not None else CLOSE if stored_close is not None else None
        open_command = command_id_for(operation_id, OPEN_SUCCESSOR)
        stored_open = self._command_row(open_command)
        if stored_open is not None:
            if stored_open["session_id"] != successor_session_id:
                raise R25Error("ROTATION_IDENTITY_CONFLICT", "successor_session_id differs from the durable OPEN_SUCCESSOR envelope")
            stored_transition = json.loads(stored_open["payload_json"]).get("rotation_transition")
            if stored_transition and durable_transition and stored_transition != durable_transition:
                raise R25Error("ROTATION_RECONCILIATION_REQUIRED", "durable rotation transition facts disagree")
            if stored_transition and durable_transition is None:
                durable_transition = stored_transition
        transition = raw.get("rotation_transition")
        if durable_transition is not None:
            transition = durable_transition
        if transition is None:
            transition = PREDECESSOR_ALREADY_TERMINAL if predecessor.status in {SessionStatus.CLOSED, SessionStatus.FAILED} else (SUSPEND if predecessor.status == SessionStatus.OPEN else CLOSE)
        transition = _text(transition, "rotation_transition").upper()
        if transition not in {SUSPEND, CLOSE, PREDECESSOR_ALREADY_TERMINAL}:
            raise R25Error("ROTATION_TRANSITION_INVALID", "rotation_transition must be SUSPEND, CLOSE or PREDECESSOR_ALREADY_TERMINAL")
        if durable_transition is None and predecessor.status in {SessionStatus.CLOSED, SessionStatus.FAILED}:
            transition = PREDECESSOR_ALREADY_TERMINAL
        elif transition == PREDECESSOR_ALREADY_TERMINAL:
            raise R25Error("ROTATION_TRANSITION_INVALID", "predecessor is not terminal")
        actor = _actor(raw.get("actor"))
        cursor = self._runtime.get_head_seq(mission_id)
        transition_result: CommandResult | None = None
        transition_command = None
        open_command = command_id_for(operation_id, OPEN_SUCCESSOR)
        if transition != PREDECESSOR_ALREADY_TERMINAL:
            transition_command = command_id_for(operation_id, f"{transition}_PREDECESSOR")
            transition_result = self._run_step(
                command_id=transition_command,
                command_type="SUSPEND_SESSION" if transition == SUSPEND else "CLOSE_SESSION",
                mission_id=mission_id, cursor=cursor, actor=actor,
                payload={"reason": "R2.5_SESSION_ROTATION", "rotation_operation_id": operation_id},
                session_id=predecessor_session_id, correlation_id=operation_id,
                expected_seq=raw.get("expected_seq"),
            )
            cursor = transition_result.last_seq or cursor
        if raw.get("expected_seq") is not None and transition == PREDECESSOR_ALREADY_TERMINAL and self._command_row(open_command) is None:
            if self._runtime.get_head_seq(mission_id) != raw["expected_seq"]:
                observed_head = self._runtime.get_head_seq(mission_id)
                raise R25Error(
                    "EXPECTED_SEQ_MISMATCH",
                    f"rotation expected_seq {raw['expected_seq']} does not match stream head {observed_head}",
                )
        open_result = self._run_step(
            command_id=open_command, command_type="OPEN_SESSION", mission_id=mission_id, cursor=cursor,
            actor=actor,
            payload={
                "rotation_operation_id": operation_id,
                "predecessor_session_id": predecessor_session_id,
                "rotation_transition": transition,
            },
            session_id=successor_session_id, correlation_id=operation_id,
        )
        cursor = open_result.last_seq or cursor
        raw_resume = dict(raw)
        raw_resume["predecessor_session_id"] = predecessor_session_id
        resume_result, attempt, context_envelope = self._run_resume_step(
            raw_resume, mission_id=mission_id, successor_session_id=successor_session_id,
            rotation_operation_id=operation_id, cursor=cursor,
        )
        cursor = resume_result.last_seq or cursor
        binding = None
        binding_result = None
        if raw.get("logical_agent_id") is not None or raw.get("binding_id") is not None:
            binding_id = _text(raw.get("binding_id") or f"{operation_id}:binding", "binding_id")
            binding_operation_result = self.bind_logical_agent(
                mission_id=mission_id, binding_id=binding_id, logical_agent_id=raw.get("logical_agent_id"),
                root_attempt_id=attempt.root_attempt_id, attempt_id=attempt.attempt_id, task_id=attempt.task_id,
                session_id=successor_session_id, actor=raw.get("actor"), expected_seq=cursor,
            )
            binding = binding_operation_result.record
            binding_result = binding_operation_result.command_result
        return RotationResult(
            rotation_operation_id=operation_id, rotation_transition=transition,
            predecessor_session_id=predecessor_session_id, successor_session_id=successor_session_id,
            transition_result=transition_result, open_result=open_result, resume_result=resume_result,
            attempt=attempt, binding=binding, binding_result=binding_result, context_envelope=context_envelope,
        )

    rotate = rotate_session
    orchestrate_rotation = rotate_session

    def dispatch_existing_child(self, request: Any = None, **kwargs: Any) -> DispatchBoundaryResult:
        raw = self._request(request, kwargs)
        mission_id = _text(raw.get("mission_id"), "mission_id")
        delegation_id = _text(raw.get("delegation_id"), "delegation_id")
        delegation = self.state(mission_id).delegation(delegation_id)
        if delegation is None:
            raise R25Error("DELEGATION_NOT_FOUND", f"Delegation not found: {delegation_id}")
        from aitest_runtime.r2_4 import TaskDispatcher, activation_command, evaluate_readiness, make_dispatch_request

        composed = self._runtime.replay_composed(mission_id)
        work_graph = composed.extension_state("r1_2_work_graph")
        if not isinstance(work_graph, WorkGraphState):
            raise R25Error("EXTENSION_DEPENDENCY_MISSING", "R2.5 requires R1.2 Work Graph")
        binding = raw.get("dispatch_binding", raw.get("binding"))
        resolution = raw.get("resolution")
        observed_at = _text(raw.get("observed_at"), "observed_at")
        report = evaluate_readiness(
            work_graph,
            mission_id=mission_id,
            plan_id=raw.get("plan_id") or work_graph.task(delegation.child_task_id).plan_id,
            plan_revision_id=raw.get("plan_revision_id") or work_graph.task(delegation.child_task_id).plan_revision_id,
            observed_seq=self._runtime.get_head_seq(mission_id),
            resolution=resolution,
            dispatch_bindings=(binding,),
            observed_at=observed_at,
        )
        if report.next_state not in {"DISPATCH", "READY"}:
            return DispatchBoundaryResult(report)
        dispatch_request = make_dispatch_request(
            mission_id=mission_id, plan_id=report.plan_id, plan_revision_id=report.plan_revision_id,
            task_id=delegation.child_task_id, binding=binding,
        )
        activation = None
        task = work_graph.task(delegation.child_task_id)
        if task is not None and task.lifecycle_state.value == "PENDING":
            command = activation_command(
                dispatch_request, expected_seq=self._runtime.get_head_seq(mission_id),
                actor=raw.get("actor") or {"type": "SYSTEM", "id": "r2.5-dispatcher"},
            )
            activation = self._runtime.execute(command)
            if not activation.ok:
                if activation.error is not None:
                    raise activation.error
                raise R25Error("R2_4_DISPATCH_REJECTED", "normal R2.4 activation was rejected")
        dispatcher = raw.get("dispatcher", self._dispatcher)
        if dispatcher is None:
            dispatcher = TaskDispatcher()
        dispatch = dispatcher.dispatch(dispatch_request) if hasattr(dispatcher, "dispatch") else dispatcher(dispatch_request)
        return DispatchBoundaryResult(report, dispatch=dispatch, activation=activation)

    dispatch_child = dispatch_existing_child
    dispatch = dispatch_existing_child

    bind_agent = bind_logical_agent
    register_child_delegation = register_delegation
    record_child = record_child_result
    join_child = join_child_result
    rotate_session_context = rotate_session


R25ApplicationService = SessionOrchestrationService
SessionOrchestrationApplicationService = SessionOrchestrationService
