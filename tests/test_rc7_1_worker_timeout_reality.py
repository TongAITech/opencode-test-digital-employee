import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import rc7_runtime  # installs RC7.1 timeout diagnostics and model resilience
from rc6_runtime.agent_runtime import AgentRuntimeError
from rc6_runtime.agent_runtime_hardening import BankFinalDshHeadlessWorkerLauncher
from rc6_runtime.authority import AuthorityRuntime
from rc6_runtime.truth import TruthRuntime


class WorkerTimeoutRealityTests(unittest.TestCase):
    @staticmethod
    def _runner(command, **_kwargs):
        if "--help" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="usage: dsh --profile --patch --dump-config",
                stderr="",
            )
        if "--dump-config" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="serverName: pfc_aitest_rc6\nid: mcp-pfc-aitest-rc6",
                stderr="",
            )
        partial = "\n".join(
            [
                json.dumps({"type": "session", "sessionId": "session-timeout-1"}),
                json.dumps({"type": "tool_call", "tool": "mcp__pfc_aitest_rc6__runtime_status"}),
            ]
        )
        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=5,
            output=partial,
            stderr="provider stalled after partial response",
        )

    def test_timeout_persists_partial_output_and_diagnostic_without_hidden_prompt(self):
        with tempfile.TemporaryDirectory() as root:
            dsh = Path(root) / "dsh"
            dsh.write_text("stub", encoding="utf-8")
            patch_path = Path(root) / "rc6.cordis.yml"
            patch_path.write_text("stub", encoding="utf-8")
            truth = TruthRuntime(Path(root) / "r1.jsonl")
            authority = AuthorityRuntime(b"0123456789abcdef-rc71-timeout")
            launcher = BankFinalDshHeadlessWorkerLauncher(
                dsh_bin=str(dsh),
                patch_path=str(patch_path),
                cwd=root,
                truth=truth,
                authority=authority,
                coordinator_instance_id="coord-1",
                release_id="R-1",
                state_root=root,
                timeout_seconds=5,
                command_runner=self._runner,
            )
            launcher._rc71_sleep_fn = lambda _seconds: None
            assignment = launcher.assign(
                agent_id="pfc-requirement-analysis",
                role="REQUIREMENT_ANALYZER",
                phase="REQUIREMENT_ANALYSIS",
                mission_id="M-1",
                attempt_id="attempt-1",
                scope="REQ-1",
                input_refs=("input://1",),
                allowed_artifact_types=("requirement_analysis",),
                allowed_tools=("mcp__pfc_aitest_rc6__runtime_status",),
            )
            secretish_prompt = "analyze with token-like text but do not persist this prompt"
            env = {
                "PFC_RC71_MODEL_TRANSIENT_RETRIES": "0",
                "PFC_RC71_MODEL_RETRY_BACKOFF_SECONDS": "0",
                "PFC_RC71_MODEL_RETRY_BACKOFF_CAP_SECONDS": "0",
            }
            with patch.dict(os.environ, env, clear=False):
                with self.assertRaises(AgentRuntimeError) as ctx:
                    launcher.execute(assignment, secretish_prompt)
            self.assertEqual(str(ctx.exception), "MODEL_TRANSIENT_RETRY_EXHAUSTED:PROVIDER_TIMEOUT")

            events = list(truth.store.iter_raw())
            names = [event["event_type"] for event in events]
            self.assertNotIn("HANDOFF_RETURNED", names)
            completed = [event["payload"] for event in events if event["event_type"] == "WORKER_COMPLETED"]
            self.assertTrue(completed)
            self.assertEqual(completed[-1]["result"], "ROUTING_INTEGRITY_FAIL")
            self.assertIn("MODEL_CALL_FAILED", names)
            self.assertIn("MODEL_RETRY_EXHAUSTED", names)
            self.assertNotIn("MODEL_RETRY_STARTED", names)

            diagnostics = [
                event["payload"]
                for event in events
                if event["event_type"] == "ROUTING_INTEGRITY_FAIL"
                and event["payload"].get("reason") == "DSH_LAUNCH_TIMEOUT_DIAGNOSTIC"
            ]
            self.assertEqual(len(diagnostics), 1)
            diagnostic = diagnostics[0]
            self.assertEqual(diagnostic["partial_dsh_session_id"], "session-timeout-1")
            self.assertFalse(diagnostic["retry_authorized"])

            raw_ref = diagnostic["partial_raw_output_ref"]
            diag_ref = diagnostic["diagnostic_ref"]
            self.assertTrue(raw_ref.startswith("file://"))
            self.assertTrue(diag_ref.startswith("file://"))
            raw_text = Path(raw_ref[len("file://"):]).read_text(encoding="utf-8")
            self.assertIn("session-timeout-1", raw_text)
            self.assertIn("provider stalled", raw_text)

            payload = json.loads(Path(diag_ref[len("file://"):]).read_text(encoding="utf-8"))
            self.assertEqual(payload["failure_type"], "TimeoutExpired")
            self.assertEqual(payload["partial_dsh_session_id"], "session-timeout-1")
            self.assertFalse(payload["prompt_persisted"])
            self.assertFalse(payload["retry_authorized"])
            self.assertNotIn(secretish_prompt, json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
