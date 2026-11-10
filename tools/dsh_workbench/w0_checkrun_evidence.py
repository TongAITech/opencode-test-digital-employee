"""Fail-closed attestation of GitHub check-runs for one exact source commit.

This is evidence classification, NOT F review, release approval or product QA.
Compatible with Python 3.8+. Supply a complete GitHub check-runs JSON snapshot.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


class CheckEvidenceError(ValueError):
    """A required, source-pinned CI attestation cannot be made."""


def attest_check_runs(
    snapshot: Mapping[str, Any], source_sha: str, required: Sequence[str]
) -> Dict[str, Any]:
    if not isinstance(source_sha, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", source_sha):
        raise CheckEvidenceError("INVALID_SOURCE_SHA")
    if not isinstance(required, (list, tuple)) or not required or any(
        not isinstance(name, str) or not name.strip() for name in required
    ) or len(set(required)) != len(required):
        raise CheckEvidenceError("INVALID_REQUIRED_CHECKS")
    if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("check_runs"), list):
        raise CheckEvidenceError("INVALID_CHECK_RUN_SNAPSHOT")
    runs = snapshot["check_runs"]
    count = snapshot.get("total_count")
    if type(count) is not int or count != len(runs):
        raise CheckEvidenceError("CHECK_RUN_PAGE_INCOMPLETE")
    pinned = source_sha.lower()
    matched = {}
    for run in runs:
        if not isinstance(run, Mapping) or not isinstance(run.get("name"), str):
            raise CheckEvidenceError("INVALID_CHECK_RUN")
        if str(run.get("head_sha", "")).lower() != pinned:
            raise CheckEvidenceError("CHECK_RUN_HEAD_MISMATCH")
        name = run["name"]
        if name in required:
            if name in matched:
                raise CheckEvidenceError("DUPLICATE_REQUIRED_CHECK: " + name)
            matched[name] = run
    for name in required:
        run = matched.get(name)
        if run is None:
            raise CheckEvidenceError("REQUIRED_CHECK_MISSING: " + name)
        if run.get("status") != "completed":
            raise CheckEvidenceError("REQUIRED_CHECK_NOT_COMPLETED: " + name)
        if run.get("conclusion") != "success":
            raise CheckEvidenceError(
                "REQUIRED_CHECK_NOT_SUCCESS: " + name + ": " + str(run.get("conclusion"))
            )
    skipped = sorted(run["name"] for run in runs if run.get("conclusion") == "skipped")
    all_success = all(
        run.get("status") == "completed" and run.get("conclusion") == "success"
        for run in runs
    )
    return {
        "source_sha": pinned,
        "required_success": list(required),
        "total_checks": len(runs),
        "skipped_checks": skipped,
        "all_checks_success": all_success,
        "product_qa_pass": False,
        "f_independent_approval": False,
        "license_release_approved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--require", required=True, action="append")
    args = parser.parse_args()
    try:
        result = attest_check_runs(
            json.loads(args.snapshot.read_text(encoding="utf-8")),
            args.source_sha, args.require,
        )
    except (CheckEvidenceError, ValueError, OSError) as exc:
        print("CI_EVIDENCE_BLOCKED: " + str(exc))
        return 2
    print("CI_EVIDENCE_ATTESTED: " + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
