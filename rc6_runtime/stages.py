from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple


class StageViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class StageTransition:
    target: str
    required_gates: Tuple[str, ...] = ()


class StageMachine:
    """Fail-closed final-integration mission state graph.

    Execution Closure extends, but does not replace, the frozen RC6 graph. A
    Frozen Case cannot jump directly to preparation/execution; it must become a
    governed ExecutableSpec and validated Script first. Failed executions must
    pass diagnosis -> recovery decision -> recovery action before any rerun.
    """

    STAGES: Tuple[str, ...] = (
        "REGISTERED",
        "REALITY_RECON",
        "TARGET_QUALIFICATION",
        "REQUIREMENT_ANALYSIS",
        "REQUIREMENT_SUFFICIENCY",
        "REQUIREMENT_GAP_REPAIR",
        "CODE_ANALYSIS",
        "CODE_SUFFICIENCY",
        "CODE_GAP_REPAIR",
        "FUSION",
        "LAYER_APPLICABILITY",
        "L1_L7_DESIGN",
        "DESIGN_SUFFICIENCY",
        "DELTA_DESIGN",
        "ORACLE_CLOSURE",
        "CASE_FREEZE",
        "EXECUTABLE_SPEC",
        "SCRIPT_BUILD",
        "SCRIPT_VALIDATE",
        "SCRIPT_READY",
        "PREPARATION",
        "PRECONDITION_VERIFY",
        "TEST_DATA_PREPARE",
        "PREPARED_ATTEMPT_FREEZE",
        "L1_L7_EXECUTION",
        "EXECUTION_INTEGRITY",
        "FAILURE_DIAGNOSIS",
        "RECOVERY_DECISION",
        "RECOVERY_ACTION",
        "REEXECUTION",
        "EMPIRICAL_COVERAGE",
        "DELTA_EXECUTION",
        "DEFECT",
        "REPORT",
        "ALLURE",
        "TRUTH_RECONCILIATION",
        "COMPLETE",
    )

    TRANSITIONS: Dict[str, Tuple[StageTransition, ...]] = {
        "REGISTERED": (StageTransition("REALITY_RECON", ("MISSION_REGISTERED",)),),
        "REALITY_RECON": (StageTransition("TARGET_QUALIFICATION", ("REALITY_RECONCILED",)),),
        "TARGET_QUALIFICATION": (StageTransition("REQUIREMENT_ANALYSIS", ("TARGET_QUALIFIED",)),),
        "REQUIREMENT_ANALYSIS": (StageTransition("REQUIREMENT_SUFFICIENCY", ("REQUIREMENT_ANALYSIS_COMPLETE",)),),
        "REQUIREMENT_SUFFICIENCY": (
            StageTransition("CODE_ANALYSIS", ("REQUIREMENT_SUFFICIENT",)),
            StageTransition("REQUIREMENT_GAP_REPAIR", ("REQUIREMENT_GAP_OPEN",)),
        ),
        "REQUIREMENT_GAP_REPAIR": (StageTransition("REQUIREMENT_SUFFICIENCY", ("REQUIREMENT_REPAIR_COMPLETE",)),),
        "CODE_ANALYSIS": (StageTransition("CODE_SUFFICIENCY", ("CODE_ANALYSIS_COMPLETE",)),),
        "CODE_SUFFICIENCY": (
            StageTransition("FUSION", ("CODE_SUFFICIENT",)),
            StageTransition("CODE_GAP_REPAIR", ("CODE_GAP_OPEN",)),
        ),
        "CODE_GAP_REPAIR": (StageTransition("CODE_SUFFICIENCY", ("CODE_REPAIR_COMPLETE",)),),
        "FUSION": (StageTransition("LAYER_APPLICABILITY", ("FUSION_COMPLETE",)),),
        "LAYER_APPLICABILITY": (StageTransition("L1_L7_DESIGN", ("LAYER_APPLICABILITY_COMPLETE",)),),
        "L1_L7_DESIGN": (StageTransition("DESIGN_SUFFICIENCY", ("L1_L7_DESIGN_COMPLETE",)),),
        "DESIGN_SUFFICIENCY": (
            StageTransition("ORACLE_CLOSURE", ("DESIGN_SUFFICIENT",)),
            StageTransition("DELTA_DESIGN", ("DESIGN_GAP_OPEN",)),
        ),
        "DELTA_DESIGN": (StageTransition("DESIGN_SUFFICIENCY", ("DELTA_DESIGN_COMPLETE",)),),
        "ORACLE_CLOSURE": (StageTransition("CASE_FREEZE", ("ORACLE_SUFFICIENT",)),),
        "CASE_FREEZE": (StageTransition("EXECUTABLE_SPEC", ("CASE_SET_FROZEN",)),),
        "EXECUTABLE_SPEC": (StageTransition("SCRIPT_BUILD", ("EXECUTABLE_SPEC_READY",)),),
        "SCRIPT_BUILD": (StageTransition("SCRIPT_VALIDATE", ("SCRIPT_GENERATED",)),),
        "SCRIPT_VALIDATE": (StageTransition("SCRIPT_READY", ("SCRIPT_READY",)),),
        "SCRIPT_READY": (StageTransition("PREPARATION", ("SCRIPT_READY_ADMITTED",)),),
        "PREPARATION": (StageTransition("PRECONDITION_VERIFY", ("PREPARATION_STARTED",)),),
        "PRECONDITION_VERIFY": (StageTransition("TEST_DATA_PREPARE", ("PRECONDITIONS_VERIFIED",)),),
        "TEST_DATA_PREPARE": (StageTransition("PREPARED_ATTEMPT_FREEZE", ("TEST_DATA_READY",)),),
        "PREPARED_ATTEMPT_FREEZE": (StageTransition("L1_L7_EXECUTION", ("PREPARED_ATTEMPT_FROZEN",)),),
        "L1_L7_EXECUTION": (StageTransition("EXECUTION_INTEGRITY", ("L1_L7_EXECUTION_COMPLETE",)),),
        "EXECUTION_INTEGRITY": (
            StageTransition("EMPIRICAL_COVERAGE", ("EXECUTION_INTEGRITY",)),
            StageTransition("FAILURE_DIAGNOSIS", ("EXECUTION_FAILURES_PRESENT",)),
        ),
        "FAILURE_DIAGNOSIS": (StageTransition("RECOVERY_DECISION", ("FAILURE_DIAGNOSIS_COMPLETE",)),),
        "RECOVERY_DECISION": (
            StageTransition("RECOVERY_ACTION", ("RECOVERY_DECISION_COMPLETE",)),
            StageTransition("DEFECT", ("PRODUCT_DEFECT_CONFIRMED",)),
        ),
        "RECOVERY_ACTION": (
            StageTransition("REEXECUTION", ("RECOVERY_RERUN_READY",)),
            StageTransition("PREPARED_ATTEMPT_FREEZE", ("RECOVERY_REPREPARE_READY",)),
        ),
        "REEXECUTION": (StageTransition("EXECUTION_INTEGRITY", ("REEXECUTION_COMPLETE",)),),
        "EMPIRICAL_COVERAGE": (
            StageTransition("DEFECT", ("COVERAGE_SUFFICIENT",)),
            StageTransition("DELTA_EXECUTION", ("EXECUTION_COVERAGE_GAP_OPEN",)),
            StageTransition("DELTA_DESIGN", ("DESIGN_GAP_OPEN",)),
        ),
        "DELTA_EXECUTION": (StageTransition("EXECUTION_INTEGRITY", ("DELTA_EXECUTION_COMPLETE",)),),
        "DEFECT": (StageTransition("REPORT", ("DEFECT_RECONCILED",)),),
        "REPORT": (StageTransition("ALLURE", ("REPORT_COMPLETE",)),),
        "ALLURE": (StageTransition("TRUTH_RECONCILIATION", ("ALLURE_COMPLETE",)),),
        "TRUTH_RECONCILIATION": (StageTransition("COMPLETE", ("TRUTH_RECONCILED",)),),
        "COMPLETE": (),
    }

    def __init__(self) -> None:
        self._stages = set(self.STAGES)

    def targets(self, current_stage: str) -> Tuple[StageTransition, ...]:
        if current_stage not in self._stages:
            raise StageViolation("UNKNOWN_STAGE")
        return self.TRANSITIONS[current_stage]

    def can_enter(self, current_stage: str, target_stage: str, passed_gates: Iterable[str]) -> bool:
        passed = set(passed_gates)
        for transition in self.targets(current_stage):
            if transition.target == target_stage:
                return set(transition.required_gates).issubset(passed)
        return False

    def enter(self, current_stage: str, target_stage: str, passed_gates: Iterable[str]) -> str:
        if current_stage not in self._stages or target_stage not in self._stages:
            raise StageViolation("UNKNOWN_STAGE")
        declared = [t for t in self.targets(current_stage) if t.target == target_stage]
        if not declared:
            raise StageViolation("ILLEGAL_STAGE_TRANSITION")
        if not self.can_enter(current_stage, target_stage, passed_gates):
            raise StageViolation("REQUIRED_GATE_NOT_PASSED")
        return target_stage
