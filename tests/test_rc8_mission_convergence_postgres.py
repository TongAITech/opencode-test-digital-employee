import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine

from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_mission_convergence import PostgresMissionConvergenceRepository, ReportReleaseAuthorizationRow
from rc8_center.mission_convergence import (
    CenterMissionConvergenceService,
    CoverageTruth,
    MissionConvergenceTruth,
    MissionNodeTruth,
)
from rc8_runtime.mission_nodes import MISSION_NODE_SEQUENCE, MissionNodeState


class PostgresMissionConvergenceTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        database = Path(self.tmpdir.name) / "center.db"
        self.engine = create_engine("sqlite+pysqlite:///%s" % database.as_posix(), future=True)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.store = PostgresStore(self.engine)
        self.repo = PostgresMissionConvergenceRepository(self.store)
        self.service = CenterMissionConvergenceService(self.repo, now_fn=lambda: 100)

    @staticmethod
    def _truth():
        nodes = tuple(
            MissionNodeTruth(
                node_type=node_type,
                state=MissionNodeState.PASS,
                evidence_refs=("evidence://node/%s" % node_type.value,),
            )
            for node_type in MISSION_NODE_SEQUENCE[:-1]
        )
        coverage = tuple(
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
        return MissionConvergenceTruth(
            truth_snapshot_id="truth://run-1/v1",
            test_run_id="run-1",
            mission_nodes=nodes,
            coverage=coverage,
            truth_refs=("r1://run-1", "postgres://run-1"),
            captured_at=100,
        )

    def test_decision_and_report_authorization_survive_repository_reconstruction(self):
        expected = self.service.evaluate(decision_id="conv-1", truth=self._truth())
        authorization = self.service.authorize_report_release(
            authorization_id="report-auth-1",
            decision_id="conv-1",
            report_id="report-1",
        )
        reconstructed = PostgresMissionConvergenceRepository(self.store)
        self.assertEqual(expected, reconstructed.get_decision("conv-1"))
        with self.store.session() as session:
            row = session.get(ReportReleaseAuthorizationRow, "report-auth-1")
            self.assertIsNotNone(row)
            self.assertEqual(authorization.report_id, row.report_id)
            self.assertEqual(authorization.decision_id, row.decision_id)


if __name__ == "__main__":
    unittest.main()
