from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import AI_ROOT, new_id, now_iso, safe_id
from .storage import all_rows, initialize, jdump, jload, one, transaction, upsert


def init_project(name: str, profile: str, root_path: str, *, project_id: str | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    initialize()
    pid = project_id or safe_id(name).upper()
    now = now_iso()
    record = {
        "project_id": pid,
        "name": name.strip(),
        "profile": profile.strip().upper() or "GENERIC",
        "root_path": str(Path(root_path).resolve()),
        "status": "INITIALIZING",
        "created_at": now,
        "updated_at": now,
        "config_json": jdump(config or {}),
    }
    existing = one("SELECT * FROM projects WHERE project_id=?", (pid,))
    if existing:
        record["created_at"] = existing["created_at"]
    upsert("projects", ["project_id"], record)
    return get_project(pid)


def get_project(project_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM projects WHERE project_id=?", (project_id,))
    if not row:
        raise KeyError(f"project not found: {project_id}")
    row["config"] = jload(row.pop("config_json"), {})
    return row


def list_projects() -> list[dict[str, Any]]:
    rows = all_rows("SELECT * FROM projects ORDER BY created_at")
    for row in rows:
        row["config"] = jload(row.pop("config_json"), {})
    return rows


def project_status(project_id: str) -> dict[str, Any]:
    project = get_project(project_id)
    counts = {}
    for name, table in (
        ("systems", "systems"),
        ("environments", "environments"),
        ("repositories", "repositories"),
        ("releases", "releases"),
        ("requirements", "requirements"),
        ("missions", "missions"),
        ("human_tasks", "human_tasks"),
        ("defects", "defects"),
    ):
        if table in {"human_tasks"}:
            row = one(
                "SELECT COUNT(*) AS n FROM human_tasks h JOIN missions m ON h.mission_id=m.mission_id WHERE m.project_id=?",
                (project_id,),
            )
        else:
            row = one(f"SELECT COUNT(*) AS n FROM {table} WHERE project_id=?", (project_id,))
        counts[name] = int((row or {}).get("n", 0))
    readiness = {
        "PROJECT_CONFIGURED": bool(project["name"] and project["root_path"]),
        "REPOSITORY_DISCOVERED": counts["repositories"] > 0,
        "ENVIRONMENT_CONFIGURED": counts["environments"] > 0,
        "TRUTH_CONNECTOR_CONFIGURED": bool(one("SELECT 1 AS ok FROM connectors WHERE project_id=? AND kind IN ('STARLINK','RELEASE_TRUTH') AND status IN ('READY','DEGRADED')", (project_id,))),
        "OBSERVABILITY_CONFIGURED": bool(one("SELECT 1 AS ok FROM connectors WHERE project_id=? AND kind='CAT' AND status IN ('READY','DEGRADED')", (project_id,))),
    }
    if all(readiness.values()):
        status = "PROJECT_READY"
    elif readiness["PROJECT_CONFIGURED"]:
        status = "PROJECT_PARTIAL"
    else:
        status = "PROJECT_INITIALIZING"
    with transaction() as conn:
        conn.execute("UPDATE projects SET status=?, updated_at=? WHERE project_id=?", (status, now_iso(), project_id))
    project["status"] = status
    return {"project": project, "counts": counts, "readiness": readiness, "status": status}


def register_system(project_id: str, system_id: str, name: str, description: str = "", owner: str = "UNKNOWN", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    record = {
        "system_id": system_id,
        "project_id": project_id,
        "name": name,
        "description": description,
        "owner": owner,
        "metadata_json": jdump(metadata or {}),
    }
    upsert("systems", ["system_id"], record)
    return system(project_id, system_id)


def system(project_id: str, system_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM systems WHERE project_id=? AND system_id=?", (project_id, system_id))
    if not row:
        raise KeyError(system_id)
    row["metadata"] = jload(row.pop("metadata_json"), {})
    return row


def register_environment(project_id: str, environment_id: str, name: str, environment_type: str = "TEST", config: dict[str, Any] | None = None) -> dict[str, Any]:
    now = now_iso()
    record = {
        "environment_id": environment_id,
        "project_id": project_id,
        "name": name,
        "environment_type": environment_type,
        "config_json": jdump(config or {}),
        "created_at": now,
        "updated_at": now,
    }
    existing = one("SELECT created_at FROM environments WHERE environment_id=?", (environment_id,))
    if existing:
        record["created_at"] = existing["created_at"]
    upsert("environments", ["environment_id"], record)
    return environment(project_id, environment_id)


def environment(project_id: str, environment_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM environments WHERE project_id=? AND environment_id=?", (project_id, environment_id))
    if not row:
        raise KeyError(environment_id)
    row["config"] = jload(row.pop("config_json"), {})
    return row


def register_connector(
    project_id: str,
    connector_id: str,
    kind: str,
    name: str,
    *,
    adapter_path: str | None = None,
    config: dict[str, Any] | None = None,
    secret_ref: str | None = None,
    status: str = "NOT_CONFIGURED",
) -> dict[str, Any]:
    if secret_ref and not secret_ref.startswith(("secret://", "env://", "profile://")):
        raise ValueError("secret_ref must be a reference, never a plaintext secret")
    record = {
        "connector_id": connector_id,
        "project_id": project_id,
        "kind": kind.upper(),
        "name": name,
        "adapter_path": adapter_path,
        "status": status,
        "config_json": jdump(config or {}),
        "secret_ref": secret_ref,
        "last_checked_at": None,
        "last_error": None,
    }
    upsert("connectors", ["connector_id"], record)
    return get_connector(connector_id)


def get_connector(connector_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM connectors WHERE connector_id=?", (connector_id,))
    if not row:
        raise KeyError(connector_id)
    row["config"] = jload(row.pop("config_json"), {})
    return row


def list_connectors(project_id: str) -> list[dict[str, Any]]:
    rows = all_rows("SELECT * FROM connectors WHERE project_id=? ORDER BY kind,name", (project_id,))
    for row in rows:
        row["config"] = jload(row.pop("config_json"), {})
    return rows


def register_auth_profile(
    project_id: str,
    auth_profile_id: str,
    name: str,
    *,
    environment_id: str | None = None,
    system_id: str | None = None,
    browser_profile_ref: str | None = None,
    secret_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if secret_ref and not secret_ref.startswith(("secret://", "env://", "profile://")):
        raise ValueError("plaintext secret is forbidden")
    record = {
        "auth_profile_id": auth_profile_id,
        "project_id": project_id,
        "environment_id": environment_id,
        "system_id": system_id,
        "name": name,
        "browser_profile_ref": browser_profile_ref,
        "secret_ref": secret_ref,
        "status": "UNKNOWN",
        "expires_at": None,
        "last_verified_at": None,
        "metadata_json": jdump(metadata or {}),
    }
    upsert("auth_profiles", ["auth_profile_id"], record)
    return auth_profile(auth_profile_id)


def auth_profile(auth_profile_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM auth_profiles WHERE auth_profile_id=?", (auth_profile_id,))
    if not row:
        raise KeyError(auth_profile_id)
    row["metadata"] = jload(row.pop("metadata_json"), {})
    return row
