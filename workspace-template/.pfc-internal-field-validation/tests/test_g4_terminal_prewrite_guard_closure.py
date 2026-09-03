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

from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.durable_core import RuntimeError
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g4.service import G4RealExecutionService
from test_g4_full_same_mission_product_e2e import intake_request
from test_g4_goal_transition_wave2 import acquire


def guarded(checks: dict[str, bool], name: str, runtime, mission_id: str, call) -> None:
    before_seq = runtime.get_head_seq(mission_id)
    before_facts = len(G4RealExecutionService(runtime).state(mission_id).facts)
    try:
        call()
        code = None
    except RuntimeError as exc:
        code = exc.code
    after_seq = runtime.get_head_seq(mission_id)
    after_facts = len(G4RealExecutionService(runtime).state(mission_id).facts)
    checks[f"{name}_fails_with_terminal_guard"] = code == "G4_TERMINAL_GOAL_MUTATION_FORBIDDEN"
    checks[f"{name}_writes_no_r1_fact_before_failure"] = before_seq == after_seq and before_facts == after_facts


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="g4-closure-terminal-") as td:
        root = Path(td)
        db = root / "runtime-spine.db"
        os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
        os.environ["AITEST_RUNTIME_SPINE_DB"] = str(db)
        runtime = create_canonical_runtime(root, db_path=db)
        orch = G21AutonomousOrchestrationService(runtime, root, session_provider=FakeOpenCodeSessionProvider(root))
        mission_id = orch.start_test(intake_request())["intake"]["intake"]["mission_id"]
        g4 = G4RealExecutionService(runtime, orchestration=orch)
        g4.create_goal(mission_id, {
            "goal_id": "terminal-closure",
            "project_id": "PFC",
            "release_id": "R2",
            "affected_applications": ["cfg-data"],
            "affected_application_target_versions": {"cfg-data": "V2"},
            "coverage_policy": {"target_pct": 95},
        })
        coverage = acquire(runtime, orch, mission_id, 96, 11)
        g4.record_coverage_from_g3(mission_id, {
            "measurement_id": "terminal-closure-m1",
            "goal_id": "terminal-closure",
            "state": "AVAILABLE",
            "g3_snapshot_fact_id": coverage["snapshot"]["fact_id"],
        })
        checks["precondition_goal_is_terminal"] = g4.evaluate_goal(mission_id, "terminal-closure")["status"] == "SATISFIED"

        guarded(checks, "create_batch", runtime, mission_id, lambda: g4.create_batch(mission_id, {
            "goal_id": "terminal-closure",
            "batch_id": "must-not-write",
        }))
        guarded(checks, "record_blocker_gap", runtime, mission_id, lambda: g4.record_blocker_gap(mission_id, {
            "goal_id": "terminal-closure",
            "gap_id": "must-not-write",
            "gap_kind": "UNKNOWN",
            "reason": "must not be durable",
        }))
        guarded(checks, "record_iteration", runtime, mission_id, lambda: g4.record_iteration(mission_id, {
            "goal_id": "terminal-closure",
            "iteration_id": "must-not-write",
            "coverage_before": {},
            "coverage_after": {},
        }))
        guarded(checks, "record_risk_acceptance", runtime, mission_id, lambda: g4.record_risk_acceptance(mission_id, {
            "goal_id": "terminal-closure",
            "risk_acceptance_id": "must-not-write",
            "risk": "must not be durable",
            "accepted_by": "tester",
        }))
        guarded(checks, "request_g3_replan", runtime, mission_id, lambda: g4.request_g3_replan(mission_id, {
            "goal_id": "terminal-closure",
            "reason": "must not be durable",
        }))
        guarded(checks, "capability_human_gate", runtime, mission_id, lambda: g4.capability_human_gate(mission_id, {
            "goal_id": "terminal-closure",
            "capability_id": "UI",
            "executor_request": {},
        }))
        guarded(checks, "request_human_takeover", runtime, mission_id, lambda: g4.request_human_takeover(mission_id, {
            "goal_id": "terminal-closure",
            "required_action": "must not open a gate",
        }))

        restarted = G4RealExecutionService(create_canonical_runtime(root, db_path=db))
        checks["terminal_truth_remains_satisfied_after_all_rejections"] = restarted.goal_status(mission_id, "terminal-closure") == "SATISFIED"
        checks["projection_verifies_after_all_rejections"] = restarted.runtime.verify_projection(mission_id).get("ok") is True
        forbidden_ids = {"must-not-write"}
        serialized = json.dumps([fact.to_dict() for fact in restarted.state(mission_id).facts], ensure_ascii=False)
        checks["no_forbidden_mutation_payload_was_durable"] = not any(value in serialized for value in forbidden_ids)

    failed = [key for key, value in checks.items() if not value]
    print(json.dumps({"status": "PASS" if not failed else "FAIL", "passed": sum(checks.values()), "total": len(checks), "failed": failed, "checks": checks}, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
