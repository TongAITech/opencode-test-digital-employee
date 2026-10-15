from __future__ import annotations

import json
from pathlib import Path

from rc7_release.package import ENTRYPOINTS, build_package, verify_package


COMMIT = "f" * 40
BANK_FINAL_NAMES = ("QUALIFY-BANK-FINAL.cmd", "QUALIFY-BANK-FINAL.sh")
BUNDLED_PYTHON = r"workspace-template\runtime\python\python.exe"
PYTHON_BIN_ENTRYPOINTS = (
    "QUALIFY-DSH-REQUIREMENT.cmd",
    "QUALIFY-DSH-CODE.cmd",
    "QUALIFY-DSH-TEST-DESIGN.cmd",
    "QUALIFY-DSH-SCRIPT.cmd",
    "QUALIFY-EXECUTION.cmd",
)


def test_bank_final_entrypoints_are_fail_closed_operator_contracts():
    repo = Path(__file__).resolve().parents[1]
    for name in BANK_FINAL_NAMES:
        relative = "packaging/rc7/%s" % name
        assert relative in ENTRYPOINTS
        text = (repo / "packaging" / "rc7" / name).read_text(encoding="utf-8")
        assert "PFC_RC7_R1_PATH" in text
        assert "PFC_RC7_MISSION_ID" in text
        assert "PFC_RC7_ENGINEERING_EVIDENCE" in text
        assert "PFC_RC7_ADMIN_EVIDENCE" in text
        assert "PFC_RC7_DELIVERY_EVIDENCE" in text
        assert "PFC_RC7_REQUIRE_FINAL_PASS" in text
        assert "QUALIFY-FINAL" in text
        assert "REAL_MISSION_PASS" not in text
        assert "BLOAN-PF" not in text


def test_windows_final_entrypoints_prefer_bundled_python_before_host_fallback():
    repo = Path(__file__).resolve().parents[1]
    bundled = (
        f'if not defined PFC_PYTHON if exist "%ROOT%\\{BUNDLED_PYTHON}" '
        f'set "PFC_PYTHON=%ROOT%\\{BUNDLED_PYTHON}"'
    )
    fallback = 'if not defined PFC_PYTHON set "PFC_PYTHON=python"'
    for name in ("QUALIFY-BANK-FINAL.cmd", "QUALIFY-FINAL.cmd"):
        text = (repo / "packaging" / "rc7" / name).read_text(encoding="utf-8")
        assert bundled in text
        assert fallback in text
        assert text.index(bundled) < text.index(fallback)


def test_windows_stage_qualification_entrypoints_prefer_bundled_python_before_path_lookup():
    repo = Path(__file__).resolve().parents[1]
    bundled = (
        f'if not defined PYTHON_BIN if exist "%ROOT%\\{BUNDLED_PYTHON}" '
        f'set "PYTHON_BIN=%ROOT%\\{BUNDLED_PYTHON}"'
    )
    host_lookup = "where python"
    for name in PYTHON_BIN_ENTRYPOINTS:
        text = (repo / "packaging" / "rc7" / name).read_text(encoding="utf-8")
        assert bundled in text
        assert host_lookup in text
        assert text.index(bundled) < text.index(host_lookup)


def test_windows_admin_entrypoint_prefers_bundled_python_before_host_fallback():
    repo = Path(__file__).resolve().parents[1]
    text = (repo / "packaging" / "rc7" / "START-RC7-ADMIN.cmd").read_text(encoding="utf-8")
    bundled = (
        f'if not defined PFC_PYTHON_BIN if exist "%ROOT%\\{BUNDLED_PYTHON}" '
        f'set "PFC_PYTHON_BIN=%ROOT%\\{BUNDLED_PYTHON}"'
    )
    fallback = 'if not defined PFC_PYTHON_BIN set "PFC_PYTHON_BIN=python"'
    assert bundled in text
    assert fallback in text
    assert text.index(bundled) < text.index(fallback)


def test_bank_final_entrypoints_are_manifested_checksummed_and_packaged(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    package_root = build_package(repo, tmp_path / "dist", COMMIT, make_zip=False)
    verified = verify_package(package_root)
    assert verified["status"] == "PASS"

    manifest = json.loads((package_root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    checksums = (package_root / "CHECKSUMS.sha256").read_text(encoding="utf-8")
    for name in BANK_FINAL_NAMES:
        relative = "packaging/rc7/%s" % name
        assert (package_root / relative).is_file()
        assert relative in manifest["entrypoints"]
        assert ("  %s" % relative) in checksums
