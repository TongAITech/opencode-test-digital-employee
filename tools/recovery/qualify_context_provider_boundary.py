"""Qualify the Context Governor at the real OpenCode host/provider boundary.

This is intentionally NOT a real-model proof. It runs the exact host binary
supplied by the caller against a loopback OpenAI-compatible recording provider.
The provider returns deterministic text only; it never authors a Plan or AITest
semantic result.

What this proves:
- ALLOW reaches the provider transport through the real OpenCode host.
- Large accumulated Host history + a small current turn is BLOCKED before the
  provider transport.
- The block is persisted through canonical R1/G2.1 pressure truth.
- ControlLoop/Supervisor replaces the Planner Session and the bounded bootstrap
  reaches the provider on the successor.
- The same sequence can happen twice without losing Mission/LogicalAgent truth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

parser = argparse.ArgumentParser()
parser.add_argument("--repo", type=Path, required=True)
parser.add_argument("--payload-workspace", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--host-opencode", type=Path, required=True)
parser.add_argument("--timeout", type=int, default=180)
args = parser.parse_args()

repo = args.repo.resolve()
payload = args.payload_workspace.resolve()
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=False)
workspace = output / "workspace"
workspace.mkdir()

def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def sha_json(value) -> str:
    return sha_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())

def wait_until(predicate, timeout: float, *, interval: float = 0.1):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
            last = value
        except Exception as exc:
            last = exc
        time.sleep(interval)
    raise TimeoutError(f"condition not met; last={last!r}")

head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
if subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True).strip():
    raise SystemExit("SOURCE_NOT_CLEAN")

for name in (".opencode", "ai-test"):
    shutil.copytree(repo / "workspace-template" / name, workspace / name,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules"))
for name in ("AGENTS.md", "opencode.json"):
    shutil.copy2(repo / "workspace-template" / name, workspace / name)

# Offline dependencies/runtime come only from an already-qualified payload.
shutil.copytree(payload / ".opencode" / "node_modules", workspace / ".opencode" / "node_modules")
if os.name == "nt":
    shutil.copytree(payload / "runtime" / "python", workspace / "runtime" / "python")
else:
    py = workspace / "runtime" / "python"
    py.mkdir(parents=True)
    (py / "python").symlink_to(sys.executable)

requests: list[dict] = []
requests_lock = threading.Lock()

class RecordingProvider(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        return

    def _json(self, status: int, value):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if urlparse(self.path).path == "/v1/models":
            self._json(200, {"object": "list", "data": [{"id": "fixture-model", "object": "model"}]})
            return
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length)
        path = urlparse(self.path).path
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            body = {}
        with requests_lock:
            requests.append({
                "seq": len(requests) + 1,
                "path": path,
                "body_bytes": len(raw),
                "body_sha256": sha_bytes(raw),
                "stream": bool(body.get("stream")),
                "model": body.get("model"),
                "message_count": len(body.get("messages") or []),
            })
        if path not in {"/v1/chat/completions", "/chat/completions"}:
            self._json(404, {"error": {"message": "unsupported provider path", "path": path}})
            return
        if body.get("stream"):
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self.end_headers()
            created = int(time.time())
            chunks = [
                {"id": "chatcmpl-aitest", "object": "chat.completion.chunk", "created": created,
                 "model": "fixture-model", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "fixture-ok"}, "finish_reason": None}]},
                {"id": "chatcmpl-aitest", "object": "chat.completion.chunk", "created": created,
                 "model": "fixture-model", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
            ]
            for item in chunks:
                self.wfile.write(("data: " + json.dumps(item) + "\n\n").encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True
            return
        self._json(200, {
            "id": "chatcmpl-aitest", "object": "chat.completion", "created": int(time.time()),
            "model": "fixture-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "fixture-ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

provider_server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingProvider)
threading.Thread(target=provider_server.serve_forever, daemon=True).start()
provider_origin = f"http://127.0.0.1:{provider_server.server_port}/v1"

# Use a custom OpenAI-compatible provider so no real credentials/network are
# involved, while still exercising OpenCode's actual provider stack.
config = json.loads((workspace / "opencode.json").read_text(encoding="utf-8"))
config["model"] = "aitest-boundary/fixture-model"
config["small_model"] = "aitest-boundary/fixture-model"
config.setdefault("provider", {})
config["provider"]["aitest-boundary"] = {
    "npm": "@ai-sdk/openai-compatible",
    "name": "AITest Boundary Recorder",
    "options": {"baseURL": provider_origin, "apiKey": "fixture-only"},
    "models": {
        "fixture-model": {
            "name": "AITest Boundary Fixture",
            "tool_call": True,
            "limit": {"context": 65536, "output": 4096},
        }
    },
}
(workspace / "opencode.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    host_port = sock.getsockname()[1]

env = dict(os.environ)
for key in ("GH_TOKEN", "GITHUB_TOKEN"):
    env.pop(key, None)
env.update({
    "AITEST_WORKSPACE_ROOT": str(workspace),
    "AITEST_RUNTIME_SPINE_DB": str(workspace / "data/state/runtime-spine.db"),
    "PFC_LOCAL_STATE_ROOT": str(workspace / "data"),
    "AITEST_OPENCODE_ENDPOINT": f"http://127.0.0.1:{host_port}",
    "OPENCODE_SERVER_USERNAME": "opencode",
    "OPENCODE_SERVER_PASSWORD": uuid.uuid4().hex,
    "OPENCODE_DISABLE_AUTOUPDATE": "1",
    "OPENCODE_DISABLE_MODELS_FETCH": "1",
    "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
    "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
    "OPENCODE_DISABLE_SHARE": "1",
    "npm_config_offline": "true",
    "npm_config_registry": "http://127.0.0.1:9",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "PYTHONPATH": os.pathsep.join([str(workspace / "ai-test/runtime"), os.environ.get("PYTHONPATH", "")]),
})

sys.path[:0] = [str(repo / "tools/recovery"), str(workspace / "ai-test/runtime")]
from host_opencode import CapabilityClient
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.autonomous_orchestration import DirectoryScopedOpenCodeSessionProvider
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.dispatch_receipts import business_cursor
from aitest_runtime.primary_sessions import PrimarySessionOwner

client = CapabilityClient(env["AITEST_OPENCODE_ENDPOINT"], workspace, env)
host = None
old_env = dict(os.environ)
result = {
    "schema_version": "aitest.context-provider-boundary-proof.v1",
    "classification": "REAL_OPENCODE_HOST_LOCAL_RECORDING_PROVIDER_NO_REAL_MODEL",
    "source_head": head,
    "status": "FAIL",
    "provider_origin": provider_origin,
    "gates": {},
}

def call_count():
    with requests_lock:
        return len(requests)

def latest_planner_rotation(tick):
    for item in tick.get("supervision", []):
        value = item.get("result", {}) if item.get("phase") == "PLANNING" else {}
        if value.get("status") == "ROTATED":
            return value
    return None


def latest_task_rotation(tick, task_id):
    for item in tick.get("supervision", []):
        if item.get("task_id") != task_id:
            continue
        value = item.get("result", {})
        if value.get("status") == "ROTATED":
            return value.get("rotation")
    return None


class CrashAfterHostAcceptProvider:
    """Delegate to the real OpenCode Host, then lose the client-side receipt once."""

    def __init__(self, delegate):
        self.delegate = delegate
        self.crash_once = True

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def send_context(self, *, session_id: str, agent: str, text: str):
        value = self.delegate.send_context(session_id=session_id, agent=agent, text=text)
        if self.crash_once:
            self.crash_once = False
            raise OSError("SIMULATED_CLIENT_CRASH_AFTER_OPENCODE_ACCEPT")
        return value

try:
    host = subprocess.Popen(
        [str(args.host_opencode), "serve", "--hostname", "127.0.0.1", "--port", str(host_port)],
        cwd=workspace, env=env, stdout=(output / "opencode.log").open("wb"),
        stderr=subprocess.STDOUT,
    )
    wait_until(lambda: client.request("GET", "/global/health", timeout=1).get("healthy"), 45)

    os.environ.update(env)
    runtime = create_canonical_runtime(workspace)
    provider = DirectoryScopedOpenCodeSessionProvider(workspace, timeout=20)
    service = G21AutonomousOrchestrationService(runtime, workspace, session_provider=provider)

    started = service.start_test({
        "intake_id": "context-provider-boundary",
        "operation": "CREATE",
        "scope": {"mode": "EXPLICIT_SET", "project_id": "PFC", "version": "BOUNDARY", "requirements": ["REQ-C2"]},
        "goal": {"title": "Context Provider Boundary", "intent": "prove host transport admission", "constraints": []},
        "source": {"kind": "USER", "source_ref": "qualification:context-provider-boundary",
                   "source_digest": sha_json({"goal": "context-provider-boundary"}),
                   "observed_at": "2026-09-14T00:00:00Z", "valid_until": None, "source_precedence": 1},
        "actor": {"type": "USER", "id": "qualification"},
        "resolution": {"resolution_id": "resolution:context-provider-boundary",
                       "request_digest": sha_json({"request": "context-provider-boundary"}),
                       "snapshot_id": "snapshot:context-provider-boundary",
                       "fact_set_digest": sha_json({"facts": []}), "status": "RESOLVED",
                       "reason_code": None, "source_refs": ["qualification:context-provider-boundary"],
                       "valid_until": "2026-09-15T00:00:00Z"},
    })
    mission = started["intake"]["intake"]["mission_id"]
    planner = started["planner_session"]["external_session"]["session_id"]

    # The bounded Planner bootstrap must reach the provider through the real host.
    wait_until(lambda: call_count() >= 1, 30)
    baseline_calls = call_count()
    result["gates"]["ALLOW_REACHES_PROVIDER"] = "PASS"

    current = planner
    rotations = []
    for cycle in (1, 2):
        # noReply persists real Host history without creating a provider call.
        history = ("历史压力样本-%d-" % cycle) + ("测" * 52000)
        client.request(
            "POST", f"/session/{current}/message",
            {"agent": "aitest-planner", "noReply": True,
             "parts": [{"type": "text", "text": history}]},
            timeout=30, budget=8 * 1024 * 1024,
        )
        before_block = call_count()
        if before_block != baseline_calls + len(rotations):
            raise RuntimeError("NOREPLY_REACHED_PROVIDER")

        # A small current turn must be recoverable on a clean successor.
        client.request(
            "POST", f"/session/{current}/prompt_async",
            {"agent": "aitest-planner", "parts": [{"type": "text", "text": f"继续当前规划，压力恢复验证 {cycle}"}]},
            timeout=30,
        )
        # The plugin invokes Python synchronously before provider transport.
        wait_until(
            lambda: (
                service.session_control.state(mission).observation(current) is not None
                and service.session_control.state(mission).observation(current).provider_state
                    .get("pressure", {}).get("final_request_admission_blocked") is True
            ),
            30,
        )
        time.sleep(0.5)
        if call_count() != before_block:
            raise RuntimeError("BLOCKED_REQUEST_REACHED_PROVIDER")
        result["gates"][f"BLOCK_{cycle}_PREVENTS_PROVIDER"] = "PASS"

        tick = service.supervise_once()
        rotation = latest_planner_rotation(tick)
        if not rotation or rotation["predecessor_session_id"] != current:
            raise RuntimeError("PLANNER_ROTATION_NOT_OBSERVED")
        successor = rotation["successor_session_id"]
        if successor == current:
            raise RuntimeError("SUCCESSOR_REUSED_PREDECESSOR")
        rotations.append({
            "cycle": cycle,
            "predecessor": current,
            "successor": successor,
            "rotation_id": rotation["rotation_id"],
        })
        current = successor
        wait_until(lambda: call_count() >= before_block + 1, 30)
        baseline_calls = before_block
        result["gates"][f"SUCCESSOR_{cycle}_BOOTSTRAP_REACHES_PROVIDER"] = "PASS"

    control = service.session_control.state(mission)
    completed = [x for x in control.rotations if x.status == "COMPLETED"]
    if len(completed) < 2:
        raise RuntimeError("TWO_DURABLE_ROTATIONS_REQUIRED")

    # Exercise the normal Mission Worker path on the same exact Host. The plan
    # is a deterministic qualification fixture; no fixture model output is
    # treated as a Planner decision.
    worker_plan = {
        "objective": "qualify worker context rotation",
        "tasks": [{
            "task_key": "boundary-worker",
            "intent": "bounded executor qualification",
            "acceptance_criteria": [{"id": "done", "description": "worker Session remains replaceable"}],
            "routing": {
                "role": "EXECUTOR",
                "required_capabilities": ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"],
                "isolation_policy": "DEDICATED_TASK_SESSION",
                "parallelism_policy": "SERIAL",
            },
        }],
        "dependencies": [],
    }
    before_worker_dispatch = call_count()
    dispatched = service.propose_plan(mission, worker_plan)["next"]
    worker_task_id = dispatched["task_id"]
    worker = dispatched["external_session"]["session_id"]
    wait_until(lambda: call_count() >= before_worker_dispatch + 1, 30)
    worker_rotations = []
    for cycle in (1, 2):
        worker_history = ("WORKER-HISTORY-%d-" % cycle) + ("测" * 52000)
        client.request(
            "POST", f"/session/{worker}/message",
            {"agent": "aitest-executor", "noReply": True,
             "parts": [{"type": "text", "text": worker_history}]},
            timeout=30, budget=8 * 1024 * 1024,
        )
        before_worker_block = call_count()
        client.request(
            "POST", f"/session/{worker}/prompt_async",
            {"agent": "aitest-executor",
             "parts": [{"type": "text", "text": f"继续当前执行任务，Worker 压力恢复验证 {cycle}"}]},
            timeout=30,
        )
        wait_until(
            lambda: (
                service.session_control.state(mission).observation(worker) is not None
                and service.session_control.state(mission).observation(worker).provider_state
                    .get("pressure", {}).get("final_request_admission_blocked") is True
            ),
            30,
        )
        time.sleep(0.5)
        if call_count() != before_worker_block:
            raise RuntimeError("WORKER_BLOCKED_REQUEST_REACHED_PROVIDER")
        tick = service.supervise_once()
        rotation = latest_task_rotation(tick, worker_task_id)
        if not rotation or rotation["predecessor_session_id"] != worker:
            raise RuntimeError("WORKER_ROTATION_NOT_OBSERVED")
        successor = rotation["successor_session_id"]
        if successor == worker:
            raise RuntimeError("WORKER_SUCCESSOR_REUSED_PREDECESSOR")
        wait_until(lambda: call_count() >= before_worker_block + 1, 30)
        worker_rotations.append({
            "cycle": cycle,
            "predecessor": worker,
            "successor": successor,
            "rotation_id": rotation["rotation_id"],
            "root_attempt_id": rotation["root_attempt_id"],
        })
        worker = successor
    if len({dispatched["external_session"]["session_id"], *(x["successor"] for x in worker_rotations)}) != 3:
        raise RuntimeError("TWO_DISTINCT_WORKER_SUCCESSORS_REQUIRED")
    result["gates"]["WORKER_TWO_DURABLE_ROTATIONS"] = "PASS"
    result["worker_rotations"] = worker_rotations

    # Primary end-to-end plugin proof on the exact Host. Accumulate large
    # history without a model call, then send a small current turn. The old
    # request must be blocked inside OpenCode, Runtime must create a clean
    # successor, and only that successor may reach provider transport.
    live_primary = PrimarySessionOwner(runtime, workspace, provider)
    live_old = live_primary.ensure_current()
    live_history = "PRIMARY-CONTEXT-PRESSURE-" + ("测" * 52000)
    client.request(
        "POST", f"/session/{live_old['session_id']}/message",
        {"agent": "aitest-director", "noReply": True,
         "parts": [{"type": "text", "text": live_history}]},
        timeout=30, budget=8 * 1024 * 1024,
    )
    before_primary_block = call_count()
    live_text = "继续当前任务；验证 Primary Context Governor 自动切换 clean successor。"
    client.request(
        "POST", f"/session/{live_old['session_id']}/prompt_async",
        {"agent": "aitest-director", "parts": [{"type": "text", "text": live_text}]},
        timeout=30,
    )

    def live_primary_accepted():
        state = live_primary.state()
        predecessor = state.bindings.get(str(live_old["epoch"])) or {}
        recovery = predecessor.get("context_recovery") or {}
        if state.epoch <= live_old["epoch"] or recovery.get("state") != "ACCEPTED":
            return None
        successor = state.bindings.get(str(state.epoch)) or {}
        sid = successor.get("session_id")
        return sid if sid and sid != live_old["session_id"] else None

    live_successor = wait_until(live_primary_accepted, 45)
    wait_until(lambda: call_count() >= before_primary_block + 1, 30)
    time.sleep(0.5)
    if call_count() != before_primary_block + 1:
        raise RuntimeError("PRIMARY_BLOCK_OR_REPLAY_PROVIDER_DUPLICATE")
    live_recovery = live_primary.state().bindings[str(live_old["epoch"])]["context_recovery"]
    if live_recovery.get("target_session_id") != live_successor:
        raise RuntimeError("PRIMARY_PLUGIN_SUCCESSOR_IDENTITY_MISMATCH")
    result["gates"]["PRIMARY_PLUGIN_BLOCK_REPLAYS_ON_CLEAN_SUCCESSOR"] = "PASS"
    result["primary_plugin_recovery"] = {
        "predecessor_epoch": live_old["epoch"],
        "predecessor": live_old["session_id"],
        "successor": live_successor,
        "final_state": live_recovery["state"],
        "provider_delta": call_count() - before_primary_block,
    }

    # Real Host crash-window proof for the Primary path. The OpenCode HTTP
    # request succeeds and stores the user message, but the client deliberately
    # loses the acknowledgement. R1 must remain SENDING until a fresh Owner
    # reconciles by Host readback; it must never replay the same turn blindly.
    crashing = CrashAfterHostAcceptProvider(provider)
    primary = PrimarySessionOwner(runtime, workspace, crashing)
    primary_old = primary.ensure_current()
    crash_predecessor_epoch = primary_old["epoch"]
    replay_text = "继续当前任务；验证真实 OpenCode Host 接收后客户端崩溃的 readback 恢复。"
    replay_digest = hashlib.sha256(replay_text.encode()).hexdigest()
    recovery_id = primary.claim_context_recovery(
        primary_old["session_id"], "aitest-director", replay_text, "c" * 64
    )
    first_recovery = primary.recover_pending_context()
    if first_recovery.get("status") != "RECONCILE_REQUIRED" or first_recovery.get("reason") != "PRIMARY_RECOVERY_EFFECT_UNKNOWN":
        raise RuntimeError("PRIMARY_CRASH_WINDOW_DID_NOT_ENTER_RECONCILE")
    primary_state = primary.state()
    journal = primary_state.bindings[str(crash_predecessor_epoch)].get("context_recovery") or {}
    if journal.get("state") != "SENDING":
        raise RuntimeError("PRIMARY_CRASH_WINDOW_NOT_DURABLE_SENDING")
    primary_successor = primary_state.bindings[str(primary_state.epoch)]["session_id"]

    # A new owner instance represents process restart. Readback of the exact
    # successor text is the only path to ACCEPTED. find_context_receipt itself
    # fails closed if more than one matching user message exists.
    restarted_primary = PrimarySessionOwner(runtime, workspace, provider)

    def reconcile_primary():
        value = restarted_primary.recover_pending_context()
        if value.get("status") == "ACCEPTED":
            return value
        if value.get("status") == "RECONCILE_REQUIRED":
            return None
        raise RuntimeError("PRIMARY_CRASH_WINDOW_RECONCILE_STATE_INVALID")

    # prompt_async forks the OpenCode prompt task and returns 204 immediately.
    # The user message may therefore become visible after the client has already
    # lost the acknowledgement. Polling here models repeated ControlLoop ticks;
    # SENDING is read-only during these ticks and can never trigger a resend.
    accepted = wait_until(reconcile_primary, 30)
    if accepted.get("successor_session_id") != primary_successor:
        raise RuntimeError("PRIMARY_CRASH_WINDOW_READBACK_NOT_ACCEPTED")
    receipt = provider.find_context_receipt(primary_successor, replay_digest)
    if receipt is None or receipt.get("message_id") != accepted.get("receipt", {}).get("message_id"):
        raise RuntimeError("PRIMARY_CRASH_WINDOW_RECEIPT_MISMATCH")
    if restarted_primary.pending_context_recovery() is not None:
        raise RuntimeError("PRIMARY_CRASH_WINDOW_REMAINED_PENDING")
    result["gates"]["PRIMARY_CRASH_AFTER_HOST_ACCEPT_READBACK"] = "PASS"
    result["primary_crash_window"] = {
        "recovery_id": recovery_id,
        "predecessor": primary_old["session_id"],
        "successor": primary_successor,
        "final_state": restarted_primary.state().bindings[str(crash_predecessor_epoch)]["context_recovery"]["state"],
        "receipt": receipt,
        "blind_resend": False,
    }

    # C3 exact-host qualification: durable no-progress must create a governed
    # Replanning Planner on the actual OpenCode 1.18.3 Host. Host-observed
    # context pressure must rotate that Replanner while preserving the same
    # progress-bound lineage. No model semantic output is used to author a Plan.
    c3_started = service.start_test({
        "intake_id": "c3-replanning-host-boundary",
        "operation": "CREATE",
        "scope": {"mode": "EXPLICIT_SET", "project_id": "PFC", "version": "C3-HOST", "requirements": ["REQ-C3"]},
        "goal": {"title": "C3 Replanning Host Boundary", "intent": "prove durable no-progress replanning on exact host", "constraints": []},
        "source": {"kind": "USER", "source_ref": "qualification:c3-replanning-host-boundary",
                   "source_digest": sha_json({"goal": "c3-replanning-host-boundary"}),
                   "observed_at": "2026-09-14T00:00:00Z", "valid_until": None, "source_precedence": 1},
        "actor": {"type": "USER", "id": "qualification"},
        "resolution": {"resolution_id": "resolution:c3-replanning-host-boundary",
                       "request_digest": sha_json({"request": "c3-replanning-host-boundary"}),
                       "snapshot_id": "snapshot:c3-replanning-host-boundary",
                       "fact_set_digest": sha_json({"facts": []}), "status": "RESOLVED",
                       "reason_code": None, "source_refs": ["qualification:c3-replanning-host-boundary"],
                       "valid_until": "2026-09-15T00:00:00Z"},
    })
    c3_mission = c3_started["intake"]["intake"]["mission_id"]
    c3_worker = service.propose_plan(c3_mission, {
        "objective": "one bounded worker for no-progress host qualification",
        "tasks": [{
            "task_key": "worker",
            "intent": "bounded execution",
            "acceptance_criteria": [{"id": "done", "description": "host replanning proves autonomous continuation substrate"}],
            "routing": {"role": "EXECUTOR",
                        "required_capabilities": ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"],
                        "isolation_policy": "DEDICATED_TASK_SESSION",
                        "parallelism_policy": "SERIAL"},
        }],
        "dependencies": [],
    })["next"]
    c3_cursor = business_cursor(runtime, c3_mission)
    before_replan_provider = call_count()
    c3_replan = service._handle_no_progress(
        c3_mission,
        task_id=c3_worker["task_id"],
        session_id=c3_worker["external_session"]["session_id"],
        reason="AUTO_CONTINUE_NO_BUSINESS_PROGRESS",
        cursor=c3_cursor,
    )
    if c3_replan.get("status") != "REPLAN_DISPATCHED":
        raise RuntimeError("C3_EXACT_HOST_REPLAN_NOT_DISPATCHED")
    c3_progress_id = c3_replan["progress_id"]
    c3_replan_session = c3_replan["session_id"]
    wait_until(lambda: call_count() >= before_replan_provider + 1, 30)
    result["gates"]["C3_REPLANNING_CONTEXT_REACHES_PROVIDER"] = "PASS"

    client.request(
        "POST", f"/session/{c3_replan_session}/message",
        {"agent": "aitest-planner", "noReply": True,
         "parts": [{"type": "text", "text": "C3-HOST-PRESSURE-" + ("测" * 120000)}]},
        timeout=30, budget=2 * 1024 * 1024,
    )
    def c3_pressure_ready():
        observed = provider.observe_session(c3_replan_session)
        utilization = observed.get("context_utilization")
        messages = observed.get("message_count")
        pressured = (
            (isinstance(utilization, (int, float)) and float(utilization) >= 0.85)
            or (isinstance(messages, int) and messages >= 60)
            or bool((observed.get("pressure") or {}).get("observation_byte_budget_exceeded"))
        )
        return observed if pressured else None

    c3_observation = wait_until(c3_pressure_ready, 30)
    c3_activity = wait_until(
        lambda: (lambda value: value if value == "idle" else None)(provider.session_activity(c3_replan_session)),
        30,
    )
    result["c3_replanning_host_observation"] = {
        "activity": c3_activity,
        "message_count": c3_observation.get("message_count"),
        "context_utilization": c3_observation.get("context_utilization"),
        "context_used": c3_observation.get("context_used"),
        "context_limit": c3_observation.get("context_limit"),
        "pressure": c3_observation.get("pressure"),
    }

    before_rotation_provider = call_count()
    c3_tick = service.supervise_once()
    c3_rotations = [
        item["result"] for item in c3_tick.get("supervision", [])
        if item.get("phase") == "REPLANNING"
        and item.get("result", {}).get("status") == "ROTATED"
        and item.get("result", {}).get("progress_id") == c3_progress_id
    ]
    if len(c3_rotations) != 1:
        raise RuntimeError("C3_EXACT_HOST_REPLANNER_ROTATION_NOT_OBSERVED")
    c3_rotation = c3_rotations[0]
    c3_successor = c3_rotation["successor_session_id"]
    if c3_successor == c3_replan_session:
        raise RuntimeError("C3_EXACT_HOST_REPLANNER_SUCCESSOR_REUSED")
    wait_until(lambda: call_count() >= before_rotation_provider + 1, 30)
    c3_progress = service.session_control.state(c3_mission).progress(c3_progress_id)
    if c3_progress is None or c3_progress.replan_session_id != c3_successor:
        raise RuntimeError("C3_EXACT_HOST_PROGRESS_POINTER_NOT_ADVANCED")
    result["gates"]["C3_REPLANNER_PRESSURE_ROTATES_ON_EXACT_HOST"] = "PASS"

    before_reentry_provider = call_count()
    c3_reentry = service._handle_no_progress(
        c3_mission,
        task_id=c3_worker["task_id"],
        session_id=c3_worker["external_session"]["session_id"],
        reason="AUTO_CONTINUE_NO_BUSINESS_PROGRESS",
        cursor=c3_cursor,
    )
    if c3_reentry.get("status") != "REPLAN_IN_PROGRESS" or c3_reentry.get("session_id") != c3_successor:
        raise RuntimeError("C3_EXACT_HOST_REENTRY_DID_NOT_REUSE_SUCCESSOR")
    time.sleep(0.5)
    if call_count() != before_reentry_provider:
        raise RuntimeError("C3_EXACT_HOST_REENTRY_DUPLICATED_PROVIDER_PROMPT")

    restarted_c3 = G21AutonomousOrchestrationService(runtime, workspace, session_provider=provider)
    c3_restart = restarted_c3._handle_no_progress(
        c3_mission,
        task_id=c3_worker["task_id"],
        session_id=c3_worker["external_session"]["session_id"],
        reason="AUTO_CONTINUE_NO_BUSINESS_PROGRESS",
        cursor=c3_cursor,
    )
    if c3_restart.get("status") != "REPLAN_IN_PROGRESS" or c3_restart.get("session_id") != c3_successor:
        raise RuntimeError("C3_EXACT_HOST_RESTART_DID_NOT_REUSE_SUCCESSOR")
    result["gates"]["C3_REPLAN_RESTART_REUSES_SUCCESSOR"] = "PASS"
    result["c3_replanning_host"] = {
        "mission_id": c3_mission,
        "progress_id": c3_progress_id,
        "initial_replan_session": c3_replan_session,
        "successor_replan_session": c3_successor,
        "rotation_id": c3_rotation["rotation_id"],
        "lineage": c3_rotation["root_attempt_id"],
        "provider_calls_after_reentry": call_count(),
        "duplicate_replan_prompt": False,
    }

    result.update({
        "status": "PASS",
        "mission_id": mission,
        "rotation_count": len(rotations),
        "rotations": rotations,
        "provider_request_count": call_count(),
        "provider_requests": list(requests),
        "gates": {**result["gates"], "TWO_DURABLE_ROTATIONS": "PASS"},
        "r1_cursor": runtime.get_head_seq(mission),
    })
finally:
    if host is not None and host.poll() is None:
        host.terminate()
        try:
            host.wait(timeout=10)
        except subprocess.TimeoutExpired:
            host.kill()
            host.wait()
    provider_server.shutdown()
    provider_server.server_close()
    os.environ.clear()
    os.environ.update(old_env)
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))

raise SystemExit(0 if result["status"] == "PASS" else 1)
