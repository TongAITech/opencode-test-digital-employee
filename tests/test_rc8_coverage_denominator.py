import unittest

from rc8_center.coverage_denominator import CenterCoverageDenominatorService, CoverageDenominatorError, CoverageObligation, CoverageObligationState, MemoryCoverageDenominatorRepository


class CoverageDenominatorTest(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.repo = MemoryCoverageDenominatorRepository()
        self.service = CenterCoverageDenominatorService(self.repo, now_fn=lambda: self.now)

    def _obligation(self, obligation_id):
        return CoverageObligation(obligation_id=obligation_id, layer="L3", subject_ref="api://%s" % obligation_id, source_refs=("trace://%s" % obligation_id,))

    def test_zero_denominator_is_forbidden(self):
        with self.assertRaisesRegex(CoverageDenominatorError, "ZERO_FORBIDDEN"):
            self.service.freeze(snapshot_id="cov-1", test_run_id="run-1", mission_node_id="run-1:scope:N7", layer="L3", source_revision="sha-1", obligations=())

    def test_covered_fail_counts_as_tested_and_does_not_block_coverage_closure(self):
        snapshot = self.service.freeze(snapshot_id="cov-1", test_run_id="run-1", mission_node_id="run-1:scope:N7", layer="L3", source_revision="sha-1", obligations=(self._obligation("api-1"), self._obligation("api-2")))
        self.service.record(receipt_id="r1", snapshot_id=snapshot.snapshot_id, obligation_id="api-1", state=CoverageObligationState.COVERED_PASS, attempt_id="a1", case_id="c1", evidence_refs=("evidence://api-1",))
        self.service.record(receipt_id="r2", snapshot_id=snapshot.snapshot_id, obligation_id="api-2", state=CoverageObligationState.COVERED_FAIL, attempt_id="a2", case_id="c2", evidence_refs=("evidence://api-2",))
        closure = self.service.closure(snapshot.snapshot_id)
        self.assertTrue(closure.complete)
        self.assertEqual(1, closure.covered_pass)
        self.assertEqual(1, closure.covered_fail)

    def test_blocked_obligation_prevents_closure(self):
        snapshot = self.service.freeze(snapshot_id="cov-1", test_run_id="run-1", mission_node_id="run-1:scope:N7", layer="L3", source_revision="sha-1", obligations=(self._obligation("api-1"),))
        self.service.record(receipt_id="r1", snapshot_id=snapshot.snapshot_id, obligation_id="api-1", state=CoverageObligationState.BLOCKED, evidence_refs=("evidence://blocked",))
        closure = self.service.closure(snapshot.snapshot_id)
        self.assertFalse(closure.complete)
        self.assertEqual(1, closure.blocked)

    def test_excluded_obligation_requires_evidence_and_can_close(self):
        snapshot = self.service.freeze(snapshot_id="cov-1", test_run_id="run-1", mission_node_id="run-1:scope:N7", layer="L3", source_revision="sha-1", obligations=(self._obligation("api-1"),))
        self.service.record(receipt_id="r1", snapshot_id=snapshot.snapshot_id, obligation_id="api-1", state=CoverageObligationState.EXCLUDED_WITH_EVIDENCE, evidence_refs=("evidence://na/1",))
        self.assertTrue(self.service.closure(snapshot.snapshot_id).complete)

    def test_expansion_invalidates_old_100_percent_and_reopens_layer(self):
        first = self.service.freeze(snapshot_id="cov-v1", test_run_id="run-1", mission_node_id="run-1:scope:N7", layer="L3", source_revision="sha-1", obligations=(self._obligation("api-1"),))
        self.service.record(receipt_id="r1", snapshot_id=first.snapshot_id, obligation_id="api-1", state=CoverageObligationState.COVERED_PASS, attempt_id="a1", case_id="c1", evidence_refs=("evidence://api-1",))
        self.assertTrue(self.service.closure(first.snapshot_id).complete)
        second, reopen = self.service.expand(new_snapshot_id="cov-v2", previous_snapshot_id=first.snapshot_id, added_obligations=(self._obligation("api-2"),), reopen_id="reopen-1", evidence_refs=("evidence://new-risk",))
        self.assertEqual(2, second.version)
        self.assertEqual(("r1",), reopen.invalidated_receipt_ids)
        with self.assertRaisesRegex(CoverageDenominatorError, "STALE_COVERAGE_DENOMINATOR"):
            self.service.closure(first.snapshot_id)
        current = self.service.closure(second.snapshot_id)
        self.assertFalse(current.complete)
        self.assertEqual(2, current.unresolved)


if __name__ == "__main__":
    unittest.main()
