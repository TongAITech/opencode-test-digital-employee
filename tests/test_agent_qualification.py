import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rc6_release.agent_qualification import run_real_vertical_slice


class RealAgentQualificationFailClosedTests(unittest.TestCase):
    def test_missing_dsh_is_not_proven_and_never_pass(self):
        with tempfile.TemporaryDirectory() as root:
            with mock.patch("rc6_release.agent_qualification._resolve_dsh", return_value=""):
                result = run_real_vertical_slice(home=root, timeout_seconds=1)
            self.assertEqual(result.status, "NOT_PROVEN")
            self.assertIn("ROUTING_INTEGRITY_FAIL", result.reason)
            self.assertNotEqual(result.status, "AGENT_RUNTIME_PASS")
            r1 = Path(root) / "runtime-state" / "r1" / "event-stream.jsonl"
            self.assertTrue(r1.is_file())
            self.assertIn("ROUTING_INTEGRITY_FAIL", r1.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
