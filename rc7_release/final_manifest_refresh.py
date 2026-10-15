from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional


FINAL_ENTRYPOINTS = (
    "packaging/rc7/AITEST.cmd",
    "packaging/rc7/AITEST.sh",
    "packaging/rc7/INSTALL-RC7.cmd",
    "packaging/rc7/INSTALL-RC7.sh",
    "packaging/rc7/QUALIFY-RC7-FINAL-UNIFIED.cmd",
    "packaging/rc7/QUALIFY-RC7-FINAL-UNIFIED.sh",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if path.name in ("PACKAGE_MANIFEST.json", "CHECKSUMS.sha256"):
            continue
        if "__pycache__" in rel.parts or path.suffix.lower() in (".pyc", ".pyo"):
            continue
        if rel.parts and rel.parts[0] in ("state", "runtime-state", "reports", "evidence"):
            continue
        yield path


def refresh(home: Path) -> Dict[str, object]:
    manifest_path = home / "PACKAGE_MANIFEST.json"
    inventory_path = home / "FULL-CAPABILITY-INVENTORY.json"
    if not manifest_path.is_file() or not inventory_path.is_file():
        return {"status": "FAIL", "reason": "FINAL_MANIFEST_OR_INVENTORY_MISSING"}

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    for capability in inventory.get("capabilities", []):
        cap_id = str(capability.get("id", ""))
        if cap_id == "DSH_PLUGIN:@perrylink/dsh-plugin-doctor":
            capability["tier"] = "PLUGIN_DIAGNOSTIC_OPTIONAL"
            capability["mission_required"] = False
            if capability.get("status") == "MISSING":
                capability["status"] = "OPTIONAL_NOT_RESOLVED"
        elif cap_id.startswith("DSH_PLUGIN:") and cap_id not in (
            "DSH_PLUGIN:dsh-vision-router",
            "DSH_PLUGIN:dsh-plugin-anydoc",
            "DSH_PLUGIN:dsh-memento",
            "DSH_PLUGIN:dsh-error-handling",
        ):
            capability["mission_required"] = True
    inventory["plugin_policy"] = {
        "mission_required": [
            "dsh-routing-suite",
            "@wxg-prc-cpg/browser-skill-dsh-plugin",
            "dsh-context",
            "dsh-plugin-bridge",
            "@nanmicoder/dsh-agent-teams",
        ],
        "diagnostic_optional": ["@perrylink/dsh-plugin-doctor"],
        "optional_disabled_by_default": ["dsh-vision-router", "dsh-plugin-anydoc", "dsh-memento", "dsh-error-handling"],
        "public_remote_vision": "FORBIDDEN",
    }
    inventory_path.write_text(json.dumps(inventory, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entrypoints = list(manifest.get("entrypoints") or [])
    for item in FINAL_ENTRYPOINTS:
        if item not in entrypoints:
            entrypoints.append(item)
    manifest["entrypoints"] = entrypoints
    manifest["final_entrypoint"] = "packaging/rc7/AITEST.cmd"
    manifest["git_bash_entrypoint"] = "packaging/rc7/AITEST.sh"
    manifest["install_entrypoint"] = "packaging/rc7/INSTALL-RC7.cmd"
    manifest["full_capability_inventory"] = "FULL-CAPABILITY-INVENTORY.json"
    manifest["runtime_policy_schema"] = "aitest.offline-runtime-policy.v3"
    manifest["final_unified_turnkey"] = True
    manifest["files"] = [
        {"path": p.relative_to(home).as_posix(), "sha256": sha256_file(p), "size": p.stat().st_size}
        for p in files(home)
    ]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    checksum_lines: List[str] = []
    for p in files(home):
        checksum_lines.append("%s  %s" % (sha256_file(p), p.relative_to(home).as_posix()))
    checksum_lines.append("%s  PACKAGE_MANIFEST.json" % sha256_file(manifest_path))
    (home / "CHECKSUMS.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    return {
        "status": "PASS",
        "file_count": len(manifest["files"]),
        "entrypoint_count": len(entrypoints),
        "plugin_policy": inventory["plugin_policy"],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    result = refresh(Path(args.home).resolve())
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
