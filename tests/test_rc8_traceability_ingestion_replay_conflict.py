import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from sqlalchemy import create_engine

from rc8_center.code_source import CodeSourceSnapshot
from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_traceability import PostgresTraceabilityRepository
from rc8_center.traceability import (
    TraceNodeType,
    TraceRelationType,
    TraceabilityError,
    TraceabilityGraph,
)
from rc8_center.traceability_ingestion import (
    CenterTraceabilityIngestion,
    RawTraceObservation,
    TraceEndpointObservation,
    TraceObservationSource,
)


class CenterTraceabilityReplayConflictTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        database = Path(self.tmpdir.name) / "center.db"
        self.engine = create_engine("sqlite+pysqlite:///%s" % database.as_posix(), future=True)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.store = PostgresStore(self.engine)
        self.store.create_test_run("run-1", test_round_id="round-1", now=1)
        self.repo = PostgresTraceabilityRepository(self.store)
        self.repo.freeze_code_source(
            CodeSourceSnapshot(
                snapshot_id="code-1",
                repository_id="pfc",
                repository_url="git://pfc",
                application_id="cfg-center",
                base_commit_sha="base",
                commit_sha="head",
                created_at=1,
                payload={"changed_java_files": [], "changed_methods": []},
            ),
            test_round_id="round-1",
            scope_revision_id="scope-1",
        )
        self.repo.create_graph(
            TraceabilityGraph(
                graph_id="graph-1",
                test_run_id="run-1",
                test_round_id="round-1",
                scope_revision_id="scope-1",
                code_source_snapshot_id="code-1",
                created_at=1,
                payload={},
            )
        )
        self.ingestion = CenterTraceabilityIngestion(self.repo)

    def observation(self):
        return RawTraceObservation(
            observation_id="obs-1",
            graph_id="graph-1",
            source_kind=TraceObservationSource.CODEGRAPH,
            source_ref="codegraph://run/obs-1",
            from_endpoint=TraceEndpointObservation(TraceNodeType.API, "GET /a", "GET /a"),
            to_endpoint=TraceEndpointObservation(TraceNodeType.METHOD, "A#m", "A#m"),
            relation_type=TraceRelationType.API_IMPLEMENTED_BY,
            captured_at=100,
            integrity_hash="sha256:original",
            stage_id="stage-code",
            work_item_id="work-code",
            attempt_id="attempt-code",
        )

    def test_same_observation_id_with_changed_integrity_is_fail_closed(self):
        original = self.observation()
        self.ingestion.ingest(original)
        with self.assertRaisesRegex(TraceabilityError, "TRACE_OBSERVATION_ID_CONFLICT"):
            self.ingestion.ingest(replace(original, integrity_hash="sha256:tampered"))

    def test_same_observation_id_with_changed_source_ref_is_fail_closed(self):
        original = self.observation()
        self.ingestion.ingest(original)
        with self.assertRaisesRegex(TraceabilityError, "TRACE_OBSERVATION_ID_CONFLICT"):
            self.ingestion.ingest(replace(original, source_ref="codegraph://other/obs-1"))


if __name__ == "__main__":
    unittest.main()
