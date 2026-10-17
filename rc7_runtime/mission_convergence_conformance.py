"""Fail-closed convergence authority for contracted RC7 Bank Missions.

Bank Final already replays these facts after a run.  This authority moves the
same trust boundary into the product path: a graph-v2 Mission carrying the
Execution Recovery Contract cannot transition to CONVERGED until canonical
Mission/Node Tool, recovery, Actual Result/Oracle and Defect Review truth all
pass from R1.

Legacy Missions without the additive recovery contract remain resumable and are
reported as NOT_ENFORCED; they are not silently upgraded to a new contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from rc6_runtime.truth import TruthRuntime

from .defect_review_conformance import DefectReviewConformanceChecker
from .execution_recovery_conformance import (
    ExecutionRecoveryConformanceChecker,
    contract_row as execution_recovery_contract_row,
)
from .mission_conformance import MissionConformanceChecker
from .oracle_conformance import ActualResultOracleConformanceChecker


class MissionConvergenceConformanceError(RuntimeError):
    pass


def canonical_execution_task_id(truth: TruthRuntime, mission_id: str) -> str:
    row = execution_recovery_contract_row(truth, mission_id)
    if row is None:
        return ""
    refs = [str(value) for value in list(row.get("subject_refs") or []) if str(value)]
    if len(refs) != 1:
        raise MissionConvergenceConformanceError(
            "CANONICAL_EXECUTION_CONTRACT_SUBJECT_INVALID:%d" % len(refs)
        )
    task_id = refs[0]
    rows = truth.query("rc7_task", task_id=task_id)
    if (
        len(rows) != 1
        or rows[0].get("mission_id") != mission_id
        or rows[0].get("node") != "EXECUTION"
    ):
        raise MissionConvergenceConformanceError(
            "CANONICAL_EXECUTION_TASK_INVALID:%s" % task_id
        )
    return task_id


@dataclass(frozen=True)
class MissionConvergenceConformanceResult:
    mission_id: str
    status: str
    enforced: bool
    canonical_execution_task_id: str
    mission_conformance: Dict[str, Any]
    execution_recovery_conformance: Dict[str, Any]
    actual_result_oracle_conformance: Dict[str, Any]
    defect_review_conformance: Dict[str, Any]
    violations: Tuple[str, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "status": self.status,
            "enforced": self.enforced,
            "canonical_execution_task_id": self.canonical_execution_task_id,
            "mission_conformance": self.mission_conformance,
            "execution_recovery_conformance": self.execution_recovery_conformance,
            "actual_result_oracle_conformance": self.actual_result_oracle_conformance,
            "defect_review_conformance": self.defect_review_conformance,
            "violations": list(self.violations),
        }


class MissionConvergenceConformanceChecker:
    def __init__(self, truth: TruthRuntime) -> None:
        self.truth = truth

    def check(self, mission_id: str) -> MissionConvergenceConformanceResult:
        mission_id = str(mission_id or "").strip()
        if not mission_id:
            raise MissionConvergenceConformanceError("MISSION_ID_REQUIRED")
        contract = execution_recovery_contract_row(self.truth, mission_id)
        if contract is None:
            return MissionConvergenceConformanceResult(
                mission_id=mission_id,
                status="PASS",
                enforced=False,
                canonical_execution_task_id="",
                mission_conformance={"status": "NOT_ENFORCED"},
                execution_recovery_conformance={"status": "NOT_ENFORCED"},
                actual_result_oracle_conformance={"status": "NOT_ENFORCED"},
                defect_review_conformance={"status": "NOT_ENFORCED"},
                violations=(),
            )

        violations: List[str] = []
        task_id = canonical_execution_task_id(self.truth, mission_id)

        try:
            mission = MissionConformanceChecker(self.truth).check(mission_id)
            mission_payload = mission.as_dict()
            if mission.status != "PASS":
                violations.append(
                    "MISSION_CONFORMANCE_FAILED:%s" % ",".join(mission.violations)
                )
        except Exception as exc:
            mission_payload = {"status": "FAIL", "reason": str(exc)}
            violations.append("MISSION_CONFORMANCE_ERROR:%s" % str(exc))

        try:
            recovery = ExecutionRecoveryConformanceChecker(self.truth).check_task(
                mission_id, task_id
            )
            recovery_payload = recovery.as_dict()
            if recovery.status != "PASS":
                violations.append(
                    "EXECUTION_RECOVERY_CONFORMANCE_FAILED:%s"
                    % ",".join(recovery.violations)
                )
        except Exception as exc:
            recovery_payload = {"status": "FAIL", "reason": str(exc)}
            violations.append("EXECUTION_RECOVERY_CONFORMANCE_ERROR:%s" % str(exc))

        try:
            oracle = ActualResultOracleConformanceChecker(self.truth).check_task(
                mission_id, task_id
            )
            oracle_payload = oracle.as_dict()
            if oracle.status != "PASS":
                violations.append(
                    "ACTUAL_RESULT_ORACLE_CONFORMANCE_FAILED:%s"
                    % ",".join(oracle.violations)
                )
        except Exception as exc:
            oracle_payload = {"status": "FAIL", "reason": str(exc)}
            violations.append("ACTUAL_RESULT_ORACLE_CONFORMANCE_ERROR:%s" % str(exc))

        try:
            defect = DefectReviewConformanceChecker(self.truth).check_mission(mission_id)
            defect_payload = defect.as_dict()
            if defect.status != "PASS":
                violations.append(
                    "DEFECT_REVIEW_CONFORMANCE_FAILED:%s"
                    % ",".join(defect.violations)
                )
        except Exception as exc:
            defect_payload = {"status": "FAIL", "reason": str(exc)}
            violations.append("DEFECT_REVIEW_CONFORMANCE_ERROR:%s" % str(exc))

        deduped = tuple(dict.fromkeys(violations))
        return MissionConvergenceConformanceResult(
            mission_id=mission_id,
            status="PASS" if not deduped else "FAIL",
            enforced=True,
            canonical_execution_task_id=task_id,
            mission_conformance=mission_payload,
            execution_recovery_conformance=recovery_payload,
            actual_result_oracle_conformance=oracle_payload,
            defect_review_conformance=defect_payload,
            violations=deduped,
        )

    def require_pass(self, mission_id: str) -> MissionConvergenceConformanceResult:
        result = self.check(mission_id)
        if result.status != "PASS":
            raise MissionConvergenceConformanceError(
                "MISSION_CONVERGENCE_CONFORMANCE_FAILED:%s"
                % ",".join(result.violations)
            )
        return result
