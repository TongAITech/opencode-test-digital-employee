from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .common import AI_ROOT, WORKSPACE_ROOT, new_id, now_iso, redact
from .storage import all_rows, jdump, jload, one, transaction


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _find_browser(explicit: str | None = None) -> str | None:
    candidates = []
    configured = explicit or os.environ.get("AITEST_BROWSER_EXECUTABLE")
    if configured:
        candidates.append(configured)
    # V1.11.1 full-offline: portable Chrome for Testing is preferred over
    # machine-global browsers so BrowserSession behavior is reproducible.
    if os.name == "nt":
        portable = WORKSPACE_ROOT / "runtime" / "browser" / "chrome-win64" / "chrome.exe"
        candidates.append(str(portable))
    if os.name == "nt":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                candidates.extend([
                    str(Path(base) / "Google/Chrome/Application/chrome.exe"),
                    str(Path(base) / "Microsoft/Edge/Application/msedge.exe"),
                ])
    else:
        candidates.extend(["google-chrome", "chromium", "chromium-browser", "microsoft-edge", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"])
    for candidate in candidates:
        if Path(candidate).exists():
            return str(Path(candidate))
        found = shutil.which(candidate)
        if found:
            return found
    return None


def create_browser_session(
    project_id: str,
    mode: str,
    *,
    mission_id: str | None = None,
    human_task_id: str | None = None,
    environment_id: str | None = None,
    auth_profile_id: str | None = None,
    lease_owner: str = "HUMAN",
    start_url: str | None = None,
    allowed_domains: list[str] | None = None,
) -> dict[str, Any]:
    sid = new_id("BS")
    profile_path = AI_ROOT / "control-plane" / "browser-profiles" / sid
    profile_path.mkdir(parents=True, exist_ok=True)
    now = now_iso()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO browser_sessions(browser_session_id,project_id,mission_id,human_task_id,environment_id,auth_profile_id,mode,lease_owner,status,start_url,allowed_domains_json,profile_path,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, project_id, mission_id, human_task_id, environment_id, auth_profile_id, mode.upper(), lease_owner.upper(), "CREATED", start_url, jdump(allowed_domains or []), str(profile_path), now, now),
        )
        if human_task_id:
            conn.execute("UPDATE human_tasks SET browser_session_id=? WHERE human_task_id=?", (sid, human_task_id))
    return get_browser_session(sid)


def get_browser_session(browser_session_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM browser_sessions WHERE browser_session_id=?", (browser_session_id,))
    if not row:
        raise KeyError(browser_session_id)
    row["allowed_domains"] = jload(row.pop("allowed_domains_json"), [])
    return row


def launch_browser(
    project_id: str,
    mode: str = "TEACH",
    *,
    browser_session_id: str | None = None,
    mission_id: str | None = None,
    human_task_id: str | None = None,
    environment_id: str | None = None,
    auth_profile_id: str | None = None,
    start_url: str | None = None,
    allowed_domains: list[str] | None = None,
    browser_executable: str | None = None,
    dry_run: bool = False,
    control_plane_url: str = "http://127.0.0.1:8765",
) -> dict[str, Any]:
    session = get_browser_session(browser_session_id) if browser_session_id else create_browser_session(
        project_id, mode, mission_id=mission_id, human_task_id=human_task_id, environment_id=environment_id,
        auth_profile_id=auth_profile_id, lease_owner="HUMAN", start_url=start_url, allowed_domains=allowed_domains,
    )
    executable = _find_browser(browser_executable)
    port = _free_port()
    extension = AI_ROOT / "control-plane" / "browser-extension"
    url = start_url or session.get("start_url") or "about:blank"
    host = urlparse(url).hostname
    allowed = session.get("allowed_domains") or allowed_domains or []
    if host and allowed and host not in allowed:
        raise PermissionError(f"START_URL_NOT_ALLOWED:{host}")
    command = [
        executable or "<BROWSER_NOT_FOUND>",
        f"--user-data-dir={session['profile_path']}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        f"--load-extension={extension}",
        f"--disable-extensions-except={extension}",
        url,
    ]
    process_id = None
    status = "READY_TO_LAUNCH"
    if not dry_run:
        if not executable:
            status = "BROWSER_NOT_FOUND"
        else:
            env = os.environ.copy()
            env["AITEST_BROWSER_SESSION_ID"] = session["browser_session_id"]
            env["AITEST_CONTROL_PLANE_URL"] = control_plane_url
            process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            process_id = process.pid
            status = "OPEN"
    with transaction() as conn:
        conn.execute(
            "UPDATE browser_sessions SET status=?,debug_port=?,process_id=?,updated_at=? WHERE browser_session_id=?",
            (status, port, process_id, now_iso(), session["browser_session_id"]),
        )
    return {"browser_session": get_browser_session(session["browser_session_id"]), "command": command, "launched": status == "OPEN"}


def transfer_lease(browser_session_id: str, from_owner: str, to_owner: str) -> dict[str, Any]:
    session = get_browser_session(browser_session_id)
    if session["lease_owner"] != from_owner.upper():
        raise PermissionError(f"LEASE_OWNED_BY:{session['lease_owner']}")
    with transaction() as conn:
        conn.execute("UPDATE browser_sessions SET lease_owner=?,updated_at=? WHERE browser_session_id=?", (to_owner.upper(), now_iso(), browser_session_id))
    return get_browser_session(browser_session_id)


def record_event(browser_session_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = get_browser_session(browser_session_id)
    url = str(payload.get("url") or payload.get("page_url") or "")
    host = urlparse(url).hostname
    allowed = session.get("allowed_domains") or []
    if host and allowed and host not in allowed:
        raise PermissionError(f"BROWSER_EVENT_DOMAIN_NOT_ALLOWED:{host}")
    sensitive = bool(payload.get("sensitive"))
    value_repr = str(payload.get("value_repr") or "")
    if sensitive:
        value_repr = "<SECRET_INPUT>"
    # Never persist the raw value. A browser event can arrive with several
    # aliases (value/value_repr/text/password/token), so filtering one field is
    # not sufficient. Redact the whole event and force an explicit placeholder
    # for interactions marked sensitive by the controlled-browser extension.
    safe_payload = redact({
        k: v
        for k, v in payload.items()
        if k not in {"value", "password", "passwd", "pwd", "token", "authorization", "cookie", "otp", "mfa"}
    })
    if sensitive:
        safe_payload["value_repr"] = "<SECRET_INPUT>"
    event_id = new_id("BEV")
    with transaction() as conn:
        conn.execute(
            "INSERT INTO browser_events(browser_event_id,browser_session_id,event_type,page_url,selector,semantic_name,value_repr,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (event_id, browser_session_id, event_type, url, payload.get("selector"), payload.get("semantic_name"), value_repr, jdump(safe_payload), now_iso()),
        )
    return {"browser_event_id": event_id, "browser_session_id": browser_session_id, "value_repr": value_repr}


def close_browser_session(browser_session_id: str) -> dict[str, Any]:
    with transaction() as conn:
        conn.execute("UPDATE browser_sessions SET status='CLOSED',closed_at=?,updated_at=? WHERE browser_session_id=?", (now_iso(), now_iso(), browser_session_id))
    return get_browser_session(browser_session_id)


def trace(browser_session_id: str) -> list[dict[str, Any]]:
    rows = all_rows("SELECT * FROM browser_events WHERE browser_session_id=? ORDER BY created_at", (browser_session_id,))
    for row in rows:
        row["payload"] = jload(row.pop("payload_json"), {})
    return rows
