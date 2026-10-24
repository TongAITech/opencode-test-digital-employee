import unittest

from rc8_center.defect_closure import DefectSeverity, DefectState
from rc8_center.mission_convergence import (
    CenterMissionConvergenceService,
    CoverageTruth,
    DefectTruth,
    MemoryMissionConvergenceRepository,
    MissionConvergenceError,
    MissionConvergenceTruth,
    MissionNodeTruth,
    ProductQualityAssessment,
    ReleaseRecommendation,
    ResidualRisk,
    ResidualRiskLevel,
    TestSufficiencyDecision,
)
from rc8_runtime.mission_nodes import MISSION_NODE_SEQUENCE, MissionNodeState


class MissionConvergenceTest(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.repo = MemoryMissionConvergenceRepository()
        self.service = CenterMissionConvergenceService(self.repo, now_fn=lambda: self.now)

    def _nodes(self, override=None):
        override = override or {}
        return tuple(
            MissionNodeTruth(
                node_type=node_type,
                state=override.get(node_type, MissionNodeState.PASS),
                evidence_refs=("evidence://node/%s" % node_type.value,),
            )
            for node_type in MISSION_NODE_SEQUENCE[:-1]
        )

    def _coverage(self, complete=True, blocked=0, covered_fail=0):
        return tuple(
            CoverageTruth(
                layer="L%s" % index,
                snapshot_id="coverage://L%s/v1" % index,
                complete=complete,
                blocked=blocked if index == 3 else 0,
                covered_fail=covered_fail if index == 3 else 0,
                evidence_refs=("evidence://coverage/L%s" % index,),
            )
            for index in range(1, 8)
        )

    def _truth(self, **kwargs):
        values = {
            "truth_snapshot_id": "truth://run-1/v1",
            "test_run_id": "run-1",
            "mission_nodes": self._nodes(),
            "coverage": self._coverage(),
            "truth_refs": ("r1://run-1", "postgres://run-1"),
            "captured_at": self.now,
        }
        values.update(kwargs)
        return MissionConvergenceTruth(**values)

    def test_clean_mission_is_sufficient_quality_pass_and_go(self):
        decision = self.service.evaluate(decision_id="conv-1", truth=self._truth())
        self.assertEqual(TestSufficiencyDecision.SUFFICIENT, decision.test_sufficiency)
        self.assertEqual(ProductQualityAssessment.PASS, decision.product_quality)
        self.assertEqual(ReleaseRecommendation.GO, decision.release_recommendation)
        self.assertTrue(decision.mission_converged)
        authorization = self.service.authorize_report_release(authorization_id="report-auth-1", decision_id="conv-1", report_id="report-1")
        self.assertEqual("report-1", authorization.report_id)

    def test_high_open_product_defect_can_be_test_sufficient_but_no_go(self):
        defect = DefectTruth(
            defect_case_id="defect-1",
            state=DefectState.FILED,
            severity=DefectSeverity.HIGH,
            evidence_refs=("evidence://defect/1",),
        )
        decision = self.service.evaluate(decision_id="conv-1", truth=self._truth(defects=(defect,), coverage=self._coverage(covered_fail=1)))
        self.assertEqual(TestSufficiencyDecision.SUFFICIENT, decision.test_sufficiency)
        self.assertEqual(ProductQualityAssessment.FAIL, decision.product_quality)
        self.assertEqual(ReleaseRecommendation.NO_GO, decision.release_recommendation)
        self.assertTrue(decision.mission_converged)

    def test_covered_fail_is_tested_but_degrades_product_quality(self):
        decision = self.service.evaluate(decision_id="conv-1", truth=self._truth(coverage=self._coverage(covered_fail=1)))
        self.assertEqual(TestSufficiencyDecision.SUFFICIENT, decision.test_sufficiency)
        self.assertEqual(ProductQualityAssessment.DEGRADED, decision.product_quality)
        self.assertEqual(ReleaseRecommendation.HOLD, decision.release_recommendation)
        self.assertTrue(decision.mission_converged)

    def test_incomplete_coverage_does_not_converge_and_report_is_forbidden(self):
        decision = self.service.evaluate(decision_id="conv-1", truth=self._truth(coverage=self._coverage(complete=False)))
        self.assertEqual(TestSufficiencyDecision.INSUFFICIENT, decision.test_sufficiency)
        self.assertEqual(ProductQualityAssessment.UNKNOWN, decision.product_quality)
        self.assertEqual(ReleaseRecommendation.HOLD, decision.release_recommendation)
        self.assertFalse(decision.mission_converged)
        with self.assertRaisesRegex(MissionConvergenceError, "REPORT_RELEASE_REQUIRES_MISSION_CONVERGED"):
            self.service.authorize_report_release(authorization_id="report-auth-1", decision_id="conv-1", report_id="report-1")

    def test_blocked_coverage_is_blocked_not_fake_sufficient(self):
        decision = self.service.evaluate(decision_id="conv-1", truth=self._truth(coverage=self._coverage(complete=False, blocked=1)))
        self.assertEqual(TestSufficiencyDecision.BLOCKED, decision.test_sufficiency)
        self.assertFalse(decision.mission_converged)

    def test_unknown_defect_disposition_prevents_sufficiency(self):
        defect = DefectTruth(
            defect_case_id="defect-1",
            state=DefectState.CANDIDATE,
            severity=None,
            evidence_refs=("evidence://candidate/1",),
        )
        decision = self.service.evaluate(decision_id="conv-1", truth=self._truth(defects=(defect,)))
        self.assertEqual(TestSufficiencyDecision.INSUFFICIENT, decision.test_sufficiency)
        self.assertIn("DEFECT_DISPOSITION_UNKNOWN", decision.reason_codes)
        self.assertFalse(decision.mission_converged)

    def test_unaccepted_high_residual_risk_holds_release_without_erasing_test_sufficiency(self):
        risk = ResidualRisk(
            risk_id="risk-1",
            level=ResidualRiskLevel.HIGH,
            accepted=False,
            evidence_refs=("evidence://risk/1",),
        )
        decision = self.service.evaluate(decision_id="conv-1", truth=self._truth(residual_risks=(risk,)))
        self.assertEqual(TestSufficiencyDecision.SUFFICIENT, decision.test_sufficiency)
        self.assertEqual(ProductQualityAssessment.PASS, decision.product_quality)
        self.assertEqual(ReleaseRecommendation.HOLD, decision.release_recommendation)
        self.assertTrue(decision.mission_converged)

    def test_exact_n1_n9_truth_is_required(self):
        with self.assertRaisesRegex(MissionConvergenceError, "EXACT_N1_N9"):
            self._truth(mission_nodes=self._nodes()[:-1])

    def test_active_gap_and_unknown_failure_each_prevent_convergence(self):
        gap = self.service.evaluate(decision_id="conv-gap", truth=self._truth(active_blocking_gap_ids=("gap-1",)))
        self.assertEqual(TestSufficiencyDecision.INSUFFICIENT, gap.test_sufficiency)
        unknown = self.service.evaluate(decision_id="conv-unknown", truth=self._truth(truth_snapshot_id="truth://run-1/v2", unresolved_unknown_failure_ids=("failure-1",)))
        self.assertEqual(TestSufficiencyDecision.INSUFFICIENT, unknown.test_sufficiency)


if __name__ == "__main__":
    unittest.main()
