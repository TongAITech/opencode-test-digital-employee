from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping

from aitest_runtime.durable_core import CommandResult, RuntimeError
from aitest_runtime.execution_context import EventCursor


EXTENSION_ID = "r2_5_session_orchestration"
EXTENSION_VERSION = "1"
R25_SCHEMA_VERSION = 1
PROJECTION_VERSION = 1
CANONICALIZATION_VERSION = 1
SESSION_CONTEXT_SCHEMA_VERSION = 1

BIND_LOGICAL_AGENT = "R25_BIND_LOGICAL_AGENT"
REGISTER_DELEGATION = "R25_REGISTER_DELEGATION"
RECORD_CHILD_RESULT = "R25_RECORD_CHILD_RESULT"
JOIN_CHILD_RESULT = "R25_JOIN_CHILD_RESULT"

LOGICAL_AGENT_BOUND = "r2_5.logical_agent_bound.v1"
DELEGATION_REGISTERED = "r2_5.delegation_registered.v1"
CHILD_RESULT_RECORDED = "r2_5.child_result_recorded.v1"
JOINED = "r2_5.child_result_joined.v1"

SUSPEND = "SUSPEND"
CLOSE = "CLOSE"
PREDECESSOR_ALREADY_TERMINAL = "PREDECESSOR_ALREADY_TERMINAL"
ROTATION_SUSPEND = SUSPEND
SUSPEND_PREDECESSOR = "SUSPEND_PREDECESSOR"
CLOSE_PREDECESSOR = "CLOSE_PREDECESSOR"
OPEN_SUCCESSOR = "OPEN_SUCCESSOR"

ACTIVE = "ACTIVE"
TASK_TRUTH_CONFLICT = "TASK_TRUTH_CONFLICT"


class R25Error(RuntimeError):
    """R2.5 error type kept as a named alias for callers."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R25Error("R2_5_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _non_negative(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise R25Error("R2_5_SCHEMA_INVALID", f"{name} must be a non-negative integer")
    return value


def _positive(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise R25Error("R2_5_SCHEMA_INVALID", f"{name} must be a positive integer")
    return value


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R25Error("R2_5_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def command_id_for(operation_id: str, operation: str) -> str:
    operation_id = _text(operation_id, "operation_id")
    operation = _text(operation, "operation")
    return f"r2.5:{operation_id}:{operation}"


def default_idempotency_key(command_id: str) -> str:
    return _text(command_id, "command_id")


def _created_by(value: Mapping[str, Any]) -> dict[str, str]:
    raw = _mapping(value, "created_by")
    return {"type": _text(raw.get("type"), "created_by.type"), "id": _text(raw.get("id"), "created_by.id")}


@dataclass(frozen=True)
class LogicalAgentBinding:
    binding_id: str
    mission_id: str
    logical_agent_id: str
    root_attempt_id: str
    attempt_id: str
    task_id: str
    session_id: str
    created_seq: int
    created_at: str
    created_by: Mapping[str, str]

    def __post_init__(self) -> None:
        for name in (
            "binding_id", "mission_id", "logical_agent_id", "root_attempt_id", "attempt_id",
            "task_id", "session_id", "created_at",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "created_seq", _positive(self.created_seq, "created_seq"))
        object.__setattr__(self, "created_by", _created_by(self.created_by))

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "mission_id": self.mission_id,
            "logical_agent_id": self.logical_agent_id,
            "root_attempt_id": self.root_attempt_id,
            "attempt_id": self.attempt_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "created_seq": self.created_seq,
            "created_at": self.created_at,
            "created_by": dict(self.created_by),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LogicalAgentBinding":
        return cls(
            binding_id=value["binding_id"], mission_id=value["mission_id"],
            logical_agent_id=value["logical_agent_id"], root_attempt_id=value["root_attempt_id"],
            attempt_id=value["attempt_id"], task_id=value["task_id"], session_id=value["session_id"],
            created_seq=value["created_seq"], created_at=value["created_at"], created_by=value["created_by"],
        )


BindingRecord = LogicalAgentBinding


@dataclass(frozen=True)
class DelegationRecord:
    delegation_id: str
    mission_id: str
    parent_root_attempt_id: str
    parent_attempt_id: str
    parent_task_id: str
    child_task_id: str
    logical_agent_id: str | None
    delegation_version: int
    max_total_children_per_parent: int | None
    max_active_children_per_parent: int | None
    created_seq: int
    created_at: str
    created_by: Mapping[str, str]
    child_root_attempt_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "delegation_id", "mission_id", "parent_root_attempt_id", "parent_attempt_id",
            "parent_task_id", "child_task_id", "created_at",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "logical_agent_id", _optional_text(self.logical_agent_id, "logical_agent_id"))
        object.__setattr__(self, "child_root_attempt_id", _optional_text(self.child_root_attempt_id, "child_root_attempt_id"))
        object.__setattr__(self, "delegation_version", _positive(self.delegation_version, "delegation_version"))
        for name in ("max_total_children_per_parent", "max_active_children_per_parent"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _positive(value, name))
        object.__setattr__(self, "created_seq", _positive(self.created_seq, "created_seq"))
        object.__setattr__(self, "created_by", _created_by(self.created_by))

    def to_dict(self) -> dict[str, Any]:
        return {
            "delegation_id": self.delegation_id,
            "mission_id": self.mission_id,
            "parent_root_attempt_id": self.parent_root_attempt_id,
            "parent_attempt_id": self.parent_attempt_id,
            "parent_task_id": self.parent_task_id,
            "child_task_id": self.child_task_id,
            "child_root_attempt_id": self.child_root_attempt_id,
            "logical_agent_id": self.logical_agent_id,
            "delegation_version": self.delegation_version,
            "max_total_children_per_parent": self.max_total_children_per_parent,
            "max_active_children_per_parent": self.max_active_children_per_parent,
            "created_seq": self.created_seq,
            "created_at": self.created_at,
            "created_by": dict(self.created_by),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DelegationRecord":
        return cls(
            delegation_id=value["delegation_id"], mission_id=value["mission_id"],
            parent_root_attempt_id=value["parent_root_attempt_id"], parent_attempt_id=value["parent_attempt_id"],
            parent_task_id=value["parent_task_id"], child_task_id=value["child_task_id"],
            child_root_attempt_id=value.get("child_root_attempt_id"), logical_agent_id=value.get("logical_agent_id"),
            delegation_version=value["delegation_version"],
            max_total_children_per_parent=value.get("max_total_children_per_parent"),
            max_active_children_per_parent=value.get("max_active_children_per_parent"),
            created_seq=value["created_seq"], created_at=value["created_at"], created_by=value["created_by"],
        )


@dataclass(frozen=True)
class ChildResultRecord:
    child_result_id: str
    mission_id: str
    delegation_id: str
    parent_root_attempt_id: str
    child_task_id: str
    child_attempt_id: str
    child_root_attempt_id: str
    plan_revision_id: str
    terminal_state: str
    result_ref: Mapping[str, Any]
    result_digest: str | None
    canonical_source_seq: int
    outcome: Mapping[str, Any] | None
    recorded_seq: int
    recorded_at: str
    recorded_by: Mapping[str, str]

    def __post_init__(self) -> None:
        for name in (
            "child_result_id", "mission_id", "delegation_id", "parent_root_attempt_id", "child_task_id",
            "child_attempt_id", "child_root_attempt_id", "plan_revision_id", "terminal_state", "recorded_at",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "result_ref", _freeze_json(_mapping(self.result_ref, "result_ref")))
        digest = self.result_digest
        if digest is not None:
            if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise R25Error("R2_5_SCHEMA_INVALID", "result_digest must be a lowercase SHA-256 digest")
        object.__setattr__(self, "result_digest", digest)
        object.__setattr__(self, "canonical_source_seq", _positive(self.canonical_source_seq, "canonical_source_seq"))
        if self.outcome is not None:
            object.__setattr__(self, "outcome", _freeze_json(_mapping(self.outcome, "outcome")))
        object.__setattr__(self, "recorded_seq", _positive(self.recorded_seq, "recorded_seq"))
        object.__setattr__(self, "recorded_by", _created_by(self.recorded_by))

    @property
    def result_payload(self) -> Mapping[str, Any]:
        """Compatibility view of the bounded reference, never execution truth."""
        return self.result_ref

    def to_dict(self) -> dict[str, Any]:
        return {
            "child_result_id": self.child_result_id,
            "mission_id": self.mission_id,
            "delegation_id": self.delegation_id,
            "parent_root_attempt_id": self.parent_root_attempt_id,
            "child_task_id": self.child_task_id,
            "child_attempt_id": self.child_attempt_id,
            "child_root_attempt_id": self.child_root_attempt_id,
            "plan_revision_id": self.plan_revision_id,
            "terminal_state": self.terminal_state,
            "result_ref": dict(self.result_ref),
            "result_digest": self.result_digest,
            "canonical_source_seq": self.canonical_source_seq,
            "outcome": dict(self.outcome) if self.outcome is not None else None,
            "recorded_seq": self.recorded_seq,
            "recorded_at": self.recorded_at,
            "recorded_by": dict(self.recorded_by),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ChildResultRecord":
        return cls(
            child_result_id=value["child_result_id"], mission_id=value["mission_id"],
            delegation_id=value["delegation_id"], parent_root_attempt_id=value["parent_root_attempt_id"],
            child_task_id=value["child_task_id"], child_attempt_id=value["child_attempt_id"],
            child_root_attempt_id=value["child_root_attempt_id"], plan_revision_id=value["plan_revision_id"],
            terminal_state=value["terminal_state"], result_ref=value["result_ref"],
            result_digest=value.get("result_digest"), canonical_source_seq=value["canonical_source_seq"],
            outcome=value.get("outcome"), recorded_seq=value["recorded_seq"], recorded_at=value["recorded_at"],
            recorded_by=value["recorded_by"],
        )


@dataclass(frozen=True)
class JoinRecord:
    join_id: str
    mission_id: str
    parent_root_attempt_id: str
    delegation_id: str
    child_result_id: str
    join_version: int
    joined_seq: int
    joined_at: str
    joined_by: Mapping[str, str]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "join_id", "mission_id", "parent_root_attempt_id", "delegation_id", "child_result_id", "joined_at",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "join_version", _positive(self.join_version, "join_version"))
        object.__setattr__(self, "joined_seq", _positive(self.joined_seq, "joined_seq"))
        object.__setattr__(self, "joined_by", _created_by(self.joined_by))
        object.__setattr__(self, "metadata", _freeze_json(_mapping(self.metadata, "metadata")))

    def to_dict(self) -> dict[str, Any]:
        return {
            "join_id": self.join_id,
            "mission_id": self.mission_id,
            "parent_root_attempt_id": self.parent_root_attempt_id,
            "delegation_id": self.delegation_id,
            "child_result_id": self.child_result_id,
            "join_version": self.join_version,
            "joined_seq": self.joined_seq,
            "joined_at": self.joined_at,
            "joined_by": dict(self.joined_by),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JoinRecord":
        return cls(
            join_id=value["join_id"], mission_id=value["mission_id"],
            parent_root_attempt_id=value["parent_root_attempt_id"], delegation_id=value["delegation_id"],
            child_result_id=value["child_result_id"], join_version=value["join_version"],
            joined_seq=value["joined_seq"], joined_at=value["joined_at"], joined_by=value["joined_by"],
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True)
class SessionOrchestrationState:
    mission_id: str
    bindings: tuple[LogicalAgentBinding, ...] = ()
    delegations: tuple[DelegationRecord, ...] = ()
    child_results: tuple[ChildResultRecord, ...] = ()
    joins: tuple[JoinRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        for name, cls in (
            ("bindings", LogicalAgentBinding), ("delegations", DelegationRecord),
            ("child_results", ChildResultRecord), ("joins", JoinRecord),
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, cls) for item in values):
                raise R25Error("R2_5_SCHEMA_INVALID", f"{name} must be an immutable tuple")
            ids = [item.__dict__[next(iter(item.__dict__))] for item in values]
            if len(ids) != len(set(ids)):
                raise R25Error("R2_5_IDENTITY_CONFLICT", f"{name} identities must be unique")

    def binding(self, binding_id: str) -> LogicalAgentBinding | None:
        return next((item for item in self.bindings if item.binding_id == binding_id), None)

    def delegation(self, delegation_id: str) -> DelegationRecord | None:
        return next((item for item in self.delegations if item.delegation_id == delegation_id), None)

    def child_result(self, child_result_id: str) -> ChildResultRecord | None:
        return next((item for item in self.child_results if item.child_result_id == child_result_id), None)

    def join(self, join_id: str) -> JoinRecord | None:
        return next((item for item in self.joins if item.join_id == join_id), None)

    def delegations_for_parent(self, parent_root_attempt_id: str) -> tuple[DelegationRecord, ...]:
        return tuple(item for item in self.delegations if item.parent_root_attempt_id == parent_root_attempt_id)

    def delegation_version(self, parent_root_attempt_id: str) -> int:
        return len(self.delegations_for_parent(parent_root_attempt_id))

    def joins_for_delegation(self, delegation_id: str) -> tuple[JoinRecord, ...]:
        return tuple(item for item in self.joins if item.delegation_id == delegation_id)

    def join_version(self, delegation_id: str) -> int:
        """Return the replay-derived Join CAS version for one Delegation only."""
        return len(self.joins_for_delegation(delegation_id))

    def active_child_count(self, parent_root_attempt_id: str) -> int:
        registered = self.delegations_for_parent(parent_root_attempt_id)
        accepted = {item.delegation_id for item in self.child_results}
        return sum(1 for item in registered if item.delegation_id not in accepted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "bindings": [item.to_dict() for item in sorted(self.bindings, key=lambda x: x.binding_id)],
            "delegations": [item.to_dict() for item in sorted(self.delegations, key=lambda x: x.delegation_id)],
            "child_results": [item.to_dict() for item in sorted(self.child_results, key=lambda x: x.child_result_id)],
            "joins": [item.to_dict() for item in sorted(self.joins, key=lambda x: x.join_id)],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SessionOrchestrationState":
        return cls(
            mission_id=value["mission_id"],
            bindings=tuple(LogicalAgentBinding.from_dict(item) for item in value.get("bindings") or ()),
            delegations=tuple(DelegationRecord.from_dict(item) for item in value.get("delegations") or ()),
            child_results=tuple(ChildResultRecord.from_dict(item) for item in value.get("child_results") or ()),
            joins=tuple(JoinRecord.from_dict(item) for item in value.get("joins") or ()),
        )


R25State = SessionOrchestrationState
R25SessionState = SessionOrchestrationState
LogicalAgentBindingRecord = LogicalAgentBinding
Delegation = DelegationRecord
ChildResult = ChildResultRecord
Join = JoinRecord


@dataclass(frozen=True)
class SessionContextEnvelope:
    """Non-durable context passed across a Session rotation boundary."""

    mission_id: str
    predecessor_session_id: str | None
    successor_session_id: str
    root_attempt_id: str
    attempt_id: str
    cursor: EventCursor
    context: Any = None
    schema_version: int = SESSION_CONTEXT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("mission_id", "successor_session_id", "root_attempt_id", "attempt_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "predecessor_session_id", _optional_text(self.predecessor_session_id, "predecessor_session_id"))
        if not isinstance(self.cursor, EventCursor):
            raise R25Error("R2_5_SCHEMA_INVALID", "cursor must be an EventCursor")
        if self.cursor.mission_id not in (None, self.mission_id):
            raise R25Error("R2_5_SCHEMA_INVALID", "cursor Mission mismatch")
        if self.schema_version != SESSION_CONTEXT_SCHEMA_VERSION:
            raise R25Error("R2_5_SCHEMA_INVALID", "unsupported SessionContextEnvelope schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "predecessor_session_id": self.predecessor_session_id,
            "successor_session_id": self.successor_session_id,
            "root_attempt_id": self.root_attempt_id,
            "attempt_id": self.attempt_id,
            "cursor": self.cursor.to_dict(),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class R25OperationResult:
    outcome: str
    command_result: CommandResult
    record: Any

    @property
    def last_seq(self) -> int | None:
        return self.command_result.last_seq

    @property
    def ok(self) -> bool:
        return self.command_result.ok

    @property
    def fact(self) -> Any:
        return self.record

    @property
    def binding(self) -> Any:
        return self.record

    @property
    def delegation(self) -> Any:
        return self.record

    @property
    def child_result(self) -> Any:
        return self.record

    @property
    def join(self) -> Any:
        return self.record


@dataclass(frozen=True)
class RotationResult:
    rotation_operation_id: str
    rotation_transition: str
    predecessor_session_id: str
    successor_session_id: str
    transition_result: CommandResult | None
    open_result: CommandResult
    resume_result: CommandResult
    attempt: Any
    binding: LogicalAgentBinding | None = None
    binding_result: CommandResult | None = None
    context_envelope: SessionContextEnvelope | None = None

    @property
    def command_results(self) -> tuple[CommandResult, ...]:
        values = tuple(item for item in (self.transition_result, self.open_result, self.resume_result) if item is not None)
        return values + (() if self.binding_result is None else (self.binding_result,))


# Public compatibility spelling used by some callers.
SessionOrchestrationState = SessionOrchestrationState
