from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
WORKSPACE = HERE.parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(HERE.parent))

from aitest_runtime import product_entry
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.common import now_iso
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g4.service import G4RealExecutionService
from aitest_runtime.r2_6.contracts import OUTCOMES, policy_digest
from aitest_runtime.r3_e2.contracts import BrowserContextRef
from test_g3_testing_intelligence_product_path import binding, intake_request
from test_g4_background_auto_resume_wave2 import BrowserPort, seed_g3, task


def parallel_task(task_key: str) -> dict:
    value = task()
    value["task_key"] = task_key
    value["intent"] = f"execute governed case after browser auth on {task_key}"
    value["routing"] = {**value["routing"], "parallelism_policy": "PARALLEL_SAFE"}
    return value


def open_ambiguous_gate(g4: G4RealExecutionService, mission_id: str, gate_id: str, dispatch: dict) -> None:
    # Use an exact scheduler-produced lineage. Two ambiguity gates must belong to
    # two distinct active lineages in the same Mission; inventing a second gate
    # on one lineage would correctly violate frozen R2.6 concurrency safety.
    attempt = dispatch["attempt"]
    routes = {
        outcome: (("BLOCK",) if outcome == "REJECTED" else ("NONE",))
        for outcome in OUTCOMES
    }
    allowed = ("EXTERNAL_ACTION_COMPLETED",)
    policy_id = "closure-ambiguity-policy"
    g4.human_gates.open_gate({
        "mission_id": mission_id,
        "gate_id": gate_id,
        "plan_id": attempt["plan_id"],
        "plan_revision_id": attempt["plan_revision_id"],
        "task_id": dispatch["task_id"],
        "root_attempt_id": attempt["root_attempt_id"],
        "origin_attempt_id": attempt["attempt_id"],
        "origin_session_id": dispatch["external_session"]["session_id"],
        "gate_kind": "EXTERNAL_ACTION",
        "request_payload": {"action": "ambiguous durable human action", "reason": "CLOSURE_ADVERSARIAL"},
        "response_schema": {"type": "object"},
        "expires_at": None,
        "expiry_policy": "NONE",
        "decision_policy_id": policy_id,
        "decision_policy_version": 1,
        "decision_policy_digest": policy_digest(policy_id, 1, allowed, routes),
        "allowed_outcomes": list(allowed),
        "allowed_routes_by_outcome": {key: list(value) for key, value in routes.items()},
        "request_provenance": {
            "source_ref": f"closure:{gate_id}",
            "source_digest": canonical_sha256({"gate": gate_id}),
            "observed_at": now_iso(),
        },
        "actor": {"type": "SYSTEM", "id": "closure-test"},
    })
    g4._record(
        mission_id,
        "HUMAN_TAKEOVER_REQUEST",
        {
            "human_gate_id": gate_id,
            "resume_mode": "EXPLICIT",
            "status": "HUMAN_CONTROLLED",
            "sensitive_evidence_suppressed": True,
        },
        provenance_refs=(f"r2.6:{gate_id}",),
    )


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="g4-closure-user-turn-") as td:
        root = Path(td)
        db = root / "runtime-spine.db"
        os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
        os.environ["AITEST_RUNTIME_SPINE_DB"] = str(db)
        runtime = create_canonical_runtime(root, db_path=db)
        provider = FakeOpenCodeSessionProvider(root)
        orch = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        mission_id = orch.start_test(intake_request())["intake"]["intake"]["mission_id"]
        case_fact, strategy_id = seed_g3(runtime, mission_id)
        plan = orch.propose_plan(
            mission_id,
            {
                "objective": "explicit user-turn resume",
                "tasks": [parallel_task("AUTO-A"), parallel_task("AUTO-B")],
                "dependencies": [],
            },
        )
        dispatch_a = plan["next"]
        attempt = binding(dispatch_a)
        attempt["root_attempt_id"] = str(dispatch_a["attempt"]["root_attempt_id"])
        ref = BrowserContextRef("browser-explicit", "epoch-explicit", canonical_sha256({"ctx": "explicit"}), "AI", "2026-09-03T02:00:00Z")
        browser = BrowserPort(ref)
        g4 = G4RealExecutionService(runtime, orchestration=orch, browser_provider=browser)
        g4.create_goal(mission_id, {
            "goal_id": "goal-explicit",
            "project_id": "PFC",
            "release_id": "R2",
            "affected_applications": ["cfg-data"],
            "affected_application_target_versions": {"cfg-data": "V2"},
            "coverage_policy": {"target_pct": 95},
        })
        g4.create_batch(mission_id, {
            "batch_id": "batch-explicit",
            "goal_id": "goal-explicit",
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
            "execution_batch_id": "batch-explicit",
            "current_step_index": 2,
            "completed_step_ids": ["prepare", "navigate"],
            "pending_step_id": "verify-auth",
            "last_safe_checkpoint": "before-auth",
        })
        opened = g4.request_human_takeover(mission_id, {
            **attempt,
            "human_gate_id": "gate-explicit",
            "takeover_id": "takeover-explicit",
            "case_id": "TC-AUTO",
            "browser_context_ref": ref.to_dict(),
            "required_action": "complete protected authentication",
            "reason": "AUTH_REQUIRED",
            "allowed_scope": {"environment": "TEST"},
            "resume_mode": "EXPLICIT",
            "resume_condition": {"authenticated": True, "page": "protected"},
            "goal_id": "goal-explicit",
            "batch_id": "batch-explicit",
            "mandatory_for_goal": True,
        })
        checks["takeover_tool_call_yields_and_can_end_ai_turn"] = opened["status"] == "WAITING_HUMAN" and opened["ai_turn"] == "YIELD" and opened["blocking_tool_call"] is False
        checks["human_control_keeps_chat_and_observer_enabled"] = opened["chat_input"] == "ENABLED" and opened["browser_observer"] == "ENABLED" and opened["ai_browser_actuation"] == "DISABLED" and opened["new_user_turn_required"] is True
        checks["takeover_transfers_ai_to_human"] = browser.owner == "HUMAN"

        not_ready = g4.resolve_human_gate_user_turn(mission_id, {"user_text": "完成", "actor_id": "tester"})
        human_state = runtime.replay_composed(mission_id).extension_state("r2_6_human_gate")
        checks["new_user_turn_enters_request_to_verify_path"] = not_ready["intent"] == "REQUEST_TO_VERIFY_COMPLETION" and not_ready["completion_authority"] == "BROWSER_RUNTIME_FRESH_VERIFICATION"
        checks["completion_text_is_not_authority_when_browser_not_ready"] = not_ready["status"] == "WAITING_HUMAN" and not_ready["verification"] == "NOT_YET_COMPLETE" and human_state.gate("gate-explicit").status == "PENDING" and browser.owner == "HUMAN"
        resume_request = g4.state(mission_id).latest("HUMAN_GATE_USER_TURN_RESUME_REQUEST")
        checks["resolver_uses_r1_and_never_persists_raw_user_text"] = resume_request is not None and resume_request.payload["raw_user_text_persisted"] is False and resume_request.payload["user_text_authoritative"] is False and not_ready["conversation_history_dependency"] is False

        browser.resume_ready = True
        # Product-path call creates a fresh Runtime/service internally. This is the
        # exact allowed OpenCode 1.18.3 fallback: Primary Director -> deterministic resolver.
        product_entry._G4_BROWSER_PROVIDER = browser
        try:
            resumed = product_entry.g4_command("DIRECTOR", "human_gate_user_turn_resume", {
                "mission_id": mission_id,
                "user_text": "完成",
                "actor_id": "tester-new-user-turn",
            })
        finally:
            product_entry._G4_BROWSER_PROVIDER = None
        restarted = create_canonical_runtime(root, db_path=db)
        restarted_human = restarted.replay_composed(mission_id).extension_state("r2_6_human_gate")
        checks["product_director_new_user_turn_resumes_after_fresh_verification"] = resumed["status"] == "RESUME_SAFE" and resumed["completion_authority"] == "BROWSER_RUNTIME_FRESH_VERIFICATION"
        checks["canonical_r26_resolves_only_after_runtime_verification"] = restarted_human.gate("gate-explicit").status == "RESOLVED"
        checks["successful_resume_transfers_human_back_to_ai"] = browser.owner == "AI"
        g4_restart = G4RealExecutionService(restarted, browser_provider=browser)
        cursor = g4_restart.recover_cursor(mission_id, root_attempt_id=attempt["root_attempt_id"])
        checks["same_root_attempt_and_step_cursor_resume"] = cursor["payload"]["root_attempt_id"] == attempt["root_attempt_id"] and cursor["payload"]["pending_step_id"] == "verify-auth" and cursor["payload"]["current_step_index"] == 2
        checks["same_browser_context_is_preserved"] = browser._ref().browser_context_id_or_epoch == ref.browser_context_id_or_epoch and browser._ref().context_binding_digest == ref.context_binding_digest
        checks["runtime_rebuild_replays_resume_truth_from_r1"] = restarted.verify_projection(mission_id).get("ok") is True and g4_restart.state(mission_id).latest("HUMAN_GATE_USER_TURN_RESUME_REQUEST") is not None
        checks["user_completion_phrase_not_present_in_r1_storage_bytes"] = "完成".encode("utf-8") not in db.read_bytes()

        # Adversarial R1 truth: same Mission, two real scheduler lineages, two
        # compatible pending gates. Resolver must fail closed instead of guessing.
        open_ambiguous_gate(g4_restart, mission_id, "gate-ambiguous-a", dispatch_a)
        orch_restart = G21AutonomousOrchestrationService(restarted, root, session_provider=provider)
        dispatch_b = orch_restart.dispatch_next(mission_id)
        open_ambiguous_gate(g4_restart, mission_id, "gate-ambiguous-b", dispatch_b)
        ambiguous = g4_restart.resolve_human_gate_user_turn(mission_id, {"user_text": "好了"})
        rebuilt_human = restarted.replay_composed(mission_id).extension_state("r2_6_human_gate")
        checks["multiple_compatible_pending_gates_fail_closed"] = dispatch_b["status"] == "DISPATCHED" and dispatch_b["task_id"] != dispatch_a["task_id"] and ambiguous["status"] == "CLARIFICATION_REQUIRED" and ambiguous["reason"] == "MULTIPLE_COMPATIBLE_PENDING_HUMAN_GATES" and set(ambiguous["compatible_gate_refs"]) == {"gate-ambiguous-a", "gate-ambiguous-b"}
        checks["ambiguity_does_not_resolve_any_gate"] = rebuilt_human.gate("gate-ambiguous-a").status == "PENDING" and rebuilt_human.gate("gate-ambiguous-b").status == "PENDING"

    failed = [key for key, value in checks.items() if not value]
    print(json.dumps({"status": "PASS" if not failed else "FAIL", "passed": sum(checks.values()), "total": len(checks), "failed": failed, "checks": checks}, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
