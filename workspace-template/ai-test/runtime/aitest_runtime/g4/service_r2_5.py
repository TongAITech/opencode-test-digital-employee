from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.common import now_iso
from aitest_runtime.durable_core import RuntimeError

from .goal_transitions import LEGAL_GOAL_TRANSITIONS, TERMINAL_GOAL_STATUSES
from .service_r2_4 import *  # noqa: F401,F403
from .service_r2_4 import G4RealExecutionService as _R2_4_G4RealExecutionService
from .service_base import _dict, _human_state, _text


class G4RealExecutionService(_R2_4_G4RealExecutionService):
    """R2-5: legal TestingGoal transitions plus pre-mutation terminal locking."""

    def assert_goal_mutable(
        self,
        mission_id: str,
        goal_id: str,
        *,
        mutation: str,
        error_code: str = "G4_TERMINAL_GOAL_MUTATION_FORBIDDEN",
    ) -> str:
        """Fail closed before any goal-scoped durable write or external side effect."""
        goal_id = _text(goal_id, "goal_id")
        current = self.goal_status(mission_id, goal_id)
        if current in TERMINAL_GOAL_STATUSES:
            raise RuntimeError(error_code, f"{goal_id}:{current}:{mutation}")
        return current

    def _goal_id_for_execution_request(self, mission_id: str, request: Mapping[str, Any]) -> str:
        """Resolve the goal through the governed ExecutionBatch using R1 truth only."""
        data = _dict(request, "request")
        attempt = self._canonical_attempt(
            mission_id,
            _text(data.get("attempt_id"), "attempt_id"),
            _text(data.get("task_id"), "task_id"),
        )
        binding = self._validate_governed_execution(mission_id, data, attempt=attempt)
        batch = self.state(mission_id).by_id(binding.execution_batch_fact_id)
        if batch is None or batch.fact_kind != "EXECUTION_BATCH":
            raise RuntimeError("G4_EXECUTION_BINDING_REQUIRED", binding.execution_batch_fact_id)
        return _text(batch.payload.get("goal_id"), "goal_id")

    def _goal_id_for_gate(self, mission_id: str, gate_id: str) -> str | None:
        binding = self.state(mission_id).latest(
            "HUMAN_GATE_BINDING",
            lambda fact: fact.payload.get("gate_id") == gate_id,
        )
        if binding is None or not binding.payload.get("goal_id"):
            return None
        return str(binding.payload.get("goal_id"))

    def _set_goal_status(
        self,
        mission_id: str,
        goal_id: str,
        status: str,
        *,
        reason: str,
        provenance_refs: tuple[str, ...] | list[str] = (),
    ) -> dict[str, Any]:
        target = str(status).upper()
        if target not in GOAL_STATUSES:
            raise RuntimeError("G4_GOAL_STATUS_INVALID", target)
        current_fact = self._goal_status_fact(mission_id, goal_id)
        current = (
            str(current_fact.payload.get("status"))
            if current_fact is not None
            else str(self.goal(mission_id, goal_id)["payload"].get("status") or "ACTIVE")
        ).upper()
        allowed = LEGAL_GOAL_TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            raise RuntimeError("G4_GOAL_TRANSITION_FORBIDDEN", f"{current}->{target}")
        if current_fact is not None and current == target and current in TERMINAL_GOAL_STATUSES:
            return current_fact.to_dict()
        payload = {
            "goal_id": goal_id,
            "status": target,
            "from_status": current,
            "reason": reason,
            "transition_source_seq": self.runtime.get_head_seq(mission_id),
            "observed_at": now_iso(),
        }
        return self._record(
            mission_id,
            "TESTING_GOAL_STATUS",
            payload,
            provenance_refs=tuple(provenance_refs),
        )

    def create_batch(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        self.assert_goal_mutable(mission_id, _text(data.get("goal_id"), "goal_id"), mutation="create_batch")
        return super().create_batch(mission_id, data)

    def create_focused_execution_binding(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        self.assert_goal_mutable(
            mission_id,
            _text(data.get("goal_id"), "goal_id"),
            mutation="create_focused_execution_binding",
        )
        return super().create_focused_execution_binding(mission_id, data)

    def record_cursor(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        goal_id = self._goal_id_for_execution_request(mission_id, data)
        self.assert_goal_mutable(mission_id, goal_id, mutation="record_cursor")
        return super().record_cursor(mission_id, data)

    def execute_capability(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        goal_id = self._goal_id_for_execution_request(mission_id, data)
        self.assert_goal_mutable(mission_id, goal_id, mutation="execute_capability")
        return super().execute_capability(mission_id, data)

    def capability_human_gate(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        if data.get("goal_id"):
            self.assert_goal_mutable(mission_id, str(data["goal_id"]), mutation="capability_human_gate")
        return super().capability_human_gate(mission_id, data)

    def request_human_takeover(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        if data.get("goal_id"):
            self.assert_goal_mutable(mission_id, str(data["goal_id"]), mutation="request_human_takeover")
        return super().request_human_takeover(mission_id, data)

    def reconcile_human_takeover(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        gate_id = _text(data.get("human_gate_id"), "human_gate_id")
        goal_id = self._goal_id_for_gate(mission_id, gate_id)
        if goal_id:
            self.assert_goal_mutable(mission_id, goal_id, mutation="reconcile_human_takeover")
        return super().reconcile_human_takeover(mission_id, data)

    def complete_human_takeover(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        gate_id = data.get("human_gate_id")
        if gate_id:
            goal_id = self._goal_id_for_gate(mission_id, str(gate_id))
            if goal_id:
                self.assert_goal_mutable(mission_id, goal_id, mutation="complete_human_takeover")
        else:
            human_state = _human_state(self.runtime, mission_id)
            compatible = [
                gate for gate in getattr(human_state, "gates", ())
                if gate.status == "PENDING" and gate.mission_id == mission_id and gate.gate_kind == "EXTERNAL_ACTION"
            ]
            # Exact selection remains the superclass responsibility. This loop only
            # blocks terminal-goal candidates before any reconciliation/write.
            for gate in compatible:
                goal_id = self._goal_id_for_gate(mission_id, gate.gate_id)
                if goal_id:
                    self.assert_goal_mutable(mission_id, goal_id, mutation="complete_human_takeover")
        return super().complete_human_takeover(mission_id, data)

    def resolve_human_gate_user_turn(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        compatible = self._compatible_explicit_human_gates(mission_id)
        if len(compatible) == 1:
            goal_id = self._goal_id_for_gate(mission_id, compatible[0][0].gate_id)
            if goal_id:
                self.assert_goal_mutable(mission_id, goal_id, mutation="resolve_human_gate_user_turn")
        return super().resolve_human_gate_user_turn(mission_id, request)

    def record_coverage_from_g3(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        goal_id = _text(data.get("goal_id"), "goal_id")
        self.assert_goal_mutable(
            mission_id,
            goal_id,
            mutation="record_coverage_from_g3",
            error_code="G4_TERMINAL_GOAL_NEW_MEASUREMENT_REQUIRES_NEW_GOAL",
        )
        return super().record_coverage_from_g3(mission_id, data)

    def record_blocker_gap(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        self.assert_goal_mutable(mission_id, _text(data.get("goal_id"), "goal_id"), mutation="record_blocker_gap")
        return super().record_blocker_gap(mission_id, data)

    def record_risk_acceptance(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        self.assert_goal_mutable(mission_id, _text(data.get("goal_id"), "goal_id"), mutation="record_risk_acceptance")
        return super().record_risk_acceptance(mission_id, data)

    def record_iteration(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        self.assert_goal_mutable(mission_id, _text(data.get("goal_id"), "goal_id"), mutation="record_iteration")
        return super().record_iteration(mission_id, data)

    def request_g3_replan(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        self.assert_goal_mutable(mission_id, _text(data.get("goal_id"), "goal_id"), mutation="request_g3_replan")
        return super().request_g3_replan(mission_id, data)

    def evaluate_goal(self, mission_id: str, goal_id: str) -> dict[str, Any]:
        current = self.goal_status(mission_id, goal_id)
        if current in TERMINAL_GOAL_STATUSES:
            latest = self.state(mission_id).latest(
                "GOAL_EVALUATION",
                lambda fact: fact.payload.get("goal_id") == goal_id and fact.payload.get("status") == current,
            )
            return {
                "status": current,
                "truth_source": "R1_EVENT_STREAM",
                "evaluation": latest.to_dict() if latest is not None else None,
                "goal_status": self._goal_status_fact(mission_id, goal_id).to_dict() if self._goal_status_fact(mission_id, goal_id) is not None else None,
                "terminal_state_locked": True,
            }
        return super().evaluate_goal(mission_id, goal_id)
