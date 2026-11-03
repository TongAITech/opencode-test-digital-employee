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
        "PACKAGE_MANIFEST.json": "{}",
        "CHECKSUMS.sha256": "",
        "FULL-CAPABILITY-INVENTORY.json": "{}",
        "runtime-state/r1/event-stream.jsonl": '{"kind":"ENGINEERING_TEST_ONLY"}\n',
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
    assert len(result["files"]) == 8
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
