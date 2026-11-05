from __future__ import annotations

from pathlib import Path

from rc7_release.package import SOURCE_DIRS
from rc7_release.windows_clean_qualification import REQUIRED_FIELD_HARDENED_FILES


ROOT = Path(__file__).resolve().parents[1]


def test_field_hardened_runtime_files_are_productized_by_package_source_dirs() -> None:
    assert "rc7_runtime" in SOURCE_DIRS
    assert "rc7_release" in SOURCE_DIRS
    required = set(REQUIRED_FIELD_HARDENED_FILES)
    assert "rc7_runtime/reality_recon.py" in required
    assert "rc7_runtime/mission_conformance.py" in required
    assert "rc7_runtime/mission_stage_dispatch.py" in required
    assert "rc7_release/windows_clean_qualification.py" in required
    for rel in required:
        assert (ROOT / rel).is_file(), rel


def test_final_ci_runs_windows_clean_session_qualification_from_the_only_certified_zip() -> None:
    workflow = (ROOT / ".github" / "workflows" / "rc7-field-hardening.yml").read_text(encoding="utf-8")

    # On ordinary feature commits there is no expensive intermediate ZIP.
    # The single final ZIP is gated by full source and same-head regressions.
    assert "final_qualification:" in workflow
    assert "default: false" in workflow
    assert workflow.count("if: github.event_name == 'workflow_dispatch' && inputs.final_qualification == true") == 2
    assert "field-hardened-package:" in workflow
    assert "      - field-hardening-source-regression" in workflow
    assert "      - rc7-source-suite" in workflow
    assert workflow.count("python -m rc7_release.package build --repo-root . --output") == 1

    # Real archive, checksum, independent extraction and package-local Python.
    assert workflow.count("Expand-Archive -LiteralPath $zip.FullName") == 2
    assert "Get-FileHash -LiteralPath $zip.FullName -Algorithm SHA256" in workflow
    assert "workspace-template\\runtime\\python\\python.exe" in workflow
    assert "& $certifiedPython -m rc7_release.runtime_turnkey_certificate verify --package-root $certifiedRoot --rerun-smoke" in workflow
    assert "& $certifiedPython -m rc7_release.windows_clean_qualification --package-root $certifiedRoot" in workflow
    assert "RC7 certified ZIP Windows clean-session qualification failed" in workflow
    assert "Qualify final package through real Git Bash entrypoint" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "dist/*.zip.sha256" in workflow
