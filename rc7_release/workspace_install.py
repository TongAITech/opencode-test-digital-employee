from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional


def ignore_runtime_state(directory: str, names: List[str]) -> List[str]:
    ignored = []
    base = Path(directory).name.lower()
    if base in ("state", "runtime-state", "reports", "evidence"):
        return list(names)
    for name in names:
        if name in ("__pycache__",) or name.endswith((".pyc", ".pyo")):
            ignored.append(name)
    return ignored


def install(source: Path, target: Path, upgrade: bool, dry_run: bool) -> Dict[str, object]:
    source = source.resolve()
    target = target.resolve()
    if source == target:
        return {"status": "PASS", "mode": "IN_PLACE", "target": str(target), "backup": None}
    if not (source / "PACKAGE_MANIFEST.json").is_file():
        return {"status": "FAIL", "reason": "SOURCE_NOT_RC7_PACKAGE", "source": str(source)}
    backup = None
    if target.exists():
        if not upgrade:
            return {"status": "FAIL", "reason": "TARGET_EXISTS_USE_UPGRADE", "target": str(target)}
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = target.parent / (target.name + ".backup-" + stamp)
        if backup.exists():
            return {"status": "FAIL", "reason": "BACKUP_COLLISION", "backup": str(backup)}
    if dry_run:
        return {"status": "PASS", "mode": "UPGRADE" if target.exists() else "FRESH", "source": str(source), "target": str(target), "backup": str(backup) if backup else None, "dry_run": True}
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copytree(str(target), str(backup))
        preserved = {}
        for rel in ("state", "reports", "evidence"):
            p = target / rel
            if p.exists():
                preserved[rel] = True
        shutil.rmtree(str(target))
    shutil.copytree(str(source), str(target), ignore=ignore_runtime_state)
    for name in ("state", "reports", "evidence"):
        (target / name).mkdir(parents=True, exist_ok=True)
    version = (target / "SOURCE_COMMIT").read_text(encoding="utf-8").strip() if (target / "SOURCE_COMMIT").is_file() else "UNKNOWN"
    (target / "AITEST_VERSION").write_text(version + "\n", encoding="utf-8")
    return {"status": "PASS", "mode": "UPGRADE" if backup else "FRESH", "source": str(source), "target": str(target), "backup": str(backup) if backup else None, "source_commit": version}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--upgrade", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--output")
    args = p.parse_args(argv)
    result = install(Path(args.source), Path(args.target), args.upgrade, args.dry_run)
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        dest = Path(args.output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
