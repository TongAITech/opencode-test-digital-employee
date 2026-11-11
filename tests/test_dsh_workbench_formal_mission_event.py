"""Exact raw initial-event vectors for the detached formal Mission parser."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rc6_runtime.truth import ProjectionIntegrityError, TruthRuntime
from test_dsh_workbench_mission_create_codec import request
from tools.dsh_workbench.formal_mission_event import (
    FORMAL_MISSION_EVENT_TYPE,
    FormalMissionCreationKey,
    FormalMissionEventError,
    parse_formal_mission_event,
)
from tools.dsh_workbench.mission_create_codec import encode_mission_create_request


def event():
    wire = request()
    payload = {
        "artifact_type": "rc7_mission", "artifact_version": 1,
        "mission_id": "M1", "release_id": "RT1", "goal": wire["command"]["goal"],
        "state": "REGISTERED", "sufficiency_state": "UNKNOWN",
        "artifact_refs": [], "open_gap_ids": [], "active_task_ids": [], "residual_risk_ids": [],
        "latest_evaluation_id": None, "revision": 1, "created_at": 0, "updated_at": 0,
        "project_id": "P1", "batch_id": "B1",
        "scope_binding": dict(wire["scope_binding"], request_digest=encode_mission_create_request(wire).digest),
        "runtime_batch_mapping": wire["runtime_batch_mapping"], "receipt_ref": "receipt:1",
    }
    return {
        "seq": 9223372036854775807, "event_id": "event:1", "event_type": FORMAL_MISSION_EVENT_TYPE,
        "entity_type": "rc7_mission", "entity_id": "M1", "entity_version": 1, "payload": payload,
    }


def line(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def rehash(value):
    payload = value["payload"]
    binding = dict(payload["scope_binding"])
    del binding["request_digest"]
    payload["scope_binding"]["request_digest"] = encode_mission_create_request({
        "schema_version": 1,
        "command": {"goal": payload["goal"]},
        "scope_binding": binding,
        "runtime_batch_mapping": payload["runtime_batch_mapping"],
    }).digest


class FormalMissionEventTest(unittest.TestCase):
    def test_exact_raw_vector_exposes_immutable_facts_and_no_old_registration(self):
        raw = line(event())
        result = parse_formal_mission_event(raw)
        self.assertEqual(result.seq, 9223372036854775807)
        self.assertEqual((result.event_id, result.receipt_ref), ("event:1", "receipt:1"))
        self.assertEqual(result.creation_key, FormalMissionCreationKey("a1", "alice", "P1", "k1"))
        self.assertEqual((result.scope.mission_id, result.scope.release_id), ("M1", "RT1"))
        self.assertEqual(result.mapping.runtime_release_batch_id, "RUN-BATCH1")
        self.assertEqual((result.binding_ref, result.goal, result.created_at),
                         ("bind:1", request()["command"]["goal"], 0))
        self.assertEqual(result.request_digest, "70dd4f7c9fc1836ab5086d8ef9d4b8ce3e0d87a31602933a592294661c91f89a")
        self.assertEqual(result.event_sha256, "d0851b1e8126dda79d35a14358e83b68968c40909d805ec402af00804b1827b6")
        self.assertEqual(result.event_sha256, hashlib.sha256(raw[:-1]).hexdigest())
        self.assertNotEqual(result.event_sha256, hashlib.sha256(raw).hexdigest())
        with self.assertRaises(AttributeError):
            result.seq = 1
        with TemporaryDirectory() as directory:
            path = Path(directory) / "r1.jsonl"
            path.write_bytes(raw)
            with self.assertRaisesRegex(ProjectionIntegrityError, "UNSUPPORTED_EVENT_TYPE"):
                TruthRuntime(path)
            self.assertEqual(path.read_bytes(), raw)

    def test_line_endings_duplicates_and_noncanonical_json(self):
        raw = line(event())
        for bad in (
            bytearray(raw), b"", b"\n", raw[:-1], raw[:-1] + b"\r\n", b"\n" + raw, raw + raw,
            raw.replace(b'"seq":922', b'"seq":1,"seq":922'),
            raw.replace(b'"mission_id":"M1"', b'"mission_id":"M1","mission_\\u0069d":"M1"', 1),
            raw.replace(b'"created_at":0', b'"created_at":NaN'),
            raw.replace(b'"created_at":0', b'"created_at":-0'),
            raw.replace(b'"created_at":0', b'"created_at":0.0'),
            raw.replace(b'"M1"', b'"\\u004d1"'),
            raw.replace(b'"M1"', b'"\\udfff"'),
            b" " + raw, b"\xef\xbb\xbf" + raw, b"\xff" + raw,
        ):
            with self.subTest(raw=repr(bad)[:85]), self.assertRaises(FormalMissionEventError):
                parse_formal_mission_event(bad)

    def test_exact_initial_fields_types_and_domains(self):
        envelope_changes = {
            "seq": [0, -1, True, 9223372036854775808, "1"],
            "entity_version": [True, 1.0, 2],
            "entity_id": ["other"],
            "event_type": ["RC7_MISSION_UPSERTED"],
            "entity_type": ["other"],
            "event_id": ["", " ", "nul\0", "🚀" * 97],
            "unknown": [None],
        }
        payload_changes = {
            "artifact_type": ["other"], "artifact_version": [True, 2], "revision": [True, 2],
            "created_at": [True, -1, 1], "updated_at": [False, 1],
            "goal": [" lead", "nul\0", "🚀" * 1025],
            "state": ["registered", "RUNNING"], "sufficiency_state": ["unknown"],
            "latest_evaluation_id": ["eval"], "receipt_ref": ["", " ", "nul\0", "🚀" * 97],
            "project_id": ["other"], "batch_id": ["RT1"], "release_id": ["M1"],
            "scope_binding": [None, {}], "runtime_batch_mapping": [None, {}],
            "cases": [[]],
        }
        payload_changes.update({key: [None, {}, ["ref"]] for key in
                                ("artifact_refs", "open_gap_ids", "active_task_ids", "residual_risk_ids")})
        for changes, field in ((envelope_changes, None), (payload_changes, "payload")):
            for key, values in changes.items():
                for item in values:
                    value = event()
                    target = value[field] if field else value
                    target[key] = item
                    with self.subTest(key=key, item=repr(item)[:25]), self.assertRaises(FormalMissionEventError):
                        parse_formal_mission_event(line(value))
        for field in ("seq", "payload", "receipt_ref", "latest_evaluation_id", "open_gap_ids"):
            value = event()
            del (value if field in value else value["payload"])[field]
            with self.subTest(field=field), self.assertRaises(FormalMissionEventError):
                parse_formal_mission_event(line(value))

    def test_digest_covers_exact_goal_identity_and_operation(self):
        for field in ("goal", "request_digest", "operation", "mapping"):
            value = event()
            payload = value["payload"]
            binding = payload["scope_binding"]
            if field == "goal":
                payload["goal"] += " changed"
            elif field == "request_digest":
                binding["request_digest"] = "1" * 64
            elif field == "operation":
                binding["creation_operation_ref"] = payload["runtime_batch_mapping"]["creation_operation_ref"] = "op:2"
            else:
                payload["runtime_batch_mapping"]["runtime_release_batch_id"] = "RUN-BATCH2"
            with self.subTest(field=field), self.assertRaisesRegex(FormalMissionEventError, "DIGEST_MISMATCH"):
                parse_formal_mission_event(line(value))

    def test_allocator_ids_cannot_change_through_legacy_normalization(self):
        for field in ("mission_id", "runtime_release_id", "runtime_release_batch_id"):
            value = event()
            payload = value["payload"]
            binding = payload["scope_binding"]
            mapping = payload["runtime_batch_mapping"]
            mapping[field] += "\u00a0"
            if field == "mission_id":
                value["entity_id"] = payload[field] = binding[field] = mapping[field]
            elif field == "runtime_release_id":
                payload["release_id"] = binding["mapping"][field] = mapping[field]
            rehash(value)
            with self.subTest(field=field), self.assertRaises(FormalMissionEventError):
                parse_formal_mission_event(line(value))
