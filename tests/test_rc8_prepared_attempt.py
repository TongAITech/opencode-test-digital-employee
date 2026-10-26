import unittest

from rc8_center.prepared_attempt import CenterPreparedAttemptService, MemoryPreparedAttemptRepository, PreparedAttemptError, PreparedAttemptState


class PreparedAttemptTest(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.repo = MemoryPreparedAttemptRepository()
        self.service = CenterPreparedAttemptService(self.repo, now_fn=lambda: self.now)

    def _select(self, prepared_id="prep-1", attempt_id="attempt-1"):
        return self.service.select(
            prepared_attempt_id=prepared_id,
            test_run_id="run-1",
            mission_node_id="run-1:scope:N5_TEST_DATA_PRECONDITIONS",
            case_id="case-1",
            attempt_id=attempt_id,
            reality_snapshot_id="reality:run-1:scope:v1",
            data_refs=("data://customer/001",),
        )

    def _prepare(self):
        self._select()
        self.service.verify("prep-1", evidence_refs=("evidence://data/verified",))
        self.service.reserve("prep-1", reservation_ref="reservation://customer/001", evidence_refs=("evidence://reservation/1",))
        self.service.freshness_check("prep-1", data_freshness_ref="freshness://data/1", auth_session_ref="auth://4a/fresh/1", auth_acquired_at=95, auth_expires_at=200, evidence_refs=("evidence://4a/login/1", "evidence://data/fresh/1"))
        return self.service.bind("prep-1", environment_ref="env://pfc/test", route_ref="route://network-recording/api/customer", evidence_refs=("evidence://network/route/1", "evidence://env/1"))

    def test_full_lifecycle_authorizes_only_exact_current_attempt(self):
        value = self._prepare()
        self.assertEqual(PreparedAttemptState.PREPARED, value.state)
        authorized = self.service.require_current_for_execution(prepared_attempt_id="prep-1", test_run_id="run-1", case_id="case-1", attempt_id="attempt-1")
        self.assertEqual("auth://4a/fresh/1", authorized.auth_session_ref)
        self.assertEqual("prep-1", self.service.current_for_case(test_run_id="run-1", case_id="case-1").prepared_attempt_id)
        with self.assertRaisesRegex(PreparedAttemptError, "MISMATCH"):
            self.service.require_current_for_execution(prepared_attempt_id="other", test_run_id="run-1", case_id="case-1", attempt_id="attempt-1")

    def test_bind_before_freshness_fails_closed(self):
        self._select()
        self.service.verify("prep-1", evidence_refs=("evidence://data/verified",))
        self.service.reserve("prep-1", reservation_ref="reservation://customer/001", evidence_refs=("evidence://reservation/1",))
        with self.assertRaisesRegex(PreparedAttemptError, "STATE_REQUIRED:FRESH"):
            self.service.bind("prep-1", environment_ref="env://pfc/test", route_ref="route://network/api", evidence_refs=("evidence://bind/1",))

    def test_expired_fresh_auth_cannot_enter_execution(self):
        self._prepare()
        self.now = 200
        with self.assertRaisesRegex(PreparedAttemptError, "FRESH_AUTH_EXPIRED"):
            self.service.require_current_for_execution(prepared_attempt_id="prep-1", test_run_id="run-1", case_id="case-1", attempt_id="attempt-1")

    def test_active_case_cannot_open_second_attempt(self):
        self._select()
        with self.assertRaisesRegex(PreparedAttemptError, "CURRENT_CASE_ATTEMPT_ALREADY_EXISTS"):
            self._select(prepared_id="prep-2", attempt_id="attempt-2")
        self.assertEqual("attempt-1", self.repo.current_for_case("run-1", "case-1").attempt_id)

    def test_terminal_preparation_requires_new_attempt_identity(self):
        self._select()
        self.service.quarantine("prep-1", reason="data changed while reserved", evidence_refs=("evidence://quarantine/1",))
        with self.assertRaisesRegex(PreparedAttemptError, "RETRY_REQUIRES_NEW_ATTEMPT_IDENTITY"):
            self._select(prepared_id="prep-2", attempt_id="attempt-1")
        replacement = self._select(prepared_id="prep-2", attempt_id="attempt-2")
        self.assertEqual("attempt-2", replacement.attempt_id)

    def test_release_removes_current_and_execution_is_blocked(self):
        self._prepare()
        self.service.release("prep-1", evidence_refs=("evidence://release/1",))
        self.assertIsNone(self.repo.current_for_attempt("run-1", "case-1", "attempt-1"))
        self.assertIsNone(self.repo.current_for_case("run-1", "case-1"))
        with self.assertRaisesRegex(PreparedAttemptError, "REQUIRES_CURRENT"):
            self.service.require_current_for_execution(prepared_attempt_id="prep-1", test_run_id="run-1", case_id="case-1", attempt_id="attempt-1")


if __name__ == "__main__":
    unittest.main()
