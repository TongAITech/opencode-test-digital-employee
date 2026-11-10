"""C12 local bank-approved source, no fake ZIP qualification from PE fixtures."""
import hashlib
import json
import os
from pathlib import Path
import struct
import zipfile

import pytest

from rc7_release.rc72_c12_local_portable import (
    LocalC12Error, _safe_extract_zip, build, main, preflight,
)

SOURCE = "a" * 40


def _inputs(tmp_path, *, architecture=0x8664, magic=0x20B):
    binary = bytearray(8192)
    binary[0:2] = b"MZ"
    struct.pack_into("<I", binary, 0x3c, 0x80)
    binary[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<H", binary, 0x84, architecture)
    struct.pack_into("<H", binary, 0x98, magic)
    exe = tmp_path / "synthetic-only-not-real-dsh.exe"
    exe.write_bytes(binary)
    record = tmp_path / "external-approval.txt"
    record.write_text("TEST-FIXTURE-ONLY-NOT-BANK-APPROVED", encoding="utf-8")
    return dict(
        source_commit=SOURCE, dsh_file=str(exe),
        dsh_sha256=hashlib.sha256(binary).hexdigest(),
        approval_record=str(record),
    )


def test_preflight_is_read_only_and_never_claims_signed_bank_proof(tmp_path):
    data = _inputs(tmp_path)
    before = {x.name: x.read_bytes() for x in tmp_path.iterdir()}
    result = preflight(**data)
    assert result["status"] == "SOURCE_BYTES_PRECHECK_ONLY"
    assert result["package_built"] is False
    assert result["field_verified"] is False
    assert result["bank_final"] is False
    assert result["external_approval_authenticity_verified"] is False
    assert result["dsh_main_sha256"] == data["dsh_sha256"]
    assert {x.name: x.read_bytes() for x in tmp_path.iterdir()} == before


@pytest.mark.parametrize("bad", ["", "not-a-sha", "f" * 65])
def test_wrong_hash_format_fails_before_build(tmp_path, bad):
    data = _inputs(tmp_path)
    data["dsh_sha256"] = bad
    with pytest.raises(LocalC12Error, match="INDEPENDENT_64_HEX"):
        preflight(**data)


def test_wrong_independent_sha_fails_before_zip(tmp_path):
    data = _inputs(tmp_path)
    data["dsh_sha256"] = "0" * 64
    with pytest.raises(LocalC12Error, match="SHA256_MISMATCH"):
        preflight(**data)
    assert not list(tmp_path.glob("*.zip"))


def test_missing_external_approval_record_not_a_positive_receipt(tmp_path):
    data = _inputs(tmp_path)
    Path(data["approval_record"]).unlink()
    with pytest.raises(LocalC12Error, match="EXTERNAL_APPROVAL_DOCUMENT_REQUIRED"):
        preflight(**data)


def test_empty_approval_record_and_exe_as_record_rejected(tmp_path):
    data = _inputs(tmp_path)
    Path(data["approval_record"]).write_bytes(b"")
    with pytest.raises(LocalC12Error, match="DOCUMENT_SIZE_INVALID"):
        preflight(**data)
    data["approval_record"] = data["dsh_file"]
    with pytest.raises(LocalC12Error, match="MUST_BE_DISTINCT"):
        preflight(**data)


@pytest.mark.parametrize("arch,magic", [(0x14c, 0x20B), (0x8664, 0x10B)])
def test_unapproved_wrong_machine_or_pe32_rejected(tmp_path, arch, magic):
    data = _inputs(tmp_path, architecture=arch, magic=magic)
    with pytest.raises(LocalC12Error, match="REAL_WINDOWS_X64_PE_REQUIRED"):
        preflight(**data)


def test_symlinked_dsh_and_approval_rejected(tmp_path):
    data = _inputs(tmp_path)
    alias = tmp_path / "alias.exe"
    try:
        alias.symlink_to(data["dsh_file"])
    except (OSError, NotImplementedError):
        pytest.skip("symlink not permitted by OS")
    data["dsh_file"] = str(alias)
    with pytest.raises(LocalC12Error, match="REAL_LOCAL_MAIN_FILE_REQUIRED"):
        preflight(**data)
    data["dsh_file"] = str(tmp_path / "synthetic-only-not-real-dsh.exe")
    approval_alias = tmp_path / "alias.approval"
    approval_alias.symlink_to(data["approval_record"])
    data["approval_record"] = str(approval_alias)
    with pytest.raises(LocalC12Error, match="EXTERNAL_APPROVAL_DOCUMENT_REQUIRED"):
        preflight(**data)


def test_invalid_source_commit_rejected(tmp_path):
    data = _inputs(tmp_path)
    data["source_commit"] = "not-an-exact-commit"
    with pytest.raises(LocalC12Error, match="EXACT_40_HEX"):
        preflight(**data)


def test_non_windows_host_cannot_claim_actual_zip_or_start_network(tmp_path):
    if os.name == "nt":
        pytest.skip("non-Windows boundary exercised on Linux CI")
    data = _inputs(tmp_path)
    with pytest.raises(LocalC12Error, match="REAL_WINDOWS_BUILD_HOST_REQUIRED"):
        build(repo_root=tmp_path, output=tmp_path / "dist", **data)
    assert not (tmp_path / "dist").exists()


def test_cli_bogus_main_returns_hold_not_pass(tmp_path, capsys):
    data = _inputs(tmp_path)
    code = main([
        "build", "--repo-root", str(tmp_path), "--output", str(tmp_path / "dist"),
        "--source-commit", data["source_commit"],
        "--dsh-file", data["dsh_file"], "--dsh-sha256", "0" * 64,
        "--approval-record", data["approval_record"],
    ])
    output = json.loads(capsys.readouterr().out)
    assert code == 2
    assert output["status"] == "HOLD"
    assert output["bank_final"] is False
    assert not (tmp_path / "dist").exists()


@pytest.mark.parametrize("entry", [
    "../stolen.txt",
    "package/../../stolen.txt",
    "/package/exfiltrate.txt",
    "another-package/file.txt",
    "package\\..\\stolen.txt",
])
def test_clean_unzip_refuses_path_escapes(tmp_path, entry):
    archive = tmp_path / "adversarial.zip"
    with zipfile.ZipFile(str(archive), "w") as z:
        z.writestr(entry, b"evil")
    with pytest.raises(LocalC12Error, match="ZIP_ENTRY_OUTSIDE_PACKAGE"):
        _safe_extract_zip(archive, tmp_path / "extract", "package")
    assert not (tmp_path / "stolen.txt").exists()


def test_clean_unzip_refuses_unix_symlink_member(tmp_path):
    archive = tmp_path / "adversarial.zip"
    info = zipfile.ZipInfo("package/link")
    info.create_system = 3
    info.external_attr = 0o120777 << 16
    with zipfile.ZipFile(str(archive), "w") as z:
        z.writestr(info, "outside")
    with pytest.raises(LocalC12Error, match="ZIP_SYMLINK_FORBIDDEN"):
        _safe_extract_zip(archive, tmp_path / "extract", "package")


def test_safe_zip_extract_does_not_forge_field_acceptance(tmp_path):
    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(str(archive), "w") as z:
        z.writestr("package/test.txt", "data")
    _safe_extract_zip(archive, tmp_path / "extract", "package")
    assert (tmp_path / "extract/package/test.txt").read_text() == "data"


def test_clean_q2_checks_and_independent_audit_bind_exact_commit(tmp_path, monkeypatch):
    from rc7_release import rc72_c12_local_portable as c12
    called = []

    def record(*args, cwd, env=None):
        called.append((tuple(str(x) for x in args), str(cwd), env))
        return ""

    monkeypatch.setattr(c12, "_run", record)
    root = tmp_path / "repo"
    extracted = tmp_path / "extract"
    py = extracted / "workspace-template/runtime/python/python.exe"
    archive = tmp_path / "signed-package.zip"
    stage = tmp_path / "build-stage"
    c12._qualify_extracted(
        python=py, extracted=extracted, repo=root,
        source_commit=SOURCE, evidence_path=tmp_path / "c12-clean-runtime.json",
        zip_path=archive, original_stage=stage)
    assert len(called) == 8
    assert called[0][0][1:4] == ("-m", "rc7_release.rc72_package", "verify")
    assert "--expected-source-commit" in called[0][0]
    assert called[0][0][-1] == SOURCE
    assert called[2][0][2] == "rc7_release.rc72_complete_payload_inventory"
    assert "--require-pass" in called[3][0]
    assert called[4][0][1] == "-I"
    assert called[4][0][2].endswith("python_full_capability_probe.py")
    assert called[5][0][2] == "rc7_release.rc72_execution_node_qualification"
    assert "--require-windows-outbound-block" in called[5][0]
    assert "--require-full-text-search" in called[5][0]
    assert called[6][0][1].endswith("tools/rc72_qa_offline_audit.py") or (
        called[6][0][1].endswith("tools\\rc72_qa_offline_audit.py"))
    assert called[6][0][-2:] == ("--expected-source-commit", SOURCE)
    assert called[7][0][1:3] == ("-m", "pytest")
    env = called[7][2]
    assert env["RC72_PIP_MIRROR_COMPONENT"] == "1"
    assert env["RC72_PIP_MIRROR_PACKAGE_ARCHIVE"] == str(archive)
    assert env["RC72_PIP_MIRROR_PACKAGE_ROOT"] == str(extracted)
    assert env["RC72_PIP_MIRROR_ORIGINAL_STAGE"] == str(stage)


def test_independent_q2_failed_check_never_swallowed(tmp_path, monkeypatch):
    from rc7_release import rc72_c12_local_portable as c12

    def fail(*args, cwd, env=None):
        raise c12.LocalC12Error("C12_OFFLINE_Q2_CHECK_FAILED")

    monkeypatch.setattr(c12, "_run", fail)
    with pytest.raises(LocalC12Error, match="Q2_CHECK_FAILED"):
        c12._qualify_extracted(
            python=tmp_path / "python.exe", extracted=tmp_path,
            repo=tmp_path, source_commit=SOURCE,
            evidence_path=tmp_path / "report.json",
            zip_path=tmp_path / "zip.zip", original_stage=tmp_path / "stage")


def test_isolated_node_outbound_block_adds_and_always_removes_scoped_rule(tmp_path, monkeypatch):
    from rc7_release import rc72_c12_local_portable as c12
    node = tmp_path / "node.exe"
    node.write_bytes(b"test-only-not-a-node-runtime")
    scripts = []

    def capture(script, *, cwd):
        scripts.append((script, str(cwd)))

    monkeypatch.setattr(c12, "_powershell", capture)
    with c12._isolated_node_outbound_block(node=node, cwd=tmp_path):
        assert len(scripts) == 1
        assert "New-NetFirewallRule" in scripts[0][0]
        assert "-Action Block" in scripts[0][0]
        assert "-Direction Outbound" in scripts[0][0]
        assert "Get-NetFirewallProfile" in scripts[0][0]
        assert str(node) in scripts[0][0]
    assert len(scripts) == 2
    assert "Remove-NetFirewallRule" in scripts[1][0]
    assert scripts[0][0].split("RC72-C12-NODE-")[1].split("'")[0] == (
        scripts[1][0].split("RC72-C12-NODE-")[1].split("'")[0])


def test_isolated_firewall_cleanup_also_runs_when_q2_fails(tmp_path, monkeypatch):
    from rc7_release import rc72_c12_local_portable as c12
    node = tmp_path / "node.exe"
    node.write_bytes(b"fixture")
    scripts = []
    monkeypatch.setattr(c12, "_powershell",
                        lambda script, *, cwd: scripts.append(script))
    with pytest.raises(RuntimeError, match="Q2 FAILED"):
        with c12._isolated_node_outbound_block(node=node, cwd=tmp_path):
            raise RuntimeError("Q2 FAILED")
    assert len(scripts) == 2
    assert "Remove-NetFirewallRule" in scripts[-1]


def test_isolated_firewall_requires_real_extracted_node(tmp_path):
    from rc7_release import rc72_c12_local_portable as c12
    with pytest.raises(LocalC12Error, match="EXTRACTED_NODE_EXECUTABLE_MISSING"):
        with c12._isolated_node_outbound_block(
                node=tmp_path / "no-node.exe", cwd=tmp_path):
            pass
