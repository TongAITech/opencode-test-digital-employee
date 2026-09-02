from __future__ import annotations

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

from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g3.service import G3TestingIntelligenceService
from aitest_runtime.g4.service import G4RealExecutionService
from aitest_runtime.r3_e2.contracts import BrowserContextRef
from test_g3_testing_intelligence_product_path import binding, intake_request


class BrowserPort:
    def __init__(self, ref: BrowserContextRef) -> None:
        self.identity = ref
        self.owner = "AI"
        self.resume_ready = False
        self.handoffs = 0

    def _ref(self) -> BrowserContextRef:
        return BrowserContextRef(
            self.identity.browser_session_id,
            self.identity.browser_context_id_or_epoch,
            self.identity.context_binding_digest,
            self.owner,
            self.identity.observed_at,
        )

    def inspect_context(self, ref: BrowserContextRef) -> BrowserContextRef:
        expected = (self.identity.browser_session_id, self.identity.browser_context_id_or_epoch, self.identity.context_binding_digest)
        actual = (ref.browser_session_id, ref.browser_context_id_or_epoch, ref.context_binding_digest)
        if expected != actual:
            raise AssertionError("CONTEXT_REPLACED")
        return self._ref()

    def inspect_lease(self, ref: BrowserContextRef) -> str:
        self.inspect_context(ref)
        return self.owner

    def transfer_lease(self, ref: BrowserContextRef, *, from_owner: str, to_owner: str):
        self.inspect_context(ref)
        if self.owner != from_owner:
            raise AssertionError(f"LEASE_OWNER:{self.owner}")
        self.owner = to_owner
        self.handoffs += 1
        return SimpleNamespace(to_dict=lambda: {"handoff": self.handoffs, "from": from_owner, "to": to_owner})

    def verify_resume_condition(self, *, mission_id, browser_context_ref, resume_condition, completion_mode):
        self.inspect_context(browser_context_ref)
        if self.owner != "HUMAN":
            raise AssertionError("HUMAN_LEASE_REQUIRED")
        if not self.resume_ready:
            return {
                "resume_safe": False,
                "auth_state": "UNAUTHENTICATED",
                "page_identity": "MATCHED",
                "business_state": "UNCHANGED",
                "source_ref": "fixture:browser-observation",
                "evidence_digest": canonical_sha256({"ready": False, "mission_id": mission_id}),
                "observed_at": "2026-09-03T01:00:00Z",
            }
        return {
            "resume_safe": True,
            "auth_state": "AUTHENTICATED",
            "page_identity": "MATCHED",
            "business_state": "RESUME_SAFE",
            "source_ref": "fixture:browser-observation",
            "evidence_digest": canonical_sha256({"ready": True, "mission_id": mission_id, "condition": dict(resume_condition)}),
            "observed_at": "2026-09-03T01:01:00Z",
        }


def task() -> dict:
    return {
        "task_key": "AUTO-A",
        "intent": "execute governed case after browser auth",
        "acceptance_criteria": [{"id": "resume", "description": "resume original attempt and cursor"}],
        "routing": {
            "role": "EXECUTOR",
            "required_capabilities": ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"],
            "isolation_policy": "DEDICATED_TASK_SESSION",
            "parallelism_policy": "SERIAL",
        },
    }


def seed_g3(runtime, mission_id: str) -> tuple[dict, str]:
    g3 = G3TestingIntelligenceService(runtime)
    strategy = g3._record(
        mission_id,
        "TEST_STRATEGY_PORTFOLIO",
        {"r3_3_strategy": {"strategy_version_id": "strategy-auto-v1", "strategy_fingerprint": "strategy-auto-fp"}},
        provenance_refs=("test:wave2:auto",),
    )
    case = g3._record(
        mission_id,
        "CASE_SPECIFICATION",
        {"r3_3_case": {"tc_id": "TC-AUTO", "case_version_id": "TC-AUTO:v1", "strategy_version_id": "strategy-auto-v1"}},
        provenance_refs=(strategy["fact_id"],),
    )
    g3._record(
        mission_id,
        "CASE_VALUE_LINK",
        {"case_version_id": "TC-AUTO:v1", "strategy_version_id": "strategy-auto-v1", "value": "AUTO_RESUME"},
        provenance_refs=(case["fact_id"], strategy["fact_id"]),
    )
    return case, "strategy-auto-v1"


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="g4-wave2-auto-") as td:
        root = Path(td)
        db = root / "runtime-spine.db"
        os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
        os.environ["AITEST_RUNTIME_SPINE_DB"] = str(db)
        runtime = create_canonical_runtime(root, db_path=db)
        provider = FakeOpenCodeSessionProvider(root)
        orch = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        mission_id = orch.start_test(intake_request())["intake"]["intake"]["mission_id"]
        case_fact, strategy_id = seed_g3(runtime, mission_id)
        plan = orch.propose_plan(mission_id, {"objective": "auto resume", "tasks": [task()], "dependencies": []})
        attempt = binding(plan["next"])
        ref = BrowserContextRef("browser-auto", "epoch-auto", canonical_sha256({"ctx": "auto"}), "AI", "2026-09-03T01:00:00Z")
        browser = BrowserPort(ref)
        g4 = G4RealExecutionService(runtime, orchestration=orch, browser_provider=browser)
        g4.create_goal(mission_id, {
            "goal_id": "goal-auto",
            "project_id": "PFC",
            "release_id": "R2",
            "affected_applications": ["cfg-data"],
            "affected_application_target_versions": {"cfg-data": "V2"},
            "coverage_policy": {"target_pct": 95},
        })
        g4.create_batch(mission_id, {
            "batch_id": "batch-auto",
            "goal_id": "goal-auto",
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
            "execution_batch_id": "batch-auto",
            "current_step_index": 2,
            "completed_step_ids": ["prepare", "navigate"],
            "pending_step_id": "verify-auth",
            "last_safe_checkpoint": "before-auth",
        })
        opened = g4.request_human_takeover(mission_id, {
            **attempt,
            "human_gate_id": "gate-auto",
            "takeover_id": "takeover-auto",
            "case_id": "TC-AUTO",
            "browser_context_ref": ref.to_dict(),
            "required_action": "complete protected authentication",
            "reason": "AUTH_REQUIRED",
            "allowed_scope": {"environment": "TEST"},
            "resume_mode": "AUTO",
            "resume_condition": {"authenticated": True, "page": "protected"},
            "goal_id": "goal-auto",
            "batch_id": "batch-auto",
            "mandatory_for_goal": True,
        })
        checks["takeover_is_durable_and_yields"] = opened["status"] == "WAITING_HUMAN" and opened["ai_turn"] == "YIELD" and browser.owner == "HUMAN"
        waiting = g4.auto_resume_human_gates(mission_id)
        checks["background_tick_rejects_unauthenticated_state"] = waiting["status"] == "WAITING" and browser.owner == "HUMAN" and "gate-auto" not in waiting["resumed_gate_refs"]
        browser.resume_ready = True
        # New runtime/service instance proves no dependency on the original Conversation/OpenCode Session.
        restarted = create_canonical_runtime(root, db_path=db)
        restarted_orch = G21AutonomousOrchestrationService(restarted, root, session_provider=provider)
        g4_restart = G4RealExecutionService(restarted, orchestration=restarted_orch, browser_provider=browser)
        resumed = g4_restart.auto_resume_human_gates(mission_id)
        checks["background_tick_resumes_without_completion_call"] = resumed["status"] == "RESUMED" and resumed["resumed_gate_refs"] == ["gate-auto"] and browser.owner == "AI"
        human_state = restarted.replay_composed(mission_id).extension_state("r2_6_human_gate")
        gate = human_state.gate("gate-auto")
        checks["canonical_r26_gate_completed"] = gate is not None and gate.status == "RESOLVED"
        cursor = g4_restart.recover_cursor(mission_id, root_attempt_id=attempt["root_attempt_id"])
        checks["same_root_attempt_step_cursor_recovered"] = cursor["payload"]["pending_step_id"] == "verify-auth" and cursor["payload"]["current_step_index"] == 2 and cursor["payload"]["root_attempt_id"] == attempt["root_attempt_id"]
        checks["same_browser_context_preserved"] = browser._ref().browser_context_id_or_epoch == ref.browser_context_id_or_epoch and browser._ref().context_binding_digest == ref.context_binding_digest
        checks["background_tick_has_no_conversation_dependency"] = resumed["conversation_dependency"] is False
        checks["projection_verifies"] = restarted.verify_projection(mission_id).get("ok") is True
    failed = [key for key, value in checks.items() if not value]
    print(json.dumps({"status": "PASS" if not failed else "FAIL", "passed": sum(checks.values()), "total": len(checks), "failed": failed, "checks": checks}, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
