from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import knowledge
from .common import new_id, now_iso, sha256_file
from .project import init_project, register_environment, register_system
from .repository import discover
from .storage import all_rows, jdump, one, transaction
from .truth import link_requirement_sst, link_version_sst, register_release, register_requirement


def detect_source(source: str) -> dict[str, Any]:
    root = Path(source).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(root)
    version = "UNKNOWN"
    for candidate in (root / "VERSION", root / "workspace-template" / "VERSION"):
        if candidate.exists():
            version = candidate.read_text(encoding="utf-8", errors="replace").strip()
            break
    if (root / "ai-test" / "state" / "aitest.db").exists():
        kind = "V1.11"
    elif (root / "ai-test" / "runtime" / "kybctl.py").exists() or (root / "workspace-template" / "ai-test" / "runtime" / "kybctl.py").exists():
        kind = "V1.10.2"
    elif (root / "START_TODAY.md").exists() or (root / "ai-test").exists():
        kind = "V1.9.4"
    else:
        kind = "GENERIC_LEGACY"
    return {"root": str(root), "version": version, "kind": kind}


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (json.JSONDecodeError, OSError):
        return default


def _safe_text_facts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    # Intentionally do not import lines that look like credentials, IP/password tuples, cookies or tokens.
    text = path.read_text(encoding="utf-8", errors="replace")
    facts = []
    for no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or re.search(r"(?i)(password|passwd|pwd|token|cookie|authorization|登录密码|数据库信息)", stripped):
            continue
        if re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", stripped) and len(stripped.split()) >= 4:
            continue
        if len(stripped) > 500:
            continue
        facts.append({"line": no, "text": stripped})
    return facts


def import_legacy(source: str, *, project_name: str, profile: str = "GENERIC", project_root: str | None = None, project_id: str | None = None) -> dict[str, Any]:
    info = detect_source(source)
    src = Path(info["root"])
    destination_root = project_root or str(src)
    project = init_project(project_name, profile, destination_root, project_id=project_id, config={"migration_source": info})
    imported: dict[str, int] = {"repositories": 0, "releases": 0, "requirements": 0, "ssts": 0, "knowledge_candidates": 0}
    try:
        imported["repositories"] = len(discover(project["project_id"], destination_root).get("repositories", []))
    except Exception:
        pass
    config_root = src / "ai-test" / "config"
    if not config_root.exists():
        config_root = src / "workspace-template" / "ai-test" / "config"
    old_project = _read_json(config_root / "project.json", {})
    for item in old_project.get("environments", []) if isinstance(old_project, dict) else []:
        try:
            register_environment(project["project_id"], str(item.get("id") or item.get("name")), str(item.get("name") or item.get("id")), config={k:v for k,v in item.items() if k not in {"password","token","secret","cookie"}})
        except Exception:
            pass
    releases = _read_json(src / "ai-test" / "releases" / "index.json", {})
    if not releases:
        releases = _read_json(src / "workspace-template" / "ai-test" / "releases" / "index.json", {})
    for item in (releases.get("releases") or []) if isinstance(releases, dict) else []:
        rid = str(item.get("release_id") or item.get("id") or "").strip()
        if not rid:
            continue
        register_release(project["project_id"], rid, str(item.get("name") or rid), str(item.get("release_branch") or "UNKNOWN"), source_ref=f"legacy:{info['kind']}")
        imported["releases"] += 1
    # Conservative Markdown import: records become LEGACY_UNVERIFIED knowledge candidates, never canonical truth.
    for md in [src / "START_TODAY.md", src / "ai-test" / "state" / "active-work.md", src / "workspace-template" / "ai-test" / "state" / "active-work.md"]:
        for fact in _safe_text_facts(md):
            knowledge.create_candidate(project["project_id"], "legacy-note", "contains", fact, scope={}, source_type="LEGACY_UNVERIFIED", source_ref=f"{md}:{fact['line']}", confidence="LOW")
            imported["knowledge_candidates"] += 1
    migration_id = new_id("MIG")
    report = {"migration_id": migration_id, "source": info, "project": project, "imported": imported, "trust": "LEGACY_UNVERIFIED", "created_at": now_iso()}
    report_path = Path(__file__).resolve().parents[2] / "migrations" / f"{migration_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
