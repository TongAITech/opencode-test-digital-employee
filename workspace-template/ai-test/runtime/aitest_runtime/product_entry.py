"""OpenCode-facing canonical product boundary for the R1-R4 runtime.

G1 converged product truth onto the R1 Event Stream. G2 adds Mission/Plan/Task
autonomous orchestration. G2.1 makes Session routing and health supervision a
Runtime responsibility: agents cannot create, rotate, or monitor their own
Sessions; the background Control Loop does so from durable R1 truth.

G3 Requirement/Code/Testing Intelligence and G4 real execution/test-goal
convergence are wired through this canonical boundary. Defect Hunter +
sufficiency (G5) and the continuous closed loop (G6) remain later gates.
Unsupported operations fail closed; no command falls back to ``aitest.db``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from .autonomous_orchestration import AutonomousOrchestrationService, default_service
from .canonical_runtime import bootstrap_mission, create_canonical_runtime, runtime_status
from .g3.service import G3TestingIntelligenceService
from .g4.service import G4RealExecutionService, TestObjectiveController
from .g4.composition import load_provider_bundle


def workspace_root() -> Path:
    configured = os.environ.get("AITEST_WORKSPACE_ROOT")
    return Path(configured).resolve() if configured else Path.cwd().resolve()


def profile(root: Path) -> dict[str, Any]:
    path = root / "PFC_PROJECT_PROFILE.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


_G4_BROWSER_PROVIDER = None
_G4_CAPABILITY_EXECUTORS = None
_G4_RESUME_CONDITION_VERIFIER = None


def g4_service(root: Path | None = None) -> G4RealExecutionService:
    root = (root or workspace_root()).resolve()
    runtime = create_canonical_runtime(root)
    # Product subprocesses cannot rely on in-process monkeypatch/injection. Load an
    # explicitly configured provider factory when present; absent/invalid bindings
    # fail closed rather than guessing bank Browser/API/DB/CAT providers. Test-only
    # in-process overrides remain supported for deterministic construction evidence.
    bundle = load_provider_bundle(root, profile(root))
    browser_provider = _G4_BROWSER_PROVIDER if _G4_BROWSER_PROVIDER is not None else bundle.browser_provider
    capability_executors = _G4_CAPABILITY_EXECUTORS if _G4_CAPABILITY_EXECUTORS is not None else bundle.capability_executors
    resume_verifier = _G4_RESUME_CONDITION_VERIFIER if _G4_RESUME_CONDITION_VERIFIER is not None else bundle.resume_condition_verifier
    return G4RealExecutionService(runtime, orchestration=default_service(runtime, root), browser_provider=browser_provider, capability_executors=capability_executors, resume_condition_verifier=resume_verifier)


def orchestration_service(root: Path | None = None) -> AutonomousOrchestrationService:
    root = (root or workspace_root()).resolve()
    runtime = create_canonical_runtime(root)
    # Production composition is fail-closed and always uses the real OpenCode
    # session provider. FakeOpenCodeSessionProvider is construction-test only.
    return default_service(runtime, root)


def _mission_view(root: Path) -> dict[str, Any]:
    status = runtime_status(root)
    missions = status.get("missions") or []
    return {
        "status": "PASS",
        "truth_source": "R1_EVENT_STREAM",
        "conversation_is_not_truth": True,
        "mission_count": len(missions),
        "missions": missions,
    }


def interactive_truth(target: str, requirement_id: str | None = None, case_id: str | None = None) -> dict[str, Any]:
    root = workspace_root()
    target = (target or "status").strip().lower()
    base = runtime_status(root)
    config = profile(root)
    if target == "status":
        return {
            **base,
            "project_profile": {
                "project": config.get("project"),
                "release_id": config.get("release_id"),
                "first_validation_target": config.get("first_validation_target"),
            },
            "g1_runtime_convergence": "ENGINEERING_PASS",
            "g2_autonomous_orchestration": "ENGINEERING_PASS / BANK_OPENCODE_FIELD_VALIDATION_PENDING",
            "g2_1_session_router_control_loop": "ENGINEERING_PASS / BANK_OPENCODE_OBSERVATION_FIELD_VALIDATION_PENDING",
            "g3_testing_intelligence": "ENGINEERING_PASS / FROZEN",
            "g4_real_execution": "ENGINEERING_IN_PROGRESS / BANK_EXECUTION_FIELD_VALIDATION_PENDING",
            "real_execution_entry": "G4_PRODUCT_ENTRY",
        }
    if target == "mission":
        return _mission_view(root)
    if target == "orchestration":
        return {
            "status": "PASS",
            "truth_source": "R1_EVENT_STREAM",
            "conversation_is_not_truth": True,
            "g2_autonomous_orchestration": "ENGINEERING_PASS / BANK_OPENCODE_FIELD_VALIDATION_PENDING",
            "mission_count": base.get("mission_count", 0),
            "mock_session_fallback": "FORBIDDEN",
        }
    if target == "all":
        return {
            **base,
            "mission_view": _mission_view(root),
            "g2_autonomous_orchestration": "ENGINEERING_PASS / BANK_OPENCODE_FIELD_VALIDATION_PENDING",
            "real_execution_entry": "G4_PRODUCT_ENTRY",
        }
    if target in {"requirement", "coverage", "cases", "human_actions"}:
        mission_id = next((item.get("mission_id") for item in base.get("missions", []) if item.get("mission_id")), None)
        if mission_id is None:
            return {"status": "NO_MISSION", "truth_source": "R1_EVENT_STREAM", "target": target, "legacy_fallback": "FORBIDDEN"}
        service = G3TestingIntelligenceService(create_canonical_runtime(root))
        kind_map = {
            "requirement": {"REQUIREMENT_SEMANTIC_MODEL", "KNOWLEDGE_GAP"},
            "coverage": {"CODE_COVERAGE_OBJECTIVE", "INCREMENTAL_COVERAGE_SNAPSHOT", "COVERAGE_RECONCILIATION", "COVERAGE_GAP"},
            "cases": {"TEST_STRATEGY_PORTFOLIO", "CASE_SPECIFICATION", "CASE_VALUE_LINK", "DESIGN_EVALUATION"},
            "human_actions": {"HUMAN_TASK", "HUMAN_REVIEW_REQUEST"},
        }
        facts = [item.to_dict() for item in service.state(mission_id).facts if item.fact_kind in kind_map[target]]
        if requirement_id:
            facts = [item for item in facts if requirement_id in json.dumps(item, ensure_ascii=False)]
        if case_id:
            facts = [item for item in facts if case_id in json.dumps(item, ensure_ascii=False)]
        return {"status": "PASS", "truth_source": "R1_EVENT_STREAM", "target": target, "mission_id": mission_id, "facts": facts, "legacy_fallback": "FORBIDDEN"}
    if target in {"project", "execution", "defects"}:
        return {
            "status": ("PASS" if target == "execution" else ("HOLD" if target == "defects" else "PENDING_PRODUCTIZATION")),
            "truth_source": "R1_EVENT_STREAM", "target": target,
            "gate": "G4_REAL_EXECUTION" if target == "execution" else ("G5_DEFECT_TRUTH" if target == "defects" else "R5_PRODUCTIZATION"),
            "legacy_fallback": "FORBIDDEN",
        }
    return {"status": "INVALID_TARGET", "truth_source": "R1_EVENT_STREAM", "target": target}


def interactive_command(
    intent: str,
    requirement_id: str | None = None,
    case_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    intent = (intent or "").strip().lower()
    if intent == "show":
        return interactive_truth("status", requirement_id=requirement_id, case_id=case_id)
    # Natural-language PFC actions that require semantic intake payloads are
    # routed through aitest_director in G2 rather than guessed here.
    return {
        "status": "HOLD",
        "truth_source": "R1_EVENT_STREAM",
        "intent": intent,
        "requirement_id": requirement_id,
        "case_id": case_id,
        "note_recorded": False,
        "legacy_runtime_write": "FORBIDDEN",
        "reason": "Use canonical aitest Director/Planner/Scheduler, G3 testing-intelligence tools, and G4 real-execution tools; G5 defect truth and G6 closed-loop mutations remain HOLD",
        "real_execution_entry": "G4_PRODUCT_ENTRY",
    }


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return dict(value)


def orchestration_command(role: str, action: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    root = workspace_root()
    role = (role or "").strip().upper()
    action = (action or "").strip().lower()
    data = _object(payload, "payload")
    service = orchestration_service(root)

    allowed: dict[str, set[str]] = {
        "DIRECTOR": {"status", "start_test", "continue_test", "intake_mission", "open_planner", "open_human_gate", "decide_human_gate"},
        "PLANNER": {"status", "propose_plan"},
        "SCHEDULER": {"status", "advance", "dispatch_next"},
        "EXECUTOR": {"status", "report_task_outcome"},
        "CONTROL": {"status", "control_tick", "reconcile_sessions", "observe_session", "rotate_session"},
    }
    if role not in allowed or action not in allowed[role]:
        return {
            "status": "HOLD",
            "truth_source": "R1_EVENT_STREAM",
            "conversation_is_not_truth": True,
            "role": role,
            "action": action,
            "legacy_fallback": "FORBIDDEN",
            "reason": "ACTION_NOT_AUTHORIZED_FOR_G2_ROLE",
        }

    mission_id = data.get("mission_id")
    if action == "status":
        return service.status(str(mission_id)) if mission_id else service.status()
    if action == "start_test":
        request = data.get("request", data)
        return service.start_test(_object(request, "request"))
    if action == "continue_test":
        scope = data.get("scope")
        return service.continue_test(
            mission_id=str(mission_id) if mission_id else None,
            scope=_object(scope, "scope") if scope is not None else None,
        )
    if action == "intake_mission":
        request = data.get("request", data)
        return service.intake_mission(_object(request, "request"))
    if action == "open_planner":
        return service.open_planning_session(str(mission_id))
    if action == "open_human_gate":
        request = data.get("request", data)
        return service.open_human_gate(_object(request, "request"))
    if action == "decide_human_gate":
        request = data.get("request", data)
        return service.decide_human_gate(_object(request, "request"))
    if action == "propose_plan":
        return service.propose_plan(str(mission_id), _object(data.get("proposal"), "proposal"))
    if action == "advance":
        return service.advance(
            str(mission_id),
            parent_session_id=str(data["parent_session_id"]) if data.get("parent_session_id") else None,
        )
    if action == "dispatch_next":
        return service.dispatch_next(
            str(mission_id),
            parent_session_id=str(data["parent_session_id"]) if data.get("parent_session_id") else None,
        )
    if action == "control_tick":
        return service.supervise_once()
    if action == "reconcile_sessions":
        return {"status": "PASS", "truth_source": "R1_EVENT_STREAM", "reconciliation": service.reconcile_external_sessions()}
    if action == "observe_session":
        observation = data.get("observation")
        return service.observe_session(
            str(mission_id),
            task_id=str(data.get("task_id") or ""),
            observation=_object(observation, "observation") if observation is not None else None,
        )
    if action == "report_task_outcome":
        refs = data.get("external_references") or []
        if not isinstance(refs, list):
            raise ValueError("external_references must be an array")
        return service.report_task_outcome(
            str(mission_id),
            task_id=str(data.get("task_id") or ""),
            attempt_id=str(data.get("attempt_id") or ""),
            session_id=str(data.get("session_id") or ""),
            outcome=str(data.get("outcome") or ""),
            summary=str(data.get("summary") or ""),
            external_references=[_object(item, "external_reference") for item in refs],
        )
    if action == "rotate_session":
        return service.rotate_session(
            str(mission_id),
            task_id=str(data.get("task_id") or ""),
            reasons=[str(item) for item in (data.get("reasons") or ["CONTROL_OVERRIDE"])],
        )
    raise AssertionError(action)


def g3_command(role: str, action: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    root = workspace_root()
    role = (role or "").strip().upper()
    action = (action or "").strip().lower()
    data = _object(payload, "payload")
    runtime = create_canonical_runtime(root)
    orchestration = default_service(runtime, root)
    service = G3TestingIntelligenceService(runtime, orchestration=orchestration)
    allowed = {
        "DIRECTOR": {"status", "work_context", "register_intent"},
        "REQUIREMENT_ANALYST": {"status", "work_context", "analyze_requirement"},
        "CODE_ANALYST": {"status", "work_context", "analyze_changes", "acquire_coverage"},
        "TEST_STRATEGIST": {"status", "work_context", "recommend_next_work", "create_strategy", "design_test_profile"},
        "CASE_DESIGNER": {"status", "work_context", "design_cases"},
        "EVALUATOR": {"status", "work_context", "evaluate_case_design"},
    }
    if role not in allowed or action not in allowed[role]:
        return {"status": "HOLD", "truth_source": "R1_EVENT_STREAM", "role": role, "action": action, "reason": "ACTION_NOT_AUTHORIZED_FOR_G3_ROLE", "legacy_fallback": "FORBIDDEN"}
    mission_id = str(data.get("mission_id") or "")
    if action == "status":
        return service.status(mission_id)
    if role != "DIRECTOR":
        task_id = str(data.get("task_id") or "")
        attempt_id = str(data.get("attempt_id") or "")
        session_id = str(data.get("session_id") or "")
        if not task_id or not attempt_id or not session_id:
            raise RuntimeError("G3_GOVERNED_WORKER_BINDING_REQUIRED")
        composed = runtime.replay_composed(mission_id)
        session_control = composed.extension_state("g2_1_session_control")
        route = session_control.route(task_id) if session_control is not None and hasattr(session_control, "route") else None
        if route is None or str(route.role).upper() != role:
            raise RuntimeError("G3_SESSION_ROUTER_ROLE_BINDING_MISMATCH")
        execution = composed.extension_state("r1_3b_execution_resume")
        latest = execution.latest_attempt(task_id) if execution is not None and hasattr(execution, "latest_attempt") else None
        if latest is None or latest.attempt_id != attempt_id or latest.runtime_session_id != session_id:
            raise RuntimeError("G3_R2_5_ATTEMPT_SESSION_BINDING_MISMATCH")
    if action == "work_context":
        return service.work_context(mission_id)
    if action == "register_intent":
        return service.register_intent(mission_id, str(data.get("intent_type") or ""), _object(data.get("scope") or {}, "scope"), _object(data.get("constraints") or {}, "constraints"))
    if action == "analyze_requirement":
        return service.analyze_requirement(mission_id, str(data.get("scope_identity") or ""), _object(data.get("semantics"), "semantics"))
    if action == "analyze_changes":
        repositories = data.get("repositories") or []
        if not isinstance(repositories, list): raise ValueError("repositories must be an array")
        return service.analyze_changes(mission_id, str(data.get("scope_identity") or ""), [_object(item, "repository") for item in repositories], _object(data.get("r3_1_reference"), "r3_1_reference"))
    if action == "acquire_coverage":
        change = data.get("change_analysis")
        return service.acquire_coverage(mission_id, _object(data.get("profile") or {}, "profile"), _object(data.get("query") or {}, "query"), change_analysis=_object(change, "change_analysis") if change is not None else None, human_gate_request=_object(data["human_gate_request"], "human_gate_request") if data.get("human_gate_request") is not None else None)
    if action == "recommend_next_work":
        candidates = data.get("candidates") or []
        if not isinstance(candidates, list) or any(not isinstance(item, Mapping) for item in candidates):
            raise RuntimeError("G3_NEXT_WORK_CANDIDATES_INVALID")
        return service.recommend_next_work(mission_id, [dict(item) for item in candidates])
    if action == "create_strategy":
        refs = data.get("r3_2_references") or []
        hypotheses = data.get("hypothesis_candidates") or []
        if not isinstance(refs, list) or not isinstance(hypotheses, list): raise ValueError("r3_2_references/hypothesis_candidates must be arrays")
        return service.create_strategy(mission_id, str(data.get("scope_identity") or ""), _object(data.get("r3_1_reference"), "r3_1_reference"), [_object(item, "r3_2_reference") for item in refs], _object(data.get("risk_inputs") or {}, "risk_inputs"), [_object(item, "hypothesis") for item in hypotheses])
    if action == "design_test_profile":
        return service.design_test_profile(mission_id, str(data.get("profile_type") or ""), _object(data.get("profile") or {}, "profile"))
    if action == "design_cases":
        specs = data.get("detailed_specs") or {}
        return service.design_cases(mission_id, str(data.get("strategy_version_id") or ""), str(data.get("strategy_fingerprint") or ""), _object(specs, "detailed_specs"), designer_session_ref=str(data["designer_session_ref"]) if data.get("designer_session_ref") else None, batch_limit=int(data.get("batch_limit") or 200))
    if action == "evaluate_case_design":
        return service.evaluate_case_design(mission_id, str(data.get("scope_identity") or ""), _object(data.get("r3_1_reference"), "r3_1_reference"), _object(data.get("r3_2_reference"), "r3_2_reference"), str(data.get("case_spec_fact_id") or ""), dimension_assessments=_object(data["dimension_assessments"], "dimension_assessments") if data.get("dimension_assessments") is not None else None, reviewer_session_ref=str(data["reviewer_session_ref"]) if data.get("reviewer_session_ref") else None, human_gate_request=_object(data["human_gate_request"], "human_gate_request") if data.get("human_gate_request") is not None else None)
    raise AssertionError(action)


def g4_command(role: str, action: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    root = workspace_root()
    role = (role or "").strip().upper()
    action = (action or "").strip().lower()
    data = _object(payload, "payload")
    service = g4_service(root)
    runtime = service.runtime
    allowed = {
        "DIRECTOR": {"status", "create_goal", "control_tick", "coverage_from_g3", "blocker_gap", "risk_acceptance", "record_iteration", "human_gate_user_turn_resume"},
        "EXECUTOR": {"status", "record_cursor", "recover_cursor", "register_capability", "validate_executor", "execute_capability", "capability_human_gate", "request_human_takeover", "reconcile_human_takeover", "complete_human_takeover", "record_step_result", "create_batch"},
    }
    if role not in allowed or action not in allowed[role]:
        return {"status": "HOLD", "truth_source": "R1_EVENT_STREAM", "role": role, "action": action, "reason": "ACTION_NOT_AUTHORIZED_FOR_G4_ROLE", "legacy_fallback": "FORBIDDEN", "g5_defect_truth": "HOLD"}
    mission_id = str(data.get("mission_id") or "")
    if action == "status": return service.status(mission_id)
    if role == "EXECUTOR" and action not in {"recover_cursor", "complete_human_takeover", "register_capability", "validate_executor"}:
        task_id, attempt_id, session_id = (str(data.get(k) or "") for k in ("task_id", "attempt_id", "session_id"))
        if not task_id or not attempt_id or not session_id: raise RuntimeError("G4_GOVERNED_WORKER_BINDING_REQUIRED")
        composed = runtime.replay_composed(mission_id)
        sc = composed.extension_state("g2_1_session_control")
        route = sc.route(task_id) if sc is not None and hasattr(sc, "route") else None
        if route is None or str(route.role).upper() != "EXECUTOR": raise RuntimeError("G4_SESSION_ROUTER_ROLE_BINDING_MISMATCH")
        ex = composed.extension_state("r1_3b_execution_resume")
        attempt = ex.attempt(attempt_id) if ex is not None and hasattr(ex, "attempt") else None
        if attempt is None or attempt.task_id != task_id or attempt.runtime_session_id != session_id: raise RuntimeError("G4_R2_5_ATTEMPT_SESSION_BINDING_MISMATCH")
    if action == "create_goal": return service.create_goal(mission_id, data)
    if action == "human_gate_user_turn_resume": return service.resolve_human_gate_user_turn(mission_id, data)
    if action == "record_cursor": return service.record_cursor(mission_id, data)
    if action == "recover_cursor": return service.recover_cursor(mission_id, attempt_id=data.get("attempt_id"), root_attempt_id=data.get("root_attempt_id"), case_id=data.get("case_id"))
    if action == "register_capability": return service.register_capability(mission_id, str(data.get("capability_id") or ""), str(data.get("capability_status") or data.get("status") or ""), provider_ref=data.get("provider_ref"), metadata=_object(data.get("metadata") or {}, "metadata"))
    if action == "validate_executor":
        decision = service.validate_executor_request(str(data.get("capability_id") or ""), _object(data.get("executor_request") or {}, "executor_request")).to_dict()
        return {"status": decision["status"], "truth_source": "R1_EVENT_STREAM", "decision": decision}
    if action == "execute_capability": return service.execute_capability(mission_id, data)
    if action == "capability_human_gate": return service.capability_human_gate(mission_id, data)
    if action == "request_human_takeover": return service.request_human_takeover(mission_id, data)
    if action == "reconcile_human_takeover": return service.reconcile_human_takeover(mission_id, data)
    if action == "complete_human_takeover": return service.complete_human_takeover(mission_id, data)
    if action == "record_step_result": return service.record_step_result(mission_id, data)
    if action == "create_batch": return service.create_batch(mission_id, data)
    if action == "coverage_from_g3": return service.record_coverage_from_g3(mission_id, data)
    if action == "blocker_gap": return service.record_blocker_gap(mission_id, data)
    if action == "risk_acceptance": return service.record_risk_acceptance(mission_id, data)
    if action == "record_iteration": return service.record_iteration(mission_id, data)
    if action == "control_tick": return TestObjectiveController(service).tick(mission_id, str(data.get("goal_id") or ""), replan_context=_object(data.get("replan_context") or {}, "replan_context"))
    raise AssertionError(action)


def emit(value: Any) -> None:
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        raise RuntimeError("UTF8_MACHINE_JSON_STDOUT_BUFFER_UNAVAILABLE")
    stream.write(data)
    stream.flush()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aitest-product")
    sp = p.add_subparsers(dest="command", required=True)

    x = sp.add_parser("doctor")
    x.add_argument("--workspace-root")

    x = sp.add_parser("interactive-truth")
    x.add_argument("--target", default="status")
    x.add_argument("--requirement-id")
    x.add_argument("--case-id")

    x = sp.add_parser("interactive-command")
    x.add_argument("--intent", required=True)
    x.add_argument("--requirement-id")
    x.add_argument("--case-id")
    x.add_argument("--note")

    x = sp.add_parser("orchestrate")
    x.add_argument("--role", required=True)
    x.add_argument("--action", required=True)
    x.add_argument("--payload", default="{}")

    x = sp.add_parser("g3")
    x.add_argument("--role", required=True)
    x.add_argument("--action", required=True)
    x.add_argument("--payload", default="{}")

    x = sp.add_parser("g4")
    x.add_argument("--role", required=True)
    x.add_argument("--action", required=True)
    x.add_argument("--payload", default="{}")

    # Internal construction/migration boundary. Normal product Mission creation
    # goes through R2.2 ``start_test``/``intake_mission``.
    x = sp.add_parser("bootstrap-mission")
    x.add_argument("--mission-id", required=True)
    x.add_argument("--goal-id", required=True)
    x.add_argument("--goal", required=True)
    x.add_argument("--attributes", default="{}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if getattr(args, "workspace_root", None):
        os.environ["AITEST_WORKSPACE_ROOT"] = str(Path(args.workspace_root).resolve())
    try:
        if args.command == "doctor":
            emit(runtime_status(workspace_root()))
            return 0
        if args.command == "interactive-truth":
            emit(interactive_truth(args.target, args.requirement_id, args.case_id))
            return 0
        if args.command == "interactive-command":
            emit(interactive_command(args.intent, args.requirement_id, args.case_id, args.note))
            return 0
        if args.command == "orchestrate":
            payload = json.loads(args.payload)
            emit(orchestration_command(args.role, args.action, _object(payload, "payload")))
            return 0
        if args.command == "g3":
            payload = json.loads(args.payload)
            emit(g3_command(args.role, args.action, _object(payload, "payload")))
            return 0
        if args.command == "g4":
            payload = json.loads(args.payload)
            emit(g4_command(args.role, args.action, _object(payload, "payload")))
            return 0
        if args.command == "bootstrap-mission":
            goal = json.loads(args.goal)
            attrs = json.loads(args.attributes)
            emit(
                bootstrap_mission(
                    workspace_root(),
                    mission_id=args.mission_id,
                    goal_id=args.goal_id,
                    goal=goal,
                    attributes=attrs,
                )
            )
            return 0
        raise ValueError(args.command)
    except Exception as exc:
        emit({"status": "FAIL", "error": type(exc).__name__, "message": str(exc), "truth_source": "R1_EVENT_STREAM"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
