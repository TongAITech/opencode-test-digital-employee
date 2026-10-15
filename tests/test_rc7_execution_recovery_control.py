from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.execution_recovery import RecoveryWorkPlan
from rc7_runtime.execution_recovery_control import (
    ExecutionRecoveryController,
    RecoveryControlError,
)
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Gap,
    GapSeverity,
    Mission,
    Task,
    TaskStatus,
)


MISSION = "MISSION-DIRECT-RETRY"
SOURCE_TASK = "TASK-EXEC-DIRECT-RETRY"
GAP_ID = "GAP-EXEC-TRANSIENT-1"
WORKER = "execution-worker"


def _prepared(attempt_id="ATT-1"):
    return PreparedAttempt(
        status="PREPARED",
        attempt_id=attempt_id,
        tc_id="TC-DIRECT-RETRY",
        case_version=1,
        target_id="TARGET-1",
        precondition_evidence=("EVD-PRE-1",),
        initial_state_bindings={"loan_id": "L-1"},
        input_data_bindings={"delta": 1},
        binding_evidence=("EVD-DATA-1",),
        cleanup_policy={"mode": "NONE"},
        oracle_snapshot={
            "checks": [
                {
                    "id": "CHK-1",
                    "type": "BUSINESS_RULE",
                    "actual_path": "code",
                    "operator": "EQ",
                    "expected": "OK",
                }
            ]
        },
    )


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7-DIRECT-RETRY",
            goal="prove retry remains governed by task/gap/evaluation truth",
        ),
    )
    control.register_task(
        Task(
            task_id=SOURCE_TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute one transient-prone case",
            required_capabilities=["test_execution"],
        )
    )
    return truth, control


def _submit_first_failure(control: ClosedLoopControlPlane):
    leased = control.lease_next(worker_ref=WORKER, capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE_TASK
    control.start(SOURCE_TASK, worker_ref=WORKER)
    evidence = Evidence(
        evidence_id="EVD-EXEC-FIRST",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://execution",
        content_ref="evidence://exec-first",
        subject_refs=[SOURCE_TASK, "ATT-1"],
    )
    diagnosis = Evidence(
        evidence_id="EVD-DIAG-1",
        mission_id=MISSION,
        kind="RUNTIME_FAILURE_DIAGNOSIS",
        source_ref="runtime://execution-diagnosis",
        content_ref="evidence://diag-first",
        subject_refs=[SOURCE_TASK, "ATT-1", "TC-DIRECT-RETRY"],
    )
    artifact = Artifact(
        artifact_id="ART-EXEC-FIRST",
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=SOURCE_TASK,
        content_ref="artifact://exec-first",
        evidence_refs=[evidence.evidence_id, diagnosis.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=SOURCE_TASK,
            worker_ref=WORKER,
            artifacts=(artifact,),
            evidence=(evidence, diagnosis),
        )
    )
    gap = Gap(
        gap_id=GAP_ID,
        mission_id=MISSION,
        source_node="EXECUTION",
        category="TRANSIENT_FAILURE",
        severity=GapSeverity.MEDIUM,
        target_node="EXECUTION",
        description="evidence-backed transient timeout",
        subject_refs=["ATT-1", "TC-DIRECT-RETRY"],
        evidence_refs=[evidence.evidence_id, diagnosis.evidence_id],
        acceptance_criteria=["authorized successor attempt is executed and independently reevaluated"],
    )
    evaluation = Evaluation(
        evaluation_id="EVAL-EXEC-FIRST",
        mission_id=MISSION,
        node="EXECUTION",
        artifact_refs=[artifact.artifact_id],
        result=EvaluationResult.REPAIR_REQUIRED,
        evaluator_ref="runtime-execution-gate",
        dimensions={
            "test_result": "INCONCLUSIVE",
            "failure_class": "TRANSIENT",
            "recovery_action": "RETRY_SAME_STEP",
            "attempt_id": "ATT-1",
        },
        gap_refs=[gap.gap_id],
        evidence_refs=[evidence.evidence_id, diagnosis.evidence_id],
    )
    control.accept_evaluation(SOURCE_TASK, evaluation=evaluation, gaps=(gap,))


def test_direct_retry_is_authorized_through_repair_task_then_source_pass_closes_gap(tmp_path: Path):
    truth, control = _control(tmp_path)
    _submit_first_failure(control)
    assert control.scheduler.task(SOURCE_TASK).state == TaskStatus.REPAIR_REQUIRED
    assert truth.query("rc7_gap", gap_id=GAP_ID)[0]["state"] == "PLANNED"

    plan = RecoveryWorkPlan(
        diagnosis_id="DIAG-1",
        source_attempt_id="ATT-1",
        action="RETRY_SAME_STEP",
        mode="DIRECT_RETRY",
        target_node="EXECUTION",
        retry_allowed=True,
        reprepare_required=False,
        terminal=False,
        successor_attempt_id="ATT-2",
        reason="TRANSIENT_FAILURE",
    )
    controller = ExecutionRecoveryController(evidence_root=str(tmp_path / "recovery"))
    authorization = controller.authorize_direct_retry(
        control,
        source_task_id=SOURCE_TASK,
        gap_id=GAP_ID,
        plan=plan,
        prepared=_prepared("ATT-1"),
        diagnosis_evidence_id="EVD-DIAG-1",
    )

    assert authorization.successor_attempt_id == "ATT-2"
    assert authorization.prepared.attempt_id == "ATT-2"
    assert authorization.diagnosis_evidence_id == "EVD-DIAG-1"
    assert control.scheduler.task(SOURCE_TASK).state == TaskStatus.READY
    assert truth.query("rc7_gap", gap_id=GAP_ID)[0]["state"] == "EVIDENCE_PENDING"
    repair_rows = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "REPAIR" and row.get("gap_refs") == [GAP_ID]
    ]
    assert len(repair_rows) == 1
    assert repair_rows[0]["state"] == "PASS"
    plan_artifact = truth.query("rc7_artifact", artifact_id=authorization.plan_artifact_id)
    assert len(plan_artifact) == 1
    assert "EVD-DIAG-1" in plan_artifact[0]["evidence_refs"]
    assert len(truth.query("rc7_evidence", evidence_id=authorization.plan_evidence_id)) == 1
    ExecutionRecoveryController.verify_successor(authorization, authorization.prepared)
    with pytest.raises(RecoveryControlError, match="UNAUTHORIZED_RETRY_ATTEMPT_ID"):
        ExecutionRecoveryController.verify_successor(authorization, _prepared("ATT-OLD"))

    leased = control.lease_next(worker_ref=WORKER, capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE_TASK
    control.start(SOURCE_TASK, worker_ref=WORKER)
    evidence = Evidence(
        evidence_id="EVD-EXEC-SECOND",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://execution",
        content_ref="evidence://exec-second",
        subject_refs=[SOURCE_TASK, "ATT-2"],
    )
    artifact = Artifact(
        artifact_id="ART-EXEC-SECOND",
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=SOURCE_TASK,
        content_ref="artifact://exec-second",
        evidence_refs=[evidence.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=SOURCE_TASK,
            worker_ref=WORKER,
            artifacts=(artifact,),
            evidence=(evidence,),
        )
    )
    control.accept_evaluation(
        SOURCE_TASK,
        evaluation=Evaluation(
            evaluation_id="EVAL-EXEC-SECOND",
            mission_id=MISSION,
            node="EXECUTION",
            artifact_refs=[artifact.artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="runtime-execution-gate",
            dimensions={"test_result": "PASS", "attempt_id": "ATT-2"},
            evidence_refs=[evidence.evidence_id],
        ),
    )

    assert control.scheduler.task(SOURCE_TASK).state == TaskStatus.PASS
    final_gap = truth.query("rc7_gap", gap_id=GAP_ID)[0]
    assert final_gap["state"] == "RESOLVED"
    assert final_gap["resolution_evaluation_id"] == "EVAL-EXEC-SECOND"
