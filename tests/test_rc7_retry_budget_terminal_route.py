from __future__ import annotations

from rc6_runtime.diagnosis import DiagnosisResult, FailureSignature, RecoveryDecision
from rc6_runtime.execution import ExecutionRecord
from rc7_runtime.execution_loop import ExecutionClosedLoop


def test_retry_budget_exhaustion_routes_to_runtime_blocker_not_another_execution_retry():
    record = ExecutionRecord(
        attempt_id="ATT-RETRY-EXHAUSTED",
        tc_id="TC-RETRY-EXHAUSTED",
        case_version=1,
        target_id="TARGET-1",
        layer="L2",
        worker_id="runtime-worker",
        lease_id="runtime-lease",
        status="FAIL",
        integrity_passed=False,
        actual_result=None,
        tool_call_refs=(),
        evidence_refs=("EVD-EXEC-1",),
        assertion_ref=None,
        assertion_passed=None,
        reason="TIMEOUT",
    )
    diagnosis = DiagnosisResult(
        diagnosis_id="DIAG-RETRY-EXHAUSTED",
        attempt_id=record.attempt_id,
        failure_class="TRANSIENT",
        evidence_refs=("EVD-EXEC-1", "EVD-DIAG-1"),
        cat_required=False,
        cat_queried=False,
        rationale="transient failed after bounded retries",
        classifier_ref="runtime-classifier",
        failure_signature=FailureSignature(
            signature_id="FSIG-1",
            exception_type="TimeoutError",
            root_stack_frame=None,
            http_status=None,
            business_error_code=None,
            route=None,
            assertion_identity=None,
        ),
    )
    recovery = RecoveryDecision(
        diagnosis_id=diagnosis.diagnosis_id,
        attempt_id=record.attempt_id,
        action="RETRY_BUDGET_EXHAUSTED",
        retry_allowed=False,
        reprepare_allowed=False,
        terminal=True,
        next_attempt_id=None,
        reason="TRANSIENT_RETRY_LIMIT_REACHED",
    )

    result = ExecutionClosedLoop().evaluate(
        mission_id="MISSION-RETRY-EXHAUSTED",
        artifact_ref="ART-EXEC-1",
        record=record,
        diagnosis=diagnosis,
        recovery=recovery,
        evaluator_ref="runtime-execution-gate",
    )

    assert result.evaluation.result.value == "BLOCKED"
    assert result.conclusive is True
    assert len(result.gaps) == 1
    gap = result.gaps[0]
    assert gap.category == "RETRY_BUDGET_EXHAUSTED"
    assert gap.target_node == "RUNTIME"
    assert gap.severity.value == "BLOCKER"
    assert result.recovery_action == "RETRY_BUDGET_EXHAUSTED"
