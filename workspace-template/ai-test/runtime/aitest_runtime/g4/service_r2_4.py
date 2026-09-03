from __future__ import annotations

import re
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError, canonical_sha256

from .service_r2_3 import *  # noqa: F401,F403
from .service_r2_3 import (
    G4RealExecutionService as _R2_3_G4RealExecutionService,
    TestObjectiveController as _R2_3_TestObjectiveController,
)
from .service_base import _human_state


_COMPLETION_INTENTS = frozenset(
    {
        "完成",
        "好了",
        "已完成",
        "已登录",
        "操作完成",
        "登录完成",
        "done",
        "completed",
        "loggedin",
        "logincomplete",
    }
)


def _completion_intent(text: Any) -> bool:
    if not isinstance(text, str):
        return False
    normalized = re.sub(r"[\s\u3000，。！？!?,.;；:：]+", "", text.strip().lower())
    return normalized in _COMPLETION_INTENTS


class G4RealExecutionService(_R2_3_G4RealExecutionService):
    """R2-4 HumanGate resume seams.

    Explicit user-turn resume and AUTO background resume are deliberately separate.
    User text is never completion authority: it can only request runtime verification.
    """

    def request_human_takeover(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        result = super().request_human_takeover(mission_id, request)
        if result.get("status") == "WAITING_HUMAN":
            return {
                **result,
                "ai_turn": "YIELD",
                "blocking_tool_call": False,
                "chat_input": "ENABLED",
                "browser_observer": "ENABLED",
                "ai_browser_actuation": "DISABLED",
                "new_user_turn_required": True,
                "resume_instruction": "请在当前受控浏览器完成操作，完成后在当前可输入的OpenCode会话发送‘完成’。",
            }
        return result

    def _compatible_explicit_human_gates(self, mission_id: str) -> list[tuple[Any, Any]]:
        human_state = _human_state(self.runtime, mission_id)
        compatible: list[tuple[Any, Any]] = []
        for gate in getattr(human_state, "gates", ()):
            if gate.status != "PENDING" or gate.mission_id != mission_id or gate.gate_kind != "EXTERNAL_ACTION":
                continue
            takeover = self.state(mission_id).latest(
                "HUMAN_TAKEOVER_REQUEST",
                lambda fact: fact.payload.get("human_gate_id") == gate.gate_id,
            )
            if takeover is None:
                continue
            resume_mode = str(takeover.payload.get("resume_mode") or "AUTO_OR_EXPLICIT").upper()
            if resume_mode not in {"EXPLICIT", "AUTO_OR_EXPLICIT"}:
                continue
            if str(takeover.payload.get("status") or "").upper() not in {
                "HUMAN_CONTROLLED",
                "TAKEOVER_REQUESTED",
                "BLOCKED",
            }:
                continue
            compatible.append((gate, takeover))
        return compatible

    def resolve_human_gate_user_turn(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        """Resolve a new OpenCode User Turn against durable R1 HumanGate truth.

        The resolver intentionally receives no conversation-history binding. A completion
        phrase creates only REQUEST_TO_VERIFY_COMPLETION. Exact gate selection comes from
        the current Mission's durable pending HumanGates; browser/SUT fresh verification
        remains the only completion authority.
        """
        data = dict(request)
        user_text = data.get("user_text") if "user_text" in data else data.get("message")
        if not _completion_intent(user_text):
            return {
                "status": "NO_MATCH",
                "truth_source": "R1_EVENT_STREAM",
                "intent": "NOT_A_COMPLETION_INTENT",
                "conversation_history_dependency": False,
                "user_text_authoritative": False,
            }

        compatible = self._compatible_explicit_human_gates(mission_id)
        if not compatible:
            return {
                "status": "NO_PENDING_HUMAN_GATE",
                "truth_source": "R1_EVENT_STREAM",
                "intent": "REQUEST_TO_VERIFY_COMPLETION",
                "compatible_gate_refs": [],
                "conversation_history_dependency": False,
                "user_text_authoritative": False,
            }
        if len(compatible) != 1:
            return {
                "status": "CLARIFICATION_REQUIRED",
                "truth_source": "R1_EVENT_STREAM",
                "intent": "REQUEST_TO_VERIFY_COMPLETION",
                "reason": "MULTIPLE_COMPATIBLE_PENDING_HUMAN_GATES",
                "compatible_gate_refs": sorted(gate.gate_id for gate, _ in compatible),
                "conversation_history_dependency": False,
                "user_text_authoritative": False,
            }

        gate, takeover = compatible[0]
        user_turn_digest = canonical_sha256(
            {
                "mission_id": mission_id,
                "gate_id": gate.gate_id,
                "intent": "REQUEST_TO_VERIFY_COMPLETION",
                "text": str(user_text),
            }
        )
        request_fact = self._record(
            mission_id,
            "HUMAN_GATE_USER_TURN_RESUME_REQUEST",
            {
                "gate_id": gate.gate_id,
                "task_id": gate.task_id,
                "root_attempt_id": gate.root_attempt_id,
                "takeover_ref": takeover.fact_id,
                "intent": "REQUEST_TO_VERIFY_COMPLETION",
                "user_turn_digest": user_turn_digest,
                "raw_user_text_persisted": False,
                "user_text_authoritative": False,
                "completion_authority": "BROWSER_RUNTIME_FRESH_VERIFICATION",
            },
            provenance_refs=(f"r2.6:{gate.gate_id}", takeover.fact_id),
        )
        try:
            result = self.complete_human_takeover(
                mission_id,
                {
                    "human_gate_id": gate.gate_id,
                    "completion_mode": "EXPLICIT",
                    "actor_id": str(data.get("actor_id") or "opencode-user-turn"),
                    "decision_id": str(data.get("decision_id") or f"g4-user-turn:{user_turn_digest[:24]}"),
                },
            )
        except RuntimeError as exc:
            if exc.code in {
                "G4_HUMAN_RESUME_REVALIDATION_FAILED",
                "G4_HUMAN_RESUME_RUNTIME_VERIFICATION_FAILED",
                "G4_RESUME_CONDITION_VERIFIER_REQUIRED",
                "G4_HUMAN_RESUME_LEASE_INVALID",
                "G4_BROWSER_CONTEXT_REPLACED_DURING_HUMAN_CONTROL",
            }:
                current = _human_state(self.runtime, mission_id)
                durable_gate = current.gate(gate.gate_id) if current is not None and hasattr(current, "gate") else None
                return {
                    "status": "WAITING_HUMAN",
                    "truth_source": "R1_EVENT_STREAM",
                    "intent": "REQUEST_TO_VERIFY_COMPLETION",
                    "verification": "NOT_YET_COMPLETE",
                    "verification_error": exc.code,
                    "human_gate": durable_gate.to_dict() if durable_gate is not None else gate.to_dict(),
                    "resume_request": request_fact,
                    "completion_authority": "BROWSER_RUNTIME_FRESH_VERIFICATION",
                    "conversation_history_dependency": False,
                    "user_text_authoritative": False,
                }
            raise
        return {
            **result,
            "intent": "REQUEST_TO_VERIFY_COMPLETION",
            "resume_request": request_fact,
            "completion_authority": "BROWSER_RUNTIME_FRESH_VERIFICATION",
            "conversation_history_dependency": False,
            "user_text_authoritative": False,
        }

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
    """Objective tick keeps AUTO reconciliation as a compatibility path."""

    def tick(self, mission_id: str, goal_id: str, *, replan_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        auto_resume = self.service.auto_resume_human_gates(mission_id)
        result = super().tick(mission_id, goal_id, replan_context=replan_context)
        return {**result, "auto_resume": auto_resume}
