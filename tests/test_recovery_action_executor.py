from rc6_runtime.diagnosis import (
    AttemptHistory,
    AttemptHistoryEntry,
    DiagnosisResult,
    FailureContext,
    FailureSignature,
    RecoveryDecision,
)
from rc6_runtime.recovery import (
    ExecutionBudgets,
    ExecutionConvergenceController,
    RecoveryActionError,
    RecoveryActionExecutor,
)


def context(attempt="ATT-1"):
    return FailureContext(
        attempt_id=attempt,
        tc_id="TC-1",
        case_version=1,
        target_id="TARGET-1",
        layer="L3",
        execution_status="FAIL",
        preparation_verified=True,
        real_action_executed=True,
        assertion_failed=False,
        execution_evidence_refs=("evidence://execution/1",),
        exception_type="ConnectionError",
        root_stack_frame="client.request:42",
        route="/old-route",
    )


def diagnosis(ctx, failure_class="ROUTE"):
    return DiagnosisResult(
        diagnosis_id="diag-1",
        attempt_id=ctx.attempt_id,
        failure_class=failure_class,
        evidence_refs=("evidence://diag/1",),
        cat_required=False,
        cat_queried=False,
        rationale="evidence-backed",
        classifier_ref="classifier://v2",
        failure_signature=FailureSignature.from_context(ctx),
    )


def history():
    h = AttemptHistory()
    h.append(AttemptHistoryEntry("ATT-1", None, "TC-1", 1, "TARGET-1", "L3", "FAIL", ("evidence://execution/1",), 1))
    return h


def test_route_recovery_executes_adapter_and_creates_fresh_attempt():
    h = history()
    ctx = context()
    diag = diagnosis(ctx, "ROUTE")
    decision = RecoveryDecision("diag-1", "ATT-1", "RECONCILE_ROUTE_BINDING", True, False, False, "ATT-2", "route")
    executor = RecoveryActionExecutor(
        history=h,
        adapters={
            "RECONCILE_ROUTE_BINDING": lambda c, d, r: {
                "verified": True,
                "evidence_refs": ["evidence://route/reconciled"],
                "output_refs": ["route-binding://cfg-data/v2"],
            }
        },
    )
    result = executor.execute(context=ctx, diagnosis=diag, decision=decision)
    assert result.status == "RECOVERY_EXECUTED"
    assert result.next_attempt_id == "ATT-2"
    assert h.get("ATT-2").parent_attempt_id == "ATT-1"
    assert h.get("ATT-2").status == "RECOVERY_READY"


def test_recovery_cannot_claim_success_without_required_output():
    h = history()
    ctx = context()
    diag = diagnosis(ctx, "SCRIPT")
    decision = RecoveryDecision("diag-1", "ATT-1", "REPAIR_SCRIPT", True, False, False, "ATT-2", "script")
    executor = RecoveryActionExecutor(
        history=h,
        adapters={
            "REPAIR_SCRIPT": lambda c, d, r: {
                "verified": True,
                "evidence_refs": ["evidence://script/repair"],
                "output_refs": ["script://rev2"],
            }
        },
    )
    try:
        executor.execute(context=ctx, diagnosis=diag, decision=decision)
        assert False, "expected validation evidence failure"
    except RecoveryActionError as exc:
        assert "validation://" in str(exc)


def test_same_failure_signature_stops_blind_retry_loop():
    h = history()
    budgets = ExecutionBudgets(max_execution_attempts=5, max_same_signature_repeats=0)
    controller = ExecutionConvergenceController(h, budgets)
    ctx = context()
    diag = diagnosis(ctx, "ROUTE")
    first = controller.evaluate_failure(diag)
    assert first.allow_recovery
    second = controller.evaluate_failure(diag)
    assert not second.allow_recovery
    assert second.terminal_status == "MANUAL_REQUIRED"
    assert second.reason == "SAME_FAILURE_SIGNATURE_REPEATED"


def test_product_is_terminal_and_recovery_does_not_create_attempt():
    h = history()
    ctx = context()
    diag = diagnosis(ctx, "PRODUCT")
    decision = RecoveryDecision("diag-1", "ATT-1", "PRODUCT_DEFECT", False, False, True, None, "product")
    result = RecoveryActionExecutor(history=h).execute(context=ctx, diagnosis=diag, decision=decision)
    assert result.terminal_status == "PRODUCT_DEFECT_CONFIRMED"
    assert len(h.entries()) == 1
