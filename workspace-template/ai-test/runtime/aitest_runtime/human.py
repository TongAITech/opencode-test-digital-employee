from __future__ import annotations

from typing import Any

from .common import new_id, now_iso
from .mission import complete_step, get_mission, transition
from .storage import all_rows, jdump, jload, one, transaction

VALID_TYPES = {"AUTH", "MFA", "OTP", "CAPTCHA", "FACE", "BUSINESS_CONFIRMATION", "REVIEW", "DATA_INPUT", "SHOWCASE", "APPROVAL", "DEMONSTRATION"}


def create_task(
    mission_id: str,
    task_type: str,
    title: str,
    requested_action: str,
    *,
    step_id: str | None = None,
    assigned_to: str | None = None,
    browser_session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kind = task_type.upper()
    if kind not in VALID_TYPES:
        raise ValueError(kind)
    mission = get_mission(mission_id, include_steps=False)
    resume_state = mission["state"] if mission["state"] in {"EXECUTING", "VERIFYING"} else (mission.get("resume_state") or "EXECUTING")
    task_id = new_id("HT")
    with transaction() as conn:
        conn.execute(
            "INSERT INTO human_tasks(human_task_id,mission_id,step_id,task_type,title,requested_action,assigned_to,status,resume_state,resume_step_id,metadata_json,browser_session_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, mission_id, step_id, kind, title, requested_action, assigned_to, "WAITING", resume_state, step_id or mission.get("current_step_id"), jdump(metadata or {}), browser_session_id, now_iso()),
        )
    if mission["state"] != "WAITING_HUMAN":
        transition(mission_id, "WAITING_HUMAN", "system", reason=f"HUMAN_TASK:{kind}")
    return get_task(task_id)


def get_task(task_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM human_tasks WHERE human_task_id=?", (task_id,))
    if not row:
        raise KeyError(task_id)
    row["human_evidence"] = jload(row.pop("human_evidence_json"), [])
    row["metadata"] = jload(row.pop("metadata_json"), {})
    return row


def list_tasks(project_id: str, statuses: list[str] | None = None) -> list[dict[str, Any]]:
    sql = "SELECT h.* FROM human_tasks h JOIN missions m ON h.mission_id=m.mission_id WHERE m.project_id=?"
    params: list[Any] = [project_id]
    if statuses:
        sql += " AND h.status IN (" + ",".join("?" for _ in statuses) + ")"
        params.extend(statuses)
    sql += " ORDER BY h.created_at DESC"
    rows = all_rows(sql, params)
    for row in rows:
        row["human_evidence"] = jload(row.pop("human_evidence_json"), [])
        row["metadata"] = jload(row.pop("metadata_json"), {})
    return rows


def claim_task(task_id: str, user_id: str) -> dict[str, Any]:
    task = get_task(task_id)
    if task["status"] != "WAITING":
        raise ValueError(f"task not claimable: {task['status']}")
    with transaction() as conn:
        conn.execute("UPDATE human_tasks SET status='CLAIMED',assigned_to=?,claimed_at=? WHERE human_task_id=?", (user_id, now_iso(), task_id))
    return get_task(task_id)


def complete_task(task_id: str, user_id: str, *, comment: str = "", evidence: list[str] | None = None) -> dict[str, Any]:
    task = get_task(task_id)
    if task["status"] not in {"WAITING", "CLAIMED"}:
        raise ValueError(f"task not completable: {task['status']}")
    if task.get("assigned_to") and task["assigned_to"] != user_id:
        raise PermissionError("task is assigned to another user")
    with transaction() as conn:
        conn.execute(
            "UPDATE human_tasks SET status='COMPLETED',assigned_to=?,human_comment=?,human_evidence_json=?,completed_at=? WHERE human_task_id=?",
            (user_id, comment, jdump(evidence or []), now_iso(), task_id),
        )
    mission = get_mission(task["mission_id"], include_steps=False)
    if task.get("step_id"):
        step = one("SELECT status FROM mission_steps WHERE step_id=?", (task["step_id"],))
        if step and step["status"] == "WAITING_HUMAN":
            with transaction() as conn:
                conn.execute("UPDATE mission_steps SET status='READY',blocker=NULL,completed_at=NULL WHERE step_id=?", (task["step_id"],))
    remaining = one("SELECT COUNT(*) AS n FROM human_tasks WHERE mission_id=? AND status IN ('WAITING','CLAIMED')", (task["mission_id"],))
    if int((remaining or {}).get("n", 0)) == 0 and mission["state"] == "WAITING_HUMAN":
        transition(task["mission_id"], task["resume_state"], user_id, reason=f"HUMAN_TASK_COMPLETED:{task_id}")
    if task.get("browser_session_id"):
        # Hand the controlled browser back to the Executor after the human
        # completes authentication/showcase/confirmation.  Lease transfer is
        # best-effort because the user may have closed the browser manually.
        try:
            from .browser import get_browser_session, transfer_lease
            browser_session = get_browser_session(task["browser_session_id"])
            if browser_session.get("lease_owner") == "HUMAN":
                transfer_lease(task["browser_session_id"], "HUMAN", "AI")
        except (KeyError, PermissionError):
            pass
    return {"task": get_task(task_id), "mission": get_mission(task["mission_id"]), "resume_cursor": task.get("resume_step_id")}


def cancel_task(task_id: str, user_id: str, reason: str) -> dict[str, Any]:
    with transaction() as conn:
        conn.execute("UPDATE human_tasks SET status='CANCELLED',assigned_to=?,human_comment=?,completed_at=? WHERE human_task_id=?", (user_id, reason, now_iso(), task_id))
    return get_task(task_id)
