import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_domain import ReleaseBatch
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from tools.dsh_workbench.r1_snapshot_events import (
    R1SnapshotDecodeError, iter_r1_snapshot_events, iter_r1_snapshot_records,
)


class SnapshotEventsTest(unittest.TestCase):
    def test_durable_native_envelopes_match_raw_events_without_collapsing(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "r1.jsonl"
            truth = TruthRuntime(path)
            repository = CanonicalRC72Repository(truth, release_id="runtime-release")
            repository.persist(ReleaseBatch("runtime-batch", "mission", "测试"))
            first = truth.query("rc72_release_batch", release_batch_id="runtime-batch")[0]
            truth.store.append("RC72_RELEASE_BATCH_UPSERTED", first)
            snapshot = path.read_bytes()
            events = list(iter_r1_snapshot_events(snapshot))
            self.assertEqual(events, list(TruthRuntime(path).store.iter_raw()))
            self.assertEqual(len(events), 2)
            self.assertNotEqual(events[0]["event_id"], events[1]["event_id"])
            self.assertEqual(path.read_bytes(), snapshot)

    def test_empty_and_historical_whitespace_finite_numbers(self):
        self.assertEqual(list(iter_r1_snapshot_events(b"")), [])
        raw = b'\r\n {"outer": [1.5e3, 0, "line\\ntext"]}\r\n\t\n'
        self.assertEqual(list(iter_r1_snapshot_events(raw)), [{"outer": [1500.0, 0, "line\ntext"]}])

    def test_malformed_lines_have_stable_one_based_error(self):
        invalid = [
            b'{"payload":0,"payload":1}', b'{"payload":{"k":1,"\\u006b":2}}',
            b'{"x":1e999}', b'{"x":NaN}', b'{"x":-Infinity}', b'{"x":"\\ud800"}',
            b'{"\\udfff":0}', b'{"x":"\xff"}', b'\xef\xbb\xbf{}', b'[]', b'{} {}', b'{',
        ]
        for raw in invalid:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(R1SnapshotDecodeError, "INVALID_LINE_3$"):
                    list(iter_r1_snapshot_events(b"{}\n\n" + raw + b"\n"))

    def test_incomplete_tail_and_non_bytes_are_rejected(self):
        for snapshot in (b"{}", b"{}\n{", b"{}\n "):
            with self.subTest(snapshot=snapshot):
                with self.assertRaisesRegex(R1SnapshotDecodeError, "INCOMPLETE_TAIL$"):
                    next(iter_r1_snapshot_events(snapshot))
        with self.assertRaisesRegex(R1SnapshotDecodeError, "BYTES_REQUIRED$"):
            list(iter_r1_snapshot_events(bytearray(b"{}\n")))

    def test_original_record_bytes_and_line_number_survive_decoding(self):
        first = b'{"name": "\u0061"}\n'
        second = b'{"name":"a"}\r\n'
        source = b"\n" + first + second
        records = list(iter_r1_snapshot_records(source))
        self.assertEqual([record.line_number for record in records], [2, 3])
        self.assertEqual([record.raw_line for record in records], [first, second])
        self.assertEqual([record.event for record in records], [{"name": "a"}, {"name": "a"}])
        self.assertNotEqual(hashlib.sha256(records[0].raw_line[:-1]).digest(),
                            hashlib.sha256(records[1].raw_line[:-1]).digest())
