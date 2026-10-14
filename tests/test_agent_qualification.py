import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rc6_release.agent_qualification import run_real_vertical_slice


TOOL = "mcp__pfc_aitest_rc6__runtime_status"


def analysis_payload(*, repaired: bool):
    return {
        "br": [{"id": "BR-1"}],
        "sr": [{"id": "SR-1"}],
        "tr": [{"id": "TR-1"}],
        "source_assertions": [{"id": "SRC-1", "text": "amount upper bound", "source_ref": "source://QUAL-REQ-BOUNDARY-001"}],
        "atomic_statements": [{"id": "A-1", "text": "500000.00 allowed and 500000.01 rejected", "source_ref": "source://QUAL-REQ-BOUNDARY-001", "testable": True}],
        "trace_links": [{"source_id": "SRC-1", "atomic_id": "A-1", "evidence_ref": "source://QUAL-REQ-BOUNDARY-001"}],
        "evidence_refs": ["source://QUAL-REQ-BOUNDARY-001"],
        "business_rules": [{"id": "BR-AMOUNT"}],
        "roles": [{"id": "ROLE-USER"}],
        "preconditions": [{"id": "PRE-1"}],
        "normal_paths": [{"id": "PATH-NORMAL"}],
        "negative_paths": [{"id": "PATH-REJECT"}],
        "boundaries": ([{"included": "500000.00", "rejected": "500000.01"}] if repaired else []),
        "states": [{"id": "STATE-1"}],
        "data_constraints": [{"id": "DATA-1"}],
        "dependencies": [{"id": "DEP-1"}],
        "side_effects": [{"id": "EFFECT-1"}],
        "known_omission": None if repaired else "missing_boundary_rule",
    }


def review_payload(*, passed: bool):
    return {
        "decision": "PASS" if passed else "GAPS",
        "gap_ids": [] if passed else ["missing_boundary_rule"],
        "evidence_refs": ["review://real-dsh-sufficiency"],
        "summary": "sufficient" if passed else "boundary rule missing",
    }


def dsh_record(session_id, payload):
    stdout = "\n".join([
        json.dumps({"type": "session", "sessionId": session_id}),
        json.dumps({"type": "tool_call", "callId": "call-1", "tool": TOOL, "input": {}}),
        json.dumps({"type": "tool_result", "callId": "call-1", "tool": TOOL, "output": {"status": "ok"}}),
        json.dumps({"type": "final", "text": json.dumps({"qualification_payload": payload})}),
    ])
    return subprocess.CompletedProcess(["dsh"], 0, stdout=stdout, stderr="")


class RealAgentQualificationFailClosedTests(unittest.TestCase):
    def test_missing_dsh_is_not_proven_and_never_pass(self):
        with tempfile.TemporaryDirectory() as root:
            with mock.patch(
                "rc6_release.agent_qualification_runtime._resolve_dsh",
                return_value="",
            ):
                result = run_real_vertical_slice(home=root, timeout_seconds=1)
            self.assertEqual(result.status, "NOT_PROVEN")
            self.assertIn("ROUTING_INTEGRITY_FAIL", result.reason)
            self.assertNotEqual(result.status, "AGENT_RUNTIME_PASS")
            r1 = Path(root) / "runtime-state" / "r1" / "event-stream.jsonl"
            self.assertTrue(r1.is_file())
            self.assertIn("ROUTING_INTEGRITY_FAIL", r1.read_text(encoding="utf-8"))

    def test_full_vertical_slice_wiring_reaches_pass_with_four_fresh_dsh_sessions(self):
        with tempfile.TemporaryDirectory() as root:
            dsh = Path(root) / "dsh"
            dsh.write_text("stub", encoding="utf-8")
            records = [
                dsh_record("session-analysis-1", analysis_payload(repaired=False)),
                dsh_record("session-review-1", review_payload(passed=False)),
                dsh_record("session-analysis-2", analysis_payload(repaired=True)),
                dsh_record("session-review-2", review_payload(passed=True)),
            ]

            def fake_run(command, **kwargs):
                self.assertTrue(records, "unexpected fifth DSH worker invocation")
                return records.pop(0)

            with mock.patch("rc6_runtime.agent_runtime.subprocess.run", side_effect=fake_run):
                result = run_real_vertical_slice(
                    home=root,
                    dsh_bin=str(dsh),
                    coordinator_instance_id="coord-integration",
                    timeout_seconds=1,
                )

            self.assertEqual(result.status, "AGENT_RUNTIME_PASS", result.reason)
            self.assertEqual(result.first_gate_status, "NOT_SUFFICIENT_CONTENT")
            self.assertEqual(result.second_gate_status, "SUFFICIENT")
            self.assertEqual(len(result.worker_instance_ids), 4)
            self.assertEqual(len(set(result.worker_instance_ids)), 4)
            self.assertEqual(len(result.dsh_session_ids), 4)
            self.assertEqual(len(set(result.dsh_session_ids)), 4)
            self.assertFalse(records)

            r1 = Path(root) / "runtime-state" / "r1" / "event-stream.jsonl"
            text = r1.read_text(encoding="utf-8")
            for event_name in (
                "SUFFICIENCY_GAP_FOUND",
                "REPAIR_REQUESTED",
                "WORKER_REASSIGNED",
                "SUFFICIENCY_REEVALUATED",
                "SUFFICIENCY_PASSED",
            ):
                self.assertIn(event_name, text)


if __name__ == "__main__":
    unittest.main()
