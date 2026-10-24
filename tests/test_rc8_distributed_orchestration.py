import unittest

from rc8_center.control_plane import (
    CenterControlError,
    MemoryCenterRepository,
    NodeRecord,
    NodeStatus,
    WorkItemRecord,
)
from rc8_center.distributed_orchestration import (
    ActorRole,
    DirectorExecutionFence,
    ExecutionMode,
    NodePlacementScheduler,
    PlacementPolicy,
)
from rc8_runtime import CapabilityQualification, CapabilityState, NodeIdentity, WorkItemIdentity


class DistributedOrchestrationTest(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryCenterRepository()
        self.scheduler = NodePlacementScheduler(self.repo)

    def add_node(self, node_id, capabilities, status=NodeStatus.IDLE):
        identity = NodeIdentity(
            node_id=node_id,
            operator_ref="operator-test",
            os_family="linux",
            architecture="x86_64",
            shell="bash",
        )
        self.repo.upsert_node(NodeRecord(identity, status, 1, 1))
        for capability in capabilities:
            self.repo.upsert_capability(
                CapabilityQualification(
                    node_id=node_id,
                    capability_id=capability,
                    state=CapabilityState.VERIFIED,
                    probe_ref="probe://%s/%s" % (node_id, capability),
                    evidence_refs=["evidence://%s/%s" % (node_id, capability)],
                    verified_at=1,
                )
            )

    def work(self, required):
        identity = WorkItemIdentity(
            test_run_id="run-1",
            work_item_id="work-1",
            stage="CODE_ANALYSIS",
            scope_refs=["scope-1"],
            required_capabilities=list(required),
        )
        return WorkItemRecord(identity=identity)

    def test_single_node_pins_all_work_to_selected_node(self):
        self.add_node("node-1", ["codegraph"])
        decision = self.scheduler.place(
            self.work(["codegraph"]),
            PlacementPolicy(ExecutionMode.SINGLE_NODE, target_node_id="node-1"),
        )
        self.assertEqual("node-1", decision.node_id)
        self.assertEqual("SINGLE_NODE_PIN", decision.reason)

    def test_single_node_fails_closed_when_target_lacks_capability(self):
        self.add_node("node-1", ["browser"])
        with self.assertRaisesRegex(CenterControlError, "NODE_REQUIRED_CAPABILITY_NOT_VERIFIED"):
            self.scheduler.place(
                self.work(["codegraph"]),
                PlacementPolicy(ExecutionMode.SINGLE_NODE, target_node_id="node-1"),
            )

    def test_distributed_prefers_capable_worker_over_director_host(self):
        self.add_node("director-node", ["codegraph", "ai_model", "dsh", "director_runtime"])
        self.add_node("code-node", ["codegraph"])
        decision = self.scheduler.place(
            self.work(["codegraph"]),
            PlacementPolicy(ExecutionMode.DISTRIBUTED, director_node_id="director-node"),
        )
        self.assertEqual("code-node", decision.node_id)
        self.assertEqual("CAPABILITY_AWARE", decision.reason)

    def test_director_selection_requires_ai_dsh_and_director_runtime(self):
        self.add_node("worker", ["codegraph"])
        self.add_node("director", ["ai_model", "dsh", "director_runtime"])
        self.assertEqual("director", self.scheduler.select_director_node().identity.node_id)

    def test_director_domain_execution_is_forbidden(self):
        with self.assertRaisesRegex(CenterControlError, "DIRECTOR_DOMAIN_EXECUTION_FORBIDDEN"):
            DirectorExecutionFence.authorize(ActorRole.DIRECTOR, "CODEGRAPH_EXECUTION")
        self.assertFalse(
            DirectorExecutionFence.evidence_counts_for_sufficiency(
                ActorRole.DIRECTOR, "BROWSER_EXECUTION"
            )
        )

    def test_team_worker_domain_execution_is_allowed(self):
        DirectorExecutionFence.authorize(ActorRole.TEAM_WORKER, "CODEGRAPH_EXECUTION")
        self.assertTrue(
            DirectorExecutionFence.evidence_counts_for_sufficiency(
                ActorRole.TEAM_WORKER, "CODEGRAPH_EXECUTION"
            )
        )


if __name__ == "__main__":
    unittest.main()
