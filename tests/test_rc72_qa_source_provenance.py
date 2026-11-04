"""Independent adversarial Git ancestry tests for QA's exact-source admission.

All repositories and event SHAs here are local synthetic Git fixtures;
success is only a source-scope admission, not engineering or bank acceptance.
"""
import csv
import subprocess

import pytest

from tools.rc72_qa_source_provenance import ProvenanceError, verify_source


def _run(repo, *args):
    return subprocess.check_output(["git"] + list(args), cwd=str(repo),
                                   universal_newlines=True).strip()


def _commit(repo, name, content):
    (repo / name).write_text(content, encoding="utf-8")
    _run(repo, "add", name)
    _run(repo, "commit", "-m", "QA synthetic ancestry fixture")
    return _run(repo, "rev-parse", "HEAD")


def _scope_fixture(tmp_path):
    root = tmp_path / "qa source"
    root.mkdir()
    _run(root, "init")
    _run(root, "config", "user.name", "RC72 QA fixture")
    _run(root, "config", "user.email", "qa-fixture@example.invalid")
    frozen = _commit(root, "frozen.txt", "historical design\n")
    base = _commit(root, "main.txt", "current main changes\n")
    head = _commit(root, "qa.txt", "QA tests and source\n")
    ledger = tmp_path / "qa-ledger.csv"
    with ledger.open("w", encoding="utf-8", newline="") as dest:
        writer = csv.DictWriter(dest, fieldnames=["clause_id", "source_sha"])
        writer.writeheader()
        for n in range(95):
            writer.writerow({"clause_id": "CLAUSE-%02d" % n, "source_sha": frozen})
    return root, frozen, base, head, ledger


def test_git_source_proof_requires_both_base_and_historical_design_ancestors(tmp_path):
    root, frozen, base, head, ledger = _scope_fixture(tmp_path)
    result = verify_source(root, expected_head=head, expected_base=base, ledger_path=ledger)
    assert result["status"] == "SOURCE_SCOPE_VERIFIED_NOT_TEST_PASS"
    assert result["qa_contains_target_main"] is True
    assert result["target_main_contains_frozen_ledger"] is True
    assert result["target_main_sha"] == base
    assert result["frozen_design_ledger_sha"] == frozen
    assert result["field_verified"] is False and result["bank_final"] is False


@pytest.mark.parametrize("mutation,reason", [
    ("wrong_head", "QA_HEAD_IS_NOT_CHECKED_OUT_SOURCE"),
    ("non_sha", "QA_EXACT_HEAD_AND_BASE_SHA_REQUIRED"),
    ("not_ancestor", "QA_HEAD_DOES_NOT_CONTAIN_TARGET_MAIN"),
    # A syntactically valid but NONEXISTENT SHA makes git merge-base return
    # an explicit ancestry-error exit code (not the valid-but-unrelated 1).
    ("forged_ledger", "QA_GIT_ANCESTRY_ERROR"),
    ("short_ledger", "QA_LEDGER_DENOMINATOR_CHANGED"),
])
def test_stale_base_forged_head_or_ledger_never_produces_green_scope(tmp_path, mutation, reason):
    root, frozen, base, head, ledger = _scope_fixture(tmp_path)
    if mutation == "wrong_head":
        head = base
    elif mutation == "non_sha":
        head = "HEAD"
    elif mutation == "not_ancestor":
        _run(root, "checkout", "-b", "synthetic-sibling", frozen)
        sibling = _commit(root, "unrelated.txt", "another branch\n")
        _run(root, "checkout", "--detach", head)
        base = sibling
    elif mutation == "forged_ledger":
        ledger.write_text(
            "clause_id,source_sha\n" +
            "".join("CLAUSE-%02d,%s\n" % (n, "f" * 40) for n in range(95)),
            encoding="utf-8",
        )
    elif mutation == "short_ledger":
        ledger.write_text("clause_id,source_sha\nX,%s\n" % frozen, encoding="utf-8")
    with pytest.raises(ProvenanceError, match=reason):
        verify_source(root, expected_head=head, expected_base=base, ledger_path=ledger)


def test_wrong_baseline_branch_cannot_pass_just_because_head_is_latest(tmp_path):
    root, frozen, base, head, ledger = _scope_fixture(tmp_path)
    _run(root, "checkout", "-b", "unrelated-first", frozen)
    unrelated = _commit(root, "sibling.txt", "sibling unrelated to main\n")
    _run(root, "checkout", "--detach", head)
    with pytest.raises(ProvenanceError, match="QA_HEAD_DOES_NOT_CONTAIN_TARGET_MAIN"):
        verify_source(root, expected_head=head, expected_base=unrelated, ledger_path=ledger)


def test_frozen_ledger_existing_commit_from_sibling_is_rejected_as_non_ancestor(tmp_path):
    root, frozen, base, head, ledger = _scope_fixture(tmp_path)
    _run(root, "checkout", "-b", "independent-ledger-source", frozen)
    unrelated = _commit(root, "other-version.txt", "sibling design baseline\\n")
    _run(root, "checkout", "--detach", head)
    ledger.write_text("clause_id,source_sha\\n" +
                      "".join("CLAUSE-%02d,%s\\n" % (n, unrelated) for n in range(95)),
                      encoding="utf-8")
    with pytest.raises(ProvenanceError, match="QA_LEDGER_BASELINE_NOT_IN_TARGET_MAIN"):
        verify_source(root, expected_head=head, expected_base=base, ledger_path=ledger)
