from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError

from .service_r2_3 import *  # noqa: F401,F403
from .service_r2_3 import (
    G4RealExecutionService as _R2_3_G4RealExecutionService,
    TestObjectiveController as _R2_3_TestObjectiveController,
    _human_state,
)


class G4RealExecutionService(_R2_3_G4RealExecutionService):
    """R2-4: non-LLM durable HumanGate AUTO/AUTO_OR_EXPLICIT supervisor."""

    def auto_resume_human_gates(self, mission_id: str) -> dict[str, Any]:
        if self.browser_provider is None or self.browser_supervisor is None:
            return {
                "status": "UNAVAILABLE",
                "truth_source": "R1_EVENT_STREAM",
                "resumed_gate_refs": [],
                "pending_gate_refs": [],
                "reason": "BROWSER_RESUME_SUPERVISOR_NOT_BOUND",
                "conversation_dependency": False,
            }
        human_state = _human_state(self.runtime, mission_id)
        pending = [
            gate for gate in getattr(human_state, "gates", ())
            if gate.status == "PENDING" and gate.mission_id == mission_id
        ]
        resumed: list[str] = []
        waiting: list[dict[str, str]] = []
        for gate in pending:
            takeover = self.state(mission_id).latest(
                "HUMAN_TAKEOVER_REQUEST",
                lambda fact: fact.payload.get("human_gate_id") == gate.gate_id,
            )
            if takeover is None:
                continue
            resume_mode = str(takeover.payload.get("resume_mode") or "AUTO_OR_EXPLICIT").upper()
            if resume_mode not in {"AUTO", "AUTO_OR_EXPLICIT"}:
                continue
            try:
                result = self.complete_human_takeover(
                    mission_id,
                    {
                        "human_gate_id": gate.gate_id,
                        "completion_mode": "AUTO",
                        "actor_id": "g4-browser-human-gate-supervisor",
                    },
                )
            except RuntimeError as exc:
                if exc.code in {
                    "G4_HUMAN_RESUME_REVALIDATION_FAILED",
                    "G4_HUMAN_RESUME_RUNTIME_VERIFICATION_FAILED",
                    "G4_RESUME_CONDITION_VERIFIER_REQUIRED",
                    "G4_HUMAN_RESUME_LEASE_INVALID",
                }:
                    waiting.append({"gate_id": gate.gate_id, "reason": exc.code})
                    continue
                raise
            if result.get("status") == "RESUME_SAFE":
                resumed.append(gate.gate_id)
            else:
                waiting.append({"gate_id": gate.gate_id, "reason": str(result.get("status") or "BLOCKED")})
        return {
            "status": "RESUMED" if resumed else ("WAITING" if waiting else "NOOP"),
            "truth_source": "R1_EVENT_STREAM",
            "resumed_gate_refs": resumed,
            "pending_gate_refs": waiting,
            "conversation_dependency": False,
        }


class TestObjectiveController(_R2_3_TestObjectiveController):
    """Objective tick also drives the background HumanGate observer before evaluation."""

    def tick(self, mission_id: str, goal_id: str, *, replan_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        auto_resume = self.service.auto_resume_human_gates(mission_id)
        result = super().tick(mission_id, goal_id, replan_context=replan_context)
        return {**result, "auto_resume": auto_resume}
