"""C12: synthetic PE fixture tests; never a claim of genuine approved DSH."""
import hashlib
import os
from pathlib import Path
import struct
from urllib.error import HTTPError
from rc7_release import rc72_dsh_main_payload as source_module

import pytest

from rc7_release.rc72_dsh_main_payload import (
    DshMainPayloadError, DSH_RELATIVE_PATH, materialize,
)
from tools.rc72_qa_offline_audit import _native_dsh_executable



def _package(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "SOURCE_COMMIT").write_text("a" * 40)
    return package


def _fixture_binary(tmp_path, *, architecture=0x8664, magic=0x20B):
    """Produce just a structural PE fixture, NOT a runnable program."""
    payload = bytearray(8192)
    payload[0:2] = b"MZ"
    struct.pack_into("<I", payload, 0x3c, 0x80)
    payload[0x80:0x84] = bytes((80, 69, 0, 0))
    struct.pack_into("<H", payload, 0x84, architecture)
    struct.pack_into("<H", payload, 0x98, magic)
    source = tmp_path / "stub.exe"
    source.write_bytes(bytes(payload))
    return source, hashlib.sha256(payload).hexdigest()


def test_pinned_native_main_is_copied_and_idempotent_without_external_io(tmp_path):
    root = _package(tmp_path)
    source, digest = _fixture_binary(tmp_path)
    result = materialize(root, expected_sha256=digest, source_file=source)
    target = root / DSH_RELATIVE_PATH
    assert result["status"] == "PHYSICAL_CANDIDATE_ONLY"
    assert result["field_verified"] is False and result["bank_final"] is False
    assert target.read_bytes() == source.read_bytes()
    assert materialize(root, expected_sha256=digest, source_file=source)["sha256"] == digest


@pytest.mark.parametrize("invalid", ["", "0" * 64, "f" * 65, "invalid"])
def test_bad_source_hash_fail_closed_before_copy(tmp_path, invalid):
    root = _package(tmp_path)
    source, digest = _fixture_binary(tmp_path)
    with pytest.raises(DshMainPayloadError):
        materialize(root, expected_sha256=invalid, source_file=source)
    assert not (root / DSH_RELATIVE_PATH).exists()


@pytest.mark.parametrize("architecture,magic", [(0x14c, 0x20B), (0x8664, 0x10B)])
def test_invalid_windows_architecture_rejected(tmp_path, architecture, magic):
    root = _package(tmp_path)
    source, digest = _fixture_binary(tmp_path, architecture=architecture, magic=magic)
    with pytest.raises(DshMainPayloadError):
        materialize(root, expected_sha256=digest, source_file=source)
    assert not (root / DSH_RELATIVE_PATH).exists()


def test_replacing_main_with_different_approved_digest_never_overwrites(tmp_path):
    root = _package(tmp_path)
    source, digest = _fixture_binary(tmp_path)
    materialize(root, expected_sha256=digest, source_file=source)
    other = tmp_path / "alternate.exe"
    other.write_bytes(source.read_bytes() + b"changed")
    other_digest = hashlib.sha256(other.read_bytes()).hexdigest()
    with pytest.raises(DshMainPayloadError, match="EXISTING_TARGET_CONFLICT"):
        materialize(root, expected_sha256=other_digest, source_file=other)
    assert (root / DSH_RELATIVE_PATH).read_bytes() == source.read_bytes()


def test_unapproved_or_mixed_source_never_accepted(tmp_path):
    root = _package(tmp_path)
    source, digest = _fixture_binary(tmp_path)
    with pytest.raises(DshMainPayloadError, match="EXACTLY_ONE"):
        materialize(root, expected_sha256=digest)
    with pytest.raises(DshMainPayloadError, match="EXACTLY_ONE"):
        materialize(root, expected_sha256=digest, source_file=source,
                    source_url="https://example.com/dsh.exe")
    with pytest.raises(DshMainPayloadError, match="APPROVED_HTTPS"):
        materialize(root, expected_sha256=digest, source_url="file:///bank/dsh.exe")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="platform symlink unsupported")
def test_symlink_target_is_never_overwritten(tmp_path):
    root = _package(tmp_path)
    source, digest = _fixture_binary(tmp_path)
    target = root / "workspace-template/runtime/dsh"
    target.mkdir(parents=True)
    try:
        (target / "dsh.exe").symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not authorized by host")
    with pytest.raises(DshMainPayloadError, match="SYMLINK"):
        materialize(root, expected_sha256=digest, source_file=source)


def test_build_and_bank_launcher_require_genuine_package_local_main():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/rc7.2-portable-transport.yml").read_text(encoding="utf-8")
    launcher = (root / "packaging/rc7.2/AITEST.sh").read_text(encoding="utf-8")
    assert "RC72_DSH_MAIN_APPROVED_SOURCE_AND_SHA256_REQUIRED" in workflow
    assert "rc7_release.rc72_dsh_main_payload" in workflow
    assert "approved-dsh-main.json" in workflow
    assert workflow.index("rc72_dsh_main_payload") < workflow.index("_rewrite_manifest")
    assert 'secrets.RC72_DSH_MAIN_URL' in workflow
    assert "vars.RC72_DSH_MAIN_SHA256" in workflow
    assert "DSH_MAIN=\"$ROOT/workspace-template/runtime/dsh/dsh.exe\"" in launcher
    assert "export PATH=\"$DSH_PATH_DIR:$PATH\"" in launcher
    assert "Package-local DSH bound" in launcher


def test_c12_independent_qa_physically_checks_pe32plus_and_amd64(tmp_path):
    source, digest = _fixture_binary(tmp_path)
    assert _native_dsh_executable(source, DSH_RELATIVE_PATH) is True
    wrong_machine, _ = _fixture_binary(tmp_path, architecture=0x14c)
    assert _native_dsh_executable(wrong_machine, DSH_RELATIVE_PATH) is False
    wrong_optional_header, _ = _fixture_binary(tmp_path, magic=0x10B)
    assert _native_dsh_executable(wrong_optional_header, DSH_RELATIVE_PATH) is False


def test_remote_approved_source_denies_redirect_before_any_payload(monkeypatch, tmp_path):
    """A cross-host redirect may not inherit the approved vendor/bank token."""
    visited = []
    class RedirectingOpener:
        def open(self, request, timeout):
            visited.append(request.full_url)
            assert request.get_header("Authorization") == "Bearer synthetic-test-token"
            raise HTTPError(request.full_url, 302, "Redirect", {
                "Location": "https://other-host.example/unauthorized.exe"}, None)
    def opener(*handlers):
        assert len(handlers) == 1
        assert isinstance(handlers[0], source_module._DenyRedirect)
        return RedirectingOpener()
    monkeypatch.setattr(source_module, "build_opener", opener)
    monkeypatch.setenv("RC72_DSH_MAIN_AUTHORIZATION", "Bearer synthetic-test-token")
    target = tmp_path / "no-redirected-binary"
    with pytest.raises(DshMainPayloadError, match="HTTP_REDIRECT_FORBIDDEN"):
        source_module._stream_download("https://approved.example/dsh.exe", target)
    assert visited == ["https://approved.example/dsh.exe"]
    assert not target.exists()


def test_remote_approved_source_does_not_disclose_transport_error(monkeypatch, tmp_path):
    from urllib.error import URLError
    class FailingOpener:
        def open(self, request, timeout):
            raise URLError("synthetic-private-approved-token")
    monkeypatch.setattr(source_module, "build_opener", lambda *args: FailingOpener())
    with pytest.raises(DshMainPayloadError, match="DSH_MAIN_HTTPS_FETCH_FAILED") as exc:
        source_module._stream_download("https://approved.example/dsh.exe",
                                       tmp_path / "no-secret-output")
    assert "synthetic-private-approved-token" not in str(exc.value)
    assert not (tmp_path / "no-secret-output").exists()


def test_remote_approved_source_rejects_authorization_header_newlines(monkeypatch, tmp_path):
    monkeypatch.setenv("RC72_DSH_MAIN_AUTHORIZATION", "Bearer test\nX-Leak: test")
    with pytest.raises(DshMainPayloadError, match="AUTHORIZATION_HEADER_INVALID"):
        source_module._stream_download("https://approved.example/dsh.exe",
                                       tmp_path / "invalid-header")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="platform symlink unsupported")
def test_parent_runtime_symlink_cannot_redirect_approved_main_outside_package(tmp_path):
    root = _package(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    nested = root / "workspace-template"
    try:
        nested.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation not permitted")
    source, digest = _fixture_binary(tmp_path)
    with pytest.raises(DshMainPayloadError, match="TARGET_SYMLINK_OR_NONDIR"):
        materialize(root, expected_sha256=digest, source_file=source)
    assert not (outside / "runtime/dsh/dsh.exe").exists()


def test_local_approved_main_rejects_oversized_source_before_copy(tmp_path):
    from rc7_release.rc72_dsh_main_payload import MAX_SIZE
    root = _package(tmp_path)
    large = tmp_path / "oversized.exe"
    with large.open("wb") as file:
        file.seek(MAX_SIZE)
        file.write(b"X")
    with pytest.raises(DshMainPayloadError, match="BINARY_SIZE_INVALID"):
        materialize(root, expected_sha256="a" * 64, source_file=large)
    assert not (root / DSH_RELATIVE_PATH).exists()
