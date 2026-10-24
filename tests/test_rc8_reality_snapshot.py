import tempfile
import unittest
from pathlib import Path

from rc8_center.control_plane import CenterControlPlane, MemoryCenterRepository, NodeStatus
from rc8_center.reality_snapshot import (
    CenterRealitySnapshotService,
    MemoryRealitySnapshotRepository,
    RealityCapabilityRequirement,
)
from rc8_runtime.contracts import CapabilityQualification, CapabilityState, NodeIdentity
from rc8_runtime.mission_nodes import MissionNodeAdoptionGraph, MissionNodeType
from rc8_runtime.r1_runtime import CentralR1RuntimeLedger


class CenterRealitySnapshotServiceTest(unittest.TestCase):
    def setUp(self):
        self.center_repo = MemoryCenterRepository()
        self.snapshot_repo = MemoryRealitySnapshotRepository()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.center = CenterControlPlane(
            self.center_repo,
            CentralR1RuntimeLedger(str(Path(self.tmpdir.name) / "r1.jsonl")),
            now_fn=lambda: 100,
        )
        self.service = CenterRealitySnapshotService(self.center_repo, self.snapshot_repo, now_fn=lambda: 200)
        self._register_node("pc-a")
        self._register_node("pc-b")

    def _register_node(self, node_id):
        self.center.register_node(
            NodeIdentity(
                node_id=node_id,
                operator_ref="tester",
                os_family="linux",
                architecture="x86_64",
                shell="bash",
                registered_at=1,
            )
        )
        self.center.heartbeat(node_id, status=NodeStatus.IDLE)

    def _qualify(self, node_id, capability_id, *, state=CapabilityState.VERIFIED, verified_at=10, probe_suffix="1"):
        probe_ref = None
        evidence_refs = []
        timestamp = None
        if state == CapabilityState.VERIFIED:
            probe_ref = "probe://%s/%s/%s" % (node_id, capability_id, probe_suffix)
            evidence_refs = ["evidence://%s/%s/%s" % (node_id, capability_id, probe_suffix)]
            timestamp = verified_at
        self.center.qualify_capability(
            CapabilityQualification(
                node_id=node_id,
                capability_id=capability_id,
                state=state,
                probe_ref=probe_ref,
                evidence_refs=evidence_refs,
                verified_at=timestamp,
            )
        )

    def _capture(self, requirements, *, source_revision="sha-1", environment_refs=("env://pfc/test",)):
        return self.service.capture(
            test_run_id="run-1",
            scope_version="scope-v1",
            source_revision=source_revision,
            requirements=requirements,
            environment_refs=environment_refs,
        )

    def test_verified_probe_evidence_freezes_ready_snapshot_and_binds_n2(self):
        self._qualify("pc-a", "dsh")
        snapshot = self._capture((RealityCapabilityRequirement("req-dsh", "dsh", "pc-a"),))
        self.assertTrue(snapshot.ready)
        self.assertEqual(1, snapshot.snapshot_version)
        self.assertEqual("pc-a", snapshot.capabilities[0].execution_node_id)
        self.assertTrue(snapshot.capabilities[0].probe_ref.startswith("probe://"))
        graph = MissionNodeAdoptionGraph("run-1", "scope-v1")
        binding = self.service.bind_downstream(graph.node(MissionNodeType.N2_REQUIREMENT_ANALYSIS), snapshot)
        self.assertEqual(snapshot.snapshot_id, binding.reality_snapshot_id)
        self.assertEqual(snapshot.fingerprint, binding.reality_fingerprint)

    def test_registered_but_unprobed_capability_is_blocker_not_reality(self):
        self._qualify("pc-a", "codegraph", state=CapabilityState.REGISTERED)
        snapshot = self._capture((RealityCapabilityRequirement("req-codegraph", "codegraph", "pc-a"),))
        self.assertFalse(snapshot.ready)
        self.assertEqual(0, len(snapshot.capabilities))
        self.assertEqual("CAPABILITY_NOT_VERIFIED", snapshot.blockers[0].reason)
        graph = MissionNodeAdoptionGraph("run-1", "scope-v1")
        with self.assertRaisesRegex(ValueError, "REALITY_SNAPSHOT_BLOCKED"):
            self.service.bind_downstream(graph.node(MissionNodeType.N3_CODE_ANALYSIS), snapshot)

    def test_offline_node_does_not_satisfy_verified_capability(self):
        self._qualify("pc-a", "browser")
        self.center.heartbeat("pc-a", status=NodeStatus.OFFLINE)
        snapshot = self._capture((RealityCapabilityRequirement("req-browser", "browser", "pc-a"),))
        self.assertFalse(snapshot.ready)
        self.assertEqual("CAPABILITY_NOT_VERIFIED", snapshot.blockers[0].reason)

    def test_unpinned_requirement_selects_latest_healthy_verified_node(self):
        self._qualify("pc-a", "dsh", verified_at=10, probe_suffix="old")
        self._qualify("pc-b", "dsh", verified_at=20, probe_suffix="new")
        snapshot = self._capture((RealityCapabilityRequirement("req-dsh", "dsh"),))
        self.assertTrue(snapshot.ready)
        self.assertEqual("pc-b", snapshot.capabilities[0].execution_node_id)

    def test_noncritical_missing_capability_does_not_block_snapshot(self):
        snapshot = self._capture((RealityCapabilityRequirement("req-optional", "optional-tool", critical=False),))
        self.assertTrue(snapshot.ready)
        self.assertEqual(0, len(snapshot.blockers))

    def test_same_reality_new_snapshot_version_is_not_material_change(self):
        self._qualify("pc-a", "dsh")
        requirements = (RealityCapabilityRequirement("req-dsh", "dsh", "pc-a"),)
        first = self._capture(requirements)
        second = self._capture(requirements)
        self.assertEqual(2, second.snapshot_version)
        self.assertEqual(first.fingerprint, second.fingerprint)
        change = self.service.compare(first, second)
        self.assertFalse(change.material)
        self.assertEqual(tuple(), change.invalidate_mission_nodes)

    def test_new_probe_is_material_and_invalidates_all_downstream_nodes(self):
        self._qualify("pc-a", "dsh", verified_at=10, probe_suffix="1")
        requirements = (RealityCapabilityRequirement("req-dsh", "dsh", "pc-a"),)
        first = self._capture(requirements)
        self._qualify("pc-a", "dsh", verified_at=11, probe_suffix="2")
        second = self._capture(requirements)
        change = self.service.compare(first, second)
        self.assertTrue(change.material)
        self.assertEqual(("req-dsh",), change.changed_requirement_ids)
        self.assertNotIn(MissionNodeType.N1_REALITY_ENVIRONMENT_RECON, change.invalidate_mission_nodes)
        self.assertIn(MissionNodeType.N2_REQUIREMENT_ANALYSIS, change.invalidate_mission_nodes)
        self.assertIn(MissionNodeType.N10_MISSION_EVIDENCE_GLOBAL_CONVERGENCE, change.invalidate_mission_nodes)

    def test_source_revision_change_is_material_even_when_capabilities_same(self):
        self._qualify("pc-a", "dsh")
        requirements = (RealityCapabilityRequirement("req-dsh", "dsh", "pc-a"),)
        first = self._capture(requirements, source_revision="sha-1")
        second = self._capture(requirements, source_revision="sha-2")
        change = self.service.compare(first, second)
        self.assertTrue(change.material)
        self.assertEqual(tuple(), change.changed_requirement_ids)
        self.assertGreater(len(change.invalidate_mission_nodes), 0)

    def test_cross_scope_binding_and_n1_self_binding_fail_closed(self):
        self._qualify("pc-a", "dsh")
        snapshot = self._capture((RealityCapabilityRequirement("req-dsh", "dsh", "pc-a"),))
        graph = MissionNodeAdoptionGraph("run-1", "scope-v1")
        with self.assertRaisesRegex(ValueError, "N1_PRODUCES_REALITY"):
            self.service.bind_downstream(graph.node(MissionNodeType.N1_REALITY_ENVIRONMENT_RECON), snapshot)
        other_graph = MissionNodeAdoptionGraph("run-1", "scope-v2")
        with self.assertRaisesRegex(ValueError, "REALITY_SNAPSHOT_SCOPE_MISMATCH"):
            self.service.bind_downstream(other_graph.node(MissionNodeType.N2_REQUIREMENT_ANALYSIS), snapshot)


if __name__ == "__main__":
    unittest.main()
