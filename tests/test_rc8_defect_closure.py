import unittest

from rc8_center.defect_closure import (
    CenterDefectClosureService,
    DefectClosureError,
    DefectReviewDecision,
    DefectSeverity,
    DefectState,
    MemoryDefectClosureRepository,
)
from rc8_center.failure_diagnosis import CenterFailureDiagnosisService, FailureClassification, MemoryFailureDiagnosisRepository


class DefectClosureTest(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.diagnosis_repo = MemoryFailureDiagnosisRepository()
        self.diagnosis = CenterFailureDiagnosisService(self.diagnosis_repo, now_fn=lambda: self.now)
        self.repo = MemoryDefectClosureRepository()
        self.service = CenterDefectClosureService(self.repo, self.diagnosis_repo, now_fn=lambda: self.now)

    def _route(self, classification=FailureClassification.PRODUCT, suffix="1"):
        self.diagnosis.observe(
            observation_id="obs-%s" % suffix,
            test_run_id="run-1",
            source_mission_node_id="run-1:scope:N7",
            source_attempt_id="attempt-%s" % suffix,
            source_case_id="case-%s" % suffix,
            summary="failure-%s" % suffix,
            evidence_refs=("evidence://attempt/%s" % suffix,),
        )
        diagnostic = self.diagnosis.diagnose(
            diagnostic_id="diag-%s" % suffix,
            observation_id="obs-%s" % suffix,
            classification=classification,
            classifier_ref="classifier://n8",
            reason_code=classification.value,
            evidence_refs=("evidence://diagnosis/%s" % suffix,),
        )
        return self.diagnosis.route(decision_id="route-%s" % suffix, diagnostic_id=diagnostic.diagnostic_id, gap_id="gap-%s" % suffix)

    def test_non_product_failure_cannot_create_defect_candidate(self):
        route = self._route(FailureClassification.SCRIPT)
        with self.assertRaisesRegex(DefectClosureError, "N9_REQUIRES_PRODUCT_ROUTE"):
            self.service.create_candidate(defect_case_id="defect-1", route_decision_id=route.decision_id, evidence_refs=("evidence://candidate",))

    def test_independent_reproduction_requires_new_attempt(self):
        route = self._route()
        self.service.create_candidate(defect_case_id="defect-1", route_decision_id=route.decision_id, evidence_refs=("evidence://candidate",))
        with self.assertRaisesRegex(DefectClosureError, "INDEPENDENT_REPRODUCTION_REQUIRES_NEW_ATTEMPT"):
            self.service.reproduce("defect-1", reproduction_attempt_id="attempt-1", reproducer_ref="team://defect-review", evidence_refs=("evidence://repro",))

    def test_full_defect_lifecycle_closes_only_after_fix_and_impact_regression(self):
        route = self._route()
        candidate = self.service.create_candidate(defect_case_id="defect-1", route_decision_id=route.decision_id, evidence_refs=("evidence://candidate",))
        self.assertEqual(DefectState.CANDIDATE, candidate.state)
        self.service.reproduce("defect-1", reproduction_attempt_id="attempt-repro-2", reproducer_ref="team://independent-reproducer", evidence_refs=("evidence://repro/2",))
        self.service.qualify("defect-1", qualified=True, evidence_refs=("evidence://qualification",))
        self.service.record_rca("defect-1", rca_summary="service rejects valid state transition", evidence_refs=("evidence://rca",))
        self.service.deduplicate("defect-1", evidence_refs=("evidence://dedup",))
        self.service.assess("defect-1", severity=DefectSeverity.HIGH, impact_refs=("requirement://STBB19-320", "api://customer/update"), evidence_refs=("evidence://impact",))
        self.service.review("defect-1", decision=DefectReviewDecision.ACCEPT, evidence_refs=("evidence://review",))
        self.service.file("defect-1", external_defect_ref="defect://PFC-1001", evidence_refs=("evidence://file",))
        self.service.detect_fix("defect-1", fix_revision_ref="git://sha/fix1", evidence_refs=("evidence://fix-detected",))
        self.service.verify_fix("defect-1", passed=True, evidence_refs=("evidence://fix-verify",))
        self.service.record_impact_regression("defect-1", passed=True, evidence_refs=("evidence://impact-regression",))
        closed = self.service.close("defect-1", evidence_refs=("evidence://close",))
        self.assertEqual(DefectState.CLOSED, closed.state)
        self.assertTrue(closed.disposition_complete)

    def test_failed_fix_verification_reopens_instead_of_closing(self):
        route = self._route()
        self.service.create_candidate(defect_case_id="defect-1", route_decision_id=route.decision_id, evidence_refs=("evidence://candidate",))
        self.service.reproduce("defect-1", reproduction_attempt_id="attempt-repro-2", reproducer_ref="team://reproducer", evidence_refs=("evidence://repro",))
        self.service.qualify("defect-1", qualified=True, evidence_refs=("evidence://qualification",))
        self.service.record_rca("defect-1", rca_summary="bad branch", evidence_refs=("evidence://rca",))
        self.service.deduplicate("defect-1", evidence_refs=("evidence://dedup",))
        self.service.assess("defect-1", severity=DefectSeverity.MEDIUM, impact_refs=("api://x",), evidence_refs=("evidence://impact",))
        self.service.review("defect-1", decision=DefectReviewDecision.ACCEPT, evidence_refs=("evidence://review",))
        self.service.file("defect-1", external_defect_ref="defect://PFC-1002", evidence_refs=("evidence://file",))
        self.service.detect_fix("defect-1", fix_revision_ref="git://sha/fix2", evidence_refs=("evidence://fix",))
        reopened = self.service.verify_fix("defect-1", passed=False, evidence_refs=("evidence://still-fails",))
        self.assertEqual(DefectState.REOPENED, reopened.state)
        self.assertFalse(reopened.disposition_complete)

    def test_duplicate_and_not_defect_are_evidence_backed_dispositions(self):
        route = self._route(suffix="1")
        self.service.create_candidate(defect_case_id="defect-1", route_decision_id=route.decision_id, evidence_refs=("evidence://candidate",))
        self.service.reproduce("defect-1", reproduction_attempt_id="attempt-repro-1", reproducer_ref="team://reproducer", evidence_refs=("evidence://repro",))
        self.service.qualify("defect-1", qualified=True, evidence_refs=("evidence://qualification",))
        self.service.record_rca("defect-1", rca_summary="same known issue", evidence_refs=("evidence://rca",))
        duplicate = self.service.deduplicate("defect-1", duplicate_of="defect://PFC-900", evidence_refs=("evidence://dedup",))
        self.assertEqual(DefectState.DUPLICATE_LINKED, duplicate.state)
        self.assertTrue(duplicate.disposition_complete)

        route2 = self._route(suffix="2")
        self.service.create_candidate(defect_case_id="defect-2", route_decision_id=route2.decision_id, evidence_refs=("evidence://candidate/2",))
        self.service.reproduce("defect-2", reproduction_attempt_id="attempt-repro-2", reproducer_ref="team://reproducer", evidence_refs=("evidence://repro/2",))
        not_defect = self.service.qualify("defect-2", qualified=False, evidence_refs=("evidence://not-defect",))
        self.assertEqual(DefectState.NOT_DEFECT, not_defect.state)
        self.assertTrue(not_defect.disposition_complete)


if __name__ == "__main__":
    unittest.main()
