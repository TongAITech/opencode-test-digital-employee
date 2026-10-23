import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import rc7_runtime  # installs RC7.1 overlays
from rc6_runtime.agent_runtime import AgentRuntimeError
from rc6_runtime.agent_runtime_hardening import BankFinalDshHeadlessWorkerLauncher
from rc6_runtime.authority import AuthorityRuntime
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.model_resilience import (
    PersistentSlidingWindowGovernor,
    _tool_is_read_only,
    classify_failure,
)


class _ScriptedRunner:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.model_calls = 0
        self.session_no = 0

    def __call__(self, command, **_kwargs):
        if "--help" in command:
            return subprocess.CompletedProcess(command, 0, stdout="usage: dsh --profile --patch --dump-config", stderr="")
        if "--dump-config" in command:
            return subprocess.CompletedProcess(command, 0, stdout="serverName: pfc_aitest_rc6\nid: mcp-pfc-aitest-rc6", stderr="")
        self.model_calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else "success"
        self.session_no += 1
        session_id = "session-model-%d" % self.session_no
        if outcome == "502-no-tool":
            stdout = "\n".join([
                json.dumps({"type": "session", "sessionId": session_id}),
                json.dumps({"type": "error", "code": 502, "message": "LLMRequestError 网络波动或模型处理超时; SSE stream ended without [DONE]"}, ensure_ascii=False),
            ])
            return subprocess.CompletedProcess(command, 1, stdout=stdout, stderr="")
        if outcome == "502-after-write":
            stdout = "\n".join([
                json.dumps({"type": "session", "sessionId": session_id}),
                json.dumps({"type": "tool_call", "tool": "mcp__pfc_aitest_rc6__database_update"}),
                json.dumps({"type": "error", "code": 502, "message": "SSE stream ended without [DONE]"}),
            ])
            return subprocess.CompletedProcess(command, 1, stdout=stdout, stderr="")
        stdout = "\n".join([
            json.dumps({"type": "session", "sessionId": session_id}),
            json.dumps({"type": "tool_call", "tool": "mcp__pfc_aitest_rc6__runtime_status"}),
            json.dumps({"type": "final", "text": json.dumps({"ok": True})}),
        ])
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


class ModelResilienceTests(unittest.TestCase):
    def _launcher(self, root, runner):
        dsh = Path(root) / "dsh"
        dsh.write_text("stub", encoding="utf-8")
        patch_path = Path(root) / "rc6.cordis.yml"
        patch_path.write_text("stub", encoding="utf-8")
        truth = TruthRuntime(Path(root) / "r1.jsonl")
        authority = AuthorityRuntime(b"0123456789abcdef-rc71-model")
        launcher = BankFinalDshHeadlessWorkerLauncher(
            dsh_bin=str(dsh),
            patch_path=str(patch_path),
            cwd=root,
            truth=truth,
            authority=authority,
            coordinator_instance_id="coord-model",
            release_id="R-1",
            state_root=root,
            timeout_seconds=5,
            command_runner=runner,
        )
        return launcher, truth

    @staticmethod
    def _assignment(launcher, suffix):
        return launcher.assign(
            agent_id="pfc-requirement-analysis",
            role="REQUIREMENT_ANALYZER",
            phase="REQUIREMENT_ANALYSIS",
            mission_id="M-1",
            attempt_id="attempt-%s" % suffix,
            scope="task:T-%s" % suffix,
            input_refs=("input://1",),
            allowed_artifact_types=("requirement_analysis",),
            allowed_tools=("mcp__pfc_aitest_rc6__runtime_status", "mcp__pfc_aitest_rc6__database_update"),
        )

    def test_governor_enforces_sliding_window(self):
        with tempfile.TemporaryDirectory() as root:
            now = [100.0]
            governor = PersistentSlidingWindowGovernor(
                Path(root),
                max_requests=3,
                window_seconds=10.0,
                now_fn=lambda: now[0],
                sleep_fn=lambda _seconds: None,
            )
            self.assertTrue(governor.reserve().admitted)
            self.assertTrue(governor.reserve().admitted)
            self.assertTrue(governor.reserve().admitted)
            blocked = governor.reserve()
            self.assertFalse(blocked.admitted)
            self.assertGreaterEqual(blocked.wait_seconds, 10.0)
            now[0] = 110.1
            self.assertTrue(governor.reserve().admitted)

    def test_field_failure_strings_are_retryable(self):
        self.assertEqual(classify_failure('SSE stream ended without [DONE]; {"code":502}').category, "SSE_STREAM_CLOSED_BEFORE_DONE")
        self.assertTrue(classify_failure('SSE stream ended without [DONE]; {"code":502}').retryable)
        self.assertEqual(classify_failure("LLMRequestError 网络波动或模型处理超时").category, "PROVIDER_TIMEOUT")
        self.assertEqual(classify_failure("HTTP 429 Too Many Requests").category, "RATE_LIMIT")

    def test_tool_side_effect_classifier_is_token_aware(self):
        self.assertTrue(_tool_is_read_only("mcp__pfc_aitest_rc6__runtime_status"))
        self.assertTrue(_tool_is_read_only("mcp__pfc_aitest_rc7__read_text"))
        self.assertTrue(_tool_is_read_only("mcp__pfc_aitest_rc7__codegraph_query"))
        self.assertFalse(_tool_is_read_only("mcp__pfc_aitest_rc6__database_update"))
        self.assertFalse(_tool_is_read_only("mcp__pfc_aitest_rc6__browser_click"))
        self.assertFalse(_tool_is_read_only("mcp__pfc_aitest_rc6__publish"))

    def test_502_before_tool_side_effect_auto_retries_and_recovers(self):
        with tempfile.TemporaryDirectory() as root:
            runner = _ScriptedRunner(["502-no-tool", "success"])
            launcher, truth = self._launcher(root, runner)
            launcher._rc71_sleep_fn = lambda _seconds: None
            assignment = self._assignment(launcher, "retry")
            env = {
                "PFC_RC71_MODEL_RATE_MAX": "100",
                "PFC_RC71_MODEL_RATE_WINDOW_SECONDS": "600",
                "PFC_RC71_MODEL_TRANSIENT_RETRIES": "2",
                "PFC_RC71_MODEL_RETRY_BACKOFF_SECONDS": "0",
                "PFC_RC71_MODEL_RETRY_BACKOFF_CAP_SECONDS": "0",
            }
            with patch.dict(os.environ, env, clear=False):
                invocation, output = launcher.execute(assignment, "continue task from durable inputs")
            self.assertEqual(runner.model_calls, 2)
            self.assertEqual(invocation.result, "PASS")
            self.assertTrue(output["ok"])
            names = [event["event_type"] for event in truth.store.iter_raw()]
            self.assertIn("MODEL_CALL_FAILED", names)
            self.assertIn("MODEL_RETRY_SCHEDULED", names)
            self.assertIn("MODEL_RETRY_STARTED", names)
            self.assertIn("MODEL_RECOVERED", names)
            self.assertIn("HANDOFF_RETURNED", names)

    def test_rate_window_waits_then_auto_resumes_without_manual_continue(self):
        with tempfile.TemporaryDirectory() as root:
            runner = _ScriptedRunner(["success", "success"])
            launcher, truth = self._launcher(root, runner)
            assignment1 = self._assignment(launcher, "rate-1")
            assignment2 = self._assignment(launcher, "rate-2")
            waits = []
            launcher._rc71_sleep_fn = lambda seconds: (waits.append(seconds), time.sleep(seconds))[1]
            env = {
                "PFC_RC71_MODEL_RATE_MAX": "1",
                "PFC_RC71_MODEL_RATE_WINDOW_SECONDS": "0.1",
                "PFC_RC71_MODEL_TRANSIENT_RETRIES": "0",
            }
            with patch.dict(os.environ, env, clear=False):
                launcher.execute(assignment1, "first")
                launcher.execute(assignment2, "second")
            self.assertEqual(runner.model_calls, 2)
            self.assertTrue(waits)
            names = [event["event_type"] for event in truth.store.iter_raw()]
            self.assertIn("MODEL_RATE_LIMIT_WAIT", names)
            admitted = [event for event in truth.store.iter_raw() if event["event_type"] == "MODEL_REQUEST_ADMITTED"]
            self.assertEqual(len(admitted), 2)

    def test_transient_failure_after_write_is_not_blindly_replayed(self):
        with tempfile.TemporaryDirectory() as root:
            runner = _ScriptedRunner(["502-after-write", "success"])
            launcher, truth = self._launcher(root, runner)
            launcher._rc71_sleep_fn = lambda _seconds: None
            assignment = self._assignment(launcher, "side-effect")
            env = {
                "PFC_RC71_MODEL_RATE_MAX": "100",
                "PFC_RC71_MODEL_TRANSIENT_RETRIES": "3",
                "PFC_RC71_MODEL_RETRY_BACKOFF_SECONDS": "0",
            }
            with patch.dict(os.environ, env, clear=False):
                with self.assertRaises(AgentRuntimeError) as ctx:
                    launcher.execute(assignment, "execute bank task")
            self.assertEqual(str(ctx.exception), "MODEL_RECOVERY_REQUIRED:SIDE_EFFECT_UNCERTAIN")
            self.assertEqual(runner.model_calls, 1)
            blocked = [
                event["payload"] for event in truth.store.iter_raw()
                if event["event_type"] == "MODEL_RECOVERY_BLOCKED_SIDE_EFFECT"
            ]
            self.assertEqual(len(blocked), 1)
            self.assertEqual(blocked[0]["task_id"], "T-side-effect")
            self.assertEqual(blocked[0]["recovery_action"], "MISSION_AUTOPILOT_R1_RESUME_REQUIRED")
            self.assertIn("mcp__pfc_aitest_rc6__database_update", blocked[0]["unsafe_tool_calls"])
            names = [event["event_type"] for event in truth.store.iter_raw()]
            self.assertNotIn("MODEL_RETRY_STARTED", names)


if __name__ == "__main__":
    unittest.main()
