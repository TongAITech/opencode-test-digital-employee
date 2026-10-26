import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine

from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_prepared_attempt import PostgresPreparedAttemptRepository
from rc8_center.prepared_attempt import CenterPreparedAttemptService, PreparedAttemptError


class PostgresPreparedAttemptRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        database = Path(self.tmpdir.name) / "center.db"
        self.engine = create_engine("sqlite+pysqlite:///%s" % database.as_posix(), future=True)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.repo = PostgresPreparedAttemptRepository(PostgresStore(self.engine))
        self.now = 100
        self.service = CenterPreparedAttemptService(self.repo, now_fn=lambda: self.now)

    def _prepare(self):
        self.service.select(prepared_attempt_id="prep-1", test_run_id="run-1", mission_node_id="run-1:scope:N5_TEST_DATA_PRECONDITIONS", case_id="case-1", attempt_id="attempt-1", reality_snapshot_id="reality:run-1:scope:v1", data_refs=("data://customer/001",))
        self.service.verify("prep-1", evidence_refs=("evidence://verify/1",))
        self.service.reserve("prep-1", reservation_ref="reservation://customer/001", evidence_refs=("evidence://reserve/1",))
        self.service.freshness_check("prep-1", data_freshness_ref="freshness://data/1", auth_session_ref="auth://4a/fresh/1", auth_acquired_at=90, auth_expires_at=200, evidence_refs=("evidence://fresh/1",))
        return self.service.bind("prep-1", environment_ref="env://pfc/test", route_ref="route://browser-network/customer", evidence_refs=("evidence://bind/1",))

    def test_prepared_attempt_survives_repository_reconstruction(self):
        expected = self._prepare()
        reconstructed = PostgresPreparedAttemptRepository(self.repo.store)
        loaded = reconstructed.get_prepared_attempt("prep-1")
        self.assertEqual(expected, loaded)
        current = reconstructed.current_for_attempt("run-1", "case-1", "attempt-1")
        self.assertEqual("prep-1", current.prepared_attempt_id)

    def test_terminal_preparation_requires_new_attempt_identity(self):
        self._prepare()
        self.service.quarantine(
            "prep-1",
            reason="AUTH_BINDING_CHANGED",
            evidence_refs=("evidence://mutation/auth-2",),
        )
        with self.assertRaisesRegex(PreparedAttemptError, "RETRY_REQUIRES_NEW_ATTEMPT_IDENTITY"):
            self.service.select(prepared_attempt_id="prep-2", test_run_id="run-1", mission_node_id="run-1:scope:N5_TEST_DATA_PRECONDITIONS", case_id="case-1", attempt_id="attempt-1", reality_snapshot_id="reality:run-1:scope:v2", data_refs=("data://customer/002",))

        second = self.service.select(prepared_attempt_id="prep-2", test_run_id="run-1", mission_node_id="run-1:scope:N5_TEST_DATA_PRECONDITIONS", case_id="case-1", attempt_id="attempt-2", reality_snapshot_id="reality:run-1:scope:v2", data_refs=("data://customer/002",))
        self.assertEqual("prep-2", second.prepared_attempt_id)
        self.assertEqual("attempt-2", second.attempt_id)

    def test_repository_rejects_competing_current_preparation(self):
        self.service.select(prepared_attempt_id="prep-1", test_run_id="run-1", mission_node_id="run-1:scope:N5_TEST_DATA_PRECONDITIONS", case_id="case-1", attempt_id="attempt-1", reality_snapshot_id="reality:run-1:scope:v1", data_refs=("data://customer/001",))
        with self.assertRaisesRegex(PreparedAttemptError, "CURRENT_PREPARED_ATTEMPT_ALREADY_EXISTS"):
            self.service.select(prepared_attempt_id="prep-2", test_run_id="run-1", mission_node_id="run-1:scope:N5_TEST_DATA_PRECONDITIONS", case_id="case-1", attempt_id="attempt-1", reality_snapshot_id="reality:run-1:scope:v1", data_refs=("data://customer/002",))


if __name__ == "__main__":
    unittest.main()
