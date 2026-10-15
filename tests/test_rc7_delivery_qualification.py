from __future__ import annotations

import os
from pathlib import Path

from rc7_release.delivery_qualification import qualify_delivery
from rc7_release.package import PACKAGE_LOCAL_CODEGRAPH, PACKAGE_NAME, build_package, verify_package


COMMIT = "d" * 40


def _build_zip(tmp_path: Path) -> Path:
    repo = Path(__file__).resolve().parents[1]
    out = tmp_path / "dist"
    build_package(repo, out, COMMIT, make_zip=True)
    return out / ("%s-%s.zip" % (PACKAGE_NAME, COMMIT[:12]))


def test_delivery_qualification_without_build_payload_fails_closed_at_codegraph(tmp_path):
    zip_path = _build_zip(tmp_path)
    result = qualify_delivery(zip_path=str(zip_path), source_commit=COMMIT)

    assert result["package_verify"] == "PASS"
    assert len(result["package_sha256"]) == 64
    assert result["package_name"] == PACKAGE_NAME
    assert result["qualification_kind"] == "CLEAN_TURNKEY_DELIVERY_PACKAGE_LOCAL_RUNTIME"
    assert result["status"] == "HOLD"
    assert result["package_local_codegraph_verify"] == "HOLD"
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


def test_package_build_can_bind_codegraph_payload_with_hash_provenance(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    fake = tmp_path / "codegraph-server-win32-x64.exe"
    fake.write_bytes(b"fake-codegraph-build-payload")
    import hashlib
    digest = hashlib.sha256(fake.read_bytes()).hexdigest()
    monkeypatch.setenv("PFC_RC7_BUILD_CODEGRAPH_BIN", str(fake))
    monkeypatch.setenv("PFC_RC7_BUILD_CODEGRAPH_VERSION", "test-stable")
    monkeypatch.setenv("PFC_RC7_BUILD_CODEGRAPH_SHA256", digest)

    package_root = build_package(repo, tmp_path / "with-codegraph", COMMIT, make_zip=False)
    verified = verify_package(package_root)
    assert verified["package_local_codegraph_bundled"] is True
    assert verified["package_local_codegraph_sha256"] == digest
    assert verified["package_local_codegraph_version"] == "test-stable"
    assert (package_root / PACKAGE_LOCAL_CODEGRAPH).read_bytes() == fake.read_bytes()


def test_delivery_qualification_rejects_package_from_other_commit(tmp_path):
    zip_path = _build_zip(tmp_path)
    result = qualify_delivery(zip_path=str(zip_path), source_commit="e" * 40)

    assert result["status"] == "HOLD"
    assert any("PACKAGE_SOURCE_COMMIT_MISMATCH" in reason for reason in result["blocking_reasons"])
