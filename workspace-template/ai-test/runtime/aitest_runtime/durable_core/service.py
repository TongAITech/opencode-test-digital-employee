from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from .canonical import Clock, SystemClock
from .command_bus import CommandBus, FailureInjector
from .contracts import (
    CommandEnvelope,
    CommandResult,
    ComposedRuntimeState,
    EventEnvelope,
    ExtensionManifest,
    ExtensionRegistry,
    RuntimeError,
    RuntimeState,
    SubjectRef,
    SubjectState,
)
from .event_store import get_head_seq as store_head_seq
from .event_store import list_events as store_list_events
from .projections import (
    _rebuild_composed_projections,
    _rebuild_projections,
    replay_composed_state,
    replay_state,
    read_extension_projection,
    verify_composed_projection,
    verify_projection as verify_materialized,
)
from .schema import connect, immediate_transaction, initialize, initialize_extensions


class RuntimeService:
    def __init__(
        self,
        db_path: str | Path,
        clock: Clock | None = None,
        failure_injector: FailureInjector | None = None,
        extensions: Iterable[ExtensionManifest] = (),
    ) -> None:
        if db_path is None or not str(db_path).strip():
            raise ValueError("db_path is required")
        self._db_path = Path(db_path)
        self._failure_injector = failure_injector
        self._extension_registry = ExtensionRegistry(tuple(extensions))
        initialize(self._db_path)
        if self._extension_registry.enabled:
            initialize_extensions(
                self._db_path,
                self._extension_registry,
                (clock or SystemClock()).now(),
            )
        self._command_bus = CommandBus(
            self._db_path,
            clock=clock,
            failure_injector=failure_injector,
            extension_registry=self._extension_registry,
        )

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def extension_registry(self) -> ExtensionRegistry:
        return self._extension_registry

    def execute(self, command: CommandEnvelope | Mapping[str, Any]) -> CommandResult:
        return self._command_bus.execute(command)

    def replay(self, mission_id: str, through_seq: int | None = None) -> RuntimeState:
        conn = connect(self._db_path)
        try:
            if self._extension_registry.enabled:
                return replay_composed_state(
                    conn,
                    mission_id,
                    self._extension_registry,
                    through_seq=through_seq,
                ).core_state
            return replay_state(conn, mission_id, through_seq=through_seq)
        finally:
            conn.close()

    def replay_composed(self, mission_id: str, through_seq: int | None = None) -> ComposedRuntimeState:
        conn = connect(self._db_path)
        try:
            return replay_composed_state(
                conn,
                mission_id,
                self._extension_registry,
                through_seq=through_seq,
            )
        finally:
            conn.close()

    def get_composed_state(self, mission_id: str) -> ComposedRuntimeState:
        state = self.replay_composed(mission_id)
        if state.core_state.mission is None:
            raise RuntimeError("MISSION_NOT_FOUND", f"Mission not found: {mission_id}")
        return state

    def get_subject_state(self, subject: SubjectRef) -> SubjectState:
        """Typed accessor derives identity from replay, never from requested kind."""
        from .subjects import root_owner_for_state
        if not isinstance(subject, SubjectRef):
            raise RuntimeError("SUBJECT_REF_REQUIRED", "typed SubjectRef is required")
        composed = self.replay_composed(subject.subject_id)
        actual = composed.subject
        if actual is None and composed.core_state.mission is not None:
            actual = SubjectRef("MISSION", subject.subject_id)
        if actual is None:
            raise RuntimeError("ROOT_NOT_FOUND", "subject has no immutable creation event")
        if actual != subject:
            raise RuntimeError("ROOT_REFERENCE_MISMATCH", "requested subject kind differs from durable identity")
        owner = root_owner_for_state(composed, self._extension_registry)
        if owner is None:
            return SubjectState(subject, composed.seq, 1, "CORE", composed.core_state, composed.extension_states)
        manifest, root = owner
        return SubjectState(subject, composed.seq, root.version, manifest.extension_id,
                            composed.extension_state(manifest.extension_id), composed.extension_states)

    def assert_writable_compatible(self) -> None:
        """Guard dispatch/rebuild; scoped supported reads remain independently usable."""
        from .subjects import assert_runtime_compatible
        conn = connect(self._db_path)
        try:
            assert_runtime_compatible(conn, self._extension_registry)
        finally:
            conn.close()

    def get_extension_projection(self, extension_id: str, mission_id: str) -> Any:
        manifest = self._extension_registry.manifest(extension_id)
        conn = connect(self._db_path)
        try:
            return read_extension_projection(conn, manifest, mission_id)
        finally:
            conn.close()

    def get_state(self, mission_id: str) -> RuntimeState:
        state = self.replay(mission_id)
        if state.mission is None:
            raise RuntimeError("MISSION_NOT_FOUND", f"Mission not found: {mission_id}")
        return state

    def get_head_seq(self, mission_id: str) -> int:
        conn = connect(self._db_path)
        try:
            return store_head_seq(conn, mission_id)
        finally:
            conn.close()

    def list_events(
        self,
        mission_id: str,
        after_seq: int = 0,
        through_seq: int | None = None,
    ) -> list[EventEnvelope]:
        conn = connect(self._db_path)
        try:
            return store_list_events(conn, mission_id, after_seq=after_seq, through_seq=through_seq)
        finally:
            conn.close()

    def verify_projection(self, mission_id: str) -> dict[str, object]:
        conn = connect(self._db_path)
        try:
            if self._extension_registry.enabled:
                return verify_composed_projection(conn, mission_id, self._extension_registry)
            return verify_materialized(conn, mission_id)
        finally:
            conn.close()

    def rebuild_projections(self, mission_id: str | None = None) -> dict[str, object]:
        conn = connect(self._db_path)
        try:
            with immediate_transaction(conn):
                if self._extension_registry.enabled:
                    return _rebuild_composed_projections(conn, self._extension_registry, mission_id, self._failure_injector)
                from .subjects import assert_runtime_compatible
                assert_runtime_compatible(conn, self._extension_registry)
                return _rebuild_projections(conn, mission_id)
        finally:
            conn.close()
