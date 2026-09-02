from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from .contracts import (
    ComposedRuntimeState,
    EventEnvelope,
    ExtensionRegistry,
    GoalState,
    GoalStatus,
    MissionState,
    MissionStatus,
    RuntimeError,
    RuntimeState,
    SessionState,
    SessionStatus,
)


SUPPORTED_EVENTS = {
    "mission.created",
    "mission.activated",
    "mission.paused",
    "mission.blocked",
    "mission.continued",
    "mission.completed",
    "mission.failed",
    "mission.cancelled",
    "goal.created",
    "goal.revised",
    "goal.status_changed",
    "session.opened",
    "session.suspended",
    "session.closed",
    "session.failed",
}


def initial_state(mission_id: str) -> RuntimeState:
    if not isinstance(mission_id, str) or not mission_id.strip():
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "mission_id must be non-empty")
    return RuntimeState(mission_id=mission_id)


def initial_composed_state(mission_id: str, registry: ExtensionRegistry) -> ComposedRuntimeState:
    core_state = initial_state(mission_id)
    return ComposedRuntimeState(
        mission_id=mission_id,
        seq=0,
        core_state=core_state,
        extension_states={
            manifest.extension_id: manifest.state_contribution.initial_state(mission_id)
            for manifest in registry.manifests
        },
    )


def advance_shared_seq(state: RuntimeState, event: EventEnvelope) -> RuntimeState:
    if event.schema_version != 1:
        raise RuntimeError("UNSUPPORTED_EVENT_SCHEMA", f"unsupported event schema: {event.schema_version}")
    if event.mission_id != state.mission_id:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "event mission_id does not match state")
    if event.seq != state.seq + 1:
        raise RuntimeError("EVENT_SEQUENCE_VIOLATION", f"expected seq {state.seq + 1}, received {event.seq}")
    if state.mission is None:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "extension event requires an existing Mission")
    return replace(state, seq=event.seq)


def reduce_composed(
    state: ComposedRuntimeState,
    event: EventEnvelope,
    registry: ExtensionRegistry,
) -> ComposedRuntimeState:
    if event.seq != state.seq + 1:
        raise RuntimeError(
            "COMPOSED_EVENT_SEQUENCE_VIOLATION",
            f"expected seq {state.seq + 1}, received {event.seq}",
        )
    owner = registry.event_owner(event.event_type)
    if owner is None:
        raise RuntimeError("UNSUPPORTED_EVENT_TYPE", f"unsupported event type: {event.event_type}")
    extension_states = dict(state.extension_states)
    if owner == "CORE":
        core_state = reduce(state.core_state, event)
    else:
        core_state = advance_shared_seq(state.core_state, event)
        current = extension_states[owner.extension_id]
        extension_states[owner.extension_id] = owner.reducer_contribution.reduce(current, event, core_state)
    return ComposedRuntimeState(
        mission_id=state.mission_id,
        seq=event.seq,
        core_state=core_state,
        extension_states=extension_states,
    )


def _replace_goal(state: RuntimeState, goal: GoalState) -> tuple[GoalState, ...]:
    return tuple(goal if item.goal_id == goal.goal_id else item for item in state.goals)


def _replace_session(state: RuntimeState, session: SessionState) -> tuple[SessionState, ...]:
    return tuple(session if item.session_id == session.session_id else item for item in state.sessions)


def _require_mission(state: RuntimeState) -> MissionState:
    if state.mission is None:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "event requires an existing Mission")
    return state.mission


def reduce(state: RuntimeState, event: EventEnvelope) -> RuntimeState:
    if event.schema_version != 1:
        raise RuntimeError("UNSUPPORTED_EVENT_SCHEMA", f"unsupported event schema: {event.schema_version}")
    if event.event_type not in SUPPORTED_EVENTS:
        raise RuntimeError("UNSUPPORTED_EVENT_TYPE", f"unsupported event type: {event.event_type}")
    if event.mission_id != state.mission_id:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "event mission_id does not match state")
    if event.seq != state.seq + 1:
        raise RuntimeError(
            "EVENT_SEQUENCE_VIOLATION",
            f"expected seq {state.seq + 1}, received {event.seq}",
        )

    payload = deepcopy(dict(event.payload))
    mission = state.mission
    goals = state.goals
    sessions = state.sessions

    if event.event_type == "mission.created":
        if mission is not None or state.seq != 0:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Mission may be created only once")
        mission = MissionState(
            mission_id=event.mission_id,
            status=MissionStatus.CREATED,
            active_goal_id=None,
            created_at=event.created_at,
            updated_at=event.created_at,
            attributes=payload.get("attributes") or {},
        )
    elif event.event_type.startswith("mission."):
        current = _require_mission(state)
        allowed_sources = {
            "mission.activated": {MissionStatus.CREATED},
            "mission.paused": {MissionStatus.ACTIVE},
            "mission.blocked": {MissionStatus.ACTIVE},
            "mission.continued": {MissionStatus.PAUSED, MissionStatus.BLOCKED},
            "mission.completed": {MissionStatus.ACTIVE},
            "mission.failed": {MissionStatus.ACTIVE, MissionStatus.PAUSED, MissionStatus.BLOCKED},
            "mission.cancelled": {MissionStatus.CREATED, MissionStatus.ACTIVE, MissionStatus.PAUSED, MissionStatus.BLOCKED},
        }
        if current.status not in allowed_sources[event.event_type]:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Mission event violates lifecycle")
        if event.event_type == "mission.activated" and current.active_goal_id is None:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "activation fact requires an ACTIVE Goal")
        if event.event_type == "mission.completed" and not any(goal.status == GoalStatus.ACHIEVED for goal in state.goals):
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "completion fact requires an ACHIEVED Goal")
        target_by_event = {
            "mission.activated": MissionStatus.ACTIVE,
            "mission.paused": MissionStatus.PAUSED,
            "mission.blocked": MissionStatus.BLOCKED,
            "mission.continued": MissionStatus.ACTIVE,
            "mission.completed": MissionStatus.COMPLETED,
            "mission.failed": MissionStatus.FAILED,
            "mission.cancelled": MissionStatus.CANCELLED,
        }
        mission = replace(current, status=target_by_event[event.event_type], updated_at=event.created_at)
    elif event.event_type == "goal.created":
        current = _require_mission(state)
        goal_id = event.entity_id
        if state.goal(goal_id) is not None:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Goal already exists")
        if current.active_goal_id is not None:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Mission already has an ACTIVE Goal")
        if int(payload.get("revision", 0)) != 1 or payload.get("status") != GoalStatus.ACTIVE.value:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "new Goal must be ACTIVE revision 1")
        goal = GoalState(
            goal_id=goal_id,
            mission_id=event.mission_id,
            revision=int(payload["revision"]),
            status=GoalStatus(str(payload["status"])),
            definition=payload.get("definition") or {},
            created_at=event.created_at,
            updated_at=event.created_at,
        )
        goals = state.goals + (goal,)
        mission = replace(current, active_goal_id=goal_id, updated_at=event.created_at)
    elif event.event_type == "goal.revised":
        current = _require_mission(state)
        goal = state.goal(event.entity_id)
        if goal is None:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Goal revision references missing Goal")
        if goal.status != GoalStatus.ACTIVE:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "terminal Goal cannot be revised")
        if int(payload.get("base_revision", -1)) != goal.revision or int(payload.get("revision", 0)) != goal.revision + 1:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Goal revision fact is not contiguous")
        revised = replace(
            goal,
            revision=int(payload["revision"]),
            definition=payload.get("definition") or {},
            updated_at=event.created_at,
        )
        goals = _replace_goal(state, revised)
        mission = replace(current, updated_at=event.created_at)
    elif event.event_type == "goal.status_changed":
        current = _require_mission(state)
        goal = state.goal(event.entity_id)
        if goal is None:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Goal status event references missing Goal")
        target_status = GoalStatus(str(payload["to_status"]))
        if goal.status != GoalStatus.ACTIVE or target_status not in {GoalStatus.ACHIEVED, GoalStatus.CANCELLED}:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Goal status fact violates lifecycle")
        changed = replace(goal, status=target_status, updated_at=event.created_at)
        goals = _replace_goal(state, changed)
        mission = replace(current, active_goal_id=None, updated_at=event.created_at)
    elif event.event_type == "session.opened":
        current = _require_mission(state)
        if state.session(event.entity_id) is not None:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Session already exists")
        session = SessionState(
            session_id=event.entity_id,
            mission_id=event.mission_id,
            status=SessionStatus.OPEN,
            created_at=event.created_at,
            updated_at=event.created_at,
            attributes=payload.get("attributes") or {},
        )
        sessions = state.sessions + (session,)
        mission = replace(current, updated_at=event.created_at)
    else:
        current = _require_mission(state)
        session = state.session(event.entity_id)
        if session is None:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Session event references missing Session")
        allowed_session_sources = {
            "session.suspended": {SessionStatus.OPEN},
            "session.closed": {SessionStatus.OPEN, SessionStatus.SUSPENDED},
            "session.failed": {SessionStatus.OPEN, SessionStatus.SUSPENDED},
        }
        if session.status not in allowed_session_sources[event.event_type]:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Session event violates lifecycle")
        target_by_event = {
            "session.suspended": SessionStatus.SUSPENDED,
            "session.closed": SessionStatus.CLOSED,
            "session.failed": SessionStatus.FAILED,
        }
        changed_session = replace(session, status=target_by_event[event.event_type], updated_at=event.created_at)
        sessions = _replace_session(state, changed_session)
        mission = replace(current, updated_at=event.created_at)

    return RuntimeState(
        mission_id=state.mission_id,
        seq=event.seq,
        mission=mission,
        goals=goals,
        sessions=sessions,
    )
