import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine

from rc8_center.coverage_denominator import CenterCoverageDenominatorService, CoverageObligation, CoverageObligationState
from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_coverage_denominator import PostgresCoverageDenominatorRepository


class PostgresCoverageDenominatorTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        database = Path(self.tmpdir.name) / "center.db"
        self.engine = create_engine("sqlite+pysqlite:///%s" % database.as_posix(), future=True)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.repo = PostgresCoverageDenominatorRepository(PostgresStore(self.engine))
        self.service = CenterCoverageDenominatorService(self.repo, now_fn=lambda: 100)

    def _obligation(self, obligation_id):
        return CoverageObligation(obligation_id=obligation_id, layer="L3", subject_ref="api://%s" % obligation_id, source_refs=("trace://%s" % obligation_id,))

    def test_snapshot_receipt_and_expansion_survive_repository_reconstruction(self):
        first = self.service.freeze(snapshot_id="cov-v1", test_run_id="run-1", mission_node_id="run-1:scope:N7", layer="L3", source_revision="sha-1", obligations=(self._obligation("api-1"),))
        self.service.record(receipt_id="r1", snapshot_id=first.snapshot_id, obligation_id="api-1", state=CoverageObligationState.COVERED_PASS, attempt_id="a1", case_id="c1", evidence_refs=("evidence://api-1",))
        second, reopen = self.service.expand(new_snapshot_id="cov-v2", previous_snapshot_id="cov-v1", added_obligations=(self._obligation("api-2"),), reopen_id="reopen-1", evidence_refs=("evidence://risk/2",))
        reconstructed = PostgresCoverageDenominatorRepository(self.repo.store)
        self.assertEqual(second, reconstructed.current_snapshot("run-1", "L3"))
        self.assertEqual(1, len(reconstructed.receipts("cov-v1")))
        self.assertEqual(("r1",), reopen.invalidated_receipt_ids)


if __name__ == "__main__":
    unittest.main()
