from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

from .mission import MissionRuntime, MissionState, ResumeEnvelope
from .stages import StageMachine, StageViolation
from .truth import TruthRuntime


class MissionOrchestrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MissionDirective:
    mission_id: str
    stage: str
    action: str
    required_role: Optional[str] = None
    layer: Optional[str] = None
    scope_ref: Optional[str] = None
    required_artifact_types: Tuple[str, ...] = ()
    required_tools: Tuple[str, ...] = ()
    blocking_reasons: Tuple[str, ...] = ()
    checkpoint_required: bool = False
    resume_envelope_ref: Optional[str] = None
    target_id: Optional[str] = None
    idempotency_key: str = ""


class AutonomousMissionOrchestrator:
    """Deterministic high-level Mission controller.

    The LLM may execute a directive, but it cannot choose the next professional
    phase. Stage movement is sequential and depends only on durable Mission
    gates. Chat/session state is never consulted.
    """

    GATE_STAGE: Dict[str, str] = {
        "REQUIREMENT_SUFFICIENT": "REQUIREMENT_ANALYSIS",
        "CODE_SUFFICIENT": "CODE_ANALYSIS",
        "FUSION_COMPLETE": "FUSION",
        "DESIGN_SUFFICIENT": "TEST_DESIGN",
        "ORACLE_SUFFICIENT": "TEST_DESIGN",
        "PROJECTION_INTEGRITY": "TEST_DESIGN",
        "TARGET_IDENTITY_READY": "TEST_DESIGN",
        "PREPARATION_READY": "PREPARATION",
        "EXECUTION_INTEGRITY": "EXECUTION",
        "COVERAGE_SUFFICIENT": "COVERAGE_CLOSURE",
        "REPORT_COMPLETE": "REPORTING",
    }

    def __init__(self, missions: MissionRuntime, truth: TruthRuntime):
        self.missions = missions
        self.truth = truth
        self.stages = StageMachine()

    def plan_next(self, mission_id: str, *, context_pressure: bool = False) -> MissionDirective:
        state = self.missions.load(mission_id)
        if context_pressure:
            return self._directive(
                state,
                "ROTATE_SESSION",
                blocking=("COORDINATOR_CONTEXT_PRESSURE",),
                checkpoint_required=True,
            )
        return self._directive_for_stage(state)

    def control_tick(self, mission_id: str, *, context_pressure: bool = False) -> MissionDirective:
        state = self.missions.load(mission_id)
        if context_pressure:
            envelope = self.missions.checkpoint(state)
            ref = self._resume_ref(envelope)
            return self._directive(
                self.missions.load(mission_id),
                "ROTATE_SESSION",
                blocking=("COORDINATOR_CONTEXT_PRESSURE",),
                checkpoint_required=True,
                resume_envelope_ref=ref,
            )

        # Mission existence itself is the deterministic registration proof.
        if state.stage == "REGISTERED" and "MISSION_REGISTERED" not in state.completed_gates:
            state.completed_gates.append("MISSION_REGISTERED")
            self.missions.save(state)

        next_stage = self._next_stage(state.stage)
        if next_stage and self.stages.can_enter(next_stage, state.completed_gates):
            state.stage = self.stages.enter(state.stage, next_stage, state.completed_gates)
            self.missions.save(state)
            state = self.missions.load(mission_id)
        return self._directive_for_stage(state)

    def record_verified_gate(self, mission_id: str, gate_name: str, evidence_ref: str) -> MissionState:
        state = self.missions.load(mission_id)
        expected_stage = self.GATE_STAGE.get(gate_name)
        if expected_stage is None:
            raise MissionOrchestrationError("UNKNOWN_OR_UNCOMMITTABLE_GATE")
        if state.stage != expected_stage:
            raise MissionOrchestrationError("GATE_STAGE_MISMATCH")
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            raise MissionOrchestrationError("GATE_EVIDENCE_REF_REQUIRED")
        if gate_name not in state.completed_gates:
            state.completed_gates.append(gate_name)
        gate_marker = "gate://%s/%s" % (gate_name.lower(), evidence_ref.strip())
        if gate_marker not in state.artifact_refs:
            state.artifact_refs.append(gate_marker)
        state.open_gaps = [g for g in state.open_gaps if g != "GATE_BLOCKED:" + gate_name]
        self.missions.save(state)
        return state

    def record_gate_blocked(self, mission_id: str, gate_name: str, reason: str) -> MissionState:
        state = self.missions.load(mission_id)
        expected_stage = self.GATE_STAGE.get(gate_name)
        if expected_stage is None or state.stage != expected_stage:
            raise MissionOrchestrationError("GATE_STAGE_MISMATCH")
        if gate_name in state.completed_gates:
            state.completed_gates.remove(gate_name)
        marker = "GATE_BLOCKED:" + gate_name
        if marker not in state.open_gaps:
            state.open_gaps.append(marker)
        if reason:
            reason_ref = "gap://%s/%s" % (gate_name.lower(), reason.strip())
            if reason_ref not in state.artifact_refs:
                state.artifact_refs.append(reason_ref)
        self.missions.save(state)
        return state

    def bind_target(self, mission_id: str, target_id: str) -> MissionState:
        state = self.missions.load(mission_id)
        if state.stage != "TEST_DESIGN":
            raise MissionOrchestrationError("TARGET_BIND_STAGE_MISMATCH")
        if not isinstance(target_id, str) or not target_id.startswith("TARGET-"):
            raise MissionOrchestrationError("INVALID_TARGET_ID")
        state.target_identity_ref = target_id
        if "TARGET_IDENTITY_READY" not in state.completed_gates:
            state.completed_gates.append("TARGET_IDENTITY_READY")
        self.missions.save(state)
        return state

    def _directive_for_stage(self, state: MissionState) -> MissionDirective:
        release = state.release_id
        inventory = self.truth.full_inventory()

        if state.stage == "REGISTERED":
            return self._directive(state, "CONTROL_TICK", blocking=("MISSION_REGISTRATION_TRANSITION_REQUIRED",))

        if state.stage == "REQUIREMENT_ANALYSIS":
            if inventory.get("requirement_analysis", 0) == 0:
                return self._directive(
                    state, "SPAWN_WORKER", role="REQUIREMENT_ANALYZER", scope=release,
                    artifacts=("requirement_analysis",), blocking=("REQUIREMENT_ANALYSIS_MISSING",),
                )
            if "REQUIREMENT_SUFFICIENT" not in state.completed_gates:
                return self._directive(
                    state, "RUN_GATE", role="REQUIREMENT_REVIEWER", scope=release,
                    artifacts=("requirement_analysis",), blocking=("REQUIREMENT_SUFFICIENCY_NOT_VERIFIED",),
                )

        if state.stage == "CODE_ANALYSIS":
            if inventory.get("code_analysis", 0) == 0:
                return self._directive(
                    state, "SPAWN_WORKER", role="CODE_ANALYZER", scope=release,
                    artifacts=("code_analysis",), tools=("git", "codegraph"), blocking=("CODE_ANALYSIS_MISSING",),
                )
            if "CODE_SUFFICIENT" not in state.completed_gates:
                return self._directive(
                    state, "RUN_GATE", role="CODE_REVIEWER", scope=release,
                    artifacts=("code_analysis",), tools=("git", "codegraph"), blocking=("CODE_SUFFICIENCY_NOT_VERIFIED",),
                )

        if state.stage == "FUSION":
            if inventory.get("test_intent", 0) == 0 or inventory.get("test_condition", 0) == 0:
                return self._directive(
                    state, "SPAWN_WORKER", role="TEST_FUSION", scope=release,
                    artifacts=("test_intent", "test_condition"), blocking=("FUSION_ARTIFACTS_MISSING",),
                )
            if "FUSION_COMPLETE" not in state.completed_gates:
                return self._directive(state, "RUN_GATE", scope=release, blocking=("FUSION_GATE_NOT_VERIFIED",))

        if state.stage == "TEST_DESIGN":
            if inventory.get("test_case", 0) == 0:
                return self._directive(
                    state, "SPAWN_LAYER_WORKERS", scope=release,
                    artifacts=("test_condition", "test_case"), blocking=("L1_L7_LAYER_DESIGN_REQUIRED",),
                )
            if "DESIGN_SUFFICIENT" not in state.completed_gates:
                return self._directive(state, "RUN_GATE", scope=release, artifacts=("test_case",), blocking=("DESIGN_COVERAGE_CLOSURE_REQUIRED",))
            if "ORACLE_SUFFICIENT" not in state.completed_gates:
                return self._directive(state, "RUN_GATE", scope=release, artifacts=("test_case",), blocking=("ORACLE_CLOSURE_REQUIRED",))
            if "PROJECTION_INTEGRITY" not in state.completed_gates:
                self.truth.rebuild_projection()
                return self._directive(state, "RUN_GATE", scope=release, blocking=("PROJECTION_INTEGRITY_COMMIT_REQUIRED",))
            if not state.target_identity_ref:
                return self._directive(state, "BUILD_TARGET", scope=release, blocking=("TARGET_IDENTITY_REQUIRED",))

        if state.stage == "PREPARATION":
            if "PREPARATION_READY" not in state.completed_gates:
                return self._directive(
                    state, "RESOLVE_PRECONDITION", scope=release, artifacts=("test_case",),
                    blocking=("PRECONDITION_DATA_BINDING_REQUIRED",), target=state.target_identity_ref,
                )

        if state.stage == "EXECUTION":
            if "EXECUTION_INTEGRITY" not in state.completed_gates:
                return self._directive(
                    state, "EXECUTE_LAYER", scope=release, artifacts=("execution_attempt", "assertion", "evidence"),
                    blocking=("L1_L7_EXECUTION_INCOMPLETE",), target=state.target_identity_ref,
                )

        if state.stage == "COVERAGE_CLOSURE":
            if "COVERAGE_SUFFICIENT" not in state.completed_gates:
                return self._directive(
                    state, "CLOSE_COVERAGE", scope=release, artifacts=("coverage_observation",),
                    blocking=("EMPIRICAL_COVERAGE_GAPS_OPEN",), target=state.target_identity_ref,
                )

        if state.stage == "REPORTING":
            if "REPORT_COMPLETE" not in state.completed_gates:
                return self._directive(
                    state, "REPORT", scope=release, artifacts=("report",),
                    blocking=("R1_REPORT_ALLURE_RECONCILIATION_REQUIRED",), target=state.target_identity_ref,
                )

        if state.stage == "COMPLETE":
            return self._directive(state, "COMPLETE", scope=release, target=state.target_identity_ref)

        return self._directive(state, "CONTROL_TICK", blocking=("STAGE_GATE_READY_FOR_TRANSITION",))

    def _directive(
        self,
        state: MissionState,
        action: str,
        *,
        role: Optional[str] = None,
        layer: Optional[str] = None,
        scope: Optional[str] = None,
        artifacts: Tuple[str, ...] = (),
        tools: Tuple[str, ...] = (),
        blocking: Tuple[str, ...] = (),
        checkpoint_required: bool = False,
        resume_envelope_ref: Optional[str] = None,
        target: Optional[str] = None,
    ) -> MissionDirective:
        raw = {
            "mission_id": state.mission_id,
            "stage": state.stage,
            "action": action,
            "role": role,
            "layer": layer,
            "scope": scope,
            "artifacts": list(artifacts),
            "tools": list(tools),
            "blocking": list(blocking),
            "checkpoint_seq": state.checkpoint_seq,
            "coordinator_generation": state.coordinator_generation,
            "target": target,
        }
        key = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:24]
        return MissionDirective(
            mission_id=state.mission_id,
            stage=state.stage,
            action=action,
            required_role=role,
            layer=layer,
            scope_ref=scope,
            required_artifact_types=artifacts,
            required_tools=tools,
            blocking_reasons=blocking,
            checkpoint_required=checkpoint_required,
            resume_envelope_ref=resume_envelope_ref,
            target_id=target or state.target_identity_ref,
            idempotency_key="directive-" + key,
        )

    def _next_stage(self, stage: str) -> Optional[str]:
        names = [rule.name for rule in self.stages.RULES]
        try:
            idx = names.index(stage)
        except ValueError as exc:
            raise MissionOrchestrationError("UNKNOWN_STAGE") from exc
        return names[idx + 1] if idx + 1 < len(names) else None

    @staticmethod
    def _resume_ref(envelope: ResumeEnvelope) -> str:
        return "mission://%s/checkpoint/%d/generation/%d" % (
            envelope.mission_id,
            envelope.checkpoint_seq,
            envelope.coordinator_generation,
        )
