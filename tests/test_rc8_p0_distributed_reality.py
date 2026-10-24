import tempfile
import unittest
from pathlib import Path

from rc8_center.control_plane import CenterControlError, CenterControlPlane, MemoryCenterRepository
from rc8_center.distributed_lifecycle import DistributedLifecycleCoordinator
from rc8_center.distributed_orchestration import (
    ActorRole,
    DirectorExecutionFence,
    ExecutionMode,
    NodePlacementScheduler,
    PlacementPolicy,
)
from rc8_runtime.contracts import CapabilityQualification, CapabilityState, NodeIdentity, WorkItemIdentity
from rc8_runtime.r1_runtime import CentralR1RuntimeLedger


class P0DistributedRealityRegressionTest(unittest.TestCase):
    """Cross-component P0 regression; deterministic harness, not a claim of physical 2-PC reality."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = [100]
        self.repo = MemoryCenterRepository()
        self.ledger = CentralR1RuntimeLedger(str(Path(self.tmp.name) / "event-stream.jsonl"))
        self.center = CenterControlPlane(self.repo, self.ledger, now_fn=lambda: self.now[0])
        self.lifecycle = DistributedLifecycleCoordinator(
            self.center, heartbeat_timeout_seconds=30, now_fn=lambda: self.now[0]
        )
        self.scheduler = NodePlacementScheduler(self.repo)
        self._node(
            "director-node",
            ["ai_model", "dsh", "director_runtime", "agent_teams", "codegraph"],
        )
        self._node("worker-node", ["dsh", "agent_teams", "codegraph"])
        self.center.register_work_item(
            WorkItemIdentity(
                test_run_id="run-p0",
                work_item_id="work-p0",
                stage="CODE_ANALYSIS",
                scope_refs=["scope-p0"],
                required_capabilities=["agent_teams", "codegraph"],
            )
        )

    def _node(self, node_id, capabilities):
        self.center.register_node(
            NodeIdentity(
                node_id=node_id,
                operator_ref="p0-regression",
                os_family="linux",
                architecture="x86_64",
                shell="bash",
                registered_at=1,
            )
        )
        self.center.heartbeat(node_id)
        for capability in capabilities:
            self.center.qualify_capability(
                CapabilityQualification(
                    node_id=node_id,
                    capability_id=capability,
                    state=CapabilityState.VERIFIED,
                    probe_ref="probe://%s/%s" % (node_id, capability),
                    evidence_refs=["evidence://%s/%s" % (node_id, capability)],
                    verified_at=1,
                )
            )

    def test_center_director_separation_and_worker_failover_share_one_r1_truth(self):
        director = self.scheduler.select_director_node()
        self.assertEqual("director-node", director.identity.node_id)
        with self.assertRaisesRegex(CenterControlError, "DIRECTOR_DOMAIN_EXECUTION_FORBIDDEN"):
            DirectorExecutionFence.authorize(ActorRole.DIRECTOR, "CODEGRAPH_EXECUTION")

        policy = PlacementPolicy(
            mode=ExecutionMode.DISTRIBUTED,
            director_node_id=director.identity.node_id,
        )
        first = self.lifecycle.dispatch("work-p0", policy, ttl_seconds=300)
        self.assertEqual("worker-node", first.decision.node_id)
        first_attempt = first.attempt_id

        # Worker disappears while the Director host remains healthy. Center, not
        # Director, expires the old lease and re-places the domain WorkItem.
        self.now[0] = 125
        self.center.heartbeat("director-node")
        self.now[0] = 140
        second = self.lifecycle.reconcile("work-p0", policy, ttl_seconds=60)
        self.assertIsNotNone(second)
        self.assertEqual("director-node", second.decision.node_id)
        self.assertNotEqual(first_attempt, second.attempt_id)

        # Even when the Director host is the only remaining capable node, the
        # Director role itself stays fenced; execution must be node-local team work.
        with self.assertRaisesRegex(CenterControlError, "DIRECTOR_DOMAIN_EXECUTION_FORBIDDEN"):
            DirectorExecutionFence.authorize(ActorRole.DIRECTOR, "CODEGRAPH_EXECUTION")
        DirectorExecutionFence.authorize(ActorRole.TEAM_WORKER, "CODEGRAPH_EXECUTION")

        self.lifecycle.record_stale_attempt_rejected(
            work_item_id="work-p0",
            node_id="worker-node",
            attempt_id=first_attempt,
            reason="LEASE_OWNER_CHANGED",
        )
        events = self.ledger.runtime_events(test_run_id="run-p0", work_item_id="work-p0")
        self.assertEqual(
            ["PLACED", "LEASED", "NODE_LOST", "LEASE_EXPIRED", "PLACED", "LEASED", "STALE_ATTEMPT_REJECTED"],
            [event["event_type"] for event in events],
        )
        self.assertEqual(second.attempt_id, events[-1]["data"]["current_attempt_id"])

    def test_single_node_never_silently_fails_over(self):
        policy = PlacementPolicy(mode=ExecutionMode.SINGLE_NODE, target_node_id="worker-node")
        self.lifecycle.dispatch("work-p0", policy, ttl_seconds=300)
        self.now[0] = 140
        self.center.heartbeat("director-node")
        with self.assertRaisesRegex(CenterControlError, "NODE_NOT_PLACEMENT_ELIGIBLE"):
            self.lifecycle.reconcile("work-p0", policy, ttl_seconds=60)
        current = self.repo.get_work_item("work-p0")
        self.assertIsNone(current.lease_id)
        self.assertIsNone(current.lease_owner_node_id)


if __name__ == "__main__":
    unittest.main()
