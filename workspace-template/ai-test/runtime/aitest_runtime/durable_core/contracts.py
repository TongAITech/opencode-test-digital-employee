from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, Mapping


class MissionStatus(str, Enum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class GoalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ACHIEVED = "ACHIEVED"
    CANCELLED = "CANCELLED"


class SessionStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


def _require_id(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ActorRef:
    type: str
    id: str

    def __post_init__(self) -> None:
        _require_id("actor.type", self.type)
        _require_id("actor.id", self.id)

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "id": self.id}


@dataclass(frozen=True)
class Mission:
    mission_id: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_id("mission_id", self.mission_id)


@dataclass(frozen=True)
class Goal:
    goal_id: str
    mission_id: str
    definition: Mapping[str, Any]
    revision: int = 1

    def __post_init__(self) -> None:
        _require_id("goal_id", self.goal_id)
        _require_id("mission_id", self.mission_id)
        if self.revision < 1:
            raise ValueError("revision must be positive")


@dataclass(frozen=True)
class Session:
    session_id: str
    mission_id: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_id("session_id", self.session_id)
        _require_id("mission_id", self.mission_id)


class RuntimeError(Exception):
    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        self.code = _require_id("error.code", code)
        self.message = str(message)
        self.details = dict(details or {})
        super().__init__(f"{self.code}: {self.message}")

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RuntimeError) and self.to_dict() == other.to_dict()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RuntimeError:
        return cls(str(value["code"]), str(value.get("message") or ""), value.get("details") or {})


@dataclass(frozen=True)
class CommandEnvelope:
    command_id: str
    type: str
    mission_id: str
    expected_seq: int
    actor: ActorRef
    payload: Mapping[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    idempotency_key: str | None = None
    correlation_id: str | None = None
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "type": self.type,
            "mission_id": self.mission_id,
            "session_id": self.session_id,
            "expected_seq": self.expected_seq,
            "actor": self.actor.to_dict(),
            "payload": dict(self.payload),
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class CommandResult:
    outcome: str
    command_id: str
    mission_id: str
    first_seq: int | None = None
    last_seq: int | None = None
    duplicate_of: str | None = None
    error: RuntimeError | None = None
    state_hash: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome in {"APPLIED", "DUPLICATE"}

    @property
    def error_code(self) -> str | None:
        return self.error.code if self.error else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "command_id": self.command_id,
            "mission_id": self.mission_id,
            "first_seq": self.first_seq,
            "last_seq": self.last_seq,
            "duplicate_of": self.duplicate_of,
            "error": self.error.to_dict() if self.error else None,
            "state_hash": self.state_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CommandResult:
        raw_error = value.get("error")
        return cls(
            outcome=str(value["outcome"]),
            command_id=str(value["command_id"]),
            mission_id=str(value["mission_id"]),
            first_seq=value.get("first_seq"),
            last_seq=value.get("last_seq"),
            duplicate_of=value.get("duplicate_of"),
            error=RuntimeError.from_dict(raw_error) if isinstance(raw_error, Mapping) else None,
            state_hash=value.get("state_hash"),
        )


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    mission_id: str
    seq: int
    event_type: str
    entity_type: str
    entity_id: str
    command_id: str
    correlation_id: str
    initiator_type: str
    initiator_id: str
    payload: Mapping[str, Any]
    created_at: str
    session_id: str | None = None
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "mission_id": self.mission_id,
            "session_id": self.session_id,
            "seq": self.seq,
            "event_type": self.event_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "command_id": self.command_id,
            "correlation_id": self.correlation_id,
            "initiator_type": self.initiator_type,
            "initiator_id": self.initiator_id,
            "payload": dict(self.payload),
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EventEnvelope:
        return cls(
            event_id=str(value["event_id"]),
            mission_id=str(value["mission_id"]),
            session_id=value.get("session_id"),
            seq=int(value["seq"]),
            event_type=str(value["event_type"]),
            entity_type=str(value["entity_type"]),
            entity_id=str(value["entity_id"]),
            command_id=str(value["command_id"]),
            correlation_id=str(value["correlation_id"]),
            initiator_type=str(value["initiator_type"]),
            initiator_id=str(value["initiator_id"]),
            payload=dict(value.get("payload") or {}),
            created_at=str(value["created_at"]),
            schema_version=int(value.get("schema_version", 1)),
        )


@dataclass(frozen=True)
class MissionState:
    mission_id: str
    status: MissionStatus
    active_goal_id: str | None
    created_at: str
    updated_at: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "status": self.status.value,
            "active_goal_id": self.active_goal_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class GoalState:
    goal_id: str
    mission_id: str
    revision: int
    status: GoalStatus
    definition: Mapping[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "mission_id": self.mission_id,
            "revision": self.revision,
            "status": self.status.value,
            "definition": dict(self.definition),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class SessionState:
    session_id: str
    mission_id: str
    status: SessionStatus
    created_at: str
    updated_at: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "mission_id": self.mission_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class RuntimeState:
    mission_id: str
    seq: int = 0
    mission: MissionState | None = None
    goals: tuple[GoalState, ...] = ()
    sessions: tuple[SessionState, ...] = ()

    def goal(self, goal_id: str) -> GoalState | None:
        return next((item for item in self.goals if item.goal_id == goal_id), None)

    def session(self, session_id: str) -> SessionState | None:
        return next((item for item in self.sessions if item.session_id == session_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "seq": self.seq,
            "mission": self.mission.to_dict() if self.mission else None,
            "goals": {item.goal_id: item.to_dict() for item in sorted(self.goals, key=lambda x: x.goal_id)},
            "sessions": {item.session_id: item.to_dict() for item in sorted(self.sessions, key=lambda x: x.session_id)},
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RuntimeState:
        raw_mission = value.get("mission")
        mission = None
        if isinstance(raw_mission, Mapping):
            mission = MissionState(
                mission_id=str(raw_mission["mission_id"]),
                status=MissionStatus(str(raw_mission["status"])),
                active_goal_id=raw_mission.get("active_goal_id"),
                created_at=str(raw_mission["created_at"]),
                updated_at=str(raw_mission["updated_at"]),
                attributes=dict(raw_mission.get("attributes") or {}),
            )
        goals = tuple(
            GoalState(
                goal_id=str(item["goal_id"]),
                mission_id=str(item["mission_id"]),
                revision=int(item["revision"]),
                status=GoalStatus(str(item["status"])),
                definition=dict(item.get("definition") or {}),
                created_at=str(item["created_at"]),
                updated_at=str(item["updated_at"]),
            )
            for item in (value.get("goals") or {}).values()
        )
        sessions = tuple(
            SessionState(
                session_id=str(item["session_id"]),
                mission_id=str(item["mission_id"]),
                status=SessionStatus(str(item["status"])),
                created_at=str(item["created_at"]),
                updated_at=str(item["updated_at"]),
                attributes=dict(item.get("attributes") or {}),
            )
            for item in (value.get("sessions") or {}).values()
        )
        return cls(str(value["mission_id"]), int(value.get("seq", 0)), mission, goals, sessions)


def _contributed_value(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _contributed_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_contributed_value(item) for item in value]
    if isinstance(value, list):
        return [_contributed_value(item) for item in value]
    return value


@dataclass(frozen=True)
class ComposedRuntimeState:
    mission_id: str
    seq: int
    core_state: RuntimeState
    extension_states: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_id("mission_id", self.mission_id)
        if self.seq < 0:
            raise ValueError("seq must be non-negative")
        if self.core_state.mission_id != self.mission_id or self.core_state.seq != self.seq:
            raise ValueError("core_state must share the composed mission_id and seq")

    def extension_state(self, extension_id: str) -> Any:
        if extension_id not in self.extension_states:
            raise RuntimeError("EXTENSION_NOT_REGISTERED", f"Extension not registered: {extension_id}")
        return self.extension_states[extension_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "seq": self.seq,
            "core_state": self.core_state.to_dict(),
            "extension_states": {
                extension_id: _contributed_value(self.extension_states[extension_id])
                for extension_id in sorted(self.extension_states)
            },
        }


MigrationApply = Callable[[Any], None]


@dataclass(frozen=True)
class MigrationStep:
    version: int
    checksum: str
    apply: MigrationApply

    def __post_init__(self) -> None:
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise RuntimeError("EXTENSION_MIGRATION_INVALID", "migration version must be a positive integer")
        if (
            not isinstance(self.checksum, str)
            or len(self.checksum) != 64
            or any(character not in "0123456789abcdef" for character in self.checksum.lower())
        ):
            raise RuntimeError("EXTENSION_MIGRATION_INVALID", "migration checksum must be a SHA-256 hex digest")
        if not callable(self.apply):
            raise RuntimeError("EXTENSION_MIGRATION_INVALID", "migration apply must be callable")


@dataclass(frozen=True)
class ExtensionManifest:
    extension_id: str
    extension_version: str
    command_types: frozenset[str]
    event_types: frozenset[str]
    state_contribution: Any
    command_contribution: Any
    reducer_contribution: Any
    projection_contribution: Any
    migration_contribution: Any

    def __post_init__(self) -> None:
        try:
            _require_id("extension_id", self.extension_id)
            _require_id("extension_version", self.extension_version)
        except ValueError as exc:
            raise RuntimeError("EXTENSION_MANIFEST_INVALID", str(exc)) from exc
        object.__setattr__(self, "command_types", frozenset(self.command_types))
        object.__setattr__(self, "event_types", frozenset(self.event_types))
        if not self.command_types or not self.event_types:
            raise RuntimeError(
                "EXTENSION_MANIFEST_INVALID",
                "extension command_types and event_types must be non-empty",
            )

    @property
    def extensionId(self) -> str:
        return self.extension_id

    @property
    def extensionVersion(self) -> str:
        return self.extension_version

    @property
    def ownedCommandTypes(self) -> frozenset[str]:
        return self.command_types

    @property
    def ownedEventTypes(self) -> frozenset[str]:
        return self.event_types


class ExtensionRegistry:
    _CORE_PROJECTION_TABLES = {
        "commands",
        "events",
        "schema_migrations",
        "mission_projection",
        "goal_projection",
        "session_projection",
    }

    def __init__(
        self,
        manifests: Iterable[ExtensionManifest] = (),
        *,
        core_command_types: Iterable[str] | None = None,
        core_event_types: Iterable[str] | None = None,
    ) -> None:
        if core_command_types is None or core_event_types is None:
            from .handlers import SUPPORTED_COMMANDS
            from .reducer import SUPPORTED_EVENTS

            core_command_types = SUPPORTED_COMMANDS if core_command_types is None else core_command_types
            core_event_types = SUPPORTED_EVENTS if core_event_types is None else core_event_types
        self._core_command_types = frozenset(core_command_types)
        self._core_event_types = frozenset(core_event_types)
        by_id: dict[str, ExtensionManifest] = {}
        command_owners: dict[str, ExtensionManifest] = {}
        event_owners: dict[str, ExtensionManifest] = {}
        table_owners: dict[str, ExtensionManifest] = {}
        for manifest in tuple(manifests):
            if not isinstance(manifest, ExtensionManifest):
                raise RuntimeError("EXTENSION_MANIFEST_INVALID", "extensions must contain ExtensionManifest values")
            if manifest.extension_id in by_id:
                raise RuntimeError("EXTENSION_ID_CONFLICT", f"duplicate extension_id: {manifest.extension_id}")
            self._validate_manifest(manifest)
            by_id[manifest.extension_id] = manifest
            for command_type in manifest.command_types:
                if command_type in self._core_command_types or command_type in command_owners:
                    raise RuntimeError("COMMAND_TYPE_OWNER_CONFLICT", f"command type already owned: {command_type}")
                command_owners[command_type] = manifest
            for event_type in manifest.event_types:
                if event_type in self._core_event_types or event_type in event_owners:
                    raise RuntimeError("EVENT_TYPE_OWNER_CONFLICT", f"event type already owned: {event_type}")
                event_owners[event_type] = manifest
            for table in self._projection_tables(manifest):
                if table in self._CORE_PROJECTION_TABLES:
                    raise RuntimeError("PROJECTION_TABLE_FORBIDDEN", f"extension may not own core table: {table}")
                if table == "extension_migrations" or table in table_owners:
                    raise RuntimeError("PROJECTION_TABLE_OWNER_CONFLICT", f"projection table already owned: {table}")
                table_owners[table] = manifest
        self._manifests = tuple(by_id[key] for key in sorted(by_id))
        self._by_id = by_id
        self._command_owners = command_owners
        self._event_owners = event_owners

    @staticmethod
    def _projection_tables(manifest: ExtensionManifest) -> frozenset[str]:
        raw = getattr(manifest.projection_contribution, "projection_tables", None)
        if raw is None:
            raise RuntimeError("EXTENSION_MANIFEST_INVALID", "projection contribution must declare projection_tables")
        tables = frozenset(raw)
        if not tables or any(
            not isinstance(table, str) or not table.strip() or not table.isidentifier()
            for table in tables
        ):
            raise RuntimeError(
                "EXTENSION_MANIFEST_INVALID",
                "projection_tables must contain safe identifier names",
            )
        return tables

    @staticmethod
    def _migration_steps(manifest: ExtensionManifest) -> tuple[MigrationStep, ...]:
        contribution = manifest.migration_contribution
        if getattr(contribution, "extension_id", manifest.extension_id) != manifest.extension_id:
            raise RuntimeError("EXTENSION_MIGRATION_INVALID", "migration contribution extension_id mismatch")
        steps = tuple(getattr(contribution, "migrations", ()))
        if not steps:
            raise RuntimeError("EXTENSION_MIGRATION_INVALID", "extension migrations must be non-empty")
        if any(not isinstance(step, MigrationStep) for step in steps):
            raise RuntimeError("EXTENSION_MIGRATION_INVALID", "migrations must contain MigrationStep values")
        if [step.version for step in steps] != list(range(1, len(steps) + 1)):
            raise RuntimeError("EXTENSION_MIGRATION_INVALID", "migration versions must be continuous from 1")
        return steps

    def _validate_manifest(self, manifest: ExtensionManifest) -> None:
        for name, contribution, methods in (
            ("state", manifest.state_contribution, ("initial_state", "encode", "decode", "hash")),
            ("command", manifest.command_contribution, ("handle",)),
            ("reducer", manifest.reducer_contribution, ("reduce",)),
            ("projection", manifest.projection_contribution, ("apply", "read", "clear", "verify")),
        ):
            if contribution is None or any(not callable(getattr(contribution, method, None)) for method in methods):
                raise RuntimeError("EXTENSION_MANIFEST_INVALID", f"invalid {name} contribution")
        self._projection_tables(manifest)
        self._migration_steps(manifest)
        for command_type in manifest.command_types:
            if not isinstance(command_type, str) or not command_type.strip():
                raise RuntimeError("EXTENSION_MANIFEST_INVALID", "command type must be non-empty")
        for event_type in manifest.event_types:
            if not isinstance(event_type, str) or not event_type.strip() or "." not in event_type:
                raise RuntimeError("EVENT_NAMESPACE_INVALID", f"invalid extension event namespace: {event_type}")
            if event_type.startswith(("mission.", "goal.", "session.")):
                raise RuntimeError("EVENT_NAMESPACE_INVALID", f"core event namespace is reserved: {event_type}")

    @property
    def manifests(self) -> tuple[ExtensionManifest, ...]:
        return self._manifests

    @property
    def enabled(self) -> bool:
        return bool(self._manifests)

    def manifest(self, extension_id: str) -> ExtensionManifest:
        manifest = self._by_id.get(extension_id)
        if manifest is None:
            raise RuntimeError("EXTENSION_NOT_REGISTERED", f"Extension not registered: {extension_id}")
        return manifest

    def command_owner(self, command_type: str) -> str | ExtensionManifest | None:
        if command_type in self._core_command_types:
            return "CORE"
        return self._command_owners.get(command_type)

    def event_owner(self, event_type: str) -> str | ExtensionManifest | None:
        if event_type in self._core_event_types:
            return "CORE"
        return self._event_owners.get(event_type)

    def migration_steps(self, manifest: ExtensionManifest) -> tuple[MigrationStep, ...]:
        return self._migration_steps(manifest)
