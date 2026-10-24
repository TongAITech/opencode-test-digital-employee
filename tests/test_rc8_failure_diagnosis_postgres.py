import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine

from rc8_center.failure_diagnosis import CenterFailureDiagnosisService, FailureClassification, RepairResult
from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_failure_diagnosis import PostgresFailureDiagnosisRepository
from rc8_runtime.mission_nodes import MissionNodeType


class PostgresFailureDiagnosisTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        database = Path(self.tmpdir.name) / "center.db"
        self.engine = create_engine("sqlite+pysqlite:///%s" % database.as_posix(), future=True)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.repo = PostgresFailureDiagnosisRepository(PostgresStore(self.engine))
        self.service = CenterFailureDiagnosisService(self.repo, now_fn=lambda: 100)

    def test_diagnosis_route_repair_and_successor_survive_repository_reconstruction(self):
        observation = self.service.observe(
            observation_id="obs-1",
            test_run_id="run-1",
            source_mission_node_id="run-1:scope:N7",
            source_attempt_id="attempt-1",
            source_case_id="case-1",
            summary="auth expired",
            evidence_refs=("evidence://attempt/1",),
        )
        diagnostic = self.service.diagnose(
            diagnostic_id="diag-1",
            observation_id=observation.observation_id,
            classification=FailureClassification.AUTH,
            classifier_ref="classifier://n8",
            reason_code="AUTH_EXPIRED",
            evidence_refs=("evidence://auth/expired",),
        )
        route = self.service.route(decision_id="route-1", diagnostic_id=diagnostic.diagnostic_id, gap_id="gap-1")
        self.assertEqual(MissionNodeType.N5_TEST_DATA_PRECONDITIONS, route.target_mission_node)
        order = self.service.create_repair_work_order(work_order_id="wo-1", route_decision_id=route.decision_id, evidence_refs=("evidence://fresh-login/request",))
        receipt = self.service.record_repair_receipt(receipt_id="rr-1", work_order_id=order.work_order_id, result=RepairResult.REPAIRED, evidence_refs=("evidence://fresh-login/2",))
        successor = self.service.authorize_successor_attempt(successor_id="succ-1", work_order_id=order.work_order_id, repair_receipt_id=receipt.receipt_id, successor_attempt_id="attempt-2")

        reconstructed = PostgresFailureDiagnosisRepository(self.repo.store)
        self.assertEqual(observation, reconstructed.get_observation("obs-1"))
        self.assertEqual(diagnostic, reconstructed.get_diagnostic("diag-1"))
        self.assertEqual(route, reconstructed.get_route("route-1"))
        self.assertEqual(order, reconstructed.get_work_order("wo-1"))
        self.assertEqual(receipt, reconstructed.get_repair_receipt("rr-1"))
        with reconstructed.store.session() as session:
            from rc8_center.infrastructure.postgres_failure_diagnosis import SuccessorAttemptRow
            row = session.get(SuccessorAttemptRow, "succ-1")
            self.assertIsNotNone(row)
            self.assertEqual(successor.successor_attempt_id, row.successor_attempt_id)


if __name__ == "__main__":
    unittest.main()
