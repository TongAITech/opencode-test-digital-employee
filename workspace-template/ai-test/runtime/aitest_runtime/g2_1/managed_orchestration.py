"""G2.1 authoritative Session Router + autonomous Session Supervisor.

This layer is additive over the frozen G2 orchestration implementation.  G2
continues to decide Mission/Plan/Task scheduling.  G2.1 owns WHO/WHERE Session
routing, durable external-session provisioning, autonomous observation and
rotation, and reconciliation.  Agents never own their Session lifecycle.
"""
from __future__ import annotations

import json
import os
import sqlite3
from functools import wraps
from datetime import datetime, timezone
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
from ..durable_core import ActorRef, CommandEnvelope, MissionStatus, RuntimeError, RuntimeService, canonical_sha256
from ..r2_3 import PlannerInput
from ..work_graph import TaskLifecycleState, WorkGraphState
from ..execution_context import (BuildExecutionContextRequest, ContextTarget, EventCursor,
                                 ExecutionContextApplicationService, KnowledgeSetInput)
from ..session_pressure import POLICY_ID as PRESSURE_POLICY_ID
from .router import AgentRoleRegistry, RouteDecision, SessionRouter, TASK_OUTCOME_REPORT
from .service import SessionControlApplicationService, execute_control_command
from .supervisor import RotationPolicy, SessionObservation, durable_pressure
from ..dispatch_receipts import (runtime_coordination, dispatch_context, business_cursor,
                                 reconcile_context_receipt, ContextDeliveryUnconfirmed, CoordinationBusy)

POST_DISPATCH_GRACE_SECONDS = 2
AUTO_CONTINUE_STABLE_HOST_SECONDS = 6

def _coordinated(method):
    @wraps(method)
    def call(self,*args,**kwargs):
        with runtime_coordination(self.runtime.db_path):return method(self,*args,**kwargs)
    return call


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
        self._independent_session = False
        self.context_sender = None

    @contextmanager
    def provision(self, token: str, friendly_title: str, *, independent_session: bool = False) -> Iterator[None]:
        if self._token is not None:
            raise RuntimeError("NESTED_SESSION_PROVISION_CONTEXT_FORBIDDEN")
        self._token = _text(token, "provision_token")
        self._friendly_title = _text(friendly_title, "friendly_title")
        self._independent_session = independent_session
        try:
            yield
        finally:
            self._token = None
            self._friendly_title = None
            self._independent_session = False

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
        # OpenCode 1.18.3 recursively deletes children when a parent closes.
        # Rotation lineage belongs to R1; its successor must survive cleanup
        # of the predecessor's external Session.
        return self.delegate.create_session(title=effective, parent_id=None if self._independent_session else parent_id)

    def send_context(self, *, session_id: str, agent: str, text: str) -> Mapping[str, Any]:
        if self.context_sender is not None:
            return self.context_sender(session_id=session_id,agent=agent,text=text)
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
        self.provisioning_provider.context_sender = lambda **kw: dispatch_context(self, **kw)

    @_coordinated
    def intake_mission(self, request):
        return super().intake_mission(request)

    def status(self, mission_id: str | None = None) -> dict[str, Any]:
        result = super().status(mission_id)
        import os
        if mission_id is None and os.environ.get("AITEST_HOST_SESSION_ID"):
            from ..general_work.execution import GeneralExecutionService
            result["general_work"] = GeneralExecutionService(self.runtime, self.workspace_root, self.raw_session_provider).status(os.environ["AITEST_HOST_SESSION_ID"])
        result["g2_1_session_management"] = {
            "session_router": "RUNTIME_OWNED",
            "session_supervisor": "CONTROL_LOOP_OWNED",
            "agent_owns_session_lifecycle": False,
            "pressure_policy": PRESSURE_POLICY_ID,
            "missing_metrics_behavior": "MESSAGE_API_THEN_R1_DURABLE_BLIND_BUDGET",
            "bootstrap_max_bytes": 16384,
            "bank_opencode_observation_field_validation": "PENDING",
        }
        if mission_id is not None:
            result["session_control"] = self.session_control.state(str(mission_id)).to_dict()
        return result

    def _provision_token(self, *parts: str) -> str:
        from ..mission_session_authority import MissionSessionOwner
        return "g21-" + canonical_sha256({"parts": list(parts), "host_realm": MissionSessionOwner(self).realm()})[:28]

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
        from ..mission_session_authority import MissionSessionOwner
        MissionSessionOwner(self).request(mission_id, token)

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
            "r1_cursor": {"mission_id": mission_id, "through_seq": composed.seq},
            "resume_checkpoint": self._latest_checkpoint(mission_id, "__PLANNING__"),
            "instruction": (
                "Analyze the durable Goal and governed evidence. Author a bounded semantic Plan candidate, "
                "then persist it only through the canonical Planner tool. Unknown facts remain KNOWLEDGE_GAP. "
                "Session lifecycle is owned by the Runtime Session Router/Supervisor; do not create or rotate Sessions."
            ),
        }
        return self._bounded_bootstrap("AITEST_CANONICAL_PLANNING_CONTEXT\n", envelope)

    def _progress_identity(self, mission_id: str, *, task_id: str | None, session_id: str | None,
                           reason: str, cursor: int) -> tuple[str, str]:
        identity = {
            "mission_id": mission_id, "task_id": task_id, "session_id": session_id,
            "reason": reason, "business_cursor": cursor,
        }
        signature = canonical_sha256(identity)
        return "g21-progress:" + signature[:40], signature

    def _replanning_context_message(self, mission_id: str, progress_id: str, logical_agent_id: str) -> str:
        control = self.session_control.state(mission_id)
        progress = control.progress(progress_id)
        if progress is None:
            raise RuntimeError("C3_PROGRESS_RECORD_REQUIRED")
        composed, graph, goal, current_plan = self._active_plan_context(mission_id)
        if current_plan is None or current_plan.current_revision_id is None:
            raise RuntimeError("C3_REPLAN_CURRENT_REVISION_REQUIRED")
        revision = graph.revision(current_plan.current_revision_id)
        envelope = {
            "schema": "aitest.replanning-context.v1",
            "authority": "R1_EVENT_STREAM",
            "conversation_is_not_truth": True,
            "mission_id": mission_id,
            "goal_id": goal.goal_id,
            "goal_revision": goal.revision,
            "current_plan_id": current_plan.plan_id,
            "current_plan_revision_id": current_plan.current_revision_id,
            "current_plan_content_hash": getattr(revision, "content_hash", None),
            "progress": {
                "progress_id": progress.progress_id,
                "business_cursor": progress.business_cursor,
                "reason": progress.reason,
                "failure_signature": progress.failure_signature,
                "task_id": progress.task_id,
                "session_id": progress.session_id,
            },
            "logical_agent_id": logical_agent_id,
            "required_next_action": "AUTHOR_PLAN_REVISION",
            "instruction": (
                "Diagnose the durable no-progress condition from canonical R1/G3/G4/G5 evidence and author a governed "
                "PlanRevision through the canonical Planner tool. Planner owns WHAT: Runtime must not invent Tasks. "
                "If further investigation is required, add a bounded DIAGNOSIS-role Task so Router selects aitest-diagnosis. "
                "Preserve completed and in-flight work identities, never replay UNKNOWN_SIDE_EFFECT, and do not treat "
                "PLAN_COMPLETE as TEST_SUFFICIENT. If evidence is insufficient, make the missing evidence explicit."
            ),
        }
        return self._bounded_bootstrap("AITEST_CANONICAL_REPLANNING_CONTEXT\n", envelope)

    def _open_replanning_session(self, mission_id: str, progress_id: str) -> dict[str, Any]:
        from ..mission_controls import pending_controls
        if pending_controls(self.runtime, mission_id=mission_id, stopping_only=True, limit=1):
            return {"status":"WAIT","reason":"MISSION_CONTROL_PENDING","truth_source":"R1_EVENT_STREAM"}
        control = self.session_control.state(mission_id)
        progress = control.progress(progress_id)
        if progress is None:
            raise RuntimeError("C3_PROGRESS_RECORD_REQUIRED")
        composed, _graph, _goal, current_plan = self._active_plan_context(mission_id)
        if composed.core_state.mission.status != MissionStatus.ACTIVE:
            return {"status":"WAIT","reason":"MISSION_NOT_ACTIVE","truth_source":"R1_EVENT_STREAM"}
        if current_plan is None or current_plan.current_revision_id is None:
            raise RuntimeError("C3_REPLAN_CURRENT_REVISION_REQUIRED")

        role = self.role_registry.resolve("PLANNER")
        lineage = "replanning:" + progress_id
        logical_agent_id = self.session_router.logical_agent_id(role.agent_name, lineage)

        if progress.phase == "REPLANNING" and progress.replan_session_id:
            current_session = composed.core_state.session(progress.replan_session_id)
            if current_session is not None and current_session.status.value == "OPEN":
                attrs = dict(current_session.attributes or {})
                if attrs.get("phase") != "REPLANNING" or attrs.get("logical_agent_id") != logical_agent_id:
                    raise RuntimeError("C3_REPLAN_SESSION_LINEAGE_MISMATCH")
                text = self._replanning_context_message(mission_id, progress_id, logical_agent_id)
                try:
                    delivery = self.provisioning_provider.send_context(
                        session_id=progress.replan_session_id, agent=role.agent_name, text=text,
                    )
                except ContextDeliveryUnconfirmed as exc:
                    return {
                        "status":"WAIT", "reason":str(exc), "progress_id":progress_id,
                        "session_id":progress.replan_session_id, "truth_source":"R1_EVENT_STREAM",
                    }
                bound = next((
                    p for p in self.session_control.state(mission_id).provisions
                    if p.external_session_id == progress.replan_session_id
                    and p.phase in {"REPLANNING","REPLANNING_ROTATION"}
                    and p.status == "BOUND"
                ), None)
                if bound is None:
                    raise RuntimeError("C3_REPLAN_BOUND_PROVISION_REQUIRED")
                return {
                    "status":"REPLAN_DISPATCHED" if delivery.get("prompt_sent") else "REPLAN_IN_PROGRESS",
                    "truth_source":"R1_EVENT_STREAM", "conversation_is_not_truth":True,
                    "progress_id":progress_id, "business_cursor":progress.business_cursor,
                    "failure_signature":progress.failure_signature, "agent":role.agent_name,
                    "logical_agent_id":logical_agent_id, "session_id":progress.replan_session_id,
                    "provision_token":bound.provision_token, "delivery":delivery,
                }
            if current_session is not None and current_session.status.value != "OPEN":
                # A completed rotation should have updated this pointer before
                # closing its predecessor. A stale durable pointer is a real
                # reconciliation failure, never permission to silently fork.
                raise RuntimeError("C3_REPLAN_DURABLE_POINTER_STALE")

        token = self._provision_token(mission_id, logical_agent_id, "REPLANNING", progress_id)
        title = f"AITest Replan · {mission_id} · {progress_id[-12:]}"
        self._request_provision_if_needed(
            mission_id, token=token, task_id=None, logical_agent_id=logical_agent_id,
            root_attempt_id=lineage, role=role.role, agent_name=role.agent_name,
            phase="REPLANNING", title=title,
        )
        expected_title = ProvisioningOpenCodeSessionProvider.title_for(token, title)
        matches = [item for item in self.raw_session_provider.list_sessions() if item.title == expected_title]
        if len(matches) > 1:
            raise RuntimeError("C3_REPLAN_DUPLICATE_EXTERNAL_SESSION")
        external = matches[0] if matches else None
        if external is None:
            with self.provisioning_provider.provision(token, title, independent_session=True):
                external = self.provisioning_provider.create_session(title=title)

        refreshed = self.runtime.replay_composed(mission_id)
        core = refreshed.core_state.session(external.session_id)
        if core is None:
            self._open_core_session(
                mission_id=mission_id, external=external, task_id=None, agent=role.agent_name,
                phase="REPLANNING", logical_agent_id=logical_agent_id,
            )
        elif core.status.value != "OPEN":
            raise RuntimeError("C3_REPLAN_SESSION_NOT_OPEN")
        else:
            attrs = dict(core.attributes or {})
            if attrs.get("phase") != "REPLANNING" or attrs.get("logical_agent_id") != logical_agent_id:
                raise RuntimeError("C3_REPLAN_SESSION_LINEAGE_MISMATCH")

        progress = self.session_control.state(mission_id).progress(progress_id)
        if progress is None:
            raise RuntimeError("C3_PROGRESS_RECORD_REQUIRED")
        if progress.phase == "STALLED":
            self.session_control.record_progress_state(mission_id, {
                "progress_id": progress.progress_id, "business_cursor": progress.business_cursor,
                "phase": "REPLANNING", "reason": progress.reason,
                "failure_signature": progress.failure_signature, "task_id": progress.task_id,
                "session_id": progress.session_id, "replan_lineage": lineage,
                "replan_session_id": external.session_id, "observed_at": _utc_now(),
            })
        elif progress.phase != "REPLANNING":
            return {"status":"WAIT","reason":"C3_PROGRESS_NOT_REPLANNABLE","progress_id":progress_id,
                    "truth_source":"R1_EVENT_STREAM"}

        text = self._replanning_context_message(mission_id, progress_id, logical_agent_id)
        try:
            delivery = self.provisioning_provider.send_context(
                session_id=external.session_id, agent=role.agent_name, text=text,
            )
        except ContextDeliveryUnconfirmed as exc:
            return {"status":"WAIT","reason":str(exc),"progress_id":progress_id,
                    "session_id":external.session_id,"truth_source":"R1_EVENT_STREAM"}
        self._bind_provision_if_needed(mission_id, token, external.session_id)
        return {
            "status": "REPLAN_DISPATCHED" if delivery.get("prompt_sent") else "REPLAN_IN_PROGRESS",
            "truth_source": "R1_EVENT_STREAM", "conversation_is_not_truth": True,
            "progress_id": progress_id, "business_cursor": progress.business_cursor,
            "failure_signature": progress.failure_signature, "agent": role.agent_name,
            "logical_agent_id": logical_agent_id, "session_id": external.session_id,
            "provision_token": token, "delivery": delivery,
        }

    def _handle_no_progress(self, mission_id: str, *, task_id: str | None, session_id: str | None,
                            reason: str, cursor: int | None = None) -> dict[str, Any]:
        mission_id = _text(mission_id, "mission_id")
        effect_barrier = self._business_effect_barrier(
            mission_id, task_id=task_id, session_id=session_id,
        )
        if effect_barrier:
            return effect_barrier
        cursor = business_cursor(self.runtime, mission_id) if cursor is None else int(cursor)
        progress_id, signature = self._progress_identity(
            mission_id, task_id=task_id, session_id=session_id, reason=reason, cursor=cursor,
        )
        existing = self.session_control.state(mission_id).progress(progress_id)
        if existing is None:
            self.session_control.record_progress_state(mission_id, {
                "progress_id": progress_id, "business_cursor": cursor, "phase": "STALLED",
                "reason": reason, "failure_signature": signature, "task_id": task_id,
                "session_id": session_id, "replan_lineage": None, "replan_session_id": None,
                "observed_at": _utc_now(),
            })
        return self._open_replanning_session(mission_id, progress_id)

    @_coordinated
    def open_planning_session(self, mission_id: str) -> dict[str, Any]:
        from ..mission_controls import pending_controls
        if pending_controls(self.runtime, mission_id=mission_id, stopping_only=True, limit=1):
            return {'status':'WAIT','reason':'MISSION_CONTROL_PENDING','truth_source':'R1_EVENT_STREAM'}
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
            self.provisioning_provider.send_context(
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
        active_host_session_id = os.environ.get("AITEST_HOST_SESSION_ID", "").strip()
        for session in list(composed.core_state.sessions):
            attrs = dict(session.attributes or {})
            if session.status.value != "OPEN" or attrs.get("phase") not in {"PLANNING","REPLANNING"}:
                continue
            close_id = f"g2.1:planning:{session.session_id}:PLAN_ACCEPTED:CLOSE"
            result = execute_control_command(self.runtime, CommandEnvelope(
                close_id, "CLOSE_SESSION", mission_id, self.runtime.get_head_seq(mission_id),
                ActorRef("SYSTEM", "g2.1-session-router"), {"reason": "PLAN_ACCEPTED"},
                session_id=session.session_id, idempotency_key=close_id, correlation_id=close_id, schema_version=1,
            ))
            if not result.ok:
                if result.error:
                    raise result.error
                raise RuntimeError("PLANNER_SESSION_CLOSE_AFTER_PLAN_REJECTED")
            # If this Plan was accepted by a real OpenCode Planner tool call,
            # deleting that exact Host Session here can terminate the still-running
            # tool process before it returns and before Scheduler handoff completes.
            # Durable Core is already CLOSED, so the background reconciler owns the
            # external cleanup after the Host call unwinds. Other stale planning
            # Sessions remain safe to delete immediately.
            if session.session_id != active_host_session_id:
                try:
                    self.raw_session_provider.delete_session(session.session_id)
                except Exception:
                    pass
            closed.append(session.session_id)
        return closed

    def _resolve_replanning_progress_after_plan(self, mission_id: str) -> list[str]:
        """A newly accepted PlanRevision is business progress for all open replanning generations.

        Planner sessions are closed immediately after a governed Plan/Revision is
        accepted. Leaving their ProgressRecord in REPLANNING would make a later
        control tick treat completed recovery work as an unresolved deadlock.
        """
        resolved: list[str] = []
        for progress in list(self.session_control.state(mission_id).progress_records):
            if progress.phase != "REPLANNING":
                continue
            self.session_control.record_progress_state(mission_id, {
                "progress_id": progress.progress_id,
                "business_cursor": progress.business_cursor,
                "phase": "RESOLVED",
                "reason": progress.reason,
                "failure_signature": progress.failure_signature,
                "task_id": progress.task_id,
                "session_id": progress.session_id,
                "replan_lineage": progress.replan_lineage,
                "replan_session_id": progress.replan_session_id,
                "observed_at": _utc_now(),
            })
            resolved.append(progress.progress_id)
        return resolved

    @staticmethod
    def _plan_semantic_surface(
        objective: Any,
        constraints: Any,
        tasks: Any,
        dependencies: Any,
    ) -> dict[str, Any] | None:
        """Identity-free Planner semantics used only to reject fake progress.

        Frozen R2.3 remains the sole authority that validates and persists a
        PlanRevision. This helper intentionally strips revision/task ids so a
        cursor-qualified retry with identical WHAT cannot manufacture business
        progress merely by receiving new durable identities.
        """
        if not isinstance(tasks, (list, tuple)) or not tasks:
            return None
        normalized_tasks: list[dict[str, Any]] = []
        references: dict[str, str] = {}
        seen: set[str] = set()
        for index, raw in enumerate(tasks):
            if not isinstance(raw, Mapping):
                return None
            raw = dict(raw)
            key = next(
                (str(raw[name]).strip() for name in ("task_key","key","semantic_key","name")
                 if raw.get(name) is not None and str(raw.get(name)).strip()),
                f"task-{index + 1}",
            )
            if key in seen:
                return None
            seen.add(key)
            intent = next(
                (str(raw[name]).strip() for name in ("intent","description","statement","action")
                 if raw.get(name) is not None and str(raw.get(name)).strip()),
                key,
            )
            criteria_raw = raw.get("acceptance_criteria", raw.get("acceptance", raw.get("criteria", [])))
            if criteria_raw is None:
                criteria_raw = []
            if not isinstance(criteria_raw, (list, tuple)):
                return None
            criteria: list[dict[str, str]] = []
            criterion_ids: set[str] = set()
            for criterion_index, item in enumerate(criteria_raw):
                if not isinstance(item, Mapping):
                    return None
                cid = next(
                    (str(item[name]).strip() for name in ("criterion_id","id","key")
                     if item.get(name) is not None and str(item.get(name)).strip()),
                    f"{key}:criterion:{criterion_index + 1}",
                )
                if cid in criterion_ids:
                    return None
                criterion_ids.add(cid)
                description = next(
                    (str(item[name]).strip() for name in ("description","statement","expected","value")
                     if item.get(name) is not None and str(item.get(name)).strip()),
                    intent,
                )
                criteria.append({"criterion_id":cid,"description":description})
            normalized_tasks.append({
                "task_key":key, "intent":intent, "acceptance_criteria":criteria,
            })
            references[key] = key
            references[str(index + 1)] = key
            if raw.get("task_id") is not None:
                references[str(raw["task_id"])] = key

        if constraints is None:
            constraints = []
        if not isinstance(constraints, (list, tuple)):
            return None
        normalized_constraints: list[dict[str, Any]] = []
        for item in constraints:
            if not isinstance(item, Mapping):
                return None
            kind = item.get("kind")
            if not isinstance(kind, str) or not kind.strip() or "value" not in item:
                return None
            normalized_constraints.append({"kind":kind.strip(),"value":item["value"]})

        if dependencies is None:
            dependencies = []
        if not isinstance(dependencies, (list, tuple)):
            return None
        normalized_dependencies: list[dict[str, str]] = []
        seen_edges: set[tuple[str, str]] = set()
        for item in dependencies:
            if not isinstance(item, Mapping):
                return None
            predecessor_raw = item.get("predecessor_task_id", item.get("predecessor", item.get("from")))
            successor_raw = item.get("successor_task_id", item.get("successor", item.get("to")))
            predecessor = references.get(str(predecessor_raw))
            successor = references.get(str(successor_raw))
            kind = str(item.get("dependency_kind", item.get("kind", "FINISH_TO_START")))
            if predecessor is None or successor is None or kind != "FINISH_TO_START" or predecessor == successor:
                return None
            edge = (predecessor, successor)
            if edge in seen_edges:
                return None
            seen_edges.add(edge)
            normalized_dependencies.append({
                "predecessor_task_key":predecessor,
                "successor_task_key":successor,
                "dependency_kind":"FINISH_TO_START",
            })

        return {
            "objective": objective,
            "constraints": normalized_constraints,
            "tasks": normalized_tasks,
            "dependencies": normalized_dependencies,
        }

    @classmethod
    def _proposal_semantic_digest(cls, proposal: Mapping[str, Any]) -> str | None:
        tasks = proposal.get("tasks", proposal.get("task_definitions"))
        surface = cls._plan_semantic_surface(
            proposal.get("objective"), proposal.get("constraints", []),
            tasks, proposal.get("dependencies", []),
        )
        return canonical_sha256(surface) if surface is not None else None

    def _proposal_route_semantic_digest(self, tasks: Any) -> str | None:
        if not isinstance(tasks, (list, tuple)) or not tasks:
            return None
        normalized: list[dict[str, Any]] = []
        for index, raw in enumerate(tasks):
            if not isinstance(raw, Mapping):
                return None
            key = next(
                (str(raw[name]).strip() for name in ("task_key","key","semantic_key","name")
                 if raw.get(name) is not None and str(raw.get(name)).strip()),
                f"task-{index + 1}",
            )
            routing = raw.get("routing")
            routing = dict(routing) if isinstance(routing, Mapping) else {}
            role_name = str(routing.get("role") or "EXECUTOR").upper()
            role = self.role_registry.resolve(role_name)
            agent_name = str(routing.get("agent_name") or role.agent_name)
            requested_caps = routing.get("required_capabilities") or []
            if not isinstance(requested_caps, list) or not all(isinstance(item, str) and item for item in requested_caps):
                return None
            capabilities = list(dict.fromkeys([
                OPENCODE_AGENT_CAPABILITY, TASK_OUTCOME_REPORT, *requested_caps,
            ]))
            normalized.append({
                "task_key":key,
                "role":role.role,
                "agent_name":agent_name,
                "required_capabilities":capabilities,
                "isolation_policy":str(routing.get("isolation_policy") or "DEDICATED_TASK_SESSION"),
                "parallelism_policy":str(routing.get("parallelism_policy") or "SERIAL"),
            })
        return canonical_sha256(normalized)

    def _revision_route_semantic_digest(self, mission_id: str, revision: Any) -> str | None:
        if revision is None:
            return None
        state = self.session_control.state(mission_id)
        normalized: list[dict[str, Any]] = []
        for index, raw in enumerate(getattr(revision, "task_definitions", ())):
            if not isinstance(raw, Mapping):
                return None
            task_id = raw.get("task_id")
            key = raw.get("task_key")
            if not isinstance(task_id, str) or not task_id or not isinstance(key, str) or not key:
                return None
            route = state.route(task_id)
            if route is None:
                # Missing current route is not permission to collapse a replan.
                return None
            normalized.append({
                "task_key":key,
                "role":route.role,
                "agent_name":route.agent_name,
                "required_capabilities":list(route.required_capabilities),
                "isolation_policy":route.isolation_policy,
                "parallelism_policy":route.parallelism_policy,
            })
        return canonical_sha256(normalized) if normalized else None

    @classmethod
    def _revision_semantic_digest(cls, revision: Any) -> str | None:
        if revision is None:
            return None
        tasks = [dict(item) for item in getattr(revision, "task_definitions", ())]
        # Frozen WorkGraph dependencies reference canonical task ids. Map those
        # ids back to semantic task keys before comparing with a fresh proposal.
        surface = cls._plan_semantic_surface(
            getattr(revision, "objective", None),
            [dict(item) for item in getattr(revision, "constraints", ())],
            tasks,
            [dict(item) for item in getattr(revision, "dependencies", ())],
        )
        return canonical_sha256(surface) if surface is not None else None

    @_coordinated
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
        business_before_plan = business_cursor(self.runtime, mission_id)
        replanning_was_active = any(
            progress.phase == "REPLANNING"
            for progress in self.session_control.state(mission_id).progress_records
        )
        stable_proposal = {
            "objective": proposal.get("objective"),
            "constraints": proposal.get("constraints", []),
            # Routing metadata is not R2.3 WorkGraph content; keep the frozen R2.3
            # candidate semantic surface unchanged.
            "tasks": [({k: v for k, v in item.items() if k != "routing"} if isinstance(item, Mapping) else item) for item in tasks],
            "dependencies": proposal.get("dependencies", []),
        }
        proposal_digest = canonical_sha256(stable_proposal)
        candidate_semantic_digest = self._proposal_semantic_digest(stable_proposal)
        current_semantic_digest = self._revision_semantic_digest(current_revision)
        candidate_route_digest = self._proposal_route_semantic_digest(normalized_tasks)
        current_route_digest = self._revision_route_semantic_digest(mission_id, current_revision)
        if (
            current_plan is not None
            and current_revision is not None
            and candidate_semantic_digest is not None
            and candidate_semantic_digest == current_semantic_digest
            and candidate_route_digest is not None
            and candidate_route_digest == current_route_digest
        ):
            # A new cursor/revision identity is not semantic business progress.
            # Do not call frozen R2.3: doing so would legitimately persist a new
            # Revision identity and make the Event Stream look like progress.
            # The durable current Revision remains the sole Plan Truth.
            return {
                "schema_version":G2_SCHEMA,
                "status":"PASS",
                "truth_source":"R1_EVENT_STREAM",
                "operation":"PLAN_PROPOSAL",
                "ai_authored_proposal_digest":proposal_digest,
                "runtime_governed_result":{
                    "outcome":"NO_CHANGE", "status":"NO_CHANGE",
                    "mission_id":mission_id, "active_goal_id":goal.goal_id,
                    "plan_id":current_plan.plan_id,
                    "revision_id":current_plan.current_revision_id,
                    "content_hash":current_revision.content_hash,
                    "reason_code":"PLAN_UNCHANGED",
                    "reason":"Candidate semantic content matches the durable current Revision",
                    "c3_semantic_digest":candidate_semantic_digest,
                    "c3_route_semantic_digest":candidate_route_digest,
                    "frozen_r2_3_invoked":False,
                },
                "route_requirements":[],
                "closed_planner_sessions":[],
                "resolved_progress_ids":[],
                "semantic_business_progress":False,
                "stalled_replan_no_change":replanning_was_active,
                "autonomous_handoff":None,
                "next":None,
                "head_seq":self.runtime.get_head_seq(mission_id),
            }

        planning_cursor = self.runtime.get_head_seq(mission_id)
        # R2.3 request_digest deliberately binds planning_cursor. Therefore the
        # fallback planner_request_id must identify one cursor-qualified planning
        # attempt too; reusing proposal-only identity across a later REPLAN would
        # correctly trigger frozen R2.3 IDEMPOTENCY_CONFLICT.
        request_id = str(
            proposal.get("planner_request_id")
            or f"g2:plan:{mission_id}:{planning_cursor}:{proposal_digest[:20]}"
        )
        item = PlannerInput(
            mission_id=mission_id,
            active_goal_id=goal.goal_id,
            goal_revision=goal.revision,
            goal_definition_digest=canonical_sha256(goal.definition),
            scope_digest=goal.definition.get("scope_digest") or canonical_sha256(goal.definition.get("execution_scope", {})),
            planning_cursor=planning_cursor,
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
        business_after_plan = business_cursor(self.runtime, mission_id)
        semantic_progress = business_after_plan > business_before_plan
        stalled_replan_no_change = accepted and replanning_was_active and not semantic_progress
        resolved_progress = (
            self._resolve_replanning_progress_after_plan(mission_id)
            if accepted and semantic_progress else []
        )
        closed_planner_sessions = (
            self._close_planning_sessions_after_plan(mission_id)
            if accepted and not stalled_replan_no_change else []
        )
        next_state = self.advance(mission_id) if accepted and not stalled_replan_no_change else None
        return {
            "schema_version": G2_SCHEMA,
            "status": "PASS" if accepted else result.outcome,
            "truth_source": "R1_EVENT_STREAM",
            "operation": "PLAN_PROPOSAL",
            "ai_authored_proposal_digest": proposal_digest,
            "runtime_governed_result": result.to_dict(),
            "route_requirements": routes,
            "closed_planner_sessions": closed_planner_sessions,
            "resolved_progress_ids": resolved_progress,
            "semantic_business_progress": semantic_progress if accepted else False,
            "stalled_replan_no_change": stalled_replan_no_change if accepted else False,
            "autonomous_handoff": "SCHEDULER" if accepted and not stalled_replan_no_change else None,
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
        context = ExecutionContextApplicationService(self.runtime).build(BuildExecutionContextRequest(
            execution_attempt_id=attempt.attempt_id, mission_id=mission_id,
            cursor=attempt.context_cursor,
            target=ContextTarget("TASK", plan_id, revision_id, task_id),
            knowledge_set=KnowledgeSetInput(), policy_id=attempt.policy_id, policy_version=attempt.policy_version,
            knowledge_scope={"mission_id": mission_id, "task_id": task_id},
        ))
        if context.semantic_digest != attempt.context_semantic_digest:
            raise RuntimeError("G2_1_RESUME_CONTEXT_DIGEST_MISMATCH")
        envelope["context_pack_reference"] = {
            "authority": "R1_EVENT_STREAM", "cursor": context.cursor.to_dict(),
            "semantic_digest": context.semantic_digest,
            "policy_id": context.policy_id, "policy_version": context.policy_version,
        }
        # Bootstrap carries a bounded extract. Canonical ContextPack is always
        # reconstructible from its exact cursor/digest; no conversation copy is
        # a resume source. Never paste an unbounded Event Stream into a Session.
        extract: list[dict[str, Any]] = []
        remaining = 8192
        omitted = 0
        for section in context.sections:
            for item in section.items:
                entry = {"section": section.name, "item": item.to_dict()}
                size = len(json.dumps(entry, ensure_ascii=False).encode("utf-8"))
                if size > remaining:
                    omitted += 1
                    continue
                extract.append(entry)
                remaining -= size
        envelope["bounded_context_extract"] = {"items": extract, "omitted_items": omitted, "max_bytes": 8192}
        envelope["resume_checkpoint"] = self._latest_checkpoint(mission_id, task_id)
        envelope["logical_agent_id"] = self._route_task(mission_id, task_id).logical_agent_id
        from aitest_runtime.recovery_knowledge import session_view
        envelope["task_knowledge"] = session_view(self.runtime, mission_id, task_id, agent)
        envelope["instruction"] = (
            "Resume only this durable Task. Read canonical tools before acting. "
            "Do not observe, create, close, or rotate your own Session; the G2.1 Session Supervisor/Router owns Session lifecycle. "
            "Report terminal outcome with the exact mission_id/task_id/attempt_id/session_id from this envelope. "
            "Do not reconstruct Mission state from conversation history and do not silently replan."
        )
        return self._bounded_bootstrap(prefix, envelope)

    @staticmethod
    def _bounded_bootstrap(prefix: str, envelope: dict[str, Any]) -> str:
        def encode() -> str:
            return prefix + json.dumps(envelope, ensure_ascii=False, sort_keys=True)
        if len(encode().encode("utf-8")) > 16384:
            for key in ("goal", "task"):
                if envelope.get(key) is not None:
                    value = envelope[key]
                    envelope[key] = {"authority": "R1_EVENT_STREAM", "body_omitted": True,
                                     "digest": canonical_sha256(value), "read_via": "canonical status tools"}
        if len(encode().encode("utf-8")) > 16384:
            extract = envelope.get("bounded_context_extract")
            if isinstance(extract, dict):
                extract["omitted_items"] += len(extract["items"])
                extract["items"] = []
        text = encode()
        if len(text.encode("utf-8")) > 16384:
            raise RuntimeError("G2_1_BOOTSTRAP_METADATA_EXCEEDS_BUDGET")
        return text

    def _latest_checkpoint(self, mission_id: str, task_id: str) -> dict[str, Any] | None:
        record = next((item for item in reversed(self.session_control.state(mission_id).rotations)
                       if item.task_id == task_id and item.checkpoint), None)
        return dict(record.checkpoint) if record is not None else None

    def _rotation_checkpoint(self, mission_id: str, task_id: str, predecessor_session_id: str,
                             root_attempt_id: str, logical_agent_id: str) -> dict[str, Any]:
        composed = self.runtime.replay_composed(mission_id)
        execution = composed.extension_state("r1_3b_execution_resume")
        attempt = execution.latest_attempt(task_id) if execution is not None else None
        return {
            "schema": "aitest.g2.1.rotation-checkpoint.v1", "authority": "R1_EVENT_STREAM",
            "mission_id": mission_id, "task_id": task_id, "predecessor_session_id": predecessor_session_id,
            "root_attempt_id": root_attempt_id, "logical_agent_id": logical_agent_id,
            "attempt_id": attempt.attempt_id if attempt is not None else None,
            "through_seq": composed.seq, "state_digest": canonical_sha256(composed.to_dict()),
            "conversation_is_truth": False,
        }

    def _abort_predecessor(self, session_id: str) -> None:
        abort = getattr(self.raw_session_provider, "abort_session", None)
        if callable(abort):
            abort(session_id)

    def _business_effect_barrier(self, mission_id: str, *, task_id: str | None = None,
                                 session_id: str | None = None) -> dict[str, Any] | None:
        """Fence autonomous liveness while a side effect has no durable outcome.

        R1 ToolExecution intent is written before the external adapter call. A
        process death can therefore leave an intent with no outcome even when
        the external system may already have applied the effect. UNKNOWN and
        ATTEMPTED observations carry the same replay risk. None of these states
        may become a wake, rotation, replan, or Mission completion. Only
        canonical ToolExecution reconciliation may release the fence.
        """
        composed = self.runtime.replay_composed(mission_id)
        state = composed.extension_state("r1_4_tool_execution")
        unresolved: list[dict[str, Any]] = []
        for record in tuple(getattr(state, "executions", ()) or ()):
            intent = getattr(record, "intent", None)
            if intent is None:
                continue
            raw_policy = getattr(intent, "side_effect_policy", None)
            policy = getattr(raw_policy, "value", str(raw_policy or ""))
            if policy == "NONE":
                continue
            if task_id is not None and getattr(intent, "task_id", None) != task_id:
                continue
            fact = getattr(record, "execution_fact", None)
            reconciliation = getattr(record, "reconciliation", None)
            raw_state = getattr(record, "side_effect_state", None)
            state_value = getattr(raw_state, "value", str(raw_state or ""))
            intent_without_outcome = fact is None and reconciliation is None
            if not intent_without_outcome and state_value not in {"ATTEMPTED", "UNKNOWN"}:
                continue
            unresolved.append({
                "tool_execution_id": str(getattr(intent, "tool_execution_id", "")),
                "task_id": str(getattr(intent, "task_id", "")),
                "runtime_session_id": str(getattr(intent, "runtime_session_id", "")),
                "side_effect_policy": policy,
                "side_effect_state": "INTENT_WITHOUT_OUTCOME" if intent_without_outcome else state_value,
            })
        if not unresolved:
            return None
        refs = sorted(unresolved, key=lambda item: item["tool_execution_id"])
        return {
            "status":"WAIT",
            "reason":"BUSINESS_EFFECT_RECONCILIATION_REQUIRED",
            "session_id":session_id,
            "tool_execution_refs":refs[:16],
            "unresolved_effect_count":len(refs),
            "truth_source":"R1_EVENT_STREAM",
        }

    def _activity_barrier(self, mission_id: str, session_id: str, task_id: str | None = None):
        from ..mission_controls import pending_controls
        if pending_controls(self.runtime, mission_id=mission_id, stopping_only=True, limit=1):
            return {'status':'WAIT','reason':'MISSION_CONTROL_PENDING','session_id':session_id}
        composed = self.runtime.replay_composed(mission_id)
        if composed.core_state.mission.status != MissionStatus.ACTIVE:
            return {'status':'WAIT','reason':'MISSION_NOT_ACTIVE','session_id':session_id}
        gates = composed.extension_state('r2_6_human_gate')
        if any(g.status == 'PENDING' and (task_id is None or g.task_id == task_id)
               for g in getattr(gates,'gates',())):
            return {'status':'WAIT','reason':'WAITING_HUMAN','session_id':session_id}
        effect_barrier = self._business_effect_barrier(
            mission_id, task_id=task_id, session_id=session_id,
        )
        if effect_barrier:
            return effect_barrier
        if any(x['session_id'] == session_id and x['phase'] in {'CLAIMED','UNKNOWN'}
               for x in self.session_control.state(mission_id).context_dispatches):
            return {'status':'WAIT','reason':'CONTEXT_DELIVERY_UNCONFIRMED','session_id':session_id}
        activity = getattr(self.raw_session_provider,'session_activity',None)
        if not callable(activity):
            return {'status':'WAIT','reason':'ACTIVITY_UNAVAILABLE','session_id':session_id}
        try: observed = activity(session_id)
        except Exception as exc:
            return {'status':'WAIT','reason':'ACTIVITY_UNAVAILABLE','error':type(exc).__name__,'session_id':session_id}
        if observed != 'idle':
            return {'status':'WAIT','reason':'WAIT_BUSY' if observed == 'busy' else 'WAIT_BACKOFF' if observed == 'retry' else 'ACTIVITY_UNAVAILABLE','session_id':session_id}
        return None

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

    @_coordinated
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
        if route.decision == 'REUSE' and latest is not None:
            bound = next((p for p in reversed(self.session_control.state(mission_id).provisions)
                          if p.status == 'BOUND' and p.external_session_id == latest.runtime_session_id
                          and p.task_id == task_id and p.logical_agent_id == logical_agent_id), None)
            if bound is not None:
                # Reuse the successor's own immutable provision; never rebind
                # the initial Task token to a later Session after rotation.
                with self.provisioning_provider.provision(bound.provision_token, bound.title):
                    result = super()._provision_active_task_session(
                        mission_id=mission_id, plan_id=plan_id, revision_id=revision_id,
                        task_id=task_id, agent=route.agent_name, parent_session_id=parent_session_id)
                return {**result, 'route':route.to_dict(), 'provision_token':bound.provision_token}
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
            if result.get('status') != 'ROTATED':return result
            return {**result, "status": "DISPATCH_REPAIRED_BY_ROTATION", "route": route.to_dict()}
        try:
            with self.provisioning_provider.provision(token, title):
                result = super()._provision_active_task_session(
                    mission_id=mission_id, plan_id=plan_id, revision_id=revision_id,
                    task_id=task_id, agent=route.agent_name, parent_session_id=parent_session_id,
                )
        except ContextDeliveryUnconfirmed as exc:
            return {'status':'WAIT','reason':str(exc),'task_id':task_id,'prompt_sent':False,'truth_source':'R1_EVENT_STREAM'}
        session_id = result.get("session_id") or (result.get("external_session") or {}).get("session_id")
        if not session_id:
            raise RuntimeError("TASK_SESSION_ID_MISSING_AFTER_PROVISION")
        self._bind_provision_if_needed(mission_id, token, str(session_id))
        return {**result, "route": route.to_dict(), "provision_token": token}

    @_coordinated
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

    @_coordinated
    def advance(self, mission_id: str, *, agent: str | None = None, parent_session_id: str | None = None) -> dict[str, Any]:
        if agent is not None:
            raise RuntimeError("SESSION_ROUTER_AGENT_OVERRIDE_FORBIDDEN")
        result = super().dispatch_next(mission_id, agent=DEFAULT_WORKER_AGENT, parent_session_id=parent_session_id)
        return {**result, "orchestration_advanced": True, "session_router": "G2_1"}

    @_coordinated
    def dispatch_next(self, mission_id: str, *, agent: str | None = None, parent_session_id: str | None = None) -> dict[str, Any]:
        from ..mission_controls import pending_controls
        if pending_controls(self.runtime, mission_id=mission_id, stopping_only=True, limit=1):
            return {'status':'WAIT','reason':'MISSION_CONTROL_PENDING','truth_source':'R1_EVENT_STREAM'}
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
            close = execute_control_command(self.runtime, CommandEnvelope(
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

    @_coordinated
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

        barrier = self._activity_barrier(mission_id, latest.runtime_session_id, task_id)
        if barrier:return barrier
        progress_cursor = business_cursor(self.runtime, mission_id)
        prior_failures = [x for x in self.session_control.state(mission_id).rotations
                          if x.task_id == task_id and x.root_attempt_id == latest.root_attempt_id
                          and x.requested_seq > progress_cursor]
        if len(prior_failures) >= 3:
            return {'status':'WAIT','reason':'DIAGNOSIS_REQUIRED_REPEATED_SESSION_FAILURE','failure_signature':sorted(set(reasons or [route.reason or 'RUNTIME_POLICY'])),'task_id':task_id,'recovery_count':len(prior_failures),'business_cursor':progress_cursor}

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
                 "predecessor_session_id": predecessor_session_id, "reasons": rotation_reasons,
                 "checkpoint": self._rotation_checkpoint(mission_id, task_id, predecessor_session_id, root_attempt_id, route.logical_agent_id)},
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
            self.provisioning_provider.send_context(
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

        self._abort_predecessor(predecessor_session_id)
        with self.provisioning_provider.provision(token, title, independent_session=True):
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

    @_coordinated
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
        # A worker can finish and close its external Session while the network
        # observation is in flight. Reconcile against fresh R1 before treating
        # that legitimate closure as an unreachable active Session.
        refreshed = self.runtime.replay_composed(mission_id)
        current_task = refreshed.extension_state("r1_2_work_graph").task(task_id)
        current_attempt = refreshed.extension_state("r1_3b_execution_resume").latest_attempt(task_id)
        current_session = refreshed.core_state.session(latest.runtime_session_id)
        if (current_task is None or current_task.lifecycle_state != TaskLifecycleState.ACTIVE
                or current_attempt is None or current_attempt.attempt_id != latest.attempt_id
                or current_session is None or current_session.status.value != "OPEN"):
            return {"schema_version": G2_SCHEMA, "status": "KEEP", "truth_source": "R1_EVENT_STREAM",
                    "reason": "OBSERVATION_SUPERSEDED_BY_DURABLE_LIFECYCLE", "rotation_reasons": [],
                    "session_id": latest.runtime_session_id, "task_id": task_id}
        raw = durable_pressure(raw, self.session_control.state(mission_id).observation(latest.runtime_session_id))
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
            "schema_version": G2_SCHEMA, "status": rotated.get('status','ROTATED'), "truth_source": "R1_EVENT_STREAM",
            "observation": obs.to_dict(), "rotation_reasons": reasons, "rotation": rotated,
        }

    @_coordinated
    def rotate_planning_session(self, mission_id: str, predecessor_session_id: str, reasons: list[str]) -> dict[str, Any]:
        mission_id = _text(mission_id, "mission_id")
        barrier = self._activity_barrier(mission_id, predecessor_session_id)
        if barrier:return barrier

        composed = self.runtime.replay_composed(mission_id)
        predecessor = composed.core_state.session(predecessor_session_id)
        if predecessor is None or predecessor.status.value != "OPEN":
            raise RuntimeError("PLANNER_PREDECESSOR_NOT_OPEN")
        attrs = dict(predecessor.attributes or {})
        phase = str(attrs.get("phase") or "")
        logical_agent_id = str(attrs.get("logical_agent_id") or "")
        if not logical_agent_id:
            raise RuntimeError("PLANNER_LOGICAL_AGENT_ID_MISSING")
        if phase not in {"PLANNING", "REPLANNING"}:
            raise RuntimeError("PLANNER_CONTROL_PHASE_INVALID")

        progress_id = None
        if phase == "REPLANNING":
            candidates = [
                p for p in self.session_control.state(mission_id).provisions
                if p.external_session_id == predecessor_session_id
                and p.phase in {"REPLANNING", "REPLANNING_ROTATION"}
                and p.status == "BOUND"
            ]
            if len(candidates) != 1:
                raise RuntimeError("C3_REPLAN_PREDECESSOR_PROVISION_AMBIGUOUS")
            root_attempt_id = str(candidates[0].root_attempt_id or "")
            if not root_attempt_id.startswith("replanning:"):
                raise RuntimeError("C3_REPLAN_LINEAGE_INVALID")
            progress_id = root_attempt_id.split(":", 1)[1]
            progress = self.session_control.state(mission_id).progress(progress_id)
            if progress is None or progress.phase != "REPLANNING":
                raise RuntimeError("C3_REPLAN_PROGRESS_REQUIRED")
            rotation_task_id = "__REPLANNING__:" + progress_id
            successor_phase = "REPLANNING"
            provision_phase = "REPLANNING_ROTATION"
            title = f"AITest Replan resume · {mission_id} · {progress_id[-12:]}"
        else:
            root_attempt_id = f"planning:{logical_agent_id}"
            rotation_task_id = "__PLANNING__"
            successor_phase = "PLANNING"
            provision_phase = "PLANNING_ROTATION"
            title = f"AITest Planner resume · {mission_id}"

        progress_cursor = business_cursor(self.runtime, mission_id)
        failures = [
            x for x in self.session_control.state(mission_id).rotations
            if x.task_id == rotation_task_id and x.requested_seq > progress_cursor
        ]
        if len(failures) >= 3:
            if phase == "REPLANNING":
                return {
                    "status":"WAIT", "reason":"DIAGNOSIS_REQUIRED_REPEATED_REPLANNER_FAILURE",
                    "recovery_count":len(failures), "progress_id":progress_id,
                    "business_cursor":progress_cursor,
                }
            return {"status":"WAIT","reason":"DIAGNOSIS_REQUIRED_REPEATED_PLANNER_FAILURE",
                    "recovery_count":len(failures),"business_cursor":progress_cursor}

        pending = self._pending_rotation(mission_id, rotation_task_id)
        if pending is not None:
            if pending.predecessor_session_id != predecessor_session_id:
                raise RuntimeError("PLANNER_ROTATION_PREDECESSOR_CHANGED")
            rotation_id = pending.rotation_id
            if pending.root_attempt_id != root_attempt_id:
                raise RuntimeError("PLANNER_ROTATION_ROOT_MISMATCH")
            rotation_reasons = list(pending.reasons)
        else:
            rotation_id = self._rotation_record_id(mission_id, rotation_task_id, predecessor_session_id)
            record = self.session_control.state(mission_id).rotation(rotation_id)
            if record is not None and record.status == "COMPLETED":
                return {
                    "status":"ROTATED", "truth_source":"R1_EVENT_STREAM", "phase":phase,
                    "rotation_id":rotation_id, "predecessor_session_id":predecessor_session_id,
                    "successor_session_id":record.successor_session_id,
                    "root_attempt_id":root_attempt_id, "idempotent_replay":True,
                }
            rotation_reasons = list(reasons)
            self.session_control.request_rotation(
                mission_id,
                {
                    "rotation_id":rotation_id, "task_id":rotation_task_id,
                    "root_attempt_id":root_attempt_id,
                    "predecessor_session_id":predecessor_session_id,
                    "reasons":rotation_reasons,
                    "checkpoint":self._rotation_checkpoint(
                        mission_id, rotation_task_id, predecessor_session_id,
                        root_attempt_id, logical_agent_id,
                    ),
                },
            )

        role = self.role_registry.resolve("PLANNER")
        token = self._provision_token(
            mission_id, logical_agent_id, provision_phase, predecessor_session_id
        )
        self._request_provision_if_needed(
            mission_id, token=token, task_id=None, logical_agent_id=logical_agent_id,
            root_attempt_id=root_attempt_id, role=role.role, agent_name=role.agent_name,
            phase=provision_phase, title=title,
        )
        expected_title = ProvisioningOpenCodeSessionProvider.title_for(token, title)
        matches = [item for item in self.raw_session_provider.list_sessions() if item.title == expected_title]
        if len(matches) > 1:
            raise RuntimeError("PLANNER_ROTATION_DUPLICATE_EXTERNAL_SUCCESSOR")
        external = matches[0] if matches else None
        if external is None:
            self._abort_predecessor(predecessor_session_id)
            with self.provisioning_provider.provision(token, title, independent_session=True):
                external = self.provisioning_provider.create_session(
                    title=title, parent_id=predecessor_session_id
                )

        refreshed = self.runtime.replay_composed(mission_id)
        successor_core = refreshed.core_state.session(external.session_id)
        if successor_core is None:
            self._open_core_session(
                mission_id=mission_id, external=external, task_id=None,
                agent=role.agent_name, phase=successor_phase,
                logical_agent_id=logical_agent_id,
            )
        elif successor_core.status.value != "OPEN":
            raise RuntimeError("PLANNER_ROTATION_SUCCESSOR_NOT_OPEN")
        else:
            successor_attrs = dict(successor_core.attributes or {})
            if (successor_attrs.get("phase") != successor_phase
                    or successor_attrs.get("logical_agent_id") != logical_agent_id):
                raise RuntimeError("PLANNER_ROTATION_SUCCESSOR_LINEAGE_MISMATCH")

        text = (
            self._replanning_context_message(mission_id, progress_id, logical_agent_id)
            if phase == "REPLANNING"
            else self._planning_context_message(mission_id, logical_agent_id)
        )
        self.provisioning_provider.send_context(
            session_id=external.session_id, agent=role.agent_name, text=text,
        )
        self._bind_provision_if_needed(mission_id, token, external.session_id)

        if phase == "REPLANNING":
            progress = self.session_control.state(mission_id).progress(progress_id)
            if progress is None or progress.phase != "REPLANNING":
                raise RuntimeError("C3_REPLAN_PROGRESS_REQUIRED")
            self.session_control.record_progress_state(mission_id, {
                "progress_id":progress.progress_id,
                "business_cursor":progress.business_cursor,
                "phase":"REPLANNING",
                "reason":progress.reason,
                "failure_signature":progress.failure_signature,
                "task_id":progress.task_id,
                "session_id":progress.session_id,
                "replan_lineage":root_attempt_id,
                "replan_session_id":external.session_id,
                "observed_at":_utc_now(),
            })

        self._close_predecessor_after_successor(
            mission_id, rotation_id=rotation_id,
            predecessor_session_id=predecessor_session_id,
            reason="G2_1_REPLANNER_SUCCESSOR_BOOTSTRAPPED" if phase == "REPLANNING"
                   else "G2_1_PLANNER_SUCCESSOR_BOOTSTRAPPED",
        )
        self.session_control.complete_rotation(mission_id, rotation_id, external.session_id)
        return {
            "status":"ROTATED", "truth_source":"R1_EVENT_STREAM", "phase":phase,
            "rotation_id":rotation_id, "predecessor_session_id":predecessor_session_id,
            "successor_session_id":external.session_id, "logical_agent_id":logical_agent_id,
            "root_attempt_id":root_attempt_id, "rotation_reasons":rotation_reasons,
            **({"progress_id":progress_id} if progress_id else {}),
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
                # Initial Planner lifecycle is stale once a governed Plan exists.
                return None
            if intent.phase == "PLANNING_ROTATION":
                state = self.session_control.state(mission_id)
                record = next((x for x in state.rotations if x.status == "REQUIRED" and x.task_id == "__PLANNING__"), None)
                if record is not None:
                    return self.rotate_planning_session(mission_id, record.predecessor_session_id, list(record.reasons))
            return self.open_planning_session(mission_id)
        if intent.phase in {"REPLANNING", "REPLANNING_ROTATION"}:
            lineage = str(intent.root_attempt_id or "")
            if not lineage.startswith("replanning:"):
                raise RuntimeError("C3_REPLAN_LINEAGE_INVALID")
            progress_id = lineage.split(":", 1)[1]
            progress = self.session_control.state(mission_id).progress(progress_id)
            if progress is None or progress.phase != "REPLANNING":
                return None
            if intent.phase == "REPLANNING_ROTATION":
                key = "__REPLANNING__:" + progress_id
                record = next((
                    x for x in self.session_control.state(mission_id).rotations
                    if x.status == "REQUIRED" and x.task_id == key
                       and x.root_attempt_id == lineage
                ), None)
                if record is not None:
                    return self.rotate_planning_session(
                        mission_id, record.predecessor_session_id, list(record.reasons)
                    )
            return self._open_replanning_session(mission_id, progress_id)
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

    @_coordinated
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
            mission = self.runtime.replay_composed(mission_id).core_state.mission
            # PAUSED/BLOCKED are durable suspended work, not terminal garbage.
            # Preserve in-flight receipts and Sessions; do not prompt them here.
            if mission and mission.status.value in {"PAUSED", "BLOCKED"}:
                for intent in state.provisions: by_token.pop(intent.provision_token, None)
                continue
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
                        activity_reader = getattr(self.raw_session_provider, "session_activity", None)
                        for item in matches:
                            # Durable terminality is authoritative, but OpenCode may
                            # still be executing the very tool call that produced the
                            # terminal transition. Killing a busy Host Session here
                            # can interrupt the return path before Scheduler handoff
                            # or durable receipt reconciliation completes. Cleanup is
                            # therefore fail-safe: delete only once Host activity is
                            # observably idle; unknown/busy/retry states are retried
                            # by the next Control Loop tick.
                            if callable(activity_reader):
                                try:
                                    activity = str(activity_reader(item.session_id))
                                except Exception as exc:
                                    actions.append({
                                        "mission_id": mission_id,
                                        "session_id": item.session_id,
                                        "token": intent.provision_token,
                                        "status": "TERMINAL_EXTERNAL_ACTIVITY_UNKNOWN_DEFERRED",
                                        "error": type(exc).__name__,
                                    })
                                    continue
                                if activity != "idle":
                                    actions.append({
                                        "mission_id": mission_id,
                                        "session_id": item.session_id,
                                        "token": intent.provision_token,
                                        "status": "TERMINAL_EXTERNAL_" + activity.upper() + "_DEFERRED",
                                    })
                                    continue
                            else:
                                actions.append({
                                    "mission_id": mission_id,
                                    "session_id": item.session_id,
                                    "token": intent.provision_token,
                                    "status": "TERMINAL_EXTERNAL_ACTIVITY_UNKNOWN_DEFERRED",
                                })
                                continue
                            close_external(item, status="TERMINAL_EXTERNAL_CLOSED", mission_id=mission_id, token=intent.provision_token)

        orphan_closed: list[str] = []
        unrelated_untagged: list[str] = []
        # Refresh the provider list because duplicate/terminal cleanup above may
        # have changed it, and recovery may have created a deterministic Session.
        refreshed_external = list(self.raw_session_provider.list_sessions())
        # The Scheduler (or recovery above) can persist a new ProvisionIntent
        # and create its Session while this reconciliation pass is running.
        # R1 intent is committed BEFORE the external create. Read R1 AFTER this
        # final external snapshot so a newly visible valid Session cannot be
        # deleted using the stale token set captured at the start of the pass.
        known_tokens = {
            intent.provision_token
            for durable_mission_id in self._all_mission_ids()
            for intent in self.session_control.state(durable_mission_id).provisions
        }
        for item in refreshed_external:
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
                if session.status.value != "OPEN" or attrs.get("phase") not in {"PLANNING","REPLANNING"}:
                    continue
                try:
                    raw = dict(self.raw_session_provider.observe_session(session.session_id))
                except OpenCodeSessionAdmissionPending:
                    raise
                except Exception as exc:
                    raw = {"reachable": False, "healthy": False, "error": type(exc).__name__, "provider": "OPENCODE"}
                raw = durable_pressure(raw, self.session_control.state(mission_id).observation(session.session_id))
                obs = SessionObservation.from_provider(session.session_id, raw)
                self.session_control.record_observation(mission_id, obs.to_dict())
                reasons = self.rotation_policy.evaluate(obs)
                if reasons:
                    result = self.rotate_planning_session(mission_id, session.session_id, reasons)
                    results.append({"mission_id": mission_id, "phase": attrs.get("phase"), "result": result})
                else:
                    results.append({"mission_id": mission_id, "phase": attrs.get("phase"), "status": "KEEP",
                                    "session_id": session.session_id, "observation": obs.to_dict()})
            composed = self.runtime.replay_composed(mission_id)
            graph = composed.extension_state("r1_2_work_graph")
            execution = composed.extension_state("r1_3b_execution_resume")
            if not isinstance(graph, WorkGraphState) or execution is None:
                continue
            _current_composed, _current_graph, _current_goal, current_plan = self._active_plan_context(mission_id)
            if current_plan is None or current_plan.current_revision_id is None:
                continue
            for task in graph.tasks:
                if (task.lifecycle_state != TaskLifecycleState.ACTIVE
                        or task.plan_id != current_plan.plan_id
                        or task.plan_revision_id != current_plan.current_revision_id):
                    continue
                latest = execution.latest_attempt(task.task_id)
                if latest is None:
                    continue
                result = self.observe_session(mission_id, task_id=task.task_id)
                results.append({"mission_id": mission_id, "task_id": task.task_id, "result": result})
            results.append({'mission_id':mission_id,'phase':'PROGRESS','result':self.progress_once(mission_id)})
        from ..general_work.execution import GeneralExecutionService
        general = GeneralExecutionService(self.runtime, self.workspace_root, self.raw_session_provider).supervise_once()
        return {
            "schema_version": "aitest.g2.1.control-loop-tick.v1",
            "status": "PASS" if reconciliation.get("status") == "PASS" else "REPAIR",
            "truth_source": "R1_EVENT_STREAM",
            "reconciliation": reconciliation, "supervision": results,
            "active_mission_count": len(mission_ids),
            "general_work_supervision": general,
        }

    def _quality_input_cursor(self, mission_id: str) -> int:
        """Return the latest durable quality *input* sequence.

        G4's own GOAL_EVALUATION / TESTING_GOAL_STATUS / REPLAN_REQUEST facts are
        control outputs. Counting them as progress would make PLAN_COMPLETE
        self-excite forever. Only execution/measurement/evidence/human/defect
        inputs advance this generation.
        """
        control_kinds = {"GOAL_EVALUATION", "TESTING_GOAL_STATUS", "REPLAN_REQUEST"}
        latest = 0
        for event in self.runtime.list_events(mission_id):
            et = str(event.event_type)
            relevant = (
                et.startswith("task.outcome_recorded.")
                or et.startswith("g3.")
                or et.startswith("r2.6.")
                or et.startswith("r3.")
                or et.startswith("r4.")
            )
            if et == "g4.fact_recorded.v1":
                fact_kind = str((event.payload or {}).get("fact_kind") or "")
                relevant = fact_kind not in control_kinds
            elif et.startswith("g4."):
                # No other G4 control event is currently a quality input.
                relevant = False
            if relevant:
                latest = max(latest, int(event.seq))
        return latest

    def _completion_blockers(self, mission_id: str) -> list[str]:
        """Conservative cross-layer gate before Core Mission completion."""
        composed = self.runtime.replay_composed(mission_id)
        blockers: list[str] = []

        human = composed.extension_state("r2_6_human_gate")
        for gate in getattr(human, "gates", ()):
            if getattr(gate, "is_blocking", False):
                blockers.append("HUMAN_GATE:" + str(gate.gate_id))

        r36 = composed.extension_state("r3_6_defect_investigation_rca")
        r43 = composed.extension_state("r4_3_confirmed_defect_fix_resolution_lifecycle")
        assessments = tuple(getattr(r36, "defect_assessments", ()) or ())
        lifecycles = tuple(getattr(r43, "confirmed_defect_lifecycles", ()) or ())
        for candidate in tuple(getattr(r36, "candidates", ()) or ()):
            matches = [item for item in assessments if item.candidate_id == candidate.candidate_id]
            if len(matches) != 1:
                blockers.append("DEFECT_CANDIDATE_UNASSESSED:" + candidate.candidate_id)
                continue
            assessment = matches[0]
            if assessment.outcome in {"INCONCLUSIVE", "BLOCKED"}:
                blockers.append("DEFECT_ASSESSMENT_" + assessment.outcome + ":" + candidate.candidate_id)
                continue
            if assessment.outcome == "CONFIRMED_DEFECT":
                handed = [
                    item for item in lifecycles
                    if item.r3_6_defect_assessment_ref.object_id == assessment.assessment_id
                    and item.r3_6_defect_assessment_ref.source_digest == assessment.defect_assessment_digest
                    and item.r3_6_assessment_digest == assessment.defect_assessment_digest
                ]
                if len(handed) != 1:
                    blockers.append("CONFIRMED_DEFECT_HANDOFF_REQUIRED:" + candidate.candidate_id)
        return sorted(set(blockers))

    def _complete_quality_converged_mission(self, mission_id: str, *, quality_cursor: int,
                                            g4_goal_id: str, g4_status: str) -> dict[str, Any]:
        composed = self.runtime.replay_composed(mission_id)
        mission = composed.core_state.mission
        if mission is None:
            raise RuntimeError("MISSION_NOT_FOUND")
        if mission.status == MissionStatus.COMPLETED:
            return {
                "status":"COMPLETED", "reason":"TEST_SUFFICIENT",
                "truth_source":"R1_EVENT_STREAM", "idempotent_replay":True,
                "g4_goal_id":g4_goal_id, "g4_status":g4_status,
            }
        if mission.status != MissionStatus.ACTIVE or not mission.active_goal_id:
            return {"status":"WAIT","reason":"MISSION_NOT_ACTIVE","truth_source":"R1_EVENT_STREAM"}

        goal = composed.core_state.goal(mission.active_goal_id)
        if goal is None:
            raise RuntimeError("ACTIVE_GOAL_NOT_FOUND")
        actor = ActorRef("SYSTEM", "c3-quality-convergence")
        generation = canonical_sha256({
            "mission_id":mission_id, "quality_cursor":quality_cursor,
            "g4_goal_id":g4_goal_id, "g4_status":g4_status,
        })[:32]
        if goal.status.value == "ACTIVE":
            changed = self.runtime.execute(CommandEnvelope(
                "c3:goal-achieved:" + generation, "CHANGE_GOAL_STATUS", mission_id,
                self.runtime.get_head_seq(mission_id), actor,
                {"goal_id":goal.goal_id, "status":"ACHIEVED"},
            ))
            if not changed.ok:
                raise changed.error or RuntimeError("C3_GOAL_ACHIEVEMENT_REJECTED")
        elif goal.status.value != "ACHIEVED":
            return {"status":"WAIT","reason":"CORE_GOAL_NOT_ACHIEVABLE","truth_source":"R1_EVENT_STREAM"}

        refreshed = self.runtime.replay_composed(mission_id)
        if refreshed.core_state.mission.status == MissionStatus.COMPLETED:
            return {
                "status":"COMPLETED", "reason":"TEST_SUFFICIENT",
                "truth_source":"R1_EVENT_STREAM", "idempotent_replay":True,
                "g4_goal_id":g4_goal_id, "g4_status":g4_status,
            }
        completed = self.runtime.execute(CommandEnvelope(
            "c3:mission-complete:" + generation, "COMPLETE_MISSION", mission_id,
            self.runtime.get_head_seq(mission_id), actor,
            {"reason":"TEST_SUFFICIENT:" + g4_status},
        ))
        if not completed.ok:
            raise completed.error or RuntimeError("C3_MISSION_COMPLETION_REJECTED")
        return {
            "status":"COMPLETED", "reason":"TEST_SUFFICIENT",
            "truth_source":"R1_EVENT_STREAM", "quality_cursor":quality_cursor,
            "g4_goal_id":g4_goal_id, "g4_status":g4_status,
        }

    def _handle_plan_complete(self, mission_id: str, scheduler: Mapping[str, Any]) -> dict[str, Any]:
        effect_barrier = self._business_effect_barrier(mission_id)
        if effect_barrier:
            return {**effect_barrier, "scheduler":dict(scheduler)}
        from ..g4 import G4RealExecutionService, TestObjectiveController
        quality_cursor = self._quality_input_cursor(mission_id)
        g4 = G4RealExecutionService(self.runtime, orchestration=self)
        try:
            goal = g4.goal(mission_id)
        except RuntimeError as exc:
            if getattr(exc, "code", None) != "G4_TESTING_GOAL_NOT_FOUND":
                raise
            replan = self._handle_no_progress(
                mission_id, task_id=None, session_id=None,
                reason="PLAN_COMPLETE_TESTING_GOAL_MISSING", cursor=quality_cursor,
            )
            return {**replan, "scheduler":dict(scheduler), "quality_cursor":quality_cursor}

        goal_id = str(goal["payload"]["goal_id"])
        _composed, _graph, _goal, current_plan = self._active_plan_context(mission_id)
        if current_plan is None or current_plan.current_revision_id is None:
            raise RuntimeError("C3_QUALITY_PLAN_REVISION_REQUIRED", mission_id)
        generation_id = "c3-quality:" + canonical_sha256({
            "mission_id": mission_id,
            "plan_id": current_plan.plan_id,
            "plan_revision_id": current_plan.current_revision_id,
            "g4_goal_id": goal_id,
            "quality_cursor": quality_cursor,
        })[:40]
        prior = self.session_control.state(mission_id).quality_decision(generation_id)
        if prior is not None:
            decision = {
                "status": prior.g4_status,
                "truth_source": "R1_EVENT_STREAM",
                "next_action": prior.next_action,
                "durable_replay": True,
                "generation_id": generation_id,
                "evaluation_fact_id": prior.evaluation_fact_id,
                "replan_request_fact_id": prior.replan_request_fact_id,
            }
        else:
            decision = TestObjectiveController(g4).tick(
                mission_id, goal_id,
                replan_context={
                    "trigger":"PLAN_COMPLETE",
                    "quality_input_cursor":quality_cursor,
                    "scheduler_status":"PLAN_COMPLETE",
                    "quality_generation_id":generation_id,
                },
            )
            status_now = str(decision.get("goal_status") or decision.get("status") or "")
            next_action_now = str(decision.get("next_action") or "")
            evaluation = decision.get("evaluation")
            replan = decision.get("replan")
            evaluation_fact_id = (
                str(evaluation.get("fact_id")) if isinstance(evaluation, Mapping) and evaluation.get("fact_id")
                else str(getattr(evaluation, "fact_id", "")) or None
            )
            replan_request_fact_id = (
                str(replan.get("fact_id")) if isinstance(replan, Mapping) and replan.get("fact_id")
                else str(getattr(replan, "fact_id", "")) or None
            )
            stable = {
                "generation_id":generation_id,
                "quality_cursor":quality_cursor,
                "plan_id":current_plan.plan_id,
                "plan_revision_id":current_plan.current_revision_id,
                "g4_goal_id":goal_id,
                "g4_status":status_now,
                "next_action":next_action_now,
                "evaluation_fact_id":evaluation_fact_id,
                "replan_request_fact_id":replan_request_fact_id,
            }
            stable["decision_digest"] = canonical_sha256(stable)
            self.session_control.record_quality_decision(mission_id, stable)
            decision = {**decision, "generation_id":generation_id, "durable_replay":False}

        status = str(decision.get("goal_status") or decision.get("status") or "")
        next_action = str(decision.get("next_action") or "")

        if next_action == "WAIT_COVERAGE_REFRESH" or status == "WAITING_MEASUREMENT":
            return {
                "status":"WAIT", "reason":"QUALITY_MEASUREMENT_REQUIRED",
                "truth_source":"R1_EVENT_STREAM", "quality_cursor":quality_cursor,
                "g4_goal_id":goal_id, "g4_status":status,
                "quality_controller":decision, "scheduler":dict(scheduler),
            }

        if next_action == "G3_REPLAN" or status == "REPLANNING":
            replan = self._handle_no_progress(
                mission_id, task_id=None, session_id=None,
                reason="PLAN_COMPLETE_G4_REPLANNING", cursor=quality_cursor,
            )
            return {
                **replan, "scheduler":dict(scheduler), "quality_cursor":quality_cursor,
                "g4_goal_id":goal_id, "g4_status":status, "quality_controller":decision,
            }

        if status not in {"SATISFIED", "COMPLETED_WITH_ACCEPTED_GAP"}:
            return {
                "status":"WAIT", "reason":"QUALITY_CONVERGENCE_NOT_TERMINAL",
                "truth_source":"R1_EVENT_STREAM", "quality_cursor":quality_cursor,
                "g4_goal_id":goal_id, "g4_status":status,
                "quality_controller":decision, "scheduler":dict(scheduler),
            }

        blockers = self._completion_blockers(mission_id)
        if blockers:
            signature = canonical_sha256(blockers)[:16]
            replan = self._handle_no_progress(
                mission_id, task_id=None, session_id=None,
                reason=("PLAN_COMPLETE_QUALITY_BLOCKED:" + signature), cursor=quality_cursor,
            )
            return {
                **replan, "scheduler":dict(scheduler), "quality_cursor":quality_cursor,
                "g4_goal_id":goal_id, "g4_status":status,
                "completion_blockers":blockers, "quality_controller":decision,
            }

        completed = self._complete_quality_converged_mission(
            mission_id, quality_cursor=quality_cursor, g4_goal_id=goal_id, g4_status=status,
        )
        return {**completed, "scheduler":dict(scheduler), "quality_controller":decision}

    def _drive_replanning_progress(self, mission_id: str) -> dict[str, Any] | None:
        """Bounded autonomous recovery for a Planner that itself makes no progress.

        Each replanning Session gets one INITIAL prompt and at most one
        AUTO_CONTINUE for the same semantic business cursor.  A second idle tick
        at that same cursor rotates to a clean successor.  Repeated successor
        failure is already capped by rotate_planning_session; exhausting that
        budget blocks the durable ProgressRecord instead of retrying forever.
        """
        state = self.session_control.state(mission_id)
        active = [
            item for item in state.progress_records
            if item.phase == "REPLANNING" and item.replan_session_id
        ]
        if not active:
            return None
        progress = active[-1]
        session_id = str(progress.replan_session_id)
        barrier = self._activity_barrier(mission_id, session_id, progress.task_id)
        if barrier:
            return {
                **barrier,
                "phase":"REPLANNING",
                "progress_id":progress.progress_id,
                "failure_signature":progress.failure_signature,
                "retry_budget_consumed":False,
            }

        current_cursor = business_cursor(self.runtime, mission_id)
        text = self._replanning_context_message(
            mission_id,
            progress.progress_id,
            str(progress.replan_lineage or "").replace("replanning:", "", 1)
            and self.session_router.logical_agent_id(
                "aitest-planner", str(progress.replan_lineage)
            )
            or self.session_router.logical_agent_id(
                "aitest-planner", "replanning:" + progress.progress_id
            ),
        )
        try:
            delivery = dispatch_context(
                self,
                session_id=session_id,
                agent="aitest-planner",
                text=text,
                mode="AUTO_CONTINUE",
                cursor=current_cursor,
            )
        except ContextDeliveryUnconfirmed as exc:
            return {
                "status":"WAIT",
                "reason":str(exc),
                "phase":"REPLANNING",
                "progress_id":progress.progress_id,
                "session_id":session_id,
                "failure_signature":progress.failure_signature,
                "retry_budget_consumed":False,
                "truth_source":"R1_EVENT_STREAM",
            }

        if delivery.get("prompt_sent"):
            return {
                "status":"AUTO_CONTINUE_REPLANNING",
                "reason":"REPLANNER_IDLE_NO_BUSINESS_PROGRESS",
                "phase":"REPLANNING",
                "progress_id":progress.progress_id,
                "session_id":session_id,
                "business_cursor":current_cursor,
                "failure_signature":progress.failure_signature,
                "retry_budget_consumed":True,
                "delivery":delivery,
                "truth_source":"R1_EVENT_STREAM",
            }

        rotation = self.rotate_planning_session(
            mission_id,
            session_id,
            [
                "REPLANNER_NO_BUSINESS_PROGRESS",
                "FAILURE_SIGNATURE:" + progress.failure_signature[:24],
            ],
        )
        if (rotation.get("status") == "WAIT"
                and rotation.get("reason") == "DIAGNOSIS_REQUIRED_REPEATED_REPLANNER_FAILURE"):
            current = self.session_control.state(mission_id).progress(progress.progress_id)
            if current is not None and current.phase == "REPLANNING":
                self.session_control.record_progress_state(mission_id, {
                    "progress_id":current.progress_id,
                    "business_cursor":current.business_cursor,
                    "phase":"BLOCKED",
                    "reason":current.reason,
                    "failure_signature":current.failure_signature,
                    "task_id":current.task_id,
                    "session_id":current.session_id,
                    "replan_lineage":current.replan_lineage,
                    "replan_session_id":current.replan_session_id,
                    "observed_at":_utc_now(),
                })
                close_id = "c3:replanner-budget:" + current.progress_id + ":CLOSE"
                closed = execute_control_command(self.runtime, CommandEnvelope(
                    close_id, "CLOSE_SESSION", mission_id, self.runtime.get_head_seq(mission_id),
                    ActorRef("SYSTEM", "g2.1-progress"),
                    {"reason":"REPLANNER_RETRY_BUDGET_EXHAUSTED"},
                    session_id=session_id, idempotency_key=close_id,
                    correlation_id=current.progress_id, schema_version=1,
                ))
                if not closed.ok:
                    raise closed.error or RuntimeError(
                        "C3_REPLANNER_BUDGET_SESSION_CLOSE_REJECTED", session_id
                    )
                try:
                    self.raw_session_provider.delete_session(session_id)
                except Exception:
                    # Durable Core Session is already terminal. Reconciliation
                    # retries deletion of any still-visible package-owned Host
                    # Session and never resumes this blocked generation.
                    pass
            return {
                **rotation,
                "phase":"REPLANNING",
                "progress_id":progress.progress_id,
                "failure_signature":progress.failure_signature,
                "retry_budget_exhausted":True,
                "truth_source":"R1_EVENT_STREAM",
            }
        return {
            **rotation,
            "reason":"REPLANNER_NO_BUSINESS_PROGRESS",
            "failure_signature":progress.failure_signature,
            "retry_budget_consumed":True,
        }

    @_coordinated
    def progress_once(self, mission_id: str) -> dict[str, Any]:
        from ..mission_controls import pending_controls
        if pending_controls(self.runtime, mission_id=mission_id, stopping_only=True, limit=1):
            return {'status':'WAIT','reason':'MISSION_CONTROL_PENDING','truth_source':'R1_EVENT_STREAM'}
        """Reconcile one bounded scheduling/wake decision from current R1."""
        composed=self.runtime.replay_composed(mission_id)
        if composed.core_state.mission.status != MissionStatus.ACTIVE:
            return {'status':'WAIT','reason':'MISSION_NOT_ACTIVE'}
        for prior in self.session_control.state(mission_id).context_dispatches:
            if prior['phase'] not in {'CLAIMED','UNKNOWN'}:continue
            try:reconcile_context_receipt(self,mission_id,prior)
            except Exception:
                # Keep the durable unknown fence; a readback failure never
                # authorizes a fresh prompt or an implicit successor.
                continue
        replanning = self._drive_replanning_progress(mission_id)
        if replanning is not None:
            return replanning
        _composed, graph, _goal, plan=self._active_plan_context(mission_id)
        if plan is None:
            # Planner wake shares the same bounded send journal, never a new plan.
            sessions=[s for s in composed.core_state.sessions if s.status.value=='OPEN' and (s.attributes or {}).get('phase')=='PLANNING']
            if not sessions:return {'status':'WAIT','reason':'PLANNER_PROVISION_REQUIRED'}
            session=sessions[-1]
            barrier=self._activity_barrier(mission_id,session.session_id)
            if barrier:return barrier
            control=self.session_control.state(mission_id)
            observation=control.observation(session.session_id)
            if observation is None or not observation.reachable or observation.healthy is False:
                return {'status':'WAIT','reason':'HEALTH_RECOVERY_REQUIRED'}
            text=self._planning_context_message(mission_id,(session.attributes or {}).get('logical_agent_id','aitest-planner'))
            return self._wake_once(mission_id,session.session_id,'aitest-planner',text)
        tasks=[t for t in graph.tasks if t.plan_id==plan.plan_id and t.plan_revision_id==plan.current_revision_id]
        failed=[t for t in tasks if t.lifecycle_state==TaskLifecycleState.FAILED]
        if failed:
            # Technical task failure is explicit; this is not a SUT quality verdict.
            command_id='g21:progress-failed:'+canonical_sha256({'mission':mission_id,'revision':plan.current_revision_id,'tasks':[t.task_id for t in failed]})[:32]
            result=self.runtime.execute(CommandEnvelope(command_id,'FAIL_MISSION',mission_id,self.runtime.get_head_seq(mission_id),ActorRef('SYSTEM','g2.1-progress'),{'reason':'RUNTIME_TASK_FAILED: '+','.join(t.task_id for t in failed)}))
            if not result.ok:raise result.error or RuntimeError('PROGRESS_FAILURE_TRANSITION_REJECTED')
            return {'status':'FAILED','reason':'RUNTIME_TASK_FAILED','task_ids':[t.task_id for t in failed]}
        # Existing Scheduler evaluates dependencies, Gate exceptions and activation.
        scheduled=self.advance(mission_id)
        if scheduled.get('status')=='PLAN_COMPLETE':
            return self._handle_plan_complete(mission_id, scheduled)
        fresh=self.runtime.replay_composed(mission_id)
        graph=fresh.extension_state('r1_2_work_graph');execution=fresh.extension_state('r1_3b_execution_resume')
        wakes=[]
        for task in graph.tasks:
            if (task.lifecycle_state!=TaskLifecycleState.ACTIVE
                    or task.plan_id!=plan.plan_id
                    or task.plan_revision_id!=plan.current_revision_id):continue
            attempt=execution.latest_attempt(task.task_id)
            if attempt is None:continue
            barrier=self._activity_barrier(mission_id,attempt.runtime_session_id,task.task_id)
            if barrier:wakes.append(barrier);continue
            obs=self.session_control.state(mission_id).observation(attempt.runtime_session_id)
            if obs is None or not obs.reachable or obs.healthy is False:continue
            route=self._route_task(mission_id,task.task_id)
            text=self._context_message(mission_id=mission_id,plan_id=task.plan_id,revision_id=task.plan_revision_id,task_id=task.task_id,attempt=attempt,agent=route.agent_name)
            wakes.append(self._wake_once(mission_id,attempt.runtime_session_id,route.agent_name,text))
        return {'status':'PROGRESS_CHECKED','scheduler':scheduled,'wakes':wakes}

    @staticmethod
    def _host_progress_fingerprint(payload: Mapping[str, Any]):
        message_count = payload.get('message_count')
        last_activity = payload.get('last_activity_at')
        raw_digest = dict(payload.get('provider_state') or {}).get('raw_digest')
        if type(message_count) is int:
            return ('MESSAGE_COUNT', message_count, last_activity if isinstance(last_activity, str) else '')
        if isinstance(last_activity, str) and last_activity:
            return ('LAST_ACTIVITY', last_activity)
        if isinstance(raw_digest, str) and raw_digest:
            return ('RAW_DIGEST', raw_digest)
        return None

    def _accepted_wake_host_stability(self, mission_id: str, session_id: str, accepted: Mapping[str, Any]):
        """Require durable post-accept Host quiescence before declaring no progress.

        The initial AUTO_CONTINUE user prompt is already accepted before these
        observations are recorded.  A changed message-count/activity fingerprint
        therefore represents real Host/model/tool activity and resets the quiet
        window.  All samples come from R1 events so restart cannot forget them.
        """
        accepted_seq = int(accepted.get('recorded_seq') or 0)
        samples = []
        for event in self.runtime.list_events(mission_id):
            if int(event.seq) <= accepted_seq:
                continue
            if str(event.event_type) != 'g2_1.session_observation_recorded.v1':
                continue
            if str(event.session_id or '') != session_id:
                continue
            payload = dict(event.payload or {})
            if payload.get('reachable') is not True or payload.get('healthy') is False:
                continue
            fingerprint = self._host_progress_fingerprint(payload)
            observed_at = payload.get('observed_at')
            if fingerprint is None or not isinstance(observed_at, str):
                continue
            try:
                stamp = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
            except ValueError:
                continue
            samples.append((stamp, fingerprint, int(event.seq)))

        if not samples:
            return {
                'status':'WAIT', 'reason':'AUTO_CONTINUE_HOST_PROGRESS_EVIDENCE_PENDING',
                'session_id':session_id, 'post_accept_observation_count':0,
            }

        samples.sort(key=lambda item: item[2])
        stable_since = samples[0][0]
        fingerprint = samples[0][1]
        changes = 0
        for stamp, current, _seq in samples[1:]:
            if current != fingerprint:
                fingerprint = current
                stable_since = stamp
                changes += 1
        latest_at = samples[-1][0]
        stable_seconds = max(0.0, (latest_at - stable_since).total_seconds())
        if stable_seconds < AUTO_CONTINUE_STABLE_HOST_SECONDS:
            return {
                'status':'WAIT', 'reason':'AUTO_CONTINUE_HOST_PROGRESS_STABILIZING',
                'session_id':session_id,
                'post_accept_observation_count':len(samples),
                'host_progress_change_count':changes,
                'host_quiet_seconds':stable_seconds,
            }
        return None

    def _wake_once(self, mission_id, session_id, agent, text):
        receipts=[r for r in self.session_control.state(mission_id).context_dispatches if r['session_id']==session_id]
        if not receipts or receipts[-1]['phase']!='ACCEPTED':
            return {'status':'WAIT','reason':'INITIAL_DISPATCH_RECEIPT_REQUIRED','session_id':session_id}
        last=datetime.fromisoformat(receipts[-1]['recorded_at'].replace('Z','+00:00'))
        if (datetime.now(timezone.utc)-last).total_seconds()<POST_DISPATCH_GRACE_SECONDS:
            return {'status':'WAIT','reason':'POST_DISPATCH_GRACE','session_id':session_id}
        try:sent=dispatch_context(self,session_id=session_id,agent=agent,text=text,mode='AUTO_CONTINUE')
        except ContextDeliveryUnconfirmed as exc:return {'status':'WAIT','reason':str(exc),'session_id':session_id}
        if sent.get('prompt_sent'):
            return {'status':'AUTO_CONTINUE','reason':'NONTERMINAL_IDLE','session_id':session_id,'delivery':sent}

        # Idempotent delivery is not proof of no business progress. A real
        # OpenCode worker can transiently report idle between a tool result and
        # the model's resumed turn. Before replanning, require R1-recorded Host
        # observations after the accepted wake to become genuinely stable.
        if sent.get('status') in {'ALREADY_ACCEPTED','HOST_RECEIPT_RECONCILED'}:
            dispatch_id=sent.get('dispatch_id')
            accepted=next((
                r for r in reversed(self.session_control.state(mission_id).context_dispatches)
                if r.get('dispatch_id')==dispatch_id and r.get('phase')=='ACCEPTED'
            ),None)
            if accepted is None:
                return {
                    'status':'WAIT','reason':'AUTO_CONTINUE_ACCEPTED_RECEIPT_REQUIRED',
                    'session_id':session_id,'delivery':sent,
                }
            stability=self._accepted_wake_host_stability(mission_id,session_id,accepted)
            if stability is not None:
                return {**stability,'delivery':sent}

        composed=self.runtime.replay_composed(mission_id)
        task_id=None
        for task in composed.extension_state('r1_2_work_graph').tasks:
            execution=composed.extension_state('r1_3b_execution_resume')
            latest=execution.latest_attempt(task.task_id) if execution is not None else None
            if latest is not None and latest.runtime_session_id==session_id:
                task_id=task.task_id;break
        replan=self._handle_no_progress(
            mission_id, task_id=task_id, session_id=session_id,
            reason='AUTO_CONTINUE_NO_BUSINESS_PROGRESS', cursor=business_cursor(self.runtime,mission_id),
        )
        return {**replan,'stalled_session_id':session_id,'delivery':sent}


    def supervise_once(self) -> dict[str, Any]:
        """Autonomous tick with non-fatal pre-auth/runtime-admission waiting.

        OpenCode Web/process readiness is a different boundary from authenticated
        Session API admission.  A 401/403 keeps the same Web usable for human
        authentication and causes no Session mutation/rotation.  The next tick
        rebuilds from R1 and retries automatically.
        """
        try:
            return self._supervise_admitted_once()
        except CoordinationBusy:
            return {'status':'WAIT','reason':'RUNTIME_COORDINATION_BUSY','truth_source':'R1_EVENT_STREAM'}
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
