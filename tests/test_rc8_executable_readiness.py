import unittest

from rc8_center.executable_readiness import CenterExecutableReadinessService, ExecutableReadinessError, ExecutableReadinessState, MemoryExecutableSpecRepository
from rc8_center.prepared_attempt import CenterPreparedAttemptService, MemoryPreparedAttemptRepository


class ExecutableReadinessTest(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.prep_repo = MemoryPreparedAttemptRepository()
        self.prep = CenterPreparedAttemptService(self.prep_repo, now_fn=lambda: self.now)
        self.repo = MemoryExecutableSpecRepository()
        self.service = CenterExecutableReadinessService(self.repo, self.prep, now_fn=lambda: self.now)

    def _prepare_n5(self):
        self.prep.select(prepared_attempt_id="prep-1", test_run_id="run-1", mission_node_id="run-1:scope:N5_TEST_DATA_PRECONDITIONS", case_id="case-1", attempt_id="attempt-1", reality_snapshot_id="reality:run-1:scope:v1", data_refs=("data://customer/001",))
        self.prep.verify("prep-1", evidence_refs=("evidence://verify/1",))
        self.prep.reserve("prep-1", reservation_ref="reservation://customer/001", evidence_refs=("evidence://reserve/1",))
        self.prep.freshness_check("prep-1", data_freshness_ref="freshness://data/1", auth_session_ref="auth://4a/fresh/1", auth_acquired_at=90, auth_expires_at=200, evidence_refs=("evidence://fresh/1",))
        self.prep.bind("prep-1", environment_ref="env://pfc/test", route_ref="route://browser-network/customer", evidence_refs=("evidence://bind/1",))

    def _build(self):
        return self.service.build(executable_spec_id="exec-1", test_run_id="run-1", mission_node_id="run-1:scope:N6_SCRIPT_BUILD_READINESS", case_id="case-1", attempt_id="attempt-1", prepared_attempt_id="prep-1", frozen_case_ref="case://case-1@v3", driver_ref="driver://pytest", script_artifact_ref="artifact://script/case-1.py", fixture_binding_refs=("fixture://customer", "fixture://auth"), assertion_refs=("assertion://status", "assertion://business-code"), evidence_collector_refs=("collector://response", "collector://log"), build_evidence_refs=("evidence://compile/1",))

    def test_n6_requires_current_n5_prepared_attempt(self):
        with self.assertRaisesRegex(ExecutableReadinessError, "N6_REQUIRES_N5_PREPARED_ATTEMPT"):
            self._build()

    def test_build_verify_ready_preserves_business_pass_separation(self):
        self._prepare_n5()
        built = self._build()
        self.assertEqual(ExecutableReadinessState.BUILT, built.state)
        verified = self.service.verify("exec-1", semantic_evidence_refs=("evidence://case-script-map/1",))
        self.assertEqual(ExecutableReadinessState.VERIFIED, verified.state)
        ready = self.service.mark_ready("exec-1")
        self.assertEqual(ExecutableReadinessState.READY, ready.state)
        self.assertFalse(hasattr(ready, "business_pass"))
        self.assertEqual("exec-1", self.service.require_ready_for_execution(executable_spec_id="exec-1", prepared_attempt_id="prep-1", test_run_id="run-1", case_id="case-1", attempt_id="attempt-1").executable_spec_id)

    def test_fresh_auth_expiry_invalidates_execution_readiness_gate(self):
        self._prepare_n5()
        self._build()
        self.service.verify("exec-1", semantic_evidence_refs=("evidence://semantic/1",))
        self.service.mark_ready("exec-1")
        self.now = 200
        with self.assertRaisesRegex(ExecutableReadinessError, "N6_REQUIRES_N5_PREPARED_ATTEMPT"):
            self.service.require_ready_for_execution(executable_spec_id="exec-1", prepared_attempt_id="prep-1", test_run_id="run-1", case_id="case-1", attempt_id="attempt-1")

    def test_invalidation_allows_rebuild_for_same_attempt(self):
        self._prepare_n5()
        self._build()
        self.service.invalidate("exec-1", reason="case version changed", evidence_refs=("evidence://case-v4",))
        replacement = self.service.build(executable_spec_id="exec-2", test_run_id="run-1", mission_node_id="run-1:scope:N6_SCRIPT_BUILD_READINESS", case_id="case-1", attempt_id="attempt-1", prepared_attempt_id="prep-1", frozen_case_ref="case://case-1@v4", driver_ref="driver://pytest", script_artifact_ref="artifact://script/case-1-v4.py", fixture_binding_refs=("fixture://customer",), assertion_refs=("assertion://status",), evidence_collector_refs=("collector://response",), build_evidence_refs=("evidence://compile/2",))
        self.assertEqual("exec-2", replacement.executable_spec_id)


if __name__ == "__main__":
    unittest.main()
