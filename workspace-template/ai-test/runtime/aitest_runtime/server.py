from __future__ import annotations

import json
import mimetypes
import os
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import bootstrap, browser, defects, human, mission, reporting, scheduler, teaching
from .common import AI_ROOT, VERSION, redact
from .project import list_connectors, list_projects
from .r1_5 import ControlPlane, launch_runtime, validate_startup
from .storage import all_rows, initialize, jload, one

WEB_ROOT = AI_ROOT / "control-plane" / "web"


def _json_bytes(value: Any) -> bytes:
    return json.dumps(redact(value), ensure_ascii=False, indent=2).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "AITestControlPlane/1.11"

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("AITEST_QUIET") != "1":
            super().log_message(fmt, *args)

    def _send_json(self, value: Any, status: int = 200) -> None:
        data = _json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:8765")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _error(self, exc: Exception) -> None:
        self._send_json({"ok": False, "error": type(exc).__name__, "message": str(exc)}, 400)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:8765")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            plane = getattr(self.server, "r1_5_control_plane", None)
            r1_5_only = bool(getattr(self.server, "r1_5_only", False))
            if path in {"/api/health", "/api/r1-5/health"} and plane is not None:
                self._send_json(plane.health((qs.get("mission_id") or [None])[0]).to_dict())
                return
            if path.startswith("/api/r1-5/missions/") and path.endswith("/projection") and plane is not None:
                mission_id = path.split("/")[4]
                self._send_json(plane.projection(mission_id).to_dict())
                return
            if path.startswith("/api/r1-5/") or (r1_5_only and path.startswith("/api/")):
                self._send_json({"ok": False, "error": "NOT_FOUND"}, 404)
                return
            if path == "/api/health":
                self._send_json({"ok": True, "service": "AI Test Control Plane", "version": VERSION})
                return
            if path == "/api/projects":
                self._send_json({"projects": list_projects()})
                return
            if path == "/api/start":
                self._send_json(bootstrap.start((qs.get("project_id") or [None])[0]))
                return
            if path == "/api/report":
                project_id = (qs.get("project_id") or [None])[0]
                if not project_id:
                    raise ValueError("project_id is required")
                self._send_json(reporting.project_report(project_id))
                return
            if path == "/api/missions":
                project_id = (qs.get("project_id") or [None])[0]
                self._send_json({"missions": mission.list_missions(project_id) if project_id else all_rows("SELECT * FROM missions ORDER BY updated_at DESC")})
                return
            if path.startswith("/api/missions/"):
                mid = path.split("/")[3]
                self._send_json(mission.get_mission(mid))
                return
            if path == "/api/human-tasks":
                project_id = (qs.get("project_id") or [None])[0]
                self._send_json({"human_tasks": human.list_tasks(project_id) if project_id else all_rows("SELECT * FROM human_tasks ORDER BY created_at DESC")})
                return
            if path == "/api/defects":
                project_id = (qs.get("project_id") or [None])[0]
                self._send_json({"defects": defects.list_defects(project_id) if project_id else all_rows("SELECT * FROM defects ORDER BY updated_at DESC")})
                return
            if path == "/api/campaigns":
                project_id = (qs.get("project_id") or [None])[0]
                rows = all_rows("SELECT * FROM campaigns WHERE project_id=? ORDER BY updated_at DESC", (project_id,)) if project_id else all_rows("SELECT * FROM campaigns ORDER BY updated_at DESC")
                self._send_json({"campaigns": rows})
                return
            if path == "/api/connectors":
                project_id = (qs.get("project_id") or [None])[0]
                self._send_json({"connectors": list_connectors(project_id) if project_id else all_rows("SELECT * FROM connectors ORDER BY connector_id")})
                return
            if path == "/api/browser/active":
                row = one("SELECT * FROM browser_sessions WHERE status IN ('CREATED','READY_TO_LAUNCH','OPEN') ORDER BY updated_at DESC LIMIT 1")
                self._send_json({"browser_session": row})
                return
            if path.startswith("/api/browser/") and path.endswith("/trace"):
                sid = path.split("/")[3]
                self._send_json({"events": browser.trace(sid)})
                return
            self._static(path)
        except Exception as exc:
            self._error(exc)

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            body = self._body()
            plane = getattr(self.server, "r1_5_control_plane", None)
            r1_5_only = bool(getattr(self.server, "r1_5_only", False))
            if path == "/api/r1-5/commands" and plane is not None:
                self._send_json(plane.submit_command(body.get("command") or body).to_dict())
                return
            if path.startswith("/api/r1-5/") or (r1_5_only and path.startswith("/api/")):
                self._send_json({"ok": False, "error": "NOT_FOUND"}, 404)
                return
            if path.startswith("/api/missions/") and path.endswith("/continue"):
                mid = path.split("/")[3]
                self._send_json(mission.continue_mission(mid, body.get("actor") or "human"))
                return
            if path.startswith("/api/human-tasks/") and path.endswith("/claim"):
                tid = path.split("/")[3]
                self._send_json(human.claim_task(tid, body.get("user_id") or "local-user"))
                return
            if path.startswith("/api/human-tasks/") and path.endswith("/complete"):
                tid = path.split("/")[3]
                self._send_json(human.complete_task(tid, body.get("user_id") or "local-user", comment=body.get("comment") or "", evidence=body.get("evidence") or []))
                return
            if path.startswith("/api/human-tasks/") and path.endswith("/open-browser"):
                tid = path.split("/")[3]
                task = human.get_task(tid)
                m = mission.get_mission(task["mission_id"], include_steps=False)
                meta = task.get("metadata") or {}
                mission_meta = m.get("metadata") or {}
                start_url = body.get("start_url") or meta.get("start_url")
                allowed_domains = body.get("allowed_domains") or meta.get("allowed_domains") or []
                mode = body.get("mode") or ("TEACH" if task.get("task_type") in {"SHOWCASE", "DEMONSTRATION"} else "HUMAN_ASSISTED")
                self._send_json(browser.launch_browser(
                    m["project_id"], mode,
                    browser_session_id=task.get("browser_session_id"),
                    mission_id=task["mission_id"], human_task_id=tid,
                    environment_id=meta.get("environment_id") or mission_meta.get("environment_id"),
                    auth_profile_id=meta.get("auth_profile_id"), start_url=start_url,
                    allowed_domains=allowed_domains, browser_executable=body.get("browser_executable"),
                    dry_run=bool(body.get("dry_run", False)),
                ))
                return
            if path == "/api/browser/sessions":
                self._send_json(browser.launch_browser(**body))
                return
            if path.startswith("/api/browser/") and path.endswith("/lease"):
                sid = path.split("/")[3]
                self._send_json(browser.transfer_lease(sid, body["from_owner"], body["to_owner"]))
                return
            if path == "/api/browser/events":
                sid = body.pop("browser_session_id")
                event_type = body.pop("event_type", "EVENT")
                self._send_json(browser.record_event(sid, event_type, body))
                return
            if path == "/api/teaching/events":
                event = teaching.create_event(body["project_id"], body["event_type"], body["subject"], body.get("payload") or {}, body.get("teacher") or "local-user")
                self._send_json(event)
                return
            self._send_json({"ok": False, "error": "NOT_FOUND"}, 404)
        except Exception as exc:
            self._error(exc)

    def _static(self, path: str) -> None:
        rel = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (WEB_ROOT / rel).resolve()
        if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
            self._send_json({"error": "PATH_NOT_ALLOWED"}, 403)
            return
        if not target.exists() or not target.is_file():
            target = WEB_ROOT / "index.html"
        data = target.read_bytes()
        mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    initialize()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"AI Test Control Plane: http://{host}:{port}")
    server.serve_forever()


def serve_r1_5(
    workspace_root: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    package_root: str | Path | None = None,
    configuration_path: str | Path | None = None,
) -> None:
    startup = validate_startup(workspace_root, package_root=package_root, configuration_path=configuration_path)
    configured_host = str(startup.configuration.security["bind_host"])
    if host != configured_host:
        raise ValueError(f"host must match validated loopback configuration: {configured_host}")
    plane = ControlPlane(launch_runtime(startup))
    server = ThreadingHTTPServer((host, port), Handler)
    server.r1_5_control_plane = plane  # type: ignore[attr-defined]
    server.r1_5_only = True  # type: ignore[attr-defined]
    print(f"AI Test R1.5 Control Plane Foundation: http://{host}:{port}")
    server.serve_forever()
