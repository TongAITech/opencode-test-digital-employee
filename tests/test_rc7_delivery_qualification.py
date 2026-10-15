from __future__ import annotations

import hashlib
import os
from pathlib import Path

from rc7_release.delivery_qualification import qualify_delivery
from rc7_release.package import (
    PACKAGE_LOCAL_BROWSER,
    PACKAGE_LOCAL_CODEGRAPH,
    PACKAGE_NAME,
    build_package,
    verify_package,
)


COMMIT = "d" * 40


def _build_zip(tmp_path: Path) -> Path:
    repo = Path(__file__).resolve().parents[1]
    out = tmp_path / "dist"
    build_package(repo, out, COMMIT, make_zip=True)
    return out / ("%s-%s.zip" % (PACKAGE_NAME, COMMIT[:12]))


def test_delivery_qualification_without_build_payload_fails_closed_at_runtime_payloads(tmp_path):
    zip_path = _build_zip(tmp_path)
    result = qualify_delivery(zip_path=str(zip_path), source_commit=COMMIT)

    assert result["package_verify"] == "PASS"
    assert len(result["package_sha256"]) == 64
    assert result["package_name"] == PACKAGE_NAME
    assert result["qualification_kind"] == "CLEAN_TURNKEY_DELIVERY_PACKAGE_LOCAL_RUNTIME"
    assert result["status"] == "HOLD"
    assert result["package_local_codegraph_verify"] == "HOLD"
    assert result["package_local_browser_verify"] == "HOLD"
    assert any("PACKAGE_CODEGRAPH_NOT_BUNDLED" in reason for reason in result["blocking_reasons"])

    if os.name == "nt":
        assert result["clean_windows_unpack"] == "PASS"
        assert result["package_local_python_verify"] == "PASS"
    else:
        assert result["clean_windows_unpack"] == "HOLD_NON_WINDOWS"
        assert result["package_local_python_verify"] == "HOLD_NON_WINDOWS"
        assert "CLEAN_WINDOWS_UNPACK_REQUIRES_WINDOWS_RUNTIME" in result["blocking_reasons"]
        assert "PACKAGE_LOCAL_PYTHON_REQUIRES_WINDOWS_RUNTIME" in result["blocking_reasons"]
        assert "PACKAGE_LOCAL_CODEGRAPH_REQUIRES_WINDOWS_RUNTIME" in result["blocking_reasons"]
        assert "PACKAGE_LOCAL_BROWSER_REQUIRES_WINDOWS_RUNTIME" in result["blocking_reasons"]


def test_package_build_can_bind_codegraph_and_browser_payload_provenance(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]

    fake_codegraph = tmp_path / "codegraph-server-win32-x64.exe"
    fake_codegraph.write_bytes(b"fake-codegraph-build-payload")
    codegraph_digest = hashlib.sha256(fake_codegraph.read_bytes()).hexdigest()
    monkeypatch.setenv("PFC_RC7_BUILD_CODEGRAPH_BIN", str(fake_codegraph))
    monkeypatch.setenv("PFC_RC7_BUILD_CODEGRAPH_VERSION", "test-stable-codegraph")
    monkeypatch.setenv("PFC_RC7_BUILD_CODEGRAPH_SHA256", codegraph_digest)

    fake_browser_dir = tmp_path / "chrome-win64"
    fake_browser_dir.mkdir()
    fake_browser = fake_browser_dir / "chrome.exe"
    fake_browser.write_bytes(b"fake-browser-build-payload")
    browser_digest = hashlib.sha256(fake_browser.read_bytes()).hexdigest()
    (fake_browser_dir / "resources.pak").write_bytes(b"browser-support-file")
    monkeypatch.setenv("PFC_RC7_BUILD_BROWSER_DIR", str(fake_browser_dir))
    monkeypatch.setenv("PFC_RC7_BUILD_BROWSER_VERSION", "test-stable-browser")
    monkeypatch.setenv("PFC_RC7_BUILD_BROWSER_SHA256", browser_digest)

    package_root = build_package(repo, tmp_path / "with-runtimes", COMMIT, make_zip=False)
    verified = verify_package(package_root)
    assert verified["package_local_codegraph_bundled"] is True
    assert verified["package_local_codegraph_sha256"] == codegraph_digest
    assert verified["package_local_codegraph_version"] == "test-stable-codegraph"
    assert (package_root / PACKAGE_LOCAL_CODEGRAPH).read_bytes() == fake_codegraph.read_bytes()

    assert verified["package_local_browser_bundled"] is True
    assert verified["package_local_browser_sha256"] == browser_digest
    assert verified["package_local_browser_version"] == "test-stable-browser"
    assert (package_root / PACKAGE_LOCAL_BROWSER).read_bytes() == fake_browser.read_bytes()
    assert (package_root / PACKAGE_LOCAL_BROWSER.parent / "resources.pak").is_file()


def test_delivery_qualification_rejects_package_from_other_commit(tmp_path):
    zip_path = _build_zip(tmp_path)
    result = qualify_delivery(zip_path=str(zip_path), source_commit="e" * 40)

    assert result["status"] == "HOLD"
    assert any("PACKAGE_SOURCE_COMMIT_MISMATCH" in reason for reason in result["blocking_reasons"])
