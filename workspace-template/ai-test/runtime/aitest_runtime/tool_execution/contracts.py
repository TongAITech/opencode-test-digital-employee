from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping

from aitest_runtime.durable_core import (
    ActorRef,
    CommandResult,
    ComposedRuntimeState,
    RuntimeError,
    RuntimeService,
    canonical_sha256,
)
from aitest_runtime.execution_context import EventCursor


EXTENSION_ID = "r1_4_tool_execution"
EXTENSION_VERSION = "1"
TOOL_EXECUTION_SCHEMA_VERSION = 1
PROJECTION_VERSION = 1
CANONICALIZATION_VERSION = 1

REQUEST_COMMAND = "REQUEST_TOOL_EXECUTION"
OUTCOME_COMMAND = "RECORD_TOOL_EXECUTION_OUTCOME"
RECONCILE_COMMAND = "RECONCILE_TOOL_EXECUTION"
EVIDENCE_COMMAND = "RECORD_EVIDENCE"
COMMAND_TYPES = frozenset({REQUEST_COMMAND, OUTCOME_COMMAND, RECONCILE_COMMAND, EVIDENCE_COMMAND})

REQUEST_EVENT = "tool.execution_requested.v1"
OUTCOME_EVENT = "tool.execution_observed.v1"
RECONCILE_EVENT = "tool.execution_reconciled.v1"
EVIDENCE_EVENT = "tool.evidence_attached.v1"
EVENT_TYPES = frozenset({REQUEST_EVENT, OUTCOME_EVENT, RECONCILE_EVENT, EVIDENCE_EVENT})


class SideEffectState(str, Enum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    ATTEMPTED = "ATTEMPTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class SideEffectPolicy(str, Enum):
    NONE = "NONE"
    REVERSIBLE = "REVERSIBLE"
    IRREVERSIBLE = "IRREVERSIBLE"


ToolExecutionStatus = SideEffectState

_SENSITIVE_NAMES = {
    "password",
    "passwd",
    "token",
    "access_token",
    "refresh_token",
    "cookie",
    "set_cookie",
    "otp",
    "mfa",
    "secret",
    "private_key",
    "authorization",
}


def _error(message: str, code: str = "TOOL_EXECUTION_SCHEMA_INVALID") -> RuntimeError:
    return RuntimeError(code, message)


def _text(value: Any, name: str, code: str = "TOOL_EXECUTION_SCHEMA_INVALID") -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{name} must be a non-empty string", code)
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


def _digest(value: Any, name: str) -> str:
    value = _text(value, name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise _error(f"{name} must be a lowercase SHA-256 digest")
    return value


def _cursor(value: Any, name: str = "context_cursor") -> EventCursor:
    if isinstance(value, EventCursor):
        cursor = value
    elif isinstance(value, Mapping):
        try:
            cursor = EventCursor.from_dict(value)
        except RuntimeError as exc:
            raise _error(f"{name} is invalid") from exc
    else:
        raise _error(f"{name} must be an EventCursor")
    if cursor.mission_id is None or cursor.stream_schema_version != 1:
        raise _error(f"{name} must be a mission-bound version 1 cursor")
    return cursor


def _enum(value: Any, enum_type: type[Enum], name: str) -> Enum:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as exc:
        raise _error(f"{name} is invalid") from exc


def _safe_value(value: Any, path: str = "value") -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _error(f"{path} contains a non-string key")
            if key.lower() in _SENSITIVE_NAMES or any(part in key.lower() for part in ("password", "token", "cookie", "otp", "mfa")):
                raise _error(f"{path}.{key} contains a prohibited sensitive field", "TOOL_EXECUTION_SENSITIVE_DATA")
            result[key] = _safe_value(item, f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, f"{path}[]") for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise _error(f"{path} contains an unsupported value")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(f"{name} must be an object")
    return _safe_value(value, name)


def _actor(value: Any) -> ActorRef:
    if isinstance(value, ActorRef):
        return value
    if not isinstance(value, Mapping):
        raise _error("actor must be an ActorRef")
    try:
        return ActorRef(value["type"], value["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _error("actor is invalid") from exc


def _created_by(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"type", "id"}:
        raise _error("created_by must contain only type and id")
    return {"type": _text(value["type"], "created_by.type"), "id": _text(value["id"], "created_by.id")}


@dataclass(frozen=True)
class ToolExecutionRequest:
    command_id: str
    idempotency_key: str | None
    mission_id: str
    plan_id: str
    plan_revision_id: str
    task_id: str
    attempt_id: str
    runtime_session_id: str
    expected_seq: int
    actor: ActorRef
    correlation_id: str | None
    tool_execution_id: str
    capability_id: str
    capability_version: int
    provider_binding_id: str
    provider_binding_digest: str
    context_cursor: EventCursor
    input_digest: str
    side_effect_policy: SideEffectPolicy | str
    input_reference: str | None = None
    redacted_input: Mapping[str, Any] = field(default_factory=dict)
    authorization_id: str | None = None
    context_semantic_digest: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "command_id", "mission_id", "plan_id", "plan_revision_id", "task_id", "attempt_id",
            "runtime_session_id", "tool_execution_id", "capability_id", "provider_binding_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "idempotency_key", _optional_text(self.idempotency_key, "idempotency_key"))
        object.__setattr__(self, "correlation_id", _optional_text(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "input_reference", _optional_text(self.input_reference, "input_reference"))
        object.__setattr__(self, "authorization_id", _optional_text(self.authorization_id, "authorization_id"))
        object.__setattr__(self, "context_semantic_digest", _optional_text(self.context_semantic_digest, "context_semantic_digest"))
        object.__setattr__(self, "expected_seq", _non_negative(self.expected_seq, "expected_seq"))
        object.__setattr__(self, "capability_version", _positive(self.capability_version, "capability_version"))
        if not isinstance(self.actor, ActorRef):
            raise _error("actor must be an ActorRef")
        cursor = _cursor(self.context_cursor)
        if cursor.mission_id != self.mission_id or cursor.through_seq > self.expected_seq:
            raise _error("context_cursor is not a prior cursor for this Mission", "TOOL_EXECUTION_CONTEXT_MISMATCH")
        object.__setattr__(self, "context_cursor", cursor)
        object.__setattr__(self, "provider_binding_digest", _digest(self.provider_binding_digest, "provider_binding_digest"))
        object.__setattr__(self, "input_digest", _digest(self.input_digest, "input_digest"))
        object.__setattr__(self, "side_effect_policy", _enum(self.side_effect_policy, SideEffectPolicy, "side_effect_policy"))
        object.__setattr__(self, "redacted_input", _mapping(self.redacted_input, "redacted_input"))

    @property
    def fixed_context_cursor(self) -> EventCursor:
        return self.context_cursor

    @property
    def capability_identity(self) -> str:
        return self.capability_id

    @property
    def provider_binding_identity(self) -> str:
        return self.provider_binding_id

    @property
    def effective_correlation_id(self) -> str:
        return self.correlation_id or self.command_id

    def intent_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "runtime_session_id": self.runtime_session_id,
            "tool_execution_id": self.tool_execution_id,
            "capability_id": self.capability_id,
            "capability_version": self.capability_version,
            "provider_binding_id": self.provider_binding_id,
            "provider_binding_digest": self.provider_binding_digest,
            "context_cursor": self.context_cursor.to_dict(),
            "context_semantic_digest": self.context_semantic_digest,
            "input_digest": self.input_digest,
            "side_effect_policy": self.side_effect_policy.value,
            "input_reference": self.input_reference,
            "redacted_input": dict(self.redacted_input),
            "authorization_id": self.authorization_id,
        }

    @property
    def intent_digest(self) -> str:
        return canonical_sha256(self.intent_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "idempotency_key": self.idempotency_key,
            "mission_id": self.mission_id,
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "runtime_session_id": self.runtime_session_id,
            "expected_seq": self.expected_seq,
            "actor": self.actor.to_dict(),
            "correlation_id": self.correlation_id,
            "tool_execution_id": self.tool_execution_id,
            "capability_id": self.capability_id,
            "capability_version": self.capability_version,
            "provider_binding_id": self.provider_binding_id,
            "provider_binding_digest": self.provider_binding_digest,
            "context_cursor": self.context_cursor.to_dict(),
            "input_digest": self.input_digest,
            "side_effect_policy": self.side_effect_policy.value,
            "input_reference": self.input_reference,
            "redacted_input": dict(self.redacted_input),
            "authorization_id": self.authorization_id,
            "context_semantic_digest": self.context_semantic_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ToolExecutionRequest":
        if not isinstance(value, Mapping):
            raise _error("request must be an object")
        allowed = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if not set(value) <= allowed:
            raise _error("request contains unknown fields")
        try:
            return cls(
                command_id=value["command_id"], idempotency_key=value.get("idempotency_key"), mission_id=value["mission_id"],
                plan_id=value["plan_id"], plan_revision_id=value["plan_revision_id"], task_id=value["task_id"],
                attempt_id=value["attempt_id"], runtime_session_id=value["runtime_session_id"], expected_seq=value["expected_seq"],
                actor=_actor(value["actor"]), correlation_id=value.get("correlation_id"), tool_execution_id=value["tool_execution_id"],
                capability_id=value["capability_id"], capability_version=value["capability_version"],
                provider_binding_id=value["provider_binding_id"], provider_binding_digest=value["provider_binding_digest"],
                context_cursor=value["context_cursor"], input_digest=value["input_digest"],
                side_effect_policy=value["side_effect_policy"], input_reference=value.get("input_reference"),
                redacted_input=value.get("redacted_input") or {}, authorization_id=value.get("authorization_id"),
                context_semantic_digest=value.get("context_semantic_digest"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _error("request contains missing or malformed fields") from exc


@dataclass(frozen=True)
class ToolExecutionIntent:
    tool_execution_id: str
    mission_id: str
    plan_id: str
    plan_revision_id: str
    task_id: str
    attempt_id: str
    runtime_session_id: str
    capability_id: str
    capability_version: int
    provider_binding_id: str
    provider_binding_digest: str
    context_cursor: EventCursor
    input_digest: str
    side_effect_policy: SideEffectPolicy | str
    intent_digest: str
    idempotency_key: str | None
    command_id: str
    created_seq: int
    created_at: str
    created_by: Mapping[str, str]
    correlation_id: str
    input_reference: str | None = None
    redacted_input: Mapping[str, Any] = field(default_factory=dict)
    authorization_id: str | None = None
    context_semantic_digest: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "tool_execution_id", "mission_id", "plan_id", "plan_revision_id", "task_id", "attempt_id",
            "runtime_session_id", "capability_id", "provider_binding_id", "command_id", "created_at", "correlation_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "idempotency_key", _optional_text(self.idempotency_key, "idempotency_key"))
        object.__setattr__(self, "input_reference", _optional_text(self.input_reference, "input_reference"))
        object.__setattr__(self, "authorization_id", _optional_text(self.authorization_id, "authorization_id"))
        object.__setattr__(self, "context_semantic_digest", _optional_text(self.context_semantic_digest, "context_semantic_digest"))
        object.__setattr__(self, "capability_version", _positive(self.capability_version, "capability_version"))
        object.__setattr__(self, "provider_binding_digest", _digest(self.provider_binding_digest, "provider_binding_digest"))
        object.__setattr__(self, "input_digest", _digest(self.input_digest, "input_digest"))
        object.__setattr__(self, "intent_digest", _digest(self.intent_digest, "intent_digest"))
        object.__setattr__(self, "context_cursor", _cursor(self.context_cursor))
        object.__setattr__(self, "side_effect_policy", _enum(self.side_effect_policy, SideEffectPolicy, "side_effect_policy"))
        object.__setattr__(self, "created_seq", _positive(self.created_seq, "created_seq"))
        object.__setattr__(self, "created_by", _created_by(self.created_by))
        object.__setattr__(self, "redacted_input", _mapping(self.redacted_input, "redacted_input"))
        if self.context_cursor.mission_id != self.mission_id:
            raise _error("intent Mission and context cursor differ", "TOOL_EXECUTION_CONTEXT_MISMATCH")

    @property
    def fixed_context_cursor(self) -> EventCursor:
        return self.context_cursor

    @property
    def capability_identity(self) -> str:
        return self.capability_id

    @property
    def provider_binding_identity(self) -> str:
        return self.provider_binding_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_execution_id": self.tool_execution_id, "mission_id": self.mission_id, "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id, "task_id": self.task_id, "attempt_id": self.attempt_id,
            "runtime_session_id": self.runtime_session_id, "capability_id": self.capability_id,
            "capability_version": self.capability_version, "provider_binding_id": self.provider_binding_id,
            "provider_binding_digest": self.provider_binding_digest, "context_cursor": self.context_cursor.to_dict(),
            "input_digest": self.input_digest, "side_effect_policy": self.side_effect_policy.value,
            "intent_digest": self.intent_digest, "idempotency_key": self.idempotency_key, "command_id": self.command_id,
            "created_seq": self.created_seq, "created_at": self.created_at, "created_by": dict(self.created_by),
            "correlation_id": self.correlation_id, "input_reference": self.input_reference,
            "redacted_input": dict(self.redacted_input), "authorization_id": self.authorization_id,
            "context_semantic_digest": self.context_semantic_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ToolExecutionIntent":
        if not isinstance(value, Mapping):
            raise _error("intent must be an object")
        required = {
            "tool_execution_id", "mission_id", "plan_id", "plan_revision_id", "task_id", "attempt_id",
            "runtime_session_id", "capability_id", "capability_version", "provider_binding_id", "provider_binding_digest",
            "context_cursor", "input_digest", "side_effect_policy", "intent_digest", "idempotency_key", "command_id",
            "created_seq", "created_at", "created_by", "correlation_id", "input_reference", "redacted_input",
            "authorization_id", "context_semantic_digest",
        }
        if set(value) != required:
            raise _error("intent contains unknown or missing fields")
        return cls(
            tool_execution_id=value["tool_execution_id"], mission_id=value["mission_id"], plan_id=value["plan_id"],
            plan_revision_id=value["plan_revision_id"], task_id=value["task_id"], attempt_id=value["attempt_id"],
            runtime_session_id=value["runtime_session_id"], capability_id=value["capability_id"],
            capability_version=value["capability_version"], provider_binding_id=value["provider_binding_id"],
            provider_binding_digest=value["provider_binding_digest"], context_cursor=value["context_cursor"],
            input_digest=value["input_digest"], side_effect_policy=value["side_effect_policy"],
            intent_digest=value["intent_digest"], idempotency_key=value["idempotency_key"], command_id=value["command_id"],
            created_seq=value["created_seq"], created_at=value["created_at"], created_by=value["created_by"],
            correlation_id=value["correlation_id"], input_reference=value["input_reference"],
            redacted_input=value["redacted_input"], authorization_id=value["authorization_id"],
            context_semantic_digest=value["context_semantic_digest"],
        )


@dataclass(frozen=True)
class ToolObservation:
    status: SideEffectState | str
    side_effect_state: SideEffectState | str
    result_digest: str | None = None
    result_reference: str | None = None
    redacted_result: Mapping[str, Any] = field(default_factory=dict)
    external_request_id: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _enum(self.status, SideEffectState, "status"))
        object.__setattr__(self, "side_effect_state", _enum(self.side_effect_state, SideEffectState, "side_effect_state"))
        if self.result_digest is not None:
            object.__setattr__(self, "result_digest", _digest(self.result_digest, "result_digest"))
        object.__setattr__(self, "result_reference", _optional_text(self.result_reference, "result_reference"))
        object.__setattr__(self, "external_request_id", _optional_text(self.external_request_id, "external_request_id"))
        object.__setattr__(self, "error_code", _optional_text(self.error_code, "error_code"))
        object.__setattr__(self, "redacted_result", _mapping(self.redacted_result, "redacted_result"))
        if self.status == SideEffectState.CONFIRMED and self.side_effect_state not in {SideEffectState.CONFIRMED, SideEffectState.NOT_ATTEMPTED}:
            raise _error("CONFIRMED observation has an incompatible side_effect_state")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value, "side_effect_state": self.side_effect_state.value, "result_digest": self.result_digest,
            "result_reference": self.result_reference, "redacted_result": dict(self.redacted_result),
            "external_request_id": self.external_request_id, "error_code": self.error_code,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ToolObservation":
        if not isinstance(value, Mapping) or set(value) != {
            "status", "side_effect_state", "result_digest", "result_reference", "redacted_result", "external_request_id", "error_code"
        }:
            raise _error("observation contains unknown or missing fields")
        return cls(**dict(value))


ToolExecutionObservation = ToolObservation


@dataclass(frozen=True)
class ExecutionFact(ToolObservation):
    execution_fact_id: str = ""
    tool_execution_id: str = ""
    mission_id: str = ""
    command_id: str = ""
    created_seq: int = 0
    created_at: str = ""
    created_by: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        for name in ("execution_fact_id", "tool_execution_id", "mission_id", "command_id", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "created_seq", _positive(self.created_seq, "created_seq"))
        object.__setattr__(self, "created_by", _created_by(self.created_by))

    @property
    def fact_id(self) -> str:
        return self.execution_fact_id

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(), "execution_fact_id": self.execution_fact_id, "tool_execution_id": self.tool_execution_id,
            "mission_id": self.mission_id, "command_id": self.command_id, "created_seq": self.created_seq,
            "created_at": self.created_at, "created_by": dict(self.created_by),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionFact":
        required = {
            "status", "side_effect_state", "result_digest", "result_reference", "redacted_result", "external_request_id", "error_code",
            "execution_fact_id", "tool_execution_id", "mission_id", "command_id", "created_seq", "created_at", "created_by",
        }
        if not isinstance(value, Mapping) or set(value) != required:
            raise _error("execution fact contains unknown or missing fields")
        return cls(**dict(value))


@dataclass(frozen=True)
class ReconciliationFact(ToolObservation):
    reconciliation_id: str = ""
    tool_execution_id: str = ""
    mission_id: str = ""
    command_id: str = ""
    created_seq: int = 0
    created_at: str = ""
    created_by: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        for name in ("reconciliation_id", "tool_execution_id", "mission_id", "command_id", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "created_seq", _positive(self.created_seq, "created_seq"))
        object.__setattr__(self, "created_by", _created_by(self.created_by))

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(), "reconciliation_id": self.reconciliation_id, "tool_execution_id": self.tool_execution_id,
            "mission_id": self.mission_id, "command_id": self.command_id, "created_seq": self.created_seq,
            "created_at": self.created_at, "created_by": dict(self.created_by),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReconciliationFact":
        required = {
            "status", "side_effect_state", "result_digest", "result_reference", "redacted_result", "external_request_id", "error_code",
            "reconciliation_id", "tool_execution_id", "mission_id", "command_id", "created_seq", "created_at", "created_by",
        }
        if not isinstance(value, Mapping) or set(value) != required:
            raise _error("reconciliation fact contains unknown or missing fields")
        return cls(**dict(value))


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    tool_execution_id: str
    execution_fact_id: str
    mission_id: str
    evidence_type: str
    content_digest: str
    artifact_reference: str | None
    provenance: Mapping[str, Any]
    metadata: Mapping[str, Any]
    verification_method: str
    verified: bool
    command_id: str
    created_seq: int
    created_at: str
    created_by: Mapping[str, str]

    def __post_init__(self) -> None:
        for name in ("evidence_id", "tool_execution_id", "execution_fact_id", "mission_id", "evidence_type", "verification_method", "command_id", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "content_digest", _digest(self.content_digest, "content_digest"))
        object.__setattr__(self, "artifact_reference", _optional_text(self.artifact_reference, "artifact_reference"))
        object.__setattr__(self, "provenance", _mapping(self.provenance, "provenance"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        object.__setattr__(self, "created_seq", _positive(self.created_seq, "created_seq"))
        if not isinstance(self.verified, bool):
            raise _error("verified must be a boolean")
        object.__setattr__(self, "created_by", _created_by(self.created_by))
        if self.artifact_reference is None and not self.content_digest:
            raise _error("evidence requires a digest or artifact reference")

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id, "tool_execution_id": self.tool_execution_id, "execution_fact_id": self.execution_fact_id,
            "mission_id": self.mission_id, "evidence_type": self.evidence_type, "content_digest": self.content_digest,
            "artifact_reference": self.artifact_reference, "provenance": dict(self.provenance), "metadata": dict(self.metadata),
            "verification_method": self.verification_method, "verified": self.verified, "command_id": self.command_id,
            "created_seq": self.created_seq, "created_at": self.created_at, "created_by": dict(self.created_by),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceRecord":
        required = {
            "evidence_id", "tool_execution_id", "execution_fact_id", "mission_id", "evidence_type", "content_digest",
            "artifact_reference", "provenance", "metadata", "verification_method", "verified", "command_id", "created_seq", "created_at", "created_by",
        }
        if not isinstance(value, Mapping) or set(value) != required:
            raise _error("evidence record contains unknown or missing fields")
        return cls(**dict(value))


@dataclass(frozen=True)
class ToolExecutionRecord:
    intent: ToolExecutionIntent
    facts: tuple[ExecutionFact, ...] = ()
    reconciliations: tuple[ReconciliationFact, ...] = ()
    evidence: tuple[EvidenceRecord, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.intent, ToolExecutionIntent):
            raise _error("intent has an invalid type")
        for name, typ in (("facts", ExecutionFact), ("reconciliations", ReconciliationFact), ("evidence", EvidenceRecord)):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, typ) for item in values):
                raise _error(f"{name} must be an immutable tuple")
            if tuple(item.created_seq for item in values) != tuple(sorted(item.created_seq for item in values)):
                raise _error(f"{name} must be ordered by created_seq")

    @property
    def tool_execution_id(self) -> str:
        return self.intent.tool_execution_id

    @property
    def execution_fact(self) -> ExecutionFact | None:
        return self.facts[-1] if self.facts else None

    @property
    def latest_fact(self) -> ExecutionFact | None:
        return self.execution_fact

    @property
    def reconciliation(self) -> ReconciliationFact | None:
        return self.reconciliations[-1] if self.reconciliations else None

    @property
    def side_effect_state(self) -> SideEffectState:
        fact = self.execution_fact
        reconciliation = self.reconciliation
        if reconciliation is not None and (fact is None or reconciliation.created_seq > fact.created_seq):
            return reconciliation.side_effect_state
        if fact is not None:
            return fact.side_effect_state
        return SideEffectState.NOT_ATTEMPTED

    @property
    def status(self) -> SideEffectState:
        fact = self.execution_fact
        reconciliation = self.reconciliation
        if reconciliation is not None and (fact is None or reconciliation.created_seq > fact.created_seq):
            return reconciliation.status
        if fact is not None:
            return fact.status
        return SideEffectState.NOT_ATTEMPTED

    @property
    def intent_digest(self) -> str:
        return self.intent.intent_digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.to_dict(), "facts": [item.to_dict() for item in self.facts],
            "reconciliations": [item.to_dict() for item in self.reconciliations],
            "evidence": [item.to_dict() for item in self.evidence],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ToolExecutionRecord":
        if not isinstance(value, Mapping) or set(value) != {"intent", "facts", "reconciliations", "evidence"}:
            raise _error("tool execution record contains unknown or missing fields")
        return cls(
            ToolExecutionIntent.from_dict(value["intent"]),
            tuple(ExecutionFact.from_dict(item) for item in value["facts"]),
            tuple(ReconciliationFact.from_dict(item) for item in value["reconciliations"]),
            tuple(EvidenceRecord.from_dict(item) for item in value["evidence"]),
        )


@dataclass(frozen=True)
class ToolExecutionState:
    mission_id: str
    executions: tuple[ToolExecutionRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        if not isinstance(self.executions, tuple) or any(not isinstance(item, ToolExecutionRecord) for item in self.executions):
            raise _error("executions must be an immutable tuple")
        ids = [item.tool_execution_id for item in self.executions]
        if len(ids) != len(set(ids)):
            raise RuntimeError("TOOL_EXECUTION_DUPLICATE", "tool_execution_id is already present")
        if any(item.intent.mission_id != self.mission_id for item in self.executions):
            raise _error("execution Mission does not match state Mission")
        if tuple(item.intent.created_seq for item in self.executions) != tuple(sorted(item.intent.created_seq for item in self.executions)):
            raise _error("executions must be ordered by created_seq")

    def execution(self, tool_execution_id: str) -> ToolExecutionRecord | None:
        return next((item for item in self.executions if item.tool_execution_id == tool_execution_id), None)

    by_tool_execution_id = execution

    def by_idempotency_key(self, key: str) -> ToolExecutionRecord | None:
        return next((item for item in self.executions if item.intent.idempotency_key == key), None)

    @property
    def facts(self) -> tuple[ExecutionFact, ...]:
        return tuple(fact for item in self.executions for fact in item.facts)

    @property
    def evidence_records(self) -> tuple[EvidenceRecord, ...]:
        return tuple(evidence for item in self.executions for evidence in item.evidence)

    def to_dict(self) -> dict[str, Any]:
        return {"mission_id": self.mission_id, "executions": {item.tool_execution_id: item.to_dict() for item in self.executions}}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ToolExecutionState":
        if not isinstance(value, Mapping) or set(value) != {"mission_id", "executions"}:
            raise _error("Tool Execution state contains unknown or missing fields")
        executions = value["executions"]
        if not isinstance(executions, Mapping):
            raise _error("executions must be an object")
        return cls(value["mission_id"], tuple(ToolExecutionRecord.from_dict(item) for item in executions.values()))


@dataclass(frozen=True)
class ToolCall:
    tool_execution_id: str
    capability_id: str
    capability_version: int
    provider_binding_id: str
    provider_binding_digest: str
    context_cursor: EventCursor
    input_digest: str
    side_effect_policy: SideEffectPolicy | str
    input_reference: str | None = None
    redacted_input: Mapping[str, Any] = field(default_factory=dict)
    authorization_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_execution_id", _text(self.tool_execution_id, "tool_execution_id"))
        object.__setattr__(self, "capability_id", _text(self.capability_id, "capability_id"))
        object.__setattr__(self, "capability_version", _positive(self.capability_version, "capability_version"))
        object.__setattr__(self, "provider_binding_id", _text(self.provider_binding_id, "provider_binding_id"))
        object.__setattr__(self, "provider_binding_digest", _digest(self.provider_binding_digest, "provider_binding_digest"))
        object.__setattr__(self, "context_cursor", _cursor(self.context_cursor))
        object.__setattr__(self, "input_digest", _digest(self.input_digest, "input_digest"))
        object.__setattr__(self, "side_effect_policy", _enum(self.side_effect_policy, SideEffectPolicy, "side_effect_policy"))
        object.__setattr__(self, "input_reference", _optional_text(self.input_reference, "input_reference"))
        object.__setattr__(self, "authorization_id", _optional_text(self.authorization_id, "authorization_id"))
        object.__setattr__(self, "redacted_input", _mapping(self.redacted_input, "redacted_input"))


@dataclass(frozen=True)
class RehydrateToolExecutionRequest:
    mission_id: str
    cursor: EventCursor

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        object.__setattr__(self, "cursor", _cursor(self.cursor))
        if self.cursor.mission_id != self.mission_id:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "cursor must be bound to mission_id")


@dataclass(frozen=True)
class RehydratedToolExecution:
    mission_id: str
    cursor: EventCursor
    composed_state: ComposedRuntimeState
    tool_execution_state: ToolExecutionState
    state_digest: str

    def __post_init__(self) -> None:
        if self.cursor.mission_id != self.mission_id or self.composed_state.mission_id != self.mission_id or self.composed_state.seq != self.cursor.through_seq:
            raise RuntimeError("RUNTIME_REHYDRATION_CURSOR_MISMATCH", "rehydrated state does not match cursor")
        if not isinstance(self.tool_execution_state, ToolExecutionState):
            raise _error("tool_execution_state has an invalid type")
        object.__setattr__(self, "state_digest", _digest(self.state_digest, "state_digest"))


@dataclass(frozen=True)
class ToolExecutionOutcomeRequest:
    command_id: str
    idempotency_key: str | None
    mission_id: str
    runtime_session_id: str
    expected_seq: int
    actor: ActorRef
    correlation_id: str | None
    tool_execution_id: str
    observation: ToolObservation

    def __post_init__(self) -> None:
        for name in ("command_id", "mission_id", "runtime_session_id", "tool_execution_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "idempotency_key", _optional_text(self.idempotency_key, "idempotency_key"))
        object.__setattr__(self, "correlation_id", _optional_text(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "expected_seq", _non_negative(self.expected_seq, "expected_seq"))
        if not isinstance(self.actor, ActorRef) or not isinstance(self.observation, ToolObservation):
            raise _error("outcome contains an invalid actor or observation")


RecordToolExecutionOutcomeRequest = ToolExecutionOutcomeRequest


@dataclass(frozen=True)
class ReconcileToolExecutionRequest:
    command_id: str
    idempotency_key: str | None
    mission_id: str
    runtime_session_id: str
    expected_seq: int
    actor: ActorRef
    correlation_id: str | None
    tool_execution_id: str
    reconciliation_id: str
    observation: ToolObservation

    def __post_init__(self) -> None:
        for name in ("command_id", "mission_id", "runtime_session_id", "tool_execution_id", "reconciliation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "idempotency_key", _optional_text(self.idempotency_key, "idempotency_key"))
        object.__setattr__(self, "correlation_id", _optional_text(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "expected_seq", _non_negative(self.expected_seq, "expected_seq"))
        if not isinstance(self.actor, ActorRef) or not isinstance(self.observation, ToolObservation):
            raise _error("reconciliation contains an invalid actor or observation")


@dataclass(frozen=True)
class EvidenceInput:
    evidence_id: str
    tool_execution_id: str
    execution_fact_id: str
    evidence_type: str
    content_digest: str
    artifact_reference: str | None
    provenance: Mapping[str, Any]
    metadata: Mapping[str, Any]
    verification_method: str = "SHA-256"
    verified: bool = True

    def __post_init__(self) -> None:
        for name in ("evidence_id", "tool_execution_id", "execution_fact_id", "evidence_type", "verification_method"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "content_digest", _digest(self.content_digest, "content_digest"))
        object.__setattr__(self, "artifact_reference", _optional_text(self.artifact_reference, "artifact_reference"))
        object.__setattr__(self, "provenance", _mapping(self.provenance, "provenance"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        if not isinstance(self.verified, bool):
            raise _error("verified must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "tool_execution_id": self.tool_execution_id,
            "execution_fact_id": self.execution_fact_id,
            "evidence_type": self.evidence_type,
            "content_digest": self.content_digest,
            "artifact_reference": self.artifact_reference,
            "provenance": dict(self.provenance),
            "metadata": dict(self.metadata),
            "verification_method": self.verification_method,
            "verified": self.verified,
        }


@dataclass(frozen=True)
class RecordEvidenceRequest:
    command_id: str
    idempotency_key: str | None
    mission_id: str
    runtime_session_id: str
    expected_seq: int
    actor: ActorRef
    correlation_id: str | None
    evidence: EvidenceInput

    def __post_init__(self) -> None:
        for name in ("command_id", "mission_id", "runtime_session_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "idempotency_key", _optional_text(self.idempotency_key, "idempotency_key"))
        object.__setattr__(self, "correlation_id", _optional_text(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "expected_seq", _non_negative(self.expected_seq, "expected_seq"))
        if not isinstance(self.actor, ActorRef) or not isinstance(self.evidence, EvidenceInput):
            raise _error("evidence request contains an invalid actor or evidence")


@dataclass(frozen=True)
class LogicalToolExecutionResult:
    outcome: Literal["APPLIED", "DUPLICATE", "UNKNOWN"]
    command_result: CommandResult
    record: ToolExecutionRecord
    event_cursor: EventCursor

    def __post_init__(self) -> None:
        if self.outcome not in {"APPLIED", "DUPLICATE", "UNKNOWN"}:
            raise _error("invalid logical tool execution outcome")

    @property
    def execution(self) -> ToolExecutionRecord:
        return self.record

    @property
    def fact(self) -> ExecutionFact | None:
        return self.record.execution_fact


@dataclass(frozen=True)
class LogicalEvidenceResult:
    outcome: Literal["APPLIED", "DUPLICATE"]
    command_result: CommandResult
    evidence: EvidenceRecord
    event_cursor: EventCursor


__all__ = [
    "CANONICALIZATION_VERSION", "COMMAND_TYPES", "EVIDENCE_COMMAND", "EVIDENCE_EVENT", "EVENT_TYPES", "ExecutionFact",
    "EXTENSION_ID", "EXTENSION_VERSION", "LogicalEvidenceResult", "LogicalToolExecutionResult", "OUTCOME_COMMAND",
    "OUTCOME_EVENT", "PROJECTION_VERSION", "RECONCILE_COMMAND", "RECONCILE_EVENT", "REQUEST_COMMAND", "REQUEST_EVENT",
    "ReconcileToolExecutionRequest", "ReconciliationFact", "RehydrateToolExecutionRequest", "RehydratedToolExecution",
    "RecordEvidenceRequest", "RecordToolExecutionOutcomeRequest", "SideEffectPolicy", "SideEffectState", "ToolCall",
    "ToolExecutionIntent", "ToolExecutionObservation", "ToolExecutionOutcomeRequest", "ToolExecutionRecord", "ToolExecutionRequest",
    "ToolExecutionState", "ToolExecutionStatus", "ToolObservation", "EvidenceInput", "EvidenceRecord",
    "TOOL_EXECUTION_SCHEMA_VERSION",
]
