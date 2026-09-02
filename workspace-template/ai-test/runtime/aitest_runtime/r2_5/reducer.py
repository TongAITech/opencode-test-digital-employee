from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import EventEnvelope, RuntimeError, RuntimeState

from .contracts import (
    CHILD_RESULT_RECORDED,
    DELEGATION_REGISTERED,
    JOINED,
    LOGICAL_AGENT_BOUND,
    LogicalAgentBinding,
    ChildResultRecord,
    DelegationRecord,
    JoinRecord,
    R25Error,
    SessionOrchestrationState,
)


def _payload(event: EventEnvelope, required: set[str]) -> dict[str, Any]:
    payload = dict(event.payload)
    if set(payload) != required:
        raise R25Error("R2_5_EVENT_INVALID", f"{event.event_type} payload contains unknown or missing fields")
    if event.mission_id != payload.get("mission_id", event.mission_id):
        raise R25Error("R2_5_EVENT_INVALID", "R2.5 Event Mission identity mismatch")
    return payload


class R25ReducerContribution:
    def reduce(self, state: SessionOrchestrationState, event: EventEnvelope, core_state: RuntimeState) -> SessionOrchestrationState:
        if not isinstance(state, SessionOrchestrationState):
            raise R25Error("EXTENSION_SCHEMA_MISMATCH", "invalid R2.5 state")
        if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id:
            raise R25Error("R2_5_EVENT_INVALID", "R2.5 Event Mission identity mismatch")
        if core_state.seq != event.seq:
            raise R25Error("R2_5_EVENT_INVALID", "R2.5 Event does not share the Core sequence")
        bindings = state.bindings
        delegations = state.delegations
        results = state.child_results
        joins = state.joins
        if event.event_type == LOGICAL_AGENT_BOUND:
            payload = _payload(event, {"binding_id", "logical_agent_id", "root_attempt_id", "attempt_id", "task_id", "session_id"})
            binding = LogicalAgentBinding(
                binding_id=event.entity_id, mission_id=event.mission_id,
                logical_agent_id=payload["logical_agent_id"], root_attempt_id=payload["root_attempt_id"],
                attempt_id=payload["attempt_id"], task_id=payload["task_id"], session_id=payload["session_id"],
                created_seq=event.seq, created_at=event.created_at,
                created_by={"type": event.initiator_type, "id": event.initiator_id},
            )
            if state.binding(binding.binding_id) is not None:
                raise R25Error("R2_5_EVENT_INVALID", "LogicalAgent binding identity is not immutable")
            bindings = state.bindings + (binding,)
        elif event.event_type == DELEGATION_REGISTERED:
            required = {
                "delegation_id", "parent_root_attempt_id", "parent_attempt_id", "parent_task_id", "child_task_id",
                "child_root_attempt_id", "logical_agent_id", "expected_delegation_version", "expected_active_child_count",
                "max_total_children_per_parent", "max_active_children_per_parent", "delegation_version",
            }
            payload = _payload(event, required)
            root = payload["parent_root_attempt_id"]
            if payload["expected_delegation_version"] != state.delegation_version(root):
                raise R25Error("R2_5_EVENT_INVALID", "Delegation history version is not contiguous")
            if payload["expected_active_child_count"] != state.active_child_count(root):
                raise R25Error("R2_5_EVENT_INVALID", "active-child count is not derived from prior facts")
            if payload["delegation_version"] != payload["expected_delegation_version"] + 1:
                raise R25Error("R2_5_EVENT_INVALID", "Delegation version is not contiguous")
            delegation = DelegationRecord(
                delegation_id=event.entity_id, mission_id=event.mission_id,
                parent_root_attempt_id=root, parent_attempt_id=payload["parent_attempt_id"],
                parent_task_id=payload["parent_task_id"], child_task_id=payload["child_task_id"],
                child_root_attempt_id=payload["child_root_attempt_id"], logical_agent_id=payload["logical_agent_id"],
                delegation_version=payload["delegation_version"],
                max_total_children_per_parent=payload["max_total_children_per_parent"],
                max_active_children_per_parent=payload["max_active_children_per_parent"],
                created_seq=event.seq, created_at=event.created_at,
                created_by={"type": event.initiator_type, "id": event.initiator_id},
            )
            if state.delegation(delegation.delegation_id) is not None:
                raise R25Error("R2_5_EVENT_INVALID", "Delegation identity is not immutable")
            delegations = state.delegations + (delegation,)
        elif event.event_type == CHILD_RESULT_RECORDED:
            required = {
                "child_result_id", "delegation_id", "parent_root_attempt_id", "child_task_id", "child_attempt_id",
                "child_root_attempt_id", "plan_revision_id", "terminal_state", "result_ref", "result_digest",
                "canonical_source_seq", "outcome",
            }
            payload = _payload(event, required)
            delegation = state.delegation(payload["delegation_id"])
            if delegation is None or any(item.delegation_id == delegation.delegation_id for item in state.child_results):
                raise R25Error("R2_5_EVENT_INVALID", "ChildResult is not immutable or has no Delegation")
            result = ChildResultRecord(
                child_result_id=event.entity_id, mission_id=event.mission_id,
                delegation_id=payload["delegation_id"], parent_root_attempt_id=payload["parent_root_attempt_id"],
                child_task_id=payload["child_task_id"], child_attempt_id=payload["child_attempt_id"],
                child_root_attempt_id=payload["child_root_attempt_id"], plan_revision_id=payload["plan_revision_id"],
                terminal_state=payload["terminal_state"], result_ref=payload["result_ref"],
                result_digest=payload["result_digest"], canonical_source_seq=payload["canonical_source_seq"],
                outcome=payload["outcome"], recorded_seq=event.seq, recorded_at=event.created_at,
                recorded_by={"type": event.initiator_type, "id": event.initiator_id},
            )
            results = state.child_results + (result,)
        elif event.event_type == JOINED:
            required = {"join_id", "parent_root_attempt_id", "delegation_id", "child_result_id", "expected_join_version", "join_version", "metadata"}
            payload = _payload(event, required)
            root = payload["parent_root_attempt_id"]
            delegation = state.delegation(payload["delegation_id"])
            if delegation is None:
                raise R25Error("R2_5_EVENT_INVALID", "Join references a missing Delegation")
            if payload["expected_join_version"] != state.join_version(delegation.delegation_id) or payload["join_version"] != payload["expected_join_version"] + 1:
                raise R25Error("R2_5_EVENT_INVALID", "Join version is not contiguous")
            if state.child_result(payload["child_result_id"]) is None:
                raise R25Error("R2_5_EVENT_INVALID", "Join references missing immutable facts")
            join = JoinRecord(
                join_id=event.entity_id, mission_id=event.mission_id, parent_root_attempt_id=root,
                delegation_id=payload["delegation_id"], child_result_id=payload["child_result_id"],
                join_version=payload["join_version"], joined_seq=event.seq, joined_at=event.created_at,
                joined_by={"type": event.initiator_type, "id": event.initiator_id}, metadata=payload["metadata"],
            )
            if state.join(join.join_id) is not None:
                raise R25Error("R2_5_EVENT_INVALID", "Join identity is not immutable")
            joins = state.joins + (join,)
        else:
            raise R25Error("EXTENSION_EVENT_NOT_OWNED", f"unsupported R2.5 event: {event.event_type}")
        return replace(state, bindings=bindings, delegations=delegations, child_results=results, joins=joins)
