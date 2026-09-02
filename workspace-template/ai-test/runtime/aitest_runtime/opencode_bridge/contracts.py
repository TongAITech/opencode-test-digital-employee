from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Literal, Mapping

from aitest_runtime.durable_core import (
    ActorRef,
    CommandResult,
    ComposedRuntimeState,
    RuntimeError,
    canonical_sha256,
)
from aitest_runtime.execution_context import EventCursor


EXTENSION_ID = "r1_3d_opencode_bridge"
EXTENSION_VERSION = "1"
BRIDGE_SCHEMA_VERSION = 1
PROJECTION_VERSION = 1
COMMAND_TYPE = "OPENCODE_TRANSPORT"
EVENT_TYPE = "opencode.transport_observed.v1"
COMMAND_TYPES = frozenset({COMMAND_TYPE})
EVENT_TYPES = frozenset({EVENT_TYPE})


class TransportOperation(str, Enum):
    NEW = "NEW"
    RECONNECT = "RECONNECT"


TransportOutcome = Literal["ACCEPTED"]


def _error(message: str) -> RuntimeError:
    return RuntimeError("OPENCODE_BRIDGE_SCHEMA_INVALID", message)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{name} must be a non-empty string")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _non_negative(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _error(f"{name} must be a non-negative integer")
    return value


def _digest(value: Any, name: str) -> str:
    value = _text(value, name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise _error(f"{name} must be a lowercase SHA-256 digest")
    return value


def _cursor(value: Any, name: str) -> EventCursor:
    if isinstance(value, EventCursor):
        result = value
    elif isinstance(value, Mapping):
        try:
            result = EventCursor.from_dict(value)
        except RuntimeError as exc:
            raise _error(f"{name} is invalid") from exc
    else:
        raise _error(f"{name} must be an EventCursor object")
    if result.mission_id is None or result.stream_schema_version != 1:
        raise _error(f"{name} must be a mission-bound version 1 cursor")
    return result


def _operation(value: Any) -> TransportOperation:
    try:
        return value if isinstance(value, TransportOperation) else TransportOperation(value)
    except (TypeError, ValueError) as exc:
        raise _error("operation must be NEW or RECONNECT") from exc


@dataclass(frozen=True)
class OpenCodeBridgeRequest:
    """A logical bridge request anchored to Runtime facts.

    The provider and model are intentionally absent. They are obtained from a
    ProviderBinding rehydrated from the Runtime Event Stream immediately
    before the transport call.
    """

    command_id: str
    idempotency_key: str | None
    mission_id: str
    runtime_session_id: str
    expected_seq: int
    actor: ActorRef
    correlation_id: str | None
    bridge_request_id: str
    provider_request_id: str | None
    attempt_id: str
    operation: TransportOperation | str
    context_cursor: EventCursor
    context_semantic_digest: str
    external_transport_handle: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "command_id",
            "mission_id",
            "runtime_session_id",
            "bridge_request_id",
            "attempt_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "idempotency_key", _optional_text(self.idempotency_key, "idempotency_key"))
        object.__setattr__(self, "correlation_id", _optional_text(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "provider_request_id", _optional_text(self.provider_request_id, "provider_request_id"))
        object.__setattr__(self, "external_transport_handle", _optional_text(self.external_transport_handle, "external_transport_handle"))
        object.__setattr__(self, "expected_seq", _non_negative(self.expected_seq, "expected_seq"))
        if not isinstance(self.actor, ActorRef):
            raise _error("actor must be an ActorRef")
        object.__setattr__(self, "operation", _operation(self.operation))
        cursor = _cursor(self.context_cursor, "context_cursor")
        if cursor.mission_id != self.mission_id:
            raise RuntimeError("OPENCODE_BRIDGE_CONTEXT_MISMATCH", "context cursor Mission does not match request")
        if cursor.through_seq > self.expected_seq:
            raise RuntimeError("OPENCODE_BRIDGE_CONTEXT_MISMATCH", "context cursor is ahead of request sequence")
        object.__setattr__(self, "context_cursor", cursor)
        object.__setattr__(self, "context_semantic_digest", _digest(self.context_semantic_digest, "context_semantic_digest"))
        if self.operation == TransportOperation.RECONNECT and self.external_transport_handle is None:
            raise RuntimeError("OPENCODE_BRIDGE_HANDLE_REQUIRED", "RECONNECT requires an external transport handle")

    def with_operation(self, operation: TransportOperation | str) -> "OpenCodeBridgeRequest":
        return replace(self, operation=operation)

    @property
    def effective_correlation_id(self) -> str:
        return self.correlation_id or self.command_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "idempotency_key": self.idempotency_key,
            "mission_id": self.mission_id,
            "runtime_session_id": self.runtime_session_id,
            "expected_seq": self.expected_seq,
            "actor": self.actor.to_dict(),
            "correlation_id": self.correlation_id,
            "bridge_request_id": self.bridge_request_id,
            "provider_request_id": self.provider_request_id,
            "attempt_id": self.attempt_id,
            "operation": self.operation.value,
            "context_cursor": self.context_cursor.to_dict(),
            "context_semantic_digest": self.context_semantic_digest,
            "external_transport_handle": self.external_transport_handle,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OpenCodeBridgeRequest":
        if not isinstance(value, Mapping):
            raise _error("request must be an object")
        allowed = {
            "command_id",
            "idempotency_key",
            "mission_id",
            "runtime_session_id",
            "expected_seq",
            "actor",
            "correlation_id",
            "bridge_request_id",
            "provider_request_id",
            "attempt_id",
            "operation",
            "context_cursor",
            "context_semantic_digest",
            "external_transport_handle",
        }
        if not set(value) <= allowed:
            raise _error("request contains unknown fields")
        try:
            actor_raw = value["actor"]
            actor = actor_raw if isinstance(actor_raw, ActorRef) else ActorRef(actor_raw["type"], actor_raw["id"])
            return cls(
                command_id=value["command_id"],
                idempotency_key=value.get("idempotency_key"),
                mission_id=value["mission_id"],
                runtime_session_id=value["runtime_session_id"],
                expected_seq=value["expected_seq"],
                actor=actor,
                correlation_id=value.get("correlation_id"),
                bridge_request_id=value["bridge_request_id"],
                provider_request_id=value.get("provider_request_id"),
                attempt_id=value["attempt_id"],
                operation=value["operation"],
                context_cursor=value["context_cursor"],
                context_semantic_digest=value["context_semantic_digest"],
                external_transport_handle=value.get("external_transport_handle"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _error("request contains missing or malformed fields") from exc

    @property
    def transport_handle(self) -> str | None:
        return self.external_transport_handle

    @property
    def provider_session_handle(self) -> str | None:
        return self.external_transport_handle


OpenCodeTransportRequest = OpenCodeBridgeRequest
BridgeTransportRequest = OpenCodeBridgeRequest


@dataclass(frozen=True)
class TransportObservation:
    """The only transport result allowed across the bridge boundary."""

    status: str
    operation: TransportOperation | str
    bridge_request_id: str
    attempt_id: str
    runtime_session_id: str
    context_cursor: EventCursor
    context_semantic_digest: str
    correlation_id: str
    provider_request_id: str
    external_transport_handle: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _text(self.status, "status"))
        object.__setattr__(self, "operation", _operation(self.operation))
        for name in ("bridge_request_id", "attempt_id", "runtime_session_id", "correlation_id", "provider_request_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "external_transport_handle", _optional_text(self.external_transport_handle, "external_transport_handle"))
        cursor = _cursor(self.context_cursor, "context_cursor")
        object.__setattr__(self, "context_cursor", cursor)
        object.__setattr__(self, "context_semantic_digest", _digest(self.context_semantic_digest, "context_semantic_digest"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "operation": self.operation.value,
            "bridge_request_id": self.bridge_request_id,
            "attempt_id": self.attempt_id,
            "runtime_session_id": self.runtime_session_id,
            "context_cursor": self.context_cursor.to_dict(),
            "context_semantic_digest": self.context_semantic_digest,
            "correlation_id": self.correlation_id,
            "provider_request_id": self.provider_request_id,
            "external_transport_handle": self.external_transport_handle,
        }

    @property
    def transport_handle(self) -> str | None:
        return self.external_transport_handle

    @property
    def provider_session_handle(self) -> str | None:
        return self.external_transport_handle

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TransportObservation":
        if not isinstance(value, Mapping):
            raise _error("transport observation must be an object")
        required = {
            "status",
            "operation",
            "bridge_request_id",
            "attempt_id",
            "runtime_session_id",
            "context_cursor",
            "context_semantic_digest",
            "correlation_id",
            "provider_request_id",
            "external_transport_handle",
        }
        if set(value) != required:
            raise _error("transport observation contains unknown or missing fields")
        return cls(
            status=value["status"],
            operation=value["operation"],
            bridge_request_id=value["bridge_request_id"],
            attempt_id=value["attempt_id"],
            runtime_session_id=value["runtime_session_id"],
            context_cursor=value["context_cursor"],
            context_semantic_digest=value["context_semantic_digest"],
            correlation_id=value["correlation_id"],
            provider_request_id=value["provider_request_id"],
            external_transport_handle=value["external_transport_handle"],
        )

    def intent_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "operation": self.operation.value,
            "bridge_request_id": self.bridge_request_id,
            "attempt_id": self.attempt_id,
            "runtime_session_id": self.runtime_session_id,
            "context_cursor": self.context_cursor.to_dict(),
            "context_semantic_digest": self.context_semantic_digest,
            "correlation_id": self.correlation_id,
            "provider_request_id": self.provider_request_id,
            "external_transport_handle": self.external_transport_handle,
        }


@dataclass(frozen=True)
class TransportObservationRecord(TransportObservation):
    command_id: str = ""
    mission_id: str = ""
    created_seq: int = 0
    created_at: str = ""
    created_by: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "command_id", _text(self.command_id, "command_id"))
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))
        if not isinstance(self.created_seq, int) or isinstance(self.created_seq, bool) or self.created_seq < 1:
            raise _error("created_seq must be positive")
        object.__setattr__(self, "created_seq", self.created_seq)
        if self.created_by is None or set(self.created_by) != {"type", "id"}:
            raise _error("created_by must contain only type and id")
        object.__setattr__(self, "created_by", {"type": _text(self.created_by["type"], "created_by.type"), "id": _text(self.created_by["id"], "created_by.id")})
        if self.mission_id != self.context_cursor.mission_id:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "observation Mission and cursor differ")

    @property
    def observation_id(self) -> str:
        return self.bridge_request_id

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "command_id": self.command_id,
            "mission_id": self.mission_id,
            "created_seq": self.created_seq,
            "created_at": self.created_at,
            "created_by": dict(self.created_by or {}),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TransportObservationRecord":
        if not isinstance(value, Mapping):
            raise _error("observation record must be an object")
        required = {
            "status",
            "operation",
            "bridge_request_id",
            "attempt_id",
            "runtime_session_id",
            "context_cursor",
            "context_semantic_digest",
            "correlation_id",
            "provider_request_id",
            "external_transport_handle",
            "command_id",
            "mission_id",
            "created_seq",
            "created_at",
            "created_by",
        }
        if set(value) != required:
            raise _error("observation record contains unknown or missing fields")
        return cls(
            status=value["status"],
            operation=value["operation"],
            bridge_request_id=value["bridge_request_id"],
            attempt_id=value["attempt_id"],
            runtime_session_id=value["runtime_session_id"],
            context_cursor=value["context_cursor"],
            context_semantic_digest=value["context_semantic_digest"],
            correlation_id=value["correlation_id"],
            provider_request_id=value["provider_request_id"],
            external_transport_handle=value["external_transport_handle"],
            command_id=value["command_id"],
            mission_id=value["mission_id"],
            created_seq=value["created_seq"],
            created_at=value["created_at"],
            created_by=value["created_by"],
        )


OpenCodeTransportObservation = TransportObservation
OpenCodeTransportObservationRecord = TransportObservationRecord


@dataclass(frozen=True)
class OpenCodeBridgeState:
    mission_id: str
    observations: tuple[TransportObservationRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        if not isinstance(self.observations, tuple) or any(not isinstance(item, TransportObservationRecord) for item in self.observations):
            raise _error("observations must be an immutable tuple of records")
        bridge_ids = [item.bridge_request_id for item in self.observations]
        provider_ids = [item.provider_request_id for item in self.observations]
        if len(bridge_ids) != len(set(bridge_ids)):
            raise RuntimeError("OPENCODE_BRIDGE_DUPLICATE", "bridge_request_id is already observed")
        if len(provider_ids) != len(set(provider_ids)):
            raise RuntimeError("OPENCODE_BRIDGE_DUPLICATE", "provider_request_id is already observed")
        if any(item.mission_id != self.mission_id for item in self.observations):
            raise _error("observation Mission does not match state Mission")
        if tuple(item.created_seq for item in self.observations) != tuple(sorted(item.created_seq for item in self.observations)):
            raise _error("observations must be ordered by created_seq")

    def by_bridge_request_id(self, value: str) -> TransportObservationRecord | None:
        return next((item for item in self.observations if item.bridge_request_id == value), None)

    def by_provider_request_id(self, value: str) -> TransportObservationRecord | None:
        return next((item for item in self.observations if item.provider_request_id == value), None)

    def observation(self, value: str) -> TransportObservationRecord | None:
        return self.by_bridge_request_id(value)

    def to_dict(self) -> dict[str, Any]:
        return {"mission_id": self.mission_id, "observations": [item.to_dict() for item in self.observations]}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OpenCodeBridgeState":
        if not isinstance(value, Mapping) or set(value) != {"mission_id", "observations"}:
            raise _error("bridge state contains unknown or missing fields")
        observations = value["observations"]
        if not isinstance(observations, list):
            raise _error("observations must be an array")
        return cls(
            mission_id=value["mission_id"],
            observations=tuple(TransportObservationRecord.from_dict(item) for item in observations),
        )


BridgeState = OpenCodeBridgeState
TransportObservationState = OpenCodeBridgeState


@dataclass(frozen=True)
class RehydrateOpenCodeBridgeRequest:
    mission_id: str
    cursor: EventCursor

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        cursor = _cursor(self.cursor, "cursor")
        if cursor.mission_id != self.mission_id:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "cursor Mission does not match request Mission")
        object.__setattr__(self, "cursor", cursor)


RehydrateBridgeRequest = RehydrateOpenCodeBridgeRequest
RehydrateTransportRequest = RehydrateOpenCodeBridgeRequest


@dataclass(frozen=True)
class RehydratedOpenCodeBridge:
    mission_id: str
    cursor: EventCursor
    composed_state: ComposedRuntimeState
    bridge_state: OpenCodeBridgeState
    state_digest: str

    def __post_init__(self) -> None:
        if self.mission_id != self.cursor.mission_id or self.composed_state.mission_id != self.mission_id or self.composed_state.seq != self.cursor.through_seq:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "rehydrated bridge cursor is inconsistent")
        if self.bridge_state.mission_id != self.mission_id:
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "rehydrated bridge state Mission is inconsistent")
        object.__setattr__(self, "state_digest", _digest(self.state_digest, "state_digest"))


@dataclass(frozen=True)
class LogicalOpenCodeBridgeResult:
    outcome: Literal["APPLIED", "DUPLICATE"]
    command_result: CommandResult
    observation: TransportObservationRecord
    event_cursor: EventCursor
    binding: Any = None
    attempt: Any = None

    def __post_init__(self) -> None:
        if self.outcome not in {"APPLIED", "DUPLICATE"}:
            raise _error("invalid logical bridge outcome")
        if not isinstance(self.command_result, CommandResult):
            raise _error("command_result has an invalid type")
        if not isinstance(self.observation, TransportObservationRecord):
            raise _error("observation has an invalid type")
        if not isinstance(self.event_cursor, EventCursor):
            raise _error("event_cursor has an invalid type")

    @property
    def bridge_request_id(self) -> str:
        return self.observation.bridge_request_id

    @property
    def provider_request_id(self) -> str:
        return self.observation.provider_request_id

    @property
    def runtime_session_id(self) -> str:
        return self.observation.runtime_session_id

    @property
    def context_cursor(self) -> EventCursor:
        return self.observation.context_cursor

    @property
    def context_semantic_digest(self) -> str:
        return self.observation.context_semantic_digest

    @property
    def provider_session_handle(self) -> str | None:
        return self.observation.external_transport_handle

    @property
    def provider_binding(self) -> Any:
        return self.binding


LogicalBridgeResult = LogicalOpenCodeBridgeResult
LogicalTransportResult = LogicalOpenCodeBridgeResult


def observation_fingerprint(value: TransportObservation | TransportObservationRecord) -> str:
    return canonical_sha256(value.intent_dict())


__all__ = [
    "BRIDGE_SCHEMA_VERSION",
    "BridgeState",
    "BridgeTransportRequest",
    "COMMAND_TYPE",
    "COMMAND_TYPES",
    "EVENT_TYPE",
    "EVENT_TYPES",
    "EXTENSION_ID",
    "EXTENSION_VERSION",
    "LogicalBridgeResult",
    "LogicalOpenCodeBridgeResult",
    "LogicalTransportResult",
    "OpenCodeBridgeRequest",
    "OpenCodeBridgeState",
    "OpenCodeTransportObservation",
    "OpenCodeTransportObservationRecord",
    "OpenCodeTransportRequest",
    "PROJECTION_VERSION",
    "RehydrateBridgeRequest",
    "RehydrateOpenCodeBridgeRequest",
    "RehydrateTransportRequest",
    "RehydratedOpenCodeBridge",
    "TransportObservation",
    "TransportObservationRecord",
    "TransportObservationState",
    "TransportOperation",
    "observation_fingerprint",
]
