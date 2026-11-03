"""Independent, read-only C12 full-payload audit for Python 3.8+.

This does NOT certify a working bank mission, Linux target, or BANK_FINAL. In
particular, bank-installed DSH is not a substitute for physically carried DSH
when the delivery contract requires the complete turnkey payload.
"""
from __future__ import print_function

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys


SOURCE = re.compile(r"^[0-9a-fA-F]{40}$")
HEX = re.compile(r"^[0-9a-fA-F]{64}$")
GROUPS = (
    "python", "node", "node-execution", "browser", "code-intelligence",
    "java", "maven", "maven-repository", "allure", "k6", "zap", "ripgrep", "dsh-plugins",
)
MANDATORY = (
    "SOURCE_COMMIT", "BUILD_ID", "RELEASE_FAMILY", "RELEASE_STATUS",
    "PACKAGE_MANIFEST.json", "CHECKSUMS.sha256", "FULL-CAPABILITY-INVENTORY.json",
    "packaging/rc7.2/AITEST.sh", "packaging/rc7.2/MISSION.cmd",
    "packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh",
)


class QualificationError(RuntimeError):
    pass


def _inside(root, rel):
    if not isinstance(rel, str) or not rel or chr(92) in rel:
        raise QualificationError("INVALID_RELATIVE_PATH")
    parts = PurePosixPath(rel).parts
    if rel.startswith("/") or ".." in parts or "." in parts or not parts or ":" in parts[0]:
        raise QualificationError("PATH_TRAVERSAL:" + rel)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise QualificationError("SYMLINK_PAYLOAD_FORBIDDEN:" + rel)
    target = current.resolve()
    if os.path.commonpath([str(root), str(target)]) != str(root):
        raise QualificationError("PATH_OUTSIDE_PACKAGE:" + rel)
    return target


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise QualificationError("INVALID_JSON:" + path.name) from exc


def _read(path):
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise QualificationError("MISSING_IDENTITY:" + path.name) from exc


def _checksum_rows(root):
    rows = {}
    for line in _read(root / "CHECKSUMS.sha256").splitlines():
        if not line.strip():
            continue
        if "  " not in line:
            raise QualificationError("CHECKSUM_SYNTAX_INVALID")
        digest, rel = line.split("  ", 1)
        if not HEX.fullmatch(digest) or rel in rows:
            raise QualificationError("CHECKSUM_INVALID_OR_DUPLICATE:" + rel)
        _inside(root, rel)
        rows[rel] = digest.lower()
    if not rows:
        raise QualificationError("CHECKSUM_EMPTY")
    return rows


def qualify(root, *, expected_source, dsh_relpath=None):
    root = Path(root).resolve()
    if not root.is_dir() or not SOURCE.fullmatch(expected_source or ""):
        raise QualificationError("ROOT_OR_EXPECTED_SOURCE_REQUIRED")
    for rel in MANDATORY:
        if not _inside(root, rel).is_file():
            raise QualificationError("REQUIRED_FILE_MISSING:" + rel)

    observed = _read(root / "SOURCE_COMMIT")
    if observed.lower() != expected_source.lower():
        raise QualificationError("SOURCE_COMMIT_MISMATCH")
    if _read(root / "RELEASE_FAMILY") != "RC7.2":
        raise QualificationError("RELEASE_FAMILY_MISMATCH")
    if _read(root / "BUILD_ID") != "RC7.2-" + expected_source[:12]:
        raise QualificationError("BUILD_ID_MISMATCH")

    manifest = _json(root / "PACKAGE_MANIFEST.json")
    inventory = _json(root / "FULL-CAPABILITY-INVENTORY.json")
    if manifest.get("source_commit", "").lower() != expected_source.lower():
        raise QualificationError("MANIFEST_SOURCE_MISMATCH")
    if manifest.get("field_verified") is not False or manifest.get("bank_final") is not False:
        raise QualificationError("FALSE_FIELD_STATUS")
    if inventory.get("source_commit", "").lower() != expected_source.lower():
        raise QualificationError("INVENTORY_SOURCE_MISMATCH")
    if inventory.get("qualification_scope") != "PHYSICAL_INVENTORY_ONLY":
        raise QualificationError("INVENTORY_SCOPE_INVALID")
    rows = inventory.get("groups")
    if not isinstance(rows, list) or set(row.get("group") for row in rows if isinstance(row, dict)) != set(GROUPS) or len(rows) != len(GROUPS):
        raise QualificationError("REQUIRED_GROUPS_INCOMPLETE")

    checksums = _checksum_rows(root)
    manifest_paths = set()
    for item in manifest.get("files") or []:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise QualificationError("MANIFEST_FILE_INVALID")
        rel = item["path"]
        if rel in manifest_paths:
            raise QualificationError("MANIFEST_DUPLICATE:" + rel)
        manifest_paths.add(rel)
        path = _inside(root, rel)
        if not path.is_file() or rel not in checksums:
            raise QualificationError("MANIFEST_FILE_NOT_CHECKSUMMED:" + rel)
        if item.get("sha256", "").lower() != checksums[rel] or item.get("size") != path.stat().st_size:
            raise QualificationError("MANIFEST_BYTES_MISMATCH:" + rel)

    total_bytes = 0
    for rel, digest in checksums.items():
        path = _inside(root, rel)
        if not path.is_file() or _sha256(path) != digest:
            raise QualificationError("CHECKSUM_MISMATCH:" + rel)
        total_bytes += path.stat().st_size

    group_report = []
    for group in rows:
        name = group["group"]
        rel = group.get("relative_root")
        if not isinstance(rel, str) or rel != "workspace-template/runtime/" + name:
            raise QualificationError("GROUP_PATH_CHANGED:" + name)
        folder = _inside(root, rel)
        if not folder.is_dir():
            raise QualificationError("GROUP_MISSING:" + name)
        present = [p for p in folder.rglob("*") if p.is_file() and not p.is_symlink()]
        if not present or not any(p.stat().st_size for p in present):
            raise QualificationError("GROUP_EMPTY:" + name)
        for f in present:
            if f.is_symlink():
                raise QualificationError("GROUP_SYMLINK:" + name)
        group_report.append({"group": name, "present_files": len(present), "physical_bytes": sum(p.stat().st_size for p in present)})

    holds = []
    if not dsh_relpath:
        holds.append("DSH_MAIN_PHYSICAL_BINARY_NOT_ATTESTED")
    else:
        path = _inside(root, dsh_relpath)
        if not path.is_file() or not path.stat().st_size or dsh_relpath not in checksums or dsh_relpath not in manifest_paths:
            holds.append("DSH_MAIN_NOT_CARRIED_AND_CHECKSUMMED")
    return {
        "schema": "RC72_QA_PHYSICAL_AUDIT_V1", "source_commit": expected_source.lower(),
        "status": "HOLD" if holds else "PHYSICAL_CANDIDATE_ONLY",
        "hold_reasons": holds, "groups": group_report,
        "checksum_file_count": len(checksums), "checksum_bytes": total_bytes,
        "qualification_scope": "INDEPENDENT_PACKAGE_BYTES_ONLY",
        "source_binding": "SOURCE_COMMIT+PACKAGE_MANIFEST+CHECKSUMS+FULL_CAPABILITY_INVENTORY",
        "field_verified": False, "bank_final": False,
        "q3_target_linux_verified": False, "q5_browser_field_verified": False,
        "q7_release_batch_field_verified": False, "q8_recovery_field_verified": False,
        "q9_bank_final": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fail-closed independent RC7.2 physical payload QA; never BANK_FINAL")
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--dsh-relpath", default=None, help="Path to a physically carried signed/checksummed DSH main binary")
    parser.add_argument("--report", default=None, help="JSON output, preferably outside the package root")
    options = parser.parse_args(argv)
    try:
        result = qualify(options.package_root, expected_source=options.expected_source_commit, dsh_relpath=options.dsh_relpath)
    except (QualificationError, OSError, ValueError) as exc:
        result = {"schema": "RC72_QA_PHYSICAL_AUDIT_V1", "status": "FAIL", "reason": str(exc),
                  "field_verified": False, "bank_final": False}
    output = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + chr(10)
    if options.report:
        Path(options.report).write_text(output, encoding="utf-8")
    print(output)
    return 0 if result["status"] == "PHYSICAL_CANDIDATE_ONLY" else 1


if __name__ == "__main__":
    sys.exit(main())
