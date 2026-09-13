"""Real-model Context Governor qualification on an authenticated OpenCode host.

The caller supplies the existing host OpenCode binary and a qualified payload
workspace. Provider/model selection and authentication remain the host user's
own merged OpenCode configuration. This script never copies credentials and
never overrides the selected provider.

It proves two consecutive Primary recoveries caused by large accumulated Host
history while each current user turn remains small/replayable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import time
import uuid

parser = argparse.ArgumentParser()
parser.add_argument("--repo", type=Path, required=True)
parser.add_argument("--payload-workspace", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--host-opencode", type=Path, required=True)
parser.add_argument("--timeout", type=int, default=300)
args = parser.parse_args()

repo = args.repo.resolve()
payload = args.payload_workspace.resolve()
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=False)
workspace = output / "workspace"
workspace.mkdir()

def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def wait_until(fn, timeout: float, interval: float = 0.2):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            value = fn()
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
shutil.copytree(payload / ".opencode" / "node_modules", workspace / ".opencode" / "node_modules")
if os.name == "nt":
    shutil.copytree(payload / "runtime" / "python", workspace / "runtime" / "python")
else:
    py = workspace / "runtime/python"
    py.mkdir(parents=True)
    (py / "python").symlink_to(sys.executable)

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

env = dict(os.environ)
for key in ("GH_TOKEN", "GITHUB_TOKEN"):
    env.pop(key, None)
env.update({
    "AITEST_WORKSPACE_ROOT": str(workspace),
    "AITEST_RUNTIME_SPINE_DB": str(workspace / "data/state/runtime-spine.db"),
    "PFC_LOCAL_STATE_ROOT": str(workspace / "data"),
    "AITEST_OPENCODE_ENDPOINT": f"http://127.0.0.1:{port}",
    "OPENCODE_SERVER_USERNAME": "opencode",
    "OPENCODE_SERVER_PASSWORD": uuid.uuid4().hex,
    "OPENCODE_DISABLE_AUTOUPDATE": "1",
    "OPENCODE_DISABLE_MODELS_FETCH": "1",
    "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
    "OPENCODE_DISABLE_SHARE": "1",
    "npm_config_offline": "true",
    "npm_config_registry": "http://127.0.0.1:9",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "PYTHONPATH": os.pathsep.join([str(workspace / "ai-test/runtime"), os.environ.get("PYTHONPATH", "")]),
})
# Deliberately do not set XDG_CONFIG_HOME, provider/model env vars or provider
# credentials. The host user's existing merged configuration remains authority.

sys.path[:0] = [str(repo / "tools/recovery"), str(workspace / "ai-test/runtime")]
from host_opencode import CapabilityClient
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.autonomous_orchestration import DirectoryScopedOpenCodeSessionProvider
from aitest_runtime.primary_sessions import PrimarySessionOwner

client = CapabilityClient(env["AITEST_OPENCODE_ENDPOINT"], workspace, env)
host = None
old_env = dict(os.environ)
result = {
    "schema_version": "aitest.context-real-model-proof.v1",
    "classification": "REAL_HOST_REAL_MODEL_CONTEXT_RECOVERY",
    "source_head": head,
    "host_system": platform.system(),
    "status": "FAIL",
    "host_provider_auth_copied": False,
    "provider_override": False,
    "gates": {},
}

def messages(session_id: str):
    value = client.request("GET", f"/session/{session_id}/message?limit=50", timeout=20, budget=8 * 1024 * 1024)
    return value if isinstance(value, list) else []

def real_assistant(session_id: str):
    for row in reversed(messages(session_id)):
        info = row.get("info", {})
        if info.get("role") != "assistant":
            continue
        if info.get("error"):
            continue
        provider_id = info.get("providerID")
        model_id = info.get("modelID")
        if provider_id and model_id and "fixture" not in (str(provider_id) + str(model_id)).lower():
            return {"provider_id": provider_id, "model_id": model_id, "message_id": info.get("id")}
    return None

def error_summaries(session_id: str):
    out = []
    for row in messages(session_id):
        info = row.get("info", {})
        error = info.get("error")
        if error:
            out.append({"message_id": info.get("id"), "name": error.get("name"),
                        "message": str(error.get("message") or error)[:1000]})
    return out

try:
    host = subprocess.Popen(
        [str(args.host_opencode), "serve", "--hostname", "127.0.0.1", "--port", str(port)],
        cwd=workspace, env=env, stdout=(output / "opencode.log").open("wb"),
        stderr=subprocess.STDOUT,
    )
    wait_until(lambda: client.request("GET", "/global/health", timeout=1).get("healthy"), 45)

    os.environ.update(env)
    runtime = create_canonical_runtime(workspace)
    provider = DirectoryScopedOpenCodeSessionProvider(workspace, timeout=30)
    owner = PrimarySessionOwner(runtime, workspace, provider)
    primary = owner.ensure_current()
    current = primary["session_id"]

    client.request(
        "POST", f"/session/{current}/prompt_async",
        {"agent": "aitest-director",
         "parts": [{"type": "text", "text": "你好。只简短回复 CONTEXT_OK，不启动测试任务。"}]},
        timeout=20,
    )
    first_model = wait_until(lambda: real_assistant(current), args.timeout)
    result["initial_model"] = first_model
    result["gates"]["INITIAL_REAL_MODEL_ALLOW"] = "PASS"

    rotations = []
    identities = {(first_model["provider_id"], first_model["model_id"])}
    for cycle in (1, 2):
        # Large historical context is stored in the Host without invoking the
        # provider. The current turn remains tiny enough to replay safely.
        history = f"C2-REAL-MODEL-HISTORY-{cycle}-" + ("测" * 700000)
        client.request(
            "POST", f"/session/{current}/message",
            {"agent": "aitest-director", "noReply": True,
             "parts": [{"type": "text", "text": history}]},
            timeout=40, budget=4 * 1024 * 1024,
        )
        epoch_before = owner.state().epoch
        prompt = f"第{cycle}轮上下文恢复验证：只简短回复 CONTEXT_OK，不启动测试任务。"
        client.request(
            "POST", f"/session/{current}/prompt_async",
            {"agent": "aitest-director", "parts": [{"type": "text", "text": prompt}]},
            timeout=20,
        )

        def successor():
            state = owner.state()
            binding = state.bindings.get(str(state.epoch))
            if state.epoch <= epoch_before or not binding or binding.get("state") != "BOUND":
                return None
            sid = binding.get("session_id")
            return sid if sid and sid != current else None

        next_session = wait_until(successor, 60)
        model = wait_until(lambda: real_assistant(next_session), args.timeout)
        identities.add((model["provider_id"], model["model_id"]))
        rotations.append({
            "cycle": cycle,
            "predecessor_session_id": current,
            "successor_session_id": next_session,
            "epoch": owner.state().epoch,
            "successor_model": model,
            "predecessor_errors": error_summaries(current),
        })
        current = next_session
        result["gates"][f"REAL_MODEL_RECOVERY_{cycle}"] = "PASS"

    if len(rotations) != 2 or len({primary["session_id"], *(x["successor_session_id"] for x in rotations)}) != 3:
        raise RuntimeError("TWO_DISTINCT_SUCCESSORS_REQUIRED")
    state = owner.state()
    if state.epoch < 3:
        raise RuntimeError("PRIMARY_EPOCH_DID_NOT_ADVANCE_TWICE")
    result.update({
        "status": "PASS",
        "rotations": rotations,
        "final_epoch": state.epoch,
        "model_identities": [{"provider_id": p, "model_id": m} for p, m in sorted(identities)],
        "gates": {**result["gates"], "TWO_CONSECUTIVE_REAL_MODEL_SUCCESSORS": "PASS"},
        "r1_root_head_seq": runtime.get_subject_head_seq(owner.subject),
    })
except Exception as exc:
    result.update({
        "error_type": type(exc).__name__,
        "error_code": getattr(exc, "code", None),
        "error_message": str(exc)[:2000],
    })
finally:
    if host is not None and host.poll() is None:
        host.terminate()
        try:
            host.wait(timeout=10)
        except subprocess.TimeoutExpired:
            host.kill()
            host.wait()
    os.environ.clear()
    os.environ.update(old_env)
    result["report_path"] = str(output / "result.json")
    result["harness_sha256"] = file_sha(Path(__file__))
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))

raise SystemExit(0 if result["status"] == "PASS" else 1)
