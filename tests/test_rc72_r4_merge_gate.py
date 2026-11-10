"""Adversarial R4 merge admission: CI PASS does not bypass an independent E review."""
import copy
import unittest
from unittest.mock import patch

from rc7_release.rc72_r4_merge_gate import (
    REQUIRED_WORKFLOWS, check_snapshot, github_snapshot, _all_pages,
    AdmissionError,
)

SHA = "a" * 40
PREVIOUS_SHA = "b" * 40
AUTHOR = "TongAITech"
E_REVIEWER = "independent-qa-reviewer"


def good_snapshot():
    return {
        "pull_request": {
            "state": "open", "draft": False,
            "user": {"login": AUTHOR, "type": "User"},
            "head": {"sha": SHA}, "base": {"ref": "work/rc7.2"},
        },
        "workflow_runs": [
            {
                "id": i + 10, "name": workflow,
                "head_sha": SHA, "event": "pull_request",
                "status": "completed", "conclusion": "success",
            }
            for i, workflow in enumerate(REQUIRED_WORKFLOWS)
        ],
        "reviews": [
            {
                "id": 123, "state": "APPROVED", "commit_id": SHA,
                "submitted_at": "2026-11-10T08:00:00Z",
                "user": {"login": E_REVIEWER, "type": "User"},
            }
        ],
    }


def verdict(snapshot, *, reviewers=(E_REVIEWER,), sha=SHA):
    return check_snapshot(
        snapshot, expected_sha=sha, trusted_e_reviewers=reviewers)


class R4IndependentMergeGateTests(unittest.TestCase):
    def test_only_real_distinct_approved_e_and_16_same_head_ci_allows_source_merge(self):
        result = verdict(good_snapshot())
        self.assertEqual(result["status"], "SOURCE_MERGE_ADMISSIBLE")
        self.assertEqual(result["workflow_count"], 16)
        self.assertEqual(result["independent_e_review_count"], 1)
        self.assertFalse(result["field_verified"])
        self.assertFalse(result["bank_final"])

    def test_missing_authorized_e_roster_does_not_count_any_github_review(self):
        self.assertEqual(verdict(good_snapshot(), reviewers=[])["reason"],
                         "R4_BANK_APPROVED_E_REVIEWERS_NOT_CONFIGURED")

    def test_16_green_github_runs_without_e_still_holds(self):
        x = good_snapshot()
        x["reviews"] = []
        self.assertEqual(verdict(x)["reason"],
                         "R4_INDEPENDENT_E_EXACT_HEAD_APPROVAL_PENDING")

    def test_pr_author_cannot_approve_own_source_even_if_allowlisted(self):
        x = good_snapshot()
        x["reviews"][0]["user"]["login"] = AUTHOR
        self.assertEqual(
            verdict(x, reviewers=[AUTHOR])["status"], "HOLD")

    def test_external_untrusted_reviewer_is_not_independent_e(self):
        self.assertEqual(
            verdict(good_snapshot(), reviewers=["not-a-reviewer"])["status"], "HOLD")

    def test_stale_review_sha_is_rejected(self):
        x = good_snapshot()
        x["reviews"][0]["commit_id"] = PREVIOUS_SHA
        self.assertEqual(verdict(x)["reason"],
                         "R4_INDEPENDENT_E_EXACT_HEAD_APPROVAL_PENDING")

    def test_bot_and_dismissed_reviews_are_not_approvals(self):
        for kind, state in (("Bot", "APPROVED"), ("User", "DISMISSED")):
            x = good_snapshot()
            x["reviews"][0]["user"]["type"] = kind
            x["reviews"][0]["state"] = state
            self.assertEqual(verdict(x)["status"], "HOLD")

    def test_later_dismissal_revokes_previous_approval(self):
        x = good_snapshot()
        x["reviews"].append({
            "id": 124, "state": "DISMISSED", "commit_id": SHA,
            "submitted_at": "2026-11-10T08:20:00Z",
            "user": {"login": E_REVIEWER, "type": "User"},
        })
        self.assertEqual(verdict(x)["status"], "HOLD")

    def test_wrong_branch_draft_closed_and_head_move_all_hold(self):
        variants = [
            ("state", "closed"),
            ("draft", True),
            ("head", {"sha": PREVIOUS_SHA}),
            ("base", {"ref": "main"}),
        ]
        for key, value in variants:
            x = good_snapshot()
            x["pull_request"][key] = value
            self.assertEqual(verdict(x)["reason"],
                             "R4_PR_HEAD_BASE_OR_STATE_MISMATCH")

    def test_one_missing_skipped_failed_or_running_ci_holds(self):
        for mode in ("missing", "skipped", "failure", "in_progress"):
            x = good_snapshot()
            if mode == "missing":
                x["workflow_runs"].pop()
                self.assertEqual(verdict(x)["reason"], "R4_REQUIRED_CI_INCOMPLETE")
            else:
                row = x["workflow_runs"][0]
                row["status"] = "in_progress" if mode == "in_progress" else "completed"
                row["conclusion"] = None if mode == "in_progress" else mode
                self.assertEqual(verdict(x)["reason"],
                                 "R4_REQUIRED_CI_NOT_ALL_SUCCESS")

    def test_same_named_duplicate_is_not_selected_by_latest_green(self):
        x = good_snapshot()
        duplicate = copy.deepcopy(x["workflow_runs"][0])
        duplicate["id"] = 999
        duplicate["conclusion"] = "failure"
        x["workflow_runs"].append(duplicate)
        self.assertEqual(verdict(x)["reason"],
                         "R4_CI_DUPLICATE_WORKFLOW_AMBIGUOUS")

    def test_old_sha_and_non_pr_event_cannot_be_reused(self):
        for field, replacement in (("head_sha", PREVIOUS_SHA), ("event", "push")):
            x = good_snapshot()
            x["workflow_runs"][0][field] = replacement
            self.assertEqual(verdict(x)["reason"],
                             "R4_CI_SOURCE_OR_EVENT_UNVERIFIED")

    def test_invalid_expected_commit_rejected(self):
        self.assertEqual(verdict(good_snapshot(), sha="short")["reason"],
                         "R4_HEAD_SHA_INVALID")

    def test_missing_snapshot_sections_hold(self):
        for key in ("pull_request", "workflow_runs", "reviews"):
            x = good_snapshot()
            x.pop(key)
            self.assertEqual(verdict(x)["status"], "HOLD")

    def test_false_bank_pass_fields_from_api_are_not_promoted(self):
        x = good_snapshot()
        x["field_verified"] = True
        x["bank_final"] = True
        out = verdict(x)
        self.assertEqual(out["status"], "SOURCE_MERGE_ADMISSIBLE")
        self.assertFalse(out["field_verified"])
        self.assertFalse(out["bank_final"])

    def test_git_api_pagination_malformed_or_more_than_20_full_pages_holds(self):
        with patch(
            "rc7_release.rc72_r4_merge_gate._api_json",
            return_value={"workflow_runs": "not-array"},
        ):
            with self.assertRaises(AdmissionError):
                _all_pages("/actions/runs?head_sha=" + SHA,
                           repository="a/b", token="fixture", field="workflow_runs")
        with patch(
            "rc7_release.rc72_r4_merge_gate._api_json",
            return_value={"workflow_runs": [{}] * 100},
        ):
            with self.assertRaisesRegex(AdmissionError, "PAGINATION_INCOMPLETE"):
                _all_pages("/actions/runs?head_sha=" + SHA,
                           repository="a/b", token="fixture", field="workflow_runs")

    def test_git_api_rejects_untrusted_repo_identifier_without_network(self):
        with self.assertRaisesRegex(AdmissionError, "INPUTS_UNTRUSTED"):
            github_snapshot(
                repository="bad/repo/extra", pr_number=113,
                expected_sha=SHA, token="fixture")


if __name__ == "__main__":
    unittest.main()
