"""G2.1 authoritative Session Router + autonomous Session Supervisor.

This layer is additive over the frozen G2 orchestration implementation.  G2
continues to decide Mission/Plan/Task scheduling.  G2.1 owns WHO/WHERE Session
routing, durable external-session provisioning, autonomous observation and
rotation, and reconciliation.  Agents never own their Session lifecycle.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from ..autonomous_orchestration import (
    AutonomousOrchestrationService,
    DEFAULT_WORKER_AGENT,
    DirectoryScopedOpenCodeSessionProvider,
    ExternalSession,
    G2_SCHEMA,
    OPENCODE_AGENT_CAPABILITY,
    OpenCodeSessionAdmissionPending,
    OpenCodeSessionProvider,
    _mapping,
    _text,
    _utc_now,
)
from ..durable_core import ActorRef, CommandEnvelope, MissionStatus, RuntimeService, canonical_sha256
from ..r2_3 import PlannerInput
from ..work_graph import TaskLifecycleState, WorkGraphState
from .router import AgentRoleRegistry, RouteDecision, SessionRouter, TASK_OUTCOME_REPORT
from .service import SessionControlApplicationService
from .supervisor import RotationPolicy, SessionObservation


class ProvisioningOpenCodeSessionProvider:
    """Adds deterministic provision-token recovery to an OpenCode provider.

    The token itself is durable in the R1 Event Stream through the G2.1
    extension before the external side effect occurs.  This wrapper owns no
    authoritative state; its context only scopes one create call.
    """

    def __init__(self, delegate: OpenCodeSessionProvider) -> None:
        self.delegate = delegate
        self._token: str | None = None
        self._friendly_title: str | None = None

    @contextmanager
    def provision(self, token: str, friendly_title: str) -> Iterator[None]:
        if self._token is not None:
            raise RuntimeError("NESTED_SESSION_PROVISION_CONTEXT_FORBIDDEN")
        self._token = _text(token, "provision_token")
        self._friendly_title = _text(friendly_title, "friendly_title")
        try:
            yield
        finally:
            self._token = None
            self._friendly_title = None

    @staticmethod
    def title_for(token: str, friendly_title: str) -> str:
        return f"[AITEST_PROVISION:{token}] {friendly_title}"

    @staticmethod
    def token_from_title(title: str) -> str | None:
        prefix = "[AITEST_PROVISION:"
        if not isinstance(title, str) or not title.startswith(prefix):
            return None
        end = title.find("]", len(prefix))
        return title[len(prefix):end] if end > len(prefix) else None

    def health(self) -> Mapping[str, Any]:
        return self.delegate.health()

    def list_sessions(self) -> tuple[ExternalSession, ...]:
        return self.delegate.list_sessions()

    def create_session(self, *, title: str, parent_id: str | None = None) -> ExternalSession:
        if self._token is None:
            # G2.1 product composition forbids ungoverned create calls.
            raise RuntimeError("SESSION_ROUTER_UNGOVERNED_CREATE_FORBIDDEN")
        effective = self.title_for(self._token, self._friendly_title or title)
        matches = [item for item in self.delegate.list_sessions() if item.title == effective]
        if len(matches) > 1:
            raise RuntimeError(f"SESSION_PROVISION_DUPLICATE_EXTERNAL_MATCH: {self._token}")
        if matches:
            return matches[0]
        return self.delegate.create_session(title=effective, parent_id=parent_id)

    def send_context(self, *, session_id: str, agent: str, text: str) -> Mapping[str, Any]:
        return self.delegate.send_context(session_id=session_id, agent=agent, text=text)

    def delete_session(self, session_id: str) -> bool:
        return self.delegate.delete_session(session_id)

    def observe_session(self, session_id: str) -> Mapping[str, Any]:
        return self.delegate.observe_session(session_id)


class G21AutonomousOrchestrationService(AutonomousOrchestrationService):
    """G2 orchestration with Runtime-owned routing and autonomous supervision."""

    def __init__(
        self,
        runtime: RuntimeService,
        workspace_root: str | Path,
        *,
        session_provider: OpenCodeSessionProvider | None = None,
    ) -> None:
        base_provider = session_provider or DirectoryScopedOpenCodeSessionProvider(workspace_root)
        self.raw_session_provider = base_provider
        self.provisioning_provider = ProvisioningOpenCodeSessionProvider(base_provider)
        super().__init__(runtime, workspace_root, session_provider=self.provisioning_provider)
        self.session_control = SessionControlApplicationService(runtime)
        self.role_registry = AgentRoleRegistry.default()
        self.session_router = SessionRouter(self.role_registry)
        self.rotation_policy = RotationPolicy()

    def status(self, mission_id: str | None = None) -> dict[str, Any]:
        result = super().status(mission_id)
        result["g2_1_session_management"] = {
            "session_router": "RUNTIME_OWNED",
            "session_supervisor": "CONTROL_LOOP_OWNED",
            "agent_owns_session_lifecycle": False,
            "bank_opencode_observation_field_validation": "PENDING",
        }
        if mission_id is not None:
            result["session_control"] = self.session_control.state(str(mission_id)).to_dict()
        return result

    @staticmethod
    def _provision_token(*parts: str) -> str:
        return "g21-" + canonical_sha256({"parts": list(parts)})[:28]

    def _request_provision_if_needed(
        self,
        mission_id: str,
        *,
        token: str,
        task_id: str | None,
        logical_agent_id: str,
        root_attempt_id: str | None,
        role: str,
        agent_name: str,
        phase: str,
        title: str,
    ) -> None:
        existing = self.session_control.state(mission_id).provision(token)
        if existing is None:
            self.session_control.request_provision(
                mission_id,
                provision_token=token,
                task_id=task_id,
                root_attempt_id=root_attempt_id,
                logical_agent_id=logical_agent_id,
                role=role,
                agent_name=agent_name,
                phase=phase,
                title=ProvisioningOpenCodeSessionProvider.title_for(token, title),
            )

    def _bind_provision_if_needed(self, mission_id: str, token: str, session_id: str) -> None:
        existing = self.session_control.state(mission_id).provision(token)
        if existing is None:
            raise RuntimeError("SESSION_PROVISION_INTENT_MISSING")
        if existing.status == "BOUND":
            if existing.external_session_id != session_id:
                raise RuntimeError("SESSION_PROVISION_BINDING_CONFLICT")
            return
        self.session_control.bind_provision(mission_id, token, session_id)

    def _planning_context_message(self, mission_id: str, logical_agent_id: str) -> str:
        composed = self.runtime.replay_composed(mission_id)
        mission = composed.core_state.mission
        if mission is None or mission.status != MissionStatus.ACTIVE or not mission.active_goal_id:
            raise RuntimeError("ACTIVE_MISSION_AND_GOAL_REQUIRED_FOR_PLANNING")
        goal = composed.core_state.goal(mission.active_goal_id)
        if goal is None:
            raise RuntimeError("ACTIVE_GOAL_NOT_FOUND")
        envelope = {
            "schema": "aitest.planning-context.v1",
            "authority": "R1_EVENT_STREAM",
            "conversation_is_not_truth": True,
            "mission_id": mission_id,
            "goal": goal.to_dict(),
            "logical_agent_id": logical_agent_id,
            "instruction": (
                "Analyze the durable Goal and governed evidence. Author a bounded semantic Plan candidate, "
                "then persist it only through the canonical Planner tool. Unknown facts remain KNOWLEDGE_GAP. "
                "Session lifecycle is owned by the Runtime Session Router/Supervisor; do not create or rotate Sessions."
            ),
        }
        return "AITEST_CANONICAL_PLANNING_CONTEXT\n" + json.dumps(envelope, ensure_ascii=False, sort_keys=True)

    def open_planning_session(self, mission_id: str) -> dict[str, Any]:
        mission_id = _text(mission_id, "mission_id")
        composed = self.runtime.replay_composed(mission_id)
        mission = composed.core_state.mission
        if mission is None or mission.status != MissionStatus.ACTIVE or not mission.active_goal_id:
            raise RuntimeError("ACTIVE_MISSION_AND_GOAL_REQUIRED_FOR_PLANNING")
        goal = composed.core_state.goal(mission.active_goal_id)
        if goal is None:
            raise RuntimeError("ACTIVE_GOAL_NOT_FOUND")
        self.session_control.enable_routing_authority(mission_id)
        role = self.role_registry.resolve("PLANNER")
        logical_agent_id = self.session_router.logical_agent_id(role.agent_name, f"planning:{mission_id}:{goal.revision}")
        token = self._provision_token(mission_id, logical_agent_id, "PLANNING")
        title = f"AITest Planner · {mission_id}"
        self._request_provision_if_needed(
            mission_id, token=token, task_id=None, logical_agent_id=logical_agent_id, root_attempt_id=None,
            role=role.role, agent_name=role.agent_name, phase="PLANNING", title=title,
        )
        with self.provisioning_provider.provision(token, title):
            result = super().open_planning_session(mission_id)
        session_id = result.get("session_id") or (result.get("external_session") or {}).get("session_id")
        if not session_id:
            raise RuntimeError("PLANNER_SESSION_ID_MISSING_AFTER_PROVISION")
        # If a previous process crashed after durable OPEN_SESSION but before
        # (or during) Planner bootstrap, frozen G2 returns ALREADY_OPEN.  Re-send
        # the canonical ContextPack so recovery never depends on conversation.
        if result.get("status") == "ALREADY_OPEN":
            self.raw_session_provider.send_context(
                session_id=str(session_id), agent=role.agent_name,
                text=self._planning_context_message(mission_id, logical_agent_id),
            )
        self._bind_provision_if_needed(mission_id, token, str(session_id))
        return {**result, "session_router": "G2_1", "provision_token": token}

    def _register_plan_routes(self, mission_id: str, original_tasks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        _composed, graph, _goal, current_plan = self._active_plan_context(mission_id)
        if current_plan is None or current_plan.current_revision_id is None:
            raise RuntimeError("PLAN_REVISION_REQUIRED_FOR_ROUTE_REGISTRATION")
        canonical = [
            task for task in graph.tasks
            if task.plan_id == current_plan.plan_id and task.plan_revision_id == current_plan.current_revision_id
        ]
        if len(canonical) != len(original_tasks):
            raise RuntimeError("PLAN_ROUTE_TASK_CARDINALITY_MISMATCH")
        registered: list[dict[str, Any]] = []
        for raw, task in zip(original_tasks, canonical):
            routing = raw.get("routing") if isinstance(raw, Mapping) else None
            routing = dict(routing) if isinstance(routing, Mapping) else {}
            role_name = str(routing.get("role") or "EXECUTOR").upper()
            role = self.role_registry.resolve(role_name)
            requested_agent = routing.get("agent_name")
            if requested_agent is not None and str(requested_agent) != role.agent_name:
                raise RuntimeError("SESSION_ROUTER_ROLE_AGENT_CONFLICT")
            requested_caps = routing.get("required_capabilities") or []
            if not isinstance(requested_caps, list) or not all(isinstance(item, str) and item for item in requested_caps):
                raise ValueError("routing.required_capabilities must be a string array")
            caps = list(dict.fromkeys([OPENCODE_AGENT_CAPABILITY, TASK_OUTCOME_REPORT, *requested_caps]))
            self.session_control.register_task_route(
                mission_id,
                task_id=task.task_id,
                role=role.role,
                agent_name=role.agent_name,
                required_capabilities=list(caps),
                isolation_policy=str(routing.get("isolation_policy") or "DEDICATED_TASK_SESSION"),
                parallelism_policy=str(routing.get("parallelism_policy") or "SERIAL"),
                source="PLANNER_PROPOSAL" if routing else "DEFAULT_G2",
            )
            registered.append(self.session_control.state(mission_id).route(task.task_id).to_dict())
        return registered

    def _close_planning_sessions_after_plan(self, mission_id: str) -> list[str]:
        closed: list[str] = []
        composed = self.runtime.replay_composed(mission_id)
        for session in list(composed.core_state.sessions):
            attrs = dict(session.attributes or {})
            if session.status.value != "OPEN" or attrs.get("phase") != "PLANNING":
                continue
            close_id = f"g2.1:planning:{session.session_id}:PLAN_ACCEPTED:CLOSE"
            result = self.runtime.execute(CommandEnvelope(
                close_id, "CLOSE_SESSION", mission_id, self.runtime.get_head_seq(mission_id),
                ActorRef("SYSTEM", "g2.1-session-router"), {"reason": "PLAN_ACCEPTED"},
                session_id=session.session_id, idempotency_key=close_id, correlation_id=close_id, schema_version=1,
            ))
            if not result.ok:
                if result.error:
                    raise result.error
                raise RuntimeError("PLANNER_SESSION_CLOSE_AFTER_PLAN_REJECTED")
            try:
                self.raw_session_provider.delete_session(session.session_id)
            except Exception:
                pass
            closed.append(session.session_id)
        return closed

    def propose_plan(self, mission_id: str, proposal: Mapping[str, Any]) -> dict[str, Any]:
        """Run frozen R2.3, persist G2.1 routes, then hand off to Scheduler."""
        mission_id = _text(mission_id, "mission_id")
        proposal = _mapping(proposal, "proposal")
        tasks = proposal.get("tasks", proposal.get("task_definitions"))
        if not isinstance(tasks, list) or not tasks:
            raise ValueError("proposal.tasks must be a non-empty array")
        normalized_tasks = [dict(item) if isinstance(item, Mapping) else item for item in tasks]
        # Validate routing feasibility before R2.3 mutates the durable WorkGraph.
        for raw in normalized_tasks:
            if not isinstance(raw, Mapping):
                continue
            routing = raw.get("routing")
            routing = dict(routing) if isinstance(routing, Mapping) else {}
            role_name = str(routing.get("role") or "EXECUTOR").upper()
            role = self.role_registry.resolve(role_name)
            requested_agent = routing.get("agent_name")
            if requested_agent is not None and str(requested_agent) != role.agent_name:
                raise RuntimeError("SESSION_ROUTER_ROLE_AGENT_CONFLICT")
            requested_caps = routing.get("required_capabilities") or []
            if not isinstance(requested_caps, list) or not all(isinstance(value, str) and value for value in requested_caps):
                raise ValueError("routing.required_capabilities must be a string array")
            caps = list(dict.fromkeys([OPENCODE_AGENT_CAPABILITY, TASK_OUTCOME_REPORT, *requested_caps]))
            missing = set(caps) - set(role.capabilities)
            if missing:
                raise RuntimeError(f"SESSION_ROUTER_CAPABILITY_UNAVAILABLE: {sorted(missing)}")
        composed, work_graph, goal, current_plan = self._active_plan_context(mission_id)
        current_revision = work_graph.revision(current_plan.current_revision_id) if current_plan and current_plan.current_revision_id else None
        stable_proposal = {
            "objective": proposal.get("objective"),
            "constraints": proposal.get("constraints", []),
            # Routing metadata is not R2.3 WorkGraph content; keep the frozen R2.3
            # candidate semantic surface unchanged.
            "tasks": [({k: v for k, v in item.items() if k != "routing"} if isinstance(item, Mapping) else item) for item in tasks],
            "dependencies": proposal.get("dependencies", []),
        }
        proposal_digest = canonical_sha256(stable_proposal)
        request_id = str(proposal.get("planner_request_id") or f"g2:plan:{mission_id}:{proposal_digest[:20]}")
        item = PlannerInput(
            mission_id=mission_id,
            active_goal_id=goal.goal_id,
            goal_revision=goal.revision,
            goal_definition_digest=canonical_sha256(goal.definition),
            scope_digest=goal.definition.get("scope_digest") or canonical_sha256(goal.definition.get("execution_scope", {})),
            planning_cursor=self.runtime.get_head_seq(mission_id),
            planner_request_id=request_id,
            goal_definition=goal.definition,
            objective=proposal.get("objective"),
            constraints=proposal.get("constraints", []),
            task_definitions=stable_proposal["tasks"],
            dependencies=proposal.get("dependencies", []),
            actor=proposal.get("actor") or {"type": "AGENT", "id": "aitest-planner"},
            current_content_hash=current_revision.content_hash if current_revision is not None else None,
            current_revision_id=current_revision.revision_id if current_revision is not None else None,
            existing_plan_id=current_plan.plan_id if current_plan is not None else None,
            operation="REPLAN" if current_plan is not None else "PLAN",
        )
        result = self.planner.plan_or_revise(item)
        accepted = result.outcome in {"APPLIED", "DUPLICATE", "NO_CHANGE"}
        routes = self._register_plan_routes(mission_id, normalized_tasks) if accepted else []
        closed_planner_sessions = self._close_planning_sessions_after_plan(mission_id) if accepted else []
        next_state = self.advance(mission_id) if accepted else None
        return {
            "schema_version": G2_SCHEMA,
            "status": "PASS" if accepted else result.outcome,
            "truth_source": "R1_EVENT_STREAM",
            "operation": "PLAN_PROPOSAL",
            "ai_authored_proposal_digest": proposal_digest,
            "runtime_governed_result": result.to_dict(),
            "route_requirements": routes,
            "closed_planner_sessions": closed_planner_sessions,
            "autonomous_handoff": "SCHEDULER" if accepted else None,
            "next": next_state,
            "head_seq": self.runtime.get_head_seq(mission_id),
        }

    def _context_message(self, *, mission_id: str, plan_id: str, revision_id: str, task_id: str, attempt: Any, agent: str) -> str:
        """Build worker context without delegating Session lifecycle to the Agent.

        Frozen G2 used an Agent-driven ``observe_session`` reminder.  G2.1
        supersedes that product behavior with the autonomous Supervisor/Control
        Loop, while retaining the same durable Task/Attempt identity envelope.
        """
        raw = super()._context_message(
            mission_id=mission_id, plan_id=plan_id, revision_id=revision_id,
            task_id=task_id, attempt=attempt, agent=agent,
        )
        prefix = "AITEST_CANONICAL_CONTEXT\n"
        if not raw.startswith(prefix):
            raise RuntimeError("G2_1_CONTEXT_ENVELOPE_INVALID")
        envelope = json.loads(raw[len(prefix):])
        envelope["session_lifecycle_owner"] = "G2_1_SESSION_ROUTER_SUPERVISOR"
        envelope["instruction"] = (
            "Resume only this durable Task. Read canonical tools before acting. "
            "Do not observe, create, close, or rotate your own Session; the G2.1 Session Supervisor/Router owns Session lifecycle. "
            "Report terminal outcome with the exact mission_id/task_id/attempt_id/session_id from this envelope. "
            "Do not reconstruct Mission state from conversation history and do not silently replan."
        )
        return prefix + json.dumps(envelope, ensure_ascii=False, sort_keys=True)

    def _ensure_default_route(self, mission_id: str, task_id: str) -> None:
        state = self.session_control.state(mission_id)
        if state.route(task_id) is not None:
            return
        if state.routing_authority_enabled:
            # This Mission entered planning under G2.1. Missing route facts now
            # mean an interrupted/partial Planner->Router commit, not a legacy
            # G2 plan. Fail closed instead of silently changing the AI route.
            raise RuntimeError(f"SESSION_ROUTER_ROUTE_REGISTRATION_INCOMPLETE: {task_id}")
        role = self.role_registry.resolve("EXECUTOR")
        self.session_control.register_task_route(
            mission_id, task_id=task_id, role=role.role, agent_name=role.agent_name,
            required_capabilities=[OPENCODE_AGENT_CAPABILITY, TASK_OUTCOME_REPORT],
            isolation_policy="DEDICATED_TASK_SESSION", parallelism_policy="SERIAL",
            source="DEFAULT_G2",
        )

    def _route_task(self, mission_id: str, task_id: str) -> RouteDecision:
        self._ensure_default_route(mission_id, task_id)
        composed = self.runtime.replay_composed(mission_id)
        execution = composed.extension_state("r1_3b_execution_resume")
        latest = execution.latest_attempt(task_id) if execution is not None else None
        session = composed.core_state.session(latest.runtime_session_id) if latest is not None else None
        return self.session_router.route_task(
            self.session_control.state(mission_id), task_id=task_id, latest_attempt=latest, session=session,
        )

    def _provision_active_task_session(
        self,
        *,
        mission_id: str,
        plan_id: str,
        revision_id: str,
        task_id: str,
        agent: str,
        parent_session_id: str | None = None,
    ) -> dict[str, Any]:
        route = self._route_task(mission_id, task_id)
        if route.decision == "BLOCK":
            raise RuntimeError(f"SESSION_ROUTER_BLOCKED: {route.reason}")
        logical_agent_id = route.logical_agent_id
        composed = self.runtime.replay_composed(mission_id)
        execution = composed.extension_state("r1_3b_execution_resume")
        latest = execution.latest_attempt(task_id) if execution is not None else None
        phase = "TASK_EXECUTION" if latest is None else ("TASK_ROTATION" if route.decision == "ROTATE" else "TASK_EXECUTION")
        predecessor = latest.runtime_session_id if latest is not None else "NONE"
        # Initial task provisioning token is stable across a crash that happens
        # after OPEN_SESSION/Attempt creation but before ProvisionIntent BIND.
        # Rotation is intentionally predecessor-specific.
        token_tail = predecessor if phase == "TASK_ROTATION" else task_id
        token = self._provision_token(mission_id, logical_agent_id, phase, token_tail)
        title = f"AITest {route.agent_name} · {mission_id} · {task_id}"
        self._request_provision_if_needed(
            mission_id, token=token, task_id=task_id, logical_agent_id=logical_agent_id,
            root_attempt_id=latest.root_attempt_id if latest is not None else None, role=route.role, agent_name=route.agent_name, phase=phase, title=title,
        )
        if route.decision == "ROTATE" and latest is not None:
            result = self.rotate_session(mission_id, task_id=task_id, reasons=[route.reason])
            return {**result, "status": "DISPATCH_REPAIRED_BY_ROTATION", "route": route.to_dict()}
        with self.provisioning_provider.provision(token, title):
            result = super()._provision_active_task_session(
                mission_id=mission_id, plan_id=plan_id, revision_id=revision_id,
                task_id=task_id, agent=route.agent_name, parent_session_id=parent_session_id,
            )
        session_id = result.get("session_id") or (result.get("external_session") or {}).get("session_id")
        if not session_id:
            raise RuntimeError("TASK_SESSION_ID_MISSING_AFTER_PROVISION")
        self._bind_provision_if_needed(mission_id, token, str(session_id))
        return {**result, "route": route.to_dict(), "provision_token": token}

    def report_task_outcome(
        self,
        mission_id: str,
        *,
        task_id: str,
        attempt_id: str,
        session_id: str,
        outcome: str,
        summary: str,
        external_references: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Accept outcome only from the Session durably assigned by Router.

        The base G2 contract already binds Mission/Task/Attempt/Session IDs.
        G2.1 additionally binds that Session to the durable route's agent so a
        route drift cannot complete the logical Task under a different role.
        """
        mission_id = _text(mission_id, "mission_id")
        task_id = _text(task_id, "task_id")
        session_id = _text(session_id, "session_id")
        route = self._route_task(mission_id, task_id)
        if route.decision == "BLOCK":
            raise RuntimeError(f"SESSION_ROUTER_BLOCKED: {route.reason}")
        composed = self.runtime.replay_composed(mission_id)
        execution = composed.extension_state("r1_3b_execution_resume")
        latest = execution.latest_attempt(task_id) if execution is not None else None
        if latest is None:
            raise RuntimeError("ACTIVE_EXECUTION_ATTEMPT_REQUIRED")
        if latest.attempt_id != attempt_id:
            raise RuntimeError(f"TASK_OUTCOME_ATTEMPT_MISMATCH: expected={latest.attempt_id} actual={attempt_id}")
        if latest.runtime_session_id != session_id:
            raise RuntimeError(f"TASK_OUTCOME_SESSION_MISMATCH: expected={latest.runtime_session_id} actual={session_id}")
        session = composed.core_state.session(session_id)
        if session is None:
            raise RuntimeError("TASK_OUTCOME_SESSION_NOT_FOUND")
        r25_state = composed.extension_state("r2_5_session_orchestration")
        binding = None
        if r25_state is not None:
            binding = next((x for x in r25_state.bindings if x.root_attempt_id == latest.root_attempt_id), None)
        if binding is None or binding.logical_agent_id != route.logical_agent_id:
            actual = getattr(binding, "logical_agent_id", None) if binding is not None else None
            raise RuntimeError(
                f"TASK_OUTCOME_ROUTE_LOGICAL_AGENT_MISMATCH: expected={route.logical_agent_id} actual={actual or 'UNKNOWN'}"
            )
        # Initial G2 sessions carry opencode_agent directly. Frozen R2.5
        # successor Sessions may omit it while preserving the immutable logical
        # Agent binding to the same root Attempt, so only reject a present
        # contradictory attribute.
        actual_agent = str((session.attributes or {}).get("opencode_agent") or "")
        if actual_agent and actual_agent != route.agent_name:
            raise RuntimeError(
                f"TASK_OUTCOME_ROUTE_AGENT_MISMATCH: expected={route.agent_name} actual={actual_agent}"
            )
        return super().report_task_outcome(
            mission_id, task_id=task_id, attempt_id=attempt_id, session_id=session_id,
            outcome=outcome, summary=summary, external_references=external_references,
        )

    def advance(self, mission_id: str, *, agent: str | None = None, parent_session_id: str | None = None) -> dict[str, Any]:
        if agent is not None:
            raise RuntimeError("SESSION_ROUTER_AGENT_OVERRIDE_FORBIDDEN")
        result = super().dispatch_next(mission_id, agent=DEFAULT_WORKER_AGENT, parent_session_id=parent_session_id)
        return {**result, "orchestration_advanced": True, "session_router": "G2_1"}

    def dispatch_next(self, mission_id: str, *, agent: str | None = None, parent_session_id: str | None = None) -> dict[str, Any]:
        if agent is not None:
            raise RuntimeError("SESSION_ROUTER_AGENT_OVERRIDE_FORBIDDEN")
        return {**super().dispatch_next(mission_id, agent=DEFAULT_WORKER_AGENT, parent_session_id=parent_session_id), "session_router": "G2_1"}

    def _rotation_record_id(self, mission_id: str, task_id: str, predecessor_session_id: str) -> str:
        return "g21-rotate-" + canonical_sha256({"mission": mission_id, "task": task_id, "predecessor": predecessor_session_id})[:24]

    def _pending_rotation(self, mission_id: str, task_id: str) -> Any | None:
        return next((
            item for item in reversed(self.session_control.state(mission_id).rotations)
            if item.task_id == task_id and item.status == "REQUIRED"
        ), None)

    def _close_predecessor_after_successor(
        self, mission_id: str, *, rotation_id: str, predecessor_session_id: str, reason: str,
    ) -> None:
        after = self.runtime.replay_composed(mission_id)
        predecessor = after.core_state.session(predecessor_session_id)
        if predecessor is not None and predecessor.status.value != "CLOSED":
            close_id = f"g2.1:rotation:{rotation_id}:CLOSE_PREDECESSOR"
            close = self.runtime.execute(CommandEnvelope(
                close_id, "CLOSE_SESSION", mission_id, self.runtime.get_head_seq(mission_id),
                ActorRef("SYSTEM", "g2.1-session-supervisor"),
                {"reason": reason, "rotation_id": rotation_id},
                session_id=predecessor_session_id, idempotency_key=close_id,
                correlation_id=rotation_id, schema_version=1,
            ))
            if not close.ok:
                if close.error:
                    raise close.error
                raise RuntimeError("ROTATION_PREDECESSOR_CLOSE_REJECTED")
        try:
            self.raw_session_provider.delete_session(predecessor_session_id)
        except Exception:
            # Durable successor/closure is authoritative; external deletion is
            # retried by reconciliation rather than undoing logical rotation.
            pass

    def rotate_session(
        self,
        mission_id: str,
        *,
        task_id: str,
        agent: str | None = None,
        reasons: list[str] | None = None,
    ) -> dict[str, Any]:
        if agent is not None:
            raise RuntimeError("SESSION_ROUTER_AGENT_OVERRIDE_FORBIDDEN")
        mission_id = _text(mission_id, "mission_id")
        task_id = _text(task_id, "task_id")
        route = self._route_task(mission_id, task_id)
        composed = self.runtime.replay_composed(mission_id)
        execution = composed.extension_state("r1_3b_execution_resume")
        latest = execution.latest_attempt(task_id) if execution is not None else None
        if latest is None:
            raise RuntimeError("EXECUTION_ATTEMPT_NOT_FOUND_FOR_ROTATION")

        pending = self._pending_rotation(mission_id, task_id)
        if pending is not None:
            rotation_id = pending.rotation_id
            predecessor_session_id = pending.predecessor_session_id
            root_attempt_id = pending.root_attempt_id
            rotation_reasons = list(pending.reasons)
        else:
            predecessor_session_id = latest.runtime_session_id
            root_attempt_id = latest.root_attempt_id
            rotation_id = self._rotation_record_id(mission_id, task_id, predecessor_session_id)
            existing_rotation = self.session_control.state(mission_id).rotation(rotation_id)
            if existing_rotation is not None and existing_rotation.status == "COMPLETED":
                return {
                    "schema_version": G2_SCHEMA, "status": "ROTATED", "truth_source": "R1_EVENT_STREAM",
                    "rotation_id": rotation_id, "predecessor_session_id": existing_rotation.predecessor_session_id,
                    "successor_session_id": existing_rotation.successor_session_id,
                    "root_attempt_id": existing_rotation.root_attempt_id, "idempotent_replay": True,
                }
            rotation_reasons = list(reasons or [route.reason or "RUNTIME_POLICY"])
            self.session_control.request_rotation(
                mission_id,
                {"rotation_id": rotation_id, "task_id": task_id, "root_attempt_id": root_attempt_id,
                 "predecessor_session_id": predecessor_session_id, "reasons": rotation_reasons},
            )

        token = self._provision_token(mission_id, route.logical_agent_id, "TASK_ROTATION", predecessor_session_id)
        title = f"AITest {route.agent_name} resume · {mission_id} · {task_id}"
        self._request_provision_if_needed(
            mission_id, token=token, task_id=task_id, logical_agent_id=route.logical_agent_id,
            root_attempt_id=root_attempt_id, role=route.role, agent_name=route.agent_name, phase="TASK_ROTATION", title=title,
        )

        # Crash recovery after R2.5 has already created a successor Attempt but
        # before G2.1 BIND/CLOSE/COMPLETE.  Finalize the same logical rotation;
        # never rotate the successor again.
        composed = self.runtime.replay_composed(mission_id)
        execution = composed.extension_state("r1_3b_execution_resume")
        latest = execution.latest_attempt(task_id) if execution is not None else None
        if (latest is not None and latest.root_attempt_id == root_attempt_id
                and latest.runtime_session_id != predecessor_session_id):
            successor = latest.runtime_session_id
            successor_core = composed.core_state.session(successor)
            tagged = {item.session_id for item in self.raw_session_provider.list_sessions()
                      if item.title == ProvisioningOpenCodeSessionProvider.title_for(token, title)}
            if successor_core is None or successor_core.status.value != "OPEN" or successor not in tagged:
                raise RuntimeError("ROTATION_RECOVERY_SUCCESSOR_AMBIGUOUS")
            self.raw_session_provider.send_context(
                session_id=successor, agent=route.agent_name,
                text=self._context_message(
                    mission_id=mission_id, plan_id=latest.plan_id, revision_id=latest.plan_revision_id,
                    task_id=task_id, attempt=latest, agent=route.agent_name,
                ),
            )
            self._bind_provision_if_needed(mission_id, token, successor)
            self._close_predecessor_after_successor(
                mission_id, rotation_id=rotation_id, predecessor_session_id=predecessor_session_id,
                reason="G2_1_SUCCESSOR_BOOTSTRAPPED",
            )
            self.session_control.complete_rotation(mission_id, rotation_id, successor)
            return {
                "schema_version": G2_SCHEMA, "status": "ROTATED", "truth_source": "R1_EVENT_STREAM",
                "rotation_id": rotation_id, "predecessor_session_id": predecessor_session_id,
                "successor_session_id": successor, "root_attempt_id": root_attempt_id,
                "successor_attempt_id": latest.attempt_id, "rotation_reasons": rotation_reasons,
                "session_router": "G2_1", "recovered_pending_rotation": True,
            }

        if latest is None or latest.runtime_session_id != predecessor_session_id or latest.root_attempt_id != root_attempt_id:
            raise RuntimeError("ROTATION_RECOVERY_PREDECESSOR_MISMATCH")

        with self.provisioning_provider.provision(token, title):
            result = super().rotate_session(mission_id, task_id=task_id, agent=route.agent_name)
        successor = str(result.get("successor_session_id") or "")
        if not successor:
            raise RuntimeError("ROTATION_SUCCESSOR_SESSION_ID_MISSING")
        self._bind_provision_if_needed(mission_id, token, successor)
        # Two-phase completion: successor exists + ContextPack is accepted, then
        # predecessor closes, and only then RotationRequest becomes COMPLETED.
        self._close_predecessor_after_successor(
            mission_id, rotation_id=rotation_id, predecessor_session_id=predecessor_session_id,
            reason="G2_1_SUCCESSOR_BOOTSTRAPPED",
        )
        self.session_control.complete_rotation(mission_id, rotation_id, successor)
        return {**result, "rotation_id": rotation_id, "rotation_reasons": rotation_reasons, "session_router": "G2_1"}

    def observe_session(
        self,
        mission_id: str,
        *,
        task_id: str,
        agent: str | None = None,
        observation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if agent is not None:
            raise RuntimeError("AGENT_SESSION_OBSERVATION_OWNERSHIP_FORBIDDEN")
        mission_id = _text(mission_id, "mission_id")
        task_id = _text(task_id, "task_id")
        route = self._route_task(mission_id, task_id)
        composed = self.runtime.replay_composed(mission_id)
        execution = composed.extension_state("r1_3b_execution_resume")
        latest = execution.latest_attempt(task_id) if execution is not None else None
        if latest is None:
            raise RuntimeError("EXECUTION_ATTEMPT_NOT_FOUND_FOR_SESSION_OBSERVATION")
        if observation is None:
            try:
                raw = dict(self.raw_session_provider.observe_session(latest.runtime_session_id))
            except OpenCodeSessionAdmissionPending:
                # Web startup/auth admission is intentionally decoupled from AI
                # Session supervision. Do not turn a 401/403 admission wait into
                # an unhealthy Session and rotate it.
                raise
            except Exception as exc:
                raw = {"session_id": latest.runtime_session_id, "observed_at": _utc_now(),
                       "reachable": False, "healthy": False, "error": type(exc).__name__, "provider": "OPENCODE"}
        else:
            raw = dict(observation)
        obs = SessionObservation.from_provider(latest.runtime_session_id, raw)
        self.session_control.record_observation(mission_id, obs.to_dict())
        reasons = self.rotation_policy.evaluate(obs)
        if not reasons:
            return {
                "schema_version": G2_SCHEMA, "status": "KEEP", "truth_source": "R1_EVENT_STREAM",
                "session_id": latest.runtime_session_id, "attempt_id": latest.attempt_id,
                "root_attempt_id": latest.root_attempt_id, "observation": obs.to_dict(),
                "rotation_reasons": [], "route": route.to_dict(),
            }
        rotated = self.rotate_session(mission_id, task_id=task_id, reasons=reasons)
        return {
            "schema_version": G2_SCHEMA, "status": "ROTATED", "truth_source": "R1_EVENT_STREAM",
            "observation": obs.to_dict(), "rotation_reasons": reasons, "rotation": rotated,
        }

    def rotate_planning_session(self, mission_id: str, predecessor_session_id: str, reasons: list[str]) -> dict[str, Any]:
        mission_id = _text(mission_id, "mission_id")
        pending = self._pending_rotation(mission_id, "__PLANNING__")
        if pending is not None:
            predecessor_session_id = pending.predecessor_session_id
            rotation_id = pending.rotation_id
            root_attempt_id = pending.root_attempt_id
            rotation_reasons = list(pending.reasons)
        else:
            composed = self.runtime.replay_composed(mission_id)
            predecessor = composed.core_state.session(predecessor_session_id)
            if predecessor is None or predecessor.status.value != "OPEN":
                raise RuntimeError("PLANNER_PREDECESSOR_NOT_OPEN")
            attrs = dict(predecessor.attributes or {})
            logical_agent_id = str(attrs.get("logical_agent_id") or "")
            if not logical_agent_id:
                raise RuntimeError("PLANNER_LOGICAL_AGENT_ID_MISSING")
            root_attempt_id = f"planning:{logical_agent_id}"
            rotation_id = self._rotation_record_id(mission_id, "__PLANNING__", predecessor_session_id)
            record = self.session_control.state(mission_id).rotation(rotation_id)
            if record is not None and record.status == "COMPLETED":
                return {"status": "ROTATED", "truth_source": "R1_EVENT_STREAM", "rotation_id": rotation_id,
                        "predecessor_session_id": predecessor_session_id, "successor_session_id": record.successor_session_id,
                        "idempotent_replay": True}
            rotation_reasons = list(reasons)
            self.session_control.request_rotation(
                mission_id,
                {"rotation_id": rotation_id, "task_id": "__PLANNING__",
                 "root_attempt_id": root_attempt_id,
                 "predecessor_session_id": predecessor_session_id, "reasons": rotation_reasons},
            )

        composed = self.runtime.replay_composed(mission_id)
        predecessor = composed.core_state.session(predecessor_session_id)
        if predecessor is None:
            raise RuntimeError("PLANNER_PREDECESSOR_NOT_FOUND")
        attrs = dict(predecessor.attributes or {})
        logical_agent_id = str(attrs.get("logical_agent_id") or "")
        if not logical_agent_id:
            # A pending durable rotation is only valid for the same Planner
            # LogicalAgent lineage recorded on its predecessor.
            raise RuntimeError("PLANNER_LOGICAL_AGENT_ID_MISSING")
        if root_attempt_id != f"planning:{logical_agent_id}":
            raise RuntimeError("PLANNER_ROTATION_ROOT_MISMATCH")
        role = self.role_registry.resolve("PLANNER")
        token = self._provision_token(mission_id, logical_agent_id, "PLANNING_ROTATION", predecessor_session_id)
        title = f"AITest Planner resume · {mission_id}"
        self._request_provision_if_needed(
            mission_id, token=token, task_id=None, logical_agent_id=logical_agent_id, root_attempt_id=root_attempt_id,
            role=role.role, agent_name=role.agent_name, phase="PLANNING_ROTATION", title=title,
        )

        expected_title = ProvisioningOpenCodeSessionProvider.title_for(token, title)
        matches = [item for item in self.raw_session_provider.list_sessions() if item.title == expected_title]
        if len(matches) > 1:
            raise RuntimeError("PLANNER_ROTATION_DUPLICATE_EXTERNAL_SUCCESSOR")
        external = matches[0] if matches else None
        if external is None:
            with self.provisioning_provider.provision(token, title):
                external = self.provisioning_provider.create_session(title=title, parent_id=predecessor_session_id)

        # If a prior process already opened the successor durably, reuse it.
        # Otherwise make it durable now. In either case re-send ContextPack so a
        # crash during bootstrap cannot leave a context-less successor.
        refreshed = self.runtime.replay_composed(mission_id)
        successor_core = refreshed.core_state.session(external.session_id)
        if successor_core is None:
            self._open_core_session(
                mission_id=mission_id, external=external, task_id=None, agent=role.agent_name,
                phase="PLANNING", logical_agent_id=logical_agent_id,
            )
        elif successor_core.status.value != "OPEN":
            raise RuntimeError("PLANNER_ROTATION_SUCCESSOR_NOT_OPEN")
        self.raw_session_provider.send_context(
            session_id=external.session_id, agent=role.agent_name,
            text=self._planning_context_message(mission_id, logical_agent_id),
        )
        self._bind_provision_if_needed(mission_id, token, external.session_id)
        self._close_predecessor_after_successor(
            mission_id, rotation_id=rotation_id, predecessor_session_id=predecessor_session_id,
            reason="G2_1_PLANNER_SUCCESSOR_BOOTSTRAPPED",
        )
        self.session_control.complete_rotation(mission_id, rotation_id, external.session_id)
        return {
            "status": "ROTATED", "truth_source": "R1_EVENT_STREAM", "rotation_id": rotation_id,
            "predecessor_session_id": predecessor_session_id, "successor_session_id": external.session_id,
            "logical_agent_id": logical_agent_id, "rotation_reasons": rotation_reasons,
        }

    def _all_mission_ids(self) -> list[str]:
        conn = sqlite3.connect(str(self.runtime.db_path))
        try:
            rows = conn.execute("SELECT mission_id FROM mission_projection ORDER BY mission_id").fetchall()
            return [str(row[0]) for row in rows]
        finally:
            conn.close()

    def _active_mission_ids(self) -> list[str]:
        conn = sqlite3.connect(str(self.runtime.db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT mission_id,state_json FROM mission_projection ORDER BY mission_id").fetchall()
            result: list[str] = []
            for row in rows:
                try:
                    state = json.loads(row["state_json"])
                except Exception:
                    continue
                if state.get("status") == "ACTIVE":
                    result.append(str(row["mission_id"]))
            return result
        finally:
            conn.close()

    def _recover_requested_provision(self, mission_id: str, intent: Any) -> dict[str, Any] | None:
        if intent.status != "REQUESTED":
            return None
        if intent.phase in {"PLANNING", "PLANNING_ROTATION"}:
            _composed, _graph, _goal, current_plan = self._active_plan_context(mission_id)
            if current_plan is not None:
                # Planner lifecycle is stale once a governed Plan exists.
                return None
            if intent.phase == "PLANNING_ROTATION":
                # Rotation record gives the durable predecessor identity.
                state = self.session_control.state(mission_id)
                record = next((x for x in state.rotations if x.status == "REQUIRED" and x.task_id == "__PLANNING__"), None)
                if record is not None:
                    return self.rotate_planning_session(mission_id, record.predecessor_session_id, list(record.reasons))
            return self.open_planning_session(mission_id)
        if not intent.task_id:
            return None
        composed, graph, _goal, current_plan = self._active_plan_context(mission_id)
        task = graph.task(intent.task_id)
        if task is None or task.lifecycle_state != TaskLifecycleState.ACTIVE:
            return None
        if intent.phase == "TASK_ROTATION":
            return self.rotate_session(mission_id, task_id=intent.task_id, reasons=["PROVISION_RECONCILIATION"])
        return self._provision_active_task_session(
            mission_id=mission_id, plan_id=task.plan_id, revision_id=task.plan_revision_id,
            task_id=task.task_id, agent=DEFAULT_WORKER_AGENT,
        )

    def reconcile_external_sessions(self) -> dict[str, Any]:
        """Reconcile package-owned external Sessions against durable provision intents.

        Tagged Sessions with no durable ProvisionIntent are package-owned orphans
        and are closed; unrelated untagged OpenCode Sessions are ignored.
        Reconciliation spans all durable Missions so terminal Missions cannot
        leak an external Session merely because they left the ACTIVE projection.
        """
        external = list(self.raw_session_provider.list_sessions())
        by_token: dict[str, list[ExternalSession]] = {}
        for item in external:
            token = ProvisioningOpenCodeSessionProvider.token_from_title(item.title)
            if token:
                by_token.setdefault(token, []).append(item)
        actions: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        all_mission_ids = self._all_mission_ids()
        active_mission_ids = set(self._active_mission_ids())
        known_tokens: set[str] = set()
        for durable_mission_id in all_mission_ids:
            known_tokens.update(intent.provision_token for intent in self.session_control.state(durable_mission_id).provisions)

        def close_external(item: ExternalSession, *, status: str, mission_id: str | None = None, token: str | None = None) -> bool:
            try:
                self.raw_session_provider.delete_session(item.session_id)
                actions.append({"mission_id": mission_id, "session_id": item.session_id, "token": token, "status": status})
                return True
            except Exception as exc:
                failure = {"mission_id": mission_id, "session_id": item.session_id, "token": token,
                           "status": status + "_FAILED", "error": type(exc).__name__}
                actions.append(failure); failures.append(failure)
                return False

        for mission_id in all_mission_ids:
            state = self.session_control.state(mission_id)
            mission_active = mission_id in active_mission_ids
            for intent in state.provisions:
                matches = list(by_token.get(intent.provision_token, []))
                # Deterministic token must map to at most one external Session.
                # For BOUND we can keep only the exact durable binding; for a
                # REQUESTED/ambiguous set close all and deterministically retry.
                if len(matches) > 1:
                    if intent.status == "BOUND" and intent.external_session_id:
                        canonical = [x for x in matches if x.session_id == intent.external_session_id]
                        extras = [x for x in matches if x.session_id != intent.external_session_id]
                        for item in extras:
                            close_external(item, status="DUPLICATE_EXTERNAL_EXTRA_CLOSED", mission_id=mission_id, token=intent.provision_token)
                        matches = canonical
                    else:
                        for item in matches:
                            close_external(item, status="DUPLICATE_EXTERNAL_RESET", mission_id=mission_id, token=intent.provision_token)
                        matches = []

                if not mission_active:
                    # Never resume logical work for a terminal/non-active Mission.
                    # Clean package-owned external resources only.
                    for item in matches:
                        closed = close_external(item, status="INACTIVE_MISSION_EXTERNAL_CLOSED", mission_id=mission_id, token=intent.provision_token)
                        if closed and intent.status == "REQUESTED":
                            try:
                                self.session_control.close_orphan(
                                    mission_id, intent.provision_token, item.session_id, "MISSION_NOT_ACTIVE",
                                )
                            except Exception as exc:
                                failure = {"mission_id": mission_id, "token": intent.provision_token,
                                           "status": "INACTIVE_MISSION_DURABLE_CLEANUP_FAILED", "error": type(exc).__name__}
                                actions.append(failure); failures.append(failure)
                    continue

                if intent.status == "REQUESTED":
                    try:
                        repaired = self._recover_requested_provision(mission_id, intent)
                        if repaired:
                            actions.append({"mission_id": mission_id, "token": intent.provision_token, "status": "RECOVERED"})
                        elif matches:
                            # The durable logical phase is no longer recoverable
                            # (for example Plan accepted / Task no longer ACTIVE).
                            # Close package-owned side effects rather than leak a
                            # known token forever.
                            for item in matches:
                                if close_external(item, status="STALE_REQUESTED_EXTERNAL_CLOSED", mission_id=mission_id, token=intent.provision_token):
                                    self.session_control.close_orphan(
                                        mission_id, intent.provision_token, item.session_id, "DURABLE_PHASE_NO_LONGER_RECOVERABLE",
                                    )
                            actions.append({"mission_id": mission_id, "token": intent.provision_token, "status": "STALE_REQUESTED_CLEANED"})
                        else:
                            actions.append({"mission_id": mission_id, "token": intent.provision_token, "status": "WAIT_NO_EXTERNAL_SIDE_EFFECT"})
                    except Exception as exc:
                        failure = {"mission_id": mission_id, "token": intent.provision_token,
                                   "status": "REPAIR_FAILED", "error": type(exc).__name__}
                        actions.append(failure); failures.append(failure)
                elif intent.status == "BOUND" and intent.external_session_id:
                    composed = self.runtime.replay_composed(mission_id)
                    core = composed.core_state.session(intent.external_session_id)
                    if core is not None and core.status.value in {"CLOSED", "FAILED"} and matches:
                        for item in matches:
                            close_external(item, status="TERMINAL_EXTERNAL_CLOSED", mission_id=mission_id, token=intent.provision_token)

        orphan_closed: list[str] = []
        unrelated_untagged: list[str] = []
        # Refresh the provider list because duplicate/terminal cleanup above may
        # have changed it, and recovery may have created a deterministic Session.
        for item in self.raw_session_provider.list_sessions():
            token = ProvisioningOpenCodeSessionProvider.token_from_title(item.title)
            if token is None:
                unrelated_untagged.append(item.session_id)
                continue
            if token in known_tokens:
                continue
            if close_external(item, status="ORPHAN_EXTERNAL_CLOSED_NO_DURABLE_INTENT", token=token):
                orphan_closed.append(item.session_id)
        return {
            "status": "PASS" if not failures else "REPAIR", "actions": actions, "failures": failures,
            "orphan_package_sessions_closed": orphan_closed,
            "unrelated_untagged_sessions_ignored": unrelated_untagged,
        }

    def _supervise_admitted_once(self) -> dict[str, Any]:
        """One admitted autonomous tick; Session API is expected to be usable."""
        reconciliation = self.reconcile_external_sessions()
        results: list[dict[str, Any]] = []
        mission_ids = self._active_mission_ids()
        for mission_id in mission_ids:
            composed = self.runtime.replay_composed(mission_id)
            # Supervise pre-plan Planner Sessions by durable Core lineage.
            for session in list(composed.core_state.sessions):
                attrs = dict(session.attributes or {})
                if session.status.value != "OPEN" or attrs.get("phase") != "PLANNING":
                    continue
                try:
                    raw = dict(self.raw_session_provider.observe_session(session.session_id))
                except OpenCodeSessionAdmissionPending:
                    raise
                except Exception as exc:
                    raw = {"reachable": False, "healthy": False, "error": type(exc).__name__, "provider": "OPENCODE"}
                obs = SessionObservation.from_provider(session.session_id, raw)
                self.session_control.record_observation(mission_id, obs.to_dict())
                reasons = self.rotation_policy.evaluate(obs)
                if reasons:
                    result = self.rotate_planning_session(mission_id, session.session_id, reasons)
                    results.append({"mission_id": mission_id, "phase": "PLANNING", "result": result})
                else:
                    results.append({"mission_id": mission_id, "phase": "PLANNING", "status": "KEEP",
                                    "session_id": session.session_id, "observation": obs.to_dict()})
            composed = self.runtime.replay_composed(mission_id)
            graph = composed.extension_state("r1_2_work_graph")
            execution = composed.extension_state("r1_3b_execution_resume")
            if not isinstance(graph, WorkGraphState) or execution is None:
                continue
            for task in graph.tasks:
                if task.lifecycle_state != TaskLifecycleState.ACTIVE:
                    continue
                latest = execution.latest_attempt(task.task_id)
                if latest is None:
                    continue
                result = self.observe_session(mission_id, task_id=task.task_id)
                results.append({"mission_id": mission_id, "task_id": task.task_id, "result": result})
        return {
            "schema_version": "aitest.g2.1.control-loop-tick.v1",
            "status": "PASS" if reconciliation.get("status") == "PASS" else "REPAIR",
            "truth_source": "R1_EVENT_STREAM",
            "reconciliation": reconciliation, "supervision": results,
            "active_mission_count": len(mission_ids),
        }


    def supervise_once(self) -> dict[str, Any]:
        """Autonomous tick with non-fatal pre-auth/runtime-admission waiting.

        OpenCode Web/process readiness is a different boundary from authenticated
        Session API admission.  A 401/403 keeps the same Web usable for human
        authentication and causes no Session mutation/rotation.  The next tick
        rebuilds from R1 and retries automatically.
        """
        try:
            return self._supervise_admitted_once()
        except OpenCodeSessionAdmissionPending as exc:
            return {
                "schema_version": "aitest.g2.1.control-loop-tick.v1",
                "status": "WAIT",
                "truth_source": "R1_EVENT_STREAM",
                "runtime_admission": "WAITING_AUTH_OR_SESSION_API",
                "reason": type(exc).__name__,
                "message": str(exc),
                "reconciliation": None,
                "supervision": [],
                "active_mission_count": len(self._active_mission_ids()),
            }


def default_g21_service(
    runtime: RuntimeService,
    workspace_root: str | Path,
    *,
    session_provider: OpenCodeSessionProvider | None = None,
) -> G21AutonomousOrchestrationService:
    return G21AutonomousOrchestrationService(runtime, workspace_root, session_provider=session_provider)


__all__ = [
    "G21AutonomousOrchestrationService",
    "ProvisioningOpenCodeSessionProvider",
    "default_g21_service",
]
