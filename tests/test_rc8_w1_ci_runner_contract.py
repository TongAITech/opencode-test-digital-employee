"""Regression guard: RC8 W1 Python 3.8 CI must use a compatible Ubuntu image."""
from pathlib import Path
import unittest


class W1Python38RunnerContract(unittest.TestCase):
    def test_ubuntu_runner_is_pinned_for_python38(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "rc8-wave1-control.yml").read_text(encoding="utf-8")
        self.assertIn("os: [ubuntu-24.04, windows-2022]", workflow)
        self.assertIn("python-version: '3.8'", workflow)
        self.assertNotIn("ubuntu-latest", workflow)


if __name__ == "__main__":
    unittest.main()
