"""Runtime batch history checks using cold, durable R1 fixtures."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_domain import ReleaseBatch
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.rc72_state_machine import RC72StateMachine
from tools.dsh_workbench.runtime_batch_history import (
    RuntimeBatchHistoryError, verify_runtime_batch_history,
)
from tools.dsh_workbench.runtime_batch_mapping import RuntimeBatchMapping


class RuntimeBatchHistoryTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "r1.jsonl"
        self.truth = TruthRuntime(self.path)
        self.mapping = RuntimeBatchMapping(1, "authority", "mapping", "project", "PG-BATCH",
                                           "RT-RELEASE", "RT-BATCH", "MISSION", "operation")
        self.batch = ReleaseBatch("RT-BATCH", "MISSION", "release")
        self.repo = CanonicalRC72Repository(self.truth, release_id="RT-RELEASE")

    def bootstrap(self):
        RC72StateMachine(self.truth, release_id="RT-RELEASE").bootstrap_release_batch(self.batch)

    def verify(self):
        before = self.path.read_bytes()
        try:
            return verify_runtime_batch_history(TruthRuntime(self.path).store.iter_raw(), self.mapping)
        finally:
            self.assertEqual(self.path.read_bytes(), before)

    def test_missing_and_bootstrapped_with_ordinary_history_and_exact_id(self):
        self.assertIsNone(self.verify())
        self.bootstrap()
        initial = self.verify()
        self.assertEqual(initial.latest_version, 1)
        self.assertEqual(len(self.truth.query("rc72_mission_node", mission_id="MISSION")), 10)
        self.repo.persist(ReleaseBatch("RT-BATCH@ALT", "OTHER", "independent"))
        self.repo.persist(ReleaseBatch("RT-BATCH", "MISSION", "revised"), artifact_version=2)
        latest = self.verify()
        self.assertEqual(latest.latest_version, 2)
        self.assertEqual(latest.initial_event_id, initial.initial_event_id)
        self.assertNotEqual(latest.latest_event_id, initial.latest_event_id)

    def test_identity_drift_still_rejected_after_change_back(self):
        self.bootstrap()
        other = CanonicalRC72Repository(self.truth, release_id="OTHER-RELEASE")
        other.persist(ReleaseBatch("RT-BATCH", "OTHER-MISSION", "drift"), artifact_version=2)
        self.repo.persist(self.batch, artifact_version=3)
        self.assertEqual(TruthRuntime(self.path).query("rc72_release_batch", release_batch_id="RT-BATCH")[0]
                         ["mission_id"], "MISSION")
        with self.assertRaisesRegex(RuntimeBatchHistoryError, "HISTORY_CONFLICT"):
            self.verify()

    def test_duplicate_raw_creation_does_not_collapse(self):
        self.bootstrap()
        current = self.truth.query("rc72_release_batch", release_batch_id="RT-BATCH")[0]
        self.truth.store.append("RC72_RELEASE_BATCH_UPSERTED", current)
        self.assertEqual(len(TruthRuntime(self.path).query("rc72_release_batch", release_batch_id="RT-BATCH")), 1)
        with self.assertRaisesRegex(RuntimeBatchHistoryError, "EVENT_INVALID"):
            self.verify()

    def test_conflicting_batch_for_same_mission(self):
        self.bootstrap()
        self.repo.persist(ReleaseBatch("PG-BATCH", "MISSION", "conflicting"))
        with self.assertRaisesRegex(RuntimeBatchHistoryError, "HISTORY_CONFLICT"):
            self.verify()

    def test_raw_entity_metadata_must_match_payload(self):
        self.bootstrap()
        event = next(self.truth.store.iter_raw())
        event["entity_id"] = "PG-BATCH"
        with self.assertRaisesRegex(RuntimeBatchHistoryError, "EVENT_INVALID"):
            verify_runtime_batch_history([event], self.mapping)

    def test_matching_event_must_pass_the_canonical_release_batch_validator(self):
        self.bootstrap()
        event = next(self.truth.store.iter_raw())
        del event["payload"]["name"]
        with self.assertRaisesRegex(RuntimeBatchHistoryError, "EVENT_INVALID"):
            verify_runtime_batch_history([event], self.mapping)

    def test_canonical_normalization_cannot_hide_a_foreign_update(self):
        self.bootstrap()
        event = next(self.truth.store.iter_raw())
        event.update(event_id="foreign-event", seq=100, entity_id=" RT-BATCH ", entity_version=2)
        event["payload"].update(release_batch_id=" RT-BATCH ", release_id="FOREIGN",
                                mission_id="OTHER-MISSION", artifact_version=2)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event) + "\n")
        cold = TruthRuntime(self.path)
        self.assertEqual(cold.query("rc72_release_batch", release_batch_id="RT-BATCH")[0]
                         ["mission_id"], "OTHER-MISSION")
        with self.assertRaisesRegex(RuntimeBatchHistoryError, "HISTORY_CONFLICT"):
            self.verify()
