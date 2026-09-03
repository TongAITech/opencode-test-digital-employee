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

from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g3.coverage import CoverageProviderResult, MappingCoveragePlatformProvider
from aitest_runtime.g3.service import G3TestingIntelligenceService
from aitest_runtime.g4.service import G4RealExecutionService
from test_g4_full_same_mission_product_e2e import intake_request


def snapshot(app: str, version: str, pct: float, seq: int) -> dict:
    return {
        "snapshot_id": f"bank:{app}:{version}:{seq}",
        "application_id": app,
        "target_version": version,
        "baseline_label": "master",
        "baseline_commit": "UNKNOWN",
        "target_commit": f"{seq:040x}",
        "observed_at": f"2026-09-03T00:{seq:02d}:00Z",
        "coverage_semantics": "BANK_EFFECTIVE_INCREMENTAL",
        "source_identity": f"bank:{app}:{version}:master:{seq}",
        "effective_incremental_coverage_pct": pct,
        "effective_changed_lines_total": 100,
        "covered_changed_lines": int(pct),
        "uncovered_changed_lines": 100 - int(pct),
        "details": [{"level": "APPLICATION", "application_id": app, "coverage_pct": pct}],
    }


def acquire(runtime, orch, mission_id, snap):
    svc = G3TestingIntelligenceService(
        runtime,
        coverage_provider=MappingCoveragePlatformProvider(CoverageProviderResult("AVAILABLE", ("AGGREGATE",), snapshot=snap)),
        orchestration=orch,
    )
    return svc.acquire_coverage(
        mission_id,
        {"platform_profile_id": "bankcov", "authenticated_context_ref": "auth", "method": "API"},
        {"application_id": snap["application_id"], "target_version": snap["target_version"], "baseline_label": "master"},
    )


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="g4-wave2-coverage-id-") as td:
        root = Path(td)
        db = root / "runtime-spine.db"
        os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
        os.environ["AITEST_RUNTIME_SPINE_DB"] = str(db)
        runtime = create_canonical_runtime(root, db_path=db)
        orch = G21AutonomousOrchestrationService(runtime, root, session_provider=FakeOpenCodeSessionProvider(root))
        mission_id = orch.start_test(intake_request())["intake"]["intake"]["mission_id"]
        g4 = G4RealExecutionService(runtime, orchestration=orch)
        goal = g4.create_goal(mission_id, {
            "goal_id": "g-diff",
            "project_id": "PFC",
            "release_id": "R-2026.09",
            "affected_applications": ["cfg-data", "cfg-admin"],
            "affected_application_target_versions": {"cfg-data": "V2", "cfg-admin": "V7"},
            "coverage_policy": {"target_pct": 95},
        })
        checks["target_versions_durable_not_release_guess"] = goal["goal"]["payload"]["affected_application_target_versions"] == {"cfg-data": "V2", "cfg-admin": "V7"} and goal["goal"]["payload"]["release_id"] == "R-2026.09"
        cv1 = acquire(runtime, orch, mission_id, snapshot("cfg-data", "V1", 99, 1))
        bad = g4.record_coverage_from_g3(mission_id, {"measurement_id": "bad-version", "goal_id": "g-diff", "state": "AVAILABLE", "g3_snapshot_fact_id": cv1["snapshot"]["fact_id"]})
        checks["wrong_target_version_is_mismatch"] = bad["status"] == "SOURCE_IDENTITY_MISMATCH" and bad["actual_coverage"] is None and bad["measurement"]["payload"]["expected_target_version"] == "V2"
        checks["wrong_version_never_satisfies"] = g4.evaluate_goal(mission_id, "g-diff")["status"] == "WAITING_MEASUREMENT"
        cv2 = acquire(runtime, orch, mission_id, snapshot("cfg-data", "V2", 96, 2))
        ok1 = g4.record_coverage_from_g3(mission_id, {"measurement_id": "data-v2", "goal_id": "g-diff", "state": "AVAILABLE", "g3_snapshot_fact_id": cv2["snapshot"]["fact_id"]})
        cv3 = acquire(runtime, orch, mission_id, snapshot("cfg-admin", "V2", 99, 3))
        bad2 = g4.record_coverage_from_g3(mission_id, {"measurement_id": "admin-wrong", "goal_id": "g-diff", "state": "AVAILABLE", "g3_snapshot_fact_id": cv3["snapshot"]["fact_id"]})
        checks["per_app_identity_independent"] = ok1["status"] == "AVAILABLE" and bad2["status"] == "SOURCE_IDENTITY_MISMATCH" and g4.evaluate_goal(mission_id, "g-diff")["status"] == "WAITING_MEASUREMENT"
        cv4 = acquire(runtime, orch, mission_id, snapshot("cfg-admin", "V7", 96, 4))
        ok2 = g4.record_coverage_from_g3(mission_id, {"measurement_id": "admin-v7", "goal_id": "g-diff", "state": "AVAILABLE", "g3_snapshot_fact_id": cv4["snapshot"]["fact_id"]})
        final = g4.evaluate_goal(mission_id, "g-diff")
        checks["exact_versions_can_satisfy"] = ok2["status"] == "AVAILABLE" and final["status"] == "SATISFIED" and all(value["pct"] >= 95 for value in final["evaluation"]["payload"]["per_application"].values())
        checks["master_alias_keeps_target_semantics"] = all(value["baseline_identity_status"] == "MASTER_ALIAS_ONLY" and value["target_version"] == {"cfg-data": "V2", "cfg-admin": "V7"}[value["application_id"]] for value in [ok1["measurement"]["payload"], ok2["measurement"]["payload"]])
        checks["measurement_binds_goal_and_profile"] = all(value["goal_revision_ref"] == g4._goal_revision_ref(mission_id, "g-diff") and value["provider_profile_ref"] for value in [ok1["measurement"]["payload"], ok2["measurement"]["payload"]])
        checks["projection_verifies"] = runtime.verify_projection(mission_id).get("ok") is True
    failed = [key for key, value in checks.items() if not value]
    print(json.dumps({"status": "PASS" if not failed else "FAIL", "passed": sum(checks.values()), "total": len(checks), "failed": failed, "checks": checks}, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
