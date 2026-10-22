#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rc8_center.control_plane import WorkItemRecord, WorkItemState
from rc8_center.recovery import RecoveryReason
from rc8_center.recovery_service import LeaseRecoveryCoordinator
from rc8_runtime import WorkItemIdentity


class FakeControlRepository:
    def __init__(self, work_item: WorkItemRecord) -> None:
        self.work_item = work_item

    def list_work_items(self):
        return [self.work_item]


class FakeRecoveryRepository:
    def __init__(self) -> None:
        self.items = {}

    def get(self, incident_id):
        return self.items.get(incident_id)

    def upsert_open(self, incident):
        self.items[incident.incident_id] = incident
        return incident


class FakeCoordination:
    def lease_info(self, resource_type, resource_id):
        return {"owner_id": "stale-node", "lease_id": "stale-lease"}


class FakeLedger:
    def runtime_events(self):
        return []


class RecoveryStateContractTests(unittest.TestCase):
    def test_work_item_state_machine_is_the_frozen_rc8_contract(self) -> None:
        self.assertEqual(
            {state.value for state in WorkItemState},
            {"REGISTERED", "READY", "LEASED", "RUNNING", "COMPLETED", "FAILED", "BLOCKED"},
        )
        self.assertFalse(hasattr(WorkItemState, "PENDING"))

    def test_non_leased_states_with_redis_lease_reconcile_as_divergence(self) -> None:
        for state in (WorkItemState.REGISTERED, WorkItemState.READY, WorkItemState.BLOCKED):
            with self.subTest(state=state.value):
                work = WorkItemRecord(
                    identity=WorkItemIdentity(
                        work_item_id="work-%s" % state.value.lower(),
                        test_run_id="run-recovery-contract",
                        stage="L1_EXECUTION",
                        scope_refs=["scope:recovery-contract"],
                    ),
                    state=state,
                )
                coordinator = LeaseRecoveryCoordinator(
                    FakeControlRepository(work),
                    FakeRecoveryRepository(),
                    FakeCoordination(),
                    FakeLedger(),
                    now_fn=lambda: 100,
                )
                incidents = coordinator.reconcile()
                self.assertEqual(len(incidents), 1)
                self.assertEqual(incidents[0].work_item_state, state.value)
                self.assertEqual(incidents[0].reason, RecoveryReason.REDIS_LEASE_DIVERGED)


if __name__ == "__main__":
    unittest.main()
