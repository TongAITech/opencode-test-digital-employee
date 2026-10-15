from __future__ import annotations

import rc7_runtime


def test_autonomous_execution_closed_loop_is_public_runtime_api():
    expected = {
        "ExecutionTrustFacts",
        "DiagnosisClosure",
        "ExecutionDiagnosisCoordinator",
        "LineageAwareAttemptHistory",
        "LineageAwareExecutionDiagnosisCoordinator",
        "RecoveryWorkPlan",
        "ExecutionRecoveryPlanner",
        "RecoveryPlanningError",
        "ExecutionRecoveryController",
        "DirectRetryAuthorization",
        "RecoveryControlError",
        "AutonomousExecutionLoop",
        "AutonomousExecutionLoopResult",
        "AutonomousExecutionLoopError",
        "AutonomousClosedLoopExecutionService",
        "AutonomousExecutionServiceError",
    }
    assert expected.issubset(set(rc7_runtime.__all__))
    for name in expected:
        assert getattr(rc7_runtime, name) is not None
