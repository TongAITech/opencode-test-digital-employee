"""CI scheduling contract: reduce redundant queued work without falsifying results.

These checks deliberately use only the Python standard library. They do not
claim GitHub runner availability or replace exact-source qualification.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = {
    "rc7.2-construction.yml": "rc72-construction-${{ github.ref }}",
    "rc7.2-portable-transport.yml": "rc72-portable-${{ github.ref }}",
    "rc7.2-windows-clean-unpack.yml": "rc72-windows-unpack-${{ github.ref }}",
    "rc7-field-hardening.yml":
        "rc7-field-hardening-${{ github.event.pull_request.number || github.ref }}",
}


class CIQueueAdmissionContract(unittest.TestCase):
    def test_expensive_workflows_keep_running_verdicts_and_deduplicate_pending(self):
        for filename, group in WORKFLOWS.items():
            with self.subTest(filename=filename):
                path = ROOT / ".github" / "workflows" / filename
                content = path.read_text(encoding="utf-8")
                self.assertEqual(content.count("\nconcurrency:\n"), 1)
                self.assertIn("\n  group: " + group + "\n", content)
                self.assertIn("\n  cancel-in-progress: false\n", content)
                # No workflow is allowed to shrink its existing validation
                # steps to "solve" a runner backlog.
                self.assertIn("\njobs:\n", content)
                self.assertIn("actions/checkout@v4", content)

    def test_pr_regressions_are_isolated_by_pr_identity(self):
        path = ROOT / ".github" / "workflows" / "rc7-field-hardening.yml"
        content = path.read_text(encoding="utf-8")
        self.assertIn("\n  pull_request:\n", content)
        self.assertIn("github.event.pull_request.number || github.ref", content)
        self.assertIn("windows-latest", content)
        self.assertIn("ubuntu-latest", content)


if __name__ == "__main__":
    unittest.main()
