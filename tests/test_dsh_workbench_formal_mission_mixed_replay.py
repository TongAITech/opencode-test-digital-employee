"""Replay qualification on isolated native and prospective event snapshots."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rc6_runtime.truth import EVENT_TYPES, ProjectionIntegrityError, TruthRuntime
from rc7_runtime.models import Mission
from rc7_runtime.truth_overlay import append_entity
from test_dsh_workbench_formal_mission_receipt import json_bytes, source_event
from test_truth_layer import make_case, make_intent
from tools.dsh_workbench.formal_mission_event import FORMAL_MISSION_EVENT_TYPE
from tools.dsh_workbench.formal_mission_mixed_replay import (
    FormalMissionReplayHold, replay_formal_mission_snapshot,
)


def lines(*events):
    return b"".join(json_bytes(event) + b"\n" for event in events)


class FormalMissionMixedReplayTest(unittest.TestCase):
    def test_native_and_historical_batch_have_the_same_projection(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "r1.jsonl"
            batch = {"event_type": "TEST_INTENT_UPSERTED", "payload": {"intents": [make_intent(0)]}}
            path.write_bytes(lines(batch))
            append_entity(TruthRuntime(path), Mission("legacy", "legacy-release", "legacy"),
                          release_id="legacy-release")
            original = path.read_bytes()
            expected = TruthRuntime(path).projection.snapshot()
            actual = replay_formal_mission_snapshot(original, "authority").snapshot()
            self.assertEqual(actual, expected)
            self.assertEqual(path.read_bytes(), original)

    def test_mixed_replay_keeps_formal_payload_and_old_reader_rejects(self):
        _, formal = source_event()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "r1.jsonl"
            append_entity(TruthRuntime(path), Mission("legacy", "legacy-release", "legacy"),
                          release_id="legacy-release")
            with path.open("ab") as stream:
                stream.write(lines(formal))
            original = path.read_bytes()
            self.assertNotIn(FORMAL_MISSION_EVENT_TYPE, EVENT_TYPES)
            projection = replay_formal_mission_snapshot(original, "authority")
            self.assertEqual(projection.get("rc7_mission", "mission-1"), formal["payload"])
            self.assertEqual(projection.get("rc7_mission", "legacy")["release_id"], "legacy-release")
            with self.assertRaisesRegex(ProjectionIntegrityError, "UNSUPPORTED_EVENT_TYPE"):
                TruthRuntime(path)
            self.assertNotIn(FORMAL_MISSION_EVENT_TYPE, EVENT_TYPES)
            self.assertEqual(path.read_bytes(), original)

    def test_nan_in_legacy_record_only_holds_formal_qualification(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "r1.jsonl"
            fixture = TruthRuntime(path)
            append_entity(fixture, Mission("legacy", "legacy-release", "legacy"),
                          release_id="legacy-release")
            row = next(fixture.store.iter_raw())
            row["payload"]["historic_unknown_metric"] = float("nan")
            path.write_bytes(lines(row))
            original = path.read_bytes()
            self.assertIsNotNone(TruthRuntime(path).projection.get("rc7_mission", "legacy"))
            with self.assertRaisesRegex(FormalMissionReplayHold, "^FORMAL_MISSION_REPLAY_HOLD$"):
                replay_formal_mission_snapshot(original, "authority")
            self.assertEqual(path.read_bytes(), original)

    def test_legacy_duplicate_ids_or_sequences_cold_replay_but_hold_formal(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "r1.jsonl"
            fixture = TruthRuntime(path)
            fixture.append_atomic("TEST_INTENT_UPSERTED", make_intent(0))
            fixture.append_atomic("TEST_INTENT_UPSERTED", make_intent(1))
            first, second = fixture.store.iter_raw()
            for field in ("seq", "event_id"):
                with self.subTest(field=field):
                    original = lines(first, dict(second, **{field: first[field]}))
                    path.write_bytes(original)
                    self.assertEqual(len(TruthRuntime(path).query("test_intent")), 2)
                    with self.assertRaises(FormalMissionReplayHold):
                        replay_formal_mission_snapshot(original, "authority")
                    self.assertEqual(path.read_bytes(), original)

    def test_legacy_typed_markers_do_not_become_formal_projection(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "r1.jsonl"
            fixture = TruthRuntime(path)
            append_entity(fixture, Mission("legacy", "legacy-release", "legacy"),
                          release_id="legacy-release")
            row = next(fixture.store.iter_raw())
            row["payload"]["runtime_batch_mapping"] = None
            original = lines(row)
            path.write_bytes(original)
            self.assertIsNotNone(TruthRuntime(path).projection.get("rc7_mission", "legacy"))
            with self.assertRaises(FormalMissionReplayHold):
                replay_formal_mission_snapshot(original, "authority")
            self.assertEqual(path.read_bytes(), original)

    def test_raw_typed_markers_cannot_disappear_during_legacy_batch_expansion(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "r1.jsonl"
            for marker in ("scope_binding", "runtime_batch_mapping"):
                for cases in ([], [make_case(1)]):
                    with self.subTest(marker=marker, case_count=len(cases)):
                        row = {
                            "event_type": "RC7_MISSION_UPSERTED", "event_id": "legacy-batch", "seq": 1,
                            "payload": {"mission_id": "legacy", marker: None, "cases": cases},
                        }
                        original = lines(row)
                        path.write_bytes(original)
                        native = TruthRuntime(path)
                        self.assertEqual(native.query("rc7_mission"), [])
                        self.assertEqual(len(native.query("test_case")), len(cases))
                        with self.assertRaises(FormalMissionReplayHold):
                            replay_formal_mission_snapshot(original, "authority")
                        self.assertEqual(path.read_bytes(), original)

    def test_malformed_or_conflicting_trailing_records_never_return_projection(self):
        _, formal = source_event()
        _, foreign = source_event("2", sequence=3, authority="foreign")
        malformed_batch = {"event_type": "TEST_INTENT_UPSERTED", "payload": {"intents": {}}}
        old_collision = {
            "event_type": "RC7_MISSION_UPSERTED", "event_id": "legacy", "seq": 3,
            "payload": dict(formal["payload"], mission_id=" mission-1 ", artifact_version=2),
        }
        for tail in (lines(malformed_batch), lines(foreign), lines(old_collision), lines(formal),
                     b'{"event_type":"A","event_type":"B"}\n', b'{"event_type":'):
            with self.subTest(tail=tail[:60]):
                with self.assertRaises(FormalMissionReplayHold):
                    replay_formal_mission_snapshot(lines(formal) + tail, "authority")
