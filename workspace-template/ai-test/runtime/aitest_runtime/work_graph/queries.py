from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import (
    ComposedRuntimeState,
    RuntimeError,
    RuntimeService,
    RuntimeState,
    advance_shared_seq,
    canonical_sha256,
    reduce_composed,
)

from .contracts import (
    CANONICALIZATION_VERSION,
    EXTENSION_ID,
    PROJECTION_VERSION,
    WORK_GRAPH_SCHEMA_VERSION,
    SnapshotIndex,
    TaskAvailability,
    WorkGraphState,
)


@dataclass(frozen=True)
class ReadMeta:
    mission_id: str
    as_of_seq: int
    projection_version: int
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "as_of_seq": self.as_of_seq,
            "projection_version": self.projection_version,
            "source": self.source,
        }


@dataclass(frozen=True)
class WorkGraphRead:
    value: Any
    meta: ReadMeta

    def to_dict(self) -> dict[str, Any]:
        def encode(value: Any) -> Any:
            if hasattr(value, "to_dict"):
                return value.to_dict()
            if isinstance(value, tuple):
                return [encode(item) for item in value]
            if isinstance(value, list):
                return [encode(item) for item in value]
            if isinstance(value, Mapping):
                return {key: encode(item) for key, item in value.items()}
            return value

        value = encode(self.value)
        return {"value": value, "meta": self.meta.to_dict()}


class WorkGraphQueries:
    def __init__(self, service: RuntimeService) -> None:
        service.extension_registry.manifest(EXTENSION_ID)
        self._service = service

    def _full_state(self, mission_id: str, through_seq: int | None = None) -> tuple[WorkGraphState, int]:
        composed = self._service.replay_composed(mission_id, through_seq=through_seq)
        if composed.core_state.mission is None:
            raise RuntimeError("MISSION_NOT_FOUND", f"Mission not found: {mission_id}")
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, WorkGraphState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Work Graph state")
        return state, composed.seq

    @staticmethod
    def _read(mission_id: str, seq: int, value: Any, source: str = "REPLAY") -> WorkGraphRead:
        return WorkGraphRead(value, ReadMeta(mission_id, seq, PROJECTION_VERSION, source))

    def get_work_graph_state(self, mission_id: str, through_seq: int | None = None) -> WorkGraphRead:
        state, seq = self._full_state(mission_id, through_seq)
        return self._read(mission_id, seq, state)

    def get_plan(self, mission_id: str, plan_id: str, through_seq: int | None = None) -> WorkGraphRead:
        state, seq = self._full_state(mission_id, through_seq)
        plan = state.plan(plan_id)
        if plan is None:
            raise RuntimeError("PLAN_NOT_FOUND", f"Plan not found: {plan_id}")
        return self._read(mission_id, seq, plan)

    def list_plan_revisions(
        self,
        mission_id: str,
        plan_id: str,
        through_seq: int | None = None,
    ) -> WorkGraphRead:
        state, seq = self._full_state(mission_id, through_seq)
        if state.plan(plan_id) is None:
            raise RuntimeError("PLAN_NOT_FOUND", f"Plan not found: {plan_id}")
        revisions = tuple(item for item in state.revisions if item.plan_id == plan_id)
        return self._read(mission_id, seq, revisions)

    def get_task(self, mission_id: str, task_id: str, through_seq: int | None = None) -> WorkGraphRead:
        state, seq = self._full_state(mission_id, through_seq)
        task = state.task(task_id)
        if task is None:
            raise RuntimeError("TASK_NOT_FOUND", f"Task not found: {task_id}")
        return self._read(mission_id, seq, task)

    def list_tasks(
        self,
        mission_id: str,
        filters: Mapping[str, Any] | None = None,
        through_seq: int | None = None,
    ) -> WorkGraphRead:
        state, seq = self._full_state(mission_id, through_seq)
        values = list(state.tasks)
        filters = dict(filters or {})
        if "plan_id" in filters:
            values = [item for item in values if item.plan_id == filters["plan_id"]]
        if "plan_revision_id" in filters:
            values = [item for item in values if item.plan_revision_id == filters["plan_revision_id"]]
        if "lifecycle_state" in filters:
            values = [item for item in values if item.lifecycle_state.value == filters["lifecycle_state"]]
        if "availability" in filters:
            try:
                availability = TaskAvailability(str(filters["availability"]))
            except ValueError as exc:
                raise RuntimeError("COMMAND_SCHEMA_INVALID", "unsupported availability filter") from exc
            values = [item for item in values if state.task_availability(item.task_id) == availability]
        return self._read(mission_id, seq, tuple(values))

    def get_dependency_graph(
        self,
        mission_id: str,
        revision_id: str,
        through_seq: int | None = None,
    ) -> WorkGraphRead:
        state, seq = self._full_state(mission_id, through_seq)
        if state.revision(revision_id) is None:
            raise RuntimeError("REVISION_NOT_FOUND", f"Revision not found: {revision_id}")
        return self._read(mission_id, seq, state.revision_dependencies(revision_id))

    def get_snapshot(self, mission_id: str, snapshot_id: str) -> WorkGraphRead:
        state, seq = self._full_state(mission_id)
        snapshot = state.snapshot(snapshot_id)
        if snapshot is None:
            raise RuntimeError("SNAPSHOT_NOT_FOUND", f"Snapshot not found: {snapshot_id}")
        return self._read(mission_id, seq, snapshot)

    def _snapshot_base(
        self,
        mission_id: str,
        snapshot: SnapshotIndex,
        through_seq: int,
        scope: str,
        plan_id: str | None,
    ) -> ComposedRuntimeState | None:
        if len(self._service.extension_registry.manifests) != 1:
            return None
        if (
            snapshot.scope != scope
            or snapshot.plan_id != plan_id
            or snapshot.recorded_seq > through_seq
            or snapshot.work_graph_schema_version != WORK_GRAPH_SCHEMA_VERSION
            or snapshot.projection_version != PROJECTION_VERSION
            or snapshot.canonicalization_version != CANONICALIZATION_VERSION
            or canonical_sha256(snapshot.state_payload) != snapshot.payload_hash
        ):
            return None
        payload = snapshot.state_payload
        if (
            payload.get("mission_id") != mission_id
            or payload.get("as_of_seq") != snapshot.as_of_seq
            or payload.get("scope") != scope
            or payload.get("plan_id") != plan_id
        ):
            return None
        events = self._service.list_events(
            mission_id,
            after_seq=snapshot.as_of_seq,
            through_seq=through_seq,
        )
        snapshot_event = next(
            (
                event
                for event in events
                if event.seq == snapshot.recorded_seq
                and event.event_type == "snapshot.recorded.v1"
                and event.entity_id == snapshot.snapshot_id
            ),
            None,
        )
        if snapshot_event is None or dict(snapshot_event.payload) != {
            key: value for key, value in snapshot.to_dict().items() if key != "recorded_seq"
        }:
            return None
        try:
            core_state = RuntimeState.from_dict(payload["core_state"])
            work_graph_state = WorkGraphState.from_dict(payload["work_graph_state"])
            return ComposedRuntimeState(
                mission_id=mission_id,
                seq=snapshot.as_of_seq,
                core_state=core_state,
                extension_states={EXTENSION_ID: work_graph_state},
            )
        except (KeyError, TypeError, ValueError, RuntimeError):
            return None

    def _replay_snapshot_tail(
        self,
        composed: ComposedRuntimeState,
        mission_id: str,
        snapshot: SnapshotIndex,
        through_seq: int,
        scope: str,
        plan_id: str | None,
    ) -> ComposedRuntimeState:
        for event in self._service.list_events(
            mission_id,
            after_seq=snapshot.as_of_seq,
            through_seq=through_seq,
        ):
            if scope == "MISSION":
                composed = reduce_composed(composed, event, self._service.extension_registry)
                continue
            owner = self._service.extension_registry.event_owner(event.event_type)
            if owner == "CORE" or owner is None:
                composed = reduce_composed(composed, event, self._service.extension_registry)
                continue
            event_plan_id = event.payload.get("plan_id")
            is_mission_snapshot = (
                event.event_type == "snapshot.recorded.v1"
                and event.payload.get("scope") == "MISSION"
                and event_plan_id is None
            )
            if event_plan_id == plan_id:
                composed = reduce_composed(composed, event, self._service.extension_registry)
            elif is_mission_snapshot or isinstance(event_plan_id, str):
                core_state = advance_shared_seq(composed.core_state, event)
                composed = ComposedRuntimeState(
                    mission_id=composed.mission_id,
                    seq=event.seq,
                    core_state=core_state,
                    extension_states=composed.extension_states,
                )
            else:
                composed = reduce_composed(composed, event, self._service.extension_registry)
        return composed

    def read_work_graph(
        self,
        mission_id: str,
        scope: str = "MISSION",
        plan_id: str | None = None,
        through_seq: int | None = None,
        allow_snapshot_acceleration: bool = True,
    ) -> WorkGraphRead:
        if scope not in {"MISSION", "PLAN"} or (scope == "MISSION" and plan_id is not None):
            raise RuntimeError("SNAPSHOT_SCOPE_INVALID", "invalid Work Graph read scope")
        if scope == "PLAN" and (not isinstance(plan_id, str) or not plan_id.strip()):
            raise RuntimeError("SNAPSHOT_SCOPE_INVALID", "PLAN scope requires plan_id")
        target_seq = self._service.get_head_seq(mission_id) if through_seq is None else through_seq
        if allow_snapshot_acceleration:
            try:
                projected = self._service.get_extension_projection(EXTENSION_ID, mission_id)
                candidates = [
                    item
                    for item in projected.snapshots
                    if item.scope == scope
                    and item.plan_id == plan_id
                    and item.recorded_seq <= target_seq
                ]
                snapshot = max(candidates, key=lambda item: (item.as_of_seq, item.recorded_seq))
                composed = self._snapshot_base(
                    mission_id,
                    snapshot,
                    target_seq,
                    scope,
                    plan_id,
                )
                if composed is not None:
                    composed = self._replay_snapshot_tail(
                        composed,
                        mission_id,
                        snapshot,
                        target_seq,
                        scope,
                        plan_id,
                    )
                    value = composed.extension_state(EXTENSION_ID)
                    return self._read(mission_id, composed.seq, value, "SNAPSHOT_PLUS_TAIL")
            except (RuntimeError, ValueError, TypeError, KeyError, AttributeError):
                pass
        state, seq = self._full_state(mission_id, through_seq)
        value = state if scope == "MISSION" else state.plan_scope(str(plan_id))
        return self._read(mission_id, seq, value, "REPLAY")
