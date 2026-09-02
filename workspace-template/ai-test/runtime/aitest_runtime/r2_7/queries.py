"""On-demand fixed-cursor Runtime Operations aggregation."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from .contracts import (
    CURRENT,
    CURRENT_OBSERVATION,
    EXECUTION_SOURCE,
    Freshness,
    HUMAN_GATE_SOURCE,
    INCOMPLETE,
    LINEAGE_SOURCE,
    MISSION_SOURCE,
    R2_7_AS_OF_SEQ_AHEAD_OF_HEAD,
    R27Error,
    REQUIRED_SOURCES,
    RuntimeOperationsQuery,
    RuntimeOperationsReport,
    SourceCursor,
    STALE,
    TELEMETRY_FIELDS,
    UNAVAILABLE,
    WORK_GRAPH_SOURCE,
)
from .timeline import build_current_observations, build_historical_timeline


EXTENSION_IDS = {
    WORK_GRAPH_SOURCE: "r1_2_work_graph",
    EXECUTION_SOURCE: "r1_3b_execution_resume",
    LINEAGE_SOURCE: "r2_5_session_orchestration",
    HUMAN_GATE_SOURCE: "r2_6_human_gate",
}


def _plain(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _values(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(_plain(item) for item in value)
    return (_plain(value),)


def _state_values(state: Any, attribute: str) -> tuple[Any, ...] | str:
    if state is None:
        return UNAVAILABLE
    value = getattr(state, attribute, None)
    if value is None:
        return UNAVAILABLE
    return tuple(_plain(item) for item in value)


def _event_type(event: Any) -> str:
    return str(getattr(event, "event_type", "") or (event.get("event_type", "") if isinstance(event, Mapping) else ""))


def _event_seq(event: Any) -> int:
    value = getattr(event, "seq", None)
    if value is None and isinstance(event, Mapping):
        value = event.get("seq")
    return int(value)


def _event_value(event: Any, name: str, default: Any = None) -> Any:
    value = getattr(event, name, None)
    if value is None and isinstance(event, Mapping):
        value = event.get(name)
    return default if value is None else value


def _matches_source(source: str, event: Any) -> bool:
    event_type = _event_type(event)
    entity_type = str(_event_value(event, "entity_type", ""))
    command_id = str(_event_value(event, "command_id", ""))
    if source == MISSION_SOURCE:
        return entity_type in {"MISSION", "GOAL", "SESSION"} or event_type.startswith(("mission.", "goal.", "session."))
    if source == WORK_GRAPH_SOURCE:
        return entity_type in {"PLAN", "PLAN_REVISION", "TASK", "DEPENDENCY", "SNAPSHOT"} or event_type.startswith(("plan.", "task.", "snapshot."))
    if source == EXECUTION_SOURCE:
        return event_type.startswith("execution.")
    if source == LINEAGE_SOURCE:
        return command_id.startswith("r2.5:") or event_type.startswith("r2_5.")
    if source == HUMAN_GATE_SOURCE:
        return event_type.startswith("r2_6.")
    return False


def _event_projection_seq(runtime_service: Any, mission_id: str, source: str) -> int | None:
    """Read existing projection metadata only; never use it as a latest-wins join."""

    reader = getattr(runtime_service, "projection_seq", None)
    if callable(reader):
        for args in ((mission_id, source), (source, mission_id), (mission_id,)):
            try:
                value = reader(*args)
                return None if value is None else int(value)
            except TypeError:
                continue
            except Exception:
                return None

    db_path = getattr(runtime_service, "db_path", None)
    if db_path is None:
        return None
    tables = {
        MISSION_SOURCE: ("mission_projection",),
        WORK_GRAPH_SOURCE: (
            "work_graph_plan_projection",
            "work_graph_revision_projection",
            "work_graph_task_projection",
            "work_graph_dependency_projection",
            "work_graph_snapshot_projection",
        ),
        EXECUTION_SOURCE: ("execution_attempt_projection",),
        LINEAGE_SOURCE: ("r25_agent_bindings", "r25_delegations"),
        HUMAN_GATE_SOURCE: ("r26_human_gates",),
    }.get(source, ())
    values: set[int] = set()
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            for table in tables:
                column = "seq" if source == MISSION_SOURCE else "projection_seq"
                rows = conn.execute(
                    f"SELECT DISTINCT {column} FROM {table} WHERE mission_id=?",  # table names are fixed above
                    (mission_id,),
                ).fetchall()
                values.update(int(row[0]) for row in rows if row[0] is not None)
        finally:
            conn.close()
    except (sqlite3.DatabaseError, OSError):
        return None
    if not values:
        return None
    return next(iter(values)) if len(values) == 1 else -1


def _extension_state(composed: Any, extension_id: str) -> tuple[Any, bool]:
    if composed is None:
        return None, False
    states = getattr(composed, "extension_states", None)
    if isinstance(states, Mapping) and extension_id in states:
        state = states[extension_id]
        return state, state is not None
    accessor = getattr(composed, "extension_state", None)
    if callable(accessor):
        try:
            state = accessor(extension_id)
            return state, state is not None
        except Exception:
            return None, False
    return None, False


def _mission_state(composed: Any) -> Any:
    if composed is None:
        return None
    core = getattr(composed, "core_state", composed)
    return getattr(core, "mission", None)


def _source_cursor(
    *,
    source: str,
    as_of_seq: int,
    head_after_seq: int,
    events: Iterable[Any],
    available: bool,
    unresolved: bool,
    projection_seq: int | None,
) -> SourceCursor:
    relevant = [event for event in events if _matches_source(source, event)]
    latest = max((_event_seq(event) for event in relevant), default=None)
    if not available:
        return SourceCursor(as_of_seq, as_of_seq, projection_seq, latest, UNAVAILABLE, "canonical source unavailable")
    if unresolved:
        return SourceCursor(as_of_seq, as_of_seq, projection_seq, latest, INCOMPLETE, "historical source could not be resolved")
    if head_after_seq > as_of_seq:
        return SourceCursor(as_of_seq, as_of_seq, projection_seq, latest, STALE, "head advanced beyond requested cursor")
    reason = None
    if projection_seq != as_of_seq:
        reason = "replay_fallback_projection_cursor_mismatch"
    return SourceCursor(as_of_seq, as_of_seq, projection_seq, latest, CURRENT, reason)


def _identity_gap(*, mission: Any, goals: Any, sessions: Any, tasks: Any, delegations: Any, attempts: Any, gates: Any) -> bool:
    """Detect an incomplete required-domain identity/link without inventing one."""

    def items(value: Any) -> tuple[Mapping[str, Any], ...] | None:
        if value == UNAVAILABLE or not isinstance(value, (tuple, list)):
            return None
        if any(not isinstance(item, Mapping) for item in value):
            return None
        return tuple(value)

    if not isinstance(mission, Mapping) or not mission.get("mission_id"):
        return True
    required = (
        (goals, ("goal_id",)),
        (sessions, ("session_id",)),
        (tasks, ("task_id", "plan_id", "plan_revision_id")),
        (delegations, ("delegation_id", "parent_root_attempt_id", "parent_task_id", "child_task_id")),
        (attempts, ("attempt_id", "task_id", "root_attempt_id")),
        (gates, ("gate_id", "task_id", "root_attempt_id")),
    )
    for value, fields in required:
        normalized = items(value)
        if normalized is None:
            return True
        if any(not all(item.get(field) for field in fields) for item in normalized):
            return True
    return False


def _call_observation_provider(provider: Any, mission_id: str, as_of_seq: int) -> Iterable[Any]:
    if provider is None:
        return ()
    if hasattr(provider, "observe") and callable(provider.observe):
        return provider.observe(mission_id=mission_id, as_of_seq=as_of_seq)
    if callable(provider):
        return provider(mission_id=mission_id, as_of_seq=as_of_seq)
    return provider if isinstance(provider, (list, tuple)) else (provider,)


class RuntimeOperationsQueryService:
    """Fixed-cursor, on-demand aggregation over the existing runtime truth."""

    def __init__(
        self,
        runtime_service: Any,
        *,
        current_observation_source: Any = None,
        derived_timeline_source: Any = None,
    ) -> None:
        if runtime_service is None:
            raise ValueError("runtime_service is required")
        self._runtime_service = runtime_service
        self._current_observation_source = current_observation_source
        self._derived_timeline_source = derived_timeline_source

    @property
    def runtime_service(self) -> Any:
        return self._runtime_service

    def query(
        self,
        request: RuntimeOperationsQuery | Mapping[str, Any] | str | None = None,
        as_of_seq: int | None = None,
        *,
        mission_id: str | None = None,
        current_observations: Any = None,
    ) -> RuntimeOperationsReport:
        if request is None:
            request = mission_id
        elif mission_id is not None:
            raise R27Error("R2_7_ACTION_REQUEST_INVALID", "mission_id cannot override the query request")
        if isinstance(request, str):
            if as_of_seq is None:
                raise R27Error("R2_7_ACTION_REQUEST_INVALID", "as_of_seq is required")
            query_request = RuntimeOperationsQuery(request, as_of_seq)
        elif isinstance(request, RuntimeOperationsQuery):
            if as_of_seq is not None and as_of_seq != request.as_of_seq:
                raise R27Error("R2_7_ACTION_REQUEST_INVALID", "as_of_seq cannot override the query request")
            query_request = request
        else:
            query_request = RuntimeOperationsQuery.from_mapping(request)
            if as_of_seq is not None and as_of_seq != query_request.as_of_seq:
                raise R27Error("R2_7_ACTION_REQUEST_INVALID", "as_of_seq cannot override the query request")

        mission_id = query_request.mission_id
        as_of = query_request.as_of_seq
        head_before = int(self._runtime_service.get_head_seq(mission_id))
        if as_of > head_before:
            raise R27Error(
                R2_7_AS_OF_SEQ_AHEAD_OF_HEAD,
                "requested as_of_seq is ahead of the durable Event Stream head",
                {"as_of_seq": as_of, "head_before_seq": head_before},
            )

        event_read_failed = False
        try:
            events = list(self._runtime_service.list_events(mission_id, through_seq=as_of))
        except Exception:
            events = []
            event_read_failed = True

        composed = None
        replay_failed = False
        try:
            composed = self._runtime_service.replay_composed(mission_id, through_seq=as_of)
        except Exception:
            replay_failed = True
            try:
                composed = self._runtime_service.replay(mission_id, through_seq=as_of)
            except Exception:
                composed = None

        head_after = int(self._runtime_service.get_head_seq(mission_id))
        mission = _mission_state(composed)
        core = getattr(composed, "core_state", composed) if composed is not None else None
        extension_states: dict[str, tuple[Any, bool]] = {}
        for source, extension_id in EXTENSION_IDS.items():
            extension_states[source] = _extension_state(composed, extension_id)

        availability = {
            MISSION_SOURCE: mission is not None,
            WORK_GRAPH_SOURCE: extension_states[WORK_GRAPH_SOURCE][1],
            EXECUTION_SOURCE: extension_states[EXECUTION_SOURCE][1],
            LINEAGE_SOURCE: extension_states[LINEAGE_SOURCE][1],
            HUMAN_GATE_SOURCE: extension_states[HUMAN_GATE_SOURCE][1],
        }
        unresolved = replay_failed or event_read_failed
        cursors = {
            source: _source_cursor(
                source=source,
                as_of_seq=as_of,
                head_after_seq=head_after,
                events=events,
                available=availability[source],
                unresolved=unresolved,
                projection_seq=_event_projection_seq(self._runtime_service, mission_id, source),
            )
            for source in REQUIRED_SOURCES
        }

        work_graph = extension_states[WORK_GRAPH_SOURCE][0]
        execution = extension_states[EXECUTION_SOURCE][0]
        lineage = extension_states[LINEAGE_SOURCE][0]
        human_gate = extension_states[HUMAN_GATE_SOURCE][0]

        goals = _state_values(core, "goals")
        sessions = _state_values(core, "sessions")
        tasks = _state_values(work_graph, "tasks")
        delegations = _state_values(lineage, "delegations")
        gates = _state_values(human_gate, "gates")
        attempts = _state_values(execution, "attempts")
        active_tasks: tuple[Any, ...] | str
        if isinstance(tasks, str):
            active_tasks = UNAVAILABLE
        else:
            active_tasks = tuple(
                item
                for item in tasks
                if isinstance(item, Mapping) and str(item.get("lifecycle_state")) == "ACTIVE"
            )

        resume_count: int | str = UNAVAILABLE
        if not isinstance(attempts, str):
            resume_count = sum(
                1 for item in attempts if isinstance(item, Mapping) and item.get("attempt_kind") == "RESUME"
            )

        verified_rotation_count: int | str = UNAVAILABLE
        if not isinstance(delegations, str):
            verified_rotation_count = self._verified_rotation_count(events)

        derived_items: Iterable[Mapping[str, Any]] = ()
        derivation_incomplete = False
        if self._derived_timeline_source is not None:
            supplied_derived = _call_observation_provider(self._derived_timeline_source, mission_id, as_of)
            derived_items = _values(supplied_derived)
        try:
            timeline = build_historical_timeline(events, derived_items)
        except Exception:
            # A missing derived source is an incomplete envelope, not a
            # reason to turn a partial observation into a historical fact.
            derivation_incomplete = True
            try:
                timeline = build_historical_timeline(events)
            except Exception:
                timeline = ()

        observation_values = current_observations
        if observation_values is None:
            observation_values = _call_observation_provider(self._current_observation_source, mission_id, as_of)
        observations = build_current_observations(_values(observation_values))

        identity_incomplete = _identity_gap(
            mission=_plain(mission) if mission is not None else UNAVAILABLE,
            goals=goals,
            sessions=sessions,
            tasks=tasks,
            delegations=delegations,
            attempts=attempts,
            gates=gates,
        )
        required_incomplete = (
            derivation_incomplete
            or identity_incomplete
            or any(cursor.status in {UNAVAILABLE, INCOMPLETE} for cursor in cursors.values())
        )
        freshness_status = STALE if head_after > as_of else CURRENT
        if cursors[MISSION_SOURCE].status == UNAVAILABLE:
            freshness_status = UNAVAILABLE
        elif required_incomplete:
            freshness_status = INCOMPLETE
        freshness = Freshness(
            head_before_seq=head_before,
            head_after_seq=head_after,
            status=freshness_status,
            reason="head advanced beyond requested cursor" if freshness_status == STALE else None,
        )
        telemetry = {field: UNAVAILABLE for field in TELEMETRY_FIELDS}
        return RuntimeOperationsReport(
            mission_id=mission_id,
            as_of_seq=as_of,
            freshness=freshness,
            source_cursors=cursors,
            mission=_plain(mission) if mission is not None else UNAVAILABLE,
            goals=goals,
            sessions=sessions,
            active_tasks=active_tasks,
            delegations=delegations,
            human_gates=gates,
            attempts=attempts,
            resume_count=resume_count,
            verified_rotation_count=verified_rotation_count,
            historical_timeline=timeline,
            current_observations=observations,
            telemetry=telemetry,
        )

    get = query
    read = query
    report = query
    aggregate = query
    get_runtime_operations = query

    @staticmethod
    def _verified_rotation_count(events: Iterable[Any]) -> int:
        operations: dict[str, set[str]] = {}
        for event in events:
            command_id = str(_event_value(event, "command_id", ""))
            if not command_id.startswith("r2.5:"):
                continue
            parts = command_id.split(":")
            if len(parts) < 3:
                continue
            operation_id = parts[1]
            operations.setdefault(operation_id, set()).add(parts[2])
        return sum(1 for values in operations.values() if "OPEN_SUCCESSOR" in values and "RESUME_ATTEMPT" in values)


RuntimeOperationsQueryApplicationService = RuntimeOperationsQueryService


__all__ = ["RuntimeOperationsQueryApplicationService", "RuntimeOperationsQueryService"]
