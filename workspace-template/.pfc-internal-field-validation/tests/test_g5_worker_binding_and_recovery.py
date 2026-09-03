from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
sys.path.insert(0, str(RUNTIME))

from aitest_runtime import product_entry
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g2_1.router import AgentRoleRegistry, SessionRouter

G5_CAPABILITIES = {
    "OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT", "DEFECT_ANOMALY_INTAKE",
    "DEFECT_CANDIDATE_FORMATION", "EVIDENCE_GAP_ANALYSIS", "CROSS_SOURCE_CORRELATION",
    "REPRODUCIBILITY_REASONING", "FALSE_POSITIVE_EXCLUSION", "DEFECT_TRUTH_ASSESSMENT",
    "RCA_ANALYSIS", "DUPLICATE_CORRELATION",
}


def request(intake_id: str) -> dict:
    return {
        "intake_id": intake_id,
        "operation": "CREATE",
        "scope": {"mode": "EXPLICIT_SET", "project_id": "PFC", "version": "G5-EC0", "requirements": ["REQ-G5"]},
        "goal": {"title": "G5 binding construction", "intent": "prove router-bound Defect Hunter", "constraints": []},
        "source": {
            "kind": "USER", "source_ref": f"g5:{intake_id}", "source_digest": canonical_sha256({"id": intake_id}),
            "observed_at": "2026-09-03T10:00:00Z", "valid_until": None, "source_precedence": 1,
        },
        "actor": {"type": "USER", "id": "g5-ec0"},
        "resolution": {
            "resolution_id": f"resolution:{intake_id}", "request_digest": canonical_sha256({"resolution": intake_id}),
            "snapshot_id": f"snapshot:{intake_id}", "fact_set_digest": canonical_sha256({"facts": []}),
            "status": "RESOLVED", "reason_code": None, "source_refs": [f"g5:{intake_id}"],
            "valid_until": "2026-09-04T10:00:00Z",
        },
    }


def task(role: str, capabilities: list[str]) -> dict:
    return {
        "objective": f"one {role} work unit",
        "tasks": [{
            "task_key": f"task-{role.lower()}",
            "intent": "investigate one governed anomaly",
            "acceptance_criteria": [{"id": "done", "description": "governed work is complete"}],
            "routing": {
                "role": role,
                "required_capabilities": capabilities,
                "isolation_policy": "DEDICATED_TASK_SESSION",
                "parallelism_policy": "SERIAL",
            },
        }],
        "dependencies": [],
    }


def binding(envelope: dict) -> dict:
    return {
        "mission_id": envelope.get("mission_id") or envelope["attempt"]["mission_id"],
        "task_id": envelope["task_id"],
        "attempt_id": envelope["attempt"]["attempt_id"],
        "session_id": envelope["external_session"]["session_id"],
    }


def invoke(fn):
    try:
        return fn(), None
    except Exception as exc:
        return None, exc


def code(value) -> str:
    if isinstance(value, BaseException):
        return str(value)
    if isinstance(value, dict):
        return str(value.get("error_code") or value.get("code") or value.get("reason") or value.get("message") or "")
    return str(value or "")


def main() -> int:
    diagnosis = AgentRoleRegistry.default().resolve("DIAGNOSIS")
    foundation = {
        "existing_diagnosis_role_is_router_bound": diagnosis.agent_name == "aitest-diagnosis",
        "existing_diagnosis_has_session_capability": "OPENCODE_AGENT_SESSION" in diagnosis.capabilities,
        "existing_diagnosis_has_task_outcome": "TASK_OUTCOME_REPORT" in diagnosis.capabilities,
        "logical_agent_id_is_deterministic": SessionRouter.logical_agent_id("aitest-diagnosis", "T") == SessionRouter.logical_agent_id("aitest-diagnosis", "T"),
    }

    # Prove the existing Router/Attempt/Session fixture works before asking G5 to use it.
    with tempfile.TemporaryDirectory(prefix="g5-foundation-route-") as td:
        root = Path(td)
        runtime = create_canonical_runtime(root, db_path=root / "runtime-spine.db")
        provider = FakeOpenCodeSessionProvider(root)
        service = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        started = service.start_test(request("foundation"))
        mid = started["intake"]["intake"]["mission_id"]
        planned = service.propose_plan(mid, task("DIAGNOSIS", ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"]))
        first = planned.get("next") or {}
        foundation["existing_router_can_dispatch_diagnosis"] = first.get("status") == "DISPATCHED" and first.get("agent") == "aitest-diagnosis"

    contract = {
        "defect_hunter_role_registered": False,
        "defect_hunter_agent_exact": False,
        "defect_hunter_capabilities_exact": False,
        "defect_hunter_task_dispatches": False,
        "current_binding_accepted": False,
        "wrong_task_rejected": False,
        "wrong_attempt_rejected": False,
        "wrong_session_rejected": False,
        "stale_predecessor_rejected_after_rotation": False,
        "successor_binding_accepted_after_rotation": False,
        "root_logical_agent_binding_survives_rotation": False,
        "restart_work_context_uses_durable_truth": False,
    }

    hunter = None
    try:
        hunter = AgentRoleRegistry.default().resolve("DEFECT_HUNTER")
    except Exception:
        hunter = None
    if hunter is not None:
        contract["defect_hunter_role_registered"] = True
        contract["defect_hunter_agent_exact"] = hunter.agent_name == "aitest-diagnosis"
        contract["defect_hunter_capabilities_exact"] = set(hunter.capabilities) == G5_CAPABILITIES

    command = getattr(product_entry, "g5_command", None)
    if hunter is not None and callable(command):
        with tempfile.TemporaryDirectory(prefix="g5-worker-binding-") as td:
            root = Path(td)
            db = root / "runtime-spine.db"
            old_root = os.environ.get("AITEST_WORKSPACE_ROOT")
            old_db = os.environ.get("AITEST_RUNTIME_SPINE_DB")
            os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
            os.environ["AITEST_RUNTIME_SPINE_DB"] = str(db)
            runtime = create_canonical_runtime(root, db_path=db)
            provider = FakeOpenCodeSessionProvider(root)
            service = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
            try:
                started = service.start_test(request("hunter"))
                mid = started["intake"]["intake"]["mission_id"]
                planned = service.propose_plan(mid, task("DEFECT_HUNTER", sorted(G5_CAPABILITIES)))
                first = planned.get("next") or {}
                contract["defect_hunter_task_dispatches"] = first.get("status") == "DISPATCHED" and first.get("agent") == "aitest-diagnosis"
                if contract["defect_hunter_task_dispatches"]:
                    current = binding(first)
                    ok, exc = invoke(lambda: command("DEFECT_HUNTER", "work_context", current))
                    contract["current_binding_accepted"] = exc is None and isinstance(ok, dict) and ok.get("truth_source") == "R1_EVENT_STREAM"

                    bad_task, bad_task_exc = invoke(lambda: command("DEFECT_HUNTER", "work_context", {**current, "task_id": "wrong-task"}))
                    bad_attempt, bad_attempt_exc = invoke(lambda: command("DEFECT_HUNTER", "work_context", {**current, "attempt_id": "wrong-attempt"}))
                    bad_session, bad_session_exc = invoke(lambda: command("DEFECT_HUNTER", "work_context", {**current, "session_id": "wrong-session"}))
                    contract["wrong_task_rejected"] = any(x in code(bad_task_exc or bad_task) for x in ("G5_ROUTE_REQUIRED", "G5_ATTEMPT_TASK_MISMATCH"))
                    contract["wrong_attempt_rejected"] = any(x in code(bad_attempt_exc or bad_attempt) for x in ("G5_ATTEMPT_NOT_FOUND", "G5_ATTEMPT_NOT_CURRENT"))
                    contract["wrong_session_rejected"] = "G5_ATTEMPT_SESSION_MISMATCH" in code(bad_session_exc or bad_session)

                    old_attempt = current["attempt_id"]
                    old_session = current["session_id"]
                    old_root_attempt = first["attempt"]["root_attempt_id"]
                    rotation, rotation_exc = invoke(lambda: service.rotate_session(mid, task_id=current["task_id"], reasons=["CONTROL_OVERRIDE"]))
                    if rotation_exc is None:
                        execution = runtime.replay_composed(mid).extension_state("r1_3b_execution_resume")
                        latest = execution.latest_attempt(current["task_id"])
                        successor = {**current, "attempt_id": latest.attempt_id, "session_id": latest.runtime_session_id}
                        stale, stale_exc = invoke(lambda: command("DEFECT_HUNTER", "work_context", current))
                        fresh, fresh_exc = invoke(lambda: command("DEFECT_HUNTER", "work_context", successor))
                        contract["stale_predecessor_rejected_after_rotation"] = any(x in code(stale_exc or stale) for x in ("G5_ATTEMPT_NOT_CURRENT", "G5_SESSION_NOT_OPEN"))
                        contract["successor_binding_accepted_after_rotation"] = fresh_exc is None and isinstance(fresh, dict) and fresh.get("truth_source") == "R1_EVENT_STREAM"
                        contract["root_logical_agent_binding_survives_rotation"] = latest.root_attempt_id == old_root_attempt and latest.attempt_id != old_attempt and latest.runtime_session_id != old_session
                        restarted, restarted_exc = invoke(lambda: command("DEFECT_HUNTER", "work_context", successor))
                        contract["restart_work_context_uses_durable_truth"] = restarted_exc is None and isinstance(restarted, dict) and restarted.get("truth_source") == "R1_EVENT_STREAM"
            finally:
                if old_root is None: os.environ.pop("AITEST_WORKSPACE_ROOT", None)
                else: os.environ["AITEST_WORKSPACE_ROOT"] = old_root
                if old_db is None: os.environ.pop("AITEST_RUNTIME_SPINE_DB", None)
                else: os.environ["AITEST_RUNTIME_SPINE_DB"] = old_db

    fixture_ok = all(foundation.values())
    missing = [name for name, value in contract.items() if not value]
    status = "PASS" if fixture_ok and not missing else "FAIL"
    truthful_red = fixture_ok and status == "FAIL" and bool(missing)
    out = {
        "suite": "test_g5_worker_binding_and_recovery",
        "status": status,
        "passed": sum(bool(v) for v in {**foundation, **contract}.values()),
        "total": len(foundation) + len(contract),
        "fixture_ok": fixture_ok,
        "truthful_red": truthful_red,
        "red_kind": "MISSING_G5_INTEGRATION" if truthful_red else None,
        "foundation_checks": foundation,
        "contract_checks": contract,
        "missing_contract_checks": missing,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
