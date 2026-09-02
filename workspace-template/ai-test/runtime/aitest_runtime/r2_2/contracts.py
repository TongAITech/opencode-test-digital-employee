"""Frozen R2.2 Mission Intake and Goal definition contracts.

R2.2 owns request normalization and orchestration only.  Mission, Goal, Event,
and projection state remain owned by :mod:`aitest_runtime.durable_core`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from aitest_runtime.durable_core import RuntimeError as DurableRuntimeError
from aitest_runtime.durable_core import canonical_json
from aitest_runtime.r2_1.contracts import validate_secret_boundary


CONTRACT_VERSION = "R2.2_MISSION_INTAKE_V1"
R2_2_CONTRACT_VERSION = CONTRACT_VERSION
MISSION_INTAKE_CONTRACT_VERSION = CONTRACT_VERSION
GOAL_DEFINITION_CONTRACT_VERSION = "R2.2_GOAL_DEFINITION_V1"
SCHEMA_VERSION = 1
GOAL_DEFINITION_SCHEMA_VERSION = 1

OP_CREATE = "CREATE"
OP_REVISE = "REVISE"
OPERATION_CREATE = OP_CREATE
OPERATION_REVISE = OP_REVISE
CREATE = OP_CREATE
REVISE = OP_REVISE
OPERATIONS = frozenset({OP_CREATE, OP_REVISE})

SCOPE_MODE_EXPLICIT_SET = "EXPLICIT_SET"
SCOPE_EXPLICIT_SET = SCOPE_MODE_EXPLICIT_SET
EXPLICIT_SET = SCOPE_MODE_EXPLICIT_SET
SCOPE_MODES = frozenset({SCOPE_MODE_EXPLICIT_SET})

SOURCE_KINDS = frozenset({"USER", "CONTROL_PLANE", "GOVERNED_EXTERNAL_SOURCE"})

_SCOPE_FIELDS = frozenset(
    {
        "mode",
        "scope_mode",
        "scope_type",
        "type",
        "project_id",
        "release",
        "release_id",
        "release_ref",
        "version",
        "version_id",
        "version_ref",
        "requirements",
        "requirement_ids",
        "ssts",
        "sst_ids",
        "systems",
        "system_ids",
        "repositories",
        "repository",
        "repository_id",
        "repository_identity",
        "repository_ids",
        "repository_path",
        "repository_ref",
        "path",
        "ref",
        "branch",
        "branch_ref",
        "commit",
        "commit_sha",
        "commit_range",
        "range",
        "environment",
        "environment_id",
        "environment_ref",
        "include",
        "exclude",
    }
)
_SCOPE_DESCRIPTOR_FIELDS = frozenset(
    {
        "id",
        "identity",
        "name",
        "type",
        "kind",
        "ref",
        "path",
        "repository_id",
        "repository_identity",
        "repository_path",
        "repository_ref",
        "branch",
        "branch_ref",
        "commit",
        "commit_sha",
        "commit_range",
        "range",
        "version",
        "version_id",
        "release",
        "release_id",
        "release_ref",
        "requirement_id",
        "requirement",
        "sst_id",
        "sst",
        "system_id",
        "system",
        "environment",
        "environment_id",
        "environment_ref",
        "source_ref",
        "source_digest",
        "observed_at",
        "valid_until",
        "repository",
        "version_ref",
        "include",
        "exclude",
        "metadata",
        "attributes",
    }
)


class MissionIntakeError(DurableRuntimeError):
    """A fail-closed R2.2 contract or orchestration error."""


class IdempotencyConflict(MissionIntakeError):
    def __init__(self, intake_id: str, message: str | None = None):
        super().__init__(
            "IDEMPOTENCY_CONFLICT",
            message or f"intake_id already exists with a different normalized digest: {intake_id}",
            {"intake_id": intake_id},
        )


R2_2Error = MissionIntakeError


def _error(message: str, *, code: str = "MISSION_INTAKE_SCHEMA_INVALID") -> MissionIntakeError:
    return MissionIntakeError(code, message)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _error(f"{name} must be a positive integer")
    return value


def _digest(value: Any, name: str) -> str:
    result = _text(value, name).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise _error(f"{name} must be a lowercase SHA-256 digest")
    return result


def _normalized_digest(value: Any, name: str) -> str:
    """Accept a normalizer-produced SHA-256 or a non-empty caller identity."""
    result = _text(value, name)
    if len(result) == 64 and all(character in "0123456789abcdefABCDEF" for character in result):
        return result.lower()
    return result


def _plain_json(value: Any, name: str) -> Any:
    """Validate that a value can be safely persisted in a command payload."""
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


def _mapping(value: Any, name: str, *, optional: bool = False) -> dict[str, Any]:
    if value is None and optional:
        return {}
    if not isinstance(value, Mapping):
        raise _error(f"{name} must be an object")
    return _plain_json(dict(value), name)


def _normalize_scope_value(value: Any, name: str, *, descriptor: bool = False) -> Any:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        raw = dict(value)
        if descriptor:
            unknown = set(raw) - _SCOPE_DESCRIPTOR_FIELDS
            if unknown:
                raise _error(
                    f"{name} contains unsupported fields: {sorted(unknown)}",
                    code="REQUEST_INVALID",
                )
        return {
            str(key): _normalize_scope_value(raw[key], f"{name}.{key}", descriptor=descriptor)
            for key in sorted(raw)
        }
    if isinstance(value, (list, tuple)):
        normalized = [_normalize_scope_value(item, f"{name}[{index}]", descriptor=descriptor) for index, item in enumerate(value)]
        unique: list[Any] = []
        seen: set[str] = set()
        for item in normalized:
            marker = canonical_json(item)
            if marker not in seen:
                seen.add(marker)
                unique.append(item)
        return sorted(unique, key=canonical_json)
    return _plain_json(value, name)


def _unique_strings(values: list[Any], name: str) -> list[str]:
    result: list[str] = []
    for item in values:
        text = _text(item, name)
        if text not in result:
            result.append(text)
    return result


def normalize_scope(value: Any) -> dict[str, Any]:
    """Normalize the only permitted R2.2 scope mode: ``EXPLICIT_SET``."""
    raw = _mapping(value, "scope")
    unknown = set(raw) - _SCOPE_FIELDS
    if unknown:
        raise _error(f"scope contains unsupported fields: {sorted(unknown)}", code="REQUEST_INVALID")
    mode = str(raw.get("mode", raw.get("scope_mode", raw.get("scope_type", raw.get("type", ""))))).upper()
    if mode != SCOPE_MODE_EXPLICIT_SET:
        raise _error("scope.mode must be EXPLICIT_SET", code="SCOPE_MODE_NOT_ALLOWED")

    result: dict[str, Any] = {"mode": SCOPE_MODE_EXPLICIT_SET}
    for key in sorted(raw):
        if key in {"mode", "scope_mode", "scope_type", "type"}:
            continue
        descriptor = key in {"release", "version", "requirements", "ssts", "systems", "repositories", "repository", "environment"}
        result[key] = _normalize_scope_value(raw[key], f"scope.{key}", descriptor=descriptor)
    return result


@dataclass(frozen=True)
class SourceDescriptor:
    kind: str
    source_ref: str
    source_digest: str
    observed_at: str
    valid_until: str | None
    source_precedence: Any

    def __post_init__(self) -> None:
        kind = _text(self.kind, "source.kind").upper()
        if kind not in SOURCE_KINDS:
            raise _error("source.kind must be USER, CONTROL_PLANE, or GOVERNED_EXTERNAL_SOURCE", code="REQUEST_INVALID")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "source_ref", _text(self.source_ref, "source.source_ref"))
        object.__setattr__(self, "source_digest", _digest(self.source_digest, "source.source_digest"))
        object.__setattr__(self, "observed_at", _text(self.observed_at, "source.observed_at"))
        object.__setattr__(self, "valid_until", _optional_text(self.valid_until, "source.valid_until"))
        object.__setattr__(self, "source_precedence", _plain_json(self.source_precedence, "source.source_precedence"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source_ref": self.source_ref,
            "source_digest": self.source_digest,
            "observed_at": self.observed_at,
            "valid_until": self.valid_until,
            "source_precedence": self.source_precedence,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceDescriptor":
        if not isinstance(value, Mapping):
            raise _error("source must be an object", code="REQUEST_INVALID")
        required = {"kind", "source_ref", "source_digest", "observed_at", "valid_until", "source_precedence"}
        missing = required - set(value)
        unknown = set(value) - required
        if missing or unknown:
            raise _error(
                f"source fields must exactly match V1 (missing={sorted(missing)}, unknown={sorted(unknown)})",
                code="REQUEST_INVALID",
            )
        return cls(**dict(value))


def normalize_actor(value: Any) -> dict[str, str]:
    if value is None:
        return {"type": "SYSTEM", "id": "r2.2-mission-intake"}
    raw = _mapping(value, "actor")
    return {
        "type": _text(raw.get("type"), "actor.type"),
        "id": _text(raw.get("id"), "actor.id"),
    }


@dataclass(frozen=True)
class GoalDefinition:
    """The V1 definition written into the durable Goal Event."""

    goal: Mapping[str, Any]
    scope: Mapping[str, Any]
    scope_status: str
    scope_reason: str
    provenance: Mapping[str, Any]
    resolution_refs: Mapping[str, Any]
    execution_scope: Mapping[str, Any]
    scope_digest: str
    intake: Mapping[str, Any]
    intake_id: str | None = None
    normalized_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.goal, Mapping):
            raise _error("goal must be an object")
        if not isinstance(self.scope, Mapping):
            raise _error("scope must be an object")
        status = _text(self.scope_status, "scope_status").upper()
        reason = _text(self.scope_reason, "scope_reason")
        if not isinstance(self.provenance, Mapping) or not isinstance(self.resolution_refs, Mapping):
            raise _error("Goal.definition provenance and resolution_refs must be objects")
        if not isinstance(self.execution_scope, Mapping) or not isinstance(self.intake, Mapping):
            raise _error("Goal.definition execution_scope and intake must be objects")
        object.__setattr__(self, "goal", _plain_json(dict(self.goal), "goal"))
        object.__setattr__(self, "scope", _plain_json(dict(self.scope), "scope"))
        object.__setattr__(self, "scope_status", status)
        object.__setattr__(self, "scope_reason", reason)
        object.__setattr__(self, "provenance", _plain_json(dict(self.provenance), "provenance"))
        object.__setattr__(self, "resolution_refs", _plain_json(dict(self.resolution_refs), "resolution_refs"))
        object.__setattr__(self, "execution_scope", _plain_json(dict(self.execution_scope), "execution_scope"))
        object.__setattr__(self, "scope_digest", _digest(self.scope_digest, "scope_digest"))
        object.__setattr__(self, "intake", _plain_json(dict(self.intake), "intake"))
        if self.intake_id is not None:
            object.__setattr__(self, "intake_id", _text(self.intake_id, "intake_id"))
        if self.normalized_digest:
            object.__setattr__(self, "normalized_digest", _normalized_digest(self.normalized_digest, "normalized_digest"))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            **dict(self.goal),
            "contract_version": GOAL_DEFINITION_CONTRACT_VERSION,
            "schema_version": GOAL_DEFINITION_SCHEMA_VERSION,
            "scope": dict(self.scope),
            "scope_status": self.scope_status,
            "scope_reason": self.scope_reason,
            "provenance": dict(self.provenance),
            "resolution_refs": dict(self.resolution_refs),
            "execution_scope": dict(self.execution_scope),
            "scope_digest": self.scope_digest,
            "intake": dict(self.intake),
        }
        if self.intake_id is not None:
            result["intake_id"] = self.intake_id
        if self.normalized_digest is not None:
            result["normalized_digest"] = self.normalized_digest
        return result

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GoalDefinition":
        if not isinstance(value, Mapping):
            raise _error("Goal.definition must be an object")
        raw = dict(value)
        contract = raw.get("contract_version", GOAL_DEFINITION_CONTRACT_VERSION)
        if contract != GOAL_DEFINITION_CONTRACT_VERSION:
            raise _error("unsupported Goal.definition contract_version")
        version = raw.get("schema_version", GOAL_DEFINITION_SCHEMA_VERSION)
        if version != GOAL_DEFINITION_SCHEMA_VERSION:
            raise _error("unsupported Goal.definition schema_version")
        required = {
            "scope",
            "scope_status",
            "scope_reason",
            "provenance",
            "resolution_refs",
            "execution_scope",
            "scope_digest",
            "intake",
        }
        missing = required - set(raw)
        if missing:
            raise _error(f"Goal.definition is missing fields: {sorted(missing)}")
        goal = {
            key: item
            for key, item in raw.items()
            if key not in required | {"contract_version", "schema_version", "intake_id", "normalized_digest"}
        }
        return cls(
            goal=goal,
            scope=raw["scope"],
            scope_status=raw["scope_status"],
            scope_reason=raw["scope_reason"],
            provenance=raw["provenance"],
            resolution_refs=raw["resolution_refs"],
            execution_scope=raw["execution_scope"],
            scope_digest=raw["scope_digest"],
            intake=raw["intake"],
            intake_id=raw.get("intake_id"),
            normalized_digest=raw.get("normalized_digest"),
        )


@dataclass(frozen=True)
class MissionIntakeRequest:
    """Normalized V1 request accepted by the R2.2 orchestrator."""

    intake_id: str
    operation: Literal["CREATE", "REVISE"]
    scope: Mapping[str, Any]
    goal: Mapping[str, Any]
    source: Mapping[str, Any]
    actor: Mapping[str, str] = field(default_factory=lambda: {"type": "SYSTEM", "id": "r2.2-mission-intake"})
    mission_id: str | None = None
    goal_id: str | None = None
    base_revision: int | None = None
    resolution_request: Mapping[str, Any] = field(default_factory=dict)
    normalized_digest: str = field(default="", init=False, repr=False)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "intake_id", _text(self.intake_id, "intake_id"))
        operation = _text(self.operation, "operation").upper()
        if operation not in OPERATIONS:
            raise _error("operation must be CREATE or REVISE", code="OPERATION_NOT_ALLOWED")
        object.__setattr__(self, "operation", operation)
        if not isinstance(self.scope, Mapping):
            raise _error("scope must be an object")
        if not isinstance(self.goal, Mapping) or not self.goal:
            raise _error("goal must be a non-empty object")
        if self.actor is None:
            object.__setattr__(self, "actor", normalize_actor(None))
        elif not isinstance(self.actor, Mapping):
            raise _error("actor must be an object")
        if self.mission_id is not None:
            object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        if self.goal_id is not None:
            object.__setattr__(self, "goal_id", _text(self.goal_id, "goal_id"))
        if operation == OP_REVISE and self.mission_id is None:
            raise _error("mission_id is required for REVISE", code="IDENTITY_INVALID")
        if operation == OP_CREATE and self.base_revision is not None:
            raise _error("base_revision is not allowed for CREATE")
        if operation == OP_REVISE:
            if self.base_revision is None:
                raise _error("base_revision is required for REVISE", code="BASE_REVISION_INVALID")
            _positive_int(self.base_revision, "base_revision")
        elif self.base_revision is not None:
            _positive_int(self.base_revision, "base_revision")
        if self.schema_version != SCHEMA_VERSION:
            raise _error("unsupported MissionIntakeRequest schema_version")
        object.__setattr__(self, "scope", _plain_json(dict(self.scope), "scope"))
        object.__setattr__(self, "goal", _plain_json(dict(self.goal), "goal"))
        source = SourceDescriptor.from_mapping(self.source)
        object.__setattr__(self, "source", source.to_dict())
        object.__setattr__(self, "actor", normalize_actor(self.actor))
        object.__setattr__(self, "resolution_request", _plain_json(dict(self.resolution_request), "resolution_request"))
        if self.normalized_digest:
            object.__setattr__(self, "normalized_digest", _normalized_digest(self.normalized_digest, "normalized_digest"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "MissionIntakeRequest") -> "MissionIntakeRequest":
        if isinstance(value, cls):
            validate_secret_boundary(value.to_mapping(include_digest=False))
            return value
        if not isinstance(value, Mapping):
            raise _error("MissionIntakeRequest must be an object")
        raw = dict(value)
        validate_secret_boundary(raw)
        if "normalized_digest" in raw:
            raise _error("normalized_digest is computed internally", code="REQUEST_INVALID")
        operation = raw.get("operation", raw.get("op"))
        scope = raw["scope"] if "scope" in raw else raw.get("declared_scope")
        goal = raw.get("goal", raw.get("goal_definition", raw.get("definition")))
        resolution = _mapping(raw.get("resolution_request", raw.get("r2_1_request", {})), "resolution_request", optional=True)
        for key in (
            "resolution_id",
            "facts",
            "runtime_facts",
            "capabilities",
            "capability_declarations",
            "source_precedence",
            "valid_until",
            "context_refs",
            "declared_inputs",
        ):
            if key in raw and key not in resolution:
                resolution[key] = raw[key]
        return cls(
            intake_id=raw.get("intake_id"),
            operation=operation,
            scope=normalize_scope(scope),
            goal=_mapping(goal, "goal"),
            source=raw.get("source", raw.get("source_manifest")),
            actor=normalize_actor(raw.get("actor", raw.get("created_by"))),
            mission_id=raw.get("mission_id"),
            goal_id=raw.get("goal_id"),
            base_revision=raw.get("base_revision"),
            resolution_request=resolution,
            schema_version=raw.get("schema_version", SCHEMA_VERSION),
        )

    def to_mapping(self, *, include_digest: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "intake_id": self.intake_id,
            "operation": self.operation,
            "mission_id": self.mission_id,
            "goal_id": self.goal_id,
            "base_revision": self.base_revision,
            "actor": dict(self.actor),
            "scope": dict(self.scope),
            "goal": dict(self.goal),
            "source": dict(self.source),
            "resolution_request": dict(self.resolution_request),
        }
        if include_digest and self.normalized_digest is not None:
            result["normalized_digest"] = self.normalized_digest
        return result

    def with_normalized_digest(self, digest: str) -> "MissionIntakeRequest":
        if not digest:
            raise _error("internal normalized digest must be non-empty")
        result = object.__new__(type(self))
        for name in self.__dataclass_fields__:
            object.__setattr__(result, name, getattr(self, name))
        object.__setattr__(result, "normalized_digest", digest)
        return result


def validate_request_secrets(value: Mapping[str, Any]) -> None:
    try:
        validate_secret_boundary(value)
    except DurableRuntimeError:
        raise
    except Exception as exc:  # pragma: no cover - defensive boundary conversion
        raise _error(str(exc), code="SECRET_VALUE_NOT_ALLOWED") from exc


def ensure_canonical_json(value: Any, name: str = "value") -> Any:
    try:
        canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise _error(f"{name} must contain canonical JSON values") from exc
    return value


MissionIntakeRequestV1 = MissionIntakeRequest
GoalDefinitionV1 = GoalDefinition


__all__ = [
    "CONTRACT_VERSION",
    "R2_2_CONTRACT_VERSION",
    "MISSION_INTAKE_CONTRACT_VERSION",
    "GOAL_DEFINITION_CONTRACT_VERSION",
    "SCHEMA_VERSION",
    "GOAL_DEFINITION_SCHEMA_VERSION",
    "OP_CREATE",
    "OP_REVISE",
    "OPERATION_CREATE",
    "OPERATION_REVISE",
    "CREATE",
    "REVISE",
    "OPERATIONS",
    "SCOPE_MODE_EXPLICIT_SET",
    "SCOPE_EXPLICIT_SET",
    "EXPLICIT_SET",
    "SCOPE_MODES",
    "MissionIntakeError",
    "R2_2Error",
    "IdempotencyConflict",
    "SOURCE_KINDS",
    "SourceDescriptor",
    "GoalDefinition",
    "GoalDefinitionV1",
    "MissionIntakeRequest",
    "MissionIntakeRequestV1",
    "normalize_scope",
    "normalize_actor",
    "validate_request_secrets",
    "ensure_canonical_json",
]
