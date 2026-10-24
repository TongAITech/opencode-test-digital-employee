import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine

from rc8_center.executable_readiness import CenterExecutableReadinessService
from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_executable_readiness import PostgresExecutableSpecRepository
from rc8_center.prepared_attempt import CenterPreparedAttemptService, MemoryPreparedAttemptRepository


class PostgresExecutableReadinessTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        database = Path(self.tmpdir.name) / "center.db"
        self.engine = create_engine("sqlite+pysqlite:///%s" % database.as_posix(), future=True)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.repo = PostgresExecutableSpecRepository(PostgresStore(self.engine))
        self.now = 100
        self.prep = CenterPreparedAttemptService(MemoryPreparedAttemptRepository(), now_fn=lambda: self.now)
        self.prep.select(prepared_attempt_id="prep-1", test_run_id="run-1", mission_node_id="run-1:scope:N5_TEST_DATA_PRECONDITIONS", case_id="case-1", attempt_id="attempt-1", reality_snapshot_id="reality:run-1:scope:v1", data_refs=("data://customer/001",))
        self.prep.verify("prep-1", evidence_refs=("evidence://verify/1",))
        self.prep.reserve("prep-1", reservation_ref="reservation://customer/001", evidence_refs=("evidence://reserve/1",))
        self.prep.freshness_check("prep-1", data_freshness_ref="freshness://data/1", auth_session_ref="auth://4a/fresh/1", auth_acquired_at=90, auth_expires_at=200, evidence_refs=("evidence://fresh/1",))
        self.prep.bind("prep-1", environment_ref="env://pfc/test", route_ref="route://browser-network/customer", evidence_refs=("evidence://bind/1",))
        self.service = CenterExecutableReadinessService(self.repo, self.prep, now_fn=lambda: self.now)

    def test_ready_spec_survives_repository_reconstruction(self):
        self.service.build(executable_spec_id="exec-1", test_run_id="run-1", mission_node_id="run-1:scope:N6_SCRIPT_BUILD_READINESS", case_id="case-1", attempt_id="attempt-1", prepared_attempt_id="prep-1", frozen_case_ref="case://case-1@v3", driver_ref="driver://pytest", script_artifact_ref="artifact://script/case-1.py", fixture_binding_refs=("fixture://customer",), assertion_refs=("assertion://status",), evidence_collector_refs=("collector://response",), build_evidence_refs=("evidence://compile/1",))
        self.service.verify("exec-1", semantic_evidence_refs=("evidence://semantic/1",))
        expected = self.service.mark_ready("exec-1")
        reconstructed = PostgresExecutableSpecRepository(self.repo.store)
        self.assertEqual(expected, reconstructed.get_executable_spec("exec-1"))
        self.assertEqual("exec-1", reconstructed.current_for_attempt("run-1", "case-1", "attempt-1").executable_spec_id)


if __name__ == "__main__":
    unittest.main()
