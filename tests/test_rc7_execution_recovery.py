from __future__ import annotations

import pytest

from rc6_runtime.diagnosis import RecoveryDecision
from rc6_runtime.preparation import PreparedAttempt
from rc7_runtime.execution_recovery import ExecutionRecoveryPlanner, RecoveryPlanningError


def _decision(
    action,
    *,
    retry=True,
    reprepare=False,
    terminal=False,
    next_attempt="ATT-2",
):
    return RecoveryDecision(
        diagnosis_id="DIAG-1",
        attempt_id="ATT-1",
        action=action,
        retry_allowed=retry,
        reprepare_allowed=reprepare,
        terminal=terminal,
        next_attempt_id=next_attempt,
        reason="evidence-backed recovery",
    )


def _prepared():
    return PreparedAttempt(
        status="PREPARED",
        attempt_id="ATT-1",
        tc_id="TC-1",
        case_version=1,
        target_id="TARGET-1",
        precondition_evidence=("EVD-PRE-1",),
        initial_state_bindings={"loan": "L-1"},
        input_data_bindings={"delta": 1},
        binding_evidence=("EVD-DATA-1",),
        cleanup_policy={"mode": "NONE"},
        oracle_snapshot={"checks": [{"id": "C1", "type": "BUSINESS_RULE", "actual_path": "code", "operator": "EQ", "expected": "OK"}]},
    )


def test_transient_retry_compiles_direct_successor_attempt_without_mutating_binding():
    planner = ExecutionRecoveryPlanner()
    plan = planner.compile(_decision("RETRY_SAME_STEP"))
    assert plan.mode == "DIRECT_RETRY"
    assert plan.target_node == "EXECUTION"
    assert plan.successor_attempt_id == "ATT-2"

    successor = planner.compile_successor_prepared_attempt(_prepared(), plan)
    assert successor.attempt_id == "ATT-2"
    assert successor.tc_id == "TC-1"
    assert successor.initial_state_bindings == {"loan": "L-1"}
    assert successor.oracle_snapshot == _prepared().oracle_snapshot


def test_auth_recovery_requires_runtime_reprepare_before_retry():
    plan = ExecutionRecoveryPlanner().compile(_decision("REAUTH", reprepare=True))
    assert plan.mode == "REPREPARE_THEN_RETRY"
    assert plan.target_node == "RUNTIME"
    assert plan.reprepare_required is True
    with pytest.raises(RecoveryPlanningError, match="PREPARED_ATTEMPT_REUSE_NOT_ALLOWED"):
        ExecutionRecoveryPlanner.compile_successor_prepared_attempt(_prepared(), plan)


@pytest.mark.parametrize("action", ["RESEARCH_OR_REBUILD_DATA", "RECONSTRUCT_PRECONDITION"])
def test_data_and_precondition_recovery_return_to_runtime_preparation(action: str):
    plan = ExecutionRecoveryPlanner().compile(_decision(action, reprepare=True))
    assert plan.mode == "REPREPARE_THEN_RETRY"
    assert plan.target_node == "RUNTIME"
    assert plan.reprepare_required is True
    with pytest.raises(RecoveryPlanningError, match="PREPARED_ATTEMPT_REUSE_NOT_ALLOWED"):
        ExecutionRecoveryPlanner.compile_successor_prepared_attempt(_prepared(), plan)


def test_script_repair_routes_upstream_then_allows_new_attempt_only_after_repair():
    plan = ExecutionRecoveryPlanner().compile(_decision("REPAIR_SCRIPT"))
    assert plan.mode == "UPSTREAM_REPAIR_THEN_RETRY"
    assert plan.target_node == "SCRIPT_READINESS"
    assert plan.successor_attempt_id == "ATT-2"
    successor = ExecutionRecoveryPlanner.compile_successor_prepared_attempt(_prepared(), plan)
    assert successor.attempt_id == "ATT-2"


def test_product_defect_is_terminal_and_cannot_be_compiled_as_retry():
    plan = ExecutionRecoveryPlanner().compile(
        _decision("PRODUCT_DEFECT", retry=False, terminal=True, next_attempt=None)
    )
    assert plan.mode == "TERMINAL"
    assert plan.target_node == "DEFECT"
    assert plan.retry_allowed is False
    assert plan.successor_attempt_id is None
    with pytest.raises(RecoveryPlanningError):
        ExecutionRecoveryPlanner.compile_successor_prepared_attempt(_prepared(), plan)


def test_retry_action_without_successor_attempt_fails_closed():
    with pytest.raises(RecoveryPlanningError, match="RECOVERY_SUCCESSOR_ATTEMPT_REQUIRED"):
        ExecutionRecoveryPlanner().compile(_decision("RETRY_SAME_STEP", next_attempt=None))


def test_terminal_action_cannot_smuggle_retry_permission():
    with pytest.raises(RecoveryPlanningError, match="TERMINAL_RECOVERY_CANNOT_CREATE_RETRY"):
        ExecutionRecoveryPlanner().compile(
            _decision("PRODUCT_DEFECT", retry=True, terminal=True, next_attempt="ATT-2")
        )
