from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
WORKSPACE = HERE.parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(HERE.parent))

from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g4.service import G4RealExecutionService
from aitest_runtime.r3_e2.contracts import BrowserContextRef
from test_g3_testing_intelligence_product_path import binding, intake_request
from test_g4_background_auto_resume_wave2 import BrowserPort, seed_g3
from test_g4_explicit_user_turn_resume_closure import open_ambiguous_gate, parallel_task

DIRECTOR = (WORKSPACE / ".opencode" / "agents" / "aitest-director.md").read_text(encoding="utf-8")
TOOL_PATH = WORKSPACE / ".opencode" / "tools" / "aitest_human_gate.ts"
TOOL = TOOL_PATH.read_text(encoding="utf-8")
ENTRY = (WORKSPACE / "ai-test" / "runtime" / "aitest_runtime" / "product_entry.py").read_text(encoding="utf-8")
RUNTIME_RESOLVER = (WORKSPACE / "ai-test" / "runtime" / "aitest_runtime" / "g4" / "service_r2_4.py").read_text(encoding="utf-8")
PROBE = (WORKSPACE.parent / "docs" / "reviews" / "OPENCODE_1_18_3_USER_TURN_CAPABILITY_PROBE.md").read_text(encoding="utf-8") if (WORKSPACE.parent / "docs" / "reviews" / "OPENCODE_1_18_3_USER_TURN_CAPABILITY_PROBE.md").is_file() else ""


def write_browser_factory(path: Path) -> None:
    path.write_text(
        '''from __future__ import annotations
import json, os
from pathlib import Path
from types import SimpleNamespace
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.r3_e2.contracts import BrowserContextRef

STATE = Path(os.environ["AITEST_BROWSER_STATE"])

def _load():
    return json.loads(STATE.read_text(encoding="utf-8"))

def _save(value):
    STATE.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

class Browser:
    def _ref(self, ref):
        state = _load()
        return BrowserContextRef(ref.browser_session_id, ref.browser_context_id_or_epoch, ref.context_binding_digest, state["owner"], ref.observed_at)
    def inspect_context(self, ref):
        return self._ref(ref)
    def inspect_lease(self, ref):
        return _load()["owner"]
    def transfer_lease(self, ref, *, from_owner, to_owner):
        state = _load()
        if state["owner"] != from_owner:
            raise AssertionError("LEASE_OWNER:" + state["owner"])
        state["owner"] = to_owner
        state["handoffs"] = int(state.get("handoffs", 0)) + 1
        _save(state)
        return SimpleNamespace(to_dict=lambda: {"from": from_owner, "to": to_owner, "handoff": state["handoffs"]})
    def verify_resume_condition(self, *, mission_id, browser_context_ref, resume_condition, completion_mode):
        state = _load()
        ready = bool(state.get("ready"))
        return {
            "resume_safe": ready,
            "auth_state": "AUTHENTICATED" if ready else "UNAUTHENTICATED",
            "page_identity": "MATCHED",
            "business_state": "RESUME_SAFE" if ready else "UNCHANGED",
            "source_ref": "fixture:opencode-product-surface-browser",
            "evidence_digest": canonical_sha256({"mission_id": mission_id, "ready": ready, "condition": dict(resume_condition)}),
            "observed_at": "2026-09-03T04:30:00Z",
        }

def factory(root=None, profile=None):
    return {"browser_provider": Browser()}
''',
        encoding="utf-8",
    )


def call_product(root: Path, module_dir: Path, state_file: Path, mission_id: str, user_text: str) -> tuple[int, dict]:
    env = os.environ.copy()
    env["AITEST_WORKSPACE_ROOT"] = str(root)
    env["AITEST_RUNTIME_SPINE_DB"] = str(root / "runtime-spine.db")
    env["AITEST_G4_PROVIDER_FACTORY"] = "product_surface_browser:factory"
    env["AITEST_BROWSER_STATE"] = str(state_file)
    env["PYTHONPATH"] = str(module_dir) + os.pathsep + str(RUNTIME) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    payload = {"mission_id": mission_id, "user_text": user_text, "actor_id": "opencode-new-user-turn"}
    proc = subprocess.run(
        [sys.executable, "-m", "aitest_runtime.product_entry", "g4", "--role", "DIRECTOR", "--action", "human_gate_user_turn_resume", "--payload", json.dumps(payload, ensure_ascii=False)],
        cwd=str(WORKSPACE), env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=60,
    )
    try:
        value = json.loads(proc.stdout)
    except Exception:
        value = {"stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
    return proc.returncode, value


def main() -> int:
    checks: dict[str, bool] = {}

    checks["01_primary_director_has_official_humangate_tool_permission"] = "aitest_human_gate_resume: allow" in DIRECTOR
    checks["02_primary_director_routes_completion_intent_deterministically"] = all(token in DIRECTOR for token in ("完成", "好了", "已登录", "操作完成", "REQUEST_TO_VERIFY_COMPLETION", "MUST call the official `aitest_human_gate_resume` tool"))
    checks["03_director_preserves_r1_gate_selection_and_ambiguity_fail_closed"] = all(token in DIRECTOR for token in ("exact compatible gate selection belongs to the deterministic Runtime resolver reading R1", "CLARIFICATION_REQUIRED", "Never auto-select one"))
    checks["04_director_requires_fresh_browser_verification_before_r26_resume"] = all(token in DIRECTOR for token in ("WAITING_HUMAN", "R2.6", "HUMAN→AI", "same root Attempt/StepCursor", "Conversation text is never completion truth"))
    checks["05_opencode_1183_pre_llm_short_circuit_remains_not_proven"] = "Stable supported pre-LLM short-circuit interception is `NOT_PROVEN`" in DIRECTOR and "STABLE_PRE_LLM_SHORT_CIRCUIT_INTERCEPTION = NOT_PROVEN" in PROBE
    checks["06_official_tool_contract_exposes_human_gate_user_turn_resume"] = TOOL_PATH.is_file() and 'const ACTION = "human_gate_user_turn_resume"' in TOOL and "REQUEST_TO_VERIFY_COMPLETION" in TOOL and "Multiple compatible gates fail closed" in TOOL
    checks["07_tool_to_product_entry_to_runtime_resolver_chain_is_explicit"] = all(token in TOOL for token in ('"aitest_runtime.product_entry"', '"g4"', '"DIRECTOR"', '"--action"', "ACTION")) and '"DIRECTOR": {"status", "create_goal", "control_tick", "coverage_from_g3", "blocker_gap", "risk_acceptance", "record_iteration", "human_gate_user_turn_resume"}' in ENTRY and "resolve_human_gate_user_turn" in ENTRY and "def resolve_human_gate_user_turn" in RUNTIME_RESOLVER

    with tempfile.TemporaryDirectory(prefix="g4-opencode-product-surface-") as td:
        root = Path(td) / "workspace"
        root.mkdir(parents=True)
        db = root / "runtime-spine.db"
        os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
        os.environ["AITEST_RUNTIME_SPINE_DB"] = str(db)
        runtime = create_canonical_runtime(root, db_path=db)
        session_provider = FakeOpenCodeSessionProvider(root)
        orch = G21AutonomousOrchestrationService(runtime, root, session_provider=session_provider)
        mission_id = orch.start_test(intake_request())["intake"]["intake"]["mission_id"]
        case_fact, strategy_id = seed_g3(runtime, mission_id)
        plan = orch.propose_plan(mission_id, {"objective": "OpenCode HumanGate product surface", "tasks": [parallel_task("SURFACE-A"), parallel_task("SURFACE-B")], "dependencies": []})
        dispatch_a = plan["next"]
        attempt = binding(dispatch_a)
        attempt["root_attempt_id"] = str(dispatch_a["attempt"]["root_attempt_id"])
        ref = BrowserContextRef("browser-product-surface", "epoch-product-surface", canonical_sha256({"ctx": "product-surface"}), "AI", "2026-09-03T04:20:00Z")
        browser = BrowserPort(ref)
        g4 = G4RealExecutionService(runtime, orchestration=orch, browser_provider=browser)
        g4.create_goal(mission_id, {"goal_id": "goal-product-surface", "project_id": "PFC", "release_id": "R2", "affected_applications": ["cfg-data"], "affected_application_target_versions": {"cfg-data": "V2"}, "coverage_policy": {"target_pct": 95}})
        g4.create_batch(mission_id, {"batch_id": "batch-product-surface", "goal_id": "goal-product-surface", "case_refs": [case_fact["fact_id"]], "strategy_version_id": strategy_id, "target_application": "cfg-data", "status": "RUNNING"})
        g4.record_cursor(mission_id, {"task_id": attempt["task_id"], "attempt_id": attempt["attempt_id"], "case_id": "TC-AUTO", "case_version": "TC-AUTO:v1", "case_spec_fact_id": case_fact["fact_id"], "execution_batch_id": "batch-product-surface", "current_step_index": 2, "completed_step_ids": ["prepare", "navigate"], "pending_step_id": "verify-auth", "last_safe_checkpoint": "before-auth"})
        opened = g4.request_human_takeover(mission_id, {**attempt, "human_gate_id": "gate-product-surface", "takeover_id": "takeover-product-surface", "case_id": "TC-AUTO", "browser_context_ref": ref.to_dict(), "required_action": "complete protected authentication", "reason": "AUTH_REQUIRED", "allowed_scope": {"environment": "TEST"}, "resume_mode": "EXPLICIT", "resume_condition": {"authenticated": True, "page": "protected"}, "goal_id": "goal-product-surface", "batch_id": "batch-product-surface", "mandatory_for_goal": True})
        checks["08_takeover_yields_openchat_before_new_user_turn"] = opened["status"] == "WAITING_HUMAN" and opened["ai_turn"] == "YIELD" and opened["blocking_tool_call"] is False and opened["chat_input"] == "ENABLED" and browser.owner == "HUMAN"

        module_dir = Path(td) / "provider"
        module_dir.mkdir()
        write_browser_factory(module_dir / "product_surface_browser.py")
        state_file = Path(td) / "browser-state.json"
        state_file.write_text(json.dumps({"owner": "HUMAN", "ready": False, "handoffs": 1}), encoding="utf-8")

        code_wait, waiting = call_product(root, module_dir, state_file, mission_id, "完成")
        pending_runtime = create_canonical_runtime(root, db_path=db)
        pending_human = pending_runtime.replay_composed(mission_id).extension_state("r2_6_human_gate")
        checks["09_new_user_turn_through_product_cli_browser_fail_keeps_gate_pending"] = code_wait == 0 and waiting.get("status") == "WAITING_HUMAN" and waiting.get("intent") == "REQUEST_TO_VERIFY_COMPLETION" and pending_human.gate("gate-product-surface").status == "PENDING" and json.loads(state_file.read_text(encoding="utf-8"))["owner"] == "HUMAN"

        state = json.loads(state_file.read_text(encoding="utf-8")); state["ready"] = True; state_file.write_text(json.dumps(state), encoding="utf-8")
        code_resume, resumed = call_product(root, module_dir, state_file, mission_id, "完成")
        restarted = create_canonical_runtime(root, db_path=db)
        restarted_human = restarted.replay_composed(mission_id).extension_state("r2_6_human_gate")
        g4_restart = G4RealExecutionService(restarted)
        cursor = g4_restart.recover_cursor(mission_id, root_attempt_id=attempt["root_attempt_id"])
        browser_state = json.loads(state_file.read_text(encoding="utf-8"))
        checks["10_product_cli_browser_pass_resolves_r26_and_human_to_ai"] = code_resume == 0 and resumed.get("status") == "RESUME_SAFE" and restarted_human.gate("gate-product-surface").status == "RESOLVED" and browser_state["owner"] == "AI" and int(browser_state.get("handoffs", 0)) >= 2
        checks["11_product_cli_resume_preserves_same_root_attempt_and_step_cursor"] = cursor["payload"]["root_attempt_id"] == attempt["root_attempt_id"] and cursor["payload"]["pending_step_id"] == "verify-auth" and cursor["payload"]["current_step_index"] == 2 and restarted.verify_projection(mission_id).get("ok") is True

        orch_restart = G21AutonomousOrchestrationService(restarted, root, session_provider=session_provider)
        open_ambiguous_gate(g4_restart, mission_id, "gate-product-ambiguous-a", dispatch_a)
        dispatch_b = orch_restart.dispatch_next(mission_id)
        open_ambiguous_gate(g4_restart, mission_id, "gate-product-ambiguous-b", dispatch_b)
        code_amb, ambiguous = call_product(root, module_dir, state_file, mission_id, "好了")
        final_runtime = create_canonical_runtime(root, db_path=db)
        final_human = final_runtime.replay_composed(mission_id).extension_state("r2_6_human_gate")
        checks["12_product_cli_multiple_compatible_gates_fail_closed"] = code_amb == 0 and ambiguous.get("status") == "CLARIFICATION_REQUIRED" and ambiguous.get("reason") == "MULTIPLE_COMPATIBLE_PENDING_HUMAN_GATES" and set(ambiguous.get("compatible_gate_refs") or []) == {"gate-product-ambiguous-a", "gate-product-ambiguous-b"} and final_human.gate("gate-product-ambiguous-a").status == "PENDING" and final_human.gate("gate-product-ambiguous-b").status == "PENDING"

    failed = [name for name, ok in checks.items() if not ok]
    result = {"status": "PASS" if not failed else "FAIL", "passed": sum(bool(v) for v in checks.values()), "total": len(checks), "failed": failed, "checks": checks, "product_path": "PRIMARY_DIRECTOR -> OFFICIAL_OPENCODE_TOOL -> PRODUCT_ENTRY_CLI -> RUNTIME_RESOLVER", "pre_llm_short_circuit": "NOT_PROVEN"}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
