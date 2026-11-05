"""Exact-source CI admission for RC7.2 independent QA (Python 3.8+).

A frozen design clause ledger is a historical baseline, not proof that the
current QA tree contains the latest main branch. Check Git ancestry rather
than accepting matching strings or GitHub's synthetic pull/merge SHA.
This establishes source provenance only, NEVER test/field/BANK_FINAL PASS.
"""
import argparse
import csv
import json
from pathlib import Path
import re
import subprocess
import sys


class ProvenanceError(RuntimeError):
    pass


_SHA = re.compile(r"^[0-9a-f]{40}$")
_LEDGER = Path("docs/rc7.2/qa-release/DESIGN-CLAUSE-AUDIT-BASELINE.csv")


def _git(root, *args):
    try:
        result = subprocess.run(
            ["git"] + list(args), cwd=str(root), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, universal_newlines=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProvenanceError("QA_GIT_UNAVAILABLE") from exc
    if result.returncode:
        raise ProvenanceError("QA_GIT_QUERY_FAILED:" + ":".join(args[:2]))
    return result.stdout.strip()


def _ancestor(root, ancestor, descendant):
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProvenanceError("QA_GIT_ANCESTRY_UNAVAILABLE") from exc
    if result.returncode not in (0, 1):
        raise ProvenanceError("QA_GIT_ANCESTRY_ERROR")
    return result.returncode == 0


def _frozen_source(ledger_path):
    try:
        with Path(ledger_path).open("r", encoding="utf-8", newline="") as src:
            reader = csv.DictReader(src)
            if not reader.fieldnames or "source_sha" not in reader.fieldnames or "clause_id" not in reader.fieldnames:
                raise ProvenanceError("QA_LEDGER_SCHEMA_CHANGED")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ProvenanceError("QA_LEDGER_UNREADABLE") from exc
    if len(rows) != 95 or len({row.get("clause_id") for row in rows}) != 95:
        raise ProvenanceError("QA_LEDGER_DENOMINATOR_CHANGED")
    shas = {row.get("source_sha") for row in rows}
    if len(shas) != 1:
        raise ProvenanceError("QA_LEDGER_SOURCES_CONFLICT")
    source = next(iter(shas))
    if not isinstance(source, str) or not _SHA.fullmatch(source):
        raise ProvenanceError("QA_LEDGER_SOURCE_INVALID")
    return source


def verify_source(repo_root, *, expected_head, expected_base, ledger_path=None):
    repo_root = Path(repo_root).resolve()
    if not all(isinstance(value, str) and _SHA.fullmatch(value)
               for value in (expected_head, expected_base)):
        raise ProvenanceError("QA_EXACT_HEAD_AND_BASE_SHA_REQUIRED")
    actual_head = _git(repo_root, "rev-parse", "HEAD")
    if actual_head != expected_head:
        raise ProvenanceError("QA_HEAD_IS_NOT_CHECKED_OUT_SOURCE")
    if not _ancestor(repo_root, expected_base, actual_head):
        raise ProvenanceError("QA_HEAD_DOES_NOT_CONTAIN_TARGET_MAIN")
    ledger = Path(ledger_path) if ledger_path is not None else repo_root / _LEDGER
    frozen = _frozen_source(ledger)
    if not _ancestor(repo_root, frozen, expected_base):
        raise ProvenanceError("QA_LEDGER_BASELINE_NOT_IN_TARGET_MAIN")
    return {
        "schema": "RC72_QA_EXACT_SOURCE_PROVENANCE_V1",
        "status": "SOURCE_SCOPE_VERIFIED_NOT_TEST_PASS",
        "qa_head_sha": actual_head, "target_main_sha": expected_base,
        "frozen_design_ledger_sha": frozen,
        "qa_contains_target_main": True,
        "target_main_contains_frozen_ledger": True,
        "source_scope_only": True,
        "field_verified": False, "bank_final": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fail closed on stale RC7.2 QA vs target main")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    try:
        result = verify_source(args.repo_root, expected_head=args.expected_head,
                               expected_base=args.expected_base)
        if args.report:
            with Path(args.report).open("x", encoding="utf-8") as report:
                json.dump(result, report, sort_keys=True, indent=2)
                report.write("\n")
    except (ProvenanceError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc),
                          "field_verified": False, "bank_final": False}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
