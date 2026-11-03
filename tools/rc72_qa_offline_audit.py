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
PACKAGE_NAME = "PFC-AITest-DSH-Turnkey-RC7.2-BANK-WIN10"
BUILD_STATUS = "ENGINEERING_CANDIDATE_NOT_BANK_FINAL"
MANIFEST_SCHEMA = "pfc.aitest.rc7.2.package.v1"
IDENTITY_SCHEMA = "pfc.aitest.rc7.2.release-identity.v1"
INVENTORY_SCHEMA = "RC72_FULL_PHYSICAL_PAYLOAD_V1"

GROUPS = (
    "python", "node", "node-execution", "browser", "code-intelligence",
    "java", "maven", "maven-repository", "allure", "k6", "zap", "ripgrep", "dsh-plugins",
)
MANDATORY = (
    "SOURCE_COMMIT", "BUILD_ID", "RELEASE_FAMILY", "RELEASE_STATUS",
    "PACKAGE_MANIFEST.json", "CHECKSUMS.sha256", "FULL-CAPABILITY-INVENTORY.json",
    "RC72_RELEASE_IDENTITY.json",
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
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise QualificationError("JSON_OBJECT_REQUIRED:" + path.name)
        return document
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


def _native_dsh_executable(path, rel):
    """Physical executable admission only; does not prove DSH can start."""
    if rel not in ("workspace-template/runtime/dsh/dsh.exe", "workspace-template/runtime/dsh/dsh"):
        return False
    if not path.is_file() or path.stat().st_size < 4096:
        return False
    with path.open("rb") as stream:
        signature = stream.read(4)
        if rel.endswith(".exe"):
            if not signature.startswith(b"MZ"):
                return False
            stream.seek(0x3c)
            offset_raw = stream.read(4)
            if len(offset_raw) != 4:
                return False
            offset = int.from_bytes(offset_raw, "little")
            if offset < 64 or offset > min(path.stat().st_size - 4, 1024 * 1024):
                return False
            stream.seek(offset)
            return stream.read(4) == bytes((80, 69, 0, 0))
        # A native Linux binary needs ELF; sh or node wrappers are not enough
        # to attest the physical DSH engine itself.
        return signature == bytes((127, 69, 76, 70))


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
    build_id = "RC7.2-" + expected_source.lower()[:12]
    if _read(root / "BUILD_ID") != build_id:
        raise QualificationError("BUILD_ID_MISMATCH")
    if _read(root / "RELEASE_STATUS") != BUILD_STATUS:
        raise QualificationError("RELEASE_STATUS_MISMATCH")

    manifest = _json(root / "PACKAGE_MANIFEST.json")
    inventory = _json(root / "FULL-CAPABILITY-INVENTORY.json")
    identity = _json(root / "RC72_RELEASE_IDENTITY.json")
    if (identity.get("schema") != IDENTITY_SCHEMA or identity.get("release_family") != "RC7.2"
            or identity.get("package_name") != PACKAGE_NAME or identity.get("source_commit") != expected_source.lower()
            or identity.get("build_id") != build_id or identity.get("business_root") != "RELEASE_BATCH"
            or identity.get("runtime_control_backbone") != "N1_N10_MISSION_GRAPH"):
        raise QualificationError("RELEASE_IDENTITY_MISMATCH")
    if identity.get("field_verified") is not False or identity.get("bank_final") is not False:
        raise QualificationError("RELEASE_IDENTITY_FALSE_FIELD_STATUS")
    if (manifest.get("schema_version") != MANIFEST_SCHEMA or manifest.get("status") != BUILD_STATUS
            or manifest.get("release_family") != "RC7.2" or manifest.get("build_id") != build_id
            or manifest.get("package_name") != PACKAGE_NAME
            or manifest.get("business_root") != "RELEASE_BATCH"
            or manifest.get("runtime_control_backbone") != "N1_N10_MISSION_GRAPH"):
        raise QualificationError("MANIFEST_PRODUCT_IDENTITY_MISMATCH")
    for forbidden in ("real_mission_pass", "delivery_pass", "bank_field_pass"):
        if manifest.get(forbidden) is not False:
            raise QualificationError("MANIFEST_FALSE_COMPLETION:" + forbidden)
    if (inventory.get("schema") != INVENTORY_SCHEMA or inventory.get("release_family") != "RC7.2"
            or inventory.get("status") != "PASS" or inventory.get("field_verified") is not False
            or inventory.get("bank_final") is not False):
        raise QualificationError("INVENTORY_PRODUCT_IDENTITY_MISMATCH")
    if not isinstance(manifest.get("source_commit"), str) or manifest["source_commit"].lower() != expected_source.lower():
        raise QualificationError("MANIFEST_SOURCE_MISMATCH")
    if manifest.get("field_verified") is not False or manifest.get("bank_final") is not False:
        raise QualificationError("FALSE_FIELD_STATUS")
    if not isinstance(inventory.get("source_commit"), str) or inventory["source_commit"].lower() != expected_source.lower():
        raise QualificationError("INVENTORY_SOURCE_MISMATCH")
    if inventory.get("qualification_scope") != "PHYSICAL_INVENTORY_ONLY":
        raise QualificationError("INVENTORY_SCOPE_INVALID")
    rows = inventory.get("groups")
    if not isinstance(rows, list) or set(row.get("group") for row in rows if isinstance(row, dict)) != set(GROUPS) or len(rows) != len(GROUPS):
        raise QualificationError("REQUIRED_GROUPS_INCOMPLETE")

    checksums = _checksum_rows(root)
    manifest_paths = set()
    if not isinstance(manifest.get("files"), list) or not manifest["files"]:
        raise QualificationError("MANIFEST_FILES_REQUIRED")
    for item in manifest["files"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise QualificationError("MANIFEST_FILE_INVALID")
        rel = item["path"]
        if rel in manifest_paths:
            raise QualificationError("MANIFEST_DUPLICATE:" + rel)
        manifest_paths.add(rel)
        path = _inside(root, rel)
        if not path.is_file() or rel not in checksums:
            raise QualificationError("MANIFEST_FILE_NOT_CHECKSUMMED:" + rel)
        if (not isinstance(item.get("sha256"), str) or item["sha256"].lower() != checksums[rel]
                or type(item.get("size")) is not int or item["size"] != path.stat().st_size):
            raise QualificationError("MANIFEST_BYTES_MISMATCH:" + rel)

    # The product packager lists every ordinary physical file in CHECKSUMS and
    # every file except PACKAGE_MANIFEST.json in manifest.files.  Independently
    # compare those sets: a correctly hashed subset is NOT a complete payload.
    if "PACKAGE_MANIFEST.json" not in checksums or manifest_paths != set(checksums) - {"PACKAGE_MANIFEST.json"}:
        raise QualificationError("MANIFEST_CHECKSUM_COVERAGE_MISMATCH")
    disk_files = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise QualificationError("PHYSICAL_SYMLINK_FORBIDDEN:" + path.relative_to(root).as_posix())
        if not path.is_file():
            continue
        relpath = path.relative_to(root)
        if ("__pycache__" in relpath.parts or relpath.suffix in (".pyc", ".pyo")
                or (relpath.parts and relpath.parts[0] in ("runtime-state", "state"))):
            # Same exclusions as the upstream package writer: runtime output
            # never becomes a claim of immutable transport-file integrity.
            continue
        rel = relpath.as_posix()
        if rel != "CHECKSUMS.sha256":
            disk_files.add(rel)
    if disk_files != set(checksums):
        raise QualificationError("PHYSICAL_CHECKSUM_COVERAGE_MISMATCH")

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
        present = [p for p in folder.rglob("*")
                   if p.is_file() and "__pycache__" not in p.relative_to(root).parts
                   and p.suffix not in (".pyc", ".pyo")]
        if not present or not any(p.stat().st_size for p in present):
            raise QualificationError("GROUP_EMPTY:" + name)
        actual_count = len(present)
        actual_bytes = sum(p.stat().st_size for p in present)
        if (type(group.get("files")) is not int or type(group.get("bytes")) is not int
                or group["files"] != actual_count or group["bytes"] != actual_bytes):
            raise QualificationError("GROUP_INVENTORY_BYTES_MISMATCH:" + name)
        group_report.append({"group": name, "present_files": actual_count, "physical_bytes": actual_bytes})

    holds = []
    if not dsh_relpath:
        holds.append("DSH_MAIN_PHYSICAL_BINARY_NOT_ATTESTED")
    else:
        path = _inside(root, dsh_relpath)
        if dsh_relpath not in checksums or dsh_relpath not in manifest_paths or not path.is_file():
            holds.append("DSH_MAIN_NOT_CARRIED_AND_CHECKSUMMED")
        elif not _native_dsh_executable(path, dsh_relpath):
            holds.append("DSH_MAIN_NATIVE_EXECUTABLE_NOT_ATTESTED")
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


def _report_destination(root, report):
    """The verifier must never self-modify the payload it is auditing."""
    package_root = Path(root).resolve()
    dest = Path(report).resolve()
    if os.path.commonpath([str(package_root), str(dest)]) == str(package_root):
        raise QualificationError("AUDIT_REPORT_MUST_BE_OUTSIDE_PACKAGE")
    if dest.exists():
        raise QualificationError("AUDIT_REPORT_ALREADY_EXISTS")
    return dest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fail-closed independent RC7.2 physical payload QA; never BANK_FINAL")
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--dsh-relpath", default=None, help="Path to a physically carried signed/checksummed DSH main binary")
    parser.add_argument("--report", default=None, help="JSON output, preferably outside the package root")
    options = parser.parse_args(argv)
    report = None
    try:
        if options.report:
            report = _report_destination(options.package_root, options.report)
        result = qualify(options.package_root, expected_source=options.expected_source_commit, dsh_relpath=options.dsh_relpath)
    except (QualificationError, OSError, ValueError) as exc:
        result = {"schema": "RC72_QA_PHYSICAL_AUDIT_V1", "status": "FAIL", "reason": str(exc),
                  "field_verified": False, "bank_final": False}
    output = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + chr(10)
    if report is not None:
        try:
            with report.open("x", encoding="utf-8") as dest:
                dest.write(output)
        except OSError as exc:
            print(json.dumps({"status": "FAIL", "reason": "AUDIT_REPORT_WRITE_REFUSED:" + str(exc),
                              "field_verified": False, "bank_final": False}))
            return 1
    print(output)
    return 0 if result["status"] == "PHYSICAL_CANDIDATE_ONLY" else 1


if __name__ == "__main__":
    sys.exit(main())
