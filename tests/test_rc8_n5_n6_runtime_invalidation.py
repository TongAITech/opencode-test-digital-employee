from rc8_center.executable_readiness import CenterExecutableReadinessService, ExecutableReadinessError, ExecutableReadinessState, MemoryExecutableSpecRepository
from rc8_center.prepared_attempt import CenterPreparedAttemptService, MemoryPreparedAttemptRepository, PreparedAttemptState
from rc8_center.runtime_invalidation import CenterRuntimeInvalidationCoordinator


def _ready_chain(now=100):
    clock = lambda: now
    n5 = CenterPreparedAttemptService(MemoryPreparedAttemptRepository(), now_fn=clock)
    n6 = CenterExecutableReadinessService(MemoryExecutableSpecRepository(), n5, now_fn=clock)
    n5.select(prepared_attempt_id="p1", test_run_id="run", mission_node_id="N5", case_id="c1", attempt_id="a1", reality_snapshot_id="rs1", data_refs=["data:1"])
    n5.verify("p1", evidence_refs=["ev:verify"])
    n5.reserve("p1", reservation_ref="reservation:1", evidence_refs=["ev:reserve"])
    n5.freshness_check("p1", data_freshness_ref="fresh:1", auth_session_ref="auth:new", auth_acquired_at=90, auth_expires_at=200, evidence_refs=["ev:fresh"])
    n5.bind("p1", environment_ref="env:1", route_ref="route:1", evidence_refs=["ev:bind"])
    n6.build(executable_spec_id="x1", test_run_id="run", mission_node_id="N6", case_id="c1", attempt_id="a1", prepared_attempt_id="p1", frozen_case_ref="case:rev1", driver_ref="pytest", script_artifact_ref="script:1", fixture_binding_refs=["fixture:1"], assertion_refs=["assert:business"], evidence_collector_refs=["collector:1"], build_evidence_refs=["ev:build"])
    n6.verify("x1", semantic_evidence_refs=["ev:semantic"])
    n6.mark_ready("x1")
    return n5, n6


def test_case_revision_invalidates_n5_and_n6_and_blocks_n7_execution():
    n5, n6 = _ready_chain()
    guard = CenterRuntimeInvalidationCoordinator(n5, n6)
    result = guard.invalidate_for_case_revision(test_run_id="run", case_id="c1", attempt_id="a1", evidence_refs=["case-diff:rev2"])
    assert result.prepared_attempt.state == PreparedAttemptState.QUARANTINED
    assert result.executable_spec.state == ExecutableReadinessState.INVALIDATED
    assert result.executable_spec.invalidation_reason == "FROZEN_CASE_REVISION_CHANGED"
    try:
        n6.require_ready_for_execution(executable_spec_id="x1", prepared_attempt_id="p1", test_run_id="run", case_id="c1", attempt_id="a1")
    except ExecutableReadinessError as exc:
        assert "TEST_EXECUTION_REQUIRES_CURRENT_EXECUTABLE_SPEC" in str(exc)
    else:
        raise AssertionError("N7 must not execute an invalidated N6 spec")


def test_runtime_binding_change_cascades_and_requires_new_preparation():
    n5, n6 = _ready_chain()
    guard = CenterRuntimeInvalidationCoordinator(n5, n6)
    result = guard.invalidate_for_runtime_binding_change(binding="AUTH", test_run_id="run", case_id="c1", attempt_id="a1", evidence_refs=["auth-expired:1"])
    assert result.reason == "AUTH_BINDING_CHANGED"
    assert n5.repository.current_for_attempt("run", "c1", "a1") is None
    assert n6.repository.current_for_attempt("run", "c1", "a1") is None
    fresh = n5.select(prepared_attempt_id="p2", test_run_id="run", mission_node_id="N5", case_id="c1", attempt_id="a1", reality_snapshot_id="rs2", data_refs=["data:2"])
    assert fresh.prepared_attempt_id == "p2"
    assert fresh.state == PreparedAttemptState.SELECTED
