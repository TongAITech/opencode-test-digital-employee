from __future__ import annotations

from typing import Any

from .common import new_id, now_iso
from .storage import all_rows, jdump, jload, one, transaction

STATUSES = {"BASE", "PROJECT", "CANDIDATE", "VERIFIED", "DEPRECATED", "REJECTED"}


def create_skill(
    project_id: str,
    name: str,
    payload: dict[str, Any],
    *,
    status: str = "CANDIDATE",
    source_ref: str | None = None,
) -> dict[str, Any]:
    status = status.upper()
    if status not in STATUSES:
        raise ValueError(status)
    row = one("SELECT COALESCE(MAX(version),0) AS version FROM skill_records WHERE project_id=? AND name=?", (project_id, name))
    version = int((row or {}).get("version") or 0) + 1
    sid = new_id("SKILL")
    now = now_iso()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO skill_records(skill_id,project_id,name,version,status,source_ref,replay_status,regression_status,reviewed_by,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, project_id, name, version, status, source_ref, "NOT_RUN", "NOT_RUN", None, jdump(payload), now, now),
        )
    return get(sid)


def get(skill_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM skill_records WHERE skill_id=?", (skill_id,))
    if not row:
        raise KeyError(skill_id)
    row["payload"] = jload(row.pop("payload_json"), {})
    return row


def list_skills(project_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM skill_records WHERE project_id=?"
    params: list[Any] = [project_id]
    if status:
        sql += " AND status=?"
        params.append(status.upper())
    sql += " ORDER BY name,version DESC"
    rows = all_rows(sql, params)
    for row in rows:
        row["payload"] = jload(row.pop("payload_json"), {})
    return rows


def record_validation(skill_id: str, *, replay_status: str | None = None, regression_status: str | None = None, evidence: list[str] | None = None) -> dict[str, Any]:
    skill = get(skill_id)
    payload = {**skill["payload"]}
    if evidence:
        payload["validation_evidence"] = list(evidence)
    replay = (replay_status or skill["replay_status"]).upper()
    regression = (regression_status or skill["regression_status"]).upper()
    with transaction() as conn:
        conn.execute(
            "UPDATE skill_records SET replay_status=?,regression_status=?,payload_json=?,updated_at=? WHERE skill_id=?",
            (replay, regression, jdump(payload), now_iso(), skill_id),
        )
    return get(skill_id)


def promote(skill_id: str, reviewer: str) -> dict[str, Any]:
    skill = get(skill_id)
    if skill["status"] not in {"CANDIDATE", "PROJECT"}:
        raise ValueError(f"skill is not promotable: {skill['status']}")
    if skill["replay_status"] != "PASS" or skill["regression_status"] != "PASS":
        raise ValueError("SKILL_VALIDATION_NOT_PASS")
    with transaction() as conn:
        conn.execute(
            "UPDATE skill_records SET status='DEPRECATED',updated_at=? WHERE project_id=? AND name=? AND status='VERIFIED' AND skill_id<>?",
            (now_iso(), skill["project_id"], skill["name"], skill_id),
        )
        conn.execute(
            "UPDATE skill_records SET status='VERIFIED',reviewed_by=?,updated_at=? WHERE skill_id=?",
            (reviewer, now_iso(), skill_id),
        )
    return get(skill_id)


def reject(skill_id: str, reviewer: str, reason: str) -> dict[str, Any]:
    skill = get(skill_id)
    payload = {**skill["payload"], "rejection_reason": reason}
    with transaction() as conn:
        conn.execute(
            "UPDATE skill_records SET status='REJECTED',reviewed_by=?,payload_json=?,updated_at=? WHERE skill_id=?",
            (reviewer, jdump(payload), now_iso(), skill_id),
        )
    return get(skill_id)
