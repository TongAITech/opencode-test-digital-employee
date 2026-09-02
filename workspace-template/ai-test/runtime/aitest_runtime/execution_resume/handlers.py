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
from aitest_runtime.work_graph import (
    EXTENSION_ID as WORK_GRAPH_EXTENSION_ID,
    PlanLifecycleState,
    TaskLifecycleState,
    WorkGraphState,
)

from .contracts import EXTENSION_ID, ExecutionResumeState


COMMAND_TYPES = frozenset({
    "START_EXECUTION_ATTEMPT",
    "RESUME_EXECUTION_ATTEMPT",
})

EVENT_TYPES = frozenset({
    "execution.attempt_started.v1",
    "execution.attempt_resumed.v1",
})


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("COMMAND_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value


def _digest(value: Any, name: str) -> str:
    value = _text(value, name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise RuntimeError("COMMAND_SCHEMA_INVALID", f"{name} must be a lowercase SHA-256 digest")
    return value


def _state(composed: ComposedRuntimeState) -> ExecutionResumeState:
    value = composed.extension_state(EXTENSION_ID)
    if not isinstance(value, ExecutionResumeState):
        raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Execution Resume extension state")
    return value


def _work_graph(composed: ComposedRuntimeState) -> WorkGraphState:
    value = composed.extension_state(WORK_GRAPH_EXTENSION_ID)
    if not isinstance(value, WorkGraphState):
        raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Work Graph extension state")
    return value


def _require_active_runtime(composed: ComposedRuntimeState, command: CommandEnvelope) -> None:
    mission = composed.core_state.mission
    if mission is None:
        raise RuntimeError("MISSION_NOT_FOUND", f"Mission not found: {command.mission_id}")
    if mission.status != MissionStatus.ACTIVE:
        raise RuntimeError("INVALID_STATE_TRANSITION", "Execution Attempt requires ACTIVE Mission")
    if not command.session_id:
        raise RuntimeError("EXECUTION_SESSION_NOT_OPEN", "Execution Attempt requires an OPEN Session")
    session = composed.core_state.session(command.session_id)
    if session is None or session.mission_id != command.mission_id or session.status != SessionStatus.OPEN:
        raise RuntimeError("EXECUTION_SESSION_NOT_OPEN", f"Session is not OPEN: {command.session_id}")


def _require_task(composed: ComposedRuntimeState, command: CommandEnvelope) -> tuple[WorkGraphState, Any]:
    work_graph = _work_graph(composed)
    plan_id = _text(command.payload.get("plan_id"), "payload.plan_id")
    revision_id = _text(command.payload.get("plan_revision_id"), "payload.plan_revision_id")
    task_id = _text(command.payload.get("task_id"), "payload.task_id")
    plan = work_graph.plan(plan_id)
    if plan is None:
        raise RuntimeError("PLAN_NOT_FOUND", f"Plan not found: {plan_id}")
    if plan.lifecycle_state != PlanLifecycleState.OPEN:
        raise RuntimeError("PLAN_NOT_OPEN", f"Plan is not OPEN: {plan_id}")
    if plan.current_revision_id != revision_id:
        raise RuntimeError("TASK_REVISION_NOT_CURRENT", "Task must belong to the current Plan Revision")
    task = work_graph.task(task_id)
    if task is None:
        raise RuntimeError("TASK_NOT_FOUND", f"Task not found: {task_id}")
    if task.plan_id != plan_id or task.plan_revision_id != revision_id:
        raise RuntimeError("REVISION_PLAN_MISMATCH", "Task identity does not match Plan Revision")
    if task.lifecycle_state != TaskLifecycleState.ACTIVE:
        raise RuntimeError("EXECUTION_TASK_NOT_ACTIVE", f"Task is not ACTIVE: {task_id}")
    return work_graph, task


def _context_anchor(command: CommandEnvelope) -> dict[str, Any]:
    required = {
        "attempt_id",
        "plan_id",
        "plan_revision_id",
        "task_id",
        "context_cursor",
        "context_semantic_digest",
        "context_schema_version",
        "context_builder_version",
        "context_canonicalization_version",
        "policy_id",
        "policy_version",
        "knowledge_set_digest",
    }
    allowed = required | ({"resume_from_attempt_id"} if command.type == "RESUME_EXECUTION_ATTEMPT" else set())
    if set(command.payload) != allowed:
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "Execution Attempt payload contains unknown or missing fields")
    attempt_id = _text(command.payload.get("attempt_id"), "payload.attempt_id")
    cursor_raw = command.payload.get("context_cursor")
    if not isinstance(cursor_raw, Mapping):
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "payload.context_cursor must be an object")
    cursor = EventCursor.from_dict(cursor_raw)
    if cursor.mission_id != command.mission_id or cursor.through_seq != command.expected_seq:
        raise RuntimeError("EXECUTION_CONTEXT_ANCHOR_MISMATCH", "Context cursor must equal command expected_seq")
    if cursor.stream_schema_version != 1:
        raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "unsupported Context cursor schema")
    anchor = {
        "attempt_id": attempt_id,
        "plan_id": _text(command.payload.get("plan_id"), "payload.plan_id"),
        "plan_revision_id": _text(command.payload.get("plan_revision_id"), "payload.plan_revision_id"),
        "task_id": _text(command.payload.get("task_id"), "payload.task_id"),
        "context_cursor": cursor.to_dict(),
        "context_semantic_digest": _digest(command.payload.get("context_semantic_digest"), "payload.context_semantic_digest"),
        "context_schema_version": command.payload.get("context_schema_version"),
        "context_builder_version": command.payload.get("context_builder_version"),
        "context_canonicalization_version": command.payload.get("context_canonicalization_version"),
        "policy_id": _text(command.payload.get("policy_id"), "payload.policy_id"),
        "policy_version": command.payload.get("policy_version"),
        "knowledge_set_digest": _digest(command.payload.get("knowledge_set_digest"), "payload.knowledge_set_digest"),
    }
    for name in (
        "context_schema_version",
        "context_builder_version",
        "context_canonicalization_version",
        "policy_version",
    ):
        if not isinstance(anchor[name], int) or isinstance(anchor[name], bool) or anchor[name] != 1:
            raise RuntimeError("EXECUTION_CONTEXT_SCHEMA_MISMATCH", f"unsupported {name}")
    if command.type == "RESUME_EXECUTION_ATTEMPT":
        anchor["resume_from_attempt_id"] = _text(
            command.payload.get("resume_from_attempt_id"),
            "payload.resume_from_attempt_id",
        )
    return anchor


def _handle(command: CommandEnvelope, composed: ComposedRuntimeState) -> list[PendingEvent]:
    if command.type not in COMMAND_TYPES:
        raise RuntimeError("EXTENSION_COMMAND_NOT_OWNED", f"unsupported Execution Resume command: {command.type}")
    _require_active_runtime(composed, command)
    work_graph, task = _require_task(composed, command)
    state = _state(composed)
    anchor = _context_anchor(command)
    attempt_id = anchor["attempt_id"]
    if state.attempt(attempt_id) is not None:
        raise RuntimeError("EXECUTION_ATTEMPT_ID_CONFLICT", f"Attempt ID already used: {attempt_id}")

    if command.type == "START_EXECUTION_ATTEMPT":
        if state.attempts_for_task(task.task_id):
            raise RuntimeError("EXECUTION_ATTEMPT_ALREADY_EXISTS", f"Task already has an Attempt: {task.task_id}")
        attempt_kind = "START"
        predecessor = None
        root = attempt_id
        ordinal = 1
        event_type = "execution.attempt_started.v1"
    else:
        predecessor_id = anchor["resume_from_attempt_id"]
        predecessor = state.attempt(predecessor_id)
        if predecessor is None:
            raise RuntimeError("EXECUTION_ATTEMPT_NOT_FOUND", f"Attempt not found: {predecessor_id}")
        if (
            predecessor.mission_id != command.mission_id
            or predecessor.plan_id != work_graph.task(task.task_id).plan_id
            or predecessor.plan_revision_id != task.plan_revision_id
            or predecessor.task_id != task.task_id
        ):
            raise RuntimeError("EXECUTION_LINEAGE_MISMATCH", "Resume source does not belong to the target Task")
        latest = state.latest_attempt(task.task_id)
        if latest is None or latest.attempt_id != predecessor_id:
            raise RuntimeError("EXECUTION_RESUME_SOURCE_NOT_LATEST", "Resume source must be the latest Task Attempt")
        attempt_kind = "RESUME"
        root = predecessor.root_attempt_id
        ordinal = predecessor.ordinal + 1
        event_type = "execution.attempt_resumed.v1"

    event_payload = {
        **anchor,
        "mission_id": command.mission_id,
        "attempt_kind": attempt_kind,
        "predecessor_attempt_id": predecessor.attempt_id if predecessor is not None else None,
        "root_attempt_id": root,
        "ordinal": ordinal,
    }
    return [
        PendingEvent(
            event_type,
            "EXECUTION_ATTEMPT",
            attempt_id,
            event_payload,
            session_id=command.session_id,
        )
    ]


class ExecutionResumeCommandContribution:
    def handle(self, command: CommandEnvelope, composed: ComposedRuntimeState) -> list[PendingEvent]:
        return _handle(command, composed)
