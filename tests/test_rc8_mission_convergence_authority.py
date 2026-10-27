import unittest

from rc8_center.mission_convergence import (
    CenterMissionConvergenceService,
    CoverageTruth,
    MemoryMissionConvergenceRepository,
    MissionConvergenceError,
    MissionConvergenceTruth,
    MissionNodeTruth,
    ProductQualityAssessment,
    ReleaseRecommendation,
    TestSufficiencyDecision,
)
from rc8_center.mission_convergence_authority import CenterMissionConvergenceAuthority
from rc8_runtime.mission_nodes import MISSION_NODE_SEQUENCE, MissionNodeState


class _StaticTruthSource:
    def __init__(self, truth):
        self.truth = truth
        self.calls = []

    def capture(self, test_run_id):
        self.calls.append(test_run_id)
        return self.truth


class MissionConvergenceAuthorityTest(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.repo = MemoryMissionConvergenceRepository()
        self.service = CenterMissionConvergenceService(self.repo, now_fn=lambda: self.now)

    def _nodes(self):
        return tuple(
            MissionNodeTruth(
                node_type=node_type,
                state=MissionNodeState.PASS,
                evidence_refs=("evidence://node/%s" % node_type.value,),
            )
            for node_type in MISSION_NODE_SEQUENCE[:-1]
        )

    def _coverage(self):
        return tuple(
            CoverageTruth(
                layer="L%s" % index,
                snapshot_id="coverage://L%s/v1" % index,
                complete=True,
                blocked=0,
                covered_fail=0,
                evidence_refs=("evidence://coverage/L%s" % index,),
            )
            for index in range(1, 8)
        )

    def _truth(self, *, test_run_id="run-1", snapshot_id="truth://run-1/v1"):
        return MissionConvergenceTruth(
            truth_snapshot_id=snapshot_id,
            test_run_id=test_run_id,
            mission_nodes=self._nodes(),
            coverage=self._coverage(),
            truth_refs=("r1://%s" % test_run_id, "postgres://%s" % test_run_id),
            captured_at=self.now,
        )

    def test_authority_acquires_truth_by_test_run_identity(self):
        source = _StaticTruthSource(self._truth())
        authority = CenterMissionConvergenceAuthority(self.service, source)

        decision = authority.evaluate_test_run(decision_id="conv-auth-1", test_run_id="run-1")

        self.assertEqual(["run-1"], source.calls)
        self.assertEqual(TestSufficiencyDecision.SUFFICIENT, decision.test_sufficiency)
        self.assertEqual(ProductQualityAssessment.PASS, decision.product_quality)
        self.assertEqual(ReleaseRecommendation.GO, decision.release_recommendation)
        self.assertTrue(decision.mission_converged)

    def test_authority_rejects_truth_for_another_test_run(self):
        source = _StaticTruthSource(self._truth(test_run_id="run-other", snapshot_id="truth://run-other/v1"))
        authority = CenterMissionConvergenceAuthority(self.service, source)

        with self.assertRaisesRegex(MissionConvergenceError, "CENTER_CONVERGENCE_TRUTH_TEST_RUN_MISMATCH"):
            authority.evaluate_test_run(decision_id="conv-auth-1", test_run_id="run-1")

    def test_authority_rejects_invalid_truth_source_result(self):
        source = _StaticTruthSource(object())
        authority = CenterMissionConvergenceAuthority(self.service, source)

        with self.assertRaisesRegex(MissionConvergenceError, "CENTER_CONVERGENCE_TRUTH_SOURCE_INVALID"):
            authority.evaluate_test_run(decision_id="conv-auth-1", test_run_id="run-1")

    def test_authority_has_no_caller_authored_truth_parameter(self):
        source = _StaticTruthSource(self._truth())
        authority = CenterMissionConvergenceAuthority(self.service, source)

        with self.assertRaises(TypeError):
            authority.evaluate_test_run(
                decision_id="conv-auth-1",
                test_run_id="run-1",
                truth=self._truth(),
            )
        self.assertEqual([], source.calls)

    def test_report_release_still_requires_persisted_converged_center_decision(self):
        source = _StaticTruthSource(self._truth())
        authority = CenterMissionConvergenceAuthority(self.service, source)

        with self.assertRaisesRegex(MissionConvergenceError, "REPORT_RELEASE_REQUIRES_CONVERGENCE_DECISION"):
            authority.authorize_report_release(
                authorization_id="report-auth-1",
                decision_id="missing",
                report_id="report-1",
            )

        authority.evaluate_test_run(decision_id="conv-auth-1", test_run_id="run-1")
        authorization = authority.authorize_report_release(
            authorization_id="report-auth-1",
            decision_id="conv-auth-1",
            report_id="report-1",
        )
        self.assertEqual("report-1", authorization.report_id)


if __name__ == "__main__":
    unittest.main()
