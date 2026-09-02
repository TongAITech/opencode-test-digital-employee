from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import EventEnvelope, MissionStatus, RuntimeError, RuntimeState
from aitest_runtime.execution_context import EventCursor

from .contracts import ExecutionAttemptRecord, ExecutionResumeState
from .handlers import EVENT_TYPES


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", f"{name} must be a non-empty string")
    return value


def _digest(value: Any, name: str) -> str:
    value = _text(value, name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", f"{name} must be a lowercase SHA-256 digest")
    return value


def _require_event_payload(event: EventEnvelope) -> Mapping[str, Any]:
    if event.event_type not in EVENT_TYPES:
        raise RuntimeError("EXTENSION_EVENT_NOT_OWNED", f"unsupported Execution Resume event: {event.event_type}")
    if event.entity_type != "EXECUTION_ATTEMPT":
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Execution Resume event entity_type is invalid")
    if event.session_id is None:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Execution Attempt Event requires a Session")
    payload = dict(event.payload)
    required = {
        "attempt_id",
        "mission_id",
        "plan_id",
        "plan_revision_id",
        "task_id",
        "attempt_kind",
        "predecessor_attempt_id",
        "root_attempt_id",
        "ordinal",
        "context_cursor",
        "context_semantic_digest",
        "context_schema_version",
        "context_builder_version",
        "context_canonicalization_version",
        "policy_id",
        "policy_version",
        "knowledge_set_digest",
    }
    allowed = required | ({"resume_from_attempt_id"} if event.event_type.endswith("resumed.v1") else set())
    if set(payload) != allowed:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Execution Attempt Event payload contains unknown or missing fields")
    if payload["attempt_id"] != event.entity_id or payload["mission_id"] != event.mission_id:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Execution Attempt Event identity mismatch")
    if payload["attempt_kind"] != ("START" if event.event_type.endswith("started.v1") else "RESUME"):
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Execution Attempt Event kind mismatch")
    cursor = EventCursor.from_dict(payload["context_cursor"])
    if cursor.mission_id != event.mission_id or cursor.through_seq != event.seq - 1:
        raise RuntimeError("EXECUTION_CONTEXT_ANCHOR_MISMATCH", "Attempt Event does not follow its Context cursor")
    if cursor.stream_schema_version != 1:
        raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "unsupported Context cursor schema")
    for name in (
        "context_schema_version",
        "context_builder_version",
        "context_canonicalization_version",
        "policy_version",
    ):
        if payload[name] != 1 or isinstance(payload[name], bool):
            raise RuntimeError("EXECUTION_CONTEXT_SCHEMA_MISMATCH", f"unsupported {name}")
    _digest(payload["context_semantic_digest"], "context_semantic_digest")
    _digest(payload["knowledge_set_digest"], "knowledge_set_digest")
    _text(payload["policy_id"], "policy_id")
    _text(payload["runtime_session_id"] if "runtime_session_id" in payload else event.session_id, "runtime_session_id")
    return payload


class ExecutionResumeReducerContribution:
    def reduce(
        self,
        state: ExecutionResumeState,
        event: EventEnvelope,
        core_state: RuntimeState,
    ) -> ExecutionResumeState:
        if not isinstance(state, ExecutionResumeState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Execution Resume state")
        if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Execution Resume Mission identity mismatch")
        if core_state.seq != event.seq:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Execution Resume Event does not share Core seq")
        if core_state.mission is None or core_state.mission.status in {
            MissionStatus.COMPLETED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        }:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "terminal or missing Mission cannot accept Attempt facts")
        payload = _require_event_payload(event)
        attempt_id = str(payload["attempt_id"])
        if state.attempt(attempt_id) is not None:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Attempt identity is already used")
        predecessor_id = payload["predecessor_attempt_id"]
        predecessor = state.attempt(predecessor_id) if predecessor_id is not None else None
        kind = str(payload["attempt_kind"])
        if kind == "START":
            if predecessor is not None or payload["root_attempt_id"] != attempt_id or payload["ordinal"] != 1:
                raise RuntimeError("EXECUTION_LINEAGE_MISMATCH", "invalid START lineage")
            if state.attempts_for_task(str(payload["task_id"])):
                raise RuntimeError("EXECUTION_ATTEMPT_ALREADY_EXISTS", "Task already has an Attempt")
        else:
            if payload.get("resume_from_attempt_id") != predecessor_id:
                raise RuntimeError("EXECUTION_LINEAGE_MISMATCH", "Resume source anchor mismatch")
            if predecessor is None:
                raise RuntimeError("EXECUTION_ATTEMPT_NOT_FOUND", "Resume source Attempt not found")
            latest = state.latest_attempt(str(payload["task_id"]))
            if latest is None or latest.attempt_id != predecessor.attempt_id:
                raise RuntimeError("EXECUTION_RESUME_SOURCE_NOT_LATEST", "Resume source must be latest")
            if payload["root_attempt_id"] != predecessor.root_attempt_id:
                raise RuntimeError("EXECUTION_LINEAGE_MISMATCH", "Resume root Attempt mismatch")
            if payload["ordinal"] != predecessor.ordinal + 1:
                raise RuntimeError("EXECUTION_LINEAGE_MISMATCH", "Resume ordinal is not contiguous")
            if predecessor.plan_id != payload["plan_id"] or predecessor.plan_revision_id != payload["plan_revision_id"]:
                raise RuntimeError("EXECUTION_LINEAGE_MISMATCH", "Resume Plan lineage mismatch")
            if predecessor.task_id != payload["task_id"]:
                raise RuntimeError("EXECUTION_LINEAGE_MISMATCH", "Resume Task lineage mismatch")
        record = ExecutionAttemptRecord(
            attempt_id=attempt_id,
            mission_id=event.mission_id,
            runtime_session_id=event.session_id or "",
            plan_id=_text(payload["plan_id"], "plan_id"),
            plan_revision_id=_text(payload["plan_revision_id"], "plan_revision_id"),
            task_id=_text(payload["task_id"], "task_id"),
            attempt_kind=kind,
            predecessor_attempt_id=predecessor_id,
            root_attempt_id=_text(payload["root_attempt_id"], "root_attempt_id"),
            ordinal=payload["ordinal"],
            context_cursor=EventCursor.from_dict(payload["context_cursor"]),
            context_semantic_digest=payload["context_semantic_digest"],
            context_schema_version=payload["context_schema_version"],
            context_builder_version=payload["context_builder_version"],
            context_canonicalization_version=payload["context_canonicalization_version"],
            policy_id=payload["policy_id"],
            policy_version=payload["policy_version"],
            knowledge_set_digest=payload["knowledge_set_digest"],
            command_id=event.command_id,
            created_seq=event.seq,
            created_at=event.created_at,
            created_by={"type": event.initiator_type, "id": event.initiator_id},
        )
        return replace(state, attempts=state.attempts + (record,))
