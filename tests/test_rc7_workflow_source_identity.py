"""Protect exact source identity in Windows offline transport artifacts.

A PR run's github.sha can be a synthetic test-merge SHA; the authenticated
archive must be attributable to the actual branch HEAD that QA inspected.
These source-level tests are intentionally independent of a CI runner.
"""
from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github" / "workflows" / "rc7-field-hardening.yml"
)


def test_rc7_transport_ci_pins_all_checkouts_to_actual_pr_head():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "RC7_PACKAGE_SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}" in content
    assert content.count("uses: actions/checkout@v4") == 3
    assert content.count("ref: ${{ env.RC7_PACKAGE_SOURCE_SHA }}") == 3


def test_rc7_transport_certification_rejects_source_identity_drift():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert content.count("$commit = (git rev-parse HEAD).Trim()") == 1
    assert content.count("$expected = $env:RC7_PACKAGE_SOURCE_SHA") == 1
    assert content.count("RC7_PACKAGE_SOURCE_IDENTITY_MISMATCH") == 1
    assert content.count("python -m rc7_release.package build --repo-root . --output") == 1
    assert "name: RC7-Field-Hardened-${{ env.RC7_PACKAGE_SOURCE_SHA }}" in content
    assert "name: RC7-Field-Hardened-${{ github.sha }}" not in content


def test_rc7_transport_provenance_test_runs_in_windows_and_ubuntu_regression():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "tests/test_rc7_workflow_source_identity.py" in content
    assert "find tests -maxdepth 1 -type f -name 'test_rc7*.py'" in content


def test_rc7_iterative_commits_run_source_only_and_never_package():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "final_qualification:" in content
    assert "type: boolean" in content
    assert "default: false" in content
    gate = "if: github.event_name == 'workflow_dispatch' && inputs.final_qualification == true"
    assert content.count(gate) == 2
    assert "windows-clean-qualification:" not in content
    assert content.count("python -m rc7_release.package build --repo-root . --output") == 1
    assert 'name: "Final certified offline ZIP: single build and independent re-extract"' in content


def test_rc7_final_one_zip_certification_retains_clean_smoke_and_bank_profile_protection():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "final-certified-extract/PFC-AITest-DSH-Turnkey-RC7-BANK-WIN10" in content
    assert "rc7_release.runtime_turnkey_certificate verify --package-root $certifiedRoot --rerun-smoke" in content
    assert "name: Qualify final package through real Git Bash entrypoint" in content
    assert "grep -q" in content and "protected_bank_profile_integrity" in content
    assert "name: RC7-Field-Hardened-${{ env.RC7_PACKAGE_SOURCE_SHA }}" in content


def test_rc72_abcd_iterative_ci_defers_complete_chromium_and_full_source():
    """Normal feature pushes remain bounded; only an explicit checkpoint is full."""
    path = WORKFLOW.with_name("rc7.2-abcd-v5-qualification.yml")
    content = path.read_text(encoding="utf-8")
    assert "full_qualification:" in content
    assert "default: false" in content

    # A normal push or PR must never run Chromium/full inherited regression.
    # An explicit reviewer-requested dispatch or a dedicated qualification
    # checkpoint is permitted and must fail closed if its job is skipped.
    full = content.split("  complete-rc7-with-real-chromium:\n", 1)[1].split(
        "  checkpoint-full-gate:\n", 1)[0]
    assert full.count("    if: >-") == 1
    condition = full.split("    if: >-\n", 1)[1].split("    runs-on:", 1)[0]
    assert "(github.event_name == 'workflow_dispatch' && inputs.full_qualification == true)" in condition
    assert "(github.event_name == 'push' && startsWith(github.event.head_commit.message, 'qualify(rc7.2):'))" in condition
    assert "github.event_name == 'pull_request'" not in condition
    assert "Run every inherited RC7 and RC7.2 test module" in full
    assert "tests/test_rc72_c09_real_chromium_cdp_smoke.py" in full

    checkpoint = content.split("  checkpoint-full-gate:\n", 1)[1]
    assert "needs: [complete-rc7-with-real-chromium]" in checkpoint
    assert "always()" in checkpoint
    assert "github.event_name == 'push'" in checkpoint
    assert "startsWith(github.event.head_commit.message, 'qualify(rc7.2):')" in checkpoint
    assert 'if [ "$FULL_JOB_RESULT" != "success" ]; then' in checkpoint
    assert "RC72_FULL_QUALIFICATION_NOT_PROVEN" in checkpoint

    assert "c01-c10-engineering:" in content
    assert "c07-issue7-product-admission:" in content
    assert "tests/test_rc72_mission_factory.py" in content
    assert "python -m pytest -q" in content


def test_rc72_targeted_ci_pull_request_paths_match_changed_product_slice():
    root = WORKFLOW.parents[2]
    for name, changed in [
        ("rc7.2-c04-professional-lineage.yml", [
            "rc7_runtime/rc72_n9_professional_intake.py",
            "tests/test_rc72_n9_professional_lineage.py",
        ]),
        ("rc7.2-c08-release-denominator.yml", [
            "rc7_runtime/rc72_release_driver.py",
            "rc7_release/rc72_mission_cli.py",
            "tests/test_rc72_release_driver.py",
        ]),
    ]:
        content = (root / ".github" / "workflows" / name).read_text(
            encoding="utf-8")
        pr = content.split("  pull_request:", 1)[1].split(
            "  workflow_dispatch:", 1)[0]
        assert "    paths:" in pr
        assert all("'" + path + "'" in pr for path in changed)
