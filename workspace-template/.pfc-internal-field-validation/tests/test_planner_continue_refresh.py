"""Explicit menu continuation refreshes canonical inputs without duplicate work.

The external HTTP service is a construction fixture. R1/G3 intake and G2.1
Session provisioning are real; these checks do not claim bank/model validation.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT / "ai-test/runtime"))
from aitest_runtime.autonomous_orchestration import DirectoryScopedOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.recovery_intake import RecoveryIntakeService
from test_g2_1_session_router_control_loop import request


class HTTPFixture(BaseHTTPRequestHandler):
    def log_message(self, *_args): pass
    def respond(self, value, status=200):
        raw = json.dumps(value).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        path = urlparse(self.path).path
        self.server.request_scopes.append(self.headers.get("x-opencode-directory"))
        if path == "/session/status": self.respond(self.server.activity); return
        if path == "/session": self.respond(list(self.server.sessions.values())); return
        self.respond({}, 404)
    def do_POST(self):
        path = urlparse(self.path).path
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self.server.request_scopes.append(self.headers.get("x-opencode-directory"))
        if path == "/session":
            sid = f"planner-{len(self.server.sessions) + 1}"
            value = {"id": sid, "title": body["title"], "directory": self.headers.get("x-opencode-directory")}
            self.server.sessions[sid] = value; self.respond(value); return
        if path.endswith("/prompt_async"):
            sid = path.split("/")[-2]
            self.server.prompts.append({"session_id": sid, "body": body})
            self.respond({"accepted": True}); return
        self.respond({}, 404)


class PlannerContinueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.spine = self.root / "runtime-spine.db"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), HTTPFixture)
        self.server.sessions = {}; self.server.activity = {}; self.server.prompts = []; self.server.request_scopes = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.provider = DirectoryScopedOpenCodeSessionProvider(self.root, base_url=f"http://127.0.0.1:{self.server.server_port}")
        self.service = self.restart()
        started = self.service.start_test(request("planner-continue", "BLOAN1.9.4"))
        self.mission = started["intake"]["intake"]["mission_id"]
        self.session = started["planner_session"]["external_session"]["session_id"]

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.temporary.cleanup()

    def restart(self):
        return G21AutonomousOrchestrationService(create_canonical_runtime(self.root, db_path=self.spine), self.root, session_provider=self.provider)

    def import_menu_document(self, revision):
        path = self.root / "requirement.txt"
        path.write_text("银行需求：同一任务继续，附件正文通过分页读取。" * 3000 + str(revision), encoding="utf-8")
        return RecoveryIntakeService(self.restart().runtime).import_document(self.mission, path, "BLOAN-SST", revision=str(revision))["document"]

    def test_r1_import_then_explicit_continue_wakes_same_planner_with_bounded_fresh_input(self):
        document = self.import_menu_document(1)
        pressure = {"metrics_source": "METADATA_ONLY", "blind_started_at": "2026-09-09T00:00:00Z", "blind_activity_count": 7}
        self.service.session_control.record_observation(self.mission, {"session_id": self.session, "observed_at": "2026-09-09T00:00:00Z", "reachable": True, "healthy": True, "message_count": None, "compaction_count": None, "context_used": None, "context_limit": None, "context_utilization": None, "last_activity_at": None, "provider_state": {"provider": "CONSTRUCTION_HTTP", "pressure": pressure}})
        count = len(self.server.prompts)
        refreshed = self.restart().continue_test(mission_id=self.mission)
        self.assertEqual(refreshed["status"], "PLANNER_CONTEXT_REFRESHED")
        self.assertEqual(refreshed["session_id"], self.session)
        self.assertEqual(len(self.server.sessions), 1)
        self.assertEqual(len(self.server.prompts), count + 1)
        self.assertEqual(self.restart().session_control.state(self.mission).observation(self.session).provider_state["pressure"], pressure)
        prompt = self.server.prompts[-1]
        text = prompt["body"]["parts"][0]["text"]
        context = json.loads(text.split("\n", 1)[1])
        self.assertEqual(context["mission_id"], self.mission)
        self.assertEqual(context["logical_agent_id"], refreshed["logical_agent_id"])
        self.assertEqual(context["durable_input_refs"][-1]["fact_id"], document["fact_id"])
        self.assertEqual(context["durable_input_refs"][-1]["digest"], document["digest"])
        self.assertLessEqual(len(text.encode("utf-8")), 16384)
        self.assertNotIn("银行需求", text)
        self.assertTrue(all(scope == str(self.root.resolve()) for scope in self.server.request_scopes))
        # A normal supervisor observation changes R1 head without changing input
        # semantics. It cannot cause another automatic or explicit duplicate.
        restored = self.restart()
        restored.session_control.record_observation(self.mission, {"session_id": self.session, "observed_at": "2026-09-09T00:00:00Z", "reachable": True, "healthy": True, "message_count": 2, "compaction_count": 0, "context_used": None, "context_limit": None, "context_utilization": None, "last_activity_at": None, "provider_state": {"provider": "CONSTRUCTION_HTTP"}})
        result = self.restart().continue_test(mission_id=self.mission)
        self.assertEqual(result["status"], "ALREADY_REFRESHED")
        self.assertEqual(len(self.server.prompts), count + 1)
        self.assertFalse((self.root / "ai-test/state/aitest.db").exists())

    def test_busy_retry_and_unknown_status_do_not_consume_refresh_or_prompt(self):
        self.import_menu_document(1)
        count = len(self.server.prompts)
        for activity in ({self.session: {"type": "busy"}}, {self.session: {"type": "retry"}}, ["invalid-shape"]):
            self.server.activity = activity
            result = self.restart().continue_test(mission_id=self.mission)
            self.assertEqual(result["status"], "WAIT")
            self.assertFalse(result["prompt_sent"])
            self.assertEqual(len(self.server.prompts), count)
        self.server.activity = {}
        self.assertEqual(self.restart().continue_test(mission_id=self.mission)["status"], "PLANNER_CONTEXT_REFRESHED")
        self.import_menu_document(2)
        self.assertEqual(self.restart().continue_test(mission_id=self.mission)["status"], "PLANNER_CONTEXT_REFRESHED")
        self.assertEqual(len(self.server.prompts), count + 2)

    def test_ambiguous_delivery_claim_survives_restart_without_duplicate_prompt(self):
        self.import_menu_document(1)
        original = self.provider.send_context
        def accepted_then_disconnected(**kwargs):
            original(**kwargs)
            raise OSError("construction transport disconnected after acceptance")
        self.provider.send_context = accepted_then_disconnected
        count = len(self.server.prompts)
        first = self.restart().continue_test(mission_id=self.mission)
        self.assertEqual(first["reason"], "PLANNER_REFRESH_DELIVERY_UNCONFIRMED")
        self.provider.send_context = original
        repeated = self.restart().continue_test(mission_id=self.mission)
        self.assertEqual(repeated["reason"], "PLANNER_REFRESH_DELIVERY_UNCONFIRMED")
        self.assertEqual(len(self.server.prompts), count + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
