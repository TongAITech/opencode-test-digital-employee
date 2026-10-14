from __future__ import annotations

import pytest

from rc6_runtime.diagnosis import (
    AttemptHistory,
    DiagnosisResult,
    FailureContext,
    RecoveryEngine,
    history_entry_from_execution,
)
from rc6_runtime.execution import ExecutionRecord
from rc6_runtime.truth import TruthRuntime
from rc7_runtime import (
    Artifact,
    ClosedLoopControlError,
    ClosedLoopControlPlane,
    Evaluation,
    EvaluationResult,
    Evidence,
    Mission,
    Task,
    TaskStatus,
)
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.execution_loop import ExecutionClosedLoop


def test_trusted_product_fail_passes_execution_work_and_spawns_defect_qualification(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id="MISSION-DEFECT-HANDOFF", release_id="RC7", goal="find a real product defect"),
    )
    task = Task(
        task_id="TASK-EXEC-HANDOFF",
        mission_id="MISSION-DEFECT-HANDOFF",
        node="EXECUTION",
        task_type="PRODUCE",
        objective="reach trustworthy product test conclusion",
        required_capabilities=["test_execution"],
    )
    control.register_task(task)
    leased = control.lease_next(worker_ref="worker-execution", capabilities=["test_execution"])
    assert leased is not None and leased.task_id == task.task_id
    control.start(task.task_id, worker_ref="worker-execution")
    candidate = control.submit_worker_output(
        WorkerOutput(
            task_id=task.task_id,
            worker_ref="worker-execution",
            evidence=(
                Evidence(
                    evidence_id="EVD-EXEC-PRODUCT-FAIL",
                    mission_id="MISSION-DEFECT-HANDOFF",
                    kind="EXECUTION_PROOF",
                    source_ref="runner://attempt-1",
                    content_ref="evidence://attempt-1",
                ),
            ),
            artifacts=(
                Artifact(
                    artifact_id="ART-EXEC-PRODUCT-FAIL",
                    mission_id="MISSION-DEFECT-HANDOFF",
                    artifact_type="EXECUTION_CONCLUSION",
                    producer_task_id=task.task_id,
                    content_ref="artifact://execution-fail",
                    evidence_refs=["EVD-EXEC-PRODUCT-FAIL"],
                ),
            ),
        )
    )
    assert candidate.state == TaskStatus.OUTPUT_PRODUCED

    record = ExecutionRecord(
        attempt_id="ATT-PRODUCT-FAIL",
        tc_id="TC-PRODUCT-FAIL",
        case_version=1,
        target_id="TARGET-1",
        layer="L3",
        worker_id="worker-execution",
        lease_id="lease-execution",
        status="FAIL",
        integrity_passed=True,
        actual_result={"business_code": "WRONG_RESULT"},
        tool_call_refs=("call://api/1",),
        evidence_refs=("EVD-EXEC-PRODUCT-FAIL",),
        assertion_ref="assertion://expected-result",
        assertion_passed=False,
        reason="ORACLE_ASSERTION_FAILED",
    )
    context = FailureContext(
        attempt_id=record.attempt_id,
        tc_id=record.tc_id,
        case_version=record.case_version,
        target_id=record.target_id,
        layer=record.layer,
        execution_status="FAIL",
        preparation_verified=True,
        real_action_executed=True,
        assertion_failed=True,
        execution_evidence_refs=record.evidence_refs,
        case_oracle_verified=True,
        executable_spec_verified=True,
        script_validated=True,
        data_verified=True,
        auth_verified=True,
        route_verified=True,
        tool_verified=True,
        environment_verified=True,
        dependency_verified=True,
    )
    diagnosis = DiagnosisResult(
        diagnosis_id="DIAG-PRODUCT-1",
        attempt_id=record.attempt_id,
        failure_class="PRODUCT",
        evidence_refs=("EVD-DIAG-PRODUCT",),
        cat_required=False,
        cat_queried=False,
        rationale="all competing failure owners excluded by evidence",
        classifier_ref="classifier://evidence-backed",
    )
    history = AttemptHistory()
    history.append(history_entry_from_execution(record))
    recovery = RecoveryEngine(history).decide(context, diagnosis)
    result = ExecutionClosedLoop().evaluate(
        mission_id="MISSION-DEFECT-HANDOFF",
        artifact_ref="ART-EXEC-PRODUCT-FAIL",
        record=record,
        diagnosis=diagnosis,
        recovery=recovery,
    )
    assert result.test_result == "FAIL"
    assert result.evaluation.result == EvaluationResult.PASS
    product_gap = next(gap for gap in result.gaps if gap.category == "PRODUCT_DEFECT")

    accepted = control.accept_evaluation(
        task.task_id,
        evaluation=result.evaluation,
        gaps=result.gaps,
    )
    assert accepted.state == TaskStatus.PASS
    assert truth.query("rc7_evaluation", evaluation_id=result.evaluation.evaluation_id)[0]["dimensions"]["test_result"] == "FAIL"

    persisted_gap = truth.query("rc7_gap", gap_id=product_gap.gap_id)[0]
    assert persisted_gap["state"] == "PLANNED"
    defect_tasks = [
        row
        for row in truth.query("rc7_task", mission_id="MISSION-DEFECT-HANDOFF")
        if row["node"] == "DEFECT"
    ]
    assert len(defect_tasks) == 1
    assert defect_tasks[0]["task_type"] == "QUALIFY_DEFECT"
    assert defect_tasks[0]["state"] == "READY"
    assert defect_tasks[0]["gap_refs"] == [product_gap.gap_id]

    # Product FAIL is a conclusive execution result, not Mission completion.
    mission_eval = Evaluation(
        evaluation_id="EVAL-MISSION-TOO-EARLY",
        mission_id="MISSION-DEFECT-HANDOFF",
        node="MISSION_EVALUATION",
        artifact_refs=["ART-EXEC-PRODUCT-FAIL"],
        result=EvaluationResult.PASS,
        evaluator_ref="mission-sufficiency-gate",
        dimensions={"sufficiency_state": "SUFFICIENT"},
    )
    with pytest.raises(ClosedLoopControlError, match="MISSION_HAS_ACTIVE_TASKS|MISSION_HAS_OPEN_GAPS"):
        control.converge_mission(mission_eval)

    leased_defect = control.lease_next(worker_ref="worker-defect", capabilities=["defect_analysis"])
    assert leased_defect is not None
    assert leased_defect.task_id == defect_tasks[0]["task_id"]
    assert leased_defect.task_type == "QUALIFY_DEFECT"
    assert truth.query("rc7_gap", gap_id=product_gap.gap_id)[0]["state"] == "PLANNED"
