"""G1/G2 product-path test across independent CLI processes.

Uses the production DirectoryScopedOpenCodeSessionProvider against a tiny local
contract stub. The stub is not claimed to be bank OpenCode 1.18.3; it proves
that product_entry -> real HTTP provider -> R1 Event Stream works across
process boundaries. Bank payload compatibility remains field validation.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = WORKSPACE_ROOT / "ai-test" / "runtime"


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def request(intake_id: str) -> dict[str, object]:
    return {
        "intake_id": intake_id,
        "operation": "CREATE",
        "scope": {"mode": "EXPLICIT_SET", "project_id": "PFC", "version": "SUBPROCESS-V", "requirements": ["REQ-1"]},
        "goal": {"title": "Subprocess product path", "intent": "prove durable autonomous orchestration", "constraints": []},
        "source": {
            "kind": "USER", "source_ref": f"subprocess:{intake_id}",
            "source_digest": canonical_sha({"intake_id": intake_id}),
            "observed_at": "2026-09-01T10:00:00Z", "valid_until": None, "source_precedence": 1,
        },
        "actor": {"type": "USER", "id": "product-path-test"},
        "resolution": {
            "resolution_id": f"resolution:{intake_id}", "request_digest": canonical_sha({"resolution": intake_id}),
            "snapshot_id": f"snapshot:{intake_id}", "fact_set_digest": canonical_sha({"facts": []}),
            "status": "RESOLVED", "reason_code": None, "source_refs": [f"subprocess:{intake_id}"],
            "valid_until": "2026-09-02T10:00:00Z",
        },
    }


def proposal() -> dict[str, object]:
    return {
        "objective": "prove serial product orchestration",
        "tasks": [
            {"task_key": "one", "intent": "first governed unit", "acceptance_criteria": []},
            {"task_key": "two", "intent": "second governed unit", "acceptance_criteria": []},
        ],
        "dependencies": [{"from": "one", "to": "two"}],
    }


class OpenCodeContractStub(BaseHTTPRequestHandler):
    sessions: dict[str, dict[str, object]] = {}
    requests: list[dict[str, object]] = []
    counter = 0

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _record(self) -> None:
        parsed = urlparse(self.path)
        self.__class__.requests.append({
            "method": self.command,
            "path": parsed.path,
            "query": parse_qs(parsed.query),
            "directory_header": self.headers.get("x-opencode-directory"),
        })

    def _json(self, code: int, value: object) -> None:
        data = json.dumps(value).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self._record()
        parsed = urlparse(self.path)
        if parsed.path == "/global/health":
            self._json(200, {"healthy": True})
            return
        if parsed.path == "/session":
            self._json(200, list(self.__class__.sessions.values()))
            return
        if parsed.path.startswith("/session/"):
            sid = parsed.path.split("/")[-1]
            if sid not in self.__class__.sessions:
                self._json(404, {"error": "not found"})
                return
            value = dict(self.__class__.sessions[sid])
            value.update({"messageCount": 61, "compactionCount": 0, "contextUtilization": 0.5, "healthy": True})
            self._json(200, value)
            return
        self._json(404, {"error": "unknown"})

    def do_POST(self) -> None:
        self._record()
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if parsed.path == "/session":
            self.__class__.counter += 1
            sid = f"contract-session-{self.__class__.counter}"
            self.__class__.sessions[sid] = {"id": sid, "title": body.get("title")}
            self._json(200, {"id": sid, "title": body.get("title")})
            return
        if parsed.path.startswith("/session/") and parsed.path.endswith("/message"):
            sid = parsed.path.split("/")[-2]
            if sid not in self.__class__.sessions:
                self._json(404, {"error": "not found"})
                return
            self._json(200, {"accepted": True, "sessionID": sid})
            return
        self._json(404, {"error": "unknown"})

    def do_DELETE(self) -> None:
        self._record()
        parsed = urlparse(self.path)
        if parsed.path.startswith("/session/"):
            sid = parsed.path.split("/")[-1]
            self.__class__.sessions.pop(sid, None)
            self._json(200, True)
            return
        self._json(404, {"error": "unknown"})


def run(env: dict[str, str], role: str, action: str, payload: dict[str, object]) -> dict[str, object]:
    proc = subprocess.run(
        [sys.executable, "-m", "aitest_runtime.product_entry", "orchestrate", "--role", role, "--action", action, "--payload", json.dumps(payload, ensure_ascii=False)],
        cwd=str(Path(env["AITEST_WORKSPACE_ROOT"])), env=env, capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{role}/{action} failed: {proc.stdout} {proc.stderr}")
    value = json.loads(proc.stdout)
    if value.get("truth_source") != "R1_EVENT_STREAM":
        raise RuntimeError(f"non-canonical result: {value}")
    return value


def main() -> int:
    checks: dict[str, bool] = {}
    OpenCodeContractStub.sessions = {}
    OpenCodeContractStub.requests = []
    OpenCodeContractStub.counter = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), OpenCodeContractStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="pfc-product-path-") as td:
            root = Path(td)
            spine = root / "durable/state/runtime-spine.db"
            spine.parent.mkdir(parents=True)
            env = dict(os.environ)
            env.update({
                "AITEST_WORKSPACE_ROOT": str(root),
                "AITEST_RUNTIME_SPINE_DB": str(spine),
                "AITEST_OPENCODE_ENDPOINT": f"http://127.0.0.1:{server.server_port}",
                "PYTHONPATH": str(RUNTIME_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""),
            })

            started = run(env, "DIRECTOR", "start_test", {"request": request("sub-a")})
            mission_id = str(started["intake"]["intake"]["mission_id"])
            checks["independent_process_start_opens_real_provider_planner_session"] = started["status"] == "PLANNING" and str(started["planner_session"]["external_session"]["session_id"]).startswith("contract-session-")

            resumed = run(env, "DIRECTOR", "start_test", {"request": request("sub-b")})
            checks["independent_process_same_scope_resumes"] = resumed["intake"]["status"] == "RESUMED" and resumed["intake"]["intake"]["mission_id"] == mission_id

            planned = run(env, "PLANNER", "propose_plan", {"mission_id": mission_id, "proposal": proposal()})
            first = planned["next"]
            checks["independent_process_plan_auto_dispatches"] = planned["autonomous_handoff"] == "SCHEDULER" and first["status"] == "DISPATCHED"

            first_done = run(env, "EXECUTOR", "report_task_outcome", {
                "mission_id": mission_id, "task_id": first["task_id"], "attempt_id": first["attempt"]["attempt_id"],
                "session_id": first["external_session"]["session_id"], "outcome": "SUCCEEDED", "summary": "first done",
            })
            second = first_done["next"]
            checks["independent_process_outcome_auto_dispatches_successor"] = second["status"] == "DISPATCHED" and second["task_id"] != first["task_id"]

            tick = run(env, "CONTROL", "control_tick", {})
            rotated = [
                item["result"] for item in tick.get("supervision", [])
                if item.get("task_id") == second["task_id"] and item.get("result", {}).get("status") == "ROTATED"
            ]
            observed = rotated[0]
            rotation = observed["rotation"]
            checks["production_provider_control_loop_observation_drives_rotation_without_agent_call"] = (
                observed["status"] == "ROTATED" and rotation["root_attempt_id"] == second["attempt"]["root_attempt_id"]
            )

            second_done = run(env, "EXECUTOR", "report_task_outcome", {
                "mission_id": mission_id, "task_id": second["task_id"], "attempt_id": rotation["successor_attempt_id"],
                "session_id": rotation["successor_session_id"], "outcome": "SUCCEEDED", "summary": "second done",
            })
            checks["independent_process_loop_completes"] = second_done["next"]["status"] == "PLAN_COMPLETE"
            continued = run(env, "DIRECTOR", "continue_test", {"mission_id": mission_id})
            checks["new_process_continue_reads_event_stream"] = continued["status"] == "PLAN_COMPLETE" and spine.is_file()

            requests = OpenCodeContractStub.requests
            checks["provider_sends_explicit_directory_binding"] = bool(requests) and all(item["directory_header"] == str(root.resolve()) for item in requests)
            checks["provider_sends_directory_query_for_session_calls"] = all(
                item["query"].get("directory") == [str(root.resolve())]
                for item in requests if str(item["path"]).startswith("/session")
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    payload = {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "http_requests": len(OpenCodeContractStub.requests)}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
