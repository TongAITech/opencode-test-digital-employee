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
        if command.type == RECORD_CONTEXT_DISPATCH:
            p = _payload(command, {"dispatch_id","session_id","context_digest","phase","mode","business_cursor"}, {'host_receipt'})
            validate_dispatch_record(p)
            session = composed.core_state.session(str(p['session_id']))
            if session is None or (p['phase'] == 'CLAIMED' and (session.status.value != 'OPEN' or composed.core_state.mission.status.value != 'ACTIVE')):
                raise RuntimeError('G21_DISPATCH_SESSION_NOT_ACTIVE', str(p['session_id']))
            if command.session_id != p['session_id'] or command.actor.type != 'SYSTEM' or command.actor.id != 'g2.1-session-control':
                raise RuntimeError('G21_DISPATCH_CALLER_INVALID', 'Runtime dispatch owner required')
            if (not isinstance(p['dispatch_id'], str) or not p['dispatch_id'] or len(p['dispatch_id']) > 160
                    or p['mode'] not in {'INITIAL','AUTO_CONTINUE'} or p['phase'] not in {'CLAIMED','ACCEPTED','UNKNOWN'}
                    or not isinstance(p['context_digest'], str) or len(p['context_digest']) != 64
                    or any(c not in '0123456789abcdef' for c in p['context_digest'])
                    or not isinstance(p['business_cursor'], int) or isinstance(p['business_cursor'], bool)
                    or not 0 <= p['business_cursor'] <= composed.seq):
                raise RuntimeError('G21_DISPATCH_SCHEMA_INVALID', 'Invalid bounded dispatch identity')
            previous = composed.extension_state(EXTENSION_ID).context_dispatch(p['dispatch_id'])
            receipt=p.get('host_receipt')
            if receipt is not None and (not isinstance(receipt, dict) or set(receipt) != {'source','session_id','message_id','context_digest'}
                    or receipt.get('source') != 'OPENCODE_SESSION_MESSAGE_READBACK'
                    or receipt.get('session_id') != p['session_id'] or receipt.get('context_digest') != p['context_digest']
                    or not isinstance(receipt.get('message_id'),str) or not 1<=len(receipt['message_id'])<=160):
                raise RuntimeError('G21_HOST_RECEIPT_INVALID',p['dispatch_id'])
            if previous is None and p['phase'] != 'CLAIMED':
                raise RuntimeError('G21_DISPATCH_CLAIM_REQUIRED', p['dispatch_id'])
            if previous is not None:
                if not ((previous['phase'] == 'CLAIMED' and p['phase'] in {'ACCEPTED','UNKNOWN'})
                        or (previous['phase'] == 'UNKNOWN' and p['phase']=='ACCEPTED' and receipt)):
                    raise RuntimeError('G21_DISPATCH_TRANSITION_INVALID', p['dispatch_id'])
                if any(previous[k] != p[k] for k in ('session_id','context_digest','mode','business_cursor')):
                    raise RuntimeError('G21_DISPATCH_IDENTITY_CONFLICT', p['dispatch_id'])
            return [PendingEvent(CONTEXT_DISPATCH_RECORDED, 'CONTEXT_DISPATCH', p['dispatch_id'], p, p['session_id'])]
        if command.type == RECORD_PROGRESS_STATE:
            p = _payload(command, {"progress_id","business_cursor","phase","reason","failure_signature",
                                   "task_id","session_id","replan_lineage","replan_session_id","observed_at"})
            if (not isinstance(p["progress_id"], str) or not 1 <= len(p["progress_id"]) <= 160
                    or p["phase"] not in {"STALLED","REPLANNING","RESOLVED","BLOCKED"}
                    or not isinstance(p["business_cursor"], int) or isinstance(p["business_cursor"], bool)
                    or not 0 <= p["business_cursor"] <= composed.seq
                    or not isinstance(p["reason"], str) or not 1 <= len(p["reason"]) <= 256
                    or not isinstance(p["failure_signature"], str) or len(p["failure_signature"]) != 64
                    or any(ch not in "0123456789abcdef" for ch in p["failure_signature"])
                    or any(value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 256)
                           for value in (p["task_id"], p["session_id"], p["replan_lineage"], p["replan_session_id"]))):
                raise RuntimeError("G2_1_PROGRESS_SCHEMA_INVALID", str(p.get("progress_id")))
            previous = composed.extension_state(EXTENSION_ID).progress(p["progress_id"])
            if previous is None and p["phase"] != "STALLED":
                raise RuntimeError("G2_1_PROGRESS_STALLED_REQUIRED", p["progress_id"])
            if previous is not None:
                allowed = {
                    "STALLED": {"STALLED","REPLANNING","BLOCKED"},
                    "REPLANNING": {"REPLANNING","RESOLVED","BLOCKED"},
                    "RESOLVED": {"RESOLVED"},
                    "BLOCKED": {"BLOCKED"},
                }
                if p["phase"] not in allowed.get(previous.phase, set()):
                    raise RuntimeError("G2_1_PROGRESS_TRANSITION_INVALID", p["progress_id"])
                for key in ("business_cursor","reason","failure_signature","task_id","session_id"):
                    if getattr(previous, key) != p[key]:
                        raise RuntimeError("G2_1_PROGRESS_IDENTITY_CONFLICT", p["progress_id"])
            return [PendingEvent(PROGRESS_STATE_RECORDED, "MISSION_PROGRESS", p["progress_id"], p, p["session_id"])]
        if command.type == RECORD_QUALITY_DECISION:
            p = _payload(command, {"generation_id","quality_cursor","plan_id","plan_revision_id",
                                   "g4_goal_id","g4_status","next_action","evaluation_fact_id",
                                   "replan_request_fact_id","decision_digest"})
            valid_status = {"SATISFIED","COMPLETED_WITH_ACCEPTED_GAP","WAITING_MEASUREMENT","REPLANNING"}
            valid_action = {"NONE","WAIT_COVERAGE_REFRESH","G3_REPLAN"}
            if (not isinstance(p["generation_id"], str) or not 1 <= len(p["generation_id"]) <= 160
                    or not isinstance(p["quality_cursor"], int) or isinstance(p["quality_cursor"], bool)
                    or not 0 <= p["quality_cursor"] <= composed.seq
                    or any(not isinstance(p[key], str) or not 1 <= len(p[key]) <= 256
                           for key in ("plan_id","plan_revision_id","g4_goal_id"))
                    or p["g4_status"] not in valid_status or p["next_action"] not in valid_action
                    or not isinstance(p["decision_digest"], str) or len(p["decision_digest"]) != 64
                    or any(ch not in "0123456789abcdef" for ch in p["decision_digest"])
                    or any(value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 256)
                           for value in (p["evaluation_fact_id"], p["replan_request_fact_id"]))):
                raise RuntimeError("G2_1_QUALITY_DECISION_SCHEMA_INVALID", str(p.get("generation_id")))
            previous = composed.extension_state(EXTENSION_ID).quality_decision(p["generation_id"])
            if previous is not None:
                prior = previous.to_dict()
                prior.pop("recorded_seq", None); prior.pop("recorded_at", None)
                if prior != p:
                    raise RuntimeError("G2_1_QUALITY_DECISION_CONFLICT", p["generation_id"])
                return []
            return [PendingEvent(QUALITY_DECISION_RECORDED, "QUALITY_DECISION", p["generation_id"], p)]
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
            p = _payload(command, {"rotation_id","task_id","root_attempt_id","predecessor_session_id","reasons"}, {"checkpoint"})
            checkpoint = p.get("checkpoint")
            if checkpoint is not None:
                if not isinstance(checkpoint, Mapping) or checkpoint.get("mission_id") != composed.mission_id or checkpoint.get("predecessor_session_id") != p["predecessor_session_id"] or checkpoint.get("task_id") != p["task_id"] or checkpoint.get("root_attempt_id") != p["root_attempt_id"]:
                    raise RuntimeError("G2_1_CHECKPOINT_LINEAGE_INVALID", "rotation checkpoint identity mismatch")
                cursor = checkpoint.get("through_seq")
                if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0 or cursor > composed.seq:
                    raise RuntimeError("G2_1_CHECKPOINT_CURSOR_INVALID", "rotation checkpoint is not a durable R1 cursor")
            return [PendingEvent(SESSION_ROTATION_REQUESTED, "SESSION_ROTATION", str(p["rotation_id"]), p, str(p["predecessor_session_id"]))]
        if command.type == COMPLETE_SESSION_ROTATION:
            p = _payload(command, {"rotation_id","successor_session_id"})
            return [PendingEvent(SESSION_ROTATION_COMPLETED, "SESSION_ROTATION", str(p["rotation_id"]), p, str(p["successor_session_id"]))]
        raise RuntimeError("G2_1_COMMAND_NOT_OWNED", command.type)
