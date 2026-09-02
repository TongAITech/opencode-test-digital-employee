from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .common import now_iso, redact, run_process, safe_id
from .storage import all_rows, jdump, jload, one, upsert


def _git(path: Path, *args: str) -> str:
    result = run_process(["git", "-C", str(path), *args], timeout=30)
    return result["stdout"] if result["ok"] else "UNKNOWN"


def inspect_repository(project_id: str, path: Path, system_id: str | None = None) -> dict[str, Any]:
    root = Path(_git(path, "rev-parse", "--show-toplevel"))
    if str(root) == "UNKNOWN":
        raise ValueError(f"not a git repository: {path}")
    remote = _git(root, "remote", "get-url", "origin")
    branch = _git(root, "branch", "--show-current")
    head = _git(root, "rev-parse", "HEAD")
    default_branch = _git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "--short")
    if default_branch.startswith("origin/"):
        default_branch = default_branch.split("/", 1)[1]
    full_name = root.name
    if remote != "UNKNOWN":
        tail = remote.rstrip("/").split("/")[-1]
        full_name = tail[:-4] if tail.endswith(".git") else tail
    now = now_iso()
    record = {
        "repository_id": f"REPO-{safe_id(full_name).upper()}",
        "project_id": project_id,
        "full_name": full_name,
        "local_path": str(root.resolve()),
        "remote_url": remote,
        "default_branch": default_branch,
        "current_branch": branch,
        "head_sha": head,
        "system_id": system_id,
        "module_name": None,
        "discovered_at": now,
        "updated_at": now,
    }
    existing = one("SELECT discovered_at FROM repositories WHERE project_id=? AND full_name=?", (project_id, full_name))
    if existing:
        record["discovered_at"] = existing["discovered_at"]
    upsert("repositories", ["repository_id"], record)
    return redact(record)


def discover(project_id: str, root_path: str, max_depth: int = 4) -> dict[str, Any]:
    root = Path(root_path).resolve()
    if not root.exists():
        raise FileNotFoundError(root)
    discovered: list[dict[str, Any]] = []
    visited: set[Path] = set()
    for current, dirs, _files in os.walk(root):
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts)
        if depth > max_depth:
            dirs[:] = []
            continue
        if ".git" in dirs:
            repo_root = current_path.resolve()
            dirs.remove(".git")
            if repo_root not in visited:
                visited.add(repo_root)
                try:
                    discovered.append(inspect_repository(project_id, repo_root))
                except Exception as exc:
                    discovered.append({"path": str(repo_root), "status": "ERROR", "error": str(exc)})
            dirs[:] = [d for d in dirs if d not in {"node_modules", ".gitnexus", ".venv", "target", "build", "dist"}]
    return {"project_id": project_id, "root": str(root), "repositories": discovered, "count": len([r for r in discovered if r.get("repository_id")])}


def refresh(project_id: str, repository_id: str | None = None) -> list[dict[str, Any]]:
    rows = all_rows("SELECT * FROM repositories WHERE project_id=?" + (" AND repository_id=?" if repository_id else ""), (project_id, repository_id) if repository_id else (project_id,))
    output = []
    for row in rows:
        output.append(inspect_repository(project_id, Path(row["local_path"]), row.get("system_id")))
    return output


def list_repositories(project_id: str) -> list[dict[str, Any]]:
    return all_rows("SELECT * FROM repositories WHERE project_id=? ORDER BY full_name", (project_id,))


def get_repository(repository_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM repositories WHERE repository_id=?", (repository_id,))
    if not row:
        raise KeyError(repository_id)
    return row
