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


def test_ci_has_real_windows_clean_package_qualification_before_final_rebuild() -> None:
    workflow = (ROOT / ".github" / "workflows" / "rc7-field-hardening.yml").read_text(encoding="utf-8")

    assert "windows-clean-qualification:" in workflow
    assert "name: Windows clean package qualification" in workflow
    assert "Expand-Archive" in workflow
    assert "workspace-template\\runtime\\python\\python.exe" in workflow
    assert "-m rc7_release.windows_clean_qualification" in workflow
    assert "field-hardened-package:" in workflow
    assert "needs: windows-clean-qualification" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "*.zip.sha256" in workflow
