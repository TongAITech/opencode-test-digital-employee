"""G2.1 continuous background Control Loop product-path check.

This runs product_entry in independent processes against the real HTTP provider
boundary, then starts aitest_runtime.control_loop as a separate process. No
Agent/Scheduler observation action is called. The external contract server is a
construction stub, not a claim about bank OpenCode 1.18.3 payload reality.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = WORKSPACE_ROOT / "ai-test" / "runtime"


def sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def request() -> dict[str, object]:
    return {
        "intake_id": "g21-background",
        "operation": "CREATE",
        "scope": {"mode": "EXPLICIT_SET", "project_id": "PFC", "version": "G21-BG", "requirements": ["REQ-BG"]},
        "goal": {"title": "background supervisor", "intent": "prove autonomous rotation", "constraints": []},
        "source": {"kind": "USER", "source_ref": "g21:bg", "source_digest": sha({"source": "bg"}),
                   "observed_at": "2026-09-01T10:00:00Z", "valid_until": None, "source_precedence": 1},
        "actor": {"type": "USER", "id": "background-test"},
        "resolution": {"resolution_id": "resolution:bg", "request_digest": sha({"resolution": "bg"}),
                       "snapshot_id": "snapshot:bg", "fact_set_digest": sha({"facts": []}), "status": "RESOLVED",
                       "reason_code": None, "source_refs": ["g21:bg"], "valid_until": "2026-09-02T10:00:00Z"},
    }


def proposal() -> dict[str, object]:
    return {
        "objective": "one worker for background rotation",
        "tasks": [{"task_key": "long-worker", "intent": "long governed worker", "acceptance_criteria": []}],
        "dependencies": [],
    }


class Stub(BaseHTTPRequestHandler):
    sessions: dict[str, dict[str, object]] = {}
    requests: list[dict[str, object]] = []
    counter = 0

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _record(self) -> None:
        parsed = urlparse(self.path)
        self.__class__.requests.append({
            "method": self.command, "path": parsed.path, "query": parse_qs(parsed.query),
            "directory": self.headers.get("x-opencode-directory"),
        })

    def _json(self, code: int, value: object) -> None:
        data = json.dumps(value).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self) -> None:
        self._record(); parsed = urlparse(self.path)
        if parsed.path == "/global/health": self._json(200, {"healthy": True}); return
        if parsed.path == "/session": self._json(200, list(self.__class__.sessions.values())); return
        if parsed.path.startswith("/session/"):
            sid = parsed.path.split("/")[-1]; value = self.__class__.sessions.get(sid)
            if value is None: self._json(404, {"error": "not found"}); return
            self._json(200, value); return
        self._json(404, {"error": "unknown"})

    def do_POST(self) -> None:
        self._record(); parsed = urlparse(self.path); n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n) or b"{}")
        if parsed.path == "/session":
            self.__class__.counter += 1; sid = f"bg-session-{self.__class__.counter}"
            self.__class__.sessions[sid] = {"id": sid, "title": body.get("title"), "messageCount": 1, "compactionCount": 0, "healthy": True}
            self._json(200, self.__class__.sessions[sid]); return
        if parsed.path.startswith("/session/") and parsed.path.endswith("/message"):
            sid = parsed.path.split("/")[-2]
            if sid not in self.__class__.sessions: self._json(404, {"error": "not found"}); return
            self._json(200, {"accepted": True, "sessionID": sid}); return
        self._json(404, {"error": "unknown"})

    def do_DELETE(self) -> None:
        self._record(); sid = urlparse(self.path).path.split("/")[-1]; self.__class__.sessions.pop(sid, None); self._json(200, True)


def run(env: dict[str, str], role: str, action: str, payload: dict[str, object]) -> dict[str, object]:
    proc = subprocess.run(
        [sys.executable, "-m", "aitest_runtime.product_entry", "orchestrate", "--role", role, "--action", action, "--payload", json.dumps(payload)],
        cwd=env["AITEST_WORKSPACE_ROOT"], env=env, capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout + " " + proc.stderr)
    return json.loads(proc.stdout)


def main() -> int:
    checks: dict[str, bool] = {}
    Stub.sessions = {}; Stub.requests = []; Stub.counter = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    control: subprocess.Popen[str] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="pfc-g21-bg-") as td:
            root = Path(td); spine = root / "durable/state/runtime-spine.db"; spine.parent.mkdir(parents=True)
            env = dict(os.environ)
            env.update({
                "AITEST_WORKSPACE_ROOT": str(root), "AITEST_RUNTIME_SPINE_DB": str(spine),
                "AITEST_OPENCODE_ENDPOINT": f"http://127.0.0.1:{server.server_port}",
                "PYTHONPATH": str(RUNTIME_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""),
            })
            started = run(env, "DIRECTOR", "start_test", {"request": request()}); mission_id = str(started["intake"]["intake"]["mission_id"])
            planned = run(env, "PLANNER", "propose_plan", {"mission_id": mission_id, "proposal": proposal()}); first = planned["next"]
            predecessor = str(first["external_session"]["session_id"]); root_attempt = str(first["attempt"]["root_attempt_id"])
            Stub.sessions[predecessor]["messageCount"] = 61

            control = subprocess.Popen(
                [sys.executable, "-m", "aitest_runtime.control_loop", "--workspace-root", str(root), "--interval", "0.1"],
                cwd=str(root), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            rotated_status: dict[str, object] | None = None
            deadline = time.time() + 5
            while time.time() < deadline:
                value = run(env, "DIRECTOR", "status", {"mission_id": mission_id})
                attempts = value.get("execution", {}).get("attempts", [])  # type: ignore[union-attr]
                if isinstance(attempts, list) and len(attempts) >= 2:
                    rotated_status = value
                    break
                time.sleep(0.1)
            checks["background_process_rotates_without_agent_or_scheduler_observe"] = rotated_status is not None
            if rotated_status is not None:
                attempts = rotated_status["execution"]["attempts"]  # type: ignore[index]
                latest = attempts[-1]
                checks["background_rotation_preserves_root_attempt"] = latest["root_attempt_id"] == root_attempt and latest["runtime_session_id"] != predecessor
                sessions = rotated_status["core"]["sessions"]  # type: ignore[index]
                checks["background_rotation_durable_predecessor_closed_successor_open"] = sessions[predecessor]["status"] == "CLOSED" and sessions[latest["runtime_session_id"]]["status"] == "OPEN"
            else:
                checks["background_rotation_preserves_root_attempt"] = False
                checks["background_rotation_durable_predecessor_closed_successor_open"] = False

            # Kill/restart the Control Loop itself. No durable Mission/Session
            # reconstruction is supplied to it beyond R1 + provider facts.
            assert control is not None
            control.terminate(); control.wait(timeout=5); control = None
            before = run(env, "DIRECTOR", "status", {"mission_id": mission_id})
            once = subprocess.run(
                [sys.executable, "-m", "aitest_runtime.control_loop", "--workspace-root", str(root), "--once"],
                cwd=str(root), env=env, capture_output=True, text=True, timeout=30,
            )
            after = run(env, "DIRECTOR", "status", {"mission_id": mission_id})
            checks["control_loop_restart_rebuilds_from_r1_without_state_loss"] = once.returncode == 0 and before["head_seq"] <= after["head_seq"] and after["mission_id"] == mission_id
            checks["background_provider_calls_are_directory_scoped"] = bool(Stub.requests) and all(
                item["directory"] == str(root.resolve()) for item in Stub.requests if str(item["path"]).startswith("/session")
            )
    finally:
        if control is not None:
            control.terminate()
            try: control.wait(timeout=3)
            except subprocess.TimeoutExpired: control.kill()
        server.shutdown(); server.server_close(); thread.join(timeout=2)

    payload = {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "http_requests": len(Stub.requests)}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
