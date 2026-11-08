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
    # Manual and qualified reusable entrypoints are supported, but NEVER
    # direct push/PR into the expensive build itself.
    assert "\n  workflow_call:" in before_jobs
    assert "\n  workflow_dispatch:" in before_jobs
    assert "if: inputs.final_qualification == true" in body
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


def test_one_shot_final_transport_requires_merged_pr_same_sha_and_all_checks():
    """One-shot caller is more restrictive than manual final_qualification."""
    body = _workflow("rc7.2-p0-one-shot-portable.yml")
    header = body.split("\njobs:", 1)[0]
    assert "work/rc7.2-p0-final-transport-20261108" in header
    assert "\n  pull_request:" not in header
    assert "cancel-in-progress: false" in header
    assert "actions: read" in body
    assert "pull-requests: read" in body
    assert "git merge-base --is-ancestor" in body
    assert "github.rest.pulls.get" in body
    assert "pull_number: 76" in body
    assert "pr.merged" in body
    assert "pr.head.sha !== context.sha" in body
    assert "pr.base.ref !== 'work/rc7.2'" in body
    assert "github.rest.actions.listWorkflowRunsForRepo" in body
    for exact_check in (
        "RC7.2 ABCD-v3 Same-HEAD Product and Independent QA Qualification",
        "RC7.2 ABCD-v4 Same-HEAD Product and Independent QA Qualification",
        "RC6 Wave 1 Runtime Kernel",
        "RC7.2 A N8 Multi-Round and Q7 CLI Side-Effect Admission",
    ):
        assert exact_check in body
    assert "run.conclusion === 'success'" in body
    assert "needs: qualify-source" in body
    assert "if: needs.qualify-source.result == 'success'" in body
    assert "uses: ./.github/workflows/rc7.2-portable-transport.yml" in body
    assert "final_qualification: true" in body


def test_one_shot_cannot_be_qualified_merely_by_a_documented_flag():
    """No unconditional package job before exact same-HEAD CI proof."""
    body = _workflow("rc7.2-p0-one-shot-portable.yml")
    assert "qualify-source:" in body
    assert body.index("qualify-source:") < body.index("build-and-verify-exact-qualified-sha:")
    assert "run.head_sha === context.sha" in body
    assert "missingOrRed" in body
    assert "all qualified PR checks" in body
