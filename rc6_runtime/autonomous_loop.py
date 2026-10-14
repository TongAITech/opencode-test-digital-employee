from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from .mission import MissionRuntime, MissionState
from .orchestrator import AutonomousMissionOrchestrator, MissionDirective, MissionOrchestrationError


@dataclass(frozen=True)
class MissionActionOutcome:
    status: str
    gate_name: Optional[str] = None
    passed: Optional[bool] = None
    evidence_ref: Optional[str] = None
    reason: Optional[str] = None
    target_id: Optional[str] = None
    successor_session_ref: Optional[str] = None


@dataclass(frozen=True)
class MissionLoopResult:
    status: str
    mission_id: str
    stage: str
    steps: int
    coordinator_generation: int
    checkpoint_seq: int
    active_coordinator_session_ref: Optional[str]
    coordinator_session_refs: Tuple[str, ...]
    last_action: str
    blocking_reasons: Tuple[str, ...] = ()


class AutonomousMissionLoop:
    """Runtime-owned same-Mission drive loop.

    The caller starts it once. It keeps advancing from durable state, applies
    handler outcomes through stage-bound Runtime gates, performs strict
    checkpoint/successor handoff under context pressure, and only stops for a
    durable COMPLETE state or an actual runtime/environment block. It never
    requires a human 'continue' message to move to the next legal Stage.
    """

    VALID_OUTCOMES = {"COMPLETED", "BLOCKED", "ROTATED"}

    def __init__(
        self,
        orchestrator: AutonomousMissionOrchestrator,
        missions: MissionRuntime,
        action_handler: Callable[[MissionDirective], MissionActionOutcome],
        context_pressure: Optional[Callable[[MissionState], bool]] = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.missions = missions
        self.action_handler = action_handler
        self.context_pressure = context_pressure or (lambda state: False)

    def run(self, mission_id: str, *, max_steps: int = 128) -> MissionLoopResult:
        if max_steps <= 0:
            raise MissionOrchestrationError("INVALID_MAX_STEPS")
        last_action = "NONE"
        for step in range(1, max_steps + 1):
            before = self.missions.load(mission_id)
            pressure = bool(self.context_pressure(before))
            directive = self.orchestrator.control_tick(mission_id, context_pressure=pressure)
            last_action = directive.action
            if directive.action == "COMPLETE":
                return self._result("COMPLETE", mission_id, step, last_action)

            outcome = self.action_handler(directive)
            if outcome.status not in self.VALID_OUTCOMES:
                raise MissionOrchestrationError("INVALID_ACTION_OUTCOME")

            if directive.action == "ROTATE_SESSION":
                if outcome.status != "ROTATED" or not outcome.successor_session_ref:
                    raise MissionOrchestrationError("SUCCESSOR_SESSION_REQUIRED")
                pending = self.missions.load(mission_id)
                if not pending.successor_pending:
                    raise MissionOrchestrationError("ROTATION_CHECKPOINT_MISSING")
                self.missions.activate_successor(pending, outcome.successor_session_ref)
                continue

            if outcome.status == "ROTATED":
                raise MissionOrchestrationError("UNEXPECTED_SESSION_ROTATION")
            if outcome.status == "BLOCKED":
                return self._result(
                    "BLOCKED",
                    mission_id,
                    step,
                    last_action,
                    tuple(x for x in (outcome.reason,) if x),
                )

            if outcome.target_id:
                self.orchestrator.bind_target(mission_id, outcome.target_id)
            if outcome.gate_name:
                if outcome.passed is True:
                    if not outcome.evidence_ref:
                        raise MissionOrchestrationError("GATE_EVIDENCE_REF_REQUIRED")
                    self.orchestrator.record_verified_gate(
                        mission_id, outcome.gate_name, outcome.evidence_ref
                    )
                elif outcome.passed is False:
                    self.orchestrator.record_gate_blocked(
                        mission_id, outcome.gate_name, outcome.reason or "RUNTIME_GATE_BLOCKED"
                    )
                else:
                    raise MissionOrchestrationError("GATE_DECISION_REQUIRED")

            after = self.missions.load(mission_id)
            if self._fingerprint(after) == self._fingerprint(before):
                raise MissionOrchestrationError("NO_DURABLE_PROGRESS")

        return self._result(
            "BLOCKED",
            mission_id,
            max_steps,
            last_action,
            ("AUTONOMOUS_STEP_BUDGET_EXHAUSTED",),
        )

    def _result(
        self,
        status: str,
        mission_id: str,
        steps: int,
        last_action: str,
        blocking: Tuple[str, ...] = (),
    ) -> MissionLoopResult:
        state = self.missions.load(mission_id)
        return MissionLoopResult(
            status=status,
            mission_id=mission_id,
            stage=state.stage,
            steps=steps,
            coordinator_generation=state.coordinator_generation,
            checkpoint_seq=state.checkpoint_seq,
            active_coordinator_session_ref=state.active_coordinator_session_ref,
            coordinator_session_refs=tuple(state.coordinator_session_refs),
            last_action=last_action,
            blocking_reasons=blocking,
        )

    @staticmethod
    def _fingerprint(state: MissionState) -> tuple:
        return (
            state.stage,
            tuple(state.completed_gates),
            tuple(state.open_gaps),
            state.target_identity_ref,
            state.checkpoint_seq,
            state.coordinator_generation,
            state.active_coordinator_session_ref,
            tuple(state.coordinator_session_refs),
            state.successor_pending,
        )
