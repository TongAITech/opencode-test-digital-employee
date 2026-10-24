import tempfile
import unittest
from pathlib import Path

from rc8_center.control_plane import CenterControlError, CenterControlPlane, MemoryCenterRepository, NodeStatus
from rc8_center.distributed_lifecycle import DistributedLifecycleCoordinator, DistributedLifecycleError
from rc8_center.distributed_orchestration import ExecutionMode, PlacementPolicy
from rc8_runtime.contracts import (
    CapabilityQualification,
    CapabilityState,
    NodeIdentity,
    WorkItemIdentity,
)
from rc8_runtime.r1_runtime import CentralR1RuntimeLedger


class DistributedLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.now = [100]
        self.repo = MemoryCenterRepository()
        self.ledger = CentralR1RuntimeLedger(str(Path(self.temp_dir.name) / "event-stream.jsonl"))
        self.center = CenterControlPlane(self.repo, self.ledger, now_fn=lambda: self.now[0])
        self.lifecycle = DistributedLifecycleCoordinator(
            self.center,
            heartbeat_timeout_seconds=30,
            now_fn=lambda: self.now[0],
        )
        self._add_node("node-1")
        self._add_node("node-2")
        self.center.register_work_item(
            WorkItemIdentity(
                work_item_id="work-1",
                test_run_id="run-1",
                stage="CODE_ANALYSIS",
                scope_refs=["scope-1"],
                required_capabilities=["codegraph", "agent_teams"],
            )
        )

    def _add_node(self, node_id):
        self.center.register_node(
            NodeIdentity(
                node_id=node_id,
                operator_ref="operator-test",
                os_family="linux",
                architecture="x86_64",
                shell="bash",
                registered_at=1,
            )
        )
        for capability in ("codegraph", "agent_teams"):
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

    def _events(self):
        return self.ledger.runtime_events(test_run_id="run-1", work_item_id="work-1")

    def test_distributed_node_loss_requeues_to_healthy_node_and_audits_stale_attempt(self):
        policy = PlacementPolicy(mode=ExecutionMode.DISTRIBUTED)
        first = self.lifecycle.dispatch("work-1", policy, ttl_seconds=300)
        self.assertEqual("node-1", first.decision.node_id)
        old_attempt = first.attempt_id

        self.now[0] = 195
        self.center.heartbeat("node-2")
        self.now[0] = 200
        second = self.lifecycle.reconcile("work-1", policy, ttl_seconds=60)
        self.assertIsNotNone(second)
        self.assertEqual("node-2", second.decision.node_id)
        self.assertNotEqual(old_attempt, second.attempt_id)
        self.assertEqual(NodeStatus.OFFLINE, self.repo.get_node("node-1").status)

        with self.assertRaisesRegex(CenterControlError, "ACTIVE_WORK_ITEM_LEASE_REQUIRED"):
            self.center.authorize_work_item_write(
                test_run_id="run-1",
                work_item_id="work-1",
                node_id="node-1",
            )
        self.lifecycle.record_stale_attempt_rejected(
            work_item_id="work-1",
            node_id="node-1",
            attempt_id=old_attempt,
            reason="LEASE_OWNER_CHANGED",
        )

        events = self._events()
        event_types = [event["event_type"] for event in events]
        self.assertEqual(
            [
                "PLACED",
                "LEASED",
                "NODE_LOST",
                "LEASE_EXPIRED",
                "PLACED",
                "LEASED",
                "STALE_ATTEMPT_REJECTED",
            ],
            event_types,
        )
        stale = events[-1]
        self.assertEqual(old_attempt, stale["attempt_id"])
        self.assertEqual(second.attempt_id, stale["data"]["current_attempt_id"])
        self.assertEqual("node-2", stale["data"]["current_node_id"])
        self.assertEqual("CENTER", stale["data"]["actor_role"])

    def test_ttl_expiry_on_healthy_node_creates_new_attempt_without_marking_node_lost(self):
        policy = PlacementPolicy(mode=ExecutionMode.DISTRIBUTED)
        first = self.lifecycle.dispatch("work-1", policy, ttl_seconds=5)
        old_attempt = first.attempt_id
        self.now[0] = 104
        self.center.heartbeat("node-1")
        self.now[0] = 106
        second = self.lifecycle.reconcile("work-1", policy, ttl_seconds=60)

        self.assertIsNotNone(second)
        self.assertEqual("node-1", second.decision.node_id)
        self.assertNotEqual(old_attempt, second.attempt_id)
        self.assertEqual(NodeStatus.EXECUTING, self.repo.get_node("node-1").status)
        event_types = [event["event_type"] for event in self._events()]
        self.assertIn("LEASE_EXPIRED", event_types)
        self.assertNotIn("NODE_LOST", event_types)

    def test_single_node_mode_fails_closed_when_selected_node_is_lost(self):
        policy = PlacementPolicy(mode=ExecutionMode.SINGLE_NODE, target_node_id="node-1")
        first = self.lifecycle.dispatch("work-1", policy, ttl_seconds=300)
        self.assertEqual("node-1", first.decision.node_id)
        self.now[0] = 200

        with self.assertRaisesRegex(CenterControlError, "NODE_NOT_PLACEMENT_ELIGIBLE"):
            self.lifecycle.reconcile("work-1", policy, ttl_seconds=60)

        current = self.repo.get_work_item("work-1")
        self.assertIsNone(current.lease_id)
        self.assertEqual(NodeStatus.OFFLINE, self.repo.get_node("node-1").status)
        event_types = [event["event_type"] for event in self._events()]
        self.assertEqual(
            ["PLACED", "LEASED", "NODE_LOST", "LEASE_EXPIRED"],
            event_types,
        )

    def test_valid_active_attempt_cannot_be_falsely_recorded_as_stale(self):
        policy = PlacementPolicy(mode=ExecutionMode.DISTRIBUTED)
        current = self.lifecycle.dispatch("work-1", policy, ttl_seconds=60)
        with self.assertRaisesRegex(DistributedLifecycleError, "ATTEMPT_IS_STILL_ACTIVE"):
            self.lifecycle.record_stale_attempt_rejected(
                work_item_id="work-1",
                node_id=current.decision.node_id,
                attempt_id=current.attempt_id,
                reason="SHOULD_NOT_HAPPEN",
            )
        self.assertNotIn(
            "STALE_ATTEMPT_REJECTED",
            [event["event_type"] for event in self._events()],
        )


if __name__ == "__main__":
    unittest.main()
