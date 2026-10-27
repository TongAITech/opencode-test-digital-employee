from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rc8_center.n7_execution_result import N7CaseExecutionOutcome, N7CaseExecutionResult
from rc8_center.n7_execution_result_receipt import (
    CenterN7CaseExecutionResultReceiptAuthority,
    DERIVED_RESULT_AUTHORITY,
    DERIVED_RESULT_EVENT_TYPE,
    DERIVED_RESULT_PRODUCER_REF,
    N7CaseExecutionResultReceiptError,
)
from rc8_runtime import RuntimeProducerKind
from rc8_runtime.r1_runtime import CentralR1RuntimeLedger, runtime_event


class N7ExecutionResultReceiptTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = CentralR1RuntimeLedger(str(Path(self.temp.name) / "event-stream.jsonl"))
        self.authority = CenterN7CaseExecutionResultReceiptAuthority(self.ledger, now_fn=lambda: 123)
        self.result = N7CaseExecutionResult(
            outcome=N7CaseExecutionOutcome.PASS,
            test_run_id="run-1",
            work_item_id="work-1",
            case_id="case-1",
            case_execution_attempt_id="attempt-2",
            prepared_attempt_id="prepared-2",
            executable_spec_id="spec-2",
            assertion_refs=("assertion:a", "assertion:b"),
            resolved_assertion_refs=("assertion:a", "assertion:b"),
            evidence_refs=("ev-a", "ev-b"),
            reason="ALL_REQUIRED_ASSERTIONS_VERIFIED_PASS",
        )

    def test_terminal_result_is_persisted_and_replayed_from_r1(self):
        persisted = self.authority.record(self.result, node_id="node-1")
        self.assertEqual(self.result, persisted)
        replayed = self.authority.read_for_work_item("work-1")
        self.assertEqual(self.result, replayed)
        events = self.ledger.runtime_events(test_run_id="run-1", work_item_id="work-1")
        receipt = [item for item in events if item["event_type"] == DERIVED_RESULT_EVENT_TYPE]
        self.assertEqual(1, len(receipt))
        self.assertEqual(DERIVED_RESULT_PRODUCER_REF, receipt[0]["producer_ref"])
        self.assertEqual(RuntimeProducerKind.NODE_AGENT.value, receipt[0]["producer_kind"])
        self.assertEqual(DERIVED_RESULT_AUTHORITY, receipt[0]["data"]["authority"])
        self.assertEqual(["artifact:ev-a", "artifact:ev-b"], receipt[0]["refs"])

    def test_record_is_idempotent(self):
        first = self.authority.record(self.result, node_id="node-1")
        second = self.authority.record(self.result, node_id="node-1")
        self.assertEqual(first, second)
        events = [
            item for item in self.ledger.runtime_events(work_item_id="work-1")
            if item["event_type"] == DERIVED_RESULT_EVENT_TYPE
        ]
        self.assertEqual(1, len(events))

    def test_pending_result_cannot_be_persisted(self):
        pending = N7CaseExecutionResult(
            outcome=N7CaseExecutionOutcome.PENDING,
            test_run_id="run-1",
            work_item_id="work-1",
            case_id="case-1",
            case_execution_attempt_id="attempt-2",
            prepared_attempt_id="prepared-2",
            executable_spec_id="spec-2",
            assertion_refs=("assertion:a",),
            resolved_assertion_refs=(),
            evidence_refs=(),
            reason="ASSERTION_EVIDENCE_PENDING",
        )
        with self.assertRaisesRegex(N7CaseExecutionResultReceiptError, "TERMINAL_OUTCOME"):
            self.authority.record(pending, node_id="node-1")

    def test_spoofed_receipt_identity_is_not_accepted(self):
        spoof = runtime_event(
            event_id="worker-spoof",
            test_run_id="run-1",
            work_item_id="work-1",
            node_id="node-1",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref=DERIVED_RESULT_PRODUCER_REF,
            event_type=DERIVED_RESULT_EVENT_TYPE,
            sequence=1,
            case_id="case-1",
            attempt_id="attempt-2",
            refs=["artifact:ev-a"],
            data={
                "authority": DERIVED_RESULT_AUTHORITY,
                "outcome": "PASS",
                "prepared_attempt_id": "prepared-2",
                "executable_spec_id": "spec-2",
                "assertion_refs": ["assertion:a"],
                "resolved_assertion_refs": ["assertion:a"],
                "evidence_refs": ["ev-a"],
                "reason": "FAKE",
            },
            occurred_at=1,
        )
        self.ledger.append_runtime(spoof)
        with self.assertRaisesRegex(N7CaseExecutionResultReceiptError, "PRODUCER_KIND_INVALID"):
            self.authority.read_for_work_item("work-1")


if __name__ == "__main__":
    unittest.main()
