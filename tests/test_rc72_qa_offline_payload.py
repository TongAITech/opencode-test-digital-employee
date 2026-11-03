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
    data["RC72_RELEASE_IDENTITY.json"] = json.dumps({
        "schema": "pfc.aitest.rc7.2.release-identity.v1", "release_family": "RC7.2",
        "package_name": "PFC-AITest-DSH-Turnkey-RC7.2-BANK-WIN10",
        "source_commit": COMMIT, "build_id": "RC7.2-" + COMMIT[:12],
        "business_root": "RELEASE_BATCH", "runtime_control_backbone": "N1_N10_MISSION_GRAPH",
        "field_verified": False, "bank_final": False,
    })
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
        "schema": "RC72_FULL_PHYSICAL_PAYLOAD_V1", "status": "PASS",
        "release_family": "RC7.2", "field_verified": False, "bank_final": False,
        "source_commit": COMMIT, "qualification_scope": "PHYSICAL_INVENTORY_ONLY",
        "groups": groups,
    }
    write("FULL-CAPABILITY-INVENTORY.json", json.dumps(inventory))
    rows = []
    for rel in sorted(list(data) + ["FULL-CAPABILITY-INVENTORY.json"]):
        path = root / rel
        rows.append({"path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size})
    write("PACKAGE_MANIFEST.json", json.dumps({
        "schema_version": "pfc.aitest.rc7.2.package.v1",
        "status": "ENGINEERING_CANDIDATE_NOT_BANK_FINAL",
        "package_name": "PFC-AITest-DSH-Turnkey-RC7.2-BANK-WIN10",
        "release_family": "RC7.2", "source_commit": COMMIT, "build_id": "RC7.2-" + COMMIT[:12],
        "business_root": "RELEASE_BATCH", "runtime_control_backbone": "N1_N10_MISSION_GRAPH",
        "field_verified": False, "bank_final": False, "real_mission_pass": False,
        "delivery_pass": False, "bank_field_pass": False,
        "files": rows,
    }))
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


def test_unlisted_physical_file_is_not_silently_accepted(tmp_path):
    root = _make_fixture(tmp_path)
    stray = root / "workspace-template/runtime/browser/unlisted-driver.bin"
    stray.write_bytes(b"unregistered-real-byte")
    with pytest.raises(QualificationError, match="PHYSICAL_CHECKSUM_COVERAGE_MISMATCH"):
        qualify(root, expected_source=COMMIT, dsh_relpath="workspace-template/runtime/dsh/dsh.exe")


def test_missing_manifest_member_fails_even_if_checksum_is_intact(tmp_path):
    root = _make_fixture(tmp_path)
    manifest = root / "PACKAGE_MANIFEST.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    # The checksums still cover the file, but the manifest silently drops it.
    data["files"] = [row for row in data["files"] if row["path"] != "SOURCE_COMMIT"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(QualificationError, match="MANIFEST_CHECKSUM_COVERAGE_MISMATCH"):
        qualify(root, expected_source=COMMIT, dsh_relpath="workspace-template/runtime/dsh/dsh.exe")


def test_forged_group_inventory_is_refused_even_with_consistent_hashes(tmp_path):
    root = _make_fixture(tmp_path)
    inv = root / "FULL-CAPABILITY-INVENTORY.json"
    data = json.loads(inv.read_text(encoding="utf-8"))
    data["groups"][0]["files"] += 1
    inv.write_text(json.dumps(data), encoding="utf-8")
    # Recalculate both attestation tables so the test reaches the independent
    # actual-versus-claimed GROUP_FILES check, not an incidental checksum error.
    manifest = root / "PACKAGE_MANIFEST.json"
    rows = json.loads(manifest.read_text(encoding="utf-8"))
    for row in rows["files"]:
        if row["path"] == "FULL-CAPABILITY-INVENTORY.json":
            row["sha256"] = hashlib.sha256(inv.read_bytes()).hexdigest()
            row["size"] = inv.stat().st_size
    manifest.write_text(json.dumps(rows), encoding="utf-8")
    checksum_lines = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "CHECKSUMS.sha256":
            rel = path.relative_to(root).as_posix()
            checksum_lines.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + rel)
    (root / "CHECKSUMS.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    with pytest.raises(QualificationError, match="GROUP_INVENTORY_BYTES_MISMATCH:python"):
        qualify(root, expected_source=COMMIT, dsh_relpath="workspace-template/runtime/dsh/dsh.exe")


@pytest.mark.parametrize("path,key,value,error", [
    ("RELEASE_STATUS", None, "BANK_FINAL", "RELEASE_STATUS_MISMATCH"),
    ("RC72_RELEASE_IDENTITY.json", "bank_final", True, "RELEASE_IDENTITY_FALSE_FIELD_STATUS"),
    ("RC72_RELEASE_IDENTITY.json", "runtime_control_backbone", "FAKE_PIPELINE", "RELEASE_IDENTITY_MISMATCH"),
    ("PACKAGE_MANIFEST.json", "real_mission_pass", True, "MANIFEST_FALSE_COMPLETION"),
    ("PACKAGE_MANIFEST.json", "build_id", "RC7.2-false", "MANIFEST_PRODUCT_IDENTITY_MISMATCH"),
    ("FULL-CAPABILITY-INVENTORY.json", "bank_final", True, "INVENTORY_PRODUCT_IDENTITY_MISMATCH"),
])
def test_forged_identity_and_false_completion_refused_before_hashing(tmp_path, path, key, value, error):
    root = _make_fixture(tmp_path)
    target = root / path
    if key is None:
        target.write_text(value, encoding="utf-8")
    else:
        document = json.loads(target.read_text(encoding="utf-8"))
        document[key] = value
        target.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(QualificationError, match=error):
        qualify(root, expected_source=COMMIT, dsh_relpath="workspace-template/runtime/dsh/dsh.exe")


def test_malformed_identity_document_fails_closed(tmp_path):
    root = _make_fixture(tmp_path)
    (root / "RC72_RELEASE_IDENTITY.json").write_text("[]", encoding="utf-8")
    with pytest.raises(QualificationError, match="JSON_OBJECT_REQUIRED"):
        qualify(root, expected_source=COMMIT)
