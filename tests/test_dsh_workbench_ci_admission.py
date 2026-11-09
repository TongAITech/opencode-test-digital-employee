"""Negative-first regression tests for CI run-cost admission boundaries."""
from __future__ import annotations
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "dsh_workbench"))
from ci_admission import NON_DRAFT, problems, read_workflows


class TestCIAdmission(unittest.TestCase):
    def setUp(self):
        self.source = read_workflows(ROOT)

    def changed(self, name, needle, substitute, expected):
        sample = copy.deepcopy(self.source)
        self.assertIn(needle, sample[name])
        sample[name] = sample[name].replace(needle, substitute)
        self.assertIn(expected, problems(sample))

    def test_repository_policy_is_consistent(self):
        self.assertEqual(problems(self.source), [])

    def test_v3_cannot_reintroduce_duplicate_full_pr(self):
        self.changed("v3", "  workflow_dispatch:",
                     "  pull_request:\n    branches: [work/rc7.2]\n  workflow_dispatch:",
                     "DUPLICATE_V3_FULL_PR")

    def test_v4_draft_full_suite_cannot_be_activated(self):
        self.changed("v4", NON_DRAFT, "if: always()",
                     "V4_DRAFT_FULL_TESTS_REENABLED")

    def test_v4_release_suite_cannot_be_removed(self):
        self.changed("v4", "find tests -maxdepth 1 -type f -name 'test_rc7*.py'",
                     "echo dropped", "V4_FULL_RELEASE_COVERAGE_DROPPED")

    def test_v4_pr_concurrency_must_not_key_by_sha(self):
        self.changed("v4", "group: rc72-abcd-v4-",
                     "group: rc72-abcd-v4-github.sha-",
                     "V4_OLD_SHA_TASKS_NOT_CANCELLED")

    def test_w0_double_push_and_pr_runs_are_rejected(self):
        self.changed("w0", "  workflow_dispatch:",
                     "  pull_request:\n    branches: [work/rc7.2]\n  workflow_dispatch:",
                     "W0_DUPLICATE_OR_MISSING_BRANCH_GATE")

    def test_l1_pinned_sha_must_remain_fail_closed(self):
        self.changed("l1", "L1_SOURCE_HEAD_MISMATCH", "SILENTLY_ACCEPT",
                     "L1_SOURCE_PIN_OR_GATES_MISSING")

    def test_c_browser_does_not_rebuild_on_document_ledger(self):
        self.changed("c", "  pull_request:\n    types:",
                     "  pull_request:\n    paths:\n      - 'docs/dsh-workbench/08-CONSTRUCTION-PLAN.md'\n    types:",
                     "C_BROWSER_RERUN_ON_LEDGER")

    def test_c04_matrix_requires_path_filter(self):
        self.changed("c04", "    paths:", "    old_paths_disabled:",
                     "C04_UNSCOPED_MATRIX")

    def test_n8_explicit_manual_gate_must_remain(self):
        self.changed("n8", "  workflow_dispatch:", "  disabled_manual_gate:",
                     "N8_EXPLICIT_GATE_LOST")

    def test_q1_py38_fg17_negative_proof_is_preserved(self):
        self.changed("q1", "'tests/test_rc72_c09_real_chromium_cdp_smoke.py'",
                     "'docs/irrelevant.md'", "Q1_FG17_NEGATIVE_CHECK_REMOVED")


if __name__ == "__main__":
    unittest.main()
