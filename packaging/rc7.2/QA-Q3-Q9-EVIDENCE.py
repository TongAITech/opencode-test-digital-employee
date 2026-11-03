"""Q3-Q9 explicit R1/field-evidence transport exporter (not an acceptance oracle).

Python 3.8+ stdlib only. It copies only named files, refuses path escapes and
symlinks, binds all copied bytes to SOURCE_COMMIT, and never declares a PASS.
Review/redact the resulting ZIP according to bank data policies before sharing.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile


class ExportError(RuntimeError):
    pass


def _digest(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _checked(root, rel):
    if not isinstance(rel, str) or not rel or chr(92) in rel:
        raise ExportError("FIELD_EVIDENCE_INVALID_RELATIVE_PATH")
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts or ":" in p.parts[0]:
        raise ExportError("FIELD_EVIDENCE_PATH_ESCAPE")
    current = root
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise ExportError("FIELD_EVIDENCE_SYMLINK_FORBIDDEN:" + rel)
    resolved = current.resolve()
    if os.path.commonpath([str(root), str(resolved)]) != str(root):
        raise ExportError("FIELD_EVIDENCE_PATH_ESCAPE")
    if not resolved.is_file():
        raise ExportError("FIELD_EVIDENCE_FILE_MISSING:" + rel)
    return resolved


def export_evidence(root, output, *, source_commit, includes=(), r1_relpath="runtime-state/r1/event-stream.jsonl"):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not root.is_dir() or not re.fullmatch(r"[0-9a-fA-F]{40}", source_commit or ""):
        raise ExportError("FIELD_EVIDENCE_ROOT_AND_SOURCE_REQUIRED")
    if r1_relpath != "runtime-state/r1/event-stream.jsonl":
        raise ExportError("FIELD_EVIDENCE_CANONICAL_R1_REQUIRED")
    if os.path.commonpath([str(root), str(output)]) == str(root):
        raise ExportError("FIELD_EVIDENCE_OUTPUT_MUST_BE_OUTSIDE_PACKAGE")
    if output.exists() or Path(str(output) + ".sha256").exists():
        raise ExportError("FIELD_EVIDENCE_OUTPUT_ALREADY_EXISTS")
    actual = _checked(root, "SOURCE_COMMIT").read_text(encoding="utf-8").strip()
    if actual.lower() != source_commit.lower():
        raise ExportError("FIELD_EVIDENCE_SOURCE_MISMATCH")

    required = [
        "SOURCE_COMMIT", "BUILD_ID", "RELEASE_FAMILY", "RELEASE_STATUS",
        "RC72_RELEASE_IDENTITY.json", "PACKAGE_MANIFEST.json",
        "CHECKSUMS.sha256", "FULL-CAPABILITY-INVENTORY.json", r1_relpath,
    ]
    selected = sorted(set(required + list(includes)))
    # Check all named inputs before creating anything; collection remains a
    # byte transport, not evidence validation or Field acceptance.
    for rel in selected:
        _checked(root, rel)
    files = []
    report = {
        "schema": "RC72_QA_Q3_Q9_EVIDENCE_TRANSPORT_V1",
        "source_commit": source_commit.lower(),
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "r1_event_stream": r1_relpath, "files": files,
        "scope": "EVIDENCE_COPY_ONLY_NOT_INDEPENDENT_VERIFICATION",
        "q3_target_linux": "PENDING_INDEPENDENT_VERIFICATION",
        "q4_offline": "PENDING_INDEPENDENT_VERIFICATION",
        "q5_browserskill": "PENDING_INDEPENDENT_VERIFICATION",
        "q6_human_approval": "PENDING_INDEPENDENT_VERIFICATION",
        "q7_releasebatch": "PENDING_INDEPENDENT_VERIFICATION",
        "q8_failure_recovery": "PENDING_INDEPENDENT_VERIFICATION",
        "q9_bank_final": "NOT_ADMITTED",
        "field_verified": False, "bank_final": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    sidecar = Path(str(output) + ".sha256")
    created_output = False
    created_sidecar = False
    try:
        with zipfile.ZipFile(str(output), "x", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            created_output = True
            for rel in selected:
                # Hash precisely the bytes written to the archive, not a
                # preflight snapshot which could change before ZipFile.write.
                digest = hashlib.sha256()
                count = 0
                with _checked(root, rel).open("rb") as source, archive.open("payload/" + rel, "w", force_zip64=True) as destination:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        destination.write(chunk)
                        digest.update(chunk)
                        count += len(chunk)
                files.append(dict(
                    path=rel, size=count, sha256=digest.hexdigest(),
                    kind="R1_EVENT_STREAM" if rel == r1_relpath else
                         "PACKAGE_IDENTITY" if rel in required else "EXPLICIT_FIELD_ATTACHMENT",
                ))
            archive.writestr("QA-EVIDENCE-INDEX.json", json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
        with sidecar.open("x", encoding="utf-8") as receipt:
            created_sidecar = True
            receipt.write(_digest(output) + "  " + output.name + "\n")
    except BaseException:
        if created_output and output.exists():
            output.unlink()
        # A pre-existing receipt (including one racing with us) is immutable.
        if created_sidecar and sidecar.exists():
            sidecar.unlink()
        raise
    return dict(report, archive_path=str(output), archive_sha256=_digest(output))




def _strict_archive_relative(rel):
    """Reject archive index traversal, noncanonical aliases and Windows escapes."""
    if not isinstance(rel, str) or not rel or "\\" in rel:
        raise ExportError("FIELD_EVIDENCE_ZIP_PATH_INVALID")
    p = PurePosixPath(rel)
    if (p.is_absolute() or ".." in p.parts or not p.parts or ":" in p.parts[0]
            or p.as_posix() != rel):
        raise ExportError("FIELD_EVIDENCE_ZIP_PATH_ESCAPE")
    return rel


def _verify_canonical_r1_jsonl(stream):
    """Structural truth check; business provenance still needs independent QA."""
    last_seq, count = 0, 0
    event_ids = set()
    for line in stream:
        if not line.strip():
            continue
        try:
            event = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise ExportError("FIELD_EVIDENCE_ZIP_R1_JSONL_INVALID") from exc
        if not isinstance(event, dict):
            raise ExportError("FIELD_EVIDENCE_ZIP_R1_EVENT_INVALID")
        seq = event.get("seq")
        if type(seq) is not int or seq != last_seq + 1:
            raise ExportError("FIELD_EVIDENCE_ZIP_R1_SEQUENCE_INVALID")
        if any(not isinstance(event.get(key), str) or not event[key]
               for key in ("event_id", "event_type", "entity_type", "entity_id")):
            raise ExportError("FIELD_EVIDENCE_ZIP_R1_EVENT_INVALID")
        if (type(event.get("entity_version")) is not int or event["entity_version"] < 1
                or not isinstance(event.get("payload"), dict)):
            raise ExportError("FIELD_EVIDENCE_ZIP_R1_EVENT_INVALID")
        if event["event_id"] in event_ids:
            raise ExportError("FIELD_EVIDENCE_ZIP_R1_EVENT_ID_REUSED")
        event_ids.add(event["event_id"])
        # R1 event headers must not contradict the original canonical
        # artifact metadata where the source payload declares it.
        payload = event["payload"]
        if ("artifact_type" in payload and payload["artifact_type"] != event["entity_type"]):
            raise ExportError("FIELD_EVIDENCE_ZIP_R1_PAYLOAD_ENTITY_MISMATCH")
        if ("artifact_version" in payload and type(payload["artifact_version"]) is int
                and payload["artifact_version"] != event["entity_version"]):
            raise ExportError("FIELD_EVIDENCE_ZIP_R1_PAYLOAD_VERSION_MISMATCH")
        last_seq = seq
        count += 1
    if not count:
        raise ExportError("FIELD_EVIDENCE_ZIP_EMPTY_R1")
    return count


def verify_evidence_export(archive_path, *, expected_source_commit):
    """Independently check exported ZIP/receipt and every index file byte.

    Byte-copy integrity only: does not validate business R1 semantics,
    independent approvers, Field qualification or BANK_FINAL.
    """
    if not isinstance(expected_source_commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", expected_source_commit):
        raise ExportError("FIELD_EVIDENCE_VERIFY_SOURCE_REQUIRED")
    archive_path = Path(archive_path).resolve()
    receipt_path = Path(str(archive_path) + ".sha256")
    if not archive_path.is_file() or not receipt_path.is_file():
        raise ExportError("FIELD_EVIDENCE_ZIP_OR_RECEIPT_MISSING")
    receipt = receipt_path.read_text(encoding="utf-8").strip().split("  ", 1)
    if (len(receipt) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", receipt[0])
            or receipt[1] != archive_path.name or receipt[0].lower() != _digest(archive_path)):
        raise ExportError("FIELD_EVIDENCE_ZIP_RECEIPT_MISMATCH")
    try:
        with zipfile.ZipFile(str(archive_path), "r") as archive:
            metadata = archive.infolist()
            names = [item.filename for item in metadata]
            if len(names) != len(set(names)) or "QA-EVIDENCE-INDEX.json" not in names:
                raise ExportError("FIELD_EVIDENCE_ZIP_DUPLICATE_OR_MISSING_INDEX")
            for entry in metadata:
                if (entry.filename != "QA-EVIDENCE-INDEX.json"
                        and (not entry.filename.startswith("payload/")
                             or not _strict_archive_relative(entry.filename[len("payload/"):]))):
                    raise ExportError("FIELD_EVIDENCE_ZIP_UNDECLARED_ENTRY")
                if entry.filename.endswith("/") or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ExportError("FIELD_EVIDENCE_ZIP_SYMLINK_OR_DIRECTORY")
            index_entry = archive.getinfo("QA-EVIDENCE-INDEX.json")
            if index_entry.file_size > 10 * 1024 * 1024:
                raise ExportError("FIELD_EVIDENCE_ZIP_INDEX_OVERSIZE")
            try:
                index = json.loads(archive.read(index_entry).decode("utf-8"))
            except (ValueError, UnicodeError) as exc:
                raise ExportError("FIELD_EVIDENCE_ZIP_INDEX_INVALID") from exc
            if not isinstance(index, dict) or index.get("schema") != "RC72_QA_Q3_Q9_EVIDENCE_TRANSPORT_V1":
                raise ExportError("FIELD_EVIDENCE_ZIP_SCHEMA_INVALID")
            if index.get("source_commit") != expected_source_commit.lower():
                raise ExportError("FIELD_EVIDENCE_ZIP_SOURCE_MISMATCH")
            if (index.get("field_verified") is not False or index.get("bank_final") is not False
                    or index.get("q9_bank_final") != "NOT_ADMITTED"
                    or index.get("scope") != "EVIDENCE_COPY_ONLY_NOT_INDEPENDENT_VERIFICATION"
                    or any(index.get("q" + str(n) + "_" + {
                        3: "target_linux", 4: "offline", 5: "browserskill", 6: "human_approval",
                        7: "releasebatch", 8: "failure_recovery",
                    }[n]) != "PENDING_INDEPENDENT_VERIFICATION" for n in range(3, 9))):
                raise ExportError("FIELD_EVIDENCE_ZIP_FALSE_FIELD_CLAIM")
            rows = index.get("files")
            if not isinstance(rows, list) or not rows:
                raise ExportError("FIELD_EVIDENCE_ZIP_FILES_REQUIRED")
            listed = {}
            for row in rows:
                if not isinstance(row, dict):
                    raise ExportError("FIELD_EVIDENCE_ZIP_ROW_INVALID")
                rel = _strict_archive_relative(row.get("path"))
                if rel in listed or type(row.get("size")) is not int or row["size"] < 0:
                    raise ExportError("FIELD_EVIDENCE_ZIP_ROW_INVALID")
                if not isinstance(row.get("sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", row["sha256"]):
                    raise ExportError("FIELD_EVIDENCE_ZIP_HASH_INVALID")
                listed[rel] = row
            r1 = _strict_archive_relative(index.get("r1_event_stream"))
            if r1 != "runtime-state/r1/event-stream.jsonl":
                raise ExportError("FIELD_EVIDENCE_ZIP_CANONICAL_R1_REQUIRED")
            required = {"SOURCE_COMMIT", "BUILD_ID", "RELEASE_FAMILY", "RELEASE_STATUS",
                        "RC72_RELEASE_IDENTITY.json", "PACKAGE_MANIFEST.json",
                        "CHECKSUMS.sha256", "FULL-CAPABILITY-INVENTORY.json", r1}
            if not required.issubset(listed):
                raise ExportError("FIELD_EVIDENCE_ZIP_REQUIRED_EVIDENCE_MISSING")
            for rel, row in listed.items():
                expected_kind = ("R1_EVENT_STREAM" if rel == r1 else
                                 "PACKAGE_IDENTITY" if rel in required else "EXPLICIT_FIELD_ATTACHMENT")
                if row.get("kind") != expected_kind:
                    raise ExportError("FIELD_EVIDENCE_ZIP_ROW_KIND_MISMATCH:" + rel)
            expected_entries = {"QA-EVIDENCE-INDEX.json"} | {"payload/" + rel for rel in listed}
            if set(names) != expected_entries:
                raise ExportError("FIELD_EVIDENCE_ZIP_ENTRY_COVERAGE_MISMATCH")
            for rel, row in listed.items():
                info = archive.getinfo("payload/" + rel)
                if info.file_size != row["size"]:
                    raise ExportError("FIELD_EVIDENCE_ZIP_SIZE_MISMATCH:" + rel)
                digest, count = hashlib.sha256(), 0
                with archive.open(info, "r") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                        count += len(chunk)
                if count != row["size"] or digest.hexdigest() != row["sha256"].lower():
                    raise ExportError("FIELD_EVIDENCE_ZIP_BYTES_MISMATCH:" + rel)
            # Physical ZIP/receipt integrity is not enough if the included
            # package identity documents refer to a different source or
            # falsely claim bank approval. Read bounded metadata only.
            metadata_docs = {}
            for rel in ("RC72_RELEASE_IDENTITY.json", "PACKAGE_MANIFEST.json", "FULL-CAPABILITY-INVENTORY.json"):
                info = archive.getinfo("payload/" + rel)
                if info.file_size > 32 * 1024 * 1024:
                    raise ExportError("FIELD_EVIDENCE_ZIP_IDENTITY_DOCUMENT_TOO_LARGE:" + rel)
                try:
                    metadata_docs[rel] = json.loads(archive.read(info).decode("utf-8"))
                except (ValueError, UnicodeError) as exc:
                    raise ExportError("FIELD_EVIDENCE_ZIP_IDENTITY_DOCUMENT_INVALID:" + rel) from exc
                if not isinstance(metadata_docs[rel], dict):
                    raise ExportError("FIELD_EVIDENCE_ZIP_IDENTITY_DOCUMENT_INVALID:" + rel)
            identity = metadata_docs["RC72_RELEASE_IDENTITY.json"]
            manifest = metadata_docs["PACKAGE_MANIFEST.json"]
            inventory = metadata_docs["FULL-CAPABILITY-INVENTORY.json"]
            if (identity.get("schema") != "pfc.aitest.rc7.2.release-identity.v1"
                    or identity.get("source_commit") != expected_source_commit.lower()
                    or identity.get("build_id") != "RC7.2-" + expected_source_commit.lower()[:12]
                    or identity.get("release_family") != "RC7.2"
                    or identity.get("package_name") != "PFC-AITest-DSH-Turnkey-RC7.2-BANK-WIN10"
                    or identity.get("business_root") != "RELEASE_BATCH"
                    or identity.get("runtime_control_backbone") != "N1_N10_MISSION_GRAPH"
                    or identity.get("field_verified") is not False
                    or identity.get("bank_final") is not False):
                raise ExportError("FIELD_EVIDENCE_ZIP_RELEASE_IDENTITY_MISMATCH")
            if (manifest.get("source_commit") != expected_source_commit.lower()
                    or manifest.get("build_id") != "RC7.2-" + expected_source_commit.lower()[:12]
                    or manifest.get("release_family") != "RC7.2"
                    or manifest.get("field_verified") is not False
                    or manifest.get("bank_final") is not False
                    or any(manifest.get(k) is not False for k in
                           ("real_mission_pass", "delivery_pass", "bank_field_pass"))):
                raise ExportError("FIELD_EVIDENCE_ZIP_MANIFEST_IDENTITY_MISMATCH")
            if (inventory.get("source_commit") != expected_source_commit.lower()
                    or inventory.get("release_family") != "RC7.2"
                    or inventory.get("field_verified") is not False
                    or inventory.get("bank_final") is not False):
                raise ExportError("FIELD_EVIDENCE_ZIP_INVENTORY_IDENTITY_MISMATCH")
            with archive.open("payload/" + r1, "r") as stream:
                r1_event_count = _verify_canonical_r1_jsonl(stream)
            if (archive.read("payload/SOURCE_COMMIT").decode("utf-8").strip().lower() != expected_source_commit.lower()
                    or archive.read("payload/BUILD_ID").decode("utf-8").strip() != "RC7.2-" + expected_source_commit.lower()[:12]
                    or archive.read("payload/RELEASE_FAMILY").decode("utf-8").strip() != "RC7.2"
                    or archive.read("payload/RELEASE_STATUS").decode("utf-8").strip() != "ENGINEERING_CANDIDATE_NOT_BANK_FINAL"):
                raise ExportError("FIELD_EVIDENCE_ZIP_IDENTITY_MISMATCH")
    except zipfile.BadZipFile as exc:
        raise ExportError("FIELD_EVIDENCE_ZIP_CORRUPTED") from exc
    return {
        "status": "EVIDENCE_COPY_INTEGRITY_ONLY",
        "source_commit": expected_source_commit.lower(),
        "archive_sha256": receipt[0].lower(),
        "file_count": len(listed), "r1_structural_event_count": r1_event_count,
        "r1_validation_scope": "JSONL_SHAPE_AND_SEQUENCE_ONLY_NOT_BUSINESS_ORACLE",
        "field_verified": False, "bank_final": False, "q9_bank_final": "NOT_ADMITTED",
    }

def main(argv=None):
    parser = argparse.ArgumentParser(description="Export or verify Q3-Q9 evidence bytes; NEVER declares BANK_FINAL")
    parser.add_argument("--package-root", help="Package root for export")
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--output", help="New ZIP outside the package root for export")
    parser.add_argument("--verify-archive", help="Read-only verify an exported ZIP and its .sha256 receipt")
    parser.add_argument("--r1-relpath", default="runtime-state/r1/event-stream.jsonl")
    parser.add_argument("--include", action="append", default=[], help="Explicit relative evidence file; repeat for each attachment")
    args = parser.parse_args(argv)
    try:
        if args.verify_archive:
            if args.package_root or args.output or args.include:
                raise ExportError("FIELD_EVIDENCE_VERIFY_EXPORT_OPTIONS_CONFLICT")
            result = verify_evidence_export(args.verify_archive, expected_source_commit=args.expected_source_commit)
            print(json.dumps(result, sort_keys=True))
            return 0
        if not args.package_root or not args.output:
            raise ExportError("FIELD_EVIDENCE_EXPORT_ROOT_AND_OUTPUT_REQUIRED")
        result = export_evidence(args.package_root, args.output, source_commit=args.expected_source_commit,
                                 includes=args.include, r1_relpath=args.r1_relpath)
    except (ExportError, OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc), "bank_final": False}, sort_keys=True))
        return 1
    print(json.dumps({"status": "EVIDENCE_COPY_ONLY", "archive_path": result["archive_path"],
                      "archive_sha256": result["archive_sha256"], "file_count": len(result["files"]),
                      "field_verified": False, "bank_final": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
