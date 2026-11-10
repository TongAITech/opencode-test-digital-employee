"""R4 source merge admission: exact-HEAD independent engineering QA evidence.

Frozen RC7.2 requires independent QA and verified N1-N10 evidence, but does
not mandate a *second GitHub account* for engineering source integration.
GitHub CHANGES_REQUESTED still vetoes merge. Authentic human approval is
optional metadata; it is never fabricated or required to prove Q3-Q9 Field.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SHA = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
REQUIRED_WORKFLOWS = (
    "RC7 Field Hardening",
    "RC7.2 C10 Deterministic Bank Quota Window Qualification",
    "RC7.2 C01-C02 Whole-N5 Independent Proof Regression",
    "RC7.2 R4 Q3-Q6 Field Signature Gate (No ZIP)",
    "RC7.2 R4 C07 Bank-Owned AgentTeams Provider Trust (No ZIP)",
    "RC7.2 R4 Model Governor Fail-Closed Qualification (No ZIP)",
    "RC7.2 C07 Captain-Fenced Independent N9 DSH Bridge Admission",
    "RC7.2 R4 AgentTeams 32 Member Engineering Qualification (No ZIP)",
    "RC7.2 R4 N8 Cold Delivery Integrity (No ZIP)",
    "RC7.2 C04 Package Native Independent N9 DSH Host",
    "RC7.2 C03 N8 Semantic Route Replay Integrity",
    "RC7.2 A N8 Multi-Round and Q7 CLI Side-Effect Admission",
    "RC7.2 Runtime C06-C07 Contract Qualification",
    "RC7.2 C08 Mandatory N1-N10 Denominator Integrity",
    "RC7.2 ABCD-v3 Same-HEAD Product and Independent QA Qualification",
    "RC7.2 ABCD-v4 Same-HEAD Product and Independent QA Qualification",
    # Genuine independent QA/source workflows, not the gate checking itself.
    "RC7.2 R4 E Independent Merge Gate Source Tests (No ZIP)",
    "RC7.2 R4 C12 Local Approved Windows Source Qualification (No ZIP)",
)


class AdmissionError(ValueError):
    """Auditable release HOLD: no silently accepted partial checks."""


def _hold(reason, sha):
    return {
        "status": "HOLD",
        "reason": reason,
        "source_sha": sha,
        "field_verified": False,
        "bank_final": False,
    }


def check_snapshot(snapshot, *, expected_sha, trusted_e_reviewers,
                   expected_pr_number=None):
    """Pure review of GitHub-origin data. Never use caller-provided approval booleans."""
    sha = str(expected_sha or "")
    if not SHA.fullmatch(sha):
        return _hold("R4_HEAD_SHA_INVALID", sha)
    if not isinstance(snapshot, dict):
        return _hold("R4_GITHUB_SNAPSHOT_INVALID", sha)
    pr, runs, reviews = (snapshot.get("pull_request"),
                         snapshot.get("workflow_runs"), snapshot.get("reviews"))
    if not isinstance(pr, dict):
        return _hold("R4_PR_PROOF_MISSING", sha)
    number = pr.get("number")
    if (type(number) is not int or number < 1
            or (expected_pr_number is not None
                and (type(expected_pr_number) is not int
                     or number != expected_pr_number))):
        return _hold("R4_PR_NUMBER_MISMATCH", sha)
    head = pr.get("head")
    if (not isinstance(head, dict)
            or not isinstance(head.get("ref"), str)
            or not head["ref"].strip()):
        return _hold("R4_PR_HEAD_BRANCH_UNVERIFIED", sha)
    if (pr.get("state") != "open" or pr.get("draft") is not False
            or not isinstance(pr.get("head"), dict)
            or pr["head"].get("sha") != sha
            or not isinstance(pr.get("base"), dict)
            or pr["base"].get("ref") != "work/rc7.2"):
        return _hold("R4_PR_HEAD_BASE_OR_STATE_MISMATCH", sha)
    owner = (pr.get("user") or {}).get("login")
    if not isinstance(owner, str) or not owner.strip():
        return _hold("R4_PR_AUTHOR_UNKNOWN", sha)

    if not isinstance(runs, list):
        return _hold("R4_SAME_HEAD_CI_MISSING", sha)
    selected = {}
    for run in runs:
        if not isinstance(run, dict):
            return _hold("R4_CI_RECORD_INVALID", sha)
        name = run.get("name")
        if name not in REQUIRED_WORKFLOWS:
            continue
        if (run.get("head_sha") != sha or run.get("event") != "pull_request"
                or not isinstance(run.get("id"), int) or isinstance(run.get("id"), bool)):
            return _hold("R4_CI_SOURCE_OR_EVENT_UNVERIFIED", sha)
        # The GitHub SHA filter alone is not a PR association: the same commit
        # can be used by another pull request. Require a native per-run PR
        # reference to the exact candidate, not a caller-written string.
        associated = run.get("pull_requests")
        if (not isinstance(associated, list) or
                not any(isinstance(item, dict)
                        and type(item.get("number")) is int
                        and item["number"] == number
                        for item in associated)):
            return _hold("R4_CI_PULL_REQUEST_ASSOCIATION_UNVERIFIED", sha)
        if (run.get("head_branch") is not None
                and run.get("head_branch") != head["ref"]):
            return _hold("R4_CI_HEAD_BRANCH_MISMATCH", sha)
        # Refuse multiple different runs with the same name. Silent selection
        # by name could accidentally hide a conflicting failed run.
        if name in selected:
            return _hold("R4_CI_DUPLICATE_WORKFLOW_AMBIGUOUS", sha)
        selected[name] = run
    if set(selected) != set(REQUIRED_WORKFLOWS):
        return _hold("R4_REQUIRED_CI_INCOMPLETE", sha)
    if any(row.get("status") != "completed" or row.get("conclusion") != "success"
           for row in selected.values()):
        return _hold("R4_REQUIRED_CI_NOT_ALL_SUCCESS", sha)

    # Preserve a genuine GitHub CHANGES_REQUESTED veto. An unrequested
    # GitHub approval is NOT equivalent to an independent technical review
    # and is not required by frozen RC7.2 construction contracts.
    if not isinstance(reviews, list):
        return _hold("R4_GITHUB_REVIEW_STATUS_UNAVAILABLE", sha)
    allowed = {name.strip().casefold() for name in trusted_e_reviewers
               if isinstance(name, str) and name.strip()}
    latest = {}
    for review in reviews:
        if not isinstance(review, dict):
            return _hold("R4_REVIEW_RECORD_INVALID", sha)
        reviewer = (review.get("user") or {}).get("login")
        if not isinstance(reviewer, str) or not reviewer.strip():
            return _hold("R4_REVIEW_AUTHOR_INVALID", sha)
        key = reviewer.casefold()
        try:
            order = (str(review.get("submitted_at") or ""), int(review.get("id") or 0))
        except (ValueError, TypeError):
            return _hold("R4_REVIEW_ORDER_INVALID", sha)
        if key not in latest or order > latest[key][0]:
            latest[key] = (order, review)
    if any(x[1].get("state") == "CHANGES_REQUESTED"
           and name != owner.casefold()
           for name, x in latest.items()):
        return _hold("R4_GITHUB_CHANGES_REQUESTED_UNRESOLVED", sha)
    approved = [
        row[1] for name, row in latest.items()
        if (name in allowed and name != owner.casefold()
            and row[1].get("state") == "APPROVED"
            and row[1].get("commit_id") == sha
            and (row[1].get("user") or {}).get("type") != "Bot")
    ]
    return {
        "status": "SOURCE_MERGE_ADMISSIBLE",
        "source_sha": sha,
        "workflow_count": len(selected),
        "independent_qa_ci_workflows_verified": [
            "RC7.2 ABCD-v3 Same-HEAD Product and Independent QA Qualification",
            "RC7.2 ABCD-v4 Same-HEAD Product and Independent QA Qualification",
            "RC7.2 R4 E Independent Merge Gate Source Tests (No ZIP)",
            "RC7.2 R4 C12 Local Approved Windows Source Qualification (No ZIP)",
        ],
        "external_github_review_required_by_frozen_rc72_contract": False,
        "independent_e_review_count": len(approved),
        "field_verified": False,
        "bank_final": False,
    }


def _api_json(endpoint, *, token, repository):
    request = Request(
        "https://api.github.com/repos/%s%s" % (repository, endpoint),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "rc72-r4-release-admission",
        })
    with urlopen(request, timeout=25) as response:
        body = response.read(3_000_001)
        if len(body) > 3_000_000:
            raise AdmissionError("R4_GITHUB_RESPONSE_TOO_LARGE")
    return json.loads(body.decode("utf-8"))


def _all_pages(path, *, token, repository, field):
    results = []
    for page in range(1, 21):
        separator = "&" if "?" in path else "?"
        payload = _api_json(
            "%s%sper_page=100&page=%d" % (path, separator, page),
            token=token, repository=repository)
        rows = payload.get(field) if field else payload
        if not isinstance(rows, list):
            raise AdmissionError("R4_GITHUB_PAGINATION_MALFORMED")
        results.extend(rows)
        if len(rows) < 100:
            return results
    raise AdmissionError("R4_GITHUB_PAGINATION_INCOMPLETE")


def github_snapshot(*, repository, pr_number, expected_sha, token):
    if (not REPOSITORY.fullmatch(repository) or not 0 < pr_number < 2_147_483_647
            or not SHA.fullmatch(expected_sha) or not token):
        raise AdmissionError("R4_GITHUB_INPUTS_UNTRUSTED")
    pr = _api_json("/pulls/%d" % pr_number,
                   token=token, repository=repository)
    # Query only the expected source commit. Duplicate and conflicting
    # workflows are deliberately not selected away by the API client.
    runs = _all_pages(
        "/actions/runs?head_sha=%s&event=pull_request" % expected_sha,
        token=token, repository=repository, field="workflow_runs")
    reviews = _all_pages(
        "/pulls/%d/reviews" % pr_number,
        token=token, repository=repository, field=None)
    return dict(pull_request=pr, workflow_runs=runs, reviews=reviews)


def main(argv=None):
    parser = argparse.ArgumentParser(description="R4 same-HEAD, independent E integration admission")
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--pr-number", type=int, required=True)
    args = parser.parse_args(argv)
    trusted = os.environ.get("RC72_E_REVIEWER_LOGINS", "")
    try:
        snapshot = github_snapshot(
            repository=args.repository, pr_number=args.pr_number,
            expected_sha=args.expected_head, token=os.environ.get("GITHUB_TOKEN", ""))
        verdict = check_snapshot(
            snapshot, expected_sha=args.expected_head,
            trusted_e_reviewers=trusted.split(","),
            expected_pr_number=args.pr_number)
    except (AdmissionError, HTTPError, URLError, OSError, ValueError, TypeError,
            UnicodeError) as exc:
        reason = str(exc) if isinstance(exc, AdmissionError) else "R4_GITHUB_PROOF_UNAVAILABLE"
        verdict = _hold(reason, args.expected_head)
    print(json.dumps(verdict, ensure_ascii=False, sort_keys=True))
    return 0 if verdict["status"] == "SOURCE_MERGE_ADMISSIBLE" else 2


if __name__ == "__main__":
    sys.exit(main())
