import json
import os
import subprocess
import sys
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
        if outcome == "429-no-tool":
            stdout = "\n".join([
                json.dumps({"type": "session", "sessionId": session_id}),
                json.dumps({"type": "error", "code": 429, "message": "LLMRequestError HTTP 429 rate limit"}),
            ])
            return subprocess.CompletedProcess(command, 1, stdout=stdout, stderr="")
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

    def test_r4_corrupt_shared_rate_ledger_never_resets_to_empty(self):
        with tempfile.TemporaryDirectory() as root:
            governor = PersistentSlidingWindowGovernor(
                Path(root), max_requests=1, window_seconds=600.0)
            state_path = governor.state_path
            bad_states = (
                "{",
                "[]",
                "{}",
                '{"schema":"wrong","timestamps":[]}',
                '{"schema":"rc7.1-model-rate-window-v1","timestamps":null}',
                '{"schema":"rc7.1-model-rate-window-v1","timestamps":[null]}',
                '{"schema":"rc7.1-model-rate-window-v1","timestamps":["bad"]}',
                '{"schema":"rc7.1-model-rate-window-v1","timestamps":[NaN]}',
                '{"schema":"rc7.1-model-rate-window-v1","timestamps":[-1]}',
                '{"schema":"rc7.1-model-rate-window-v1","timestamps":[true]}',
            )
            for raw in bad_states:
                state_path.write_text(raw, encoding="utf-8")
                original = state_path.read_bytes()
                with self.assertRaisesRegex(
                        AgentRuntimeError, "MODEL_RATE_GOVERNOR_STATE_UNVERIFIED"):
                    governor.reserve()
                self.assertEqual(state_path.read_bytes(), original)
                # The OS-advisory lock file persists after unlock. It is never
                # removed in a way that can undermine another process's lock.
                self.assertTrue(governor.lock_path.is_file())
                governor._lock()
                governor._unlock()
            # A valid owned snapshot remains usable; recovery is explicit.
            state_path.write_text(json.dumps({
                "schema": "rc7.1-model-rate-window-v1",
                "timestamps": [],
            }), encoding="utf-8")
            self.assertTrue(governor.reserve().admitted)
            self.assertFalse(governor.reserve().admitted)

    def test_r4_predictable_governor_temp_symlink_cannot_overwrite_other_file(self):
        with tempfile.TemporaryDirectory() as root:
            governor = PersistentSlidingWindowGovernor(
                Path(root), max_requests=1, window_seconds=600.0)
            protected = Path(root) / "protected-bank-file.txt"
            protected.write_text("ORIGINAL BANK DATA", encoding="utf-8")
            legacy_temp = governor.state_path.with_suffix(".tmp")
            try:
                legacy_temp.symlink_to(protected)
            except (OSError, NotImplementedError):
                self.skipTest("Platform does not permit creation of test symlinks")
            self.assertTrue(governor.reserve().admitted)
            self.assertEqual(protected.read_text(encoding="utf-8"), "ORIGINAL BANK DATA")
            self.assertTrue(legacy_temp.is_symlink())
            self.assertFalse(governor.state_path.is_symlink())
            self.assertFalse(governor.reserve().admitted)

    def test_r4_governor_atomic_write_leaves_legacy_temp_untouched(self):
        with tempfile.TemporaryDirectory() as root:
            governor = PersistentSlidingWindowGovernor(
                Path(root), max_requests=1, window_seconds=600.0)
            legacy_temp = governor.state_path.with_suffix(".tmp")
            legacy_temp.write_text("stale crash remnant", encoding="utf-8")
            self.assertTrue(governor.reserve().admitted)
            self.assertEqual(legacy_temp.read_text(encoding="utf-8"),
                             "stale crash remnant")
            self.assertFalse(governor.reserve().admitted)
            self.assertFalse(any(governor.state_path.parent.glob(
                ".shared-window-*.tmp")))

    def test_r4_active_bank_quota_lock_cannot_be_stolen_after_30_seconds(self):
        with tempfile.TemporaryDirectory() as root:
            first = PersistentSlidingWindowGovernor(
                Path(root), max_requests=1, window_seconds=600.0)
            second = PersistentSlidingWindowGovernor(
                Path(root), max_requests=1, window_seconds=600.0,
                lock_timeout_seconds=0.05)
            first._lock()
            try:
                stale = time.time() - 3600
                os.utime(str(first.lock_path), (stale, stale))
                with self.assertRaisesRegex(
                        AgentRuntimeError, "MODEL_RATE_GOVERNOR_LOCK_TIMEOUT"):
                    second.reserve()
                self.assertTrue(first.lock_path.is_file())
                self.assertIsNotNone(first._lock_fd)
            finally:
                first._unlock()
            self.assertTrue(second.reserve().admitted)
            self.assertFalse(first.reserve().admitted)

    def test_r4_legacy_orphan_marker_can_recover_without_resetting_model_quota(self):
        with tempfile.TemporaryDirectory() as root:
            now = time.time()
            governor = PersistentSlidingWindowGovernor(
                Path(root), max_requests=1, window_seconds=600.0,
                now_fn=lambda: now)
            governor.state_path.write_text(json.dumps({
                "schema": "rc7.1-model-rate-window-v1",
                "timestamps": [now],
            }), encoding="utf-8")
            governor.lock_path.write_text("dead-legacy-process-marker",
                                          encoding="utf-8")
            stale = now - 3600
            os.utime(str(governor.lock_path), (stale, stale))
            # A filesystem marker left by a crashed process does not own a
            # kernel lock. Recovery must preserve the one already-used slot.
            blocked = governor.reserve()
            self.assertFalse(blocked.admitted)
            self.assertEqual(blocked.request_count, 1)
            self.assertTrue(governor.lock_path.is_file())
            self.assertFalse(governor.reserve().admitted)

    def test_r4_os_quota_lock_releases_on_abrupt_worker_process_exit(self):
        with tempfile.TemporaryDirectory() as root:
            script = (
                "import os,sys;"
                "from pathlib import Path;"
                "from rc7_runtime.model_resilience import PersistentSlidingWindowGovernor;"
                "g=PersistentSlidingWindowGovernor(Path(sys.argv[1]));"
                "g._lock();"
                "os._exit(0)"
            )
            result = subprocess.run(
                [sys.executable, "-c", script, root],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=20, check=False)
            self.assertEqual(result.returncode, 0, result.stderr.decode(
                "utf-8", errors="replace"))
            # The process never called _unlock. The OS nevertheless releases
            # its lock and cold restart can re-acquire it.
            governor = PersistentSlidingWindowGovernor(Path(root))
            self.assertTrue(governor.reserve().admitted)
            self.assertTrue(governor.lock_path.is_file())

    def test_r4_corrupt_rate_ledger_blocks_actual_launcher_before_model_io(self):
        with tempfile.TemporaryDirectory() as root:
            runner = _ScriptedRunner(["success"])
            launcher, truth = self._launcher(root, runner)
            assignment = self._assignment(launcher, "corrupt-rate-ledger")
            state_path = Path(root) / "model-governor" / "shared-window.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text("{interrupted-write", encoding="utf-8")
            with self.assertRaisesRegex(
                    AgentRuntimeError, "MODEL_RATE_GOVERNOR_STATE_UNVERIFIED"):
                launcher.execute(assignment, "must not start a model")
            self.assertEqual(runner.model_calls, 0)
            self.assertEqual(state_path.read_text(encoding="utf-8"),
                             "{interrupted-write")
            self.assertFalse(any(
                row.get("event_name") == "WORKER_STARTED"
                for row in truth.query("agent_runtime_event",
                                       assignment_id=assignment.assignment_id)))

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

    def test_502_before_visible_tool_receipt_still_requires_r1_reconciliation(self):
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
                with self.assertRaises(AgentRuntimeError):
                    launcher.execute(assignment, "continue task from durable inputs")
            self.assertEqual(runner.model_calls, 1)
            names = [event["event_type"] for event in truth.store.iter_raw()]
            self.assertIn("MODEL_CALL_FAILED", names)
            self.assertIn("MODEL_RECOVERY_BLOCKED_SIDE_EFFECT", names)
            self.assertNotIn("MODEL_RETRY_STARTED", names)
            self.assertNotIn("MODEL_RECOVERED", names)
            self.assertNotIn("HANDOFF_RETURNED", names)
            blocked = [event["payload"] for event in truth.store.iter_raw()
                if event["event_type"] == "MODEL_RECOVERY_BLOCKED_SIDE_EFFECT"]
            self.assertEqual(blocked[0]["reason"], "R1_WORKER_STARTED_UNKNOWN_EFFECT")
            self.assertEqual(blocked[0]["recovery_action"], "MISSION_AUTOPILOT_R1_RESUME_REQUIRED")

    def test_r4_429_after_worker_started_never_blindly_relaunches(self):
        with tempfile.TemporaryDirectory() as root:
            runner = _ScriptedRunner(["429-no-tool", "success"])
            launcher, truth = self._launcher(root, runner)
            launcher._rc71_sleep_fn = lambda _seconds: None
            assignment = self._assignment(launcher, "r4-429-reentry")
            with patch.dict(os.environ, {
                "PFC_RC71_MODEL_RATE_MAX": "100",
                "PFC_RC71_MODEL_TRANSIENT_RETRIES": "3",
                "PFC_RC71_MODEL_RETRY_BACKOFF_SECONDS": "0",
            }, clear=False):
                with self.assertRaises(AgentRuntimeError):
                    launcher.execute(assignment, "no repeated side effect")
            self.assertEqual(runner.model_calls, 1)
            records = [e["payload"] for e in truth.store.iter_raw()
                       if e["event_type"] == "MODEL_RECOVERY_BLOCKED_SIDE_EFFECT"]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["failure_category"], "RATE_LIMIT")
            self.assertEqual(records[0]["reason"], "R1_WORKER_STARTED_UNKNOWN_EFFECT")
            self.assertEqual(records[0]["recovery_action"],
                             "MISSION_AUTOPILOT_R1_RESUME_REQUIRED")
            self.assertFalse(any(
                e["event_type"] == "MODEL_RETRY_STARTED"
                for e in truth.store.iter_raw()))

    def test_rate_window_waits_then_auto_resumes_without_manual_continue(self):
        with tempfile.TemporaryDirectory() as root:
            runner = _ScriptedRunner(["success", "success"])
            launcher, truth = self._launcher(root, runner)
            assignment1 = self._assignment(launcher, "rate-1")
            assignment2 = self._assignment(launcher, "rate-2")
            waits = []

            # This is an integration check for the launcher's automatic resume,
            # not a wall-clock performance benchmark.  The former 0.1s window
            # was platform-speed dependent: on a slower Windows runner the first
            # fixture call could consume the whole window, so no wait was
            # correctly required and the test failed spuriously.  Keep a long
            # deterministic window, then fast-forward the persisted timestamps
            # when the injected sleeper is invoked.
            def fast_forward_window(seconds):
                waits.append(seconds)
                state_path = Path(root) / "model-governor" / "shared-window.json"
                state = json.loads(state_path.read_text(encoding="utf-8"))
                state["timestamps"] = [float(value) - float(seconds) - 1.0 for value in state.get("timestamps", [])]
                state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

            launcher._rc71_sleep_fn = fast_forward_window
            env = {
                "PFC_RC71_MODEL_RATE_MAX": "1",
                "PFC_RC71_MODEL_RATE_WINDOW_SECONDS": "60",
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