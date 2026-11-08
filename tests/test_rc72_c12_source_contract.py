"""Independent policy checks for a real, exact-SHA C12 audit with no rebuild."""
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def test_c12_consumes_only_actual_merged_p0_source_and_artifact():
    text = (WORKFLOWS / "rc7.2-qa-physical-transport.yml").read_text(encoding="utf-8")
    triggers = text.split("\njobs:", 1)[0]
    assert "\n  workflow_call:" in triggers and "\n  workflow_dispatch:" in triggers
    assert "\n  push:" not in triggers and "\n  pull_request:" not in triggers
    assert "if: inputs.final_qualification == true" in text
    assert "default: false" in triggers
    assert "git merge-base --is-ancestor $env:TARGET_MAIN_SHA" in text
    assert "C12_SOURCE_NOT_EXACT_MERGED_PR76" in text
    assert "$pr.head.sha -ne $env:TARGET_MAIN_SHA" in text
    assert "$pr.base.ref -ne 'work/rc7.2'" in text
    assert "name='RC7.2 P0 One-Shot Qualified Portable Transport'" in text
    assert "$_.name -eq $expectations.name" in text
    assert "path='.github/workflows/rc7.2-p0-one-shot-portable.yml'" in text
    assert "$_.path -eq $expectations.path" in text
    assert "branch='work/rc7.2-p0-final-transport-20261108'" in text
    assert "$_.head_branch -eq $expectations.branch" in text
    assert "$_.head_sha -eq $env:TARGET_MAIN_SHA" in text
    assert "$_.conclusion -eq 'success'" in text
    assert "C12_EXACT_SHA_VALID_ARTIFACT_MISSING_OR_AMBIGUOUS" in text
    assert "C12_ZIP_SHA256_BYTES_MISMATCH" in text
    assert "rc72_qa_zip_preflight.py" in text
    assert "rc72_qa_offline_audit.py" in text
    assert "gh run download" in text
    assert "rc7_release.rc72_package build" not in text
    assert "field_verified=$false" in text and "bank_final=$false" in text


def test_c12_one_shot_audit_caller_is_fenced_and_never_builds_package():
    text = (WORKFLOWS / "rc7.2-p1-c12-once.yml").read_text(encoding="utf-8")
    assert "work/rc7.2-p1-c12-verify-20261108" in text
    assert "\n  pull_request:" not in text.split("\njobs:", 1)[0]
    assert "cancel-in-progress: false" in text
    assert "needs: verify-exact-source" in text
    assert "uses: ./.github/workflows/rc7.2-qa-physical-transport.yml" in text
    assert "target_main_sha: 8c68f727ed4766111e6bdf5e6c8ca7728807aa36" in text
    assert "final_qualification: true" in text
    assert "rc7_release.rc72_package build" not in text


def test_c12_second_round_requires_same_sha_merged_source_and_one_shot_no_rebuild():
    audit = (WORKFLOWS / "rc7.2-qa-physical-transport.yml").read_text(encoding="utf-8")
    release = (WORKFLOWS / "rc7.2-p1-one-shot-portable.yml").read_text(encoding="utf-8")
    assert "source_round:" in audit and "C12_UNKNOWN_RELEASE_SOURCE_ROUND" in audit
    assert "C12_SOURCE_NOT_EXACT_MERGED_P1_PR" in audit
    assert "commits/$env:TARGET_MAIN_SHA/pulls?per_page=100" in audit
    assert "work/rc7.2-p1-stage-20261108" in audit
    assert "RC7.2 P1 One-Shot Qualified Portable Transport" in audit
    assert "work/rc7.2-p1-final-transport-20261108" in audit
    assert "source_workflow=$expectations.name" in audit
    assert "source_branch=$expectations.branch" in audit
    assert "rc7_release.rc72_package build" not in audit

    header = release.split("\njobs:", 1)[0]
    assert "work/rc7.2-p1-final-transport-20261108" in header
    assert "\n  pull_request:" not in header
    assert "cancel-in-progress: false" in release
    assert "git merge-base --is-ancestor" in release
    assert "listPullRequestsAssociatedWithCommit" in release
    assert "P1_FINAL_EXACT_MERGED_SOURCE_PR_REQUIRED" in release
    assert "P1_FINAL_CI_MISSING_OR_RED" in release
    assert "RC7.2 P1 Staging Contract Check (No ZIP)" in release
    assert "secrets: inherit" in release
    assert release.count("uses: ./.github/workflows/rc7.2-portable-transport.yml") == 1
    assert "final_qualification: true" in release


def test_p1_final_qualifies_runnable_worker_contract_and_independent_qa():
    source = (WORKFLOWS / "rc7.2-runtime-contracts.yml").read_text(encoding="utf-8")
    caller = (WORKFLOWS / "rc7.2-p1-one-shot-portable.yml").read_text(encoding="utf-8")
    assert "RC7.2 Runtime C06-C07 Contract Qualification" in caller
    assert "RC7.2 Independent QA Product and Transport" in caller
    trigger = source.split("\njobs:", 1)[0]
    assert "pull_request:" in trigger
    assert "- work/rc7.2" in trigger
    for path in (
        "rc6_runtime/agent_runtime.py",
        "rc7_runtime/model_resilience.py",
        "rc7_runtime/rc72_worker_lifecycle.py",
        "rc7_runtime/rc72_n5_data_discovery_handoff.py",
        "rc7_runtime/rc72_n5_data_verification_handoff.py",
        "rc7_runtime/rc72_n5_existing_data_repair.py",
        "tests/test_rc72_worker_process_environment.py",
        "tests/test_rc72_n5_data_discovery_handoff.py",
        "tests/test_rc72_n5_existing_data_repair.py",
    ):
        assert "'" + path + "'" in trigger
