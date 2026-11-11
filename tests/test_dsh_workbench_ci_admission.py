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

    def test_v3_preserves_required_status_but_skips_duplicate_full_pr(self):
        self.changed("v3", "if: github.event_name != 'pull_request'",
                     "if: always()", "V3_PR_STATUS_COMPATIBILITY_OR_FULL_RUN")

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
                     "  push:\n    branches: [work/dsh-wb-w0]\n  workflow_dispatch:",
                     "W0_DUPLICATE_OR_MISSING_PR_TRIGGER")

    def test_a01_w1_bilingual_must_remain_in_w0_design_gate(self):
        self.changed("w0", "python tools/dsh_workbench/a01_locale_scope.py",
                     "echo bilingual not required",
                     "A01_W1_BILINGUAL_SCOPE_GATE_REMOVED")

    def test_w0_c_node_scope_negative_tests_must_run(self):
        self.changed("w0", "node --test tests/test_dsh_workbench_ui_w0.mjs",
                     "echo skipped C scope tests",
                     "W0_C_SCOPE_NEGATIVE_TESTS_NOT_ADMITTED")

    def test_w0_scope_response_fence_cannot_be_silently_removed(self):
        self.changed("w0", " tests/test_dsh_workbench_ui_source_fence.mjs",
                     " tests/removed_scope_fence.mjs",
                     "W0_SCOPE_RESPONSE_FENCE_NOT_ADMITTED")

    def test_l1_pinned_sha_must_remain_fail_closed(self):
        self.changed("l1", "L1_SOURCE_HEAD_MISMATCH", "SILENTLY_ACCEPT",
                     "L1_SOURCE_PIN_OR_GATES_MISSING")

    def test_l1_scope_response_fence_must_be_present(self):
        self.changed("l1", "tests/test_dsh_workbench_ui_source_fence.mjs",
                     "tests/disabled_source_fence.mjs",
                     "L1_SCOPE_RESPONSE_FENCE_NOT_ADMITTED")

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

    def test_n5_full_matrix_never_runs_on_draft_pr(self):
        self.changed("n5", NON_DRAFT, "if: always()",
                     "N5_DRAFT_HEAVY_MATRIX_OR_REQUIRED_PROOF_LOST")

    def test_n5_old_sha_queue_must_be_cancelled(self):
        self.changed("n5", "rc72-n5-proof-", "rc72-n5-proof-github.sha-",
                     "N5_DRAFT_HEAVY_MATRIX_OR_REQUIRED_PROOF_LOST")

    def test_q1_py38_fg17_negative_proof_is_preserved(self):
        self.changed("q1", "'tests/test_rc72_c09_real_chromium_cdp_smoke.py'",
                     "'docs/irrelevant.md'", "Q1_FG17_NEGATIVE_CHECK_REMOVED_OR_DRAFT_UNGATED")

    def test_q1_real_chromium_test_path_removal_fails_closed(self):
        self.changed("q1", "tests/test_rc72_c09_real_chromium_cdp_smoke.py",
                     "tests/empty_browser_probe.py",
                     "Q1_FG17_NEGATIVE_CHECK_REMOVED_OR_DRAFT_UNGATED")

    def test_q1_draft_reenablement_and_missing_browser_test_are_independent(self):
        sample = copy.deepcopy(self.source)
        sample["q1"] = sample["q1"].replace(
            "if: github.event_name == 'pull_request' && github.event.pull_request.draft == false",
            "if: github.event_name == 'pull_request'")
        sample["q1"] = sample["q1"].replace(
            "'tests/test_rc72_c09_real_chromium_cdp_smoke.py'",
            "'tests/removed_real_cdp.py'")
        self.assertIn(
            "Q1_FG17_NEGATIVE_CHECK_REMOVED_OR_DRAFT_UNGATED", problems(sample))

    def test_q1_py38_browser_runs_only_on_non_draft_candidate(self):
        self.changed("q1", "if: github.event_name == 'pull_request' && github.event.pull_request.draft == false",
                     "if: github.event_name == 'pull_request'",
                     "Q1_FG17_NEGATIVE_CHECK_REMOVED_OR_DRAFT_UNGATED")

    def test_fg17_keeps_exact_python38_five_trial_gate(self):
        self.changed("fg17", "for trial in 1 2 3 4 5",
                     "for trial in 1 2 3 4",
                     "FG17_EXACT_PY38_FIVE_TRIAL_OR_CROSS_VERSION_GATE_MISSING")

    def test_field_hardening_does_not_run_full_source_matrix_on_draft(self):
        self.changed("field", NON_DRAFT, "if: always()",
                     "FIELD_HARDENING_DRAFT_RUN_NOT_GATED")


if __name__ == "__main__":
    unittest.main()
