"""Governed autonomous execution loop for evidence-backed direct retries.

Each attempt still passes through the normal RC7 Execution Task, independent
Evaluation, Gap planning and Recovery repair Task.  This loop merely consumes a
persisted DIRECT_RETRY work plan and invokes the already-governed retry
controller.  It never retries PRODUCT/ORACLE/UNKNOWN/terminal outcomes and an
automation cycle cap never converts unfinished work into PASS.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

from rc6_runtime.preparation import PreparedAttempt

from .closed_loop_control import ClosedLoopControlPlane
from .execution_recovery import RecoveryWorkPlan
from .execution_recovery_control import DirectRetryAuthorization, ExecutionRecoveryController
from .lineage_diagnosis import LineageAwareExecutionDiagnosisCoordinator
from .runtime_execution_control import ClosedLoopExecutionResult


class AutonomousExecutionLoopError(RuntimeError):
    pass


@dataclass(frozen=True)
class AutonomousExecutionLoopResult:
    attempts: Tuple[ClosedLoopExecutionResult, ...]
    authorizations: Tuple[DirectRetryAuthorization, ...]
    final_task_state: str
    stopped_reason: str

    @property
    def converged(self) -> bool:
        return self.final_task_state in {"PASS", "BLOCKED"} and self.stopped_reason != "AUTO_LOOP_BUDGET_REACHED"


class AutonomousExecutionLoop:
    def __init__(self, *, recovery_controller: ExecutionRecoveryController, max_cycles: int = 4) -> None:
        self.recovery_controller = recovery_controller
        self.max_cycles = int(max_cycles)
        if self.max_cycles < 1:
            raise ValueError("max_cycles must be >= 1")

    def run(
        self,
        control: ClosedLoopControlPlane,
        *,
        source_task_id: str,
        prepared: PreparedAttempt,
        coordinator: LineageAwareExecutionDiagnosisCoordinator,
        run_once: Callable[[PreparedAttempt, LineageAwareExecutionDiagnosisCoordinator], ClosedLoopExecutionResult],
    ) -> AutonomousExecutionLoopResult:
        attempts = []
        authorizations = []
        current = prepared

        for _ in range(self.max_cycles):
            result = run_once(current, coordinator)
            attempts.append(result)
            state = result.task_state
            if state != "REPAIR_REQUIRED":
                return AutonomousExecutionLoopResult(
                    attempts=tuple(attempts),
                    authorizations=tuple(authorizations),
                    final_task_state=state,
                    stopped_reason="EXECUTION_CONCLUSION_REACHED",
                )

            plan = self._direct_retry_plan(control, result)
            if plan is None:
                return AutonomousExecutionLoopResult(
                    attempts=tuple(attempts),
                    authorizations=tuple(authorizations),
                    final_task_state=state,
                    stopped_reason="NON_DIRECT_RECOVERY_REQUIRED",
                )
            gap_id = self._direct_retry_gap(result)
            diagnosis_evidence_id = self._diagnosis_evidence_id(control, result.execution_record.attempt_id)
            authorization = self.recovery_controller.authorize_direct_retry(
                control,
                source_task_id=source_task_id,
                gap_id=gap_id,
                plan=plan,
                prepared=current,
                diagnosis_evidence_id=diagnosis_evidence_id,
            )
            authorizations.append(authorization)
            self.recovery_controller.verify_successor(authorization, authorization.prepared)
            current = authorization.prepared

        return AutonomousExecutionLoopResult(
            attempts=tuple(attempts),
            authorizations=tuple(authorizations),
            final_task_state=control.scheduler.task(source_task_id).state.value,
            stopped_reason="AUTO_LOOP_BUDGET_REACHED",
        )

    @staticmethod
    def _direct_retry_gap(result: ClosedLoopExecutionResult) -> str:
        eligible = [
            gap.gap_id
            for gap in result.loop_result.gaps
            if gap.target_node == "EXECUTION" and gap.category in {"TRANSIENT_FAILURE", "FLAKY_SUSPECTED"}
        ]
        if len(eligible) != 1:
            raise AutonomousExecutionLoopError("DIRECT_RETRY_GAP_NOT_UNIQUE")
        return eligible[0]

    def _direct_retry_plan(
        self,
        control: ClosedLoopControlPlane,
        result: ClosedLoopExecutionResult,
    ) -> Optional[RecoveryWorkPlan]:
        attempt_id = result.execution_record.attempt_id
        evidence_rows = [
            row
            for row in control.truth.query("rc7_evidence", mission_id=control.mission_id)
            if row.get("kind") == "RUNTIME_FAILURE_DIAGNOSIS"
            and attempt_id in list(row.get("subject_refs", []))
        ]
        if len(evidence_rows) != 1:
            return None
        content_ref = evidence_rows[0].get("content_ref")
        if not isinstance(content_ref, str) or not content_ref.startswith("file://"):
            raise AutonomousExecutionLoopError("DIAGNOSIS_EVIDENCE_FILE_REQUIRED")
        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise AutonomousExecutionLoopError("DIAGNOSIS_EVIDENCE_FILE_MISSING")
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw = payload.get("work_plan") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            return None
        plan = RecoveryWorkPlan(**raw)
        if plan.mode != "DIRECT_RETRY" or plan.target_node != "EXECUTION" or not plan.retry_allowed:
            return None
        if plan.source_attempt_id != attempt_id:
            raise AutonomousExecutionLoopError("RECOVERY_PLAN_ATTEMPT_MISMATCH")
        return plan

    @staticmethod
    def _diagnosis_evidence_id(control: ClosedLoopControlPlane, attempt_id: str) -> Optional[str]:
        rows = [
            row
            for row in control.truth.query("rc7_evidence", mission_id=control.mission_id)
            if row.get("kind") == "RUNTIME_FAILURE_DIAGNOSIS"
            and attempt_id in list(row.get("subject_refs", []))
        ]
        if len(rows) != 1:
            return None
        value = rows[0].get("evidence_id")
        return value if isinstance(value, str) and value else None
