from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve()
WORKSPACE = HERE.parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(HERE.parent))

from aitest_runtime import control_loop
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g4.service import G4RealExecutionService
from aitest_runtime.r3_e2.contracts import BrowserContextRef
from test_g3_testing_intelligence_product_path import binding, intake_request
from test_g4_background_auto_resume_wave2 import BrowserPort, seed_g3, task


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="g4-closure-background-") as td:
        root = Path(td)
        db = root / "runtime-spine.db"
        os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
        os.environ["AITEST_RUNTIME_SPINE_DB"] = str(db)
        runtime = create_canonical_runtime(root, db_path=db)
        provider = FakeOpenCodeSessionProvider(root)
        orch = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        mission_id = orch.start_test(intake_request())["intake"]["intake"]["mission_id"]
        case_fact, strategy_id = seed_g3(runtime, mission_id)
        plan = orch.propose_plan(mission_id, {"objective": "package background auto resume", "tasks": [task()], "dependencies": []})
        attempt = binding(plan["next"])
        attempt["root_attempt_id"] = str(plan["next"]["attempt"]["root_attempt_id"])
        ref = BrowserContextRef("browser-background", "epoch-background", canonical_sha256({"ctx": "background"}), "AI", "2026-09-03T03:00:00Z")
        browser = BrowserPort(ref)
        g4 = G4RealExecutionService(runtime, orchestration=orch, browser_provider=browser)
        g4.create_goal(mission_id, {
            "goal_id": "goal-background",
            "project_id": "PFC",
            "release_id": "R2",
            "affected_applications": ["cfg-data"],
            "affected_application_target_versions": {"cfg-data": "V2"},
            "coverage_policy": {"target_pct": 95},
        })
        g4.create_batch(mission_id, {
            "batch_id": "batch-background",
            "goal_id": "goal-background",
            "case_refs": [case_fact["fact_id"]],
            "strategy_version_id": strategy_id,
            "target_application": "cfg-data",
            "status": "RUNNING",
        })
        g4.record_cursor(mission_id, {
            "task_id": attempt["task_id"],
            "attempt_id": attempt["attempt_id"],
            "case_id": "TC-AUTO",
            "case_version": "TC-AUTO:v1",
            "case_spec_fact_id": case_fact["fact_id"],
            "execution_batch_id": "batch-background",
            "current_step_index": 2,
            "completed_step_ids": ["prepare", "navigate"],
            "pending_step_id": "verify-auth",
            "last_safe_checkpoint": "before-auth",
        })
        opened = g4.request_human_takeover(mission_id, {
            **attempt,
            "human_gate_id": "gate-background",
            "takeover_id": "takeover-background",
            "case_id": "TC-AUTO",
            "browser_context_ref": ref.to_dict(),
            "required_action": "complete protected authentication",
            "reason": "AUTH_REQUIRED",
            "allowed_scope": {"environment": "TEST"},
            "resume_mode": "AUTO",
            "resume_condition": {"authenticated": True, "page": "protected"},
            "goal_id": "goal-background",
            "batch_id": "batch-background",
            "mandatory_for_goal": True,
        })
        checks["auto_takeover_yields_with_human_lease"] = opened["status"] == "WAITING_HUMAN" and browser.owner == "HUMAN"

        old_default = control_loop.default_g21_service
        old_bundle = control_loop.load_provider_bundle
        control_loop.default_g21_service = lambda _runtime, _root: SimpleNamespace(
            supervise_once=lambda: {"status": "PASS", "truth_source": "R1_EVENT_STREAM", "fixture": "g2.1-supervision"}
        )
        control_loop.load_provider_bundle = lambda _root, _profile: SimpleNamespace(
            browser_provider=browser,
            capability_executors={},
            resume_condition_verifier=browser,
        )
        try:
            waiting_tick = control_loop.run_tick(root)
            checks["package_control_loop_observer_waits_when_runtime_verification_fails"] = waiting_tick["g4_human_gate_background"]["status"] == "WAITING" and browser.owner == "HUMAN"
            browser.resume_ready = True
            resumed_tick = control_loop.run_tick(root)
        finally:
            control_loop.default_g21_service = old_default
            control_loop.load_provider_bundle = old_bundle

        background = resumed_tick["g4_human_gate_background"]
        checks["package_control_loop_resumes_auto_gate_without_g4_objective_tick"] = background["status"] == "RESUMED" and background["resumed_gate_refs"] == ["gate-background"] and background["objective_control_tick_dependency"] is False
        checks["background_observer_is_non_llm_and_package_owned"] = background["non_llm"] is True and background["package_owned"] is True and browser.owner == "AI"
        checks["background_function_has_no_objective_controller_dependency"] = "TestObjectiveController" not in inspect.getsource(control_loop._g4_background_human_gate_tick)
        checks["long_running_control_loop_calls_package_run_tick"] = "value = run_tick(root)" in inspect.getsource(control_loop.main)

        restarted = create_canonical_runtime(root, db_path=db)
        human_state = restarted.replay_composed(mission_id).extension_state("r2_6_human_gate")
        checks["background_auto_resolves_canonical_r26_gate"] = human_state.gate("gate-background").status == "RESOLVED"
        resumed_cursor = G4RealExecutionService(restarted, browser_provider=browser).recover_cursor(mission_id, root_attempt_id=attempt["root_attempt_id"])
        checks["background_auto_resumes_same_root_attempt_cursor"] = resumed_cursor["payload"]["root_attempt_id"] == attempt["root_attempt_id"] and resumed_cursor["payload"]["pending_step_id"] == "verify-auth"
        checks["projection_verifies"] = restarted.verify_projection(mission_id).get("ok") is True

    failed = [key for key, value in checks.items() if not value]
    print(json.dumps({"status": "PASS" if not failed else "FAIL", "passed": sum(checks.values()), "total": len(checks), "failed": failed, "checks": checks}, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
