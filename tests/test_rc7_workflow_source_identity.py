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
    assert "name: Final certified offline ZIP: single build and independent re-extract" in content


def test_rc7_final_one_zip_certification_retains_clean_smoke_and_bank_profile_protection():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "final-certified-extract/PFC-AITest-DSH-Turnkey-RC7-BANK-WIN10" in content
    assert "rc7_release.runtime_turnkey_certificate verify --package-root $certifiedRoot --rerun-smoke" in content
    assert "name: Qualify final package through real Git Bash entrypoint" in content
    assert "grep -q" in content and "protected_bank_profile_integrity" in content
    assert "name: RC7-Field-Hardened-${{ env.RC7_PACKAGE_SOURCE_SHA }}" in content


def test_rc72_abcd_iterative_ci_defers_complete_chromium_and_full_source():
    path = WORKFLOW.with_name("rc7.2-abcd-v5-qualification.yml")
    content = path.read_text(encoding="utf-8")
    assert "full_qualification:" in content
    assert "default: false" in content
    assert "if: github.event_name == 'workflow_dispatch' && inputs.full_qualification == true" in content
    assert "c01-c10-engineering:" in content
    assert "tests/test_rc72_mission_factory.py" in content
    assert "Run every inherited RC7 and RC7.2 test module" in content
    assert "python -m pytest -q" in content
