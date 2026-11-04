"""All RC7.2 expensive transport builds are explicit FINAL gates.

Daily feature/defect commits must not download, rebuild or upload large offline
ZIP payloads. These tests are lightweight and execute with source regression.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _workflow(filename):
    return (ROOT / filename).read_text(encoding="utf-8")


def test_portable_transport_requires_explicit_final_dispatch():
    body = _workflow("rc7.2-portable-transport.yml")
    before_jobs = body.split("\njobs:", 1)[0]
    assert "\n  push:" not in before_jobs
    assert "\n  pull_request:" not in before_jobs
    assert "final_qualification:" in before_jobs
    assert "default: false" in before_jobs
    assert "if: github.event_name == 'workflow_dispatch' && inputs.final_qualification == true" in body
    assert "rc7_release.rc72_package build" in body


def test_q2_windows_clean_unpack_is_final_only_and_still_proves_real_zip():
    body = _workflow("rc7.2-windows-clean-unpack.yml")
    before_jobs = body.split("\njobs:", 1)[0]
    assert "\n  push:" not in before_jobs
    assert "\n  pull_request:" not in before_jobs
    assert "final_qualification:" in before_jobs
    assert "default: false" in before_jobs
    assert "if: github.event_name == 'workflow_dispatch' && inputs.final_qualification == true" in body
    assert "rc7_release.rc72_package build" in body
    assert "Expand-Archive" in body
    assert ".sha256" in body


def test_c12_independent_physical_audit_consumes_final_zip_only():
    body = _workflow("rc7.2-qa-physical-transport.yml")
    before_jobs = body.split("\njobs:", 1)[0]
    assert "\n  pull_request:" not in before_jobs
    assert "target_main_sha:" in before_jobs
    assert "final_qualification:" in before_jobs
    assert "default: false" in before_jobs
    assert "if: github.event_name == 'workflow_dispatch' && inputs.final_qualification == true" in body
    assert "rc72_qa_zip_preflight.py" in body
    assert "actions/runs?head_sha=" in body
    assert "RC72-PORTABLE-WIN10-" in body


def test_construction_ci_requires_manual_final_packaging_not_repeated_on_pr():
    body = _workflow("rc7-field-hardening.yml")
    assert body.count(
        "if: github.event_name == 'workflow_dispatch' && inputs.final_qualification == true"
    ) == 2
    assert body.count("python -m rc7_release.package build --repo-root . --output") == 1
