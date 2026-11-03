"""Negative/identity tests of the independent C12 payload byte verifier.

Synthetic package fixtures test the verifier itself, not a release package,
and must never be reported as physical C12, target Linux or bank evidence.
"""
import hashlib
import json

import pytest

from tools.rc72_qa_offline_audit import GROUPS, QualificationError, qualify


COMMIT = "a" * 40


def _make_fixture(tmp_path):
    root = tmp_path / "clean payload"
    root.mkdir()
    data = {
        "SOURCE_COMMIT": COMMIT,
        "BUILD_ID": "RC7.2-" + COMMIT[:12],
        "RELEASE_FAMILY": "RC7.2",
        "RELEASE_STATUS": "ENGINEERING_CANDIDATE_NOT_BANK_FINAL",
        "packaging/rc7.2/AITEST.sh": "echo command",
        "packaging/rc7.2/MISSION.cmd": "echo command",
        "packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh": "echo command",
        "workspace-template/runtime/dsh/dsh.exe": "placeholder-test-binary",
    }
    groups = []
    for name in GROUPS:
        rel = "workspace-template/runtime/" + name
        data[rel + "/sample.dat"] = "payload:" + name
        groups.append({"group": name, "relative_root": rel, "files": 1, "bytes": len(data[rel + "/sample.dat"])})
    def write(rel, value):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    for rel, value in data.items():
        write(rel, value)
    inventory = {
        "schema": "RC72_FULL_PHYSICAL_PAYLOAD_V1",
        "source_commit": COMMIT, "qualification_scope": "PHYSICAL_INVENTORY_ONLY",
        "groups": groups,
    }
    write("FULL-CAPABILITY-INVENTORY.json", json.dumps(inventory))
    rows = []
    for rel in sorted(list(data) + ["FULL-CAPABILITY-INVENTORY.json"]):
        path = root / rel
        rows.append({"path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size})
    write("PACKAGE_MANIFEST.json", json.dumps({"source_commit": COMMIT, "field_verified": False, "bank_final": False, "files": rows}))
    checksum_lines = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "CHECKSUMS.sha256":
            rel = path.relative_to(root).as_posix()
            checksum_lines.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + rel)
    write("CHECKSUMS.sha256", "\n".join(checksum_lines) + "\n")
    return root


def test_candidate_dsh_required_and_field_status_never_conflated(tmp_path):
    root = _make_fixture(tmp_path)
    hold = qualify(root, expected_source=COMMIT)
    assert hold["status"] == "HOLD"
    assert hold["hold_reasons"] == ["DSH_MAIN_PHYSICAL_BINARY_NOT_ATTESTED"]
    candidate = qualify(root, expected_source=COMMIT, dsh_relpath="workspace-template/runtime/dsh/dsh.exe")
    assert candidate["status"] == "PHYSICAL_CANDIDATE_ONLY"
    assert len(candidate["groups"]) == 13
    assert candidate["field_verified"] is False
    assert candidate["bank_final"] is False
    assert candidate["q3_target_linux_verified"] is False
    assert candidate["q9_bank_final"] is False


def test_source_identity_and_payload_tampering_fail_closed(tmp_path):
    root = _make_fixture(tmp_path)
    with pytest.raises(QualificationError, match="SOURCE_COMMIT_MISMATCH"):
        qualify(root, expected_source="b" * 40)
    payload = root / "workspace-template/runtime/browser/sample.dat"
    payload.write_bytes(payload.read_bytes() + b"tampered")
    with pytest.raises(QualificationError, match="(MANIFEST_BYTES_MISMATCH|CHECKSUM_MISMATCH)"):
        qualify(root, expected_source=COMMIT, dsh_relpath="workspace-template/runtime/dsh/dsh.exe")


def test_missing_dsh_main_cannot_be_hidden_by_dsh_plugins(tmp_path):
    root = _make_fixture(tmp_path)
    (root / "workspace-template/runtime/dsh/dsh.exe").unlink()
    with pytest.raises(QualificationError, match="(MANIFEST_FILE_NOT_CHECKSUMMED|CHECKSUM_MISMATCH)"):
        qualify(root, expected_source=COMMIT, dsh_relpath="workspace-template/runtime/dsh/dsh.exe")


def test_path_escape_refused_before_read_or_hash(tmp_path):
    root = _make_fixture(tmp_path)
    manifest = root / "PACKAGE_MANIFEST.json"
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["files"][0]["path"] = "../outside.bin"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(QualificationError, match="PATH_TRAVERSAL"):
        qualify(root, expected_source=COMMIT)
