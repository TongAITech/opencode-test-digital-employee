"""Read-only RC7.2 status must distinguish NOT_BOOTSTRAPPED from corrupt R1."""
from __future__ import annotations

import unittest

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_release_driver import release_batch_status


SOURCE = "a" * 40
BATCH = "BLOAN-PF1.3.0"


class _ReadOnlyTruth:
    def __init__(self, batches):
        self.batches = batches
        self.rebuilt = 0
        self.writes = []

    def rebuild_projection(self):
        self.rebuilt += 1

    def query(self, artifact_type, **filters):
        if artifact_type == "rc72_release_batch":
            return [x for x in self.batches if x["release_batch_id"] == filters["release_batch_id"]]
        if artifact_type == "rc72_mission_node":
            return []
        raise AssertionError("Unexpected query: " + artifact_type)

    def append_atomic(self, *args, **kwargs):
        self.writes.append((args, kwargs))
        raise AssertionError("Status must never write R1")


class RC72MissingReleaseBatchStatusTests(unittest.TestCase):
    def test_zero_batch_is_readable_and_not_success(self):
        truth = _ReadOnlyTruth([])
        output = release_batch_status(truth, source_commit=SOURCE, release_batch_id=BATCH)
        self.assertEqual(output["status"], "NOT_BOOTSTRAPPED")
        self.assertEqual(output["bootstrap"], "NOT_STARTED")
        self.assertEqual(output["release_batch_id"], BATCH)
        self.assertEqual(output["source_commit"], SOURCE)
        self.assertIsNone(output["mission_id"])
        self.assertIsNone(output["release_id"])
        self.assertEqual(output["nodes"], [])
        self.assertFalse(output["field_verified"])
        self.assertFalse(output["bank_final"])
        self.assertEqual(truth.rebuilt, 1)
        self.assertEqual(truth.writes, [])

    def test_duplicates_still_fail_closed(self):
        row = {"release_batch_id": BATCH, "release_id": "release", "mission_id": "mission"}
        truth = _ReadOnlyTruth([dict(row), dict(row)])
        with self.assertRaisesRegex(ContractError, "RC72_RELEASE_DRIVER_TRUTH_NOT_UNIQUE"):
            release_batch_status(truth, source_commit=SOURCE, release_batch_id=BATCH)
        self.assertEqual(truth.writes, [])

    def test_existing_batch_without_nodes_is_not_pass(self):
        row = {"release_batch_id": BATCH, "release_id": "release", "mission_id": "mission"}
        truth = _ReadOnlyTruth([row])
        output = release_batch_status(truth, source_commit=SOURCE, release_batch_id=BATCH)
        self.assertEqual(output["nodes"], [])
        self.assertFalse(output["field_verified"])
        self.assertFalse(output["bank_final"])
        self.assertEqual(truth.writes, [])

    def test_untrusted_source_is_refused_even_for_zero_batch(self):
        truth = _ReadOnlyTruth([])
        with self.assertRaisesRegex(ContractError, "RC72_RELEASE_DRIVER_EXACT_SOURCE_REQUIRED"):
            release_batch_status(truth, source_commit="latest", release_batch_id=BATCH)
        self.assertEqual(truth.rebuilt, 0)
        self.assertEqual(truth.writes, [])


if __name__ == "__main__":
    unittest.main()
