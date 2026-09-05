from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from contextlib import contextmanager
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


def exact_code(value) -> str | None:
    if isinstance(value, BaseException):
        direct = getattr(value, "code", None) or getattr(value, "error_code", None)
        return direct if isinstance(direct, str) else None
    if isinstance(value, dict):
        direct = value.get("error_code") or value.get("code")
        return direct if isinstance(direct, str) else None
    return None


@contextmanager
def runtime_environment(root: Path):
    old_root = os.environ.get("AITEST_WORKSPACE_ROOT")
    old_db = os.environ.get("AITEST_RUNTIME_SPINE_DB")
    os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
    os.environ["AITEST_RUNTIME_SPINE_DB"] = str(root / "runtime-spine.db")
    try:
        yield
    finally:
        if old_root is None: os.environ.pop("AITEST_WORKSPACE_ROOT", None)
        else: os.environ["AITEST_WORKSPACE_ROOT"] = old_root
        if old_db is None: os.environ.pop("AITEST_RUNTIME_SPINE_DB", None)
        else: os.environ["AITEST_RUNTIME_SPINE_DB"] = old_db


class BindingBoundaryReached(Exception):
    pass


def dispatched_fixture(root: Path, fixture_id: str, role: str, capabilities: list[str]) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    runtime = create_canonical_runtime(root, db_path=root / "runtime-spine.db")
    service = G21AutonomousOrchestrationService(
        runtime, root, session_provider=FakeOpenCodeSessionProvider(root)
    )
    started = service.start_test(request(fixture_id))
    mission_id = started["intake"]["intake"]["mission_id"]
    planned = service.propose_plan(mission_id, task(role, capabilities))
    first = planned.get("next") or {}
    if first.get("status") != "DISPATCHED":
        raise RuntimeError("G5_FIXTURE_DISPATCH_FAILED")
    return {
        "runtime": runtime,
        "service": service,
        "mission_id": mission_id,
        "current": binding(first),
        "first": first,
    }


def interrupted_before_r25_binding_fixture(root: Path, fixture_id: str) -> dict:
    """Build the real G2.1 pre-R2.5-bind crash boundary without mocking G5."""
    root.mkdir(parents=True, exist_ok=True)
    runtime = create_canonical_runtime(root, db_path=root / "runtime-spine.db")
    service = G21AutonomousOrchestrationService(
        runtime, root, session_provider=FakeOpenCodeSessionProvider(root)
    )
    started = service.start_test(request(fixture_id))
    mission_id = started["intake"]["intake"]["mission_id"]
    original_bind = service.sessions.bind_logical_agent

    def stop_before_bind(*_args, **_kwargs):
        raise BindingBoundaryReached("SIMULATED_CRASH_BEFORE_R2_5_BIND")

    service.sessions.bind_logical_agent = stop_before_bind  # type: ignore[method-assign]
    reached = False
    try:
        service.propose_plan(mission_id, task("DEFECT_HUNTER", sorted(G5_CAPABILITIES)))
    except BindingBoundaryReached:
        reached = True
    finally:
        service.sessions.bind_logical_agent = original_bind  # type: ignore[method-assign]
    if not reached:
        raise RuntimeError("G5_R2_5_BINDING_BOUNDARY_NOT_REACHED")

    composed = runtime.replay_composed(mission_id)
    work_graph = composed.extension_state("r1_2_work_graph")
    execution = composed.extension_state("r1_3b_execution_resume")
    routes = service.session_control.state(mission_id)
    route = routes.task_routes[-1] if routes.task_routes else None
    latest = execution.latest_attempt(route.task_id) if route is not None else None
    task_record = work_graph.task(route.task_id) if route is not None else None
    session = composed.core_state.session(latest.runtime_session_id) if latest is not None else None
    r25 = composed.extension_state("r2_5_session_orchestration")
    if (
        route is None
        or route.role != "DEFECT_HUNTER"
        or route.agent_name != "aitest-diagnosis"
        or set(route.required_capabilities) != G5_CAPABILITIES
        or task_record is None
        or latest is None
        or latest.mission_id != mission_id
        or latest.task_id != route.task_id
        or session is None
        or latest.runtime_session_id != session.session_id
        or session.status.value != "OPEN"
        or any(item.root_attempt_id == latest.root_attempt_id for item in r25.bindings)
    ):
        raise RuntimeError("G5_R2_5_PRE_BIND_FIXTURE_INVALID")
    return {
        "runtime": runtime,
        "service": service,
        "mission_id": mission_id,
        "current": {
            "mission_id": mission_id,
            "task_id": route.task_id,
            "attempt_id": latest.attempt_id,
            "session_id": latest.runtime_session_id,
        },
        "latest": latest,
    }


def bind_mismatched_logical_agent(fixture: dict) -> bool:
    latest = fixture["latest"]
    current = fixture["current"]
    expected = SessionRouter.logical_agent_id("aitest-diagnosis", current["task_id"])
    wrong = "aitest-diagnosis:mismatched-fixture"
    result = fixture["service"].sessions.bind_logical_agent(
        mission_id=current["mission_id"],
        binding_id=f"g2:binding:{latest.root_attempt_id}",
        logical_agent_id=wrong,
        root_attempt_id=latest.root_attempt_id,
        attempt_id=latest.attempt_id,
        task_id=latest.task_id,
        session_id=latest.runtime_session_id,
        actor={"type": "SYSTEM", "id": "g5-r2.5-mismatch-fixture"},
        expected_seq=fixture["runtime"].get_head_seq(current["mission_id"]),
    )
    record = result.record
    return (
        record is not None
        and record.mission_id == current["mission_id"]
        and record.logical_agent_id == wrong
        and record.logical_agent_id != expected
        and record.root_attempt_id == latest.root_attempt_id
        and record.attempt_id == latest.attempt_id
        and record.task_id == latest.task_id
        and record.session_id == latest.runtime_session_id
    )


def close_current_session(fixture: dict) -> bool:
    current = fixture["current"]
    runtime = fixture["runtime"]
    result = runtime.execute({
        "command_id": f"g5-fixture:{current['session_id']}:CLOSE",
        "type": "CLOSE_SESSION",
        "mission_id": current["mission_id"],
        "session_id": current["session_id"],
        "expected_seq": runtime.get_head_seq(current["mission_id"]),
        "actor": {"type": "SYSTEM", "id": "g5-session-not-open-fixture"},
        "payload": {"reason": "G5_NEGATIVE_ORACLE"},
        "idempotency_key": f"g5-fixture:{current['session_id']}:CLOSE",
        "correlation_id": f"g5-fixture:{current['session_id']}:CLOSE",
        "schema_version": 1,
    })
    session = runtime.replay_composed(current["mission_id"]).core_state.session(current["session_id"])
    return result.ok and session is not None and session.status.value == "CLOSED"


def probe_missing_fixture() -> bool:
    with tempfile.TemporaryDirectory(prefix="g5-r25-missing-probe-") as td:
        fixture = interrupted_before_r25_binding_fixture(Path(td), "r25-missing-probe")
        return bool(fixture["current"])


def probe_mismatch_fixture() -> bool:
    with tempfile.TemporaryDirectory(prefix="g5-r25-mismatch-probe-") as td:
        fixture = interrupted_before_r25_binding_fixture(Path(td), "r25-mismatch-probe")
        return bind_mismatched_logical_agent(fixture)


def probe_route_mismatch_fixture() -> bool:
    with tempfile.TemporaryDirectory(prefix="g5-route-mismatch-probe-") as td:
        fixture = dispatched_fixture(
            Path(td), "route-mismatch-probe", "DIAGNOSIS",
            ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"],
        )
        route = fixture["service"].session_control.state(fixture["mission_id"]).route(
            fixture["current"]["task_id"]
        )
        return route is not None and route.role == "DIAGNOSIS" and route.agent_name == "aitest-diagnosis"


def probe_session_not_open_fixture() -> bool:
    with tempfile.TemporaryDirectory(prefix="g5-session-closed-probe-") as td:
        fixture = dispatched_fixture(
            Path(td), "session-closed-probe", "DEFECT_HUNTER", sorted(G5_CAPABILITIES)
        )
        return close_current_session(fixture)


def exercise_missing_binding(command) -> bool:
    with tempfile.TemporaryDirectory(prefix="g5-r25-missing-") as td:
        root = Path(td)
        with runtime_environment(root):
            fixture = interrupted_before_r25_binding_fixture(root, "r25-missing")
            result, exc = invoke(lambda: command("DEFECT_HUNTER", "work_context", fixture["current"]))
            return exact_code(exc or result) == "G5_LOGICAL_AGENT_BINDING_MISSING"


def exercise_mismatched_binding(command) -> bool:
    with tempfile.TemporaryDirectory(prefix="g5-r25-mismatch-") as td:
        root = Path(td)
        with runtime_environment(root):
            fixture = interrupted_before_r25_binding_fixture(root, "r25-mismatch")
            if not bind_mismatched_logical_agent(fixture):
                return False
            result, exc = invoke(lambda: command("DEFECT_HUNTER", "work_context", fixture["current"]))
            return exact_code(exc or result) == "G5_LOGICAL_AGENT_BINDING_MISMATCH"


def exercise_route_role_mismatch(command) -> bool:
    with tempfile.TemporaryDirectory(prefix="g5-route-role-mismatch-") as td:
        root = Path(td)
        with runtime_environment(root):
            fixture = dispatched_fixture(
                root, "route-role-mismatch", "DIAGNOSIS",
                ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"],
            )
            result, exc = invoke(lambda: command("DEFECT_HUNTER", "work_context", fixture["current"]))
            return exact_code(exc or result) == "G5_ROUTE_ROLE_MISMATCH"


def exercise_session_not_open(command) -> bool:
    with tempfile.TemporaryDirectory(prefix="g5-session-not-open-") as td:
        root = Path(td)
        with runtime_environment(root):
            fixture = dispatched_fixture(
                root, "session-not-open", "DEFECT_HUNTER", sorted(G5_CAPABILITIES)
            )
            if not close_current_session(fixture):
                return False
            result, exc = invoke(lambda: command("DEFECT_HUNTER", "work_context", fixture["current"]))
            return exact_code(exc or result) == "G5_SESSION_NOT_OPEN"


def main() -> int:
    diagnosis = AgentRoleRegistry.default().resolve("DIAGNOSIS")
    foundation = {
        "existing_diagnosis_role_is_router_bound": diagnosis.agent_name == "aitest-diagnosis",
        "existing_diagnosis_has_session_capability": "OPENCODE_AGENT_SESSION" in diagnosis.capabilities,
        "existing_diagnosis_has_task_outcome": "TASK_OUTCOME_REPORT" in diagnosis.capabilities,
        "logical_agent_id_is_deterministic": SessionRouter.logical_agent_id("aitest-diagnosis", "T") == SessionRouter.logical_agent_id("aitest-diagnosis", "T"),
    }
    for name, probe in (
        ("r2_5_binding_missing_fixture_constructible", probe_missing_fixture),
        ("r2_5_binding_mismatch_fixture_constructible", probe_mismatch_fixture),
        ("route_role_mismatch_fixture_constructible", probe_route_mismatch_fixture),
        ("session_not_open_fixture_constructible", probe_session_not_open_fixture),
    ):
        value, exc = invoke(probe)
        foundation[name] = exc is None and value is True

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
        "logical_agent_binding_missing_rejected": False,
        "logical_agent_binding_mismatch_rejected": False,
        "route_role_mismatch_rejected": False,
        "current_session_not_open_rejected": False,
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
        for name, exercise in (
            ("logical_agent_binding_missing_rejected", exercise_missing_binding),
            ("logical_agent_binding_mismatch_rejected", exercise_mismatched_binding),
            ("route_role_mismatch_rejected", exercise_route_role_mismatch),
            ("current_session_not_open_rejected", exercise_session_not_open),
        ):
            value, exc = invoke(lambda exercise=exercise: exercise(command))
            contract[name] = exc is None and value is True
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
