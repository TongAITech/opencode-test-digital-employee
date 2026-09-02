"""G2.1 product-level Session Router + autonomous Supervisor checks.

The fake provider replaces only the external OpenCode transport. Mission, Plan,
Task, Attempt, Session, Provision, Observation and Rotation facts all use the
real canonical R1 Event Stream and G2/G2.1 extensions.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = WORKSPACE_ROOT / "ai-test" / "runtime"
sys.path.insert(0, str(RUNTIME_ROOT))

from aitest_runtime import product_entry  # noqa: E402
from aitest_runtime.autonomous_orchestration import (  # noqa: E402
    DirectoryScopedOpenCodeSessionProvider, FakeOpenCodeSessionProvider,
)
from aitest_runtime.canonical_runtime import create_canonical_runtime  # noqa: E402
from aitest_runtime.durable_core import ActorRef, CommandEnvelope, canonical_sha256  # noqa: E402
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService  # noqa: E402
from aitest_runtime.g2_1.contracts import SessionControlState, TaskRouteRequirement  # noqa: E402
from aitest_runtime.g2_1.router import AgentRoleRegistry, SessionRouter  # noqa: E402
from aitest_runtime.g2_1.supervisor import RotationPolicy, SessionObservation  # noqa: E402


def request(intake_id: str, version: str) -> dict[str, object]:
    return {
        "intake_id": intake_id,
        "operation": "CREATE",
        "scope": {"mode": "EXPLICIT_SET", "project_id": "PFC", "version": version, "requirements": ["REQ-G21"]},
        "goal": {"title": "G2.1 construction", "intent": "prove Runtime-owned Session lifecycle", "constraints": []},
        "source": {"kind": "USER", "source_ref": f"g21:{intake_id}", "source_digest": canonical_sha256({"id": intake_id}),
                   "observed_at": "2026-09-01T10:00:00Z", "valid_until": None, "source_precedence": 1},
        "actor": {"type": "USER", "id": "g21-construction"},
        "resolution": {"resolution_id": f"resolution:{intake_id}", "request_digest": canonical_sha256({"resolution": intake_id}),
                       "snapshot_id": f"snapshot:{intake_id}", "fact_set_digest": canonical_sha256({"facts": []}),
                       "status": "RESOLVED", "reason_code": None, "source_refs": [f"g21:{intake_id}"],
                       "valid_until": "2026-09-02T10:00:00Z"},
    }


def one_task(role: str = "EXECUTOR") -> dict[str, object]:
    return {
        "objective": "one routed durable work unit",
        "tasks": [{
            "task_key": "routed-work",
            "intent": "perform routed governed analysis",
            "acceptance_criteria": [{"id": "done", "description": "routed work is complete"}],
            "routing": {
                "role": role,
                "required_capabilities": ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"],
                "isolation_policy": "DEDICATED_TASK_SESSION",
                "parallelism_policy": "SERIAL",
            },
        }],
        "dependencies": [],
    }


class CrashAfterExternalCreateProvider(FakeOpenCodeSessionProvider):
    def __init__(self, directory: str | Path) -> None:
        super().__init__(directory)
        self.crash_after_next_create = False

    def create_session(self, *, title: str, parent_id: str | None = None):  # type: ignore[override]
        value = super().create_session(title=title, parent_id=parent_id)
        if self.crash_after_next_create:
            self.crash_after_next_create = False
            raise RuntimeError("SIMULATED_HARD_WINDOW_AFTER_EXTERNAL_CREATE")
        return value


class CrashOnSendProvider(FakeOpenCodeSessionProvider):
    def __init__(self, directory: str | Path) -> None:
        super().__init__(directory)
        self.crash_after_next_send = False

    def send_context(self, *, session_id: str, agent: str, text: str):  # type: ignore[override]
        value = super().send_context(session_id=session_id, agent=agent, text=text)
        if self.crash_after_next_send:
            self.crash_after_next_send = False
            raise RuntimeError("SIMULATED_CRASH_AFTER_CONTEXT_ACCEPTED")
        return value


def sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def main() -> int:
    checks: dict[str, bool] = {}

    # Router contract includes an explicit BLOCK result for a durable route
    # whose role/capability can no longer be admitted.  This keeps the WHO/WHERE
    # decision in Runtime rather than leaking a provider side effect before fail-closed.
    blocked_state = SessionControlState(
        mission_id="block-contract",
        task_routes=(TaskRouteRequirement(
            task_id="blocked-task", role="EXECUTOR", agent_name="aitest-executor",
            required_capabilities=("OPENCODE_AGENT_SESSION", "NON_EXISTENT_CAPABILITY"),
            isolation_policy="DEDICATED_TASK_SESSION", parallelism_policy="SERIAL",
            source="TEST", route_digest="blocked", registered_seq=1, registered_at="2026-09-01T10:00:00Z",
        ),),
    )
    blocked = SessionRouter(AgentRoleRegistry.default()).route_task(blocked_state, task_id="blocked-task")
    checks["router_explicit_block_decision_for_unavailable_capability"] = (
        blocked.decision == "BLOCK" and blocked.reason.startswith("CAPABILITY_UNAVAILABLE:")
    )

    # Router role selection + generic durable worker outcome.
    with tempfile.TemporaryDirectory(prefix="pfc-g21-route-") as td:
        root = Path(td)
        spine = root / "runtime-spine.db"
        runtime = create_canonical_runtime(root, db_path=spine)
        provider = FakeOpenCodeSessionProvider(root)
        service = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        legacy = root / "ai-test/state/aitest.db"
        legacy_before = sha(legacy)
        started = service.start_test(request("route", "ROUTE-V"))
        mission_id = started["intake"]["intake"]["mission_id"]
        planned = service.propose_plan(mission_id, one_task("EVALUATOR"))
        first = planned["next"]
        route = service.session_control.state(mission_id).route(first["task_id"])
        checks["router_selects_role_agent_capabilities_from_durable_route"] = (
            first["status"] == "DISPATCHED"
            and first["agent"] == "aitest-evaluator"
            and first["route"]["role"] == "EVALUATOR"
            and route is not None
            and route.agent_name == "aitest-evaluator"
            and "TASK_OUTCOME_REPORT" in route.required_capabilities
        )
        worker_context = next(
            item["text"] for item in reversed(provider.messages)
            if item.get("session_id") == first["external_session"]["session_id"]
        )
        checks["worker_context_delegates_session_lifecycle_to_supervisor_not_agent"] = (
            "G2_1_SESSION_ROUTER_SUPERVISOR" in worker_context
            and "Do not observe, create, close, or rotate your own Session" in worker_context
            and "Use observe_session for runtime rotation policy" not in worker_context
        )
        override_forbidden = False
        try:
            service.dispatch_next(mission_id, agent="aitest-executor")
        except RuntimeError as exc:
            override_forbidden = "SESSION_ROUTER_AGENT_OVERRIDE_FORBIDDEN" in str(exc)
        checks["scheduler_cannot_override_router_agent"] = override_forbidden
        # Generic worker boundary maps role-specific Sessions to the canonical
        # Task outcome contract; the Session role itself is not changed.
        done = service.report_task_outcome(
            mission_id,
            task_id=first["task_id"], attempt_id=first["attempt"]["attempt_id"],
            session_id=first["external_session"]["session_id"], outcome="SUCCEEDED", summary="routed work done",
        )
        checks["routed_non_executor_can_finish_same_durable_task_contract"] = done["next"]["status"] == "PLAN_COMPLETE"
        original_factory = product_entry.orchestration_service
        product_entry.orchestration_service = lambda _root=None: service  # type: ignore[assignment]
        try:
            denied = product_entry.orchestration_command("EXECUTOR", "observe_session", {"mission_id": mission_id, "task_id": first["task_id"]})
        finally:
            product_entry.orchestration_service = original_factory  # type: ignore[assignment]
        checks["agent_session_observation_action_is_not_authorized"] = denied["status"] == "HOLD"
        checks["legacy_aitest_db_not_written_by_g2_1"] = legacy_before == sha(legacy)

    # Unknown metrics remain null; a fresh Supervisor instance automatically
    # rotates without any Agent/Scheduler observation call.
    with tempfile.TemporaryDirectory(prefix="pfc-g21-supervisor-") as td:
        root = Path(td)
        spine = root / "runtime-spine.db"
        runtime = create_canonical_runtime(root, db_path=spine)
        provider = FakeOpenCodeSessionProvider(root)
        service = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        started = service.start_test(request("supervisor", "SUP-V"))
        mission_id = started["intake"]["intake"]["mission_id"]
        planned = service.propose_plan(mission_id, one_task("EXECUTOR"))
        first = planned["next"]
        session_id = first["external_session"]["session_id"]
        keep_tick = service.supervise_once()
        observation = service.session_control.state(mission_id).observation(session_id)
        checks["unknown_provider_metrics_remain_null_not_zero"] = (
            observation is not None
            and observation.context_used is None
            and observation.context_limit is None
            and observation.context_utilization is None
            and any(item.get("result", {}).get("status") == "KEEP" for item in keep_tick["supervision"] if item.get("task_id") == first["task_id"])
        )
        root_attempt_id = first["attempt"]["root_attempt_id"]
        provider.set_observation(session_id, message_count=60, compaction_count=0, context_utilization=None, healthy=True)
        # Reconstruct Runtime + service to prove the Supervisor needs no process
        # memory from the service that created the Mission/Task.
        runtime2 = create_canonical_runtime(root, db_path=spine)
        restarted = G21AutonomousOrchestrationService(runtime2, root, session_provider=provider)
        tick = restarted.supervise_once()
        rotated = [item["result"] for item in tick["supervision"] if item.get("task_id") == first["task_id"] and item.get("result", {}).get("status") == "ROTATED"]
        rotation = rotated[0]["rotation"]
        current = restarted.status(mission_id)
        latest_attempt = current["execution"]["attempts"][-1]
        checks["supervisor_restart_rotates_without_agent_observation"] = (
            rotation["root_attempt_id"] == root_attempt_id
            and rotation["successor_session_id"] != session_id
            and latest_attempt["root_attempt_id"] == root_attempt_id
        )
        core_sessions = {sid: item["status"] for sid, item in current["core"]["sessions"].items()}
        checks["two_phase_rotation_closes_predecessor_after_successor"] = (
            core_sessions.get(session_id) == "CLOSED"
            and core_sessions.get(rotation["successor_session_id"]) == "OPEN"
        )
        rotation_state = restarted.session_control.state(mission_id).rotation(rotation["rotation_id"])
        checks["rotation_required_and_completed_are_durable"] = rotation_state is not None and rotation_state.status == "COMPLETED"

        successor_context = next(
            item["text"] for item in reversed(provider.messages)
            if item.get("session_id") == rotation["successor_session_id"]
        )
        checks["rotation_successor_context_preserves_root_work_and_runtime_lifecycle_owner"] = (
            root_attempt_id in successor_context
            and "G2_1_SESSION_ROUTER_SUPERVISOR" in successor_context
            and "Use observe_session for runtime rotation policy" not in successor_context
        )

    # Router is generic across multiple product worker roles; no bespoke
    # create-session branch is added per role.
    routed_roles: dict[str, str] = {}
    for role_name, expected_agent in (("EVALUATOR", "aitest-evaluator"), ("DIAGNOSIS", "aitest-diagnosis"), ("KNOWLEDGE", "aitest-knowledge")):
        with tempfile.TemporaryDirectory(prefix=f"pfc-g21-role-{role_name.lower()}-") as td:
            role_root = Path(td)
            role_runtime = create_canonical_runtime(role_root, db_path=role_root / "runtime-spine.db")
            role_provider = FakeOpenCodeSessionProvider(role_root)
            role_service = G21AutonomousOrchestrationService(role_runtime, role_root, session_provider=role_provider)
            role_started = role_service.start_test(request(f"role-{role_name}", f"ROLE-{role_name}"))
            role_mission = role_started["intake"]["intake"]["mission_id"]
            role_planned = role_service.propose_plan(role_mission, one_task(role_name))
            role_first = role_planned["next"]
            routed_roles[role_name] = str(role_first.get("agent"))
            role_service.report_task_outcome(
                role_mission, task_id=role_first["task_id"], attempt_id=role_first["attempt"]["attempt_id"],
                session_id=role_first["external_session"]["session_id"], outcome="SUCCEEDED", summary="role route done",
            )
    checks["three_product_worker_roles_route_through_same_router_contract"] = routed_roles == {
        "EVALUATOR": "aitest-evaluator", "DIAGNOSIS": "aitest-diagnosis", "KNOWLEDGE": "aitest-knowledge"
    }

    # Runtime policy branches are explicit and independent from Agent prompts.
    policy = RotationPolicy()
    checks["rotation_policy_covers_message_compaction_context_and_unhealthy"] = (
        "MESSAGE_THRESHOLD" in policy.evaluate(SessionObservation("m", "now", True, True, message_count=60))
        and "CONTEXT_COMPACTED" in policy.evaluate(SessionObservation("c", "now", True, True, compaction_count=1))
        and "CONTEXT_PRESSURE" in policy.evaluate(SessionObservation("x", "now", True, True, context_utilization=0.85))
        and "SESSION_UNHEALTHY" in policy.evaluate(SessionObservation("u", "now", True, False))
        and "SESSION_UNREACHABLE" in policy.evaluate(SessionObservation("r", "now", False, None))
    )

    # Planner Session is also supervised before a Plan exists.
    with tempfile.TemporaryDirectory(prefix="pfc-g21-plan-rotate-") as td:
        root = Path(td)
        runtime = create_canonical_runtime(root, db_path=root / "runtime-spine.db")
        provider = FakeOpenCodeSessionProvider(root)
        service = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        started = service.start_test(request("plan-rotate", "PLAN-ROTATE-V"))
        mission_id = started["intake"]["intake"]["mission_id"]
        predecessor = started["planner_session"]["external_session"]["session_id"]
        provider.set_observation(predecessor, compaction_count=1, message_count=2, healthy=True)
        tick = service.supervise_once()
        planning_rotations = [item["result"] for item in tick["supervision"] if item.get("phase") == "PLANNING" and item.get("result", {}).get("status") == "ROTATED"]
        checks["preplan_planner_session_is_autonomously_supervised"] = bool(planning_rotations) and planning_rotations[0]["successor_session_id"] != predecessor

    # Reconciliation spans terminal Missions too; a package-owned Session
    # cannot leak merely because the Mission is no longer ACTIVE.
    with tempfile.TemporaryDirectory(prefix="pfc-g21-terminal-cleanup-") as td:
        root = Path(td); runtime = create_canonical_runtime(root, db_path=root / "runtime-spine.db")
        provider = FakeOpenCodeSessionProvider(root)
        service = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        started = service.start_test(request("terminal-cleanup", "TERM-V"))
        mission_id = started["intake"]["intake"]["mission_id"]
        package_session = started["planner_session"]["external_session"]["session_id"]
        unrelated = provider.create_session(title="Unrelated user session")
        cancel = runtime.execute(CommandEnvelope(
            "g21-test-cancel", "CANCEL_MISSION", mission_id, runtime.get_head_seq(mission_id),
            ActorRef("USER", "g21-test"), {"reason": "test terminal cleanup"},
            idempotency_key="g21-test-cancel", correlation_id="g21-test-cancel", schema_version=1,
        ))
        reconciled = service.reconcile_external_sessions(); remaining = {x.session_id for x in provider.list_sessions()}
        checks["terminal_mission_reconciliation_closes_package_session_not_unrelated"] = (
            cancel.ok and reconciled["status"] == "PASS" and package_session not in remaining and unrelated.session_id in remaining
        )

    # If a process dies after R2.3 commits a Plan but before G2.1 route facts
    # commit, Runtime must fail closed. It must not silently fall back to the
    # legacy EXECUTOR route and change Planner semantics.
    with tempfile.TemporaryDirectory(prefix="pfc-g21-route-commit-crash-") as td:
        root = Path(td); spine = root / "runtime-spine.db"
        runtime = create_canonical_runtime(root, db_path=spine)
        provider = FakeOpenCodeSessionProvider(root)
        service = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        started = service.start_test(request("route-commit-crash", "ROUTE-COMMIT"))
        mission_id = started["intake"]["intake"]["mission_id"]
        original_register = service._register_plan_routes
        service._register_plan_routes = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("SIMULATED_ROUTE_COMMIT_CRASH"))  # type: ignore[method-assign]
        route_commit_crashed = False
        try:
            service.propose_plan(mission_id, one_task("DIAGNOSIS"))
        except RuntimeError as exc:
            route_commit_crashed = "SIMULATED_ROUTE_COMMIT_CRASH" in str(exc)
        service._register_plan_routes = original_register  # type: ignore[method-assign]
        runtime2 = create_canonical_runtime(root, db_path=spine)
        recovered = G21AutonomousOrchestrationService(runtime2, root, session_provider=provider)
        route_fail_closed = False
        try:
            recovered.advance(mission_id)
        except RuntimeError as exc:
            route_fail_closed = "SESSION_ROUTER_ROUTE_REGISTRATION_INCOMPLETE" in str(exc)
        checks["partial_plan_route_commit_fails_closed_not_legacy_default"] = (
            route_commit_crashed and recovered.session_control.state(mission_id).routing_authority_enabled and route_fail_closed
        )

    # Crash after durable Core OPEN_SESSION but around bootstrap/BIND must
    # recover the same Session from R1, not create a second logical worker.
    with tempfile.TemporaryDirectory(prefix="pfc-g21-bootstrap-crash-") as td:
        root = Path(td); spine = root / "runtime-spine.db"
        runtime = create_canonical_runtime(root, db_path=spine)
        provider = CrashOnSendProvider(root)
        service = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        provider.crash_after_next_send = True
        planner_crashed = False
        try:
            service.start_test(request("planner-bootstrap-crash", "PLANNER-CRASH"))
        except RuntimeError as exc:
            planner_crashed = "SIMULATED_CRASH_AFTER_CONTEXT_ACCEPTED" in str(exc)
        runtime2 = create_canonical_runtime(root, db_path=spine)
        recovered_planner_service = G21AutonomousOrchestrationService(runtime2, root, session_provider=provider)
        resumed = recovered_planner_service.start_test(request("planner-bootstrap-retry", "PLANNER-CRASH"))
        planner_sessions = [x for x in provider.list_sessions() if "AITest Planner" in x.title]
        planner_intents = [x for x in recovered_planner_service.session_control.state(resumed["intake"]["intake"]["mission_id"]).provisions if x.phase == "PLANNING"]
        checks["planner_bootstrap_crash_recovers_same_session_and_binds_intent"] = (
            planner_crashed and resumed["resumed_existing_mission"] is True
            and len(planner_sessions) == 1 and len(planner_intents) == 1 and planner_intents[0].status == "BOUND"
        )

    with tempfile.TemporaryDirectory(prefix="pfc-g21-task-bootstrap-crash-") as td:
        root = Path(td); spine = root / "runtime-spine.db"
        runtime = create_canonical_runtime(root, db_path=spine)
        provider = CrashOnSendProvider(root)
        service = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        started = service.start_test(request("task-bootstrap-crash", "TASK-CRASH"))
        mission_id = started["intake"]["intake"]["mission_id"]
        provider.crash_after_next_send = True
        worker_crashed = False
        try:
            service.propose_plan(mission_id, one_task("EXECUTOR"))
        except RuntimeError as exc:
            worker_crashed = "SIMULATED_CRASH_AFTER_CONTEXT_ACCEPTED" in str(exc)
        runtime2 = create_canonical_runtime(root, db_path=spine)
        recovered = G21AutonomousOrchestrationService(runtime2, root, session_provider=provider)
        dispatch = recovered.advance(mission_id)
        task_id = dispatch["task_id"]
        task_intents = [x for x in recovered.session_control.state(mission_id).provisions if x.task_id == task_id and x.phase == "TASK_EXECUTION"]
        worker_sessions = [x for x in provider.list_sessions() if task_id in x.title]
        checks["task_bootstrap_crash_keeps_stable_provision_token_and_same_session"] = (
            worker_crashed and dispatch["status"] == "ACTIVE_DISPATCH_RECOVERED"
            and len(task_intents) == 1 and task_intents[0].status == "BOUND" and len(worker_sessions) == 1
        )

    # Durable provision intent closes the external-create crash window.
    with tempfile.TemporaryDirectory(prefix="pfc-g21-crash-") as td:
        root = Path(td)
        spine = root / "runtime-spine.db"
        runtime = create_canonical_runtime(root, db_path=spine)
        provider = CrashAfterExternalCreateProvider(root)
        service = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        started = service.start_test(request("crash", "CRASH-V"))
        mission_id = started["intake"]["intake"]["mission_id"]
        provider.crash_after_next_create = True
        crashed = False
        try:
            service.propose_plan(mission_id, one_task("EXECUTOR"))
        except RuntimeError as exc:
            crashed = "SIMULATED_HARD_WINDOW_AFTER_EXTERNAL_CREATE" in str(exc)
        tagged_before = [item for item in provider.list_sessions() if item.title.startswith("[AITEST_PROVISION:")]
        graph = service.runtime.replay_composed(mission_id).extension_state("r1_2_work_graph")
        active_task = next(item for item in graph.tasks if item.lifecycle_state.value == "ACTIVE")
        provision = next(item for item in service.session_control.state(mission_id).provisions if item.task_id == active_task.task_id)
        runtime2 = create_canonical_runtime(root, db_path=spine)
        repaired_service = G21AutonomousOrchestrationService(runtime2, root, session_provider=provider)
        repaired = repaired_service.advance(mission_id)
        tagged_after = [item for item in provider.list_sessions() if item.title.startswith("[AITEST_PROVISION:")]
        repaired_provision = repaired_service.session_control.state(mission_id).provision(provision.provision_token)
        checks["crash_after_external_create_recovers_same_provision_without_duplicate"] = (
            crashed
            and provision.status == "REQUESTED"
            and repaired["status"] == "DISPATCHED"
            and repaired_provision is not None and repaired_provision.status == "BOUND"
            and len(tagged_before) == 1 and len(tagged_after) == 1
            and tagged_before[0].session_id == tagged_after[0].session_id
        )

        unrelated = provider.create_session(title="User unrelated session")
        orphan = provider.create_session(title="[AITEST_PROVISION:ghost-token] orphan")
        reconciled = repaired_service.reconcile_external_sessions()
        remaining = {item.session_id for item in provider.list_sessions()}
        checks["reconciliation_closes_only_tagged_orphan_and_ignores_unrelated"] = (
            orphan.session_id not in remaining
            and unrelated.session_id in remaining
            and orphan.session_id in reconciled["orphan_package_sessions_closed"]
            and unrelated.session_id in reconciled["unrelated_untagged_sessions_ignored"]
        )

    # Crash after R2.5 successor Attempt/bootstrap but before G2.1 BIND/CLOSE/
    # COMPLETE must finalize the pending rotation instead of rotating again.
    with tempfile.TemporaryDirectory(prefix="pfc-g21-rotation-mid-crash-") as td:
        root = Path(td); spine = root / "runtime-spine.db"
        runtime = create_canonical_runtime(root, db_path=spine)
        provider = FakeOpenCodeSessionProvider(root)
        service = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        started = service.start_test(request("rotation-mid-crash", "ROT-MID"))
        mission_id = started["intake"]["intake"]["mission_id"]
        planned = service.propose_plan(mission_id, one_task("EXECUTOR")); first = planned["next"]
        predecessor = first["external_session"]["session_id"]; root_attempt = first["attempt"]["root_attempt_id"]
        original_bind = service._bind_provision_if_needed
        crash_flag = {"value": True}
        def crash_bind(mid: str, token: str, sid: str) -> None:
            if crash_flag["value"] and "TASK_ROTATION" in next((x.phase for x in service.session_control.state(mid).provisions if x.provision_token == token), ""):
                crash_flag["value"] = False
                raise RuntimeError("SIMULATED_CRASH_BEFORE_G21_ROTATION_BIND")
            original_bind(mid, token, sid)
        service._bind_provision_if_needed = crash_bind  # type: ignore[method-assign]
        provider.set_observation(predecessor, message_count=60, healthy=True)
        mid_crashed = False
        try:
            service.supervise_once()
        except RuntimeError as exc:
            mid_crashed = "SIMULATED_CRASH_BEFORE_G21_ROTATION_BIND" in str(exc)
        sessions_after_crash = tuple(provider.list_sessions())
        runtime2 = create_canonical_runtime(root, db_path=spine)
        recovered = G21AutonomousOrchestrationService(runtime2, root, session_provider=provider)
        finalized = recovered.rotate_session(mission_id, task_id=first["task_id"], reasons=["RECOVERY"])
        final_status = recovered.status(mission_id); attempts = final_status["execution"]["attempts"]
        rotations = recovered.session_control.state(mission_id).rotations
        checks["mid_rotation_crash_finalizes_same_successor_without_second_rotation"] = (
            mid_crashed and finalized.get("recovered_pending_rotation") is True
            and len(provider.list_sessions()) <= len(sessions_after_crash)
            and attempts[-1]["root_attempt_id"] == root_attempt and len(attempts) == 2
            and rotations[-1].status == "COMPLETED"
            and final_status["core"]["sessions"][predecessor]["status"] == "CLOSED"
        )

    tool_source = (WORKSPACE_ROOT / ".opencode/tools/aitest.ts").read_text(encoding="utf-8")
    scheduler_agent = (WORKSPACE_ROOT / ".opencode/agents/aitest-scheduler.md").read_text(encoding="utf-8")
    executor_agent = (WORKSPACE_ROOT / ".opencode/agents/aitest-executor.md").read_text(encoding="utf-8")
    checks["agent_prompts_and_tools_do_not_own_session_lifecycle"] = (
        'action: tool.schema.string().describe("status|advance|dispatch_next")' in tool_source
        and 'action: tool.schema.string().describe("status|report_task_outcome|record_cursor|recover_cursor|register_capability|validate_executor|execute_capability|capability_human_gate|request_human_takeover|reconcile_human_takeover|complete_human_takeover|record_step_result|create_batch")' in tool_source
        and "create_session" not in tool_source.split("export const executor = tool({", 1)[1].split("export const g4_director", 1)[0]
        and "rotate_session" not in tool_source.split("export const executor = tool({", 1)[1].split("export const g4_director", 1)[0]
        and "close_session" not in tool_source.split("export const executor = tool({", 1)[1].split("export const g4_director", 1)[0]
        and "Never call Session observation/rotation actions" in scheduler_agent
        and "Do not observe, create, close, or rotate your own Session" in executor_agent
    )
    checks["generic_worker_outcome_surface_exists_for_router_roles"] = (
        "export const worker = tool" in tool_source
        and "aitest_worker: allow" in (WORKSPACE_ROOT / ".opencode/agents/aitest-evaluator.md").read_text(encoding="utf-8")
        and "aitest_worker: allow" in (WORKSPACE_ROOT / ".opencode/agents/aitest-diagnosis.md").read_text(encoding="utf-8")
    )

    # Unknown provider/list shapes fail closed rather than being converted to
    # healthy/empty facts that could cause duplicate Session provisioning.
    checks["canonical_observation_missing_reachability_is_not_assumed_reachable"] = (
        SessionObservation.from_provider("unknown-session", {}).reachable is False
    )
    provider_contract = DirectoryScopedOpenCodeSessionProvider(WORKSPACE_ROOT)
    provider_contract._request = lambda *_args, **_kwargs: {"unexpected": "shape"}  # type: ignore[method-assign]
    list_failed_closed = False
    observation_failed_closed = False
    try:
        provider_contract.list_sessions()
    except RuntimeError as exc:
        list_failed_closed = "OPENCODE_SESSION_LIST_INVALID" in str(exc)
    try:
        provider_contract.observe_session("session-x")
    except RuntimeError as exc:
        observation_failed_closed = "OPENCODE_SESSION_OBSERVATION_INVALID" in str(exc)
    checks["unknown_opencode_session_payload_shapes_fail_closed"] = list_failed_closed and observation_failed_closed

    # Reconciliation must never trust a Session-list row that cannot prove
    # identity/title or that contradicts the explicit project directory scope.
    scoped = DirectoryScopedOpenCodeSessionProvider(WORKSPACE_ROOT)
    scoped._request = lambda *_args, **_kwargs: [{"id": "other", "title": "[AITEST_PROVISION:token] other", "directory": str(WORKSPACE_ROOT.parent)}]  # type: ignore[method-assign]
    directory_mismatch_failed = False
    try:
        scoped.list_sessions()
    except RuntimeError as exc:
        directory_mismatch_failed = "OPENCODE_SESSION_DIRECTORY_SCOPE_MISMATCH" in str(exc)
    missing_title = DirectoryScopedOpenCodeSessionProvider(WORKSPACE_ROOT)
    missing_title._request = lambda *_args, **_kwargs: [{"id": "missing-title"}]  # type: ignore[method-assign]
    missing_title_failed = False
    try:
        missing_title.list_sessions()
    except RuntimeError as exc:
        missing_title_failed = "OPENCODE_SESSION_LIST_ENTRY_INVALID" in str(exc)
    checks["session_list_directory_and_identity_scope_fail_closed"] = directory_mismatch_failed and missing_title_failed

    payload = {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}
    import json
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
