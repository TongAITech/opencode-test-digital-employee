"""The field exporter is a byte transport, not a bank acceptance oracle."""
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest


MODULE = Path(__file__).resolve().parents[1] / "packaging" / "rc7.2" / "QA-Q3-Q9-EVIDENCE.py"
spec = importlib.util.spec_from_file_location("rc72_qa_field_evidence", str(MODULE))
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)
COMMIT = "b" * 40


def _root(tmp_path):
    root = tmp_path / "physical candidate"
    for rel, value in {
        "SOURCE_COMMIT": COMMIT,
        "BUILD_ID": "RC7.2-" + COMMIT[:12],
        "RELEASE_FAMILY": "RC7.2",
        "RELEASE_STATUS": "ENGINEERING_CANDIDATE_NOT_BANK_FINAL",
        "RC72_RELEASE_IDENTITY.json": json.dumps({
            "schema": "pfc.aitest.rc7.2.release-identity.v1",
            "source_commit": COMMIT, "build_id": "RC7.2-" + COMMIT[:12],
            "release_family": "RC7.2", "package_name": "PFC-AITest-DSH-Turnkey-RC7.2-BANK-WIN10",
            "business_root": "RELEASE_BATCH", "runtime_control_backbone": "N1_N10_MISSION_GRAPH",
            "field_verified": False, "bank_final": False,
        }),
        "PACKAGE_MANIFEST.json": json.dumps({
            "source_commit": COMMIT, "build_id": "RC7.2-" + COMMIT[:12],
            "release_family": "RC7.2", "field_verified": False,
            "bank_final": False, "real_mission_pass": False,
            "delivery_pass": False, "bank_field_pass": False,
        }),
        "CHECKSUMS.sha256": "",
        "FULL-CAPABILITY-INVENTORY.json": json.dumps({
            "source_commit": COMMIT, "release_family": "RC7.2",
            "field_verified": False, "bank_final": False,
        }),
        "runtime-state/r1/event-stream.jsonl": json.dumps({
            "seq": 1, "event_id": "qa-synthetic-0001", "event_type": "ENGINEERING_TEST_ONLY",
            "entity_type": "qa_synthetic", "entity_id": "fixture-1",
            "entity_version": 1, "payload": {"test_only": True},
        }) + "\n",
        "field/q3-target-linux.json": '{"attestation":"fixture-not-bank"}',
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    return root


def test_named_q3_q9_export_is_byte_pinned_and_never_calls_it_final(tmp_path):
    root = _root(tmp_path)
    output = tmp_path / "qa-field-export.zip"
    original = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = exporter.export_evidence(root, output, source_commit=COMMIT,
        includes=["field/q3-target-linux.json"])
    assert result["field_verified"] is False and result["bank_final"] is False
    assert result["q9_bank_final"] == "NOT_ADMITTED"
    assert len(result["files"]) == 10
    assert output.is_file()
    with zipfile.ZipFile(str(output)) as z:
        index = json.loads(z.read("QA-EVIDENCE-INDEX.json"))
        assert index["source_commit"] == COMMIT
        assert index["field_verified"] is False and index["bank_final"] is False
        for row in index["files"]:
            assert hashlib.sha256(z.read("payload/" + row["path"])).hexdigest() == row["sha256"]
    assert Path(str(output) + ".sha256").read_text(encoding="utf-8").startswith(result["archive_sha256"])
    assert {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()} == original


def test_absent_r1_and_mismatched_source_refuse_to_export(tmp_path):
    root = _root(tmp_path)
    out = tmp_path / "never-created.zip"
    with pytest.raises(exporter.ExportError, match="SOURCE_MISMATCH"):
        exporter.export_evidence(root, out, source_commit="c" * 40)
    (root / "runtime-state/r1/event-stream.jsonl").unlink()
    with pytest.raises(exporter.ExportError, match="FILE_MISSING"):
        exporter.export_evidence(root, out, source_commit=COMMIT)
    assert not out.exists()


@pytest.mark.parametrize("illegal", ["../private.txt", "/tmp/untrusted.txt"])
def test_attachment_escape_cannot_be_collected(tmp_path, illegal):
    root = _root(tmp_path)
    out = tmp_path / "blocked.zip"
    with pytest.raises(exporter.ExportError, match="PATH_ESCAPE"):
        exporter.export_evidence(root, out, source_commit=COMMIT, includes=[illegal])
    assert not out.exists()


def test_export_does_not_write_into_package_or_overwrite_existing_receipt(tmp_path):
    root = _root(tmp_path)
    with pytest.raises(exporter.ExportError, match="OUTSIDE_PACKAGE"):
        exporter.export_evidence(root, root / "leak.zip", source_commit=COMMIT)
    out = tmp_path / "existing.zip"
    out.write_bytes(b"do-not-overwrite")
    with pytest.raises(exporter.ExportError, match="ALREADY_EXISTS"):
        exporter.export_evidence(root, out, source_commit=COMMIT)
    assert out.read_bytes() == b"do-not-overwrite"


def test_existing_sha256_receipt_is_not_overwritten_or_deleted(tmp_path):
    root = _root(tmp_path)
    out = tmp_path / "receipt-protected.zip"
    sidecar = Path(str(out) + ".sha256")
    sidecar.write_bytes(b"existing-bank-receipt-immutable")
    with pytest.raises(exporter.ExportError, match="ALREADY_EXISTS"):
        exporter.export_evidence(root, out, source_commit=COMMIT)
    assert not out.exists()
    assert sidecar.read_bytes() == b"existing-bank-receipt-immutable"


def test_input_mutation_between_preflight_and_copy_cannot_forge_archive_index(tmp_path, monkeypatch):
    root = _root(tmp_path)
    out = tmp_path / "mutated-before-copy.zip"
    rel = "field/q3-target-linux.json"
    old_checked = exporter._checked
    calls = [0]
    def changed_after_preflight(package_root, path):
        if path == rel:
            calls[0] += 1
            if calls[0] == 2:
                (root / rel).write_bytes(b'{"observed":"changed-after-preflight"}\n')
        return old_checked(package_root, path)
    monkeypatch.setattr(exporter, "_checked", changed_after_preflight)
    result = exporter.export_evidence(root, out, source_commit=COMMIT, includes=[rel])
    assert calls[0] >= 2
    with zipfile.ZipFile(str(out)) as archive:
        index = json.loads(archive.read("QA-EVIDENCE-INDEX.json"))
        row = next(item for item in index["files"] if item["path"] == rel)
        exported = archive.read("payload/" + rel)
    assert exported == b'{"observed":"changed-after-preflight"}\n'
    assert row["sha256"] == hashlib.sha256(exported).hexdigest()
    assert row["size"] == len(exported)
    assert result["bank_final"] is False


def _reseal_modified_archive(original, tmp_path, *, entry_name, change):
    """Adversarial archive with a *new valid ZIP SHA256 receipt*, not a cheap damaged ZIP."""
    alternative = tmp_path / "mutated-archive-bytes.zip"
    with zipfile.ZipFile(str(original), "r") as src, zipfile.ZipFile(str(alternative), "w", compression=zipfile.ZIP_DEFLATED) as out:
        for info in src.infolist():
            value = src.read(info.filename)
            if info.filename == entry_name:
                value = change(value)
            out.writestr(info.filename, value)
    alternative.replace(original)
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    Path(str(original) + ".sha256").write_text(digest + "  " + original.name + "\n", encoding="utf-8")


def test_exported_evidence_receipt_and_every_byte_can_be_independently_verified(tmp_path, capsys):
    root = _root(tmp_path)
    out = tmp_path / "qualified-copy.zip"
    exporter.export_evidence(root, out, source_commit=COMMIT, includes=["field/q3-target-linux.json"])
    verified = exporter.verify_evidence_export(out, expected_source_commit=COMMIT)
    assert verified["status"] == "EVIDENCE_COPY_INTEGRITY_ONLY"
    assert verified["file_count"] == 10
    assert verified["r1_structural_event_count"] == 1
    assert verified["r1_validation_scope"] == "JSONL_SHAPE_AND_SEQUENCE_ONLY_NOT_BUSINESS_ORACLE"
    assert verified["field_verified"] is False and verified["bank_final"] is False
    assert verified["q9_bank_final"] == "NOT_ADMITTED"
    assert exporter.main(["--verify-archive", str(out), "--expected-source-commit", COMMIT]) == 0
    assert "EVIDENCE_COPY_INTEGRITY_ONLY" in capsys.readouterr().out


def test_evidence_receipt_mutation_is_independently_rejected(tmp_path):
    root = _root(tmp_path)
    out = tmp_path / "modified.zip"
    exporter.export_evidence(root, out, source_commit=COMMIT)
    Path(str(out) + ".sha256").write_text("0" * 64 + "  modified.zip\n", encoding="utf-8")
    with pytest.raises(exporter.ExportError, match="ZIP_RECEIPT_MISMATCH"):
        exporter.verify_evidence_export(out, expected_source_commit=COMMIT)


def test_changed_zip_file_rejected_even_after_forger_reseals_archive_receipt(tmp_path):
    root = _root(tmp_path)
    out = tmp_path / "tampered-evidence.zip"
    exporter.export_evidence(root, out, source_commit=COMMIT)
    _reseal_modified_archive(out, tmp_path, entry_name="payload/runtime-state/r1/event-stream.jsonl",
                             change=lambda data: data + b'{"injected":"unattested"}\n')
    with pytest.raises(exporter.ExportError, match="ZIP_(SIZE|BYTES)_MISMATCH"):
        exporter.verify_evidence_export(out, expected_source_commit=COMMIT)


def test_forged_field_pass_in_index_rejected_even_with_new_archive_receipt(tmp_path):
    root = _root(tmp_path)
    out = tmp_path / "false-bank-final.zip"
    exporter.export_evidence(root, out, source_commit=COMMIT)
    def forge(data):
        index = json.loads(data)
        index["field_verified"] = True
        index["q9_bank_final"] = "BANK_FINAL"
        return json.dumps(index).encode("utf-8")
    _reseal_modified_archive(out, tmp_path, entry_name="QA-EVIDENCE-INDEX.json", change=forge)
    with pytest.raises(exporter.ExportError, match="ZIP_FALSE_FIELD_CLAIM"):
        exporter.verify_evidence_export(out, expected_source_commit=COMMIT)


def test_evidence_archive_source_must_match_exact_source_commit(tmp_path):
    root = _root(tmp_path)
    out = tmp_path / "other-source.zip"
    exporter.export_evidence(root, out, source_commit=COMMIT)
    with pytest.raises(exporter.ExportError, match="ZIP_SOURCE_MISMATCH"):
        exporter.verify_evidence_export(out, expected_source_commit="c" * 40)


def test_noncanonical_r1_fixture_with_valid_zip_and_receipt_is_rejected(tmp_path):
    root = _root(tmp_path)
    (root / "runtime-state/r1/event-stream.jsonl").write_text('{"kind":"not-append-only"}\n', encoding="utf-8")
    out = tmp_path / "bad-r1-event.zip"
    exporter.export_evidence(root, out, source_commit=COMMIT)
    with pytest.raises(exporter.ExportError, match="ZIP_R1_SEQUENCE_INVALID"):
        exporter.verify_evidence_export(out, expected_source_commit=COMMIT)


def test_r1_missing_event_sequence_is_rejected_with_valid_sha(tmp_path):
    root = _root(tmp_path)
    stream = root / "runtime-state/r1/event-stream.jsonl"
    first = json.loads(stream.read_text(encoding="utf-8"))
    second = dict(first, seq=3, event_id="qa-synthetic-0003")
    stream.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n", encoding="utf-8")
    out = tmp_path / "r1-event-gap.zip"
    exporter.export_evidence(root, out, source_commit=COMMIT)
    with pytest.raises(exporter.ExportError, match="ZIP_R1_SEQUENCE_INVALID"):
        exporter.verify_evidence_export(out, expected_source_commit=COMMIT)


@pytest.mark.parametrize("name,expected", [
    ("payload/../outside.json", "ZIP_PATH_ESCAPE"),
    ("payload/unlisted-extra.txt", "ZIP_ENTRY_COVERAGE_MISMATCH"),
])
def test_valid_receipt_does_not_authorize_extra_or_unsafe_zip_entries(tmp_path, name, expected):
    root = _root(tmp_path)
    out = tmp_path / "unexpected-members.zip"
    exporter.export_evidence(root, out, source_commit=COMMIT)
    with zipfile.ZipFile(str(out), "a") as archive:
        archive.writestr(name, "unreviewed input")
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    Path(str(out) + ".sha256").write_text(digest + "  " + out.name + "\n", encoding="utf-8")
    with pytest.raises(exporter.ExportError, match=expected):
        exporter.verify_evidence_export(out, expected_source_commit=COMMIT)


def test_valid_receipt_cannot_hide_duplicate_zip_index(tmp_path):
    root = _root(tmp_path)
    out = tmp_path / "duplicate-index.zip"
    exporter.export_evidence(root, out, source_commit=COMMIT)
    with zipfile.ZipFile(str(out), "a") as archive:
        archive.writestr("QA-EVIDENCE-INDEX.json", "{}")
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    Path(str(out) + ".sha256").write_text(digest + "  " + out.name + "\n", encoding="utf-8")
    with pytest.raises(exporter.ExportError, match="ZIP_DUPLICATE_OR_MISSING_INDEX"):
        exporter.verify_evidence_export(out, expected_source_commit=COMMIT)


@pytest.mark.parametrize("path,field,value,reason", [
    ("PACKAGE_MANIFEST.json", "source_commit", "c" * 40, "ZIP_MANIFEST_IDENTITY_MISMATCH"),
    ("PACKAGE_MANIFEST.json", "bank_final", True, "ZIP_MANIFEST_IDENTITY_MISMATCH"),
    ("PACKAGE_MANIFEST.json", "real_mission_pass", True, "ZIP_MANIFEST_IDENTITY_MISMATCH"),
    ("FULL-CAPABILITY-INVENTORY.json", "source_commit", "c" * 40, "ZIP_INVENTORY_IDENTITY_MISMATCH"),
    ("FULL-CAPABILITY-INVENTORY.json", "field_verified", True, "ZIP_INVENTORY_IDENTITY_MISMATCH"),
])
def test_matching_zip_receipt_cannot_hide_forged_package_identity(tmp_path, path, field, value, reason):
    root = _root(tmp_path)
    document = root / path
    body = json.loads(document.read_text(encoding="utf-8"))
    body[field] = value
    document.write_text(json.dumps(body), encoding="utf-8")
    out = tmp_path / "signed-but-false-source.zip"
    exporter.export_evidence(root, out, source_commit=COMMIT)
    with pytest.raises(exporter.ExportError, match=reason):
        exporter.verify_evidence_export(out, expected_source_commit=COMMIT)


@pytest.mark.parametrize("path,field,value,reason", [
    ("RC72_RELEASE_IDENTITY.json", "source_commit", "c" * 40, "ZIP_RELEASE_IDENTITY_MISMATCH"),
    ("RC72_RELEASE_IDENTITY.json", "bank_final", True, "ZIP_RELEASE_IDENTITY_MISMATCH"),
    ("RC72_RELEASE_IDENTITY.json", "runtime_control_backbone", "FAKE", "ZIP_RELEASE_IDENTITY_MISMATCH"),
])
def test_exported_rc72_release_identity_is_independently_bound(tmp_path, path, field, value, reason):
    root = _root(tmp_path)
    doc = root / path
    obj = json.loads(doc.read_text(encoding="utf-8"))
    obj[field] = value
    doc.write_text(json.dumps(obj), encoding="utf-8")
    out = tmp_path / "forged-rc72-identity.zip"
    exporter.export_evidence(root, out, source_commit=COMMIT)
    with pytest.raises(exporter.ExportError, match=reason):
        exporter.verify_evidence_export(out, expected_source_commit=COMMIT)


def test_missing_release_status_or_identity_refuses_weak_export(tmp_path):
    root = _root(tmp_path)
    for rel in ("RC72_RELEASE_IDENTITY.json", "RELEASE_STATUS"):
        path = root / rel
        content = path.read_bytes()
        path.unlink()
        with pytest.raises(exporter.ExportError, match="FILE_MISSING"):
            exporter.export_evidence(root, tmp_path / ("must-not-exist-" + rel + ".zip"), source_commit=COMMIT)
        path.write_bytes(content)


def test_packaged_release_status_cannot_be_forged_in_verified_zip(tmp_path):
    root = _root(tmp_path)
    (root / "RELEASE_STATUS").write_text("BANK_FINAL\n", encoding="utf-8")
    out = tmp_path / "forged-release-status.zip"
    exporter.export_evidence(root, out, source_commit=COMMIT)
    with pytest.raises(exporter.ExportError, match="ZIP_IDENTITY_MISMATCH"):
        exporter.verify_evidence_export(out, expected_source_commit=COMMIT)



def test_cannot_substitute_noncanonical_r1_file_for_final_receipt(tmp_path):
    root = _root(tmp_path)
    alternative = "field/q3-target-linux.json"
    with pytest.raises(exporter.ExportError, match="CANONICAL_R1_REQUIRED"):
        exporter.export_evidence(root, tmp_path / "wrong-r1.zip", source_commit=COMMIT,
                                 r1_relpath=alternative)
    assert not (tmp_path / "wrong-r1.zip").exists()


def test_receipt_cannot_relabel_different_payload_as_canonical_r1(tmp_path):
    root = _root(tmp_path)
    out = tmp_path / "relabeled-r1.zip"
    exporter.export_evidence(root, out, source_commit=COMMIT)
    def substitute_index(data):
        index = json.loads(data)
        index["r1_event_stream"] = "SOURCE_COMMIT"
        return json.dumps(index).encode("utf-8")
    _reseal_modified_archive(out, tmp_path, entry_name="QA-EVIDENCE-INDEX.json",
                             change=substitute_index)
    with pytest.raises(exporter.ExportError, match="ZIP_CANONICAL_R1_REQUIRED"):
        exporter.verify_evidence_export(out, expected_source_commit=COMMIT)



@pytest.mark.parametrize("path,forged_kind", [
    ("runtime-state/r1/event-stream.jsonl", "EXPLICIT_FIELD_ATTACHMENT"),
    ("RC72_RELEASE_IDENTITY.json", "R1_EVENT_STREAM"),
    ("field/q3-target-linux.json", "PACKAGE_IDENTITY"),
])
def test_resealed_zip_cannot_misclassify_r1_or_package_identity(tmp_path, path, forged_kind):
    root = _root(tmp_path)
    out = tmp_path / "false-evidence-kind.zip"
    exporter.export_evidence(root, out, source_commit=COMMIT,
                             includes=["field/q3-target-linux.json"])
    def forge(data):
        index = json.loads(data)
        for row in index["files"]:
            if row["path"] == path:
                row["kind"] = forged_kind
        return json.dumps(index).encode("utf-8")
    _reseal_modified_archive(out, tmp_path, entry_name="QA-EVIDENCE-INDEX.json", change=forge)
    with pytest.raises(exporter.ExportError, match="ZIP_ROW_KIND_MISMATCH"):
        exporter.verify_evidence_export(out, expected_source_commit=COMMIT)
