from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .mission import MissionRuntime, MissionState, ResumeEnvelope
from .stages import StageMachine
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
    """Deterministic final-integration Mission controller.

    It owns ordering and repair routing. Professional work is represented as
    directives for independently-authorized workers/runtime engines; the
    coordinator never synthesizes their artifacts.
    """

    GATE_STAGE: Dict[str, str] = {
        "REALITY_RECONCILED": "REALITY_RECON",
        "TARGET_QUALIFIED": "TARGET_QUALIFICATION",
        "TARGET_IDENTITY_READY": "TARGET_QUALIFICATION",
        "REQUIREMENT_ANALYSIS_COMPLETE": "REQUIREMENT_ANALYSIS",
        "REQUIREMENT_SUFFICIENT": "REQUIREMENT_SUFFICIENCY",
        "REQUIREMENT_REPAIR_COMPLETE": "REQUIREMENT_GAP_REPAIR",
        "CODE_ANALYSIS_COMPLETE": "CODE_ANALYSIS",
        "CODE_SUFFICIENT": "CODE_SUFFICIENCY",
        "CODE_REPAIR_COMPLETE": "CODE_GAP_REPAIR",
        "FUSION_COMPLETE": "FUSION",
        "LAYER_APPLICABILITY_COMPLETE": "LAYER_APPLICABILITY",
        "L1_L7_DESIGN_COMPLETE": "L1_L7_DESIGN",
        "DESIGN_SUFFICIENT": "DESIGN_SUFFICIENCY",
        "DELTA_DESIGN_COMPLETE": "DELTA_DESIGN",
        "ORACLE_SUFFICIENT": "ORACLE_CLOSURE",
        "CASE_SET_FROZEN": "CASE_FREEZE",
        "PREPARATION_STARTED": "PREPARATION",
        "PRECONDITIONS_VERIFIED": "PRECONDITION_VERIFY",
        "TEST_DATA_READY": "TEST_DATA_PREPARE",
        "PREPARED_ATTEMPT_FROZEN": "PREPARED_ATTEMPT_FREEZE",
        "L1_L7_EXECUTION_COMPLETE": "L1_L7_EXECUTION",
        "EXECUTION_INTEGRITY": "EXECUTION_INTEGRITY",
        "FAILURE_DIAGNOSIS_COMPLETE": "FAILURE_DIAGNOSIS",
        "COVERAGE_SUFFICIENT": "EMPIRICAL_COVERAGE",
        "DELTA_EXECUTION_COMPLETE": "DELTA_EXECUTION",
        "DEFECT_RECONCILED": "DEFECT",
        "REPORT_COMPLETE": "REPORT",
        "ALLURE_COMPLETE": "ALLURE",
        "TRUTH_RECONCILED": "TRUTH_RECONCILIATION",
        "PROJECTION_INTEGRITY": "TRUTH_RECONCILIATION",
    }

    GAP_BRANCH: Dict[str, str] = {
        "REQUIREMENT_SUFFICIENT": "REQUIREMENT_GAP_OPEN",
        "CODE_SUFFICIENT": "CODE_GAP_OPEN",
        "DESIGN_SUFFICIENT": "DESIGN_GAP_OPEN",
        "EXECUTION_INTEGRITY": "EXECUTION_FAILURES_PRESENT",
        "COVERAGE_SUFFICIENT": "EXECUTION_COVERAGE_GAP_OPEN",
    }

    BRANCH_CLEAR: Dict[str, Tuple[str, ...]] = {
        "REQUIREMENT_SUFFICIENT": ("REQUIREMENT_GAP_OPEN",),
        "CODE_SUFFICIENT": ("CODE_GAP_OPEN",),
        "DESIGN_SUFFICIENT": ("DESIGN_GAP_OPEN",),
        "EXECUTION_INTEGRITY": ("EXECUTION_FAILURES_PRESENT",),
        "COVERAGE_SUFFICIENT": ("EXECUTION_COVERAGE_GAP_OPEN", "DESIGN_GAP_OPEN"),
        "REQUIREMENT_REPAIR_COMPLETE": ("REQUIREMENT_GAP_OPEN",),
        "CODE_REPAIR_COMPLETE": ("CODE_GAP_OPEN",),
        "DELTA_DESIGN_COMPLETE": ("DESIGN_GAP_OPEN",),
        "DELTA_EXECUTION_COMPLETE": ("EXECUTION_COVERAGE_GAP_OPEN",),
        "FAILURE_DIAGNOSIS_COMPLETE": ("EXECUTION_FAILURES_PRESENT",),
    }

    def __init__(self, missions: MissionRuntime, truth: TruthRuntime):
        self.missions = missions
        self.truth = truth
        self.stages = StageMachine()

    def plan_next(self, mission_id: str, *, context_pressure: bool = False) -> MissionDirective:
        state = self.missions.load(mission_id)
        if context_pressure:
            return self._directive(state, "ROTATE_SESSION", blocking=("COORDINATOR_CONTEXT_PRESSURE",), checkpoint_required=True)
        return self._directive_for_stage(state)

    def control_tick(self, mission_id: str, *, context_pressure: bool = False) -> MissionDirective:
        state = self.missions.load(mission_id)
        if context_pressure:
            envelope = self.missions.rotation_checkpoint(state)
            return self._directive(
                self.missions.load(mission_id), "ROTATE_SESSION",
                blocking=("COORDINATOR_CONTEXT_PRESSURE",), checkpoint_required=True,
                resume_envelope_ref=self._resume_ref(envelope),
            )
        if state.successor_pending:
            raise MissionOrchestrationError("SUCCESSOR_ACTIVATION_REQUIRED")
        if state.stage == "REGISTERED" and "MISSION_REGISTERED" not in state.completed_gates:
            state.completed_gates.append("MISSION_REGISTERED")
            self.missions.save(state)
            state = self.missions.load(mission_id)
        target = self._ready_target(state)
        if target is not None:
            state.stage = self.stages.enter(state.stage, target, state.completed_gates)
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
        for branch in self.BRANCH_CLEAR.get(gate_name, ()):
            if branch in state.completed_gates:
                state.completed_gates.remove(branch)
        marker = "GATE_BLOCKED:" + gate_name
        state.open_gaps = [gap for gap in state.open_gaps if gap != marker]
        gate_marker = "gate://%s/%s" % (gate_name.lower(), evidence_ref.strip())
        if gate_marker not in state.artifact_refs:
            state.artifact_refs.append(gate_marker)
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
        branch = self.GAP_BRANCH.get(gate_name)
        if branch and branch not in state.completed_gates:
            state.completed_gates.append(branch)
        if reason:
            reason_ref = "gap://%s/%s" % (gate_name.lower(), reason.strip())
            if reason_ref not in state.artifact_refs:
                state.artifact_refs.append(reason_ref)
        self.missions.save(state)
        return state

    def bind_target(self, mission_id: str, target_id: str) -> MissionState:
        state = self.missions.load(mission_id)
        if state.stage != "TARGET_QUALIFICATION":
            raise MissionOrchestrationError("TARGET_BIND_STAGE_MISMATCH")
        if not isinstance(target_id, str) or not target_id.startswith("TARGET-"):
            raise MissionOrchestrationError("INVALID_TARGET_ID")
        state.target_identity_ref = target_id
        if "TARGET_IDENTITY_READY" not in state.completed_gates:
            state.completed_gates.append("TARGET_IDENTITY_READY")
        self.missions.save(state)
        return state

    def _ready_target(self, state: MissionState) -> Optional[str]:
        for transition in self.stages.targets(state.stage):
            if self.stages.can_enter(state.stage, transition.target, state.completed_gates):
                return transition.target
        return None

    def _count(self, artifact_type: str, release_id: str) -> int:
        return len(self.truth.query(artifact_type, release_id=release_id))

    def _directive_for_stage(self, state: MissionState) -> MissionDirective:
        release = state.release_id
        stage = state.stage
        if stage == "REGISTERED":
            return self._directive(state, "CONTROL_TICK", blocking=("MISSION_REGISTRATION_TRANSITION_REQUIRED",))
        if stage == "REALITY_RECON":
            return self._directive(state, "RECONCILE_REALITY", scope=release, blocking=("BANK_REALITY_FRESHNESS_REQUIRED",))
        if stage == "TARGET_QUALIFICATION":
            if not state.target_identity_ref:
                return self._directive(state, "BUILD_TARGET", scope=release, blocking=("TARGET_IDENTITY_REQUIRED",))
            return self._directive(state, "RUN_GATE", scope=release, blocking=("TARGET_QUALIFICATION_REQUIRED",), target=state.target_identity_ref)
        if stage == "REQUIREMENT_ANALYSIS":
            if self._count("requirement_analysis", release) == 0:
                return self._directive(state, "SPAWN_WORKER", role="REQUIREMENT_ANALYZER", scope=release, artifacts=("requirement_analysis",), blocking=("REQUIREMENT_ANALYSIS_MISSING",))
            return self._directive(state, "RUN_GATE", scope=release, artifacts=("requirement_analysis",), blocking=("REQUIREMENT_ANALYSIS_COMPLETION_REQUIRED",))
        if stage == "REQUIREMENT_SUFFICIENCY":
            return self._directive(state, "RUN_GATE", role="REQUIREMENT_REVIEWER", scope=release, artifacts=("requirement_analysis",), blocking=("REQUIREMENT_SUFFICIENCY_NOT_VERIFIED",))
        if stage == "REQUIREMENT_GAP_REPAIR":
            return self._directive(state, "SPAWN_WORKER", role="REQUIREMENT_ANALYZER", scope=release, artifacts=("requirement_analysis",), blocking=("REQUIREMENT_GAP_REPAIR_REQUIRED",))
        if stage == "CODE_ANALYSIS":
            if self._count("code_analysis", release) == 0:
                return self._directive(state, "SPAWN_WORKER", role="CODE_ANALYZER", scope=release, artifacts=("code_analysis",), tools=("git", "codegraph"), blocking=("CODE_ANALYSIS_MISSING",))
            return self._directive(state, "RUN_GATE", scope=release, artifacts=("code_analysis",), tools=("git", "codegraph"), blocking=("CODE_ANALYSIS_COMPLETION_REQUIRED",))
        if stage == "CODE_SUFFICIENCY":
            return self._directive(state, "RUN_GATE", role="CODE_REVIEWER", scope=release, artifacts=("code_analysis",), tools=("git", "codegraph"), blocking=("CODE_SUFFICIENCY_NOT_VERIFIED",))
        if stage == "CODE_GAP_REPAIR":
            return self._directive(state, "SPAWN_WORKER", role="CODE_ANALYZER", scope=release, artifacts=("code_analysis",), tools=("git", "codegraph"), blocking=("CODE_GAP_REPAIR_REQUIRED",))
        if stage == "FUSION":
            return self._directive(state, "SPAWN_WORKER", role="TEST_FUSION", scope=release, artifacts=("test_intent", "test_condition"), blocking=("FUSION_COMPLETION_REQUIRED",))
        if stage == "LAYER_APPLICABILITY":
            return self._directive(state, "RUN_GATE", scope=release, artifacts=("test_condition",), blocking=("LAYER_APPLICABILITY_REQUIRED",))
        if stage == "L1_L7_DESIGN":
            return self._directive(state, "SPAWN_LAYER_WORKERS", scope=release, artifacts=("test_condition", "test_case"), blocking=("L1_L7_LAYER_DESIGN_REQUIRED",))
        if stage == "DESIGN_SUFFICIENCY":
            return self._directive(state, "RUN_GATE", scope=release, artifacts=("test_case",), blocking=("DESIGN_COVERAGE_CLOSURE_REQUIRED",))
        if stage == "DELTA_DESIGN":
            return self._directive(state, "SPAWN_LAYER_WORKERS", scope=release, artifacts=("test_case",), blocking=("DELTA_DESIGN_REQUIRED",))
        if stage == "ORACLE_CLOSURE":
            return self._directive(state, "RUN_GATE", scope=release, artifacts=("test_case",), blocking=("ORACLE_CLOSURE_REQUIRED",))
        if stage == "CASE_FREEZE":
            return self._directive(state, "FREEZE_CASE_SET", scope=release, artifacts=("test_case",), blocking=("CASE_FREEZE_REQUIRED",), target=state.target_identity_ref)
        if stage == "PREPARATION":
            return self._directive(state, "START_PREPARATION", scope=release, artifacts=("test_case",), blocking=("PREPARATION_START_REQUIRED",), target=state.target_identity_ref)
        if stage == "PRECONDITION_VERIFY":
            return self._directive(state, "VERIFY_PRECONDITION", scope=release, artifacts=("test_case",), blocking=("PRECONDITION_VERIFY_REQUIRED",), target=state.target_identity_ref)
        if stage == "TEST_DATA_PREPARE":
            return self._directive(state, "PREPARE_TEST_DATA", scope=release, artifacts=("test_case",), blocking=("TEST_DATA_PREPARE_REQUIRED",), target=state.target_identity_ref)
        if stage == "PREPARED_ATTEMPT_FREEZE":
            return self._directive(state, "FREEZE_PREPARED_ATTEMPT", scope=release, blocking=("PREPARED_ATTEMPT_FREEZE_REQUIRED",), target=state.target_identity_ref)
        if stage == "L1_L7_EXECUTION":
            return self._directive(state, "EXECUTE_LAYER", scope=release, artifacts=("execution_attempt", "assertion", "evidence"), blocking=("L1_L7_EXECUTION_INCOMPLETE",), target=state.target_identity_ref)
        if stage == "EXECUTION_INTEGRITY":
            return self._directive(state, "RUN_GATE", scope=release, artifacts=("execution_attempt", "assertion", "evidence"), blocking=("EXECUTION_INTEGRITY_NOT_VERIFIED",), target=state.target_identity_ref)
        if stage == "FAILURE_DIAGNOSIS":
            return self._directive(state, "SPAWN_WORKER", role="FAILURE_DIAGNOSTIC", scope=release, artifacts=("evidence", "defect"), tools=("cat",), blocking=("FAILURE_DIAGNOSIS_REQUIRED",), target=state.target_identity_ref)
        if stage == "EMPIRICAL_COVERAGE":
            return self._directive(state, "CLOSE_COVERAGE", scope=release, artifacts=("coverage_observation",), blocking=("EMPIRICAL_COVERAGE_GAPS_OPEN",), target=state.target_identity_ref)
        if stage == "DELTA_EXECUTION":
            return self._directive(state, "EXECUTE_LAYER", scope=release, artifacts=("execution_attempt", "assertion", "evidence", "coverage_observation"), blocking=("DELTA_EXECUTION_REQUIRED",), target=state.target_identity_ref)
        if stage == "DEFECT":
            return self._directive(state, "RECONCILE_DEFECTS", scope=release, artifacts=("defect", "evidence"), blocking=("DEFECT_RECONCILIATION_REQUIRED",), target=state.target_identity_ref)
        if stage == "REPORT":
            return self._directive(state, "REPORT", scope=release, artifacts=("report",), blocking=("REPORT_REQUIRED",), target=state.target_identity_ref)
        if stage == "ALLURE":
            return self._directive(state, "GENERATE_ALLURE", scope=release, blocking=("ALLURE_REQUIRED",), target=state.target_identity_ref)
        if stage == "TRUTH_RECONCILIATION":
            return self._directive(state, "RECONCILE_TRUTH", scope=release, blocking=("R1_PROJECTION_QUERY_REPORT_RECONCILIATION_REQUIRED",), target=state.target_identity_ref)
        if stage == "COMPLETE":
            return self._directive(state, "COMPLETE", scope=release, target=state.target_identity_ref)
        raise MissionOrchestrationError("UNKNOWN_STAGE")

    def _directive(self, state: MissionState, action: str, *, role: Optional[str] = None, layer: Optional[str] = None, scope: Optional[str] = None, artifacts: Tuple[str, ...] = (), tools: Tuple[str, ...] = (), blocking: Tuple[str, ...] = (), checkpoint_required: bool = False, resume_envelope_ref: Optional[str] = None, target: Optional[str] = None) -> MissionDirective:
        raw = {"mission_id": state.mission_id, "stage": state.stage, "action": action, "role": role, "layer": layer, "scope": scope, "artifacts": list(artifacts), "tools": list(tools), "blocking": list(blocking), "checkpoint_seq": state.checkpoint_seq, "coordinator_generation": state.coordinator_generation, "target": target}
        key = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:24]
        return MissionDirective(mission_id=state.mission_id, stage=state.stage, action=action, required_role=role, layer=layer, scope_ref=scope, required_artifact_types=artifacts, required_tools=tools, blocking_reasons=blocking, checkpoint_required=checkpoint_required, resume_envelope_ref=resume_envelope_ref, target_id=target or state.target_identity_ref, idempotency_key="directive-" + key)

    @staticmethod
    def _resume_ref(envelope: ResumeEnvelope) -> str:
        return "mission://%s/checkpoint/%d/generation/%d" % (envelope.mission_id, envelope.checkpoint_seq, envelope.coordinator_generation)
