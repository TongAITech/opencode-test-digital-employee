from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import CommandEnvelope, GoalStatus, MissionStatus, RuntimeError, RuntimeState, SessionStatus


SUPPORTED_COMMANDS = {
    "CREATE_MISSION",
    "CREATE_GOAL",
    "ACTIVATE_MISSION",
    "PAUSE_MISSION",
    "BLOCK_MISSION",
    "CONTINUE_MISSION",
    "COMPLETE_MISSION",
    "FAIL_MISSION",
    "CANCEL_MISSION",
    "REVISE_GOAL",
    "CHANGE_GOAL_STATUS",
    "OPEN_SESSION",
    "SUSPEND_SESSION",
    "CLOSE_SESSION",
    "FAIL_SESSION",
}

MISSION_TERMINAL = {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED}


@dataclass(frozen=True)
class PendingEvent:
    event_type: str
    entity_type: str
    entity_id: str
    payload: Mapping[str, Any]
    session_id: str | None = None


def _invalid(message: str) -> RuntimeError:
    return RuntimeError("INVALID_STATE_TRANSITION", message)


def _require_text(payload: Mapping[str, Any], key: str, code: str = "COMMAND_SCHEMA_INVALID") -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(code, f"payload.{key} must be a non-empty string")
    return value


def _require_mission(state: RuntimeState):
    if state.mission is None:
        raise RuntimeError("MISSION_NOT_FOUND", f"Mission not found: {state.mission_id}")
    return state.mission


def _mission_transition(command: CommandEnvelope, state: RuntimeState) -> list[PendingEvent]:
    mission = _require_mission(state)
    transition = {
        "ACTIVATE_MISSION": (MissionStatus.CREATED, MissionStatus.ACTIVE, "mission.activated"),
        "PAUSE_MISSION": (MissionStatus.ACTIVE, MissionStatus.PAUSED, "mission.paused"),
        "BLOCK_MISSION": (MissionStatus.ACTIVE, MissionStatus.BLOCKED, "mission.blocked"),
        "COMPLETE_MISSION": (MissionStatus.ACTIVE, MissionStatus.COMPLETED, "mission.completed"),
    }
    if command.type in transition:
        source, target, event_type = transition[command.type]
        if mission.status != source:
            raise _invalid(f"{mission.status.value} cannot apply {command.type}")
        if command.type == "ACTIVATE_MISSION" and mission.active_goal_id is None:
            raise RuntimeError("ACTIVE_GOAL_REQUIRED", "Mission activation requires a current ACTIVE Goal")
        if command.type == "COMPLETE_MISSION" and not any(goal.status == GoalStatus.ACHIEVED for goal in state.goals):
            raise RuntimeError("ACHIEVED_GOAL_REQUIRED", "Mission completion requires an ACHIEVED Goal")
    elif command.type == "CONTINUE_MISSION":
        if mission.status not in {MissionStatus.PAUSED, MissionStatus.BLOCKED}:
            raise _invalid(f"{mission.status.value} cannot apply CONTINUE_MISSION")
        target, event_type = MissionStatus.ACTIVE, "mission.continued"
    elif command.type == "FAIL_MISSION":
        if mission.status not in {MissionStatus.ACTIVE, MissionStatus.PAUSED, MissionStatus.BLOCKED}:
            raise _invalid(f"{mission.status.value} cannot apply FAIL_MISSION")
        target, event_type = MissionStatus.FAILED, "mission.failed"
    elif command.type == "CANCEL_MISSION":
        if mission.status not in {MissionStatus.CREATED, MissionStatus.ACTIVE, MissionStatus.PAUSED, MissionStatus.BLOCKED}:
            raise _invalid(f"{mission.status.value} cannot apply CANCEL_MISSION")
        target, event_type = MissionStatus.CANCELLED, "mission.cancelled"
    else:
        raise RuntimeError("UNSUPPORTED_COMMAND_TYPE", f"unsupported command: {command.type}")
    return [
        PendingEvent(
            event_type,
            "MISSION",
            command.mission_id,
            {"from_status": mission.status.value, "to_status": target.value, "reason": command.payload.get("reason")},
        )
    ]


def _goal_command(command: CommandEnvelope, state: RuntimeState) -> list[PendingEvent]:
    mission = _require_mission(state)
    if mission.status in MISSION_TERMINAL:
        raise _invalid("terminal Mission cannot mutate Goals")
    goal_id = _require_text(command.payload, "goal_id")
    existing = state.goal(goal_id)
    if command.type == "CREATE_GOAL":
        if existing is not None:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", f"Goal already exists: {goal_id}")
        if mission.active_goal_id is not None:
            raise RuntimeError("ACTIVE_GOAL_ALREADY_EXISTS", "Mission already has an ACTIVE Goal")
        raw_definition = command.payload.get("goal")
        if raw_definition is None:
            raw_definition = {key: value for key, value in command.payload.items() if key != "goal_id"}
        if not isinstance(raw_definition, Mapping):
            raise RuntimeError("COMMAND_SCHEMA_INVALID", "payload.goal must be an object")
        return [
            PendingEvent(
                "goal.created",
                "GOAL",
                goal_id,
                {"revision": 1, "status": GoalStatus.ACTIVE.value, "definition": dict(raw_definition)},
            )
        ]
    if existing is None:
        raise RuntimeError("GOAL_NOT_FOUND", f"Goal not found: {goal_id}")
    if existing.status != GoalStatus.ACTIVE:
        raise _invalid("terminal Goal cannot be revised or transitioned")
    if command.type == "REVISE_GOAL":
        base_revision = command.payload.get("base_revision")
        if not isinstance(base_revision, int):
            raise RuntimeError("COMMAND_SCHEMA_INVALID", "payload.base_revision must be an integer")
        if base_revision != existing.revision:
            raise RuntimeError(
                "GOAL_REVISION_MISMATCH",
                f"expected Goal revision {existing.revision}, received {base_revision}",
            )
        definition = command.payload.get("goal", command.payload.get("definition"))
        if definition is None:
            flattened = {
                key: value
                for key, value in command.payload.items()
                if key not in {"goal_id", "base_revision"}
            }
            definition = flattened or None
        if not isinstance(definition, Mapping):
            raise RuntimeError("COMMAND_SCHEMA_INVALID", "REVISE_GOAL requires a full payload.goal object")
        return [
            PendingEvent(
                "goal.revised",
                "GOAL",
                goal_id,
                {"base_revision": base_revision, "revision": existing.revision + 1, "definition": dict(definition)},
            )
        ]
    if command.type == "CHANGE_GOAL_STATUS":
        raw_status = _require_text(command.payload, "status")
        try:
            target = GoalStatus(raw_status)
        except ValueError as exc:
            raise RuntimeError("COMMAND_SCHEMA_INVALID", f"unsupported Goal status: {raw_status}") from exc
        if target not in {GoalStatus.ACHIEVED, GoalStatus.CANCELLED}:
            raise _invalid("ACTIVE Goal may transition only to ACHIEVED or CANCELLED")
        return [
            PendingEvent(
                "goal.status_changed",
                "GOAL",
                goal_id,
                {"from_status": existing.status.value, "to_status": target.value},
            )
        ]
    raise RuntimeError("UNSUPPORTED_COMMAND_TYPE", f"unsupported command: {command.type}")


def _session_command(command: CommandEnvelope, state: RuntimeState) -> list[PendingEvent]:
    _require_mission(state)
    if not isinstance(command.session_id, str) or not command.session_id.strip():
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "session_id is required")
    existing = state.session(command.session_id)
    if command.type == "OPEN_SESSION":
        if existing is not None:
            raise _invalid("Session already exists")
        return [
            PendingEvent(
                "session.opened",
                "SESSION",
                command.session_id,
                {"attributes": dict(command.payload)},
                session_id=command.session_id,
            )
        ]
    if existing is None:
        raise RuntimeError("SESSION_NOT_FOUND", f"Session not found: {command.session_id}")
    allowed = {
        "SUSPEND_SESSION": ({SessionStatus.OPEN}, SessionStatus.SUSPENDED, "session.suspended"),
        "CLOSE_SESSION": ({SessionStatus.OPEN, SessionStatus.SUSPENDED}, SessionStatus.CLOSED, "session.closed"),
        "FAIL_SESSION": ({SessionStatus.OPEN, SessionStatus.SUSPENDED}, SessionStatus.FAILED, "session.failed"),
    }
    if command.type not in allowed:
        raise RuntimeError("UNSUPPORTED_COMMAND_TYPE", f"unsupported command: {command.type}")
    sources, target, event_type = allowed[command.type]
    if existing.status not in sources:
        raise _invalid(f"{existing.status.value} cannot apply {command.type}")
    return [
        PendingEvent(
            event_type,
            "SESSION",
            command.session_id,
            {"from_status": existing.status.value, "to_status": target.value},
            session_id=command.session_id,
        )
    ]


def handle(command: CommandEnvelope, state: RuntimeState) -> list[PendingEvent]:
    if command.type not in SUPPORTED_COMMANDS:
        raise RuntimeError("UNSUPPORTED_COMMAND_TYPE", f"unsupported command: {command.type}")
    if command.type == "CREATE_MISSION":
        if state.mission is not None:
            raise RuntimeError("MISSION_ALREADY_EXISTS", f"Mission already exists: {command.mission_id}")
        return [PendingEvent("mission.created", "MISSION", command.mission_id, {"attributes": dict(command.payload)})]
    if command.type in {
        "ACTIVATE_MISSION",
        "PAUSE_MISSION",
        "BLOCK_MISSION",
        "CONTINUE_MISSION",
        "COMPLETE_MISSION",
        "FAIL_MISSION",
        "CANCEL_MISSION",
    }:
        return _mission_transition(command, state)
    if command.type in {"CREATE_GOAL", "REVISE_GOAL", "CHANGE_GOAL_STATUS"}:
        return _goal_command(command, state)
    return _session_command(command, state)
