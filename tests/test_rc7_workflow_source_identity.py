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
    assert content.count("uses: actions/checkout@v4") == 4
    assert content.count("ref: ${{ env.RC7_PACKAGE_SOURCE_SHA }}") == 4


def test_rc7_transport_certification_rejects_source_identity_drift():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert content.count("$commit = (git rev-parse HEAD).Trim()") == 2
    assert content.count("$expected = $env:RC7_PACKAGE_SOURCE_SHA") == 2
    assert content.count("RC7_PACKAGE_SOURCE_IDENTITY_MISMATCH") == 2
    assert content.count("python -m rc7_release.package build --repo-root . --output") == 2
    assert "name: RC7-Field-Hardened-${{ env.RC7_PACKAGE_SOURCE_SHA }}" in content
    assert "name: RC7-Field-Hardened-${{ github.sha }}" not in content


def test_rc7_transport_provenance_test_runs_in_windows_and_ubuntu_regression():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "tests/test_rc7_workflow_source_identity.py" in content
    assert "find tests -maxdepth 1 -type f -name 'test_rc7*.py'" in content
