"""C12: synthetic PE fixture tests; never a claim of genuine approved DSH."""
import hashlib
import os
from pathlib import Path
import struct

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
