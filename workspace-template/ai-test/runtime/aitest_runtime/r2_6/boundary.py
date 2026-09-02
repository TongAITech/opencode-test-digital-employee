from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aitest_runtime.durable_core import RuntimeService

from .contracts import (
    APPLIED,
    BLOCK,
    CANCELLED,
    CONTINUATION_PENDING,
    EXPIRED,
    GOAL_REVISION,
    PLAN_REVISION,
    PENDING,
    RESOLVED,
    RESUME_EXECUTION,
    R26Error,
)
from .service import HumanGateApplicationService


ALLOW = "ALLOW"
WAIT = "WAIT"
ROUTE_REVISION = "ROUTE_REVISION"


@dataclass(frozen=True)
class HumanGateBoundaryDecision:
    decision: str
    mission_id: str
    task_id: str
    root_attempt_id: str
    gate_id: str | None = None
    route: str | None = None
    reason_code: str | None = None
    requires_reobserve: bool = False

    @property
    def allows_scheduler(self) -> bool:
        return self.decision == ALLOW


def evaluate_human_gate_boundary(
    runtime_service: RuntimeService,
    *,
    mission_id: str,
    task_id: str,
    root_attempt_id: str,
) -> HumanGateBoundaryDecision:
    state = HumanGateApplicationService(runtime_service).state(mission_id)
    gate = state.current_cycle(mission_id, task_id, root_attempt_id)
    if gate is None:
        # An APPLIED continuation is no longer a blocking current cycle, but
        # it remains the latest canonical Gate fact that requires the caller
        # to re-observe Goal/Plan/WorkGraph before entering R2.4.
        binding_gates = [
            item for item in state.gates
            if item.binding == (mission_id, task_id, root_attempt_id)
        ]
        latest = max(binding_gates, key=lambda item: item.created_seq, default=None)
        if latest is not None and latest.status == RESOLVED and latest.continuation_state == APPLIED:
            return HumanGateBoundaryDecision(
                ALLOW, mission_id, task_id, root_attempt_id, latest.gate_id,
                latest.continuation_route, "R2_6_CONTINUATION_APPLIED", True,
            )
        return HumanGateBoundaryDecision(ALLOW, mission_id, task_id, root_attempt_id)
    if gate.status == PENDING:
        return HumanGateBoundaryDecision(WAIT, mission_id, task_id, root_attempt_id, gate.gate_id, gate.continuation_route, "R2_6_HUMAN_GATE_PENDING")
    if gate.status in {CANCELLED, EXPIRED} or gate.continuation_route == BLOCK or gate.decision_outcome == "REJECTED":
        return HumanGateBoundaryDecision(BLOCK, mission_id, task_id, root_attempt_id, gate.gate_id, gate.continuation_route, "R2_6_HUMAN_GATE_BLOCKED")
    if gate.status == RESOLVED and gate.continuation_state == CONTINUATION_PENDING:
        if gate.continuation_route in {GOAL_REVISION, PLAN_REVISION}:
            return HumanGateBoundaryDecision(ROUTE_REVISION, mission_id, task_id, root_attempt_id, gate.gate_id, gate.continuation_route, "R2_6_REVISION_REQUIRED")
        return HumanGateBoundaryDecision(WAIT, mission_id, task_id, root_attempt_id, gate.gate_id, gate.continuation_route, "R2_6_CONTINUATION_PENDING")
    if gate.status == RESOLVED and gate.continuation_state == APPLIED:
        return HumanGateBoundaryDecision(ALLOW, mission_id, task_id, root_attempt_id, gate.gate_id, gate.continuation_route, "R2_6_CONTINUATION_APPLIED", True)
    if gate.status == RESOLVED and gate.continuation_state == "NOT_REQUIRED":
        return HumanGateBoundaryDecision(ALLOW, mission_id, task_id, root_attempt_id, gate.gate_id, gate.continuation_route, "R2_6_DECISION_COMPLETE")
    raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "Human Gate boundary encountered an invalid replay state")


def run_r2_4_if_allowed(runtime_service: RuntimeService, request: Any, dispatcher: Any, *, task_id: str, root_attempt_id: str):
    decision = evaluate_human_gate_boundary(
        runtime_service,
        mission_id=request["mission_id"] if isinstance(request, dict) else request.mission_id,
        task_id=task_id,
        root_attempt_id=root_attempt_id,
    )
    if not decision.allows_scheduler:
        return decision
    from aitest_runtime.r2_4 import orchestrate_loop

    return orchestrate_loop(runtime_service, request, dispatcher)
