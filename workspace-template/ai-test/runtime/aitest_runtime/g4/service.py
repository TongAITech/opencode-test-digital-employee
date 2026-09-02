from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.common import now_iso
from aitest_runtime.durable_core import RuntimeError

from .goal_transitions import LEGAL_GOAL_TRANSITIONS, TERMINAL_GOAL_STATUSES
from .service_r2_4 import *  # noqa: F401,F403
from .service_r2_4 import G4RealExecutionService as _R2_4_G4RealExecutionService


class G4RealExecutionService(_R2_4_G4RealExecutionService):
    """R2-5: enforce legal durable TestingGoal transitions and terminal locking."""

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

    def record_coverage_from_g3(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        goal_id = _text(data.get("goal_id"), "goal_id")
        current = self.goal_status(mission_id, goal_id)
        if current in TERMINAL_GOAL_STATUSES:
            raise RuntimeError(
                "G4_TERMINAL_GOAL_NEW_MEASUREMENT_REQUIRES_NEW_GOAL",
                f"{goal_id}:{current}",
            )
        return super().record_coverage_from_g3(mission_id, data)

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
