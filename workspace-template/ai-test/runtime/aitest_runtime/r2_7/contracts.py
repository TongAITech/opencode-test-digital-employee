"""Frozen R2.7 Runtime Operations contracts.

R2.7 is a read-through control-plane boundary.  It owns neither durable
events nor projections; the contracts in this module describe views and
requests over the existing RuntimeService and R2.2--R2.6 boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError as DurableRuntimeError


CONTRACT_VERSION = "R2.7_RUNTIME_OPERATIONS_V1"
R2_7_CONTRACT_VERSION = CONTRACT_VERSION
SCHEMA_VERSION = 1

CURRENT = "CURRENT"
STALE = "STALE"
INCOMPLETE = "INCOMPLETE"
UNAVAILABLE = "UNAVAILABLE"
SOURCE_STATUSES = frozenset({CURRENT, STALE, INCOMPLETE, UNAVAILABLE})

CANONICAL_EVENT = "CANONICAL_EVENT"
DERIVED_EVENT = "DERIVED_EVENT"
CURRENT_OBSERVATION = "CURRENT_OBSERVATION"
HISTORICAL_KINDS = frozenset({CANONICAL_EVENT, DERIVED_EVENT})

REPORT_IS_RUNTIME_PROJECTION = "REPORT_IS_RUNTIME_PROJECTION"
CONTROL_PLANE_HTTP_INTEGRATION_GAP = "OPEN"

R2_7_ACTION_UNSUPPORTED = "R2_7_ACTION_UNSUPPORTED"
R2_7_ACTION_BOUNDARY_UNAVAILABLE = "R2_7_ACTION_BOUNDARY_UNAVAILABLE"
R2_7_ACTION_REQUEST_INVALID = "R2_7_ACTION_REQUEST_INVALID"
R2_7_AS_OF_SEQ_AHEAD_OF_HEAD = "R2_7_AS_OF_SEQ_AHEAD_OF_HEAD"
R2_7_ERROR_CODES = frozenset(
    {
        R2_7_ACTION_UNSUPPORTED,
        R2_7_ACTION_BOUNDARY_UNAVAILABLE,
        R2_7_ACTION_REQUEST_INVALID,
        R2_7_AS_OF_SEQ_AHEAD_OF_HEAD,
    }
)
R2_7_MUST_NOT_SYNTHESIZE_MUTATION_IDENTITY = True

PAUSE_MISSION = "PAUSE_MISSION"
CONTINUE_MISSION = "CONTINUE_MISSION"
CANCEL_TASK = "CANCEL_TASK"
REVISE_GOAL = "REVISE_GOAL"
REVISE_PLAN = "REVISE_PLAN"
REQUEST_SESSION_ROTATION = "REQUEST_SESSION_ROTATION"
SUBMIT_HUMAN_DECISION = "SUBMIT_HUMAN_DECISION"
RECORD_HUMAN_CONTINUATION = "RECORD_HUMAN_CONTINUATION"
RETRY_TASK = "RETRY_TASK"
FORCE_ROTATE_SESSION = "FORCE_ROTATE_SESSION"

SUPPORTED_ACTIONS = frozenset(
    {
        PAUSE_MISSION,
        CONTINUE_MISSION,
        CANCEL_TASK,
        REVISE_GOAL,
        REVISE_PLAN,
        REQUEST_SESSION_ROTATION,
        SUBMIT_HUMAN_DECISION,
        RECORD_HUMAN_CONTINUATION,
        RETRY_TASK,
        FORCE_ROTATE_SESSION,
    }
)
COMMAND_ACTIONS = frozenset({PAUSE_MISSION, CONTINUE_MISSION, CANCEL_TASK})
SERVICE_ACTIONS = SUPPORTED_ACTIONS - COMMAND_ACTIONS

MISSION_SOURCE = "MISSION"
WORK_GRAPH_SOURCE = "WORK_GRAPH"
EXECUTION_SOURCE = "EXECUTION_RESUME"
LINEAGE_SOURCE = "R2_5_LINEAGE"
HUMAN_GATE_SOURCE = "R2_6_HUMAN_GATE"
REQUIRED_SOURCES = (
    MISSION_SOURCE,
    WORK_GRAPH_SOURCE,
    EXECUTION_SOURCE,
    LINEAGE_SOURCE,
    HUMAN_GATE_SOURCE,
)

TELEMETRY_FIELDS = (
    "token_usage",
    "quota",
    "remaining",
    "quota_wait",
    "auto_resume",
    "model_provider_switch",
    "context_health",
    "priority",
    "selected_skill_tool",
)


class R27Error(DurableRuntimeError):
    """Fail-closed R2.7 contract or boundary error."""


R2_7Error = R27Error


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R27Error(R2_7_ACTION_REQUEST_INVALID, f"{name} must be a non-empty string")
    return value.strip()


def _non_negative(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise R27Error(R2_7_ACTION_REQUEST_INVALID, f"{name} must be a non-negative integer")
    return value


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R27Error(R2_7_ACTION_REQUEST_INVALID, f"{name} must be an object")
    return dict(value)


def _encode(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _encode(value.to_dict())
    if isinstance(value, Mapping):
        return {str(key): _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


@dataclass(frozen=True)
class SourceCursor:
    """Proof of how one source was read for one fixed cursor."""

    requested_as_of_seq: int
    read_through_seq: int
    projection_seq: int | None = None
    latest_relevant_event_seq: int | None = None
    status: str = CURRENT
    reason: str | None = None

    def __post_init__(self) -> None:
        requested = _non_negative(self.requested_as_of_seq, "requested_as_of_seq")
        read_through = _non_negative(self.read_through_seq, "read_through_seq")
        if read_through != requested:
            raise R27Error(
                R2_7_ACTION_REQUEST_INVALID,
                "read_through_seq must equal requested_as_of_seq for a fixed-cursor read",
            )
        if self.projection_seq is not None and self.projection_seq < -1:
            raise R27Error(R2_7_ACTION_REQUEST_INVALID, "projection_seq must be >= -1 or null")
        if self.latest_relevant_event_seq is not None:
            _non_negative(self.latest_relevant_event_seq, "latest_relevant_event_seq")
        if self.status not in SOURCE_STATUSES:
            raise R27Error(R2_7_ACTION_REQUEST_INVALID, f"unsupported SourceCursor status: {self.status}")

    @property
    def as_of_seq(self) -> int:
        return self.requested_as_of_seq

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_as_of_seq": self.requested_as_of_seq,
            "read_through_seq": self.read_through_seq,
            "projection_seq": self.projection_seq,
            "latest_relevant_event_seq": self.latest_relevant_event_seq,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Freshness:
    head_before_seq: int
    head_after_seq: int
    status: str = CURRENT
    reason: str | None = None

    def __post_init__(self) -> None:
        _non_negative(self.head_before_seq, "head_before_seq")
        _non_negative(self.head_after_seq, "head_after_seq")
        if self.status not in SOURCE_STATUSES:
            raise R27Error(R2_7_ACTION_REQUEST_INVALID, f"unsupported freshness status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "head_before_seq": self.head_before_seq,
            "head_after_seq": self.head_after_seq,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeOperationsQuery:
    mission_id: str
    as_of_seq: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        _non_negative(self.as_of_seq, "as_of_seq")
        if self.schema_version != SCHEMA_VERSION:
            raise R27Error(R2_7_ACTION_REQUEST_INVALID, "unsupported R2.7 query schema_version")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "RuntimeOperationsQuery") -> "RuntimeOperationsQuery":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise R27Error(R2_7_ACTION_REQUEST_INVALID, "RuntimeOperationsQuery must be an object")
        if "as_of_seq" not in value:
            raise R27Error(R2_7_ACTION_REQUEST_INVALID, "as_of_seq is required")
        return cls(
            mission_id=value.get("mission_id"),
            as_of_seq=value.get("as_of_seq"),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "as_of_seq": self.as_of_seq,
            "schema_version": self.schema_version,
        }


RuntimeOperationsQueryRequest = RuntimeOperationsQuery
RuntimeOperationsRequest = RuntimeOperationsQuery


@dataclass(frozen=True)
class RuntimeOperationsActionRequest:
    """Discriminated action request; target and payload remain caller-owned."""

    mission_id: str
    action: str
    target: Mapping[str, Any] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)
    operation_id: str | None = None
    command_id: str | None = None
    idempotency_key: str | None = None
    actor: Mapping[str, str] | None = None
    correlation_id: str | None = None
    expected_seq: int | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        action = _text(self.action, "action").upper()
        if action not in SUPPORTED_ACTIONS:
            raise R27Error(R2_7_ACTION_UNSUPPORTED, f"unsupported Runtime Operations action: {action}")
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "target", _mapping(self.target, "target"))
        object.__setattr__(self, "payload", _mapping(self.payload, "payload"))
        if self.operation_id is not None:
            object.__setattr__(self, "operation_id", _text(self.operation_id, "operation_id"))
        if self.command_id is not None:
            object.__setattr__(self, "command_id", _text(self.command_id, "command_id"))
        if self.idempotency_key is not None:
            object.__setattr__(self, "idempotency_key", _text(self.idempotency_key, "idempotency_key"))
        if self.correlation_id is not None:
            object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        if self.actor is not None:
            actor = _mapping(self.actor, "actor")
            object.__setattr__(self, "actor", {"type": _text(actor.get("type"), "actor.type"), "id": _text(actor.get("id"), "actor.id")})
        if self.expected_seq is not None:
            _non_negative(self.expected_seq, "expected_seq")
        if self.schema_version != SCHEMA_VERSION:
            raise R27Error(R2_7_ACTION_REQUEST_INVALID, "unsupported R2.7 action schema_version")
        if self.action in COMMAND_ACTIONS:
            if self.command_id is None:
                raise R27Error(R2_7_ACTION_REQUEST_INVALID, "command-based actions require caller-supplied command_id")
            if self.expected_seq is None:
                raise R27Error(R2_7_ACTION_REQUEST_INVALID, "command-based actions require caller-supplied expected_seq")
            if self.actor is None:
                raise R27Error(R2_7_ACTION_REQUEST_INVALID, "command-based actions require caller-supplied actor")
        merged = self.action_input()
        if self.action == CANCEL_TASK and not isinstance(merged.get("task_id"), str):
            raise R27Error(R2_7_ACTION_REQUEST_INVALID, "CANCEL_TASK requires target.task_id")
        native_identity_fields = {
            REVISE_GOAL: "intake_id",
            REVISE_PLAN: "planner_request_id",
            REQUEST_SESSION_ROTATION: "rotation_operation_id",
            SUBMIT_HUMAN_DECISION: "decision_id",
            RECORD_HUMAN_CONTINUATION: "continuation_operation_id",
        }
        native_identity = native_identity_fields.get(self.action)
        if native_identity is not None:
            if self.operation_id is None:
                raise R27Error(R2_7_ACTION_REQUEST_INVALID, f"{self.action} requires caller-supplied operation_id")
            if merged.get(native_identity) != self.operation_id:
                raise R27Error(
                    R2_7_ACTION_REQUEST_INVALID,
                    f"operation_id must equal {native_identity} for {self.action}",
                )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "RuntimeOperationsActionRequest") -> "RuntimeOperationsActionRequest":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise R27Error(R2_7_ACTION_REQUEST_INVALID, "RuntimeOperationsActionRequest must be an object")
        return cls(
            mission_id=value.get("mission_id"),
            action=value.get("action", value.get("action_type")),
            target=value.get("target", {}),
            payload=value.get("payload", {}),
            operation_id=value.get("operation_id"),
            command_id=value.get("command_id"),
            idempotency_key=value.get("idempotency_key"),
            actor=value.get("actor"),
            correlation_id=value.get("correlation_id"),
            expected_seq=value.get("expected_seq"),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
        )

    def action_input(self) -> dict[str, Any]:
        """Flatten only the existing DTO fields for a service boundary."""
        value = dict(self.target)
        value.update(self.payload)
        value.setdefault("mission_id", self.mission_id)
        if self.actor is not None:
            value.setdefault("actor", dict(self.actor))
        if self.expected_seq is not None:
            value.setdefault("expected_seq", self.expected_seq)
        if self.idempotency_key is not None:
            value["idempotency_key"] = self.idempotency_key
        if self.correlation_id is not None:
            value["correlation_id"] = self.correlation_id
        return value

    @property
    def action_type(self) -> str:
        return self.action

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "action": self.action,
            "target": _encode(self.target),
            "payload": _encode(self.payload),
            "operation_id": self.operation_id,
            "command_id": self.command_id,
            "idempotency_key": self.idempotency_key,
            "actor": _encode(self.actor),
            "correlation_id": self.correlation_id,
            "expected_seq": self.expected_seq,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class RuntimeOperationsReport:
    mission_id: str
    as_of_seq: int
    freshness: Freshness
    source_cursors: Mapping[str, SourceCursor]
    mission: Any = UNAVAILABLE
    goals: tuple[Any, ...] = ()
    sessions: tuple[Any, ...] = ()
    active_tasks: tuple[Any, ...] = ()
    delegations: tuple[Any, ...] = ()
    human_gates: tuple[Any, ...] = ()
    attempts: tuple[Any, ...] = ()
    resume_count: int | str = UNAVAILABLE
    verified_rotation_count: int | str = UNAVAILABLE
    historical_timeline: tuple[Any, ...] = ()
    current_observations: tuple[Any, ...] = ()
    telemetry: Mapping[str, Any] = field(default_factory=dict)
    report_kind: str = REPORT_IS_RUNTIME_PROJECTION

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        _non_negative(self.as_of_seq, "as_of_seq")
        if self.report_kind != REPORT_IS_RUNTIME_PROJECTION:
            raise R27Error(R2_7_ACTION_REQUEST_INVALID, "R2.7 reports must be runtime projections")
        object.__setattr__(self, "source_cursors", dict(self.source_cursors))
        object.__setattr__(self, "telemetry", dict(self.telemetry))

    @property
    def status(self) -> str:
        return self.freshness.status

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "as_of_seq": self.as_of_seq,
            "freshness": self.freshness.to_dict(),
            "source_cursors": {key: value.to_dict() for key, value in sorted(self.source_cursors.items())},
            "mission": _encode(self.mission),
            "goals": _encode(self.goals),
            "sessions": _encode(self.sessions),
            "active_tasks": _encode(self.active_tasks),
            "delegations": _encode(self.delegations),
            "human_gates": _encode(self.human_gates),
            "attempts": _encode(self.attempts),
            "resume_count": self.resume_count,
            "verified_rotation_count": self.verified_rotation_count,
            "historical_timeline": _encode(self.historical_timeline),
            "current_observations": _encode(self.current_observations),
            "telemetry": _encode(self.telemetry),
            "report_kind": self.report_kind,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


__all__ = [
    "CANONICAL_EVENT",
    "COMMAND_ACTIONS",
    "CONTRACT_VERSION",
    "CONTROL_PLANE_HTTP_INTEGRATION_GAP",
    "CURRENT",
    "CURRENT_OBSERVATION",
    "DERIVED_EVENT",
    "EXECUTION_SOURCE",
    "FORCE_ROTATE_SESSION",
    "Freshness",
    "HISTORICAL_KINDS",
    "HUMAN_GATE_SOURCE",
    "INCOMPLETE",
    "LINEAGE_SOURCE",
    "MISSION_SOURCE",
    "PAUSE_MISSION",
    "RECORD_HUMAN_CONTINUATION",
    "REQUEST_SESSION_ROTATION",
    "RETRY_TASK",
    "R2_7_ACTION_BOUNDARY_UNAVAILABLE",
    "R2_7_ACTION_REQUEST_INVALID",
    "R2_7_ACTION_UNSUPPORTED",
    "R2_7_AS_OF_SEQ_AHEAD_OF_HEAD",
    "R2_7_CONTRACT_VERSION",
    "R2_7_ERROR_CODES",
    "R2_7_MUST_NOT_SYNTHESIZE_MUTATION_IDENTITY",
    "R2_7Error",
    "R27Error",
    "REVISE_GOAL",
    "REVISE_PLAN",
    "RuntimeOperationsActionRequest",
    "RuntimeOperationsQuery",
    "RuntimeOperationsQueryRequest",
    "RuntimeOperationsReport",
    "RuntimeOperationsRequest",
    "SCHEMA_VERSION",
    "SERVICE_ACTIONS",
    "SourceCursor",
    "STALE",
    "SUBMIT_HUMAN_DECISION",
    "SUPPORTED_ACTIONS",
    "TELEMETRY_FIELDS",
    "UNAVAILABLE",
    "WORK_GRAPH_SOURCE",
    "CANCEL_TASK",
    "CONTINUE_MISSION",
]
