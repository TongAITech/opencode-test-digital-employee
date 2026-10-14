from __future__ import annotations

from rc6_runtime.diagnosis import (
    AttemptHistory,
    DiagnosisResult,
    FailureContext,
    RecoveryEngine,
    history_entry_from_execution,
)
from rc6_runtime.execution import ExecutionRecord
from rc7_runtime import Task, TaskStatus, transition_task
from rc7_runtime.execution_loop import ExecutionClosedLoop


def _record(*, integrity: bool, assertion_passed, reason: str, status: str = "FAIL"):
    return ExecutionRecord(
        attempt_id="ATT-1",
        tc_id="TC-1",
        case_version=1,
        target_id="TARGET-1",
        layer="L3",
        worker_id="worker-l3",
        lease_id="lease-1",
        status=status,
        integrity_passed=integrity,
        actual_result={"business_code": "ACTUAL"} if status != "BLOCKED" else None,
        tool_call_refs=("call://api/1",) if status != "BLOCKED" else (),
        evidence_refs=("EVD-EXEC-1",),
        assertion_ref="assertion://1" if assertion_passed is not None else None,
        assertion_passed=assertion_passed,
        reason=reason,
    )


def _diagnosis(failure_class: str, rationale: str) -> DiagnosisResult:
    return DiagnosisResult(
        diagnosis_id="DIAG-%s" % failure_class,
        attempt_id="ATT-1",
        failure_class=failure_class,
        evidence_refs=("EVD-DIAG-%s" % failure_class,),
        cat_required=False,
        cat_queried=False,
        rationale=rationale,
        classifier_ref="classifier://evidence-backed",
    )


def _task() -> Task:
    task = Task(
        task_id="TASK-EXEC-1",
        mission_id="MISSION-1",
        node="EXECUTION",
        task_type="EXECUTE",
        objective="Reach a trustworthy execution conclusion",
    )
    transition_task(task, TaskStatus.READY)
    transition_task(task, TaskStatus.LEASED, lease_owner="execution-session-A")
    transition_task(task, TaskStatus.RUNNING)
    transition_task(task, TaskStatus.OUTPUT_PRODUCED)
    return task


def test_trusted_product_fail_is_conclusive_but_never_rewritten_as_test_pass(tmp_path) -> None:
    record = _record(
        integrity=True,
        assertion_passed=False,
        reason="ORACLE_ASSERTION_FAILED",
    )
    context = FailureContext(
        attempt_id="ATT-1",
        tc_id="TC-1",
        case_version=1,
        target_id="TARGET-1",
        layer="L3",
        execution_status="FAIL",
        preparation_verified=True,
        real_action_executed=True,
        assertion_failed=True,
        execution_evidence_refs=("EVD-EXEC-1",),
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
    diagnosis = _diagnosis("PRODUCT", "all competing ownership classes excluded by evidence")
    history = AttemptHistory()
    history.append(history_entry_from_execution(record))
    recovery = RecoveryEngine(history).decide(context, diagnosis)
    assert recovery.action == "PRODUCT_DEFECT"
    assert recovery.retry_allowed is False
    assert recovery.terminal is True

    loop = ExecutionClosedLoop()
    result = loop.evaluate(
        mission_id="MISSION-1",
        artifact_ref="ART-EXEC-1",
        record=record,
        diagnosis=diagnosis,
        recovery=recovery,
    )

    assert result.test_result == "FAIL"
    assert result.conclusive is True
    assert result.evaluation.result.value == "PASS"
    assert result.evaluation.dimensions["test_result"] == "FAIL"
    product_gap = next(gap for gap in result.gaps if gap.category == "PRODUCT_DEFECT")
    assert product_gap.target_node == "DEFECT"

    task = _task()
    loop.accept_candidate(task, result)
    assert task.state == TaskStatus.PASS
    assert result.test_result != "PASS"

    # The control/evidence truth preserves the FAIL while allowing the
    # execution-work Task to converge and hand ownership to Defect.
    from rc6_runtime.truth import TruthRuntime

    truth = TruthRuntime(tmp_path / "r1.jsonl")
    loop.persist(truth, release_id="RC7", result=result)
    persisted = truth.query("rc7_evaluation", evaluation_id=result.evaluation.evaluation_id)[0]
    assert persisted["dimensions"]["test_result"] == "FAIL"


def test_script_owned_failure_routes_back_to_script_and_does_not_converge() -> None:
    record = _record(
        integrity=False,
        assertion_passed=None,
        reason="IMPORT_ERROR",
    )
    context = FailureContext(
        attempt_id="ATT-1",
        tc_id="TC-1",
        case_version=1,
        target_id="TARGET-1",
        layer="L3",
        execution_status="FAIL",
        preparation_verified=True,
        real_action_executed=False,
        assertion_failed=False,
        execution_evidence_refs=("EVD-EXEC-1",),
    )
    diagnosis = _diagnosis("SCRIPT", "import failure proven by runner evidence")
    history = AttemptHistory()
    history.append(history_entry_from_execution(record))
    recovery = RecoveryEngine(history).decide(context, diagnosis)
    assert recovery.action == "REPAIR_SCRIPT"
    assert recovery.retry_allowed is True

    result = ExecutionClosedLoop().evaluate(
        mission_id="MISSION-1",
        artifact_ref="ART-EXEC-1",
        record=record,
        diagnosis=diagnosis,
        recovery=recovery,
    )
    assert result.test_result == "INCONCLUSIVE"
    assert result.conclusive is False
    assert result.evaluation.result.value == "REPAIR_REQUIRED"
    assert any(
        gap.category == "SCRIPT_DEFECT" and gap.target_node == "SCRIPT_READINESS"
        for gap in result.gaps
    )


def test_oracle_fail_without_diagnosis_cannot_be_called_product_defect() -> None:
    record = _record(
        integrity=True,
        assertion_passed=False,
        reason="ORACLE_ASSERTION_FAILED",
    )
    result = ExecutionClosedLoop().evaluate(
        mission_id="MISSION-1",
        artifact_ref="ART-EXEC-1",
        record=record,
    )
    assert result.test_result == "FAIL"
    assert result.conclusive is False
    assert result.evaluation.result.value == "REPAIR_REQUIRED"
    assert [gap.category for gap in result.gaps] == ["DIAGNOSIS_REQUIRED"]
