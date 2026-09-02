from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeService, canonical_sha256
from aitest_runtime.r2_3 import PlannerInput

from .contracts import (
    BridgeStatus,
    PlanRevisionIntent,
    PlanRevisionBridgeReceipt,
    ref_for,
)
from .errors import R2_BRIDGE_REJECTED, R2_BRIDGE_UNAVAILABLE, R2_RESULT_CONFLICT, R42Error


def _result_value(result: Any, name: str, default: Any = None) -> Any:
    if isinstance(result, Mapping):
        return result.get(name, default)
    return getattr(result, name, default)


def planner_input_digest(value: PlannerInput | Mapping[str, Any]) -> str:
    item = PlannerInput.from_mapping(value)
    return canonical_sha256(item.to_mapping())


def build_planner_input(
    runtime_service: RuntimeService,
    *,
    mission_id: str,
    planner_request_id: str,
    planner_input: PlannerInput | Mapping[str, Any] | None = None,
    planning_cursor: int | None = None,
) -> PlannerInput:
    if planner_input is not None:
        item = PlannerInput.from_mapping(planner_input)
    else:
        state = runtime_service.get_state(mission_id)
        mission = state.mission
        if mission is None or mission.active_goal_id is None:
            raise R42Error(R2_BRIDGE_REJECTED, "R2 durable Mission has no active Goal")
        goal = state.goal(mission.active_goal_id)
        if goal is None:
            raise R42Error(R2_BRIDGE_REJECTED, "R2 durable active Goal is unavailable")
        definition = dict(goal.definition)
        scope_digest = definition.get("scope_digest")
        if not isinstance(scope_digest, str) or not scope_digest.strip():
            scope_digest = canonical_sha256(definition.get("execution_scope", definition.get("scope", {})))
        item = PlannerInput(
            mission_id=mission_id,
            active_goal_id=goal.goal_id,
            goal_revision=goal.revision,
            goal_definition_digest=canonical_sha256(goal.definition),
            scope_digest=scope_digest,
            planning_cursor=runtime_service.get_head_seq(mission_id) if planning_cursor is None else planning_cursor,
            planner_request_id=planner_request_id,
            goal_definition=definition,
            objective=definition.get("objective") or definition.get("statement") or "Execute the active Goal",
            constraints=definition.get("constraints", ()),
            task_definitions=definition.get("task_definitions", definition.get("tasks", ())),
            dependencies=definition.get("dependencies", ()),
            actor={"type": "SYSTEM", "id": "r4.2-bridge"},
            operation="REVISE",
            goal_mutation_required=False,
            scope_mutation_required=False,
            blocked=False,
            blockers=(),
            current_content_hash=None,
            current_revision_id=None,
            existing_plan_id=None,
            no_change=False,
        )
    if item.mission_id != mission_id:
        raise R42Error(R2_BRIDGE_REJECTED, "PlannerInput mission_id differs from target Mission")
    if item.planner_request_id != planner_request_id:
        raise R42Error(R2_BRIDGE_REJECTED, "PlannerInput planner_request_id differs from durable intent")
    if item.goal_mutation_required or item.scope_mutation_required:
        raise R42Error(R2_BRIDGE_REJECTED, "selection intent cannot be represented without Goal or Scope mutation")
    return item


def invoke_planner(planner: Any, item: PlannerInput) -> Any:
    method = getattr(planner, "plan_or_revise", None)
    if not callable(method):
        if callable(planner):
            method = planner
        else:
            raise R42Error(R2_BRIDGE_UNAVAILABLE, "PlannerOrchestrator.plan_or_revise is unavailable")
    # Frozen boundary: one native PlannerInput positional argument only.
    return method(item)


def planner_outcome_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)
    method = getattr(result, "to_dict", None)
    if callable(method):
        value = method()
        if isinstance(value, Mapping):
            return dict(value)
    return {
        "outcome": _result_value(result, "outcome"),
        "plan_id": _result_value(result, "plan_id"),
        "revision_id": _result_value(result, "revision_id"),
        "content_hash": _result_value(result, "content_hash"),
        "reason_code": _result_value(result, "reason_code"),
        "reason": _result_value(result, "reason"),
    }


def map_planner_outcome(
    result: Any,
    *,
    mission_id: str,
    planner_input: PlannerInput,
    observed_at: str,
    correlation_id: str,
) -> dict[str, Any]:
    payload = planner_outcome_payload(result)
    outcome = str(payload.get("outcome") or payload.get("status") or "REJECTED")
    cursor = payload.get("last_seq")
    if cursor is None:
        command_results = payload.get("command_results") or ()
        if command_results:
            last = command_results[-1]
            cursor = _result_value(last, "last_seq")
    if not isinstance(cursor, int):
        cursor = None
    plan_id = payload.get("plan_id")
    revision_id = payload.get("revision_id") or payload.get("plan_revision_id")
    content_hash = payload.get("content_hash")
    if isinstance(content_hash, str) and len(content_hash) != 64:
        content_hash = canonical_sha256(content_hash)
    plan_ref = None
    revision_ref = None
    if plan_id:
        plan_ref = ref_for("R2_PLAN", str(plan_id), digest=canonical_sha256({"plan_id": str(plan_id)}), cursor=cursor, observed_at=observed_at, correlation_id=correlation_id, origin="r2.3.plan")
    if revision_id:
        revision_digest = content_hash if isinstance(content_hash, str) and len(content_hash) == 64 else canonical_sha256({"revision_id": str(revision_id), "result": payload})
        revision_ref = ref_for("R2_PLAN_REVISION", str(revision_id), digest=revision_digest, cursor=cursor, observed_at=observed_at, correlation_id=correlation_id, origin="r2.3.plan_revision")
    if outcome in {"APPLIED", "DUPLICATE"}:
        status = BridgeStatus.R2_REVISION_LINKED
    elif outcome == "NO_CHANGE":
        status = BridgeStatus.R2_NO_CHANGE
    elif outcome in {"BLOCKED", "GOAL_REVISION_REQUIRED", "REJECTED"}:
        status = BridgeStatus.R2_REJECTED
    else:
        status = BridgeStatus.R2_REJECTED
    return {
        "r2_outcome": outcome,
        "r2_plan_ref": plan_ref,
        "r2_revision_ref": revision_ref,
        "r2_content_hash": content_hash,
        "bridge_status": status,
        "r2_result_digest": canonical_sha256({"planner_input_digest": planner_input_digest(planner_input), "result": payload}),
        "reason_code": payload.get("reason_code"),
    }


__all__ = ["build_planner_input", "invoke_planner", "map_planner_outcome", "planner_input_digest", "planner_outcome_payload"]
