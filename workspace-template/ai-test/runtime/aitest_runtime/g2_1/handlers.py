from __future__ import annotations
from typing import Any, Mapping
from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent, RuntimeError
from aitest_runtime.work_graph import WorkGraphState
from .contracts import *


def _payload(command: Any, required: set[str], optional: set[str] = set()) -> dict[str, Any]:
    p = dict(command.payload)
    unknown = set(p) - required - optional
    missing = required - set(p)
    if unknown or missing:
        raise RuntimeError("G2_1_COMMAND_INVALID", f"payload mismatch missing={sorted(missing)} unknown={sorted(unknown)}")
    return p


def _require_mission(composed: ComposedRuntimeState) -> None:
    if composed.core_state.mission is None:
        raise RuntimeError("MISSION_NOT_FOUND", composed.mission_id)


class G21CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        _require_mission(composed)
        if command.type == ENABLE_ROUTING_AUTHORITY:
            p = _payload(command, set())
            return [PendingEvent(ROUTING_AUTHORITY_ENABLED, "SESSION_ROUTING", composed.mission_id, p)]
        if command.type == REGISTER_TASK_ROUTE:
            p = _payload(command, {"task_id","role","agent_name","required_capabilities","isolation_policy","parallelism_policy","source","route_digest"})
            graph = composed.extension_state("r1_2_work_graph")
            if not isinstance(graph, WorkGraphState) or graph.task(str(p["task_id"])) is None:
                raise RuntimeError("G2_1_TASK_NOT_FOUND", str(p["task_id"]))
            return [PendingEvent(TASK_ROUTE_REGISTERED, "TASK_ROUTE", str(p["task_id"]), p)]
        if command.type == REQUEST_SESSION_PROVISION:
            p = _payload(command, {"provision_token","task_id","logical_agent_id","role","agent_name","phase","title"}, {"root_attempt_id"})
            return [PendingEvent(SESSION_PROVISION_REQUESTED, "SESSION_PROVISION", str(p["provision_token"]), p)]
        if command.type == BIND_SESSION_PROVISION:
            p = _payload(command, {"provision_token","external_session_id"})
            return [PendingEvent(SESSION_PROVISION_BOUND, "SESSION_PROVISION", str(p["provision_token"]), p, str(p["external_session_id"]))]
        if command.type == CLOSE_ORPHAN_PROVISION:
            p = _payload(command, {"provision_token","external_session_id","reason"})
            return [PendingEvent(ORPHAN_PROVISION_CLOSED, "SESSION_PROVISION", str(p["provision_token"]), p, str(p["external_session_id"]))]
        if command.type == RECORD_SESSION_OBSERVATION:
            p = _payload(command, {"session_id","observed_at","reachable","healthy","message_count","compaction_count","context_used","context_limit","context_utilization","last_activity_at","provider_state"})
            return [PendingEvent(SESSION_OBSERVATION_RECORDED, "SESSION_OBSERVATION", str(p["session_id"]), p, str(p["session_id"]))]
        if command.type == REQUEST_SESSION_ROTATION:
            p = _payload(command, {"rotation_id","task_id","root_attempt_id","predecessor_session_id","reasons"})
            return [PendingEvent(SESSION_ROTATION_REQUESTED, "SESSION_ROTATION", str(p["rotation_id"]), p, str(p["predecessor_session_id"]))]
        if command.type == COMPLETE_SESSION_ROTATION:
            p = _payload(command, {"rotation_id","successor_session_id"})
            return [PendingEvent(SESSION_ROTATION_COMPLETED, "SESSION_ROTATION", str(p["rotation_id"]), p, str(p["successor_session_id"]))]
        raise RuntimeError("G2_1_COMMAND_NOT_OWNED", command.type)
