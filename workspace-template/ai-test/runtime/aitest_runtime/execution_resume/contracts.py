from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from aitest_runtime.durable_core import (
    ActorRef,
    CommandResult,
    ComposedRuntimeState,
    RuntimeError,
    RuntimeService,
)
from aitest_runtime.execution_context import (
    BuildExecutionContextRequest,
    EventCursor,
    ExecutionContext,
    KnowledgeSetInput,
)


EXTENSION_ID = "r1_3b_execution_resume"
EXTENSION_VERSION = "1"
EXECUTION_RESUME_SCHEMA_VERSION = 1
PROJECTION_VERSION = 1
CANONICALIZATION_VERSION = 1

ExecutionAttemptKind = Literal["START", "RESUME"]


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _non_negative(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", f"{name} must be a non-negative integer")
    return value


def _positive(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", f"{name} must be a positive integer")
    return value


def _digest(value: Any, name: str) -> str:
    value = _text(value, name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", f"{name} must be a lowercase SHA-256 digest")
    return value


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


@dataclass(frozen=True)
class ExecutionAttemptRecord:
    attempt_id: str
    mission_id: str
    runtime_session_id: str
    plan_id: str
    plan_revision_id: str
    task_id: str
    attempt_kind: ExecutionAttemptKind
    predecessor_attempt_id: str | None
    root_attempt_id: str
    ordinal: int
    context_cursor: EventCursor
    context_semantic_digest: str
    context_schema_version: int
    context_builder_version: int
    context_canonicalization_version: int
    policy_id: str
    policy_version: int
    knowledge_set_digest: str
    command_id: str
    created_seq: int
    created_at: str
    created_by: Mapping[str, str]

    def __post_init__(self) -> None:
        for name in (
            "attempt_id",
            "mission_id",
            "runtime_session_id",
            "plan_id",
            "plan_revision_id",
            "task_id",
            "root_attempt_id",
            "policy_id",
            "command_id",
            "created_at",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.attempt_kind not in {"START", "RESUME"}:
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "unsupported attempt_kind")
        predecessor = _optional_text(self.predecessor_attempt_id, "predecessor_attempt_id")
        if self.attempt_kind == "START" and predecessor is not None:
            raise RuntimeError("EXECUTION_LINEAGE_MISMATCH", "START cannot have a predecessor")
        if self.attempt_kind == "RESUME" and predecessor is None:
            raise RuntimeError("EXECUTION_LINEAGE_MISMATCH", "RESUME requires a predecessor")
        object.__setattr__(self, "predecessor_attempt_id", predecessor)
        object.__setattr__(self, "ordinal", _positive(self.ordinal, "ordinal"))
        if self.attempt_kind == "START" and (self.root_attempt_id != self.attempt_id or self.ordinal != 1):
            raise RuntimeError("EXECUTION_LINEAGE_MISMATCH", "invalid START lineage")
        if not isinstance(self.context_cursor, EventCursor):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "context_cursor must be an EventCursor")
        if self.context_cursor.mission_id != self.mission_id:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "context cursor Mission mismatch")
        if self.context_cursor.stream_schema_version != 1:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "unsupported context cursor schema")
        if self.context_cursor.through_seq != self.created_seq - 1:
            raise RuntimeError("EXECUTION_CONTEXT_ANCHOR_MISMATCH", "Attempt Event is not after its Context cursor")
        object.__setattr__(self, "context_semantic_digest", _digest(self.context_semantic_digest, "context_semantic_digest"))
        object.__setattr__(self, "knowledge_set_digest", _digest(self.knowledge_set_digest, "knowledge_set_digest"))
        for name in (
            "context_schema_version",
            "context_builder_version",
            "context_canonicalization_version",
        ):
            value = _positive(getattr(self, name), name)
            if value != 1:
                raise RuntimeError("EXECUTION_CONTEXT_SCHEMA_MISMATCH", f"unsupported {name}")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "policy_version", _positive(self.policy_version, "policy_version"))
        object.__setattr__(self, "created_seq", _positive(self.created_seq, "created_seq"))
        created_by = _mapping(self.created_by, "created_by")
        if not _text(created_by.get("type"), "created_by.type") or not _text(created_by.get("id"), "created_by.id"):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "created_by requires type and id")
        object.__setattr__(self, "created_by", {"type": created_by["type"], "id": created_by["id"]})

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "mission_id": self.mission_id,
            "runtime_session_id": self.runtime_session_id,
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "task_id": self.task_id,
            "attempt_kind": self.attempt_kind,
            "predecessor_attempt_id": self.predecessor_attempt_id,
            "root_attempt_id": self.root_attempt_id,
            "ordinal": self.ordinal,
            "context_cursor": self.context_cursor.to_dict(),
            "context_semantic_digest": self.context_semantic_digest,
            "context_schema_version": self.context_schema_version,
            "context_builder_version": self.context_builder_version,
            "context_canonicalization_version": self.context_canonicalization_version,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "knowledge_set_digest": self.knowledge_set_digest,
            "command_id": self.command_id,
            "created_seq": self.created_seq,
            "created_at": self.created_at,
            "created_by": dict(self.created_by),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionAttemptRecord":
        if not isinstance(value, Mapping):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "Attempt record must be an object")
        required = {
            "attempt_id", "mission_id", "runtime_session_id", "plan_id", "plan_revision_id", "task_id",
            "attempt_kind", "predecessor_attempt_id", "root_attempt_id", "ordinal", "context_cursor",
            "context_semantic_digest", "context_schema_version", "context_builder_version",
            "context_canonicalization_version", "policy_id", "policy_version", "knowledge_set_digest",
            "command_id", "created_seq", "created_at", "created_by",
        }
        if set(value) != required:
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "Attempt record contains unknown or missing fields")
        return cls(
            attempt_id=value["attempt_id"],
            mission_id=value["mission_id"],
            runtime_session_id=value["runtime_session_id"],
            plan_id=value["plan_id"],
            plan_revision_id=value["plan_revision_id"],
            task_id=value["task_id"],
            attempt_kind=value["attempt_kind"],
            predecessor_attempt_id=value["predecessor_attempt_id"],
            root_attempt_id=value["root_attempt_id"],
            ordinal=value["ordinal"],
            context_cursor=EventCursor.from_dict(value["context_cursor"]),
            context_semantic_digest=value["context_semantic_digest"],
            context_schema_version=value["context_schema_version"],
            context_builder_version=value["context_builder_version"],
            context_canonicalization_version=value["context_canonicalization_version"],
            policy_id=value["policy_id"],
            policy_version=value["policy_version"],
            knowledge_set_digest=value["knowledge_set_digest"],
            command_id=value["command_id"],
            created_seq=value["created_seq"],
            created_at=value["created_at"],
            created_by=value["created_by"],
        )


@dataclass(frozen=True)
class ExecutionResumeState:
    mission_id: str
    attempts: tuple[ExecutionAttemptRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        if not isinstance(self.attempts, tuple) or any(not isinstance(item, ExecutionAttemptRecord) for item in self.attempts):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "attempts must be an immutable tuple")
        ids = [item.attempt_id for item in self.attempts]
        if len(ids) != len(set(ids)):
            raise RuntimeError("EXECUTION_ATTEMPT_ID_CONFLICT", "Attempt IDs must be unique")
        if any(item.mission_id != self.mission_id for item in self.attempts):
            raise RuntimeError("EXECUTION_LINEAGE_MISMATCH", "Attempt Mission mismatch")
        if tuple(item.created_seq for item in self.attempts) != tuple(sorted(item.created_seq for item in self.attempts)):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "attempts must be ordered by created_seq")

    def attempt(self, attempt_id: str) -> ExecutionAttemptRecord | None:
        return next((item for item in self.attempts if item.attempt_id == attempt_id), None)

    def attempts_for_task(self, task_id: str) -> tuple[ExecutionAttemptRecord, ...]:
        return tuple(item for item in self.attempts if item.task_id == task_id)

    def latest_attempt(self, task_id: str) -> ExecutionAttemptRecord | None:
        values = self.attempts_for_task(task_id)
        return values[-1] if values else None

    def superseded_by(self, attempt_id: str) -> str | None:
        values = [item for item in self.attempts if item.predecessor_attempt_id == attempt_id]
        if not values:
            return None
        return values[-1].attempt_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "attempts": [item.to_dict() for item in self.attempts],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionResumeState":
        if not isinstance(value, Mapping) or set(value) != {"mission_id", "attempts"}:
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "Execution Resume state contains unknown or missing fields")
        attempts = value["attempts"]
        if not isinstance(attempts, list):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "attempts must be an array")
        return cls(
            mission_id=value["mission_id"],
            attempts=tuple(ExecutionAttemptRecord.from_dict(item) for item in attempts),
        )


@dataclass(frozen=True)
class RehydrateRuntimeRequest:
    mission_id: str
    cursor: EventCursor

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        if not isinstance(self.cursor, EventCursor) or self.cursor.mission_id != self.mission_id:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "cursor must be bound to mission_id")
        if self.cursor.stream_schema_version != 1:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "unsupported stream schema version")


@dataclass(frozen=True)
class RehydratedRuntime:
    mission_id: str
    cursor: EventCursor
    composed_state: ComposedRuntimeState
    execution_state: ExecutionResumeState
    state_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        if not isinstance(self.cursor, EventCursor) or self.cursor.mission_id != self.mission_id:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "rehydrated cursor mismatch")
        if not isinstance(self.composed_state, ComposedRuntimeState):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "composed_state has an invalid type")
        if self.composed_state.mission_id != self.mission_id or self.composed_state.seq != self.cursor.through_seq:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "rehydrated state does not match cursor")
        if not isinstance(self.execution_state, ExecutionResumeState) or self.execution_state.mission_id != self.mission_id:
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "execution_state has an invalid type")
        object.__setattr__(self, "state_digest", _digest(self.state_digest, "state_digest"))


@dataclass(frozen=True)
class ExecutionRequest:
    command_id: str
    idempotency_key: str | None
    mission_id: str
    runtime_session_id: str
    expected_seq: int
    actor: ActorRef
    correlation_id: str | None
    execution_attempt_id: str
    plan_id: str
    plan_revision_id: str
    task_id: str
    knowledge_set: KnowledgeSetInput
    policy_id: str
    policy_version: int
    knowledge_scope: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in (
            "command_id", "mission_id", "runtime_session_id", "execution_attempt_id",
            "plan_id", "plan_revision_id", "task_id", "policy_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "idempotency_key", _optional_text(self.idempotency_key, "idempotency_key"))
        object.__setattr__(self, "correlation_id", _optional_text(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "expected_seq", _non_negative(self.expected_seq, "expected_seq"))
        object.__setattr__(self, "policy_version", _positive(self.policy_version, "policy_version"))
        if not isinstance(self.actor, ActorRef):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "actor must be an ActorRef")
        if not isinstance(self.knowledge_set, KnowledgeSetInput):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "knowledge_set must be a KnowledgeSetInput")
        object.__setattr__(self, "knowledge_scope", _mapping(self.knowledge_scope, "knowledge_scope"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "idempotency_key": self.idempotency_key,
            "mission_id": self.mission_id,
            "runtime_session_id": self.runtime_session_id,
            "expected_seq": self.expected_seq,
            "actor": self.actor.to_dict(),
            "correlation_id": self.correlation_id,
            "execution_attempt_id": self.execution_attempt_id,
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "task_id": self.task_id,
            "knowledge_set": self.knowledge_set.to_dict(),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "knowledge_scope": dict(self.knowledge_scope),
        }


@dataclass(frozen=True)
class StartExecutionRequest(ExecutionRequest):
    pass


@dataclass(frozen=True)
class ResumeExecutionRequest(ExecutionRequest):
    resume_from_attempt_id: str

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "resume_from_attempt_id", _text(self.resume_from_attempt_id, "resume_from_attempt_id"))


@dataclass(frozen=True)
class LogicalExecutionResult:
    outcome: Literal["APPLIED", "DUPLICATE"]
    command_result: CommandResult
    attempt: ExecutionAttemptRecord
    context: ExecutionContext
    event_cursor: EventCursor

    def __post_init__(self) -> None:
        if self.outcome not in {"APPLIED", "DUPLICATE"}:
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "invalid logical execution outcome")
        if not isinstance(self.command_result, CommandResult):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "command_result has an invalid type")
        if not isinstance(self.attempt, ExecutionAttemptRecord):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "attempt has an invalid type")
        if not isinstance(self.context, ExecutionContext):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "context has an invalid type")
        if not isinstance(self.event_cursor, EventCursor):
            raise RuntimeError("EXECUTION_RESUME_SCHEMA_INVALID", "event_cursor has an invalid type")


# Keep the R1.3A import visible to type-checkers and downstream callers that
# use the execution-resume package as the orchestration boundary.
__all__ = [
    "BuildExecutionContextRequest",
    "CANONICALIZATION_VERSION",
    "EXECUTION_RESUME_SCHEMA_VERSION",
    "EXTENSION_ID",
    "EXTENSION_VERSION",
    "ExecutionAttemptKind",
    "ExecutionAttemptRecord",
    "ExecutionRequest",
    "ExecutionResumeState",
    "LogicalExecutionResult",
    "PROJECTION_VERSION",
    "RehydrateRuntimeRequest",
    "RehydratedRuntime",
    "ResumeExecutionRequest",
    "StartExecutionRequest",
]
