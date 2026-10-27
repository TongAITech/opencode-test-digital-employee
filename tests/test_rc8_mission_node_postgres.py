import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from sqlalchemy import create_engine

from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_mission_node import PostgresMissionNodeRepository
from rc8_center.mission_node_repository import MissionNodeRepositoryError
from rc8_runtime.mission_nodes import MissionNodeAdoptionGraph, MissionNodeState, MissionNodeType


class PostgresMissionNodeRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        database = Path(self.tmpdir.name) / "center.db"
        self.engine = create_engine("sqlite+pysqlite:///%s" % database.as_posix(), future=True)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.store = PostgresStore(self.engine)
        self.repo = PostgresMissionNodeRepository(self.store, now_fn=lambda: 100)

    def test_current_node_state_survives_repository_reconstruction(self):
        graph = MissionNodeAdoptionGraph("run-1", "scope-v1")
        node = graph.node(MissionNodeType.N3_CODE_ANALYSIS)
        passed = replace(
            node,
            state=MissionNodeState.PASS,
            output_refs=("evidence://codegraph/1", "center-gate:gate-1"),
        )
        self.repo.save(passed)

        reconstructed = PostgresMissionNodeRepository(self.store, now_fn=lambda: 101)
        self.assertEqual(passed, reconstructed.get(passed.mission_node_id))
        self.assertIn(passed, reconstructed.list_for_test_run("run-1"))

    def test_identity_fields_are_immutable(self):
        graph = MissionNodeAdoptionGraph("run-1", "scope-v1")
        node = graph.node(MissionNodeType.N3_CODE_ANALYSIS)
        self.repo.save(node)
        with self.assertRaisesRegex(MissionNodeRepositoryError, "SCOPE_VERSION_IMMUTABLE"):
            self.repo.save(replace(node, scope_version="scope-v2"))


if __name__ == "__main__":
    unittest.main()
