from __future__ import annotations

import hashlib
from typing import Any

from .common import new_id, now_iso, sha256_bytes
from .storage import all_rows, jdump, jload, one, transaction

MISSION_STATES = {
    "DRAFT", "DISCOVERING", "TRUTH_SYNC", "SCOPING", "WAITING_H1", "PLANNING", "WAITING_H2",
    "PREFLIGHT", "WAITING_H3", "EXECUTING", "WAITING_HUMAN", "VERIFYING", "WAITING_H4",
    "COMPLETED", "BLOCKED", "ABORTED",
}
ALLOWED_TRANSITIONS = {
    "DRAFT": {"DISCOVERING", "TRUTH_SYNC", "SCOPING", "ABORTED"},
    "DISCOVERING": {"TRUTH_SYNC", "SCOPING", "BLOCKED", "ABORTED"},
    "TRUTH_SYNC": {"SCOPING", "BLOCKED", "ABORTED"},
    "SCOPING": {"WAITING_H1", "PLANNING", "BLOCKED", "ABORTED"},
    "WAITING_H1": {"PLANNING", "BLOCKED", "ABORTED"},
    "PLANNING": {"WAITING_H2", "PREFLIGHT", "BLOCKED", "ABORTED"},
    "WAITING_H2": {"PREFLIGHT", "PLANNING", "BLOCKED", "ABORTED"},
    "PREFLIGHT": {"WAITING_H3", "BLOCKED", "ABORTED"},
    "WAITING_H3": {"EXECUTING", "PREFLIGHT", "BLOCKED", "ABORTED"},
    "EXECUTING": {"WAITING_HUMAN", "VERIFYING", "BLOCKED", "ABORTED"},
    "WAITING_HUMAN": {"EXECUTING", "VERIFYING", "BLOCKED", "ABORTED"},
    "VERIFYING": {"EXECUTING", "WAITING_H4", "BLOCKED", "ABORTED"},
    "WAITING_H4": {"COMPLETED", "VERIFYING", "BLOCKED", "ABORTED"},
    "BLOCKED": {"DISCOVERING", "TRUTH_SYNC", "SCOPING", "PLANNING", "PREFLIGHT", "EXECUTING", "VERIFYING", "ABORTED"},
    "COMPLETED": set(),
    "ABORTED": set(),
}

ROLE_MAP = {
    "aitest-director": "DIRECTOR",
    "aitest-planner": "PLANNER",
    "aitest-executor": "EXECUTOR",
    "aitest-evaluator": "EVALUATOR",
    "aitest-diagnosis": "DIAGNOSIS",
    "aitest-knowledge": "KNOWLEDGE",
    "aitest-scheduler": "SCHEDULER",
    "human": "HUMAN",
    "system": "SYSTEM",
}


def role_for_actor(actor: str) -> str:
    return ROLE_MAP.get(actor, actor.upper() if actor.upper() in set(ROLE_MAP.values()) else "UNKNOWN")


def _event(mission_id: str, event_type: str, actor: str, payload: dict[str, Any] | None = None) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT INTO mission_events(event_id,mission_id,event_type,actor,payload_json,created_at) VALUES(?,?,?,?,?,?)",
            (new_id("MEV"), mission_id, event_type, actor, jdump(payload or {}), now_iso()),
        )


def create_mission(
    project_id: str,
    title: str,
    created_by: str,
    *,
    release_id: str | None = None,
    requirement_id: str | None = None,
    campaign_id: str | None = None,
    mission_type: str = "TEST",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mission_id = new_id("MISSION")
    now = now_iso()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO missions(mission_id,project_id,release_id,requirement_id,campaign_id,mission_type,title,state,plan_version,current_step_id,resume_state,blocker,created_by,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mission_id, project_id, release_id, requirement_id, campaign_id, mission_type, title, "DRAFT", 0, None, None, None, created_by, now, now, jdump(metadata or {})),
        )
    _event(mission_id, "MISSION_CREATED", created_by, {"title": title, "mission_type": mission_type})
    return get_mission(mission_id)


def get_mission(mission_id: str, *, include_steps: bool = True) -> dict[str, Any]:
    row = one("SELECT * FROM missions WHERE mission_id=?", (mission_id,))
    if not row:
        raise KeyError(mission_id)
    row["metadata"] = jload(row.pop("metadata_json"), {})
    if include_steps and row["plan_version"]:
        steps = all_rows("SELECT * FROM mission_steps WHERE mission_id=? AND plan_version=? ORDER BY ordinal", (mission_id, row["plan_version"]))
        for step in steps:
            for key in ("input_json", "expected_json", "output_json", "evidence_json"):
                if key in step:
                    step[key[:-5] if key.endswith("_json") else key] = jload(step.pop(key), {} if key != "evidence_json" else [])
        row["steps"] = steps
    return row


def list_missions(project_id: str, *, states: list[str] | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM missions WHERE project_id=?"
    params: list[Any] = [project_id]
    if states:
        sql += " AND state IN (" + ",".join("?" for _ in states) + ")"
        params.extend(states)
    sql += " ORDER BY updated_at DESC"
    rows = all_rows(sql, params)
    for row in rows:
        row["metadata"] = jload(row.pop("metadata_json"), {})
    return rows


def transition(mission_id: str, new_state: str, actor: str, *, reason: str = "", blocker: str | None = None, force: bool = False) -> dict[str, Any]:
    new_state = new_state.upper()
    if new_state not in MISSION_STATES:
        raise ValueError(f"invalid mission state: {new_state}")
    current = get_mission(mission_id, include_steps=False)
    if not force and new_state not in ALLOWED_TRANSITIONS[current["state"]]:
        raise ValueError(f"invalid transition {current['state']} -> {new_state}")
    resume_state = current.get("resume_state")
    if new_state == "WAITING_HUMAN":
        resume_state = current["state"]
    elif current["state"] == "WAITING_HUMAN" and new_state in {"EXECUTING", "VERIFYING"}:
        resume_state = None
    with transaction() as conn:
        conn.execute(
            "UPDATE missions SET state=?,resume_state=?,blocker=?,updated_at=? WHERE mission_id=?",
            (new_state, resume_state, blocker, now_iso(), mission_id),
        )
    _event(mission_id, "STATE_TRANSITION", actor, {"from": current["state"], "to": new_state, "reason": reason, "blocker": blocker})
    return get_mission(mission_id)


def submit_plan(mission_id: str, steps: list[dict[str, Any]], actor: str, *, reason: str = "INITIAL_PLAN", replace: bool = False) -> dict[str, Any]:
    if role_for_actor(actor) != "PLANNER":
        raise PermissionError("only PLANNER may submit mission plans")
    mission = get_mission(mission_id, include_steps=False)
    if mission["state"] not in {"PLANNING", "WAITING_H2", "BLOCKED"}:
        raise ValueError(f"mission is not plannable in state {mission['state']}")
    version = int(mission["plan_version"]) + 1
    normalized = []
    for idx, raw in enumerate(steps, 1):
        step_id = str(raw.get("step_id") or f"{mission_id}-S{idx:03d}")
        normalized.append({
            "step_id": step_id,
            "ordinal": idx,
            "title": str(raw.get("title") or step_id),
            "capability_id": raw.get("capability_id"),
            "role_required": str(raw.get("role_required") or "EXECUTOR").upper(),
            "input": raw.get("input") or {},
            "expected": raw.get("expected") or {},
        })
    payload = {"mission_id": mission_id, "version": version, "steps": normalized, "reason": reason}
    plan_hash = sha256_bytes(jdump(payload).encode())
    now = now_iso()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO mission_plans(mission_id,version,status,reason,created_by,created_at,plan_json,plan_hash) VALUES(?,?,?,?,?,?,?,?)",
            (mission_id, version, "FROZEN", reason, actor, now, jdump(payload), plan_hash),
        )
        for step in normalized:
            conn.execute(
                "INSERT INTO mission_steps(step_id,mission_id,plan_version,ordinal,title,capability_id,status,role_required,input_json,expected_json,evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (step["step_id"], mission_id, version, step["ordinal"], step["title"], step["capability_id"], "PENDING", step["role_required"], jdump(step["input"]), jdump(step["expected"]), "[]"),
            )
        first = normalized[0]["step_id"] if normalized else None
        conn.execute("UPDATE missions SET plan_version=?,current_step_id=?,updated_at=?,blocker=NULL WHERE mission_id=?", (version, first, now, mission_id))
    _event(mission_id, "PLAN_FROZEN", actor, {"version": version, "hash": plan_hash, "reason": reason})
    return {"mission": get_mission(mission_id), "plan_version": version, "plan_hash": plan_hash}


def request_replan(mission_id: str, actor: str, reason: str) -> dict[str, Any]:
    if role_for_actor(actor) not in {"DIRECTOR", "HUMAN"}:
        raise PermissionError("replan requires DIRECTOR or HUMAN")
    mission = get_mission(mission_id, include_steps=False)
    if mission["state"] in {"COMPLETED", "ABORTED"}:
        raise ValueError("closed mission cannot be replanned")
    with transaction() as conn:
        conn.execute("UPDATE missions SET state='PLANNING', blocker=?, updated_at=? WHERE mission_id=?", (f"REPLAN_REQUIRED:{reason}", now_iso(), mission_id))
    _event(mission_id, "REPLAN_REQUESTED", actor, {"reason": reason, "previous_plan_version": mission["plan_version"]})
    return get_mission(mission_id)


def current_step(mission_id: str) -> dict[str, Any] | None:
    mission = get_mission(mission_id, include_steps=False)
    if not mission.get("current_step_id"):
        return None
    row = one("SELECT * FROM mission_steps WHERE step_id=?", (mission["current_step_id"],))
    if not row:
        return None
    row["input"] = jload(row.pop("input_json"), {})
    row["expected"] = jload(row.pop("expected_json"), {})
    row["output"] = jload(row.pop("output_json"), None)
    row["evidence"] = jload(row.pop("evidence_json"), [])
    return row


def continue_mission(mission_id: str, actor: str) -> dict[str, Any]:
    """Resume the persisted cursor. This function never creates a new plan."""
    mission = get_mission(mission_id, include_steps=False)
    if mission["state"] == "WAITING_HUMAN":
        waiting = one("SELECT * FROM human_tasks WHERE mission_id=? AND status IN ('WAITING','CLAIMED') ORDER BY created_at DESC LIMIT 1", (mission_id,))
        return {"action": "WAIT_FOR_HUMAN", "mission": mission, "human_task": waiting}
    if mission["state"] == "BLOCKED":
        return {"action": "BLOCKED", "mission": mission, "blocker": mission.get("blocker")}
    if mission["state"] not in {"EXECUTING", "VERIFYING", "WAITING_H3", "WAITING_H4", "PLANNING", "PREFLIGHT"}:
        return {"action": "STATE_REQUIRED", "mission": mission}
    step = current_step(mission_id)
    action = "RESUME_STEP" if step else "NO_PENDING_STEP"
    _event(mission_id, "MISSION_CONTINUE", actor, {"action": action, "step_id": (step or {}).get("step_id"), "plan_version": mission["plan_version"]})
    return {"action": action, "mission": mission, "step": step, "replanned": False}


def claim_step(mission_id: str, actor: str) -> dict[str, Any]:
    role = role_for_actor(actor)
    if role != "EXECUTOR":
        raise PermissionError("only EXECUTOR may claim an execution step")
    mission = get_mission(mission_id, include_steps=False)
    if mission["state"] != "EXECUTING":
        raise ValueError(f"mission state must be EXECUTING, got {mission['state']}")
    step = current_step(mission_id)
    if not step:
        return {"status": "NO_PENDING_STEP"}
    if step["role_required"] != role:
        raise PermissionError(f"step requires {step['role_required']}")
    if step["status"] not in {"PENDING", "READY", "BLOCKED"}:
        raise ValueError(f"step cannot be claimed from {step['status']}")
    with transaction() as conn:
        conn.execute("UPDATE mission_steps SET status='RUNNING',started_at=?,blocker=NULL WHERE step_id=?", (now_iso(), step["step_id"]))
    _event(mission_id, "STEP_CLAIMED", actor, {"step_id": step["step_id"]})
    return current_step(mission_id) or {}


def complete_step(mission_id: str, step_id: str, actor: str, *, status: str, output: dict[str, Any] | None = None, evidence: list[str] | None = None, blocker: str | None = None) -> dict[str, Any]:
    role = role_for_actor(actor)
    if role not in {"EXECUTOR", "EVALUATOR", "SYSTEM"}:
        raise PermissionError("step completion requires EXECUTOR/EVALUATOR/SYSTEM")
    status = status.upper()
    if status not in {"PASS", "FAIL", "BLOCKED", "WAITING_HUMAN", "SKIPPED"}:
        raise ValueError(status)
    step = one("SELECT * FROM mission_steps WHERE step_id=? AND mission_id=?", (step_id, mission_id))
    if not step:
        raise KeyError(step_id)
    with transaction() as conn:
        conn.execute(
            "UPDATE mission_steps SET status=?,output_json=?,evidence_json=?,blocker=?,completed_at=? WHERE step_id=?",
            (status, jdump(output or {}), jdump(evidence or []), blocker, now_iso(), step_id),
        )
        if status in {"PASS", "SKIPPED"}:
            nxt = conn.execute(
                "SELECT step_id FROM mission_steps WHERE mission_id=? AND plan_version=? AND ordinal>? ORDER BY ordinal LIMIT 1",
                (mission_id, step["plan_version"], step["ordinal"]),
            ).fetchone()
            conn.execute("UPDATE missions SET current_step_id=?,updated_at=? WHERE mission_id=?", ((nxt or {}).get("step_id"), now_iso(), mission_id))
        elif status == "FAIL":
            conn.execute("UPDATE missions SET state='VERIFYING',updated_at=? WHERE mission_id=?", (now_iso(), mission_id))
        elif status == "BLOCKED":
            conn.execute("UPDATE missions SET state='BLOCKED',blocker=?,updated_at=? WHERE mission_id=?", (blocker or "STEP_BLOCKED", now_iso(), mission_id))
        elif status == "WAITING_HUMAN":
            conn.execute("UPDATE missions SET state='WAITING_HUMAN',resume_state='EXECUTING',updated_at=? WHERE mission_id=?", (now_iso(), mission_id))
    _event(mission_id, "STEP_COMPLETED", actor, {"step_id": step_id, "status": status, "blocker": blocker})
    return {"mission": get_mission(mission_id), "step": one("SELECT * FROM mission_steps WHERE step_id=?", (step_id,))}


def context_pack(mission_id: str) -> dict[str, Any]:
    mission = get_mission(mission_id)
    project = one("SELECT * FROM projects WHERE project_id=?", (mission["project_id"],))
    release = one("SELECT * FROM releases WHERE release_id=?", (mission.get("release_id"),)) if mission.get("release_id") else None
    requirement = one("SELECT * FROM requirements WHERE requirement_id=?", (mission.get("requirement_id"),)) if mission.get("requirement_id") else None
    ssts = all_rows("SELECT * FROM requirement_ssts WHERE requirement_id=? ORDER BY sst_id", (mission.get("requirement_id"),)) if mission.get("requirement_id") else []
    gates = all_rows("SELECT * FROM gates WHERE requirement_id=? ORDER BY gate_type,updated_at", (mission.get("requirement_id"),)) if mission.get("requirement_id") else []
    human_tasks = all_rows("SELECT * FROM human_tasks WHERE mission_id=? AND status IN ('WAITING','CLAIMED')", (mission_id,))
    defects = all_rows("SELECT * FROM defects WHERE requirement_id=? AND status NOT IN ('CLOSED','NOT_A_DEFECT','DUPLICATE')", (mission.get("requirement_id"),)) if mission.get("requirement_id") else []
    payload = {
        "mission": mission,
        "project": project,
        "release": release,
        "requirement": requirement,
        "ssts": ssts,
        "gates": gates,
        "pending_human_tasks": human_tasks,
        "open_defects": defects,
        "current_step": current_step(mission_id),
    }
    payload["context_hash"] = sha256_bytes(jdump(payload).encode())
    return payload


def checkpoint(mission_id: str, reason: str, *, worker_session_id: str | None = None) -> dict[str, Any]:
    pack = context_pack(mission_id)
    cp_id = new_id("CHK")
    mission = pack["mission"]
    with transaction() as conn:
        conn.execute(
            "INSERT INTO checkpoints(checkpoint_id,mission_id,worker_session_id,state,current_step_id,context_hash,payload_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (cp_id, mission_id, worker_session_id, mission["state"], mission.get("current_step_id"), pack["context_hash"], jdump(pack), reason, now_iso()),
        )
    _event(mission_id, "CHECKPOINT_CREATED", "system", {"checkpoint_id": cp_id, "reason": reason, "context_hash": pack["context_hash"]})
    return {"checkpoint_id": cp_id, "context_hash": pack["context_hash"], "payload": pack}


def latest_checkpoint(mission_id: str) -> dict[str, Any] | None:
    row = one("SELECT * FROM checkpoints WHERE mission_id=? ORDER BY created_at DESC LIMIT 1", (mission_id,))
    if row:
        row["payload"] = jload(row.pop("payload_json"), {})
    return row
