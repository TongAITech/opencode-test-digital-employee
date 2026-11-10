"""Adversarial R4 source QA: immutable same-SHA evidence and changes-requested veto.

Frozen independent *engineering QA* is not a second human GitHub account.
No code here grants Q3-Q9/BANK_FINAL or fakes a native GitHub approval.
"""
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
            "number": 113, "state": "open", "draft": False,
            "user": {"login": AUTHOR, "type": "User"},
            "head": {"sha": SHA, "ref": "work/rc7.2-r4-consolidated-1to5-20261110"},
            "base": {"ref": "work/rc7.2"},
        },
        "workflow_runs": [
            {
                "id": i + 10, "name": workflow,
                "head_sha": SHA, "event": "pull_request",
                "head_branch": "work/rc7.2-r4-consolidated-1to5-20261110",
                "pull_requests": [{"number": 113}],
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
    def test_18_required_qa_workflows_and_optional_real_review_allow_source_merge(self):
        result = verdict(good_snapshot())
        self.assertEqual(result["status"], "SOURCE_MERGE_ADMISSIBLE")
        self.assertEqual(result["workflow_count"], 18)
        self.assertEqual(result["independent_e_review_count"], 1)
        self.assertFalse(result["field_verified"])
        self.assertFalse(result["bank_final"])

    def test_missing_optional_github_roster_does_not_block_frozen_engineering_qa(self):
        result = verdict(good_snapshot(), reviewers=[])
        self.assertEqual(result["status"], "SOURCE_MERGE_ADMISSIBLE")
        self.assertEqual(result["independent_e_review_count"], 0)

    def test_18_green_ci_without_optional_human_github_review_is_source_only(self):
        x = good_snapshot()
        x["reviews"] = []
        result = verdict(x)
        self.assertEqual(result["status"], "SOURCE_MERGE_ADMISSIBLE")
        self.assertEqual(result["independent_e_review_count"], 0)
        self.assertFalse(result["field_verified"])
        self.assertFalse(result["bank_final"])

    def test_pr_author_cannot_approve_own_source_even_if_allowlisted(self):
        x = good_snapshot()
        x["reviews"][0]["user"]["login"] = AUTHOR
        result = verdict(x, reviewers=[AUTHOR])
        self.assertEqual(result["status"], "SOURCE_MERGE_ADMISSIBLE")
        self.assertEqual(result["independent_e_review_count"], 0)

    def test_external_untrusted_reviewer_is_not_independent_e(self):
        result = verdict(good_snapshot(), reviewers=["not-a-reviewer"])
        self.assertEqual(result["status"], "SOURCE_MERGE_ADMISSIBLE")
        self.assertEqual(result["independent_e_review_count"], 0)

    def test_stale_review_sha_is_rejected(self):
        x = good_snapshot()
        x["reviews"][0]["commit_id"] = PREVIOUS_SHA
        result = verdict(x)
        self.assertEqual(result["status"], "SOURCE_MERGE_ADMISSIBLE")
        self.assertEqual(result["independent_e_review_count"], 0)

    def test_bot_and_dismissed_reviews_are_not_approvals(self):
        for kind, state in (("Bot", "APPROVED"), ("User", "DISMISSED")):
            x = good_snapshot()
            x["reviews"][0]["user"]["type"] = kind
            x["reviews"][0]["state"] = state
            result = verdict(x)
            self.assertEqual(result["status"], "SOURCE_MERGE_ADMISSIBLE")
            self.assertEqual(result["independent_e_review_count"], 0)

    def test_later_dismissal_revokes_previous_approval(self):
        x = good_snapshot()
        x["reviews"].append({
            "id": 124, "state": "DISMISSED", "commit_id": SHA,
            "submitted_at": "2026-11-10T08:20:00Z",
            "user": {"login": E_REVIEWER, "type": "User"},
        })
        result = verdict(x)
        self.assertEqual(result["status"], "SOURCE_MERGE_ADMISSIBLE")
        self.assertEqual(result["independent_e_review_count"], 0)

    def test_real_changes_requested_overrides_all_18_green_source_runs(self):
        x = good_snapshot()
        x["reviews"].append({
            "id": 124, "state": "CHANGES_REQUESTED", "commit_id": SHA,
            "submitted_at": "2026-11-10T09:20:00Z",
            "user": {"login": "external-qa-reviewer", "type": "User"},
        })
        self.assertEqual(verdict(x)["reason"],
                         "R4_GITHUB_CHANGES_REQUESTED_UNRESOLVED")

    def test_followup_genuine_approval_resolves_earlier_changes_requested(self):
        x = good_snapshot()
        x["reviews"].append({
            "id": 124, "state": "CHANGES_REQUESTED", "commit_id": SHA,
            "submitted_at": "2026-11-10T09:10:00Z",
            "user": {"login": E_REVIEWER, "type": "User"},
        })
        x["reviews"].append({
            "id": 125, "state": "APPROVED", "commit_id": SHA,
            "submitted_at": "2026-11-10T09:20:00Z",
            "user": {"login": E_REVIEWER, "type": "User"},
        })
        self.assertEqual(verdict(x)["status"], "SOURCE_MERGE_ADMISSIBLE")

    def test_c12_and_qa_source_workflow_must_both_pass_same_head(self):
        for required_name in (
            "RC7.2 R4 C12 Local Approved Windows Source Qualification (No ZIP)",
            "RC7.2 R4 E Independent Merge Gate Source Tests (No ZIP)",
        ):
            x = good_snapshot()
            x["workflow_runs"] = [
                run for run in x["workflow_runs"]
                if run["name"] != required_name]
            self.assertEqual(verdict(x)["reason"], "R4_REQUIRED_CI_INCOMPLETE")

    def test_wrong_branch_draft_closed_and_head_move_all_hold(self):
        variants = [
            ("state", "closed"),
            ("draft", True),
            ("head", {"sha": PREVIOUS_SHA, "ref": "work/rc7.2-r4-consolidated-1to5-20261110"}),
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


    def test_pr_number_must_be_exactly_int_and_match_github_request(self):
        x = good_snapshot()
        self.assertEqual(
            check_snapshot(x, expected_sha=SHA, trusted_e_reviewers=[E_REVIEWER],
                           expected_pr_number=114)["reason"],
            "R4_PR_NUMBER_MISMATCH")
        for value in (True, "113", None, 0):
            y = good_snapshot()
            y["pull_request"]["number"] = value
            self.assertEqual(verdict(y)["reason"], "R4_PR_NUMBER_MISMATCH")

    def test_github_sha_reuse_by_different_pr_fails_closed(self):
        x = good_snapshot()
        x["workflow_runs"][0]["pull_requests"] = [{"number": 999}]
        self.assertEqual(
            verdict(x)["reason"], "R4_CI_PULL_REQUEST_ASSOCIATION_UNVERIFIED")

    def test_missing_or_empty_native_pr_workflow_association_fails_closed(self):
        for value in (None, [], "PR #113"):
            x = good_snapshot()
            if value is None:
                x["workflow_runs"][0].pop("pull_requests")
            else:
                x["workflow_runs"][0]["pull_requests"] = value
            self.assertEqual(
                verdict(x)["reason"], "R4_CI_PULL_REQUEST_ASSOCIATION_UNVERIFIED")

    def test_workflow_run_source_branch_must_match_current_pr(self):
        x = good_snapshot()
        x["workflow_runs"][0]["head_branch"] = "work/unrelated-feature"
        self.assertEqual(verdict(x)["reason"], "R4_CI_HEAD_BRANCH_MISMATCH")

    def test_github_pr_head_ref_required_for_association(self):
        x = good_snapshot()
        x["pull_request"]["head"].pop("ref")
        self.assertEqual(verdict(x)["reason"], "R4_PR_HEAD_BRANCH_UNVERIFIED")

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
