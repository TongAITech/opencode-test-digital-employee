"""Adversarial tests for external bank-host DSH binding; no fake Field PASS."""
import hashlib
import json
from pathlib import Path
import struct

import pytest

from rc7_release.rc72_dsh_host_binding import (
    DshHostBindingError,
    inspect_host_dsh,
    main,
)


def _pe(tmp_path, *, machine=0x8664, magic=0x20B, name="dsh.exe"):
    data = bytearray(8192)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<H", data, 0x84, machine)
    struct.pack_into("<H", data, 0x98, magic)
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_host_binding_records_only_observation_and_never_authorization(tmp_path):
    exe = _pe(tmp_path)
    result = inspect_host_dsh(exe)
    assert result["status"] == "EXTERNAL_HOST_DSH_OBSERVED"
    assert result["binding_mode"] == "EXPLICIT_BANK_HOST_EXECUTABLE"
    assert result["pe32_plus_amd64_shape"] is True
    assert result["vendor_identity_verified"] is False
    assert result["bank_authorization_verified"] is False
    assert result["redistribution_authorized"] is False
    assert result["field_verified"] is False
    assert result["bank_final"] is False
    assert result["sha256"] == hashlib.sha256(exe.read_bytes()).hexdigest()


def test_optional_independent_sha256_must_match_exact_host_bytes(tmp_path):
    exe = _pe(tmp_path)
    expected = hashlib.sha256(exe.read_bytes()).hexdigest()
    assert inspect_host_dsh(exe, expected)["expected_sha256_matched"] is True
    with pytest.raises(DshHostBindingError, match="EXPECTED_SHA256_MISMATCH"):
        inspect_host_dsh(exe, "0" * 64)


@pytest.mark.parametrize("machine,magic", [(0x14C, 0x20B), (0x8664, 0x10B)])
def test_non_amd64_or_pe32_host_executable_is_rejected(tmp_path, machine, magic):
    exe = _pe(tmp_path, machine=machine, magic=magic)
    with pytest.raises(DshHostBindingError, match="NOT_PE32_PLUS_AMD64"):
        inspect_host_dsh(exe)


def test_host_binding_requires_absolute_regular_non_symlink_dsh_exe(tmp_path):
    exe = _pe(tmp_path)
    with pytest.raises(DshHostBindingError, match="ABSOLUTE"):
        inspect_host_dsh(Path("dsh.exe"))
    alias = tmp_path / "alias.exe"
    try:
        alias.symlink_to(exe)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(DshHostBindingError, match="NOT_REGULAR_FILE"):
        inspect_host_dsh(alias)


def test_host_binding_rejects_renamed_non_dsh_executable(tmp_path):
    exe = _pe(tmp_path, name="not-dsh.exe")
    with pytest.raises(DshHostBindingError, match="NAME_MUST_BE_DSH_EXE"):
        inspect_host_dsh(exe)


def test_cli_writes_receipt_and_never_claims_field_pass(tmp_path, capsys):
    exe = _pe(tmp_path)
    receipt = tmp_path / "state" / "dsh-host-binding.json"
    expected = hashlib.sha256(exe.read_bytes()).hexdigest()
    code = main(["--executable", str(exe), "--expected-sha256", expected,
                 "--output", str(receipt)])
    output = json.loads(capsys.readouterr().out)
    saved = json.loads(receipt.read_text(encoding="utf-8"))
    assert code == 0
    assert output == saved
    assert saved["field_verified"] is False
    assert saved["bank_final"] is False


def test_rc72_launcher_supports_exact_external_host_binding_and_keeps_local_preference():
    root = Path(__file__).resolve().parents[1]
    source = (root / "packaging/rc7.2/AITEST.sh").read_text(encoding="utf-8")
    assert 'DSH_MAIN="$ROOT/workspace-template/runtime/dsh/dsh.exe"' in source
    assert 'PFC_RC72_DSH_HOST_BIN' in source
    assert 'PFC_RC72_DSH_HOST_SHA256' in source
    assert 'rc7_release.rc72_dsh_host_binding' in source
    assert 'DSH_EXPECTED_NATIVE' in source
    assert 'DSH_RESOLVED_NATIVE' in source
    assert 'command -v cygpath' in source
    assert 'exec "$DELEGATE"' in source
    assert 'bank_authorization_verified' not in source


def test_rc72_field_and_final_transport_builds_use_node_24_for_dsh_cli_engine():
    root = Path(__file__).resolve().parents[1]
    field = (root / ".github/workflows/rc7.2-field-validation-portable.yml").read_text(encoding="utf-8")
    final = (root / ".github/workflows/rc7.2-portable-transport.yml").read_text(encoding="utf-8")
    assert "node-version: '24.9.0'" in field
    assert "node-version: '24.9.0'" in final
    assert "RC7.2 packaged Node >=24.9.0 required" in field


def test_start_launcher_prompts_only_when_package_does_not_bundle_dsh():
    root = Path(__file__).resolve().parents[1]
    source = (root / "packaging/rc7.2/start-rc7.2.cmd").read_text(encoding="utf-8")
    assert "PFC_RC72_DSH_HOST_BIN" in source
    assert "set /p" in source
    assert "workspace-template\\runtime\\dsh\\dsh.exe" in source
