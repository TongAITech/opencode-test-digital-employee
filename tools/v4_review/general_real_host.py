"""One natural GeneralWork request through actual OpenCode/model and product tools.

Only copied public product source and synthetic local notes are exposed. No
auth/provider file is copied or edited. This is a C1 component proof, not L4.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import uuid


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--dependencies", type=Path, required=True)
    p.add_argument("--opencode", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--timeout", type=int, default=180)
    args = p.parse_args(); repo = args.repo.resolve(); out = args.output.resolve(); ws = out / "workspace"
    ws.mkdir(parents=True, exist_ok=False)
    for name in (".opencode", "ai-test"):
        shutil.copytree(repo / "workspace-template" / name, ws / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules", "state", "evidence"))
    for name in ("opencode.json", "AGENTS.md"): shutil.copyfile(repo / "workspace-template" / name, ws / name)
    shutil.copytree(args.dependencies, ws / ".opencode/node_modules")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    sources = {str(f.relative_to(ws)): hashlib.sha256(f.read_bytes()).hexdigest() for f in ws.rglob("*") if f.is_file() and "node_modules" not in f.parts}
    (ws / "INSTALL_MANIFEST.json").write_text(json.dumps({"classification": "CONSTRUCTION_GENERAL_WORK_COMPONENT", "head": head, "source_snapshot": sources}))
    (ws / "runtime/python").mkdir(parents=True); (ws / "runtime/python/python").symlink_to(sys.executable)
    (ws / "notes").mkdir(); (ws / "notes/input.txt").write_text("blue apple", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet", "--template=", str(ws)], check=True)
    sys.path[:0] = [str(repo / "tools/recovery"), str(ws / "ai-test/runtime")]
    from host_opencode import CapabilityClient
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    env = dict(os.environ)
    for k in ("GH_TOKEN", "GITHUB_TOKEN"): env.pop(k, None)
    env.update(AITEST_WORKSPACE_ROOT=str(ws), AITEST_RUNTIME_SPINE_DB=str(ws / "data/state/runtime-spine.db"), PFC_LOCAL_STATE_ROOT=str(ws / "data"),
        AITEST_OPENCODE_ENDPOINT="http://127.0.0.1:" + str(port), OPENCODE_SERVER_USERNAME="opencode", OPENCODE_SERVER_PASSWORD=uuid.uuid4().hex,
        OPENCODE_DISABLE_AUTOUPDATE="1", OPENCODE_DISABLE_MODELS_FETCH="1", OPENCODE_DISABLE_DEFAULT_PLUGINS="1", OPENCODE_DISABLE_LSP_DOWNLOAD="1", OPENCODE_DISABLE_SHARE="1",
        npm_config_offline="true", npm_config_registry="http://127.0.0.1:9", PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=os.pathsep.join([str(ws / "ai-test/runtime"), os.environ.get("PYTHONPATH", "")]))
    client = CapabilityClient(env["AITEST_OPENCODE_ENDPOINT"], ws, env)
    request = "读取 notes/input.txt 并把其中的 blue 改为 green 后写到 notes/result.txt"
    result = {"classification": "REAL_HOST_GENERAL_WORK_COMPONENT_NOT_L4", "source_head": head, "source_snapshot": sources,
        "user_request": request, "user_turn_count": 1, "user_technical_command_count": 0, "model_identity": [], "status": "FAIL",
        "default_plugins": "DISABLED_FOR_ISOLATED_COMPONENT_PROBE", "host_auth_or_model_config_modified": False}
    server = loop = None
    try:
        with (out / "host.log").open("w") as log:
            server = subprocess.Popen([str(args.opencode), "serve", "--hostname", "127.0.0.1", "--port", str(port)], cwd=ws, env=env, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                if client.request("GET", "/global/health", timeout=1).get("healthy"): break
            except Exception: time.sleep(.3)
        else: raise RuntimeError("HOST_STARTUP_FAILED")
        agents = client.request("GET", "/agent")
        required = {"aitest-director", "aitest-general-worker", "aitest-runtime-diagnosis"}
        result["required_agents_present"] = required <= {a["name"] for a in agents}
        if not result["required_agents_present"]: raise RuntimeError("PRODUCT_AGENTS_MISSING")
        with (out / "loop.log").open("w") as log:
            loop = subprocess.Popen([sys.executable, "-m", "aitest_runtime.control_loop", "--workspace-root", str(ws), "--interval", "2"], cwd=ws, env=env, stdout=log, stderr=subprocess.STDOUT)
        from aitest_runtime.canonical_runtime import create_canonical_runtime
        from aitest_runtime.autonomous_orchestration import DirectoryScopedOpenCodeSessionProvider
        from aitest_runtime.primary_sessions import PrimarySessionOwner
        runtime = create_canonical_runtime(ws, db_path=ws / "data/state/runtime-spine.db")
        provider = DirectoryScopedOpenCodeSessionProvider(ws, base_url=env["AITEST_OPENCODE_ENDPOINT"],
            username=env["OPENCODE_SERVER_USERNAME"], password=env["OPENCODE_SERVER_PASSWORD"])
        director = PrimarySessionOwner(runtime, ws, provider).ensure_current()["session_id"]
        client.request("POST", "/session/" + director + "/prompt_async", {"agent": "aitest-director", "parts": [{"type": "text", "text": request}]})
        result["director_session_id"] = director
        deadline = time.monotonic() + args.timeout
        last_sessions = []
        while time.monotonic() < deadline:
            snapshots = []
            last_sessions = client.request("GET", "/session")
            for session in last_sessions:
                rows = client.request("GET", "/session/" + session["id"] + "/message?limit=40", budget=1024*1024)
                snapshots.append({"session_id": session["id"], "messages": rows})
            (out / "host-messages.json").write_text(json.dumps(snapshots, ensure_ascii=False, indent=2))
            db = ws / "data/state/runtime-spine.db"
            if db.exists():
                with sqlite3.connect(db) as conn:
                    jobs = conn.execute("SELECT job_id,state_json FROM general_work_projection").fetchall()
                    result["mission_count"] = conn.execute("SELECT count(*) FROM mission_projection").fetchone()[0]
                if jobs:
                    states = [json.loads(row[1]) for row in jobs]
                    result["jobs"] = [{"job_id": row["job_id"], "status": row["status"]} for row in states]
                    if any(row["status"] in {"COMPLETED", "FAILED"} for row in states):
                        result["file_content"] = (ws / "notes/result.txt").read_text() if (ws / "notes/result.txt").exists() else None
                        result["status"] = "PASS" if result["mission_count"] == 0 and result["file_content"] == "green apple" and all(row["status"] == "COMPLETED" for row in states) else "FAIL"
                        break
            if loop.poll() is not None: raise RuntimeError("PRODUCT_CONTROL_LOOP_EXITED")
            time.sleep(1)
        identities = set(); receipts = []
        for snapshot in snapshots:
            for message in snapshot["messages"]:
                info = message.get("info", {})
                if info.get("role") == "assistant": identities.add((info.get("providerID"), info.get("modelID")))
                for part in message.get("parts", []):
                    if part.get("type") == "tool": receipts.append({"session_id": snapshot["session_id"], "call_id": part.get("callID"), "tool": part.get("tool"), "state": part.get("state", {}).get("status"), "action": part.get("state", {}).get("input", {}).get("action")})
        result["model_identity"] = sorted([list(v) for v in identities if all(v)])
        result["actual_tool_calls"] = receipts
        result["distinct_worker_session"] = any(r["tool"] == "aitest_general_worker" and r["session_id"] != director for r in receipts)
        if not result["model_identity"] or not result["distinct_worker_session"]: result["status"] = "FAIL"
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)[:1000]
    finally:
        if server and server.poll() is None:
            try:
                for s in client.request("GET", "/session"): client.request("POST", "/session/" + s["id"] + "/abort", {})
            except Exception: pass
        for proc in (loop, server):
            if proc and proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({k: v for k, v in result.items() if k != "source_snapshot"}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
