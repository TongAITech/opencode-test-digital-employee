from __future__ import annotations

import os
from pathlib import Path

from rc7_release.delivery_qualification import qualify_delivery
from rc7_release.package import PACKAGE_NAME, build_package


COMMIT = "d" * 40


def _build_zip(tmp_path: Path) -> Path:
    repo = Path(__file__).resolve().parents[1]
    out = tmp_path / "dist"
    build_package(repo, out, COMMIT, make_zip=True)
    return out / ("%s-%s.zip" % (PACKAGE_NAME, COMMIT[:12]))


def test_delivery_qualification_executes_unpacked_package_not_source_tree(tmp_path):
    zip_path = _build_zip(tmp_path)
    result = qualify_delivery(zip_path=str(zip_path), source_commit=COMMIT)

    assert result["package_verify"] == "PASS"
    assert result["package_entrypoint_verify"] == "PASS"
    assert result["admin_startup_verify"] == "PASS"
    assert result["admin_health"]["truth"] == "R1_EVENT_STREAM"
    assert len(result["package_sha256"]) == 64
    assert result["package_name"] == PACKAGE_NAME

    if os.name == "nt":
        assert result["status"] == "PASS"
        assert result["clean_windows_unpack"] == "PASS"
        assert not result["blocking_reasons"]
    else:
        assert result["status"] == "HOLD"
        assert result["clean_windows_unpack"] == "HOLD_NON_WINDOWS"
        assert "CLEAN_WINDOWS_UNPACK_REQUIRES_WINDOWS_RUNTIME" in result["blocking_reasons"]


def test_delivery_qualification_rejects_package_from_other_commit(tmp_path):
    zip_path = _build_zip(tmp_path)
    result = qualify_delivery(zip_path=str(zip_path), source_commit="e" * 40)

    assert result["status"] == "HOLD"
    assert any("PACKAGE_SOURCE_COMMIT_MISMATCH" in reason for reason in result["blocking_reasons"])
