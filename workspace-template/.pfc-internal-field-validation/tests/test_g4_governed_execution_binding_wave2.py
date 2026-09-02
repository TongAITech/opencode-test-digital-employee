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
from aitest_runtime.durable_core import RuntimeError
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g3.coverage import CoverageProviderResult, MappingCoveragePlatformProvider
from aitest_runtime.g3.service import G3TestingIntelligenceService
from aitest_runtime.g4.service import G4RealExecutionService
from test_g4_full_same_mission_product_e2e import (
    DeterministicExecutor,
    binding,
    exec_task,
    g3_cycle,
    intake_request,
    make_repo,
)


def fails(fn, code: str) -> bool:
    try:
        fn()
    except RuntimeError as exc:
        return exc.code == code
    return False


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="g4-wave2-binding-") as td:
        root = Path(td)
        db = root / "runtime-spine.db"
        os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
        os.environ["AITEST_RUNTIME_SPINE_DB"] = str(db)
        repo, base, head = make_repo(
            root,
            "cfg-data",
            {"src/CreditLimitService.java": "public class CreditLimitService { boolean ok(long r,long a){return r<a;} }\n"},
            {"src/CreditLimitService.java": "public class CreditLimitService { boolean ok(long r,long a){if(r<0)return false;return r<=a;} }\n"},
        )
        repos = [{"repository_id": "cfg-data", "application_id": "cfg-data", "repository_path": str(repo), "base_ref": base, "head_ref": head}]
        runtime = create_canonical_runtime(root, db_path=db)
        provider = FakeOpenCodeSessionProvider(root)
        orch = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        coverage_box = {"provider": MappingCoveragePlatformProvider(CoverageProviderResult("SOURCE_UNAVAILABLE", ()))}
        old = (product_entry.orchestration_service, product_entry.default_service, product_entry.G3TestingIntelligenceService, product_entry._G4_CAPABILITY_EXECUTORS)
        executor = DeterministicExecutor("API")
        product_entry._G4_CAPABILITY_EXECUTORS = {"API": executor}
        product_entry.orchestration_service = lambda _root=None: orch
        product_entry.default_service = lambda _rt, _root: orch
        product_entry.G3TestingIntelligenceService = lambda rt, orchestration=None: G3TestingIntelligenceService(rt, coverage_provider=coverage_box["provider"], orchestration=orchestration or orch)
        try:
            started = product_entry.orchestration_command("DIRECTOR", "start_test", {"request": intake_request()})
            mission_id = started["intake"]["intake"]["mission_id"]
            cycle = g3_cycle(mission_id, orch, coverage_box, repos, 1)
            case_fact = cycle["cases"]["ready_cases"][0]["case"]
            case = case_fact["payload"]["r3_3_case"]
            strategy = cycle["strategy"]["strategy"]["strategy_version_id"]
            g4 = G4RealExecutionService(runtime, orchestration=orch, capability_executors={"API": executor})
            g4.create_goal(mission_id, {"goal_id": "goal-bind", "project_id": "PFC", "release_id": "V2", "affected_applications": ["cfg-data"], "affected_application_target_versions": {"cfg-data": "V2"}, "coverage_policy": {"target_pct": 95}})
            plan = orch.propose_plan(mission_id, {"objective": "binding negative", "tasks": [exec_task("BIND-A", case_fact["fact_id"])], "dependencies": []})
            attempt = binding(plan["next"])
            before_cursor = len(g4.state(mission_id).by_kind("STEP_CURSOR"))
            before_result = len(g4.state(mission_id).by_kind("EXECUTION_STEP_RESULT"))
            fake = {"task_id": attempt["task_id"], "attempt_id": attempt["attempt_id"], "case_id": "FAKE-CASE", "case_version": "FAKE-V1", "current_step_index": 0, "pending_step_id": "x"}
            checks["fake_case_cursor_fails_closed"] = fails(lambda: g4.record_cursor(mission_id, fake), "G4_G3_GOVERNED_CASE_REQUIRED") and len(g4.state(mission_id).by_kind("STEP_CURSOR")) == before_cursor
            checks["fake_case_result_fails_before_durable_fact"] = fails(lambda: g4.record_step_result(mission_id, {**fake, "step_id": "x", "executor_capability": "API", "expected": "ok", "actual": "ok", "oracle_result": "PASS", "oracle_reason": "fixture", "evidence_refs": ["artifact:x"], "source_identity": "fixture"}), "G4_G3_GOVERNED_CASE_REQUIRED") and len(g4.state(mission_id).by_kind("EXECUTION_STEP_RESULT")) == before_result
            calls = executor.executions
            checks["fake_case_execute_fails_before_provider"] = fails(lambda: g4.execute_capability(mission_id, {**fake, "capability_id": "API", "executor_request": {"url": "https://sut.test/x", "method": "GET", "authorized_scope": {"environment": "TEST"}}, "step": {"step_id": "x", "expected": "ok", "fixture_actual": "ok"}, "execution_node": "node"}), "G4_G3_GOVERNED_CASE_REQUIRED") and executor.executions == calls
            real = {"task_id": attempt["task_id"], "attempt_id": attempt["attempt_id"], "case_id": str(case["tc_id"]), "case_version": str(case["case_version_id"]), "case_spec_fact_id": case_fact["fact_id"]}
            checks["real_case_without_batch_fails"] = fails(lambda: g4.record_cursor(mission_id, {**real, "current_step_index": 0, "pending_step_id": "x"}), "G4_EXECUTION_BINDING_REQUIRED")
            g4.create_batch(mission_id, {"batch_id": "batch-bind", "goal_id": "goal-bind", "case_refs": [case_fact["fact_id"]], "strategy_version_id": strategy, "target_application": "cfg-data", "status": "RUNNING"})
            cursor = g4.record_cursor(mission_id, {**real, "execution_batch_id": "batch-bind", "current_step_index": 0, "pending_step_id": "x"})
            checks["exact_batch_authorizes_cursor"] = cursor["cursor"]["payload"]["governed_execution_binding"]["binding_kind"] == "EXECUTION_BATCH"
            out = g4.execute_capability(mission_id, {**real, "execution_batch_id": "batch-bind", "capability_id": "API", "executor_request": {"url": "https://sut.test/x", "method": "GET", "authorized_scope": {"environment": "TEST"}}, "step": {"step_id": "x", "expected": "ok", "fixture_actual": "ok"}, "execution_node": "node"})
            checks["exact_batch_authorizes_provider_and_result"] = out["status"] == "PASS" and executor.executions == calls + 1 and len(g4.state(mission_id).by_kind("EXECUTION_STEP_RESULT")) == before_result + 1
            checks["projection_verifies"] = runtime.verify_projection(mission_id).get("ok") is True
        finally:
            product_entry.orchestration_service, product_entry.default_service, product_entry.G3TestingIntelligenceService, product_entry._G4_CAPABILITY_EXECUTORS = old
    failed = [key for key, value in checks.items() if not value]
    print(json.dumps({"status": "PASS" if not failed else "FAIL", "passed": sum(checks.values()), "total": len(checks), "failed": failed, "checks": checks}, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
