"""Cross-version vectors for pure formal creation and selection encodings."""

import copy
import hashlib
import json
import unittest

from test_dsh_workbench_mission_scope_binding_codec import bound
from test_dsh_workbench_runtime_batch_mapping import descriptor
from tools.dsh_workbench.mission_create_codec import (
    MissionCreateWireError,
    encode_mission_create_request,
    encode_mission_prepare_selection,
)
from tools.dsh_workbench.mission_scope_binding_codec import parse_scope


_GOAL = '测试e\u0301🚀\n\t\b\r\f\x01\u2028\u2029/"\\完成'
_GOAL_JSON = r'测试é🚀\n\t\b\r\f\u0001' + '\u2028\u2029' + r'/\"\\完成'
_REQUEST_VECTOR = (
    '{"command":{"goal":"' + _GOAL_JSON + '"},'
    '"runtime_batch_mapping":{"batch_id":"B1","creation_operation_ref":"op:1","formal_authority_ref":"a1",'
    '"mapping_ref":"map:1","mission_id":"M1","project_id":"P1","runtime_release_batch_id":"RUN-BATCH1",'
    '"runtime_release_id":"RT1","schema_version":1},"schema_version":1,'
    '"scope_binding":{"access_scope_revision":3,"batch_id":"B1","binding_ref":"bind:1",'
    '"creation_key_scope":{"actor_ref":"alice","creation_key":"k1","formal_authority_ref":"a1","project_id":"P1"},'
    '"creation_operation_ref":"op:1","date_revision":9223372036854775807,'
    '"mapping":{"batch_id":"B1","formal_authority_ref":"a1","mapping_policy":"ALLOCATE_NEW_RELEASE_V1",'
    '"mapping_ref":"map:1","project_id":"P1","runtime_release_id":"RT1","schema_version":1},'
    '"mission_id":"M1","project_id":"P1","relation_revision":2,"release_date":"2026-11-11","schema_version":1,'
    '"scope_digest":"0000000000000000000000000000000000000000000000000000000000000000",'
    '"snapshot_ref":"snapshot:1"}}'
).encode("utf-8")
_SELECTION_VECTOR = (
    '{"actor_ref":"alice","batch_id":"B1","command":{"goal":"' + _GOAL_JSON + '"},"creation_key":"k1",'
    '"filters":{"requirement_ids":["é","é","需"],"sst_ids":["🚀"],"version_ids":[]},'
    '"formal_authority_ref":"a1","mapping_policy":"ALLOCATE_NEW_RELEASE_V1","project_id":"P1","schema_version":2}'
).encode("utf-8")


def request():
    binding = bound()["scope_binding"]
    del binding["request_digest"]
    binding["date_revision"] = 9223372036854775807
    return {"schema_version": 1, "command": {"goal": _GOAL}, "scope_binding": binding,
            "runtime_batch_mapping": descriptor()}


def selection():
    return {"schema_version": 2, "formal_authority_ref": "a1", "actor_ref": "alice",
            "project_id": "P1", "creation_key": "k1", "batch_id": "B1",
            "command": {"goal": _GOAL}, "mapping_policy": "ALLOCATE_NEW_RELEASE_V1",
            "filters": {"requirement_ids": ["需", "é", "e\u0301"], "version_ids": [], "sst_ids": ["🚀"]}}


class MissionCreateWireTest(unittest.TestCase):
    def test_fixed_request_and_selection_vectors(self):
        self.assertEqual(encode_mission_create_request(request()), (
            _REQUEST_VECTOR, "70dd4f7c9fc1836ab5086d8ef9d4b8ce3e0d87a31602933a592294661c91f89a",
        ))
        self.assertEqual(encode_mission_prepare_selection(selection()), (
            _SELECTION_VECTOR, "6cc12d22e5b1601c2605dd6c530bdb14875262a2b23b59b29947c250f80ad7c7",
        ))
        binding = dict(request()["scope_binding"], request_digest=encode_mission_create_request(request()).digest)
        envelope = dict(bound(), scope_binding=binding)
        self.assertEqual(parse_scope(envelope).classification, "BOUND_STRUCTURAL_ONLY")

    def test_detached_retry_and_digest_domains(self):
        for make, encode, domain in (
            (request, encode_mission_create_request, b"dsh.mission-create.v1"),
            (selection, encode_mission_prepare_selection, b"dsh.mission-prepare-selection.v2"),
        ):
            value = make()
            copy_of_value = copy.deepcopy(value)
            original = encode(value)
            self.assertEqual(value, copy_of_value)
            self.assertEqual(original, encode(original.canonical_bytes))
            reordered = json.dumps(dict(reversed(list(value.items())))).encode("utf-8")
            self.assertEqual(original, encode(reordered))
            self.assertEqual(original.digest, hashlib.sha256(domain + b"\n" + original.canonical_bytes).hexdigest())
            self.assertNotEqual(original.digest, hashlib.sha256(original.canonical_bytes).hexdigest())
            value["command"]["goal"] = _GOAL.replace("e\u0301", "é")
            self.assertNotEqual(original, encode(value))

    def test_goal_edges_type_and_utf8_length(self):
        edges = (
            "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0\u1680\u2000\u2001\u2002"
            "\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
        )
        bad_goals = ["", "a\0b", "a\udfff", 1, True, "🚀" * 1024 + "x"]
        bad_goals += [goal for edge in edges for goal in (edge + "a", "a" + edge)]
        for make, encode in ((request, encode_mission_create_request),
                             (selection, encode_mission_prepare_selection)):
            for goal in bad_goals:
                with self.subTest(goal=repr(goal)):
                    value = make()
                    value["command"]["goal"] = goal
                    with self.assertRaises(MissionCreateWireError):
                        encode(value)
            for goal in ("🚀" * 1024, "\ufeff边\ufeff", "a" + edges + "b"):
                value = make()
                value["command"]["goal"] = goal
                self.assertEqual(json.loads(encode(value).canonical_bytes)["command"]["goal"], goal)

    def test_exact_fields_and_existing_binding_constraints(self):
        variants = []
        for field in ("batch_id", "runtime_release_id", "formal_authority_ref", "creation_operation_ref"):
            candidate = request()
            candidate["runtime_batch_mapping"][field] = "elsewhere"
            variants.append(candidate)
        for name, value in (("date_revision", True), ("date_revision", 9223372036854775808),
                            ("date_revision", 0), ("release_date", "2026-02-30"),
                            ("request_digest", "0" * 64), ("snapshot_ref", "🚀" * 96 + "x"),
                            ("snapshot_ref", "x\0y"), ("snapshot_ref", "x\ud800")):
            candidate = request()
            candidate["scope_binding"][name] = value
            variants.append(candidate)
        for candidate in variants:
            with self.assertRaises(MissionCreateWireError):
                encode_mission_create_request(candidate)
        for make, encode in ((request, encode_mission_create_request),
                             (selection, encode_mission_prepare_selection)):
            value = make()
            value["command"]["state"] = "REGISTERED"
            with self.assertRaises(MissionCreateWireError):
                encode(value)
            value = make()
            value["schema_version"] = float(value["schema_version"])
            with self.assertRaises(MissionCreateWireError):
                encode(value)

    def test_filters_and_selection_storage_bounds(self):
        candidate = selection()
        reordered = copy.deepcopy(candidate)
        reordered["filters"]["requirement_ids"].reverse()
        self.assertEqual(encode_mission_prepare_selection(candidate),
                         encode_mission_prepare_selection(reordered))
        for invalid in (["same", "same"], ["x\0y"], [3], ["\ud800"], "not-an-array"):
            candidate["filters"]["version_ids"] = invalid
            with self.assertRaises(MissionCreateWireError):
                encode_mission_prepare_selection(candidate)
        candidate = selection()
        candidate["actor_ref"] = "🚀" * 96
        encode_mission_prepare_selection(candidate)
        candidate["actor_ref"] += "x"
        with self.assertRaises(MissionCreateWireError):
            encode_mission_prepare_selection(candidate)

    def test_raw_duplicates_noninteger_bad_utf8_and_malformed_wire(self):
        for wire, encode in ((_REQUEST_VECTOR, encode_mission_create_request),
                             (_SELECTION_VECTOR, encode_mission_prepare_selection)):
            for bad in (wire.replace(b'"goal":', b'"goal":"first","g\\u006fal":'),
                        wire.replace(b'"goal":', b'"goal":null,"goal":'),
                        wire.replace(b'"schema_version":', b'"schema_version":1e1,"extra":'),
                        wire.replace(b'"goal":', b'"extra":NaN,"goal":'),
                        wire.replace(b'"goal":', b'"goal":"\xff","extra":'),
                        b"\xef\xbb\xbf" + wire, wire[:-1], wire + b"{}"):
                with self.subTest(raw=bad[:80]), self.assertRaises(MissionCreateWireError):
                    encode(bad)

    def test_total_size_after_control_escaping(self):
        candidate = selection()
        candidate["filters"]["sst_ids"] = ["a"]
        baseline = len(encode_mission_prepare_selection(candidate).canonical_bytes)
        candidate["filters"]["sst_ids"] = ["a" * (65536 - baseline + 1)]
        wire = encode_mission_prepare_selection(candidate)
        self.assertEqual(len(wire.canonical_bytes), 65536)
        self.assertEqual(encode_mission_prepare_selection(wire.canonical_bytes), wire)
        candidate["filters"]["sst_ids"][0] += "a"
        with self.assertRaisesRegex(MissionCreateWireError, "TOO_LARGE"):
            encode_mission_prepare_selection(candidate)

        candidate = request()
        ref = "x" + "\x01" * 382 + "x"
        binding = candidate["scope_binding"]
        for field in ("binding_ref", "snapshot_ref", "creation_operation_ref", "project_id", "batch_id", "mission_id"):
            binding[field] = ref
        for field in binding["creation_key_scope"]:
            binding["creation_key_scope"][field] = ref
        for field in ("formal_authority_ref", "project_id", "batch_id", "runtime_release_id", "mapping_ref"):
            binding["mapping"][field] = ref
        for field in candidate["runtime_batch_mapping"].keys() - {"schema_version"}:
            candidate["runtime_batch_mapping"][field] = ref
        candidate["command"]["goal"] = "x" + "\x01" * 4094 + "x"
        with self.assertRaisesRegex(MissionCreateWireError, "TOO_LARGE"):
            encode_mission_create_request(candidate)
