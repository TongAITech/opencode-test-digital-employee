"""C3 unattended Replanner -> semantic PlanRevision -> next Task gate v2.

Only model-owned Planner tool calls are supplied. Runtime/background Control Loop
must own scheduling and continuation. No user continue, Scheduler tool call,
CONTROL tick, or manual Agent observation is issued by this gate.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIELD_TESTS = REPO_ROOT / "workspace-template" / ".pfc-internal-field-validation" / "tests"
RUNTIME_ROOT = REPO_ROOT / "workspace-template" / "ai-test" / "runtime"
sys.path.insert(0, str(FIELD_TESTS))
sys.path.insert(0, str(RUNTIME_ROOT))

import test_g2_1_background_control_loop_subprocess as bg


def diagnosis_replan() -> dict[str, object]:
    return {
        "objective": "replace stalled execution with a bounded diagnosis task",
        "tasks": [{
            "task_key": "diagnose-stall",
            "intent": "diagnose why the prior execution made no durable business progress",
            "acceptance_criteria": [{"id": "diagnosed", "description": "produce bounded diagnosis evidence"}],
            "routing": {
                "role": "DIAGNOSIS",
                "required_capabilities": ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"],
                "isolation_policy": "DEDICATED_TASK_SESSION",
                "parallelism_policy": "SERIAL",
            },
        }],
        "dependencies": [],
    }


def director_status(env: dict[str, str], primary: str, mission_id: str, label: str) -> dict[str, object]:
    payload = {"mission_id": mission_id}
    bg.bind_host_tool(env, session_id=primary, agent="aitest-director", tool="aitest_director",
                      action="status", payload=payload, label=label)
    return bg.run(env, "DIRECTOR", "status", payload)


def unique_phase_session(status: dict[str, object], phase: str) -> str:
    sessions = status.get("core", {}).get("sessions", {})
    found = [
        sid for sid, item in sessions.items()
        if isinstance(item, dict) and item.get("status") == "OPEN"
        and isinstance(item.get("attributes"), dict)
        and item["attributes"].get("phase") == phase
    ] if isinstance(sessions, dict) else []
    if len(found) != 1:
        raise AssertionError(f"C3_{phase}_SESSION_NOT_UNIQUE:" + json.dumps(status, ensure_ascii=False, sort_keys=True))
    return str(found[0])


def open_revision(status: dict[str, object]) -> str | None:
    work_graph = status.get("work_graph")
    plans = work_graph.get("plans") if isinstance(work_graph, dict) else None
    if not isinstance(plans, dict):
        return None
    opened = [item for item in plans.values() if isinstance(item, dict) and item.get("lifecycle_state") == "OPEN"]
    if len(opened) != 1:
        return None
    value = opened[0].get("current_revision_id")
    return str(value) if isinstance(value, str) and value else None


def main() -> int:
    checks: dict[str, bool] = {}
    diagnostics: dict[str, object] = {}
    bg.Stub.sessions = {}; bg.Stub.messages = {}; bg.Stub.requests = []; bg.Stub.host_messages = {}; bg.Stub.counter = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), bg.Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    control: subprocess.Popen[str] | None = None
    tmp = None
    try:
        tmp = tempfile.TemporaryDirectory(prefix="pfc-c3-handoff-v2-")
        td = tmp.name
        root = Path(td)
        spine = root / "durable/state/runtime-spine.db"; spine.parent.mkdir(parents=True)
        heartbeat = root / "durable/state/control-loop-heartbeat.json"
        env = dict(os.environ)
        env.update({
            "AITEST_WORKSPACE_ROOT": str(root), "AITEST_RUNTIME_SPINE_DB": str(spine),
            "AITEST_OPENCODE_ENDPOINT": f"http://127.0.0.1:{server.server_port}",
            "AITEST_CONTROL_LOOP_HEARTBEAT_PATH": str(heartbeat),
            "PYTHONPATH": str(RUNTIME_ROOT) + os.pathsep + str(FIELD_TESTS)
                + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""),
        })
        from aitest_runtime.autonomous_orchestration import DirectoryScopedOpenCodeSessionProvider
        from aitest_runtime.canonical_runtime import create_canonical_runtime
        from aitest_runtime.primary_sessions import PrimarySessionOwner

        runtime = create_canonical_runtime(root, db_path=spine)
        provider = DirectoryScopedOpenCodeSessionProvider(root, base_url=env["AITEST_OPENCODE_ENDPOINT"])
        primary = str(PrimarySessionOwner(runtime, root, provider).ensure_current()["session_id"])

        bg.Stub.host_messages, host_env, start_payload = bg.host_start_turn(
            bg.request()["scope"], session=primary, message="c3-handoff-v2-start")
        env.update(host_env)
        started = bg.run(env, "DIRECTOR", "start_test", start_payload)
        operations = started.get("operations")
        if (started.get("status") != "INTERACTION_PROCESSED" or not isinstance(operations, list)
                or len(operations) != 1 or operations[0].get("status") != "DISPATCHED"
                or operations[0].get("effect") != "TEST_DISPATCH"
                or not isinstance(operations[0].get("subject"), dict)
                or operations[0]["subject"].get("subject_kind") != "MISSION"
                or not isinstance(operations[0].get("result"), dict)
                or operations[0]["result"].get("status") != "PLANNER_SESSION_OPEN"):
            raise AssertionError("C3_HANDOFF_START_CONTRACT_INVALID:" + json.dumps(started, ensure_ascii=False, sort_keys=True))
        mission_id = str(operations[0]["subject"]["subject_id"])
        if operations[0]["result"].get("mission_id") != mission_id:
            raise AssertionError("C3_HANDOFF_START_MISSION_IDENTITY_MISMATCH")

        initial_status = director_status(env, primary, mission_id, "c3-handoff-v2-start-status")
        planner_id = unique_phase_session(initial_status, "PLANNING")
        initial_payload = {"mission_id": mission_id, "proposal": bg.proposal()}
        bg.bind_host_tool(env, session_id=planner_id, agent="aitest-planner", tool="aitest_planner",
                          action="propose_plan", payload=initial_payload, label="c3-handoff-v2-initial-plan")
        initial = bg.run(env, "PLANNER", "propose_plan", initial_payload)
        worker = initial.get("next")
        if not isinstance(worker, dict) or not isinstance(worker.get("external_session"), dict):
            raise AssertionError("C3_HANDOFF_INITIAL_WORKER_REQUIRED:" + json.dumps(initial, ensure_ascii=False, sort_keys=True))

        control = subprocess.Popen(
            bg.module_command("aitest_runtime.control_loop", "--workspace-root", str(root), "--interval", "0.1"),
            cwd=str(root), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        threading.Thread(target=bg.drain_background_output, args=(control.stdout,), daemon=True).start()

        replanning_status = None; active_replan = None; status_call = 0
        deadline = time.time() + 20
        while time.time() < deadline:
            status_call += 1
            value = director_status(env, primary, mission_id, f"c3-handoff-v2-wait-{status_call}")
            records = value.get("session_control", {}).get("progress_records", [])
            candidates = [x for x in records if isinstance(x, dict) and x.get("phase") == "REPLANNING" and x.get("replan_session_id")] if isinstance(records, list) else []
            if candidates:
                candidate = candidates[-1]
                replanner_id = str(candidate.get("replan_session_id") or "")
                provisions = value.get("session_control", {}).get("provisions", [])
                bound = any(
                    isinstance(item, dict)
                    and item.get("external_session_id") == replanner_id
                    and item.get("status") == "BOUND"
                    and item.get("phase") in {"REPLANNING", "REPLANNING_ROTATION"}
                    for item in provisions
                ) if isinstance(provisions, list) else False
                host_ready = (
                    replanner_id in bg.Stub.sessions
                    and len(bg.Stub.messages.get(replanner_id, [])) >= 1
                )
                if bound and host_ready:
                    replanning_status, active_replan = value, candidate; break
            time.sleep(0.1)
        checks["background_reaches_replanner_without_user_continue"] = active_replan is not None
        if active_replan is None or replanning_status is None:
            diagnostics["replanner_timeout"] = {
                "heartbeat": json.loads(heartbeat.read_text(encoding="utf-8")) if heartbeat.is_file() else {},
            }
        else:
            progress_id = str(active_replan["progress_id"])
            replanner_id = str(active_replan["replan_session_id"])
            stalled_cursor = int(active_replan["business_cursor"])
            before_revision = open_revision(replanning_status)
            replan_payload = {"mission_id": mission_id, "proposal": diagnosis_replan()}
            bg.bind_host_tool(env, session_id=replanner_id, agent="aitest-planner", tool="aitest_planner",
                              action="propose_plan", payload=replan_payload, label="c3-handoff-v2-replan")
            revised = bg.run(env, "PLANNER", "propose_plan", replan_payload)
            next_task = revised.get("next")
            checks["replanner_host_tool_authors_semantic_plan_revision"] = (
                revised.get("status") == "PASS" and revised.get("semantic_business_progress") is True
                and revised.get("stalled_replan_no_change") is False)
            checks["runtime_handoff_dispatches_diagnosis_without_scheduler_call"] = (
                isinstance(next_task, dict) and isinstance(next_task.get("route"), dict)
                and next_task["route"].get("role") == "DIAGNOSIS"
                and isinstance(next_task.get("external_session"), dict))

            after = director_status(env, primary, mission_id, "c3-handoff-v2-after")
            records = after.get("session_control", {}).get("progress_records", [])
            resolved = next((x for x in records if isinstance(x, dict) and x.get("progress_id") == progress_id), None) if isinstance(records, list) else None
            after_revision = open_revision(after)
            checks["stalled_generation_resolves_on_semantic_revision"] = (
                isinstance(resolved, dict) and resolved.get("phase") == "RESOLVED"
                and before_revision is not None and after_revision is not None and after_revision != before_revision
                and int(after.get("head_seq", 0)) > stalled_cursor)

            if isinstance(next_task, dict) and isinstance(next_task.get("external_session"), dict):
                diagnosis_session = str(next_task["external_session"]["session_id"])
                checks["new_task_remains_same_mission_truth"] = diagnosis_session in bg.Stub.sessions
                auto_continue = False; deadline = time.time() + 8
                while time.time() < deadline:
                    if len(bg.Stub.messages.get(diagnosis_session, [])) >= 2:
                        auto_continue = True; break
                    time.sleep(0.1)
                checks["background_continues_new_task_without_user_or_scheduler"] = auto_continue
            else:
                checks["new_task_remains_same_mission_truth"] = False
                checks["background_continues_new_task_without_user_or_scheduler"] = False
    finally:
        if control is not None:
            control.terminate()
            try: control.wait(timeout=3)
            except subprocess.TimeoutExpired:
                control.kill()
                control.wait(timeout=3)
        if tmp is not None:
            tmp.cleanup()
        server.shutdown(); server.server_close(); thread.join(timeout=2)

    payload = {"status": "PASS" if checks and all(checks.values()) else "FAIL", "checks": checks,
               "diagnostics": diagnostics, "http_requests": len(bg.Stub.requests)}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
