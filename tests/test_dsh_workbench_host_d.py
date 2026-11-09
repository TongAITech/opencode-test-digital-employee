"""WB-D01 executable offline negative contract tests; NOT a bank host test."""
from __future__ import annotations
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "dsh_workbench"))
from wb_d_host_probe import HostProbeError, probe, _origin


class FakeResponse:
    def __init__(self, url, body, status=200, moved=None):
        self.url = moved or url
        self.status = status
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def geturl(self):
        return self.url
    def read(self, length):
        return self.body[:length]


class FakeOpener:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []
    def open(self, request, timeout):
        self.calls.append((request.get_method(), request.full_url,
                           request.get_header("Authorization"), timeout))
        return self.mapping[request.full_url]


class DHostContractTests(unittest.TestCase):
    def setUp(self):
        self.origin = "http://127.0.0.1:4096"
        self.sid = "session_test_001"
        self.status_url = self.origin + "/session/status"
        self.id_url = self.origin + "/session/" + self.sid

    def opener(self, *, status=None, session=None, moved=False):
        data = {
            self.status_url: FakeResponse(
                self.status_url,
                json.dumps(status if status is not None
                           else {self.sid: {"type": "busy"}}).encode(),
                moved=("http://invalid.example/steal" if moved else None)),
            self.id_url: FakeResponse(self.id_url, json.dumps(
                session if session is not None else {"id": self.sid}).encode())
        }
        return FakeOpener(data)

    def test_success_is_read_only_source_schema_not_field_qa(self):
        op = self.opener()
        report = probe(base_url=self.origin, session_id=self.sid, opener=op)
        self.assertEqual(report["session_status"], "SCHEMA_OBSERVED")
        self.assertEqual(report["session_identity"], "MATCH_OBSERVED")
        self.assertFalse(report["field_verified"])
        self.assertFalse(report["bank_final"])
        self.assertEqual(report["teams_active_workers"], "NOT_PROBED")
        self.assertEqual(report["models"], "NOT_PROBED")
        self.assertNotIn(self.sid, json.dumps(report))
        self.assertEqual([c[0] for c in op.calls], ["GET", "GET"])
        self.assertTrue(all(c[2] is None and c[3] == 3 for c in op.calls))

    def test_probe_without_session_id_never_fabricates_session(self):
        op = self.opener()
        report = probe(base_url=self.origin, opener=op)
        self.assertEqual(report["session_identity"], "NOT_PROBED")
        self.assertEqual(len(op.calls), 1)

    def test_non_loopback_and_url_credentials_are_rejected_pre_io(self):
        for url in ("https://127.0.0.1:4096", "http://localhost:4096",
                    "http://example.org:4096", "http://127.0.0.1:4096/command",
                    "http://user:secret@127.0.0.1:4096",
                    "http://127.0.0.1:4096?token=abc",
                    "http://127.0.0.1:4096/#x",
                    "http://127.0.0.1", "file:///tmp/x"):
            with self.subTest(url=url), self.assertRaises(HostProbeError):
                _origin(url)

    def test_session_path_injection_rejected_before_io(self):
        for sid in ("../cmd", "short", "hello/../session", "a" * 129, "a?key=1"):
            with self.subTest(sid=sid), self.assertRaises(HostProbeError):
                probe(base_url=self.origin, session_id=sid, opener=self.opener())

    def test_wrong_session_is_never_a_live_captain(self):
        op = self.opener(session={"id": "foreign-session"})
        report = probe(base_url=self.origin, session_id=self.sid, opener=op)
        self.assertEqual(report["session_identity"], "SESSION_ID_MISMATCH")
        self.assertFalse(report["field_verified"])

    def test_missing_status_is_not_marked_active(self):
        op = self.opener(status={})
        report = probe(base_url=self.origin, session_id=self.sid, opener=op)
        self.assertEqual(report["session_identity"], "STATUS_NOT_OBSERVED")
        self.assertNotIn("PASS", json.dumps(report))

    def test_schema_mismatch_fail_closed(self):
        op = self.opener(status={self.sid: "busy"})
        report = probe(base_url=self.origin, session_id=self.sid, opener=op)
        self.assertEqual(report["session_status"], "SESSION_STATUS_SCHEMA_MISMATCH")
        self.assertEqual(report["session_identity"], "NOT_OBSERVED")
        self.assertEqual(len(op.calls), 1)

    def test_redirect_is_rejected_with_no_follow(self):
        op = self.opener(moved=True)
        report = probe(base_url=self.origin, opener=op)
        self.assertEqual(report["session_status"], "HTTP_NOT_TRUSTED")
        self.assertEqual(len(op.calls), 1)

    def test_oversize_response_rejected(self):
        op = self.opener()
        op.mapping[self.status_url] = FakeResponse(self.status_url, b"x" * 65537)
        report = probe(base_url=self.origin, opener=op)
        self.assertEqual(report["session_status"], "RESPONSE_TOO_LARGE")

    def test_bad_json_rejected(self):
        op = self.opener()
        op.mapping[self.status_url] = FakeResponse(self.status_url, b"{invalid")
        report = probe(base_url=self.origin, opener=op)
        self.assertEqual(report["session_status"], "INVALID_JSON")

    def test_contract_does_not_mutate_agentteams_profile_or_r1(self):
        root = Path(__file__).resolve().parents[1]
        code = (root / "tools/dsh_workbench/wb_d_host_probe.py").read_text(encoding="utf-8")
        self.assertNotIn("method=\"POST\"", code)
        self.assertNotIn("write_text(", code)
        self.assertNotIn("write_bytes(", code)
        self.assertNotIn("Authorization\":", code)

    def test_design_signoff_explicitly_separates_real_qa_and_secret_ownership(self):
        root = Path(__file__).resolve().parents[1]
        doc = (root / "docs/dsh-workbench/WB-D00-DESIGN-SIGNOFF-AND-D01-HOST-DELTA.md").read_text(encoding="utf-8")
        for token in ("DESIGN_SIGNOFF", "1.18.26", "R1", "PROJECT", "BATCH_COMMAND",
                      "WORKER", "NO_DUPLICATE_MODEL_KEYS", "FIELD_QA_NOT_RUN",
                      "ROSTER_32_NOT_CONCURRENCY_32", "A03"):
            with self.subTest(token=token):
                self.assertIn(token, doc)


    def test_source_audit_keeps_host_client_and_bank_qualification_separate(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "docs/dsh-workbench/WB-D01-OPEN-SOURCE-HOST-COMPATIBILITY-OBSERVATIONS.md").read_text(encoding="utf-8")
        for required in ("369c2785c473e546124ab1709664058e6ea93948",
                         "OSS_HOST_CLIENT_SEPARATION", "D-G05", "BANK_1_18_26_UNKNOWN",
                         "FIELD_QA_NOT_RUN", "CAPABILITY_UNKNOWN", "NO_DUPLICATE_MODEL_KEYS"):
            with self.subTest(required=required):
                self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
