from __future__ import annotations
from dataclasses import replace
from aitest_runtime.durable_core import EventEnvelope, RuntimeState, RuntimeError
from .contracts import *


def _upsert(items, predicate, value):
    result = [x for x in items if not predicate(x)]
    result.append(value)
    return tuple(result)


class G21ReducerContribution:
    def reduce(self, state: SessionControlState, event: EventEnvelope, core_state: RuntimeState) -> SessionControlState:
        if event.event_type == ROUTING_AUTHORITY_ENABLED:
            return replace(state, routing_authority_enabled=True, routing_authority_enabled_seq=state.routing_authority_enabled_seq or event.seq)
        if event.event_type == TASK_ROUTE_REGISTERED:
            p = dict(event.payload)
            item = TaskRouteRequirement(str(p["task_id"]), str(p["role"]), str(p["agent_name"]), tuple(p.get("required_capabilities") or ()), str(p["isolation_policy"]), str(p["parallelism_policy"]), str(p["source"]), str(p["route_digest"]), event.seq, event.created_at)
            return replace(state, task_routes=_upsert(state.task_routes, lambda x: x.task_id == item.task_id, item))
        if event.event_type == SESSION_PROVISION_REQUESTED:
            p = dict(event.payload)
            existing = state.provision(str(p["provision_token"]))
            requested_seq = existing.requested_seq if existing else event.seq
            item = ProvisionIntent(str(p["provision_token"]), p.get("task_id"), p.get("root_attempt_id"), str(p["logical_agent_id"]), str(p["role"]), str(p["agent_name"]), str(p["phase"]), str(p["title"]), "REQUESTED", existing.external_session_id if existing else None, requested_seq, event.seq, event.created_at)
            return replace(state, provisions=_upsert(state.provisions, lambda x: x.provision_token == item.provision_token, item))
        if event.event_type in {SESSION_PROVISION_BOUND, ORPHAN_PROVISION_CLOSED}:
            p = dict(event.payload); token = str(p["provision_token"]); existing = state.provision(token)
            if existing is None: raise RuntimeError("G2_1_PROVISION_NOT_FOUND", token)
            status = "BOUND" if event.event_type == SESSION_PROVISION_BOUND else "ORPHAN_CLOSED"
            item = replace(existing, status=status, external_session_id=str(p["external_session_id"]), updated_seq=event.seq, updated_at=event.created_at)
            return replace(state, provisions=_upsert(state.provisions, lambda x: x.provision_token == token, item))
        if event.event_type == SESSION_OBSERVATION_RECORDED:
            p = dict(event.payload)
            item = SessionObservationRecord(str(p["session_id"]), str(p["observed_at"]), bool(p["reachable"]), p.get("healthy"), p.get("message_count"), p.get("compaction_count"), p.get("context_used"), p.get("context_limit"), p.get("context_utilization"), p.get("last_activity_at"), dict(p.get("provider_state") or {}), event.seq)
            return replace(state, observations=_upsert(state.observations, lambda x: x.session_id == item.session_id, item))
        if event.event_type == SESSION_ROTATION_REQUESTED:
            p = dict(event.payload); rid = str(p["rotation_id"]); existing = state.rotation(rid)
            requested_seq = existing.requested_seq if existing else event.seq
            item = RotationRequestRecord(rid, str(p["task_id"]), str(p["root_attempt_id"]), str(p["predecessor_session_id"]), tuple(p.get("reasons") or ()), "REQUIRED", existing.successor_session_id if existing else None, requested_seq, event.seq, event.created_at)
            return replace(state, rotations=_upsert(state.rotations, lambda x: x.rotation_id == rid, item))
        if event.event_type == SESSION_ROTATION_COMPLETED:
            p = dict(event.payload); rid = str(p["rotation_id"]); existing = state.rotation(rid)
            if existing is None: raise RuntimeError("G2_1_ROTATION_NOT_FOUND", rid)
            item = replace(existing, status="COMPLETED", successor_session_id=str(p["successor_session_id"]), updated_seq=event.seq, updated_at=event.created_at)
            return replace(state, rotations=_upsert(state.rotations, lambda x: x.rotation_id == rid, item))
        raise RuntimeError("G2_1_EVENT_NOT_OWNED", event.event_type)
