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
from aitest_runtime.g3.coverage import CoverageProviderResult, MappingCoveragePlatformProvider
from aitest_runtime.g3.service import G3TestingIntelligenceService
from aitest_runtime.g4.service import G4RealExecutionService
from test_g4_full_same_mission_product_e2e import intake_request


def snapshot(pct: float, seq: int) -> dict:
    return {
        "snapshot_id": f"terminal:{seq}",
        "application_id": "cfg-data",
        "target_version": "V2",
        "baseline_label": "master",
        "baseline_commit": "UNKNOWN",
        "target_commit": f"{seq:040x}",
        "observed_at": f"2026-09-03T02:{seq:02d}:00Z",
        "coverage_semantics": "BANK_EFFECTIVE_INCREMENTAL",
        "source_identity": f"bank:cfg-data:V2:{seq}",
        "effective_incremental_coverage_pct": pct,
        "effective_changed_lines_total": 100,
        "covered_changed_lines": int(pct),
        "uncovered_changed_lines": 100 - int(pct),
        "details": [{"level": "APPLICATION", "application_id": "cfg-data", "coverage_pct": pct}],
    }


def acquire(runtime, orch, mission_id: str, pct: float, seq: int):
    service = G3TestingIntelligenceService(
        runtime,
        coverage_provider=MappingCoveragePlatformProvider(CoverageProviderResult("AVAILABLE", ("AGGREGATE",), snapshot=snapshot(pct, seq))),
        orchestration=orch,
    )
    return service.acquire_coverage(
        mission_id,
        {"platform_profile_id": "bankcov", "authenticated_context_ref": "auth", "method": "API"},
        {"application_id": "cfg-data", "target_version": "V2", "baseline_label": "master"},
    )


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="g4-wave2-terminal-") as td:
        root = Path(td)
        db = root / "runtime-spine.db"
        os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
        os.environ["AITEST_RUNTIME_SPINE_DB"] = str(db)
        runtime = create_canonical_runtime(root, db_path=db)
        orch = G21AutonomousOrchestrationService(runtime, root, session_provider=FakeOpenCodeSessionProvider(root))
        mission_id = orch.start_test(intake_request())["intake"]["intake"]["mission_id"]
        g4 = G4RealExecutionService(runtime, orchestration=orch)
        g4.create_goal(mission_id, {
            "goal_id": "terminal",
            "project_id": "PFC",
            "release_id": "R2",
            "affected_applications": ["cfg-data"],
            "affected_application_target_versions": {"cfg-data": "V2"},
            "coverage_policy": {"target_pct": 95},
        })
        first_snapshot = acquire(runtime, orch, mission_id, 96, 1)
        g4.record_coverage_from_g3(mission_id, {
            "measurement_id": "m1",
            "goal_id": "terminal",
            "state": "AVAILABLE",
            "g3_snapshot_fact_id": first_snapshot["snapshot"]["fact_id"],
        })
        first = g4.evaluate_goal(mission_id, "terminal")
        checks["goal_reaches_terminal_satisfied"] = first["status"] == "SATISFIED" and g4.goal_status(mission_id, "terminal") == "SATISFIED"
        status_count = len(g4.state(mission_id).by_kind("TESTING_GOAL_STATUS"))
        measurement_count = len(g4.state(mission_id).by_kind("COVERAGE_MEASUREMENT"))
        second_snapshot = acquire(runtime, orch, mission_id, 10, 2)
        try:
            g4.record_coverage_from_g3(mission_id, {
                "measurement_id": "m2",
                "goal_id": "terminal",
                "state": "AVAILABLE",
                "g3_snapshot_fact_id": second_snapshot["snapshot"]["fact_id"],
            })
            rejected = False
        except RuntimeError as exc:
            rejected = exc.code == "G4_TERMINAL_GOAL_NEW_MEASUREMENT_REQUIRES_NEW_GOAL"
        checks["later_measurement_requires_new_goal_before_write"] = rejected and len(g4.state(mission_id).by_kind("COVERAGE_MEASUREMENT")) == measurement_count
        second = g4.evaluate_goal(mission_id, "terminal")
        checks["terminal_goal_stays_satisfied"] = second["status"] == "SATISFIED" and second["terminal_state_locked"] is True and g4.goal_status(mission_id, "terminal") == "SATISFIED" and len(g4.state(mission_id).by_kind("TESTING_GOAL_STATUS")) == status_count
        try:
            g4._set_goal_status(mission_id, "terminal", "MEASURING", reason="adversarial")
            direct_blocked = False
        except RuntimeError as exc:
            direct_blocked = exc.code == "G4_GOAL_TRANSITION_FORBIDDEN"
        checks["direct_terminal_to_nonterminal_transition_fails_closed"] = direct_blocked
        restarted = G4RealExecutionService(create_canonical_runtime(root, db_path=db))
        checks["terminal_status_is_durable_after_restart"] = restarted.goal_status(mission_id, "terminal") == "SATISFIED"
        checks["same_terminal_transition_is_idempotent"] = g4._set_goal_status(mission_id, "terminal", "SATISFIED", reason="idempotent")["payload"]["status"] == "SATISFIED" and len(g4.state(mission_id).by_kind("TESTING_GOAL_STATUS")) == status_count
        checks["projection_verifies"] = runtime.verify_projection(mission_id).get("ok") is True
    failed = [key for key, value in checks.items() if not value]
    print(json.dumps({"status": "PASS" if not failed else "FAIL", "passed": sum(checks.values()), "total": len(checks), "failed": failed, "checks": checks}, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
