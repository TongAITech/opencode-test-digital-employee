import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine

from rc8_center.control_plane import CenterControlPlane, MemoryCenterRepository, NodeStatus
from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_reality_snapshot import PostgresRealitySnapshotRepository
from rc8_center.reality_snapshot import CenterRealitySnapshotService, RealityCapabilityRequirement
from rc8_runtime.contracts import CapabilityQualification, CapabilityState, NodeIdentity
from rc8_runtime.r1_runtime import CentralR1RuntimeLedger


class PostgresRealitySnapshotRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        database = Path(self.tmpdir.name) / "center.db"
        engine = create_engine("sqlite+pysqlite:///%s" % database.as_posix(), future=True)
        Base.metadata.create_all(engine)
        self.repo = PostgresRealitySnapshotRepository(PostgresStore(engine))
        self.center_repo = MemoryCenterRepository()
        self.center = CenterControlPlane(
            self.center_repo,
            CentralR1RuntimeLedger(str(Path(self.tmpdir.name) / "r1.jsonl")),
            now_fn=lambda: 100,
        )
        self.center.register_node(
            NodeIdentity(
                node_id="pc-a",
                operator_ref="tester",
                os_family="linux",
                architecture="x86_64",
                shell="bash",
                registered_at=1,
            )
        )
        self.center.heartbeat("pc-a", status=NodeStatus.IDLE)
        self.center.qualify_capability(
            CapabilityQualification(
                node_id="pc-a",
                capability_id="dsh",
                state=CapabilityState.VERIFIED,
                probe_ref="probe://pc-a/dsh/1",
                evidence_refs=["evidence://pc-a/dsh/1"],
                verified_at=10,
            )
        )
        self.service = CenterRealitySnapshotService(self.center_repo, self.repo, now_fn=lambda: 200)

    def _capture(self, revision="sha-1"):
        return self.service.capture(
            test_run_id="run-1",
            scope_version="scope-v1",
            source_revision=revision,
            requirements=(RealityCapabilityRequirement("req-dsh", "dsh", "pc-a"),),
            environment_refs=("env://pfc/test",),
        )

    def test_snapshot_survives_repository_reconstruction(self):
        first = self._capture()
        reconstructed = PostgresRealitySnapshotRepository(self.repo.store)
        loaded = reconstructed.get_reality_snapshot(first.snapshot_id)
        self.assertEqual(first, loaded)
        latest = reconstructed.latest_reality_snapshot("run-1", "scope-v1")
        self.assertEqual(first.snapshot_id, latest.snapshot_id)

    def test_versions_are_monotonic_and_latest_is_deterministic(self):
        first = self._capture("sha-1")
        second = self._capture("sha-2")
        self.assertEqual(1, first.snapshot_version)
        self.assertEqual(2, second.snapshot_version)
        latest = self.repo.latest_reality_snapshot("run-1", "scope-v1")
        self.assertEqual(second.snapshot_id, latest.snapshot_id)
        self.assertEqual("sha-2", latest.source_revision)

    def test_same_snapshot_id_is_idempotent_but_conflicting_value_rejected(self):
        snapshot = self._capture()
        self.repo.save_reality_snapshot(snapshot)
        self.assertEqual(snapshot, self.repo.get_reality_snapshot(snapshot.snapshot_id))
        from dataclasses import replace
        with self.assertRaisesRegex(ValueError, "REALITY_SNAPSHOT_ID_CONFLICT"):
            self.repo.save_reality_snapshot(replace(snapshot, source_revision="other"))

    def test_non_monotonic_manual_version_is_rejected(self):
        from dataclasses import replace
        first = self._capture()
        manual = replace(
            first,
            snapshot_id="reality:run-1:scope-v1:v3",
            snapshot_version=3,
            source_revision="sha-3",
        )
        with self.assertRaisesRegex(ValueError, "VERSION_NON_MONOTONIC"):
            self.repo.save_reality_snapshot(manual)


if __name__ == "__main__":
    unittest.main()
