import json
import tempfile
import unittest
from pathlib import Path

from rc7_release import startup_trace


class StartupRecoveryTests(unittest.TestCase):
    def test_startup_trace_keeps_model_and_session_unprobed_at_dsh_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            init = startup_trace.init(root)
            self.assertEqual(init["boundary"], "RC7_OWNED_PRESTART")
            startup_trace.mark(root, "PACKAGE_VERIFY", "START")
            startup_trace.mark(root, "PACKAGE_VERIFY", "END")
            status = startup_trace.mark(root, "DSH_HOST_LAUNCH", "START", "RC7_PRESTART_COMPLETE")
            self.assertTrue(status["dsh_host_launched"])
            self.assertEqual(status["boundary"], "DSH_HOST_PROVIDER_SESSION")
            self.assertEqual(status["model_ready"], "NOT_PROBED_BY_RC7")
            self.assertEqual(status["session_ready"], "NOT_PROBED_BY_RC7")
            trace = Path(root) / "state" / "rc71-startup-trace.jsonl"
            rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
            self.assertGreaterEqual(len(rows), 4)

    def test_aitest_launcher_has_phase_trace_and_no_prestart_package_manager_flag(self):
        text = Path("packaging/rc7/AITEST.cmd").read_text(encoding="utf-8")
        for phase in (
            "PACKAGE_VERIFY",
            "PLUGIN_PAYLOAD",
            "DSH_HOST_LOOKUP",
            "RUNTIME_PROFILE",
            "PATCH_GENERATION",
            "POST_BOOTSTRAP_PROBE",
            "DSH_HOST_LAUNCH",
        ):
            self.assertIn(phase, text)
        self.assertIn("Starting DSH now", text)
        self.assertNotIn("--attempt-persistent-install", text)
        self.assertIn("rc71-startup-status.json", text)

    def test_recovery_launcher_preserves_r1_and_uses_isolated_profile(self):
        text = Path("packaging/rc7/AITEST-RECOVER-PROFILE.cmd").read_text(encoding="utf-8")
        self.assertIn("rc7-bank-recovery", text)
        self.assertIn("runtime-state\\r1\\event-stream.jsonl", text)
        self.assertIn("AITEST.cmd", text)
        self.assertNotIn(" del ", " " + text.lower() + " ")
        self.assertNotIn(" rmdir ", " " + text.lower() + " ")


if __name__ == "__main__":
    unittest.main()
