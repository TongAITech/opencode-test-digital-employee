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
    if os.path.commonpath([str(root), str(output)]) == str(root):
        raise ExportError("FIELD_EVIDENCE_OUTPUT_MUST_BE_OUTSIDE_PACKAGE")
    if output.exists() or Path(str(output) + ".sha256").exists():
        raise ExportError("FIELD_EVIDENCE_OUTPUT_ALREADY_EXISTS")
    actual = _checked(root, "SOURCE_COMMIT").read_text(encoding="utf-8").strip()
    if actual.lower() != source_commit.lower():
        raise ExportError("FIELD_EVIDENCE_SOURCE_MISMATCH")

    required = [
        "SOURCE_COMMIT", "BUILD_ID", "RELEASE_FAMILY", "PACKAGE_MANIFEST.json",
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
    try:
        with zipfile.ZipFile(str(output), "x", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
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
            receipt.write(_digest(output) + "  " + output.name + "\n")
    except BaseException:
        if output.exists():
            output.unlink()
        # Never replace or remove a receipt that existed before this export.
        if sidecar.exists():
            sidecar.unlink()
        raise
    return dict(report, archive_path=str(output), archive_sha256=_digest(output))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export named Q3-Q9 evidence; NEVER declares BANK_FINAL")
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--output", required=True, help="New ZIP outside the package root")
    parser.add_argument("--r1-relpath", default="runtime-state/r1/event-stream.jsonl")
    parser.add_argument("--include", action="append", default=[], help="Explicit relative evidence file; repeat for each attachment")
    args = parser.parse_args(argv)
    try:
        result = export_evidence(args.package_root, args.output, source_commit=args.expected_source_commit,
                                 includes=args.include, r1_relpath=args.r1_relpath)
    except (ExportError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc), "bank_final": False}, sort_keys=True))
        return 1
    print(json.dumps({"status": "EVIDENCE_COPY_ONLY", "archive_path": result["archive_path"],
                      "archive_sha256": result["archive_sha256"], "file_count": len(result["files"]),
                      "field_verified": False, "bank_final": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
