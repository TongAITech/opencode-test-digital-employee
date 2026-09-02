from __future__ import annotations

from typing import Any

from . import knowledge, skills
from .browser import trace
from .common import new_id, now_iso, redact
from .storage import all_rows, jdump, jload, one, transaction

VALID_TYPES = {"CORRECTION", "EXPLANATION", "DEMONSTRATION", "REVIEW"}


def create_event(
    project_id: str,
    event_type: str,
    subject: str,
    payload: dict[str, Any],
    teacher: str,
) -> dict[str, Any]:
    event_type = event_type.upper()
    if event_type not in VALID_TYPES:
        raise ValueError(event_type)
    tid = new_id("TEACH")
    clean = redact(payload)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO teaching_events(teaching_event_id,project_id,event_type,subject,payload_json,teacher,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (tid, project_id, event_type, subject, jdump(clean), teacher, "CANDIDATE", now_iso()),
        )
    return get_event(tid)


def get_event(teaching_event_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM teaching_events WHERE teaching_event_id=?", (teaching_event_id,))
    if not row:
        raise KeyError(teaching_event_id)
    row["payload"] = jload(row.pop("payload_json"), {})
    return row


def list_events(project_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM teaching_events WHERE project_id=?"
    params: list[Any] = [project_id]
    if status:
        sql += " AND status=?"
        params.append(status.upper())
    sql += " ORDER BY created_at DESC"
    rows = all_rows(sql, params)
    for row in rows:
        row["payload"] = jload(row.pop("payload_json"), {})
    return rows


def materialize(teaching_event_id: str) -> dict[str, Any]:
    event = get_event(teaching_event_id)
    if event["status"] not in {"CANDIDATE", "MATERIALIZED"}:
        raise ValueError(f"teaching event not materializable: {event['status']}")
    payload = event["payload"]
    result: dict[str, Any] = {"teaching_event": event}
    if event["event_type"] in {"CORRECTION", "EXPLANATION", "REVIEW"}:
        candidate = knowledge.create_candidate(
            event["project_id"],
            event["subject"],
            str(payload.get("predicate") or "explained_as"),
            payload.get("correct") if event["event_type"] == "CORRECTION" and "correct" in payload else payload.get("object", payload),
            scope=payload.get("scope") or {},
            source_type="HUMAN_TEACHING",
            source_ref=f"teaching:{teaching_event_id}",
            confidence="HIGH",
        )
        result["knowledge_candidate"] = candidate
    if event["event_type"] == "DEMONSTRATION":
        browser_session_id = payload.get("browser_session_id")
        demonstration = trace(str(browser_session_id)) if browser_session_id else payload.get("trace") or []
        candidate = skills.create_skill(
            event["project_id"],
            str(payload.get("skill_name") or f"{event['subject']}-demonstration"),
            {
                "subject": event["subject"],
                "demonstration": demonstration,
                "success_criteria": payload.get("success_criteria") or {},
                "scope": payload.get("scope") or {},
                "secret_policy": "VALUES_NOT_RECORDED",
            },
            status="CANDIDATE",
            source_ref=f"teaching:{teaching_event_id}",
        )
        result["skill_candidate"] = candidate
    with transaction() as conn:
        conn.execute("UPDATE teaching_events SET status='MATERIALIZED' WHERE teaching_event_id=?", (teaching_event_id,))
    return result


def approve(teaching_event_id: str, reviewer: str) -> dict[str, Any]:
    event = get_event(teaching_event_id)
    with transaction() as conn:
        conn.execute("UPDATE teaching_events SET status='VERIFIED' WHERE teaching_event_id=?", (teaching_event_id,))
    return {**get_event(teaching_event_id), "reviewed_by": reviewer}
