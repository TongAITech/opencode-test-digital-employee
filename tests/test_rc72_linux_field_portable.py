"""RC7.2 Linux field transport — real host-negative/source-contract tests."""
import hashlib
import json
import os
import platform
import struct
from pathlib import Path

import pytest

from rc7_release.rc72_linux_field_portable import (
    NAME, REQUIRED, SCHEMA, LinuxFieldTransportError, _write_seal,
    inspect_linux_dsh, require_commit, verify_package,
)


def _fake_linux_package(tmp_path):
    root = tmp_path / NAME
    root.mkdir()
    commit = "a" * 40
    for rel in REQUIRED:
        if rel in ("LINUX_FIELD_PACKAGE.json", "CHECKSUMS.sha256"):
            continue
        file = root / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"owned-fixture")
    (root / "SOURCE_COMMIT").write_text(commit + "\n")
    meta = {
        "schema": SCHEMA, "package_name": NAME, "source_commit": commit,
        "platform": "linux", "architecture": "x86_64",
        "field_verified": False, "bank_final": False,
        "real_mission_pass": False, "q3_target_linux_verified": False,
        "dsh_main_payload": {"bundled": False},
        "restricted_graph_component": {"gitnexus_bundled": False},
    }
    _write_seal(root, meta)
    return root, commit


def test_sealed_package_verifier_checks_commit_every_file_and_false_field_claims(tmp_path):
    root, commit = _fake_linux_package(tmp_path)
    assert verify_package(root, commit)["status"] == "PASS"
    assert verify_package(root, commit)["bank_final"] is False
    with pytest.raises(LinuxFieldTransportError, match="SOURCE_COMMIT_MISMATCH"):
        verify_package(root, "b" * 40)
    target = root / "rc7_runtime/rc72_mission_factory.py"
    target.write_bytes(b"tampered")
    with pytest.raises(LinuxFieldTransportError, match="INTEGRITY_MISMATCH"):
        verify_package(root, commit)


def test_forged_field_pass_rejected(tmp_path):
    root, commit = _fake_linux_package(tmp_path)
    metadata = root / "LINUX_FIELD_PACKAGE.json"
    m = json.loads(metadata.read_text())
    m["field_verified"] = True
    metadata.write_text(json.dumps(m))
    with pytest.raises(LinuxFieldTransportError, match="FALSE_RELEASE_OR_FIELD_PASS"):
        verify_package(root, commit)


def test_polyform_or_dsh_bundle_cannot_be_silently_promoted(tmp_path):
    root, commit = _fake_linux_package(tmp_path)
    metadata = root / "LINUX_FIELD_PACKAGE.json"
    m = json.loads(metadata.read_text())
    m["restricted_graph_component"]["gitnexus_bundled"] = True
    metadata.write_text(json.dumps(m))
    with pytest.raises(LinuxFieldTransportError, match="NONCOMMERCIAL_GRAPH"):
        verify_package(root, commit)
    m["restricted_graph_component"]["gitnexus_bundled"] = False
    m["dsh_main_payload"]["bundled"] = True
    metadata.write_text(json.dumps(m))
    with pytest.raises(LinuxFieldTransportError, match="DSH_PAYLOAD_MUST_BE_EXTERNAL"):
        verify_package(root, commit)


def _linux_executable(tmp_path, kind="ELF64_X86_64", name="dsh"):
    f = tmp_path / name
    if kind == "ELF64_X86_64":
        payload = bytearray(128)
        payload[:4] = b"\x7fELF"
        payload[4] = 2
        payload[5] = 1
        struct.pack_into("<H", payload, 18, 62)
    elif kind == "ELF32":
        payload = bytearray(128)
        payload[:4] = b"\x7fELF"
        payload[4] = 1
    elif kind == "SHEBANG":
        payload = b"#!/usr/bin/env node\nconsole.log('dsh');\n"
    else:
        payload = b"random"
    f.write_bytes(payload)
    f.chmod(0o755)
    return f


@pytest.mark.skipif(platform.system() != "Linux", reason="native Linux executable mode required")
def test_external_linux_dsh_observation_does_not_claim_authorization(tmp_path):
    exe = _linux_executable(tmp_path)
    result = inspect_linux_dsh(exe)
    assert result["status"] == "EXTERNAL_LINUX_HOST_DSH_OBSERVED"
    assert result["executable_kind"] == "ELF64_X86_64"
    assert result["bank_authorization_verified"] is False
    assert result["vendor_identity_verified"] is False
    assert result["field_verified"] is False
    assert result["bank_final"] is False
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    assert inspect_linux_dsh(exe, digest)["expected_sha256_matched"] is True
    with pytest.raises(LinuxFieldTransportError, match="EXPECTED_SHA256_MISMATCH"):
        inspect_linux_dsh(exe, "0" * 64)


@pytest.mark.skipif(platform.system() != "Linux", reason="native Linux executable mode required")
def test_linux_host_binding_rejects_wrong_arch_symlink_and_renamed_executable(tmp_path):
    with pytest.raises(LinuxFieldTransportError, match="ELF64_REQUIRED"):
        inspect_linux_dsh(_linux_executable(tmp_path, "ELF32"))
    alias = tmp_path / "not-dsh"
    alias.symlink_to(tmp_path / "dsh")
    with pytest.raises(LinuxFieldTransportError, match="ABSOLUTE_REGULAR_FILE"):
        inspect_linux_dsh(alias)
    with pytest.raises(LinuxFieldTransportError, match="EXECUTABLE_NAME"):
        inspect_linux_dsh(_linux_executable(tmp_path, name="fake"))


@pytest.mark.skipif(platform.system() != "Linux", reason="native Linux executable mode required")
def test_linux_host_allows_explicit_approved_shebang_candidate_but_no_pass(tmp_path):
    exe = _linux_executable(tmp_path, "SHEBANG")
    receipt = inspect_linux_dsh(exe)
    assert receipt["executable_kind"] == "SHEBANG_SCRIPT"
    assert receipt["bank_final"] is False


def test_linux_workflow_is_native_not_windows_repackaged():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/rc7.2-linux-field-portable.yml").read_text()
    launcher = (root / "packaging/rc7.2/LINUX-FIELD-AITEST.sh").read_text()
    source = (root / "rc7_release/rc72_linux_field_portable.py").read_text()
    assert "ubuntu-22.04" in workflow
    assert "setup-uv" in workflow
    assert "node-version: '24.9.0'" in workflow
    assert "bsk-v0.4.1-x86_64-unknown-linux-musl.tar.gz" in workflow
    assert "rc72_linux_field_portable stage" in workflow
    assert "rc72_linux_field_portable verify" in workflow
    assert "rc72_linux_field_portable archive" in workflow
    assert "POLYFORM_NONCOMMERCIAL_LICENSE_GATE" in source
    assert "gitnexus_bundled" in source
    assert "PFC_RC72_DSH_LINUX_HOST_BIN" in launcher
    assert "PFC_RC72_LINUX_PROBE_ONLY" in launcher
    assert "exec \"$HOST_BIN\" \"$@\"" in launcher
    assert "Q3-FIELD-HANDOFF.sh" in launcher
    assert "workspace-template/runtime/python/python.exe" not in launcher


def test_invalid_source_commit_is_rejected():
    with pytest.raises(LinuxFieldTransportError, match="SOURCE_COMMIT_INVALID"):
        require_commit("not-a-commit")
