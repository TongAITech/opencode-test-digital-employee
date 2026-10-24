import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine

from rc8_center.defect_closure import CenterDefectClosureService, DefectReviewDecision, DefectSeverity, DefectState
from rc8_center.failure_diagnosis import CenterFailureDiagnosisService, FailureClassification
from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_defect_closure import PostgresDefectClosureRepository
from rc8_center.infrastructure.postgres_failure_diagnosis import PostgresFailureDiagnosisRepository


class PostgresDefectClosureTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        database = Path(self.tmpdir.name) / "center.db"
        self.engine = create_engine("sqlite+pysqlite:///%s" % database.as_posix(), future=True)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.store = PostgresStore(self.engine)
        self.diagnosis_repo = PostgresFailureDiagnosisRepository(self.store)
        self.diagnosis = CenterFailureDiagnosisService(self.diagnosis_repo, now_fn=lambda: 100)
        self.repo = PostgresDefectClosureRepository(self.store)
        self.service = CenterDefectClosureService(self.repo, self.diagnosis_repo, now_fn=lambda: 100)

    def test_closed_defect_survives_repository_reconstruction(self):
        self.diagnosis.observe(observation_id="obs-1", test_run_id="run-1", source_mission_node_id="run-1:scope:N7", source_attempt_id="attempt-1", source_case_id="case-1", summary="product mismatch", evidence_refs=("evidence://attempt/1",))
        diagnostic = self.diagnosis.diagnose(diagnostic_id="diag-1", observation_id="obs-1", classification=FailureClassification.PRODUCT, classifier_ref="classifier://n8", reason_code="PRODUCT_SEMANTIC_MISMATCH", evidence_refs=("evidence://diagnosis/1",))
        route = self.diagnosis.route(decision_id="route-1", diagnostic_id=diagnostic.diagnostic_id, gap_id="gap-1")
        self.service.create_candidate(defect_case_id="defect-1", route_decision_id=route.decision_id, evidence_refs=("evidence://candidate",))
        self.service.reproduce("defect-1", reproduction_attempt_id="attempt-repro", reproducer_ref="team://independent", evidence_refs=("evidence://repro",))
        self.service.qualify("defect-1", qualified=True, evidence_refs=("evidence://qualify",))
        self.service.record_rca("defect-1", rca_summary="state transition bug", evidence_refs=("evidence://rca",))
        self.service.deduplicate("defect-1", evidence_refs=("evidence://dedup",))
        self.service.assess("defect-1", severity=DefectSeverity.HIGH, impact_refs=("api://customer/update",), evidence_refs=("evidence://impact",))
        self.service.review("defect-1", decision=DefectReviewDecision.ACCEPT, evidence_refs=("evidence://review",))
        self.service.file("defect-1", external_defect_ref="defect://PFC-1001", evidence_refs=("evidence://file",))
        self.service.detect_fix("defect-1", fix_revision_ref="git://sha/fix", evidence_refs=("evidence://fix",))
        self.service.verify_fix("defect-1", passed=True, evidence_refs=("evidence://verify",))
        self.service.record_impact_regression("defect-1", passed=True, evidence_refs=("evidence://regression",))
        expected = self.service.close("defect-1", evidence_refs=("evidence://close",))

        reconstructed = PostgresDefectClosureRepository(self.store)
        loaded = reconstructed.get_defect_case("defect-1")
        self.assertEqual(expected, loaded)
        self.assertEqual(DefectState.CLOSED, loaded.state)
        self.assertTrue(loaded.disposition_complete)
        self.assertEqual("defect-1", reconstructed.by_route_decision("route-1").defect_case_id)


if __name__ == "__main__":
    unittest.main()
