import unittest

from rc8_center.runtime_attempt_authority import (
    RuntimeAttemptAuthority,
    RuntimeAttemptAuthorityError,
    RuntimeAttemptAuthoritySnapshot,
    RuntimeEvidenceAuthorityContext,
)


class RuntimeAttemptAuthorityTest(unittest.TestCase):
    def current(self, **overrides):
        values = dict(
            work_item_id="work-1",
            attempt_id="attempt-2",
            producer_node_id="node-b",
            attempt_started_at=200,
            lease_owner_node_id="node-b",
            lease_expires_at=400,
            superseded=False,
        )
        values.update(overrides)
        return RuntimeAttemptAuthoritySnapshot(**values)

    def evidence(self, **overrides):
        values = dict(
            work_item_id="work-1",
            attempt_id="attempt-2",
            producer_node_id="node-b",
            observed_at=250,
        )
        values.update(overrides)
        return RuntimeEvidenceAuthorityContext(**values)

    def test_current_attempt_current_lease_is_authorized(self):
        RuntimeAttemptAuthority.authorize(current=self.current(), evidence=self.evidence(), now=260)

    def test_superseded_attempt_is_rejected(self):
        with self.assertRaisesRegex(RuntimeAttemptAuthorityError, "ATTEMPT_SUPERSEDED"):
            RuntimeAttemptAuthority.authorize(current=self.current(superseded=True), evidence=self.evidence())

    def test_old_attempt_evidence_cannot_verify_new_attempt(self):
        with self.assertRaisesRegex(RuntimeAttemptAuthorityError, "STALE_ATTEMPT_EVIDENCE_REJECTED"):
            RuntimeAttemptAuthority.authorize(current=self.current(), evidence=self.evidence(attempt_id="attempt-1"))

    def test_failover_rejects_old_producer_node(self):
        with self.assertRaisesRegex(RuntimeAttemptAuthorityError, "ATTEMPT_PRODUCER_MISMATCH"):
            RuntimeAttemptAuthority.authorize(current=self.current(), evidence=self.evidence(producer_node_id="node-a"))

    def test_evidence_before_attempt_start_is_rejected(self):
        with self.assertRaisesRegex(RuntimeAttemptAuthorityError, "EVIDENCE_PREDATES_ATTEMPT"):
            RuntimeAttemptAuthority.authorize(current=self.current(), evidence=self.evidence(observed_at=199))

    def test_evidence_after_lease_expiry_is_rejected(self):
        with self.assertRaisesRegex(RuntimeAttemptAuthorityError, "EVIDENCE_AFTER_LEASE_EXPIRY"):
            RuntimeAttemptAuthority.authorize(current=self.current(), evidence=self.evidence(observed_at=401))

    def test_expired_lease_rejects_delayed_ingestion(self):
        with self.assertRaisesRegex(RuntimeAttemptAuthorityError, "LEASE_EXPIRED"):
            RuntimeAttemptAuthority.authorize(current=self.current(), evidence=self.evidence(observed_at=300), now=401)

    def test_worker_cannot_future_date_evidence_inside_lease_window(self):
        with self.assertRaisesRegex(RuntimeAttemptAuthorityError, "EVIDENCE_FROM_FUTURE"):
            RuntimeAttemptAuthority.authorize(current=self.current(), evidence=self.evidence(observed_at=350), now=300)

    def test_center_clock_before_attempt_start_fails_closed(self):
        with self.assertRaisesRegex(RuntimeAttemptAuthorityError, "ATTEMPT_NOT_STARTED"):
            RuntimeAttemptAuthority.authorize(current=self.current(), evidence=self.evidence(observed_at=200), now=199)


if __name__ == "__main__":
    unittest.main()
