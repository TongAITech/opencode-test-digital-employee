"""Adversarial tests: a W0 green check cannot stand in for full product QA."""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "dsh_workbench"))
from w0_checkrun_evidence import CheckEvidenceError, attest_check_runs

SHA = "f6aa541a7c82b74bcd1937754637d8341111fb70"
OLD = "a" * 40


def run(name, status="completed", conclusion="success", sha=SHA):
    return {"name": name, "status": status, "conclusion": conclusion, "head_sha": sha}


def fixture():
    checks = [run("w0-contracts"), run("l1", conclusion="skipped"),
              run("full-browser", conclusion="skipped")]
    return {"total_count": len(checks), "check_runs": checks}


class TestW0CheckRunEvidence(unittest.TestCase):
    def blocked(self, expected, data=None, required=None, sha=SHA):
        with self.assertRaises(CheckEvidenceError) as captured:
            attest_check_runs(fixture() if data is None else data,
                              sha, ["w0-contracts"] if required is None else required)
        self.assertIn(expected, str(captured.exception))

    def test_w0_success_is_only_w0_success(self):
        evidence = attest_check_runs(fixture(), SHA, ["w0-contracts"])
        self.assertEqual(evidence["required_success"], ["w0-contracts"])
        self.assertEqual(len(evidence["skipped_checks"]), 2)
        self.assertFalse(evidence["all_checks_success"])
        self.assertFalse(evidence["product_qa_pass"])
        self.assertFalse(evidence["f_independent_approval"])
        self.assertFalse(evidence["license_release_approved"])

    def test_cannot_count_skipped_l1_as_pass(self):
        self.blocked("REQUIRED_CHECK_NOT_SUCCESS: l1: skipped",
                     required=["w0-contracts", "l1"])

    def test_cannot_count_skipped_browser_as_pass(self):
        self.blocked("REQUIRED_CHECK_NOT_SUCCESS: full-browser: skipped",
                     required=["full-browser"])

    def test_cannot_reuse_old_source_check(self):
        data = fixture()
        data["check_runs"][0]["head_sha"] = OLD
        self.blocked("CHECK_RUN_HEAD_MISMATCH", data)

    def test_cannot_accept_missing_required_check(self):
        self.blocked("REQUIRED_CHECK_MISSING", required=["missing"])

    def test_cannot_accept_queued_required_check(self):
        data = fixture()
        data["check_runs"][0]["status"] = "queued"
        data["check_runs"][0]["conclusion"] = None
        self.blocked("REQUIRED_CHECK_NOT_COMPLETED", data)

    def test_cannot_accept_failed_required_check(self):
        data = fixture()
        data["check_runs"][0]["conclusion"] = "failure"
        self.blocked("REQUIRED_CHECK_NOT_SUCCESS", data)

    def test_cannot_accept_cancelled_required_check(self):
        data = fixture()
        data["check_runs"][0]["conclusion"] = "cancelled"
        self.blocked("REQUIRED_CHECK_NOT_SUCCESS", data)

    def test_duplicate_required_name_is_not_ambiguous_success(self):
        data = fixture()
        data["check_runs"].append(run("w0-contracts"))
        data["total_count"] += 1
        self.blocked("DUPLICATE_REQUIRED_CHECK", data)

    def test_incomplete_api_page_must_be_rejected(self):
        data = fixture()
        data["total_count"] += 1
        self.blocked("CHECK_RUN_PAGE_INCOMPLETE", data)

    def test_invalid_source_sha_must_be_rejected(self):
        self.blocked("INVALID_SOURCE_SHA", sha="old-head")

    def test_invalid_empty_or_repeated_requirements(self):
        self.blocked("INVALID_REQUIRED_CHECKS", required=[])
        self.blocked("INVALID_REQUIRED_CHECKS",
                     required=["w0-contracts", "w0-contracts"])

    def test_can_attest_all_success_but_still_not_product_qa(self):
        data = fixture()
        for check in data["check_runs"]:
            check["conclusion"] = "success"
        result = attest_check_runs(data, SHA, ["w0-contracts", "l1", "full-browser"])
        self.assertTrue(result["all_checks_success"])
        self.assertFalse(result["product_qa_pass"])


if __name__ == "__main__":
    unittest.main()
