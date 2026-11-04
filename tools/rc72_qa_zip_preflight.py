"""Read-only C12 untrusted ZIP entry preflight, Python 3.8+.

Check archive names, entry types and decompression budgets BEFORE expanding
GitHub Actions' exact-source portable archive. This is a structural safety
gate only; actual bytes/DSH and Q3-Q9 Field are separately verified.
"""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile


class UnsafeArchiveError(RuntimeError):
    pass


MAX_ENTRIES = 300000
MAX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 8 * 1024 * 1024 * 1024
EXPECTED_ROOT = "PFC-AITest-DSH-Turnkey-RC7.2-BANK-WIN10"
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    prefix + str(num) for prefix in ("COM", "LPT") for num in range(1, 10)
}


def _entry_name(name):
    if (not isinstance(name, str) or not name
            or "\\" in name or "\x00" in name or name.startswith("/")):
        raise UnsafeArchiveError("C12_UNSAFE_ARCHIVE_NAME")
    is_dir = name.endswith("/")
    bare = name[:-1] if is_dir else name
    parts = bare.split("/")
    if (not bare or any(p in ("", ".", "..") or ":" in p for p in parts)
            or PurePosixPath(bare).as_posix() != bare):
        raise UnsafeArchiveError("C12_NONCANONICAL_ARCHIVE_PATH:" + name)
    for part in parts:
        # Expand-Archive runs on NTFS: reject aliases and reserved DOS device
        # names before two distinct ZIP paths can overwrite the same file.
        if (part.endswith((".", " ")) or len(part) > 255
                or any(ord(char) < 32 or ord(char) == 127 for char in part)
                or part.split(".", 1)[0].upper() in WINDOWS_RESERVED):
            raise UnsafeArchiveError("C12_WINDOWS_UNSAFE_ARCHIVE_PATH:" + name)
    return parts, is_dir


def inspect_zip(source, *, expected_root=EXPECTED_ROOT):
    source = Path(source).resolve()
    if expected_root != EXPECTED_ROOT:
        raise UnsafeArchiveError("C12_EXPECTED_PACKAGE_ROOT_CHANGED")
    if not source.is_file():
        raise UnsafeArchiveError("C12_ARCHIVE_MISSING")
    try:
        with zipfile.ZipFile(str(source), "r") as archive:
            info = archive.infolist()
            if not info or len(info) > MAX_ENTRIES:
                raise UnsafeArchiveError("C12_ARCHIVE_ENTRY_COUNT_INVALID")
            seen = set()
            windows_names = set()
            file_paths = set()
            parent_dirs = set()
            bytes_total = 0
            files = 0
            for member in info:
                parts, path_is_dir = _entry_name(member.filename)
                if parts[0] != expected_root:
                    raise UnsafeArchiveError("C12_ARCHIVE_WRONG_ROOT:" + member.filename)
                if member.filename in seen:
                    raise UnsafeArchiveError("C12_ARCHIVE_DUPLICATE_ENTRY:" + member.filename)
                seen.add(member.filename)
                win_path = "/".join(parts).casefold()
                if win_path in windows_names:
                    raise UnsafeArchiveError("C12_WINDOWS_CASEFOLD_COLLISION:" + member.filename)
                windows_names.add(win_path)
                for count in range(1, len(parts)):
                    parent_dirs.add("/".join(parts[:count]).casefold())
                if not path_is_dir:
                    file_paths.add(win_path)
                if member.is_dir() != path_is_dir:
                    raise UnsafeArchiveError("C12_ARCHIVE_DIRECTORY_TYPE_MISMATCH")
                # A ZIP can carry Unix symlink mode even when decoded on Windows.
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise UnsafeArchiveError("C12_ARCHIVE_SYMLINK_FORBIDDEN")
                if path_is_dir:
                    if member.file_size:
                        raise UnsafeArchiveError("C12_ARCHIVE_DIRECTORY_HAS_DATA")
                    continue
                if len(parts) < 2:
                    raise UnsafeArchiveError("C12_ARCHIVE_ROOT_FILE_FORBIDDEN")
                if member.file_size > MAX_SINGLE_FILE_BYTES or member.file_size < 0:
                    raise UnsafeArchiveError("C12_ARCHIVE_FILE_SIZE_EXCEEDS_BUDGET")
                bytes_total += member.file_size
                if bytes_total > MAX_UNCOMPRESSED_BYTES:
                    raise UnsafeArchiveError("C12_ARCHIVE_TOTAL_BYTES_EXCEEDS_BUDGET")
                files += 1
            if file_paths & parent_dirs:
                raise UnsafeArchiveError("C12_WINDOWS_FILE_DIRECTORY_COLLISION")
            if not files:
                raise UnsafeArchiveError("C12_ARCHIVE_CONTAINS_NO_FILES")
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise UnsafeArchiveError("C12_ARCHIVE_CORRUPTED_OR_UNREADABLE") from exc
    return {
        "schema": "RC72_QA_C12_ZIP_STRUCTURE_V1",
        "status": "STRUCTURAL_PREFLIGHT_ONLY",
        "archive": source.name, "expected_root": expected_root,
        "file_entries": files, "total_uncompressed_bytes": bytes_total,
        "field_verified": False, "bank_final": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fail-closed pre-extraction RC7.2 ZIP path/type checks")
    parser.add_argument("--zip", required=True)
    parser.add_argument("--expected-root", default=EXPECTED_ROOT)
    parser.add_argument("--report", help="Write a new external JSON report only")
    args = parser.parse_args(argv)
    try:
        result = inspect_zip(args.zip, expected_root=args.expected_root)
        if args.report:
            output = Path(args.report).resolve()
            source = Path(args.zip).resolve()
            if output == source or output.exists():
                raise UnsafeArchiveError("C12_PREFLIGHT_REPORT_NOT_NEW")
            with output.open("x", encoding="utf-8") as destination:
                json.dump(result, destination, indent=2, sort_keys=True)
                destination.write("\n")
    except (UnsafeArchiveError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc),
                          "field_verified": False, "bank_final": False}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
