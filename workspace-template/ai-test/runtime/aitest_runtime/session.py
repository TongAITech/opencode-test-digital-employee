from __future__ import annotations

import json
from typing import Any

from .common import new_id, now_iso
from .mission import checkpoint, context_pack, get_mission
from .opencode_client import OpenCodeClient
from .storage import all_rows, jdump, jload, one, transaction

ROLE_AGENT = {
    "DIRECTOR": "aitest-director",
    "PLANNER": "aitest-planner",
    "EXECUTOR": "aitest-executor",
    "EVALUATOR": "aitest-evaluator",
    "DIAGNOSIS": "aitest-diagnosis",
    "KNOWLEDGE": "aitest-knowledge",
    "SCHEDULER": "aitest-scheduler",
}


def open_worker_session(
    mission_id: str,
    worker_role: str,
    *,
    provider: str = "AUTO",
    opencode_url: str = "http://127.0.0.1:4096",
    allow_mock: bool = True,
) -> dict[str, Any]:
    role = worker_role.upper()
    if role not in ROLE_AGENT:
        raise ValueError(f"unknown worker role: {role}")
    provider_session_id = None
    resolved_provider = provider.upper()
    error = None
    if resolved_provider in {"AUTO", "OPENCODE"}:
        try:
            client = OpenCodeClient(opencode_url)
            health = client.health()
            created = client.create_session(f"{mission_id} · {role}")
            provider_session_id = str(created.get("id") or created.get("sessionID") or created.get("session_id"))
            if not provider_session_id:
                raise RuntimeError(f"OpenCode returned no session id: {created}")
            resolved_provider = "OPENCODE"
        except Exception as exc:
            error = str(exc)
            if provider.upper() == "OPENCODE" or not allow_mock:
                raise
            resolved_provider = "MOCK"
    elif resolved_provider != "MOCK":
        raise ValueError(resolved_provider)
    worker_session_id = new_id("WS")
    pack = context_pack(mission_id)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO worker_sessions(worker_session_id,mission_id,worker_role,provider,provider_session_id,status,message_count,compaction_count,context_hash,opened_at,last_error) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (worker_session_id, mission_id, role, resolved_provider, provider_session_id, "OPEN", 0, 0, pack["context_hash"], now_iso(), error),
        )
    if resolved_provider == "OPENCODE":
        prompt = _bootstrap_prompt(pack, role)
        OpenCodeClient(opencode_url).send_message(provider_session_id, prompt, agent=ROLE_AGENT[role], no_reply=True)
    checkpoint(mission_id, f"WORKER_SESSION_OPEN:{role}", worker_session_id=worker_session_id)
    return get_worker_session(worker_session_id)


def _bootstrap_prompt(pack: dict[str, Any], role: str) -> str:
    safe = json.dumps(pack, ensure_ascii=False, indent=2)
    return (
        f"You are the {role} worker for a state-driven AI Test Mission. The runtime state below is authoritative. "
        "Do not invent a new mission or plan. Use only the custom aitest_* tools allowed to your agent role. "
        "Never use bash or edit external repositories.\n\nRUNTIME_CONTEXT:\n" + safe
    )


def get_worker_session(worker_session_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM worker_sessions WHERE worker_session_id=?", (worker_session_id,))
    if not row:
        raise KeyError(worker_session_id)
    return row


def active_worker_session(mission_id: str, worker_role: str) -> dict[str, Any] | None:
    return one(
        "SELECT * FROM worker_sessions WHERE mission_id=? AND worker_role=? AND status='OPEN' ORDER BY opened_at DESC LIMIT 1",
        (mission_id, worker_role.upper()),
    )


def refresh_health(worker_session_id: str, *, opencode_url: str = "http://127.0.0.1:4096", max_messages: int = 60, max_compactions: int = 1) -> dict[str, Any]:
    row = get_worker_session(worker_session_id)
    message_count = int(row["message_count"])
    if row["provider"] == "OPENCODE" and row.get("provider_session_id"):
        try:
            messages = OpenCodeClient(opencode_url).messages(row["provider_session_id"], limit=max_messages + 20)
            message_count = len(messages)
        except Exception as exc:
            with transaction() as conn:
                conn.execute("UPDATE worker_sessions SET last_error=? WHERE worker_session_id=?", (str(exc), worker_session_id))
    decision = "ROTATE" if message_count >= max_messages or int(row["compaction_count"]) >= max_compactions else "CONTINUE"
    with transaction() as conn:
        conn.execute("UPDATE worker_sessions SET message_count=? WHERE worker_session_id=?", (message_count, worker_session_id))
    return {"worker_session_id": worker_session_id, "message_count": message_count, "compaction_count": int(row["compaction_count"]), "decision": decision}


def note_compaction(worker_session_id: str) -> dict[str, Any]:
    with transaction() as conn:
        conn.execute("UPDATE worker_sessions SET compaction_count=compaction_count+1 WHERE worker_session_id=?", (worker_session_id,))
    return get_worker_session(worker_session_id)


def rotate_worker_session(worker_session_id: str, *, reason: str, opencode_url: str = "http://127.0.0.1:4096") -> dict[str, Any]:
    current = get_worker_session(worker_session_id)
    checkpoint(current["mission_id"], f"WORKER_ROTATE:{reason}", worker_session_id=worker_session_id)
    with transaction() as conn:
        conn.execute("UPDATE worker_sessions SET status='CLOSED',closed_at=? WHERE worker_session_id=?", (now_iso(), worker_session_id))
    return open_worker_session(current["mission_id"], current["worker_role"], provider=current["provider"], opencode_url=opencode_url, allow_mock=True)


def recover_mission_sessions(mission_id: str, *, opencode_url: str = "http://127.0.0.1:4096", roles: list[str] | None = None) -> dict[str, Any]:
    roles = roles or ["DIRECTOR"]
    sessions = []
    for role in roles:
        active = active_worker_session(mission_id, role)
        if active:
            sessions.append(active)
        else:
            sessions.append(open_worker_session(mission_id, role, provider="AUTO", opencode_url=opencode_url, allow_mock=True))
    return {"mission": get_mission(mission_id, include_steps=False), "sessions": sessions, "checkpoint": checkpoint(mission_id, "SESSION_RECOVERY")}


def close_worker_session(worker_session_id: str, *, opencode_url: str = "http://127.0.0.1:4096", dispose_provider: bool = False) -> dict[str, Any]:
    row = get_worker_session(worker_session_id)
    checkpoint(row["mission_id"], "WORKER_SESSION_CLOSE", worker_session_id=worker_session_id)
    if dispose_provider and row["provider"] == "OPENCODE" and row.get("provider_session_id"):
        try:
            OpenCodeClient(opencode_url).delete(row["provider_session_id"])
        except Exception:
            pass
    with transaction() as conn:
        conn.execute("UPDATE worker_sessions SET status='CLOSED',closed_at=? WHERE worker_session_id=?", (now_iso(), worker_session_id))
    return get_worker_session(worker_session_id)
