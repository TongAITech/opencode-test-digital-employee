from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .static_skills import ALL_SKILLS, PROFESSIONAL_SKILLS

SCHEMA_VERSION = "pfc.aitest.rc6.workspace-install.v1"
PROFILE_SCHEMA_VERSION = "pfc.aitest.rc6.agent-profile.v1"
PROFILE_DIR = Path(".dsh") / "rc6"
MANIFEST_NAME = "INSTALL_MANIFEST.json"
AGENT_PROFILE_NAME = "AGENT_PROFILE.json"
BACKUP_DIR = ".aitest-backup"
ACTIVE_SKILL_ROOTS = (Path(".dsh") / "skills", Path(".agents") / "skills")
LEGACY_OBSERVATION_ROOTS = (Path(".opencode") / "skills", Path(".opencode") / "agents")


class WorkspaceInstallError(RuntimeError):
    pass


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _payload(package_root: Path) -> Dict[str, bytes]:
    root = package_root / ".dsh" / "skills"
    result: Dict[str, bytes] = {}
    for name in ALL_SKILLS:
        path = root / name / "SKILL.md"
        if not path.is_file():
            raise WorkspaceInstallError("RC6_STATIC_SKILL_PAYLOAD_MISSING:%s" % name)
        result[name] = path.read_bytes()
    discovered = {
        p.parent.name for p in root.glob("pfc-*/SKILL.md") if p.parent.name.startswith("pfc-")
    }
    if discovered != set(ALL_SKILLS):
        raise WorkspaceInstallError("RC6_STATIC_SKILL_PAYLOAD_SET_MISMATCH")
    return result


def _source_commit(package_root: Path) -> str:
    path = package_root / "SOURCE_COMMIT"
    if not path.is_file():
        raise WorkspaceInstallError("SOURCE_COMMIT_MISSING")
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 12:
        raise WorkspaceInstallError("SOURCE_COMMIT_INVALID")
    return value


def _managed_entries(root: Path) -> List[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.name.startswith("pfc-") and (p.is_dir() or p.is_file()))


def _read_manifest(workspace: Path) -> Optional[Dict[str, Any]]:
    path = workspace / PROFILE_DIR / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _has_history(workspace: Path) -> bool:
    roots = ACTIVE_SKILL_ROOTS + LEGACY_OBSERVATION_ROOTS
    return any(_managed_entries(workspace / rel) for rel in roots) or (workspace / PROFILE_DIR / MANIFEST_NAME).is_file()


def _mode(workspace: Path, source_commit: str) -> str:
    manifest = _read_manifest(workspace)
    if manifest and manifest.get("schema_version") == SCHEMA_VERSION:
        return "RC6_REPAIR" if manifest.get("source_commit") == source_commit else "UPGRADE_FROM_RC6"
    return "UPGRADE_FROM_LEGACY" if _has_history(workspace) else "FRESH_INSTALL"


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(str(src), str(dst))
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))


def _backup(workspace: Path) -> Optional[Path]:
    items: List[Tuple[Path, Path]] = []
    for rel in ACTIVE_SKILL_ROOTS + LEGACY_OBSERVATION_ROOTS:
        for item in _managed_entries(workspace / rel):
            items.append((item, rel / item.name))
    profile = workspace / PROFILE_DIR
    if profile.is_dir():
        items.append((profile, PROFILE_DIR))
    if not items:
        return None
    out = workspace / BACKUP_DIR / ("rc6-install-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    for src, rel in items:
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        _copy(src, dst)
    return out


def _clear_active(workspace: Path) -> None:
    for rel in ACTIVE_SKILL_ROOTS:
        for item in _managed_entries(workspace / rel):
            shutil.rmtree(str(item)) if item.is_dir() else item.unlink()
    profile = workspace / PROFILE_DIR
    if profile.is_dir():
        shutil.rmtree(str(profile))


def _restore(workspace: Path, backup: Optional[Path]) -> None:
    _clear_active(workspace)
    if not backup or not backup.is_dir():
        return
    for rel in ACTIVE_SKILL_ROOTS + (PROFILE_DIR,):
        src = backup / rel
        if not src.exists():
            continue
        dst = workspace / rel
        if rel == PROFILE_DIR:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(src), str(dst))
        else:
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                _copy(item, dst / item.name)


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(value, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write("\n")


def verify_workspace(package_root: str | Path, workspace: str | Path) -> Dict[str, Any]:
    package, work = Path(package_root).resolve(), Path(workspace).resolve()
    source_commit, payload = _source_commit(package), _payload(package)
    root = work / ".dsh" / "skills"
    active = {p.name for p in _managed_entries(root)}
    if active != set(payload):
        raise WorkspaceInstallError("RC6_ACTIVE_SKILL_SET_MISMATCH")
    for name, raw in payload.items():
        path = root / name / "SKILL.md"
        if not path.is_file() or _sha_bytes(path.read_bytes()) != _sha_bytes(raw):
            raise WorkspaceInstallError("RC6_SKILL_HASH_MISMATCH:%s" % name)
    if _managed_entries(work / ".agents" / "skills"):
        raise WorkspaceInstallError("LEGACY_PFC_PROJECT_AGENT_SKILLS_STILL_ACTIVE")
    manifest = _read_manifest(work)
    if not manifest or manifest.get("source_commit") != source_commit:
        raise WorkspaceInstallError("RC6_INSTALL_MANIFEST_INVALID")
    profile_path = work / PROFILE_DIR / AGENT_PROFILE_NAME
    if not profile_path.is_file():
        raise WorkspaceInstallError("RC6_AGENT_PROFILE_MISSING")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    agents = {x.get("agent_id") for x in profile.get("agents", []) if isinstance(x, dict)}
    if agents != set(PROFESSIONAL_SKILLS):
        raise WorkspaceInstallError("RC6_AGENT_PROFILE_BINDING_MISMATCH")
    return {
        "status": "PASS", "workspace": str(work), "source_commit": source_commit,
        "install_mode": manifest.get("install_mode"), "skill_count": len(payload), "agent_count": len(agents),
        "rc6_agent_install": "PASS", "rc6_skill_install": "PASS",
        "legacy_rc5_pfc_active": False, "rc6_profile_active": "PASS",
    }


def install_workspace(package_root: str | Path, workspace: str | Path) -> Dict[str, Any]:
    package, work = Path(package_root).resolve(), Path(workspace).resolve()
    work.mkdir(parents=True, exist_ok=True)
    source_commit, payload = _source_commit(package), _payload(package)
    mode, backup = _mode(work, source_commit), _backup(work)
    try:
        _clear_active(work)
        root = work / ".dsh" / "skills"
        root.mkdir(parents=True, exist_ok=True)
        hashes: Dict[str, str] = {}
        for name, raw in payload.items():
            path = root / name / "SKILL.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            hashes[name] = _sha_bytes(raw)
        _write_json(work / PROFILE_DIR / AGENT_PROFILE_NAME, {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "source_commit": source_commit,
            "agent_runtime": "DSH_HEADLESS_FRESH_AGENT",
            "worker_skill_binding_required": True,
            "coordinator_skill": "pfc-full-chain-test",
            "agents": [
                {"agent_id": name, "skill": name, "source": "workspace-project-dsh"}
                for name in PROFESSIONAL_SKILLS
            ],
        })
        _write_json(work / PROFILE_DIR / MANIFEST_NAME, {
            "schema_version": SCHEMA_VERSION, "source_commit": source_commit, "install_mode": mode,
            "installed_at_epoch": int(time.time()), "workspace": str(work), "active_skill_root": str(root),
            "skill_hashes": hashes, "backup_path": str(backup) if backup else None,
            "release_status": "ENGINEERING_CANDIDATE_NOT_BANK_FINAL",
            "skill_source": "IMMUTABLE_PACKAGE_STATIC_PAYLOAD",
        })
        result = verify_workspace(package, work)
        result["backup_path"] = str(backup) if backup else None
        return result
    except Exception:
        _restore(work, backup)
        raise


def rollback_workspace(workspace: str | Path, backup: Optional[str] = None) -> Dict[str, Any]:
    work = Path(workspace).resolve()
    chosen = Path(backup).resolve() if backup else None
    if chosen is None:
        root = work / BACKUP_DIR
        choices = sorted((p for p in root.iterdir() if p.is_dir()), reverse=True) if root.is_dir() else []
        chosen = choices[0] if choices else None
    if chosen is None or not chosen.is_dir():
        raise WorkspaceInstallError("ROLLBACK_BACKUP_NOT_FOUND")
    _restore(work, chosen)
    return {"status": "PASS", "workspace": str(work), "restored_from": str(chosen)}


def _default_workspace() -> str:
    return os.environ.get("PFC_WORKSPACE") or (r"D:\PFC" if os.name == "nt" else "/d/PFC")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rc6_release.workspace_install")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--package-root", required=True)
        p.add_argument("--workspace", default=_default_workspace())
    rb = sub.add_parser("rollback")
    rb.add_argument("--workspace", default=_default_workspace())
    rb.add_argument("--backup")
    args = parser.parse_args(argv)
    if args.command == "install":
        result = install_workspace(args.package_root, args.workspace)
    elif args.command == "verify":
        result = verify_workspace(args.package_root, args.workspace)
    else:
        result = rollback_workspace(args.workspace, args.backup)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
