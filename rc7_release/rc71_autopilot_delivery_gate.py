"""RC7.1 clean-package gate for autonomous Mission runtime delivery.

This gate is intentionally executed *from the built package* by its bundled
Python.  A repository-side green test is not enough: the final payload must
contain the Autostart, Mission Autopilot, per-Case Execution and ACTIVE_TASK
Supervisor modules, and the package manifest/checksum truth must cover them.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
from typing import Dict, Optional, Sequence


REQUIRED_AUTOPILOT_FILES = (
    "rc7_runtime/bank_mission_start.py",
    "rc7_runtime/bank_mission_autopilot.py",
    "rc7_runtime/bank_execution_autopilot.py",
    "rc7_runtime/active_task_supervisor.py",
    "rc7_runtime/execution_capability.py",
    "packaging/rc7/START-RC7-BANK-MISSION.cmd",
    "packaging/rc7/START-RC7-BANK-MISSION.sh",
)
REQUIRED_IMPORTS = (
    "rc7_runtime.bank_mission_start",
    "rc7_runtime.bank_mission_autopilot",
    "rc7_runtime.bank_execution_autopilot",
    "rc7_runtime.active_task_supervisor",
    "rc7_runtime.execution_capability",
)
EXPECTED_ENTRYPOINT = "packaging/rc7/START-RC7-BANK-MISSION.cmd"


class Rc71AutopilotDeliveryError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _checksums(root: Path) -> Dict[str, str]:
    path = root / "CHECKSUMS.sha256"
    if not path.is_file():
        raise Rc71AutopilotDeliveryError("RC71_CHECKSUMS_REQUIRED")
    values: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise Rc71AutopilotDeliveryError("RC71_CHECKSUM_LINE_INVALID") from exc
        values[relative] = digest
    return values


def verify(package_root: Path) -> Dict[str, object]:
    root = package_root.expanduser().resolve()
    if not root.is_dir():
        raise Rc71AutopilotDeliveryError("RC71_PACKAGE_ROOT_REQUIRED")
    manifest_path = root / "PACKAGE_MANIFEST.json"
    if not manifest_path.is_file():
        raise Rc71AutopilotDeliveryError("RC71_PACKAGE_MANIFEST_REQUIRED")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Rc71AutopilotDeliveryError("RC71_PACKAGE_MANIFEST_INVALID") from exc
    if not isinstance(manifest, dict):
        raise Rc71AutopilotDeliveryError("RC71_PACKAGE_MANIFEST_OBJECT_REQUIRED")
    if manifest.get("mission_runtime_entrypoint") != EXPECTED_ENTRYPOINT:
        raise Rc71AutopilotDeliveryError("RC71_MISSION_ENTRYPOINT_MISMATCH")

    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, list):
        raise Rc71AutopilotDeliveryError("RC71_MANIFEST_FILES_REQUIRED")
    manifest_paths = {
        str(item.get("path"))
        for item in manifest_files
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    checksums = _checksums(root)

    missing = []
    manifest_missing = []
    checksum_missing = []
    hash_mismatch = []
    for relative in REQUIRED_AUTOPILOT_FILES:
        path = root / relative
        if not path.is_file():
            missing.append(relative)
            continue
        if relative not in manifest_paths:
            manifest_missing.append(relative)
        expected = checksums.get(relative)
        if not expected:
            checksum_missing.append(relative)
        elif expected != _sha256(path):
            hash_mismatch.append(relative)
    if missing:
        raise Rc71AutopilotDeliveryError("RC71_AUTOPILOT_FILE_MISSING:" + ",".join(missing))
    if manifest_missing:
        raise Rc71AutopilotDeliveryError("RC71_AUTOPILOT_MANIFEST_MISSING:" + ",".join(manifest_missing))
    if checksum_missing:
        raise Rc71AutopilotDeliveryError("RC71_AUTOPILOT_CHECKSUM_MISSING:" + ",".join(checksum_missing))
    if hash_mismatch:
        raise Rc71AutopilotDeliveryError("RC71_AUTOPILOT_HASH_MISMATCH:" + ",".join(hash_mismatch))

    for relative in (
        "packaging/rc7/START-RC7-BANK-MISSION.cmd",
        "packaging/rc7/START-RC7-BANK-MISSION.sh",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        if "rc7_runtime.bank_mission_start" not in text:
            raise Rc71AutopilotDeliveryError("RC71_AUTOSTART_ENTRY_NOT_WIRED:%s" % relative)
        if "rc7_runtime.bank_mission --r1" in text:
            raise Rc71AutopilotDeliveryError("RC71_BOOTSTRAP_ONLY_ENTRY_FORBIDDEN:%s" % relative)

    imported = []
    for module_name in REQUIRED_IMPORTS:
        module = importlib.import_module(module_name)
        module_file = Path(str(getattr(module, "__file__", ""))).resolve()
        try:
            module_file.relative_to(root)
        except ValueError as exc:
            raise Rc71AutopilotDeliveryError(
                "RC71_IMPORT_ESCAPED_PACKAGE:%s:%s" % (module_name, module_file)
            ) from exc
        imported.append(module_name)

    return {
        "status": "PASS",
        "package_root": str(root),
        "required_file_count": len(REQUIRED_AUTOPILOT_FILES),
        "manifest_coverage": "PASS",
        "checksum_coverage": "PASS",
        "autostart_entry": "PASS",
        "package_local_imports": imported,
        "manual_continue_required": False,
        "canonical_truth": "runtime-state/r1/event-stream.jsonl",
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Verify RC7.1 Autopilot runtime exists in the built package")
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--output")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = verify(Path(args.package_root))
    except Exception as exc:
        payload = {"status": "FAIL", "reason": str(exc)}
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2 if args.require_pass else 1
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
