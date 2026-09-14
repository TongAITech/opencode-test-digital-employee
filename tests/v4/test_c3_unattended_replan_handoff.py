"""C3 unattended Replanner -> PlanRevision -> next Task product-path gate.

This gate composes the existing Windows HTTP Host fixture with the current
product entry and a separate background Control Loop.  The test supplies only
model-owned tool calls (initial Planner proposal and later Replanner proposal).
It never calls Scheduler, CONTROL/control_tick, Director/continue_test, or an
Agent observation action.  Runtime must carry the same Mission from an idle
worker into Replanning, accept a semantic PlanRevision, resolve the stalled
generation, dispatch the new Diagnosis Task, and continue waking it in the
background.

This is construction/Windows evidence, not a real-model or bank-field claim.
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
            "acceptance_criteria": [{
                "id": "diagnosed",
                "description": "produce bounded evidence explaining the stalled execution",
            }],
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
    bg.bind_host_tool(
        env, session_id=primary, agent="aitest-director", tool="aitest_director",
        action="status", payload=payload, label=label,
    )
    return bg.run(env, "DIRECTOR", "status", payload)


def main() -> int:
    checks: dict[str, bool] = {}
    diagnostics: dict[str, object] = {}
    bg.Stub.sessions = {}
    bg.Stub.messages = {}
    bg.Stub.requests = []
    bg.Stub.host_messages = {}
    bg.Stub.counter = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), bg.Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    control: subprocess.Popen[str] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="pfc-c3-replan-handoff-") as td:
            root = Path(td)
            spine = root / "durable/state/runtime-spine.db"
            spine.parent.mkdir(parents=True)
            heartbeat = root / "durable/state/control-loop-heartbeat.json"
            env = dict(os.environ)
            env.update({
                "AITEST_WORKSPACE_ROOT": str(root),
                "AITEST_RUNTIME_SPINE_DB": str(spine),
                "AITEST_OPENCODE_ENDPOINT": f"http://127.0.0.1:{server.server_port}",
                "AITEST_CONTROL_LOOP_HEARTBEAT_PATH": str(heartbeat),
                "PYTHONPATH": str(RUNTIME_ROOT) + os.pathsep + str(FIELD_TESTS)
                    + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""),
            })

            from aitest_runtime.autonomous_orchestration import DirectoryScopedOpenCodeSessionProvider
            from aitest_runtime.canonical_runtime import create_canonical_runtime
            from aitest_runtime.primary_sessions import PrimarySessionOwner

            launcher_runtime = create_canonical_runtime(root, db_path=spine)
            launcher_provider = DirectoryScopedOpenCodeSessionProvider(
                root, base_url=env["AITEST_OPENCODE_ENDPOINT"]
            )
            primary = str(PrimarySessionOwner(
                launcher_runtime, root, launcher_provider
            ).ensure_current()["session_id"])

            bg.Stub.host_messages, host_env, start_payload = bg.host_start_turn(
                bg.request()["scope"], session=primary, message="c3-handoff-start"
            )
            env.update(host_env)
            started = bg.run(env, "DIRECTOR", "start_test", start_payload)
            intake = started.get("intake")
            planner_session = started.get("planner_session")
            if (
                started.get("status") != "PLANNING"
                or not isinstance(intake, dict)
                or not isinstance(intake.get("intake"), dict)
                or not isinstance(planner_session, dict)
                or planner_session.get("status") != "PLANNER_SESSION_OPEN"
                or not isinstance(planner_session.get("external_session"), dict)
            ):
                raise AssertionError(
                    "C3_HANDOFF_START_RESULT_INVALID:"
                    + json.dumps(started, ensure_ascii=False, sort_keys=True)
                )
            mission_id = str(intake["intake"]["mission_id"])
            if planner_session.get("mission_id") != mission_id:
                raise AssertionError("C3_HANDOFF_PLANNER_MISSION_IDENTITY_MISMATCH")
            planner_id = str(planner_session["external_session"]["session_id"])

            initial_payload = {"mission_id": mission_id, "proposal": bg.proposal()}
            bg.bind_host_tool(
                env, session_id=planner_id, agent="aitest-planner", tool="aitest_planner",
                action="propose_plan", payload=initial_payload, label="c3-handoff-initial-plan",
            )
            initial = bg.run(env, "PLANNER", "propose_plan", initial_payload)
            worker = initial.get("next")
            if not isinstance(worker, dict) or not isinstance(worker.get("external_session"), dict):
                raise AssertionError("C3_HANDOFF_INITIAL_WORKER_REQUIRED")
            worker_session = str(worker["external_session"]["session_id"])

            # No pressure is injected here.  The background clock must first
            # AUTO_CONTINUE the idle worker and then turn unchanged durable
            # business state into a governed Replanning generation.
            control = subprocess.Popen(
                bg.module_command(
                    "aitest_runtime.control_loop", "--workspace-root", str(root), "--interval", "0.1"
                ),
                cwd=str(root), env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True,
            )
            threading.Thread(target=bg.drain_background_output, args=(control.stdout,), daemon=True).start()

            replanning_status: dict[str, object] | None = None
            active_replan: dict[str, object] | None = None
            deadline = time.time() + 20
            status_call = 0
            while time.time() < deadline:
                status_call += 1
                value = director_status(env, primary, mission_id, f"c3-handoff-wait-replan-{status_call}")
                records = value.get("session_control", {}).get("progress_records", [])
                candidates = [
                    item for item in records
                    if isinstance(item, dict)
                    and item.get("phase") == "REPLANNING"
                    and item.get("replan_session_id")
                ] if isinstance(records, list) else []
                if candidates:
                    replanning_status = value
                    active_replan = candidates[-1]
                    break
                time.sleep(0.1)

            checks["background_reaches_replanner_without_user_continue"] = active_replan is not None
            if active_replan is None or replanning_status is None:
                diagnostics["replanner_timeout"] = {
                    "worker_session": worker_session,
                    "worker_messages": len(bg.Stub.messages.get(worker_session, [])),
                    "heartbeat": json.loads(heartbeat.read_text(encoding="utf-8")) if heartbeat.is_file() else {},
                }
            else:
                progress_id = str(active_replan["progress_id"])
                replanner_id = str(active_replan["replan_session_id"])
                stalled_cursor = int(active_replan["business_cursor"])
                before_plan = replanning_status.get("plan", {})
                before_revision = (
                    before_plan.get("current_revision_id") if isinstance(before_plan, dict) else None
                )

                replan_payload = {"mission_id": mission_id, "proposal": diagnosis_replan()}
                bg.bind_host_tool(
                    env, session_id=replanner_id, agent="aitest-planner", tool="aitest_planner",
                    action="propose_plan", payload=replan_payload, label="c3-handoff-replanner-plan",
                )
                revised = bg.run(env, "PLANNER", "propose_plan", replan_payload)
                next_task = revised.get("next")
                checks["replanner_host_tool_authors_semantic_plan_revision"] = (
                    revised.get("status") == "PASS"
                    and revised.get("semantic_business_progress") is True
                    and revised.get("stalled_replan_no_change") is False
                )
                checks["runtime_handoff_dispatches_diagnosis_without_scheduler_call"] = (
                    isinstance(next_task, dict)
                    and isinstance(next_task.get("route"), dict)
                    and next_task["route"].get("role") == "DIAGNOSIS"
                    and isinstance(next_task.get("external_session"), dict)
                )

                after_revision = director_status(env, primary, mission_id, "c3-handoff-after-revision")
                records = after_revision.get("session_control", {}).get("progress_records", [])
                resolved = next((
                    item for item in records
                    if isinstance(item, dict) and item.get("progress_id") == progress_id
                ), None) if isinstance(records, list) else None
                plan = after_revision.get("plan", {})
                after_revision_id = plan.get("current_revision_id") if isinstance(plan, dict) else None
                checks["stalled_generation_resolves_on_semantic_revision"] = (
                    isinstance(resolved, dict)
                    and resolved.get("phase") == "RESOLVED"
                    and after_revision_id is not None
                    and after_revision_id != before_revision
                    and after_revision.get("head_seq", 0) > stalled_cursor
                )

                if isinstance(next_task, dict) and isinstance(next_task.get("external_session"), dict):
                    diagnosis_session = str(next_task["external_session"]["session_id"])
                    checks["new_task_remains_same_mission_truth"] = (
                        next_task.get("mission_id", mission_id) == mission_id
                        and diagnosis_session in bg.Stub.sessions
                    )
                    # The replan tool call may synchronously perform the canonical
                    # first dispatch.  After the grace interval, only the background
                    # Control Loop may produce AUTO_CONTINUE for this new Task.
                    auto_continue_seen = False
                    deadline = time.time() + 8
                    while time.time() < deadline:
                        messages = bg.Stub.messages.get(diagnosis_session, [])
                        if len(messages) >= 2:
                            auto_continue_seen = True
                            break
                        time.sleep(0.1)
                    checks["background_continues_new_task_without_user_or_scheduler"] = auto_continue_seen
                else:
                    checks["new_task_remains_same_mission_truth"] = False
                    checks["background_continues_new_task_without_user_or_scheduler"] = False
    finally:
        if control is not None:
            control.terminate()
            try:
                control.wait(timeout=3)
            except subprocess.TimeoutExpired:
                control.kill()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    payload = {
        "status": "PASS" if checks and all(checks.values()) else "FAIL",
        "checks": checks,
        "diagnostics": diagnostics,
        "http_requests": len(bg.Stub.requests),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
