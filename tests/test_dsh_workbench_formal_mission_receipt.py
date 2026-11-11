"""Detached receipt recovery tests over exact temporary R1 bytes."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Mission
from rc7_runtime.truth_overlay import append_entity
from tools.dsh_workbench.formal_mission_event import (
    FORMAL_MISSION_EVENT_TYPE, FormalMissionCreationKey, FormalMissionEventError,
)
from tools.dsh_workbench.formal_mission_receipt import (
    FormalMissionReceiptError, lookup_formal_mission_receipt,
)
from tools.dsh_workbench.mission_create_codec import encode_mission_create_request


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def source_event(suffix="1", sequence=2, authority="authority", event_id=None, receipt_ref=None):
    mission = "mission-" + suffix
    key = FormalMissionCreationKey(authority, "actor", "project", "key-" + suffix)
    mapping = {
        "schema_version": 1, "formal_authority_ref": authority, "project_id": key.project_id,
        "batch_id": "pg-batch", "runtime_release_id": "release-" + suffix,
        "mapping_ref": "mapping-" + suffix, "mapping_policy": "ALLOCATE_NEW_RELEASE_V1",
    }
    descriptor = {field: value for field, value in mapping.items() if field != "mapping_policy"}
    descriptor.update(runtime_release_batch_id="runtime-batch-" + suffix, mission_id=mission,
                      creation_operation_ref="operation-" + suffix)
    binding = {
        "schema_version": 1, "mission_id": mission, "project_id": key.project_id,
        "batch_id": "pg-batch", "binding_ref": "binding-" + suffix, "snapshot_ref": "snapshot",
        "scope_digest": "1" * 64, "release_date": "2026-11-12", "date_revision": 1,
        "relation_revision": 2, "access_scope_revision": 3, "creation_key_scope": key._asdict(),
        "mapping": mapping, "creation_operation_ref": descriptor["creation_operation_ref"],
    }
    goal = "验证原回执"
    wire = encode_mission_create_request({
        "schema_version": 1, "command": {"goal": goal}, "scope_binding": binding,
        "runtime_batch_mapping": descriptor,
    })
    binding["request_digest"] = wire.digest
    payload = {
        "artifact_type": "rc7_mission", "artifact_version": 1, "mission_id": mission,
        "release_id": mapping["runtime_release_id"], "goal": goal, "state": "REGISTERED",
        "sufficiency_state": "UNKNOWN", "artifact_refs": [], "open_gap_ids": [],
        "active_task_ids": [], "residual_risk_ids": [], "latest_evaluation_id": None,
        "revision": 1, "created_at": 123, "updated_at": 123, "project_id": key.project_id,
        "batch_id": "pg-batch", "scope_binding": binding, "runtime_batch_mapping": descriptor,
        "receipt_ref": receipt_ref or "receipt-" + suffix,
    }
    return key, {
        "event_type": FORMAL_MISSION_EVENT_TYPE, "event_id": event_id or "event-" + suffix,
        "entity_type": "rc7_mission", "entity_id": mission, "entity_version": 1,
        "seq": sequence, "payload": payload,
    }


class FormalMissionReceiptTest(unittest.TestCase):
    def test_cold_recovery_uses_original_event_and_stable_receipt_bytes(self):
        key, event = source_event()
        event_line = json_bytes(event)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "r1.jsonl"
            append_entity(TruthRuntime(path), Mission("legacy", "legacy-release", "legacy"),
                          release_id="legacy-release")
            with path.open("ab") as stream:
                stream.write(event_line + b"\n")
            snapshot = path.read_bytes()
            first = lookup_formal_mission_receipt(snapshot, key)
            second = lookup_formal_mission_receipt(path.read_bytes(), key)
            self.assertEqual(first, second)
            self.assertEqual(path.read_bytes(), snapshot)
        payload = json.loads(first.canonical_bytes)
        self.assertEqual(payload["event_sha256"], hashlib.sha256(event_line).hexdigest())
        self.assertEqual(payload["receipt_ref"], "receipt-1")
        self.assertEqual(payload["event_ref"], "event-1")
        self.assertEqual(first.receipt_hash, hashlib.sha256(
            b"dsh.mission-create-receipt.v1\n" + first.canonical_bytes).hexdigest())
        missing = key._replace(creation_key="missing")
        self.assertIsNone(lookup_formal_mission_receipt(snapshot, missing))

    def test_conflicts_after_first_match_do_not_return_a_receipt(self):
        key, event = source_event()
        _, duplicate_receipt = source_event("2", sequence=3, receipt_ref="receipt-1")
        _, foreign_authority = source_event("2", sequence=3, authority="foreign")
        _, reused_event_id = source_event("2", sequence=3, event_id="event-1")
        _, reused_sequence = source_event("2", sequence=2)
        legacy_same_id = {"event_type": "OTHER", "event_id": "event-1", "seq": 3}
        legacy_same_sequence = {"event_type": "OTHER", "event_id": "other", "seq": 2}
        legacy_same_mission = {
            "event_type": "RC7_MISSION_UPSERTED", "event_id": "other", "seq": 3,
            "payload": {"mission_id": " mission-1 "},
        }
        for other in (event, duplicate_receipt, foreign_authority, reused_event_id, reused_sequence,
                      legacy_same_id, legacy_same_sequence, legacy_same_mission):
            with self.subTest(other=other.get("event_id")):
                snapshot = json_bytes(event) + b"\n" + json_bytes(other) + b"\n"
                with self.assertRaisesRegex(FormalMissionReceiptError, "CONFLICT"):
                    lookup_formal_mission_receipt(snapshot, key)

    def test_malformed_formal_source_prevents_missing_or_success(self):
        key, event = source_event()
        _, malformed = source_event("2", sequence=3)
        malformed["payload"]["created_at"] = -1
        snapshot = json_bytes(event) + b"\n" + json_bytes(malformed) + b"\n"
        for requested in (key, key._replace(creation_key="missing")):
            with self.assertRaises(FormalMissionEventError):
                lookup_formal_mission_receipt(snapshot, requested)

    def test_valid_unrelated_creation_and_bad_trailing_envelope(self):
        key, event = source_event()
        other_key, other = source_event("2", sequence=3)
        snapshot = json_bytes(event) + b"\n" + json_bytes(other) + b"\n"
        self.assertEqual(lookup_formal_mission_receipt(snapshot, key).event.event_id, "event-1")
        self.assertEqual(lookup_formal_mission_receipt(snapshot, other_key).event.event_id, "event-2")
        with self.assertRaisesRegex(FormalMissionReceiptError, "SOURCE_EVENT_INVALID"):
            lookup_formal_mission_receipt(snapshot + b'{}\n', key)
