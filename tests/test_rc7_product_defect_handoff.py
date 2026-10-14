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
from rc7_runtime.defect_loop import (
    DefectClosedLoop,
    DefectQualificationInput,
    DefectStatus,
    RootCauseHypothesis,
)
from rc7_runtime.execution_loop import ExecutionClosedLoop


MISSION_ID = "MISSION-DEFECT-HANDOFF"


def test_trusted_product_fail_closes_only_after_defect_fix_verification_and_regression(tmp_path) -> None:
    event_path = tmp_path / "r1.jsonl"
    truth = TruthRuntime(event_path)
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION_ID, release_id="RC7", goal="find and close a real product defect"),
    )
    task = Task(
        task_id="TASK-EXEC-HANDOFF",
        mission_id=MISSION_ID,
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
                    mission_id=MISSION_ID,
                    kind="EXECUTION_PROOF",
                    source_ref="runner://attempt-1",
                    content_ref="evidence://attempt-1",
                ),
            ),
            artifacts=(
                Artifact(
                    artifact_id="ART-EXEC-PRODUCT-FAIL",
                    mission_id=MISSION_ID,
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
        mission_id=MISSION_ID,
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
    persisted_execution_eval = truth.query(
        "rc7_evaluation", evaluation_id=result.evaluation.evaluation_id
    )[0]
    assert persisted_execution_eval["dimensions"]["test_result"] == "FAIL"

    persisted_gap = truth.query("rc7_gap", gap_id=product_gap.gap_id)[0]
    assert persisted_gap["state"] == "PLANNED"
    defect_tasks = [
        row
        for row in truth.query("rc7_task", mission_id=MISSION_ID)
        if row["node"] == "DEFECT"
    ]
    assert len(defect_tasks) == 1
    assert defect_tasks[0]["task_type"] == "QUALIFY_DEFECT"
    assert defect_tasks[0]["state"] == "READY"
    assert defect_tasks[0]["gap_refs"] == [product_gap.gap_id]

    # A conclusive product FAIL is not Mission completion. The product Gap and
    # its Defect qualification task remain active owners of the unresolved risk.
    too_early = Evaluation(
        evaluation_id="EVAL-MISSION-TOO-EARLY",
        mission_id=MISSION_ID,
        node="MISSION_EVALUATION",
        artifact_refs=["ART-EXEC-PRODUCT-FAIL"],
        result=EvaluationResult.PASS,
        evaluator_ref="mission-sufficiency-gate",
        dimensions={"sufficiency_state": "SUFFICIENT"},
    )
    with pytest.raises(ClosedLoopControlError, match="MISSION_HAS_ACTIVE_TASKS|MISSION_HAS_OPEN_GAPS"):
        control.converge_mission(too_early)

    leased_defect = control.lease_next(worker_ref="worker-defect", capabilities=["defect_analysis"])
    assert leased_defect is not None
    assert leased_defect.task_id == defect_tasks[0]["task_id"]
    assert leased_defect.task_type == "QUALIFY_DEFECT"
    assert truth.query("rc7_gap", gap_id=product_gap.gap_id)[0]["state"] == "REPAIRING"
    control.start(leased_defect.task_id, worker_ref="worker-defect")

    # Defect lifecycle is evidence backed. A PRODUCT_DEFECT Gap is not closed
    # by classification alone: reproduce, qualify, attach RCA, verify the fix,
    # and execute impact regression before terminal closure is legal.
    defect_loop = DefectClosedLoop()
    defect = defect_loop.create_candidate(
        mission_id=MISSION_ID,
        product_gap=product_gap,
        requirement_refs=["REQ-PRODUCT-1"],
        test_case_id=record.tc_id,
        execution_attempt_id=record.attempt_id,
        expected={"business_code": "EXPECTED_RESULT", "db": "UNCHANGED"},
        actual={"business_code": "WRONG_RESULT", "db": "CHANGED"},
        evidence_refs=["EVD-DB-BEFORE-AFTER"],
        severity="HIGH",
    )
    defect_loop.transition(defect, DefectStatus.QUALIFYING)
    defect_loop.record_reproduction(
        defect,
        attempt_id="ATT-PRODUCT-REPRO",
        reproduced=True,
        evidence_refs=["EVD-REPRO-PRODUCT"],
    )
    qualification = defect_loop.evaluate_qualification(
        defect,
        DefectQualificationInput(
            execution_trusted=True,
            oracle_valid=True,
            evidence_complete=True,
            script_issue_excluded=True,
            data_issue_excluded=True,
            environment_issue_excluded=True,
            reproducible=True,
        ),
    )
    assert qualification.qualified is True
    assert defect.state == DefectStatus.EVIDENCE_READY

    defect_loop.attach_root_cause_hypothesis(
        defect,
        RootCauseHypothesis(
            hypothesis_id="RCA-PRODUCT-1",
            statement="persistence branch executes after business validation failure",
            suspected_symbols=("RateService.adjustRate", "RateRepository.updateRate"),
            evidence_refs=("EVD-RCA-PRODUCT",),
            confidence=0.91,
        ),
    )
    defect_loop.transition(defect, DefectStatus.READY_FOR_REVIEW)
    defect_loop.transition(defect, DefectStatus.CONFIRMED, evaluation_id="EVAL-DEFECT-CONFIRMED")
    defect_loop.transition(defect, DefectStatus.FIX_PENDING)
    defect_loop.transition(defect, DefectStatus.FIX_DETECTED, fix_revision="fix-sha-product-1")
    defect_loop.transition(defect, DefectStatus.VERIFYING)
    defect_loop.transition(
        defect,
        DefectStatus.FIXED,
        verification_refs=["EXEC-ORIGINAL-CASE-VERIFY-PASS"],
    )
    defect_loop.transition(defect, DefectStatus.REGRESSION_TESTING)

    final_evaluation_id = "EVAL-DEFECT-CLOSED"
    defect_loop.transition(
        defect,
        DefectStatus.CLOSED,
        evaluation_id=final_evaluation_id,
        regression_refs=["EXEC-IMPACT-REGRESSION-1", "EXEC-IMPACT-REGRESSION-2"],
    )
    assert defect.state == DefectStatus.CLOSED

    defect_candidate = control.submit_worker_output(
        WorkerOutput(
            task_id=leased_defect.task_id,
            worker_ref="worker-defect",
            evidence=(
                Evidence(
                    evidence_id="EVD-DEFECT-CLOSURE",
                    mission_id=MISSION_ID,
                    kind="DEFECT_CLOSURE_PROOF",
                    source_ref="defect://%s" % defect.defect_id,
                    content_ref="evidence://defect-closure",
                ),
            ),
            artifacts=(
                Artifact(
                    artifact_id="ART-DEFECT-CLOSURE",
                    mission_id=MISSION_ID,
                    artifact_type="DEFECT_CLOSURE",
                    producer_task_id=leased_defect.task_id,
                    content_ref="defect://%s" % defect.defect_id,
                    evidence_refs=[
                        "EVD-DEFECT-CLOSURE",
                        "EXEC-ORIGINAL-CASE-VERIFY-PASS",
                        "EXEC-IMPACT-REGRESSION-1",
                    ],
                ),
            ),
        )
    )
    assert defect_candidate.state == TaskStatus.OUTPUT_PRODUCED

    defect_resolution = Evaluation(
        evaluation_id=final_evaluation_id,
        mission_id=MISSION_ID,
        node="DEFECT",
        artifact_refs=["ART-DEFECT-CLOSURE"],
        result=EvaluationResult.PASS,
        evaluator_ref="evaluator-defect-independent",
        dimensions={
            "defect_id": defect.defect_id,
            "defect_state": "CLOSED",
            "fix_revision": defect.fix_revision,
            "fix_verified": True,
            "impact_regression_passed": True,
        },
        evidence_refs=[
            "EXEC-ORIGINAL-CASE-VERIFY-PASS",
            "EXEC-IMPACT-REGRESSION-1",
            "EXEC-IMPACT-REGRESSION-2",
        ],
    )
    closed_task = control.accept_defect_resolution(
        leased_defect.task_id,
        defect=defect,
        evaluation=defect_resolution,
    )
    assert closed_task.state == TaskStatus.PASS
    assert truth.query("rc7_gap", gap_id=product_gap.gap_id)[0]["state"] == "RESOLVED"
    persisted_defect = truth.query("rc7_defect", defect_id=defect.defect_id)[0]
    assert persisted_defect["state"] == "CLOSED"
    assert persisted_defect["fix_revision"] == "fix-sha-product-1"
    assert persisted_defect["verification_refs"] == ["EXEC-ORIGINAL-CASE-VERIFY-PASS"]
    assert persisted_defect["regression_refs"] == [
        "EXEC-IMPACT-REGRESSION-1",
        "EXEC-IMPACT-REGRESSION-2",
    ]
    assert control.snapshot()["open_gap_ids"] == []

    # Only after the Defect task and product Gap are closed may Mission
    # sufficiency converge the same Mission.
    mission_eval = Evaluation(
        evaluation_id="EVAL-MISSION-AFTER-DEFECT",
        mission_id=MISSION_ID,
        node="MISSION_EVALUATION",
        artifact_refs=["ART-EXEC-PRODUCT-FAIL", "ART-DEFECT-CLOSURE"],
        result=EvaluationResult.PASS,
        evaluator_ref="mission-sufficiency-gate",
        dimensions={"sufficiency_state": "SUFFICIENT"},
        evidence_refs=["EVD-DEFECT-CLOSURE", "EXEC-IMPACT-REGRESSION-1"],
    )
    mission = control.converge_mission(mission_eval)
    assert mission.state.value == "CONVERGED"

    # A brand-new runtime reconstructs the full product-defect closure solely
    # from R1: trusted FAIL, terminal Defect, resolved Gap, converged Mission.
    replay = TruthRuntime(event_path)
    recovered = ClosedLoopControlPlane(replay, "RC7", MISSION_ID)
    assert recovered.scheduler.task(task.task_id).state == TaskStatus.PASS
    assert recovered.scheduler.task(leased_defect.task_id).state == TaskStatus.PASS
    assert replay.query("rc7_gap", gap_id=product_gap.gap_id)[0]["state"] == "RESOLVED"
    assert replay.query("rc7_defect", defect_id=defect.defect_id)[0]["state"] == "CLOSED"
    assert recovered.snapshot()["mission_state"] == "CONVERGED"
