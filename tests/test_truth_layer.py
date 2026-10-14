import json
import tempfile
import unittest
from pathlib import Path

from rc6_runtime.contracts import DomainValidationError, validate_test_case
from rc6_runtime.truth import ProjectionIntegrityError, TruthRuntime


def make_intent(i, req=None):
    req = req or f"REQ-{i % 3 + 1}"
    return {
        "id": f"INT-{i:02d}",
        "release_id": "BLOAN-PF1.2.0",
        "requirement_id": req,
        "sst_id": f"SST-{i % 4 + 1}",
        "objective": f"intent objective {i}",
        "source_refs": [f"source://req/{req}/{i}"],
        "artifact_version": 1,
    }


def make_condition(i, req=None):
    req = req or f"REQ-{i % 3 + 1}"
    return {
        "id": f"COND-{i:02d}",
        "release_id": "BLOAN-PF1.2.0",
        "requirement_id": req,
        "sst_id": f"SST-{i % 4 + 1}",
        "intent_id": f"INT-{i:02d}",
        "condition": f"condition {i}",
        "risk": "HIGH" if i % 5 == 0 else "MEDIUM",
        "source_refs": [f"source://intent/INT-{i:02d}"],
        "artifact_version": 1,
    }


def make_case(i, req=None, *, version=1, layer=None):
    req = req or f"REQ-{i % 3 + 1}"
    return {
        "tc_id": f"TC-{i:02d}",
        "case_version": version,
        "release_id": "BLOAN-PF1.2.0",
        "requirement_id": req,
        "sst_id": f"SST-{i % 4 + 1}",
        "condition_id": f"COND-{i % 17:02d}",
        "layer": layer or f"L{i % 7 + 1}",
        "objective": f"case objective {i} v{version}",
        "preconditions": ["environment qualified"],
        "test_data": {"key": i},
        "steps": [f"execute action {i}"],
        "expected": f"expected outcome {i}",
        "oracle": {"type": "business", "assert": "expected state"},
        "evidence_requirements": ["actual_result", "tool_call_ref"],
        "status": "CANDIDATE",
    }


class ContractTests(unittest.TestCase):
    def test_mixed_layer_case_is_rejected(self):
        with self.assertRaises(DomainValidationError) as ctx:
            validate_test_case(make_case(1, layer="L2|L3"))
        self.assertEqual(str(ctx.exception), "INVALID_OR_MIXED_CASE_LAYER")

    def test_batch_shape_is_rejected_by_live_contract(self):
        with self.assertRaises(DomainValidationError) as ctx:
            validate_test_case({"cases": [make_case(1)]})
        self.assertEqual(str(ctx.exception), "BATCH_SHAPED_ARTIFACT_FORBIDDEN")


class TruthLayerTests(unittest.TestCase):
    def test_atomic_write_is_queryable_immediately(self):
        with tempfile.TemporaryDirectory() as d:
            rt = TruthRuntime(Path(d) / "r1.jsonl")
            receipt = rt.append_atomic("TEST_CASE_UPSERTED", make_case(1, req="STBB19-320"))
            self.assertEqual(receipt.status, "PERSISTENCE_VERIFIED")
            self.assertEqual(receipt.requested_count, 1)
            self.assertEqual(receipt.persisted_count, 1)
            self.assertEqual(receipt.queryable_count, 1)
            rows = rt.query_cases(release_id="BLOAN-PF1.2.0", requirement_id="STBB19-320")
            self.assertEqual([x["tc_id"] for x in rows], ["TC-01"])

    def test_live_batch_write_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            rt = TruthRuntime(Path(d) / "r1.jsonl")
            with self.assertRaises(Exception) as ctx:
                rt.append_atomic("TEST_CASE_UPSERTED", {"cases": [make_case(1)]})
            self.assertIn("BATCH_SHAPED_ARTIFACT_FORBIDDEN", str(ctx.exception))
            self.assertEqual(rt.inventory()["cases"], 0)

    def test_legacy_rc5_batches_replay_to_17_17_23_without_repair_events(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "r1.jsonl"
            intents = [make_intent(i) for i in range(17)]
            conditions = [make_condition(i) for i in range(17)]
            cases = [make_case(i) for i in range(23)]
            legacy = [
                {"seq": 34, "event_id": "legacy-intents", "event_type": "TEST_INTENT_UPSERTED", "payload": {"intents": intents}},
                {"seq": 35, "event_id": "legacy-conditions", "event_type": "TEST_CONDITION_UPSERTED", "payload": {"conditions": conditions}},
                {"seq": 36, "event_id": "legacy-cases", "event_type": "TEST_CASE_UPSERTED", "payload": {"cases": cases}},
            ]
            original_lines = []
            with path.open("w", encoding="utf-8") as fh:
                for event in legacy:
                    line = json.dumps(event, ensure_ascii=False, sort_keys=True)
                    original_lines.append(line)
                    fh.write(line + "\n")
            rt = TruthRuntime(path)
            self.assertEqual(rt.inventory(), {"intents": 17, "conditions": 17, "cases": 23})
            after_lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(after_lines, original_lines)

    def test_replay_is_deterministic_and_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            rt = TruthRuntime(Path(d) / "r1.jsonl")
            for i in range(3):
                rt.append_atomic("TEST_INTENT_UPSERTED", make_intent(i))
                rt.append_atomic("TEST_CONDITION_UPSERTED", make_condition(i))
                rt.append_atomic("TEST_CASE_UPSERTED", make_case(i))
            snap1 = rt.rebuild_projection()
            snap2 = rt.rebuild_projection()
            snap3 = rt.rebuild_projection()
            self.assertEqual(snap1, snap2)
            self.assertEqual(snap2, snap3)

    def test_same_case_version_conflict_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "r1.jsonl"
            rt = TruthRuntime(path)
            rt.append_atomic("TEST_CASE_UPSERTED", make_case(1))
            raw = make_case(1)
            raw["expected"] = "conflicting expected outcome"
            event = {
                "seq": 99,
                "event_id": "conflict",
                "event_type": "TEST_CASE_UPSERTED",
                "payload": raw,
            }
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            with self.assertRaises(ProjectionIntegrityError) as ctx:
                rt.rebuild_projection()
            self.assertEqual(str(ctx.exception), "CONFLICTING_SAME_ENTITY_VERSION")

    def test_case_v2_supersedes_v1_without_losing_history(self):
        with tempfile.TemporaryDirectory() as d:
            rt = TruthRuntime(Path(d) / "r1.jsonl")
            rt.append_atomic("TEST_CASE_UPSERTED", make_case(7, version=1))
            rt.append_atomic("TEST_CASE_UPSERTED", make_case(7, version=2))
            latest = rt.query_cases(release_id="BLOAN-PF1.2.0")
            row = [x for x in latest if x["tc_id"] == "TC-07"][0]
            self.assertEqual(row["case_version"], 2)
            history = rt.projection.history("test_case", "TC-07")
            self.assertEqual([x["case_version"] for x in history], [1, 2])

    def test_release_requirement_sst_filters_are_top_level_and_stable(self):
        with tempfile.TemporaryDirectory() as d:
            rt = TruthRuntime(Path(d) / "r1.jsonl")
            c1 = make_case(1, req="STBB19-320")
            c1["sst_id"] = "STB915-7489"
            c2 = make_case(2, req="STBB19-322")
            c2["sst_id"] = "STB913-14130"
            rt.append_atomic("TEST_CASE_UPSERTED", c1)
            rt.append_atomic("TEST_CASE_UPSERTED", c2)
            self.assertEqual(len(rt.query_cases(release_id="BLOAN-PF1.2.0")), 2)
            self.assertEqual(len(rt.query_cases(requirement_id="STBB19-320")), 1)
            self.assertEqual(len(rt.query_cases(sst_id="STB915-7489")), 1)


if __name__ == "__main__":
    unittest.main()
