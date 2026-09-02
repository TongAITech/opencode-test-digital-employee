from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from aitest_runtime.durable_core import (
    ActorRef,
    CommandResult,
    ComposedRuntimeState,
    RuntimeError,
)
from aitest_runtime.execution_context import EventCursor


EXTENSION_ID = "r1_3c_provider_binding"
EXTENSION_VERSION = "1"
BINDING_SCHEMA_VERSION = 1
PROJECTION_VERSION = 1


def _error(message: str) -> RuntimeError:
    return RuntimeError("PROVIDER_BINDING_SCHEMA_INVALID", message)


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


def _positive(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _error(f"{name} must be a positive integer")
    return value


def _version(value: Any, name: str) -> str | int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _error(f"{name} must be a non-empty string or positive integer")
    if isinstance(value, int):
        return _positive(value, name)
    return _text(value, name)


def _digest(value: Any, name: str) -> str:
    value = _text(value, name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise _error(f"{name} must be a lowercase SHA-256 digest")
    return value


def _plain_json(value: Any, name: str) -> Any:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _error(f"{name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise _error(f"{name} contains a non-string object key")
            result[key] = _plain_json(item, f"{name}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_plain_json(item, f"{name}[{index}]") for index, item in enumerate(value)]
    raise _error(f"{name} contains an unsupported value of type {type(value).__name__}")


_FORBIDDEN_CONFIGURATION_KEY_PARTS = frozenset(
    {
        "secret",
        "password",
        "credential",
        "token",
        "raw_provider_response",
        "provider_response",
        "provider_session",
        "session_history",
        "history",
        "fallback",
        "candidate_provider",
        "routing_policy",
    }
)


def _safe_configuration_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(f"{name} must be an object")
    plain = _plain_json(value, name)

    def visit(current: Any, path: str) -> None:
        if isinstance(current, Mapping):
            for key, item in current.items():
                lowered = key.lower()
                if any(part in lowered for part in _FORBIDDEN_CONFIGURATION_KEY_PARTS):
                    raise RuntimeError(
                        "PROVIDER_BINDING_CONFIGURATION_FORBIDDEN",
                        f"{path}.{key} is not allowed in configuration",
                    )
                visit(item, f"{path}.{key}")
        elif isinstance(current, list):
            for index, item in enumerate(current):
                visit(item, f"{path}[{index}]")

    visit(plain, name)
    return plain


def _configuration(value: Any, name: str = "configuration") -> "ProviderConfiguration":
    if isinstance(value, ProviderConfiguration):
        return value
    if not isinstance(value, Mapping):
        raise _error(f"{name} must be an object")
    return ProviderConfiguration.from_dict(value)


@dataclass(frozen=True)
class ProviderConfiguration:
    """A reference to an explicit, externally defined provider configuration."""

    identity: str
    version: str | int
    digest: str
    scope: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "identity", _text(self.identity, "configuration.identity"))
        object.__setattr__(self, "version", _version(self.version, "configuration.version"))
        object.__setattr__(self, "digest", _digest(self.digest, "configuration.digest"))
        object.__setattr__(self, "scope", _safe_configuration_mapping(self.scope, "configuration.scope"))
        object.__setattr__(
            self,
            "provenance",
            _safe_configuration_mapping(self.provenance, "configuration.provenance"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "version": self.version,
            "digest": self.digest,
            "scope": dict(self.scope),
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderConfiguration":
        if not isinstance(value, Mapping):
            raise _error("configuration must be an object")
        required = {"identity", "version", "digest", "scope", "provenance"}
        if set(value) != required:
            raise _error("configuration contains unknown or missing fields")
        return cls(
            identity=value["identity"],
            version=value["version"],
            digest=value["digest"],
            scope=value["scope"],
            provenance=value["provenance"],
        )


ConfigurationDescriptor = ProviderConfiguration
BindingConfiguration = ProviderConfiguration


@dataclass(frozen=True)
class ProviderBindingRecord:
    attempt_id: str
    mission_id: str
    runtime_session_id: str
    provider: str
    model: str
    configuration: ProviderConfiguration
    command_id: str
    created_seq: int
    created_at: str
    created_by: Mapping[str, str]

    def __post_init__(self) -> None:
        for name in (
            "attempt_id",
            "mission_id",
            "runtime_session_id",
            "provider",
            "model",
            "command_id",
            "created_at",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "configuration", _configuration(self.configuration))
        object.__setattr__(self, "created_seq", _positive(self.created_seq, "created_seq"))
        if not isinstance(self.created_by, Mapping):
            raise _error("created_by must be an object")
        if set(self.created_by) != {"type", "id"}:
            raise _error("created_by must contain only type and id")
        object.__setattr__(
            self,
            "created_by",
            {"type": _text(self.created_by["type"], "created_by.type"), "id": _text(self.created_by["id"], "created_by.id")},
        )

    @property
    def binding_id(self) -> str:
        return self.attempt_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "mission_id": self.mission_id,
            "runtime_session_id": self.runtime_session_id,
            "provider": self.provider,
            "model": self.model,
            "configuration": self.configuration.to_dict(),
            "command_id": self.command_id,
            "created_seq": self.created_seq,
            "created_at": self.created_at,
            "created_by": dict(self.created_by),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderBindingRecord":
        if not isinstance(value, Mapping):
            raise _error("Provider Binding record must be an object")
        required = {
            "attempt_id",
            "mission_id",
            "runtime_session_id",
            "provider",
            "model",
            "configuration",
            "command_id",
            "created_seq",
            "created_at",
            "created_by",
        }
        if set(value) != required:
            raise _error("Provider Binding record contains unknown or missing fields")
        return cls(
            attempt_id=value["attempt_id"],
            mission_id=value["mission_id"],
            runtime_session_id=value["runtime_session_id"],
            provider=value["provider"],
            model=value["model"],
            configuration=ProviderConfiguration.from_dict(value["configuration"]),
            command_id=value["command_id"],
            created_seq=value["created_seq"],
            created_at=value["created_at"],
            created_by=value["created_by"],
        )


ProviderBinding = ProviderBindingRecord


@dataclass(frozen=True)
class ProviderBindingState:
    mission_id: str
    bindings: tuple[ProviderBindingRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        if not isinstance(self.bindings, tuple) or any(
            not isinstance(item, ProviderBindingRecord) for item in self.bindings
        ):
            raise _error("bindings must be an immutable tuple")
        ids = [item.attempt_id for item in self.bindings]
        if len(ids) != len(set(ids)):
            raise RuntimeError("PROVIDER_BINDING_ALREADY_EXISTS", "each Attempt may have only one successful binding")
        if any(item.mission_id != self.mission_id for item in self.bindings):
            raise RuntimeError("PROVIDER_BINDING_LINEAGE_MISMATCH", "binding Mission mismatch")
        if tuple(item.created_seq for item in self.bindings) != tuple(
            sorted(item.created_seq for item in self.bindings)
        ):
            raise _error("bindings must be ordered by created_seq")

    def binding(self, attempt_id: str) -> ProviderBindingRecord | None:
        return next((item for item in self.bindings if item.attempt_id == attempt_id), None)

    def binding_for_attempt(self, attempt_id: str) -> ProviderBindingRecord | None:
        return self.binding(attempt_id)

    def to_dict(self) -> dict[str, Any]:
        return {"mission_id": self.mission_id, "bindings": [item.to_dict() for item in self.bindings]}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderBindingState":
        if not isinstance(value, Mapping) or set(value) != {"mission_id", "bindings"}:
            raise _error("Provider Binding state contains unknown or missing fields")
        if not isinstance(value["bindings"], list):
            raise _error("bindings must be an array")
        return cls(
            mission_id=value["mission_id"],
            bindings=tuple(ProviderBindingRecord.from_dict(item) for item in value["bindings"]),
        )


@dataclass(frozen=True)
class RehydrateProviderBindingRequest:
    mission_id: str
    cursor: EventCursor

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        if not isinstance(self.cursor, EventCursor) or self.cursor.mission_id != self.mission_id:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "cursor must be bound to mission_id")
        if self.cursor.stream_schema_version != 1:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "unsupported stream schema version")


RehydrateBindingRequest = RehydrateProviderBindingRequest


@dataclass(frozen=True)
class RehydratedProviderBinding:
    mission_id: str
    cursor: EventCursor
    composed_state: ComposedRuntimeState
    binding_state: ProviderBindingState
    state_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        if not isinstance(self.cursor, EventCursor) or self.cursor.mission_id != self.mission_id:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "rehydrated cursor mismatch")
        if not isinstance(self.composed_state, ComposedRuntimeState):
            raise _error("composed_state has an invalid type")
        if self.composed_state.mission_id != self.mission_id or self.composed_state.seq != self.cursor.through_seq:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "rehydrated state does not match cursor")
        if not isinstance(self.binding_state, ProviderBindingState) or self.binding_state.mission_id != self.mission_id:
            raise _error("binding_state has an invalid type")
        object.__setattr__(self, "state_digest", _digest(self.state_digest, "state_digest"))

    @property
    def provider_binding_state(self) -> ProviderBindingState:
        return self.binding_state


@dataclass(frozen=True)
class BindProviderAttemptRequest:
    command_id: str
    idempotency_key: str | None
    mission_id: str
    runtime_session_id: str
    expected_seq: int
    actor: ActorRef
    correlation_id: str | None
    attempt_id: str
    provider: str
    model: str
    configuration: ProviderConfiguration | Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in (
            "command_id",
            "mission_id",
            "runtime_session_id",
            "attempt_id",
            "provider",
            "model",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "idempotency_key", _optional_text(self.idempotency_key, "idempotency_key"))
        object.__setattr__(self, "correlation_id", _optional_text(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "expected_seq", _non_negative(self.expected_seq, "expected_seq"))
        if not isinstance(self.actor, ActorRef):
            raise _error("actor must be an ActorRef")
        object.__setattr__(self, "configuration", _configuration(self.configuration))

    @property
    def provider_configuration(self) -> ProviderConfiguration:
        return self.configuration

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "idempotency_key": self.idempotency_key,
            "mission_id": self.mission_id,
            "runtime_session_id": self.runtime_session_id,
            "expected_seq": self.expected_seq,
            "actor": self.actor.to_dict(),
            "correlation_id": self.correlation_id,
            "attempt_id": self.attempt_id,
            "provider": self.provider,
            "model": self.model,
            "configuration": self.configuration.to_dict(),
        }


ProviderBindingRequest = BindProviderAttemptRequest


@dataclass(frozen=True)
class LogicalProviderBindingResult:
    outcome: Literal["APPLIED", "DUPLICATE"]
    command_result: CommandResult
    binding: ProviderBindingRecord
    event_cursor: EventCursor

    def __post_init__(self) -> None:
        if self.outcome not in {"APPLIED", "DUPLICATE"}:
            raise _error("invalid logical Provider Binding outcome")
        if not isinstance(self.command_result, CommandResult):
            raise _error("command_result has an invalid type")
        if not isinstance(self.binding, ProviderBindingRecord):
            raise _error("binding has an invalid type")
        if not isinstance(self.event_cursor, EventCursor):
            raise _error("event_cursor has an invalid type")

    @property
    def provider_binding(self) -> ProviderBindingRecord:
        return self.binding


__all__ = [
    "BINDING_SCHEMA_VERSION",
    "BindingConfiguration",
    "BindProviderAttemptRequest",
    "ConfigurationDescriptor",
    "EXTENSION_ID",
    "EXTENSION_VERSION",
    "LogicalProviderBindingResult",
    "PROJECTION_VERSION",
    "ProviderBinding",
    "ProviderBindingRecord",
    "ProviderBindingRequest",
    "ProviderBindingState",
    "ProviderConfiguration",
    "RehydrateBindingRequest",
    "RehydrateProviderBindingRequest",
    "RehydratedProviderBinding",
]
