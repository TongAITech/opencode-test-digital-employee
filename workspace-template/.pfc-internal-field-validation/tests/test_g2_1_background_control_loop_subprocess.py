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

_TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TEST_DIR))
from host_interaction_fixture import host_turn

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = WORKSPACE_ROOT / "ai-test" / "runtime"
sys.path.insert(0, str(RUNTIME_ROOT))


def sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def host_start_turn(scope: dict[str, object], *, session: str = "fixture-host",
                    message: str = "fixture-user") -> tuple[dict[str, dict[str, object]], dict[str, str], dict[str, object]]:
    """Current C1 Host ToolContext for a real DIRECTOR/start_test call."""
    messages, env, payload = host_turn(scope, session=session, message=message)
    assistant_id = env["AITEST_HOST_MESSAGE_ID"]
    session_id = env["AITEST_HOST_SESSION_ID"]
    call_id = message + "-start-call"
    assistant_path = f"/session/{session_id}/message/{assistant_id}"
    assistant = messages[assistant_path]
    info = assistant.get("info")
    if not isinstance(info, dict):
        raise AssertionError("HOST_ASSISTANT_INFO_REQUIRED")
    info["agent"] = "aitest-director"
    assistant["parts"] = [{
        "type": "tool",
        "callID": call_id,
        "tool": "aitest_director",
        "sessionID": session_id,
        "messageID": assistant_id,
        "state": {
            "status": "running",
            "input": {"action": "start_test", "payload": payload},
        },
    }]
    env["AITEST_HOST_CALL_ID"] = call_id
    return messages, env, payload


def bind_host_tool(env: dict[str, str], *, session_id: str, agent: str, tool: str,
                   action: str, payload: dict[str, object], label: str) -> None:
    """Bind one exact current Host tool call to the role-owned Session."""
    message_id = label + "-assistant"
    call_id = label + "-call"
    Stub.host_messages[f"/session/{session_id}/message/{message_id}"] = {
        "info": {
            "sessionID": session_id,
            "id": message_id,
            "role": "assistant",
            "agent": agent,
        },
        "parts": [{
            "type": "tool",
            "callID": call_id,
            "tool": tool,
            "sessionID": session_id,
            "messageID": message_id,
            "state": {
                "status": "running",
                "input": {"action": action, "payload": payload},
            },
        }],
    }
    env.update({
        "AITEST_HOST_SESSION_ID": session_id,
        "AITEST_HOST_MESSAGE_ID": message_id,
        "AITEST_HOST_CALL_ID": call_id,
    })


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
    host_messages: dict[str, dict[str, object]] = {}
    sessions: dict[str, dict[str, object]] = {}
    messages: dict[str, list[dict[str, object]]] = {}
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
        if parsed.path in self.__class__.host_messages:self._json(200,self.__class__.host_messages[parsed.path]);return
        if parsed.path == "/global/health": self._json(200, {"healthy": True}); return
        if parsed.path == "/provider":
            # OpenCode 1.18.3 provider catalog shape consumed by the real
            # DirectoryScopedOpenCodeSessionProvider. Successor runtime prompts
            # carry this model identity so supervision uses the advertised 128K
            # capacity instead of the deliberately conservative 32K blind fallback.
            self._json(200, {
                "all": [{
                    "id": "fixture-provider",
                    "models": {
                        "fixture-128k": {
                            "limit": {"context": 131072, "output": 8192}
                        }
                    },
                }]
            }); return
        if parsed.path == "/session": self._json(200, list(self.__class__.sessions.values())); return
        if parsed.path == "/session/status":
            # OpenCode 1.18.3 omits idle Sessions from the status map.
            self._json(200, {}); return
        if parsed.path.endswith("/message"):
            sid = parsed.path.split("/")[-2]
            self._json(200, self.__class__.messages.get(sid, [])); return
        if parsed.path.startswith("/session/"):
            sid = parsed.path.split("/")[-1]; value = self.__class__.sessions.get(sid)
            if value is None: self._json(404, {"error": "not found"}); return
            self._json(200, value); return
        self._json(404, {"error": "unknown"})

    def do_POST(self) -> None:
        self._record(); parsed = urlparse(self.path); n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n) or b"{}")
        if parsed.path == "/session":
            self.__class__.counter += 1; sid = f"bg-session-{self.__class__.counter}"
            self.__class__.sessions[sid] = {"id": sid, "title": body.get("title"), "healthy": True}
            self.__class__.messages[sid] = []
            self._json(200, self.__class__.sessions[sid]); return
        if parsed.path.startswith("/session/") and parsed.path.endswith("/abort"):
            self._json(200, True); return
        if parsed.path.startswith("/session/") and parsed.path.endswith("/prompt_async"):
            sid = parsed.path.split("/")[-2]
            if sid not in self.__class__.sessions: self._json(404, {"error": "not found"}); return
            self.__class__.messages[sid].append({
                "info": {
                    "id": f"msg-{len(self.__class__.messages[sid])}",
                    "sessionID": sid,
                    "role": "user",
                    "providerID": "fixture-provider",
                    "modelID": "fixture-128k",
                },
                "parts": body["parts"],
            })
            self._json(200, {"accepted": True, "sessionID": sid}); return
        self._json(404, {"error": "unknown"})

    def do_DELETE(self) -> None:
        self._record(); sid = urlparse(self.path).path.split("/")[-1]; self.__class__.sessions.pop(sid, None); self._json(200, True)


def drain_background_output(stream: object) -> None:
    if stream is None:
        return
    for _line in stream:
        pass


_MODULE_BOOTSTRAP = (
    "import runpy,sys;"
    "root=sys.argv.pop(1);module=sys.argv.pop(1);"
    "sys.path.insert(0,root);sys.argv[0]=module;"
    "runpy.run_module(module,run_name='__main__')"
)


def module_command(module: str, *args: str) -> list[str]:
    # The qualified Windows payload uses an embedded Python distribution whose
    # path file can ignore PYTHONPATH.  Inject current source inside the child
    # interpreter itself so subprocess evidence is about this Git HEAD.
    return [sys.executable, "-c", _MODULE_BOOTSTRAP, str(RUNTIME_ROOT), module, *args]


def run(env: dict[str, str], role: str, action: str, payload: dict[str, object]) -> dict[str, object]:
    proc = subprocess.run(
        module_command("aitest_runtime.product_entry", "orchestrate", "--role", role, "--action", action, "--payload", json.dumps(payload)),
        cwd=env["AITEST_WORKSPACE_ROOT"], env=env, capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout + " " + proc.stderr)
    return json.loads(proc.stdout)


def main() -> int:
    checks: dict[str, bool] = {}
    diagnostics: dict[str, object] = {}
    Stub.sessions = {}; Stub.messages = {}; Stub.requests = []; Stub.counter = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    control: subprocess.Popen[str] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="pfc-g21-bg-") as td:
            root = Path(td); spine = root / "durable/state/runtime-spine.db"; spine.parent.mkdir(parents=True)
            env = dict(os.environ)
            heartbeat_path = root / "durable" / "state" / "control-loop-heartbeat.json"
            env.update({
                "AITEST_WORKSPACE_ROOT": str(root), "AITEST_RUNTIME_SPINE_DB": str(spine),
                "AITEST_OPENCODE_ENDPOINT": f"http://127.0.0.1:{server.server_port}",
                "AITEST_CONTROL_LOOP_HEARTBEAT_PATH": str(heartbeat_path),
                "PYTHONPATH": str(RUNTIME_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""),
            })
            # Product startup creates the durable Primary before any Director
            # tool call. Reuse the exact trusted launcher composition here rather
            # than inventing a host Session inside the test fixture.
            from aitest_runtime.autonomous_orchestration import DirectoryScopedOpenCodeSessionProvider
            from aitest_runtime.canonical_runtime import create_canonical_runtime
            from aitest_runtime.primary_sessions import PrimarySessionOwner
            launcher_runtime = create_canonical_runtime(root, db_path=spine)
            launcher_provider = DirectoryScopedOpenCodeSessionProvider(
                root, base_url=env["AITEST_OPENCODE_ENDPOINT"]
            )
            primary_binding = PrimarySessionOwner(
                launcher_runtime, root, launcher_provider
            ).ensure_current()
            primary_host_session = str(primary_binding["session_id"])

            Stub.host_messages,host_env,payload=host_start_turn(
                request()['scope'], session=primary_host_session, message='background-start'
            )
            env.update(host_env)
            started = run(env, "DIRECTOR", "start_test", payload)
            operations = started.get("operations")
            if (
                started.get("status") != "INTERACTION_PROCESSED"
                or not isinstance(operations, list)
                or len(operations) != 1
                or operations[0].get("status") != "DISPATCHED"
                or operations[0].get("effect") != "TEST_DISPATCH"
                or not isinstance(operations[0].get("subject"), dict)
                or operations[0]["subject"].get("subject_kind") != "MISSION"
                or not isinstance(operations[0].get("result"), dict)
                or operations[0]["result"].get("status") != "PLANNER_SESSION_OPEN"
            ):
                raise AssertionError(
                    "BACKGROUND_START_RESULT_INVALID:" + json.dumps(started, ensure_ascii=False, sort_keys=True)
                )
            mission_id = str(operations[0]["subject"]["subject_id"])
            if operations[0]["result"].get("mission_id") != mission_id:
                raise AssertionError("BACKGROUND_START_MISSION_IDENTITY_MISMATCH")

            # The normal interaction wrapper intentionally does not expose the
            # external Planner Session id. Resolve it from canonical Mission
            # status instead of depending on an internal start-test return shape.
            startup_status_payload = {"mission_id": mission_id}
            bind_host_tool(
                env, session_id=primary_host_session, agent="aitest-director", tool="aitest_director",
                action="status", payload=startup_status_payload, label="background-start-status",
            )
            startup_status = run(env, "DIRECTOR", "status", startup_status_payload)
            core_sessions = startup_status.get("core", {}).get("sessions", {})
            planner_sessions = [
                sid for sid, value in core_sessions.items()
                if isinstance(value, dict)
                and value.get("status") == "OPEN"
                and isinstance(value.get("attributes"), dict)
                and value["attributes"].get("phase") == "PLANNING"
            ] if isinstance(core_sessions, dict) else []
            if len(planner_sessions) != 1:
                raise AssertionError(
                    "BACKGROUND_PLANNER_SESSION_NOT_UNIQUE:"
                    + json.dumps(startup_status, ensure_ascii=False, sort_keys=True)
                )
            planner_session_id = str(planner_sessions[0])
            plan_payload = {"mission_id": mission_id, "proposal": proposal()}
            bind_host_tool(
                env, session_id=planner_session_id, agent="aitest-planner", tool="aitest_planner",
                action="propose_plan", payload=plan_payload, label="background-plan",
            )
            planned = run(env, "PLANNER", "propose_plan", plan_payload); first = planned["next"]
            predecessor = str(first["external_session"]["session_id"]); root_attempt = str(first["attempt"]["root_attempt_id"])
            Stub.messages[predecessor] = [
                {"info": {"id": f"msg-{index}", "sessionID": predecessor, "role": "assistant"},
                 "parts": [{"type": "text", "text": "bounded governed work"}]}
                for index in range(60)
            ]

            control = subprocess.Popen(
                module_command("aitest_runtime.control_loop", "--workspace-root", str(root), "--interval", "0.1"),
                cwd=str(root), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            threading.Thread(
                target=drain_background_output, args=(control.stdout,), daemon=True
            ).start()
            rotated_status: dict[str, object] | None = None
            deadline = time.time() + 30
            status_call = 0
            while time.time() < deadline:
                status_call += 1
                status_payload = {"mission_id": mission_id}
                bind_host_tool(
                    env, session_id=primary_host_session, agent="aitest-director", tool="aitest_director",
                    action="status", payload=status_payload, label=f"background-status-{status_call}",
                )
                value = run(env, "DIRECTOR", "status", status_payload)
                attempts = value.get("execution", {}).get("attempts", [])  # type: ignore[union-attr]
                rotations = value.get("session_control", {}).get("rotations", [])
                if (isinstance(attempts, list) and len(attempts) >= 2
                        and rotations and rotations[-1].get("status") == "COMPLETED"):
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
                checkpoint = rotated_status["session_control"]["rotations"][-1]["checkpoint"]
                context = json.loads(Stub.messages[latest["runtime_session_id"]][-1]["parts"][0]["text"].split("\n", 1)[1])
                checks["fallback_rotation_records_checkpoint_and_rehydrates_context_pack"] = (
                    checkpoint["root_attempt_id"] == root_attempt and checkpoint["mission_id"] == mission_id
                    and context["resume_checkpoint"] == checkpoint and bool(context["context_pack_reference"]["semantic_digest"])
                    and context["logical_agent_id"] == checkpoint["logical_agent_id"]
                )
                observation = next(x for x in rotated_status["session_control"]["observations"] if x["session_id"] == predecessor)
                checks["metadata_has_no_counts_but_message_api_is_durable_fallback"] = (
                    "messageCount" not in Stub.sessions.get(predecessor, {})
                    and observation["message_count"] == 60
                    and observation["provider_state"]["pressure"]["metrics_source"] == "OPENCODE_MESSAGE_API"
                )

                # Keep the independent Control Loop alive. No user "continue",
                # Agent observe call or Scheduler command is issued here. The
                # loop itself must drive successor AUTO_CONTINUE and, after the
                # same business cursor produces no progress, create a governed
                # Replanning Planner from durable R1 truth.
                successor_id = str(latest["runtime_session_id"])
                unattended_status: dict[str, object] | None = None
                deadline = time.time() + 12
                while time.time() < deadline:
                    status_call += 1
                    status_payload = {"mission_id": mission_id}
                    bind_host_tool(
                        env, session_id=primary_host_session, agent="aitest-director", tool="aitest_director",
                        action="status", payload=status_payload, label=f"background-status-{status_call}",
                    )
                    value = run(env, "DIRECTOR", "status", status_payload)
                    progress_records = value.get("session_control", {}).get("progress_records", [])  # type: ignore[union-attr]
                    active_replans = [
                        item for item in progress_records
                        if item.get("phase") == "REPLANNING" and item.get("replan_session_id")
                    ]
                    if active_replans:
                        unattended_status = value
                        break
                    time.sleep(0.1)

                checks["background_progress_does_not_require_user_continue"] = unattended_status is not None
                if unattended_status is None:
                    heartbeat = {}
                    try:
                        heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        heartbeat = {}
                    status_call += 1
                    status_payload = {"mission_id": mission_id}
                    bind_host_tool(
                        env, session_id=primary_host_session, agent="aitest-director", tool="aitest_director",
                        action="status", payload=status_payload, label=f"background-status-{status_call}",
                    )
                    stalled = run(env, "DIRECTOR", "status", status_payload)
                    attempts = stalled.get("execution", {}).get("attempts", [])
                    latest_attempt = attempts[-1] if isinstance(attempts, list) and attempts else None
                    diagnostics["unattended_timeout"] = {
                        "heartbeat": heartbeat,
                        "successor_session_id": successor_id,
                        "successor_message_count": len(Stub.messages.get(successor_id, [])),
                        "successor_messages": [
                            str((row.get("parts") or [{}])[0].get("text") or "")[:120]
                            for row in Stub.messages.get(successor_id, [])
                            if isinstance(row, dict)
                        ],
                        "latest_attempt": latest_attempt,
                        "context_dispatches": [
                            row for row in stalled.get("session_control", {}).get("context_dispatches", [])
                            if row.get("session_id") == successor_id
                        ],
                        "successor_observations": [
                            row for row in stalled.get("session_control", {}).get("observations", [])
                            if row.get("session_id") == successor_id
                        ],
                        "rotations": stalled.get("session_control", {}).get("rotations", []),
                    }
                if unattended_status is not None:
                    progress_records = unattended_status["session_control"]["progress_records"]  # type: ignore[index]
                    active_replan = next(
                        item for item in progress_records
                        if item.get("phase") == "REPLANNING" and item.get("replan_session_id")
                    )
                    replanner_id = str(active_replan["replan_session_id"])
                    checks["background_worker_auto_continue_precedes_replan"] = (
                        len(Stub.messages.get(successor_id, [])) >= 2
                    )
                    checks["background_no_progress_creates_governed_replanner"] = (
                        replanner_id in Stub.sessions
                        and len(Stub.messages.get(replanner_id, [])) >= 1
                        and str(active_replan.get("failure_signature") or "") != ""
                    )
                    checks["background_replan_remains_same_mission_truth"] = (
                        active_replan.get("business_cursor") is not None
                        and unattended_status.get("mission_id") == mission_id
                    )
                else:
                    checks["background_worker_auto_continue_precedes_replan"] = False
                    checks["background_no_progress_creates_governed_replanner"] = False
                    checks["background_replan_remains_same_mission_truth"] = False
            else:
                checks["background_rotation_preserves_root_attempt"] = False
                checks["background_rotation_durable_predecessor_closed_successor_open"] = False
                checks["background_progress_does_not_require_user_continue"] = False
                checks["background_worker_auto_continue_precedes_replan"] = False
                checks["background_no_progress_creates_governed_replanner"] = False
                checks["background_replan_remains_same_mission_truth"] = False

            # Kill/restart the Control Loop itself. No durable Mission/Session
            # reconstruction is supplied to it beyond R1 + provider facts.
            assert control is not None
            control.terminate(); control.wait(timeout=5); control = None
            status_call += 1
            status_payload = {"mission_id": mission_id}
            bind_host_tool(
                env, session_id=primary_host_session, agent="aitest-director", tool="aitest_director",
                action="status", payload=status_payload, label=f"background-status-{status_call}",
            )
            before = run(env, "DIRECTOR", "status", status_payload)
            once = subprocess.run(
                module_command("aitest_runtime.control_loop", "--workspace-root", str(root), "--once"),
                cwd=str(root), env=env, capture_output=True, text=True, timeout=30,
            )
            status_call += 1
            status_payload = {"mission_id": mission_id}
            bind_host_tool(
                env, session_id=primary_host_session, agent="aitest-director", tool="aitest_director",
                action="status", payload=status_payload, label=f"background-status-{status_call}",
            )
            after = run(env, "DIRECTOR", "status", status_payload)
            checks["control_loop_restart_rebuilds_from_r1_without_state_loss"] = once.returncode == 0 and before["head_seq"] <= after["head_seq"] and after["mission_id"] == mission_id
            checks["background_provider_calls_are_directory_scoped"] = bool(Stub.requests) and all(
                item["directory"] == str(root.resolve()) for item in Stub.requests if str(item["path"]).startswith("/session")
            )
            checks["runtime_aborts_predecessor_and_submits_successor_asynchronously"] = (
                any(item["path"] == f"/session/{predecessor}/abort" for item in Stub.requests)
                and any(str(item["path"]).endswith("/prompt_async") for item in Stub.requests)
                and not any(item["method"] == "POST" and str(item["path"]).endswith("/message") for item in Stub.requests)
            )
    finally:
        if control is not None:
            control.terminate()
            try: control.wait(timeout=3)
            except subprocess.TimeoutExpired: control.kill()
        server.shutdown(); server.server_close(); thread.join(timeout=2)

    payload = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "http_requests": len(Stub.requests),
        "diagnostics": diagnostics,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
