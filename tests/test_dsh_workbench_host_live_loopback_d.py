"""WB-D01 transport-level smoke against a local disposable HTTP fixture.

This is a REAL loopback socket and HTTP client, not a FakeOpener.
It is NOT a bank DSH instance or evidence of installed 1.18.26 API compatibility.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "dsh_workbench"))
from wb_d_host_probe import probe


SESSION = "session_smoke_001"


class FixtureHandler(BaseHTTPRequestHandler):
    mode = "normal"
    requests = []

    def do_GET(self):
        type(self).requests.append(("GET", self.path))
        if type(self).mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "https://outside.invalid/capture")
            self.end_headers()
            return
        if self.path == "/session/status":
            if type(self).mode == "large":
                body = b"{" + b" " * 65537 + b"}"
            elif type(self).mode == "bad_status":
                body = json.dumps({SESSION: "busy"}).encode("utf-8")
            else:
                body = json.dumps({SESSION: {"type": "busy"}}).encode("utf-8")
        elif self.path == "/session/" + SESSION:
            body = json.dumps({
                "id": ("other_session_001" if type(self).mode == "foreign" else SESSION),
                "systemPrompt": "SECRET_MUST_NOT_BE_EMITTED",
                "messages": [{"content": "SECRET_MESSAGE"}],
            }).encode("utf-8")
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        type(self).requests.append(("POST", self.path))
        self.send_error(405)

    def log_message(self, format, *args):
        pass


class TestD01ActualLoopbackTransport(unittest.TestCase):
    def setUp(self):
        FixtureHandler.requests = []
        FixtureHandler.mode = "normal"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = "http://127.0.0.1:%d" % self.server.server_port

    def test_actual_socket_reads_only_session_and_status_and_redacts_payload(self):
        result = probe(base_url=self.origin, session_id=SESSION)
        self.assertEqual(result["session_status"], "SCHEMA_OBSERVED")
        self.assertEqual(result["session_identity"], "MATCH_OBSERVED")
        self.assertEqual(FixtureHandler.requests, [
            ("GET", "/session/status"), ("GET", "/session/" + SESSION),
        ])
        self.assertFalse(result["field_verified"])
        self.assertFalse(result["bank_final"])
        self.assertNotIn("SECRET_MUST_NOT_BE_EMITTED", json.dumps(result))
        self.assertNotIn("SECRET_MESSAGE", json.dumps(result))
        self.assertNotIn(SESSION, json.dumps(result))

    def test_wrong_session_id_fails_closed_without_local_user_data(self):
        FixtureHandler.mode = "foreign"
        result = probe(base_url=self.origin, session_id=SESSION)
        self.assertEqual(result["session_identity"], "SESSION_ID_MISMATCH")
        self.assertFalse(result["field_verified"])
        self.assertEqual(len(FixtureHandler.requests), 2)

    def test_live_redirect_not_followed_and_no_token_leak(self):
        FixtureHandler.mode = "redirect"
        result = probe(base_url=self.origin, session_id=SESSION)
        self.assertEqual(result["session_status"], "GET_UNAVAILABLE")
        self.assertEqual(FixtureHandler.requests, [("GET", "/session/status")])
        self.assertFalse(result["bank_final"])

    def test_live_oversize_status_does_not_continue_to_session(self):
        FixtureHandler.mode = "large"
        result = probe(base_url=self.origin, session_id=SESSION)
        self.assertEqual(result["session_status"], "RESPONSE_TOO_LARGE")
        self.assertEqual(FixtureHandler.requests, [("GET", "/session/status")])

    def test_live_wrong_schema_does_not_probe_more_endpoints(self):
        FixtureHandler.mode = "bad_status"
        result = probe(base_url=self.origin, session_id=SESSION)
        self.assertEqual(result["session_status"], "SESSION_STATUS_SCHEMA_MISMATCH")
        self.assertEqual(FixtureHandler.requests, [("GET", "/session/status")])


if __name__ == "__main__":
    unittest.main()
