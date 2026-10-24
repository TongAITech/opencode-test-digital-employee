import unittest
from dataclasses import replace

from rc8_center.control_plane import CenterControlError, CenterControlPlane, MemoryCenterRepository, NodeStatus
from rc8_center.director_runtime_lifecycle import DirectorRuntimeLifecycle
from rc8_center.distributed_orchestration import ExecutionMode
from rc8_runtime.contracts import CapabilityQualification, CapabilityState, NodeIdentity
from rc8_runtime.r1_runtime import CentralR1RuntimeLedger


class DirectorRuntimeLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryCenterRepository()
        self.center = CenterControlPlane(self.repo, CentralR1RuntimeLedger(":memory:"), now_fn=lambda: 100)
        self._add_node("node-a")
        self._add_node("node-b")
        self.runtime = DirectorRuntimeLifecycle(self.repo)

    def _add_node(self, node_id):
        self.center.register_node(NodeIdentity(node_id=node_id, operator_ref="op", os_family="linux", architecture="x86_64", shell="bash", registered_at=1))
        for capability in ("ai_model", "dsh", "director_runtime"):
            self.center.qualify_capability(CapabilityQualification(node_id=node_id, capability_id=capability, state=CapabilityState.VERIFIED, probe_ref="probe://%s/%s" % (node_id, capability), evidence_refs=["evidence://%s/%s" % (node_id, capability)], verified_at=1))

    def _set_node_status(self, node_id, status):
        node = self.repo.get_node(node_id)
        self.assertIsNotNone(node)
        self.repo.upsert_node(replace(node, status=status))

    def test_distributed_re_elects_after_director_loss(self):
        first = self.runtime.elect("node-a")
        self.assertEqual("node-a", first.node_id)
        self._set_node_status("node-a", NodeStatus.OFFLINE)
        second = self.runtime.reconcile(ExecutionMode.DISTRIBUTED)
        self.assertEqual("node-b", second.node_id)
        self.assertEqual(first.generation + 1, second.generation)
        self.assertEqual("DIRECTOR_FAILOVER", second.reason)

    def test_single_node_fails_closed_instead_of_moving_director(self):
        first = self.runtime.elect("node-a")
        self._set_node_status("node-a", NodeStatus.OFFLINE)
        with self.assertRaises(CenterControlError):
            self.runtime.reconcile(ExecutionMode.SINGLE_NODE, single_node_id="node-a")
        self.assertEqual(first, self.runtime.state)

    def test_healthy_director_is_stable(self):
        first = self.runtime.elect("node-a")
        second = self.runtime.reconcile(ExecutionMode.DISTRIBUTED)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
