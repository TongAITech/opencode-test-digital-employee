"""Canonical G2 autonomous orchestration over the R1 Event Stream.

The AI/LLM is responsible for semantic decisions (for example, proposing a
Plan or choosing the best logical agent for a ready Task).  This module owns
only the durable/governed side of those decisions:

* R2.2 Mission Intake and Goal truth
* R2.3 Plan/PlanRevision validation and persistence
* R2.4 readiness/dependency/bounded scheduling
* R2.5 logical agent, Session rotation and Attempt lineage
* R2.6 human-gate persistence
* R1.3A/B execution context and resume anchors

Conversation text is never a source of Mission/Plan/Task/Attempt/Session truth.
The sole durable runtime store remains the canonical R1 Event Stream.

Production invariant: no mock OpenCode Session fallback.  A real bank runtime
must fail closed when the OpenCode Web session API is unavailable.  A fake
provider exists only for deterministic construction tests and is never selected
by the product entrypoint.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from .durable_core import ActorRef, CommandEnvelope, MissionStatus, RuntimeService, canonical_sha256
from .execution_context import KnowledgeSetInput
from .execution_resume import ExecutionResumeApplicationService, StartExecutionRequest
from .r2_2 import MissionIntakeOrchestrator
from .r2_2.contracts import normalize_scope
from .r2_3 import PlannerOrchestrator, PlannerInput
from .r2_4 import (
    DispatchBinding,
    LoopBudget,
    LoopProgress,
    SchedulingPolicy,
    activation_command,
    evaluate_readiness,
    make_dispatch_request,
    select_ready_tasks,
)
from .r2_5 import SessionOrchestrationService
from .r2_6 import HumanGateApplicationService
from .work_graph import TaskLifecycleState, WorkGraphState


G2_SCHEMA = "aitest.r2.autonomous-orchestration.v1"
OPENCODE_AGENT_CAPABILITY = "OPENCODE_AGENT_SESSION"
OPENCODE_AGENT_CAPABILITY_VERSION = "1"
DEFAULT_POLICY_ID = "r1.3a.structural"
DEFAULT_POLICY_VERSION = 1
DEFAULT_WORKER_AGENT = "aitest-executor"
ROTATE_MESSAGE_THRESHOLD = 60
ROTATE_COMPACTION_THRESHOLD = 1
ROTATE_CONTEXT_UTILIZATION_THRESHOLD = 0.85
KNOWN_AGENT_NAMES = frozenset(
    {
        "aitest-director",
        "aitest-planner",
        "aitest-scheduler",
        "aitest-executor",
        "aitest-evaluator",
        "aitest-diagnosis",
        "aitest-knowledge",
        "aitest-requirement-analyst",
        "aitest-code-analyst",
        "aitest-test-strategist",
        "aitest-case-designer",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _deadline(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return dict(value)


def _to_dict(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _to_dict(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_to_dict(item) for item in value]
    if isinstance(value, list):
        return [_to_dict(item) for item in value]
    return value


@dataclass(frozen=True)
class ExternalSession:
    session_id: str
    title: str
    directory: str
    raw: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "directory": self.directory,
        }


class OpenCodeSessionAdmissionPending(RuntimeError):
    """OpenCode Web is reachable but Session API admission is not ready yet.

    HTTP 401/403 is deliberately separated from malformed payloads or provider
    failures.  PFC Web startup must remain usable so a human can complete
    authentication; the autonomous Control Loop keeps retrying from R1 truth.
    """


class OpenCodeSessionProvider(Protocol):
    """Narrow external OpenCode boundary used by R2.5 orchestration."""

    def health(self) -> Mapping[str, Any]:
        ...

    def create_session(self, *, title: str, parent_id: str | None = None) -> ExternalSession:
        ...

    def send_context(self, *, session_id: str, agent: str, text: str) -> Mapping[str, Any]:
        ...

    def delete_session(self, session_id: str) -> bool:
        ...

    def list_sessions(self) -> tuple[ExternalSession, ...]:
        ...

    def observe_session(self, session_id: str) -> Mapping[str, Any]:
        ...


class DirectoryScopedOpenCodeSessionProvider:
    """Real OpenCode 1.18.3 Web API provider with explicit project binding.

    No fake/mock fallback exists here.  HTTP 401/403 means Web is reachable but
    Session API admission is still pending, so the background Supervisor waits
    without inventing Session truth.  Other HTTP/project-binding/shape failures
    remain hard failures.
    """

    def __init__(
        self,
        directory: str | Path,
        *,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.directory = str(Path(directory).resolve())
        self.base_url = (base_url or os.environ.get("AITEST_OPENCODE_ENDPOINT") or "http://127.0.0.1:4096").rstrip("/")
        self.username = username or os.environ.get("OPENCODE_SERVER_USERNAME") or "opencode"
        self.password = password if password is not None else os.environ.get("OPENCODE_SERVER_PASSWORD")
        self.timeout = timeout

    def _request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Any:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-opencode-directory": self.directory,
        }
        if self.password:
            token = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = "Basic " + token
        request = urllib.request.Request(self.base_url + path, data=payload, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            text = exc.read(12000).decode("utf-8", errors="replace")
            if exc.code in {401, 403}:
                raise OpenCodeSessionAdmissionPending(
                    f"OPENCODE_SESSION_ADMISSION_PENDING_HTTP_{exc.code}: {text[:2000]}"
                ) from exc
            raise RuntimeError(f"OPENCODE_SESSION_HTTP_{exc.code}: {text[:2000]}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"OPENCODE_SESSION_UNAVAILABLE: {type(exc).__name__}: {exc}") from exc

    def _directory_query(self) -> str:
        return urllib.parse.urlencode({"directory": self.directory})

    @staticmethod
    def _session_id(payload: Any) -> str | None:
        if isinstance(payload, Mapping):
            for key in ("id", "sessionID", "session_id"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for value in payload.values():
                found = DirectoryScopedOpenCodeSessionProvider._session_id(value)
                if found:
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = DirectoryScopedOpenCodeSessionProvider._session_id(value)
                if found:
                    return found
        return None

    def health(self) -> Mapping[str, Any]:
        value = self._request("GET", "/global/health")
        if not isinstance(value, Mapping):
            raise RuntimeError("OPENCODE_HEALTH_INVALID")
        return dict(value)

    def create_session(self, *, title: str, parent_id: str | None = None) -> ExternalSession:
        body: dict[str, Any] = {"title": _text(title, "title")}
        if parent_id:
            body["parentID"] = _text(parent_id, "parent_id")
        payload = self._request("POST", f"/session?{self._directory_query()}", body)
        session_id = self._session_id(payload)
        if not session_id:
            raise RuntimeError("OPENCODE_SESSION_CREATE_FAILED: response has no session id")
        return ExternalSession(session_id, title, self.directory, dict(payload) if isinstance(payload, Mapping) else {})

    def send_context(self, *, session_id: str, agent: str, text: str) -> Mapping[str, Any]:
        body = {
            "agent": _text(agent, "agent"),
            "noReply": False,
            "parts": [{"type": "text", "text": _text(text, "text")}],
        }
        payload = self._request(
            "POST",
            f"/session/{urllib.parse.quote(_text(session_id, 'session_id'))}/message?{self._directory_query()}",
            body,
        )
        return dict(payload) if isinstance(payload, Mapping) else {"accepted": True}

    def delete_session(self, session_id: str) -> bool:
        payload = self._request(
            "DELETE",
            f"/session/{urllib.parse.quote(_text(session_id, 'session_id'))}?{self._directory_query()}",
        )
        return bool(payload) if payload is not None else True

    def list_sessions(self) -> tuple[ExternalSession, ...]:
        payload = self._request("GET", f"/session?{self._directory_query()}")
        values: list[Any]
        if isinstance(payload, list):
            values = payload
        elif isinstance(payload, Mapping) and isinstance(payload.get("sessions"), list):
            values = list(payload.get("sessions") or [])
        else:
            # Session-list shape is part of the OpenCode 1.18.3 bank Field
            # Validation boundary.  Unknown shapes must fail closed; treating
            # them as an empty list could duplicate a crash-window Session.
            raise RuntimeError("OPENCODE_SESSION_LIST_INVALID")
        result: list[ExternalSession] = []
        for item in values:
            # Reconciliation is allowed to create/close package-owned Sessions,
            # so list identity must be strict. Silently skipping an unknown row
            # could hide a crash-window Session and cause duplicate provisioning.
            if not isinstance(item, Mapping):
                raise RuntimeError("OPENCODE_SESSION_LIST_ENTRY_INVALID")
            session_id = self._session_id(item)
            title_value = item.get("title")
            if not session_id or not isinstance(title_value, str):
                raise RuntimeError("OPENCODE_SESSION_LIST_ENTRY_INVALID")
            title = title_value
            directory_value = item.get("directory")
            if isinstance(directory_value, str) and directory_value.strip():
                directory = str(Path(directory_value).resolve())
                if os.path.normcase(directory) != os.path.normcase(str(Path(self.directory).resolve())):
                    # The request is explicitly directory-scoped. A conflicting
                    # directory in the response means project binding cannot be
                    # trusted; never adopt or kill Sessions from another project.
                    raise RuntimeError("OPENCODE_SESSION_DIRECTORY_SCOPE_MISMATCH")
            else:
                directory = self.directory
            result.append(ExternalSession(session_id, title, directory, dict(item)))
        return tuple(result)

    def observe_session(self, session_id: str) -> Mapping[str, Any]:
        payload = self._request(
            "GET",
            f"/session/{urllib.parse.quote(_text(session_id, 'session_id'))}?{self._directory_query()}",
        )
        if not isinstance(payload, Mapping):
            # Never translate an unknown observation payload into a healthy
            # Session.  The Supervisor catches this as unreachable/unhealthy.
            raise RuntimeError("OPENCODE_SESSION_OBSERVATION_INVALID")
        raw = dict(payload)
        observed_session_id = self._session_id(raw)
        if not observed_session_id or observed_session_id != session_id:
            # Exact session identity is the minimum verified shape.  Metric
            # fields may remain unknown/null until bank field validation.
            raise RuntimeError("OPENCODE_SESSION_OBSERVATION_INVALID")

        def _number(*keys: str) -> float | None:
            for key in keys:
                value = raw.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value)
            return None

        message_count = _number("messageCount", "message_count", "messages")
        compaction_count = _number("compactionCount", "compaction_count", "compactions")
        context_used = _number("contextUsed", "context_used", "tokensUsed", "tokens_used")
        context_limit = _number("contextLimit", "context_limit", "tokensLimit", "tokens_limit")
        context_utilization = _number("contextUtilization", "context_utilization")
        if context_utilization is None and context_used is not None and context_limit and context_limit > 0:
            context_utilization = context_used / context_limit
        unhealthy = raw.get("unhealthy")
        healthy = raw.get("healthy")
        if not isinstance(healthy, bool):
            healthy = (not bool(unhealthy or raw.get("error"))) if (unhealthy is not None or raw.get("error") is not None) else None
        return {
            "session_id": session_id,
            "observed_at": _utc_now(),
            "reachable": True,
            "healthy": healthy,
            "message_count": int(message_count) if message_count is not None else None,
            "compaction_count": int(compaction_count) if compaction_count is not None else None,
            "context_used": int(context_used) if context_used is not None else None,
            "context_limit": int(context_limit) if context_limit is not None else None,
            "context_utilization": context_utilization,
            "last_activity_at": raw.get("lastActivityAt") or raw.get("last_activity_at"),
            "provider": "OPENCODE",
            "raw_digest": canonical_sha256(raw),
        }


class FakeOpenCodeSessionProvider:
    """Construction-test provider only. Product entry never instantiates it."""

    def __init__(self, directory: str | Path = "/fake/workspace") -> None:
        self.directory = str(directory)
        self.counter = 0
        self.sessions: dict[str, ExternalSession] = {}
        self.messages: list[dict[str, Any]] = []
        self.observations: dict[str, dict[str, Any]] = {}

    def health(self) -> Mapping[str, Any]:
        return {"healthy": True, "provider": "FAKE_TEST_ONLY"}

    def create_session(self, *, title: str, parent_id: str | None = None) -> ExternalSession:
        self.counter += 1
        session_id = f"fake-opencode-session-{self.counter}"
        value = ExternalSession(session_id, title, self.directory, {"parentID": parent_id})
        self.sessions[session_id] = value
        return value

    def send_context(self, *, session_id: str, agent: str, text: str) -> Mapping[str, Any]:
        if session_id not in self.sessions:
            raise RuntimeError(f"FAKE_SESSION_NOT_FOUND: {session_id}")
        value = {"session_id": session_id, "agent": agent, "text": text}
        self.messages.append(value)
        return {"accepted": True, "session_id": session_id, "agent": agent}

    def delete_session(self, session_id: str) -> bool:
        self.observations.pop(session_id, None)
        return self.sessions.pop(session_id, None) is not None

    def list_sessions(self) -> tuple[ExternalSession, ...]:
        return tuple(self.sessions.values())

    def set_observation(self, session_id: str, **values: Any) -> None:
        if session_id not in self.sessions:
            raise RuntimeError(f"FAKE_SESSION_NOT_FOUND: {session_id}")
        self.observations[session_id] = dict(values)

    def observe_session(self, session_id: str) -> Mapping[str, Any]:
        if session_id not in self.sessions:
            raise RuntimeError(f"FAKE_SESSION_NOT_FOUND: {session_id}")
        message_count = sum(1 for item in self.messages if item.get("session_id") == session_id)
        value: dict[str, Any] = {
            "session_id": session_id,
            "observed_at": _utc_now(),
            "reachable": True,
            "healthy": True,
            "message_count": message_count,
            "compaction_count": 0,
            "context_used": None,
            "context_limit": None,
            "context_utilization": None,
            "last_activity_at": None,
            "provider": "FAKE_TEST_ONLY",
        }
        value.update(self.observations.get(session_id, {}))
        return value


class AutonomousOrchestrationService:
    """G2 product service binding the existing R2 contracts into one flow."""

    def __init__(
        self,
        runtime: RuntimeService,
        workspace_root: str | Path,
        *,
        session_provider: OpenCodeSessionProvider | None = None,
    ) -> None:
        self.runtime = runtime
        self.workspace_root = Path(workspace_root).resolve()
        self.session_provider = session_provider or DirectoryScopedOpenCodeSessionProvider(self.workspace_root)
        self.intake = MissionIntakeOrchestrator(runtime)
        self.planner = PlannerOrchestrator(runtime)
        self.execution = ExecutionResumeApplicationService(runtime)
        self.sessions = SessionOrchestrationService(runtime, execution_service=self.execution)
        self.human_gates = HumanGateApplicationService(runtime)

    @staticmethod
    def mission_scope_digest(request: Mapping[str, Any]) -> str:
        scope = normalize_scope(request.get("scope"))
        return canonical_sha256(scope)

    def _active_mission_for_scope_digest(self, scope_digest: str) -> str | None:
        conn = sqlite3.connect(str(self.runtime.db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT mission_id, state_json FROM mission_projection ORDER BY seq DESC, mission_id"
            ).fetchall()
            for row in rows:
                try:
                    mission = json.loads(row["state_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if mission.get("status") != "ACTIVE":
                    continue
                goal_id = mission.get("active_goal_id")
                if not goal_id:
                    continue
                goal_row = conn.execute(
                    "SELECT state_json FROM goal_projection WHERE mission_id=? AND goal_id=?",
                    (row["mission_id"], goal_id),
                ).fetchone()
                if goal_row is None:
                    continue
                try:
                    goal = json.loads(goal_row["state_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                definition = goal.get("definition") if isinstance(goal, Mapping) else None
                if isinstance(definition, Mapping) and definition.get("scope_digest") == scope_digest:
                    return str(row["mission_id"])
            return None
        finally:
            conn.close()

    def _resume_intake_result(self, mission_id: str, scope_digest: str) -> dict[str, Any]:
        composed = self.runtime.replay_composed(mission_id)
        mission = composed.core_state.mission
        return {
            "schema_version": G2_SCHEMA,
            "status": "RESUMED",
            "truth_source": "R1_EVENT_STREAM",
            "operation": "MISSION_RESUME_BY_SCOPE",
            "scope_digest": scope_digest,
            "intake": {
                "mission_id": mission_id,
                "goal_id": mission.active_goal_id if mission is not None else None,
                "resumed": True,
            },
            "activation": None,
            "head_seq": self.runtime.get_head_seq(mission_id),
        }

    def status(self, mission_id: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": G2_SCHEMA,
            "status": "PASS",
            "truth_source": "R1_EVENT_STREAM",
            "conversation_is_not_truth": True,
            "mock_session_fallback": "FORBIDDEN",
            "runtime_db": str(self.runtime.db_path),
        }
        if mission_id is None:
            return result
        mission_id = _text(mission_id, "mission_id")
        composed = self.runtime.replay_composed(mission_id)
        work_graph = composed.extension_state("r1_2_work_graph")
        execution = composed.extension_state("r1_3b_execution_resume")
        r25 = composed.extension_state("r2_5_session_orchestration")
        r26 = composed.extension_state("r2_6_human_gate")
        result.update(
            {
                "mission_id": mission_id,
                "head_seq": self.runtime.get_head_seq(mission_id),
                "core": composed.core_state.to_dict(),
                "work_graph": _to_dict(work_graph),
                "execution": _to_dict(execution),
                "session_orchestration": _to_dict(r25),
                "human_gates": _to_dict(r26),
            }
        )
        return result

    def intake_mission(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Create/revise Goal truth through R2.2 with runtime scope dedup/resume."""
        raw = dict(request)
        force_new = bool(raw.pop("force_new_mission", False))
        operation = str(raw.get("operation") or "CREATE").upper()
        scope_digest = self.mission_scope_digest(raw)
        if operation == "CREATE" and not force_new:
            existing = self._active_mission_for_scope_digest(scope_digest)
            if existing is not None:
                return self._resume_intake_result(existing, scope_digest)
        supplied_resolution = raw.pop("resolution", None)
        result = self.intake.intake(raw, resolution=supplied_resolution)
        state = self.runtime.replay(result.mission_id)
        activation = None
        if state.mission is not None and state.mission.status == MissionStatus.CREATED:
            activation = self.runtime.execute(
                {
                    "command_id": f"g2:{result.intake_id}:ACTIVATE_MISSION",
                    "type": "ACTIVATE_MISSION",
                    "mission_id": result.mission_id,
                    "expected_seq": self.runtime.get_head_seq(result.mission_id),
                    "actor": {"type": "SYSTEM", "id": "g2-autonomous-orchestration"},
                    "payload": {"reason": "R2.2 intake admitted to autonomous runtime"},
                    "correlation_id": result.intake_id,
                    "schema_version": 1,
                }
            )
            if not activation.ok:
                if activation.error is not None:
                    raise activation.error
                raise RuntimeError("G2_MISSION_ACTIVATION_REJECTED")
        return {
            "schema_version": G2_SCHEMA,
            "status": "PASS",
            "truth_source": "R1_EVENT_STREAM",
            "operation": "MISSION_INTAKE",
            "intake": result.to_dict(),
            "activation": activation.to_dict() if activation is not None else None,
            "scope_digest": scope_digest,
            "head_seq": self.runtime.get_head_seq(result.mission_id),
        }

    def open_planning_session(self, mission_id: str) -> dict[str, Any]:
        """Create/reuse the real OpenCode Planner Session before a Plan exists.

        R2.3 deliberately governs a Plan proposal but does not invent semantic
        tasks.  This pre-plan Session is therefore a Core Session anchored to
        Mission/Goal truth (not an ExecutionAttempt).  The planner agent must
        analyze evidence and submit its candidate through ``propose_plan``.
        """
        mission_id = _text(mission_id, "mission_id")
        composed = self.runtime.replay_composed(mission_id)
        mission = composed.core_state.mission
        if mission is None or mission.status != MissionStatus.ACTIVE or not mission.active_goal_id:
            raise RuntimeError("ACTIVE_MISSION_AND_GOAL_REQUIRED_FOR_PLANNING")
        goal = composed.core_state.goal(mission.active_goal_id)
        if goal is None:
            raise RuntimeError("ACTIVE_GOAL_NOT_FOUND")
        for item in reversed(composed.core_state.sessions):
            attrs = dict(item.attributes or {})
            if item.status.value == "OPEN" and attrs.get("phase") == "PLANNING" and attrs.get("opencode_agent") == "aitest-planner":
                return {
                    "schema_version": G2_SCHEMA,
                    "status": "ALREADY_OPEN",
                    "truth_source": "R1_EVENT_STREAM",
                    "conversation_is_not_truth": True,
                    "mission_id": mission_id,
                    "session_id": item.session_id,
                    "logical_agent_id": attrs.get("logical_agent_id"),
                    "head_seq": self.runtime.get_head_seq(mission_id),
                }
        title = f"AITest Planner · {mission_id}"
        external = self.session_provider.create_session(title=title)
        logical_agent_id = self._logical_agent_id("aitest-planner", f"planning:{mission_id}:{goal.revision}")
        try:
            self._open_core_session(
                mission_id=mission_id,
                external=external,
                task_id=None,
                agent="aitest-planner",
                phase="PLANNING",
                logical_agent_id=logical_agent_id,
            )
        except Exception:
            try:
                self.session_provider.delete_session(external.session_id)
            finally:
                raise
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
                "Do not infer Mission truth from conversation history."
            ),
        }
        self.session_provider.send_context(
            session_id=external.session_id,
            agent="aitest-planner",
            text="AITEST_CANONICAL_PLANNING_CONTEXT\n" + json.dumps(envelope, ensure_ascii=False, sort_keys=True),
        )
        return {
            "schema_version": G2_SCHEMA,
            "status": "PLANNER_SESSION_OPEN",
            "truth_source": "R1_EVENT_STREAM",
            "conversation_is_not_truth": True,
            "mission_id": mission_id,
            "external_session": external.to_dict(),
            "logical_agent_id": logical_agent_id,
            "head_seq": self.runtime.get_head_seq(mission_id),
        }

    def start_test(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Start or resume one canonical test Mission by governed scope."""
        intake = self.intake_mission(request)
        mission_id = intake["intake"]["mission_id"]
        _composed, _graph, _goal, current_plan = self._active_plan_context(mission_id)
        if current_plan is None:
            planner_session = self.open_planning_session(mission_id)
            return {
                "schema_version": G2_SCHEMA,
                "status": "PLANNING",
                "truth_source": "R1_EVENT_STREAM",
                "conversation_is_not_truth": True,
                "resumed_existing_mission": intake.get("status") == "RESUMED",
                "intake": intake,
                "planner_session": planner_session,
            }
        next_state = self.advance(mission_id)
        return {
            "schema_version": G2_SCHEMA,
            "status": "RESUMED",
            "truth_source": "R1_EVENT_STREAM",
            "conversation_is_not_truth": True,
            "resumed_existing_mission": True,
            "intake": intake,
            "next": next_state,
        }

    def continue_test(self, *, mission_id: str | None = None, scope: Mapping[str, Any] | None = None) -> dict[str, Any]:
        resolved = _text(mission_id, "mission_id") if mission_id else None
        if resolved is None:
            if scope is None:
                raise ValueError("mission_id or scope is required")
            digest = canonical_sha256(normalize_scope(scope))
            resolved = self._active_mission_for_scope_digest(digest)
            if resolved is None:
                raise RuntimeError("ACTIVE_MISSION_NOT_FOUND_FOR_SCOPE")
        _composed, _graph, _goal, current_plan = self._active_plan_context(resolved)
        if current_plan is None:
            return self.open_planning_session(resolved)
        return self.advance(resolved)

    def _active_plan_context(self, mission_id: str) -> tuple[Any, WorkGraphState, Any, Any | None]:
        composed = self.runtime.replay_composed(mission_id)
        mission = composed.core_state.mission
        if mission is None:
            raise RuntimeError(f"MISSION_NOT_FOUND: {mission_id}")
        if mission.status != MissionStatus.ACTIVE:
            raise RuntimeError(f"MISSION_NOT_ACTIVE: {mission.status.value}")
        if not mission.active_goal_id:
            raise RuntimeError("ACTIVE_GOAL_REQUIRED")
        goal = composed.core_state.goal(mission.active_goal_id)
        if goal is None:
            raise RuntimeError("GOAL_NOT_FOUND")
        work_graph = composed.extension_state("r1_2_work_graph")
        if not isinstance(work_graph, WorkGraphState):
            raise RuntimeError("R1_2_WORK_GRAPH_NOT_AVAILABLE")
        current_plan = None
        for plan in work_graph.plans:
            if plan.current_revision_id is not None and plan.lifecycle_state.value == "OPEN":
                current_plan = plan
        return composed, work_graph, goal, current_plan

    def propose_plan(self, mission_id: str, proposal: Mapping[str, Any]) -> dict[str, Any]:
        """Persist an AI-authored Plan candidate through frozen R2.3 guards.

        The runtime does not invent task semantics. The OpenCode planner agent
        must author ``objective``, ``tasks`` and ``dependencies`` from evidence.
        R2.3 then canonicalizes, validates and freezes that proposal.
        """
        mission_id = _text(mission_id, "mission_id")
        proposal = _mapping(proposal, "proposal")
        tasks = proposal.get("tasks", proposal.get("task_definitions"))
        if not isinstance(tasks, list) or not tasks:
            raise ValueError("proposal.tasks must be a non-empty array")
        composed, work_graph, goal, current_plan = self._active_plan_context(mission_id)
        current_revision = work_graph.revision(current_plan.current_revision_id) if current_plan and current_plan.current_revision_id else None
        stable_proposal = {
            "objective": proposal.get("objective"),
            "constraints": proposal.get("constraints", []),
            "tasks": tasks,
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
            task_definitions=tasks,
            dependencies=proposal.get("dependencies", []),
            actor=proposal.get("actor") or {"type": "AGENT", "id": "aitest-planner"},
            current_content_hash=current_revision.content_hash if current_revision is not None else None,
            current_revision_id=current_revision.revision_id if current_revision is not None else None,
            existing_plan_id=current_plan.plan_id if current_plan is not None else None,
            operation="REPLAN" if current_plan is not None else "PLAN",
        )
        result = self.planner.plan_or_revise(item)
        accepted = result.outcome in {"APPLIED", "DUPLICATE", "NO_CHANGE"}
        next_state = self.advance(mission_id) if accepted else None
        return {
            "schema_version": G2_SCHEMA,
            "status": "PASS" if accepted else result.outcome,
            "truth_source": "R1_EVENT_STREAM",
            "operation": "PLAN_PROPOSAL",
            "ai_authored_proposal_digest": proposal_digest,
            "runtime_governed_result": result.to_dict(),
            "autonomous_handoff": "SCHEDULER" if accepted else None,
            "next": next_state,
            "head_seq": self.runtime.get_head_seq(mission_id),
        }

    def _opencode_resolution(self, *, observed_at: str) -> dict[str, Any]:
        health = dict(self.session_provider.health())
        source_digest = canonical_sha256({"health": health, "directory": str(self.workspace_root)})
        snapshot_id = f"g2-opencode:{source_digest[:20]}"
        return {
            "resolution_id": f"g2-opencode-resolution:{source_digest[:20]}",
            "snapshot_id": snapshot_id,
            "status": "RESOLVED",
            "source_refs": [f"opencode-web:{self.workspace_root}"],
            "fact_set_digest": source_digest,
            "valid_until": _deadline(1),
            "capabilities": [
                {
                    "capability_id": OPENCODE_AGENT_CAPABILITY,
                    "version": OPENCODE_AGENT_CAPABILITY_VERSION,
                    "status": "AVAILABLE",
                    "source_refs": [f"opencode-health:{source_digest[:20]}"],
                }
            ],
            "observed_at": observed_at,
        }

    def _dispatch_binding(
        self,
        *,
        mission_id: str,
        plan_id: str,
        revision_id: str,
        task_id: str,
        resolution: Mapping[str, Any],
    ) -> DispatchBinding:
        payload = {
            "mission_id": mission_id,
            "plan_id": plan_id,
            "plan_revision_id": revision_id,
            "task_id": task_id,
            "capability_id": OPENCODE_AGENT_CAPABILITY,
            "capability_version": OPENCODE_AGENT_CAPABILITY_VERSION,
            "resolution_id": resolution["resolution_id"],
            "snapshot_id": resolution["snapshot_id"],
        }
        return DispatchBinding(
            **payload,
            binding_digest=canonical_sha256(payload),
            policy_refs=("G2_SERIAL_AGENT_SESSION",),
            authorization_refs=("R2.4_READINESS",),
            valid_until=resolution.get("valid_until"),
        )

    @staticmethod
    def _agent_name(value: str) -> str:
        agent = _text(value, "agent").lower()
        if agent not in KNOWN_AGENT_NAMES:
            raise ValueError(f"unsupported OpenCode agent: {agent}")
        return agent

    @staticmethod
    def _logical_agent_id(agent: str, task_id: str) -> str:
        # R2.5 binds one LogicalAgent identity to one root Attempt.  The
        # OpenCode role name is therefore not itself a LogicalAgent identity;
        # each durable Task receives its own logical worker identity and that
        # identity survives Session rotation for the same root Attempt.
        return f"{agent}:{canonical_sha256({'task_id': task_id})[:20]}"

    def _open_core_session(
        self,
        *,
        mission_id: str,
        external: ExternalSession,
        task_id: str | None,
        agent: str,
        phase: str = "TASK_EXECUTION",
        logical_agent_id: str | None = None,
    ) -> Any:
        command_id = f"g2:session:{external.session_id}:OPEN"
        result = self.runtime.execute(
            CommandEnvelope(
                command_id=command_id,
                type="OPEN_SESSION",
                mission_id=mission_id,
                session_id=external.session_id,
                expected_seq=self.runtime.get_head_seq(mission_id),
                actor=ActorRef("SYSTEM", "g2-opencode-session-provider"),
                payload={
                    "provider": "OPENCODE",
                    "provider_session_id": external.session_id,
                    "directory": external.directory,
                    "task_id": task_id,
                    "phase": phase,
                    "logical_agent_id": logical_agent_id or self._logical_agent_id(agent, task_id or f"session:{external.session_id}"),
                    "opencode_agent": agent,
                    "conversation_is_truth": False,
                },
                idempotency_key=command_id,
                correlation_id=command_id,
                schema_version=1,
            )
        )
        if not result.ok:
            if result.error is not None:
                raise result.error
            raise RuntimeError("G2_OPEN_SESSION_REJECTED")
        return result

    def _start_attempt(
        self,
        *,
        mission_id: str,
        plan_id: str,
        revision_id: str,
        task_id: str,
        session_id: str,
    ) -> Any:
        attempt_id = f"g2:attempt:{task_id}:1"
        request = StartExecutionRequest(
            command_id=f"g2:{attempt_id}:START",
            idempotency_key=f"g2:{attempt_id}:START",
            mission_id=mission_id,
            runtime_session_id=session_id,
            expected_seq=self.runtime.get_head_seq(mission_id),
            actor=ActorRef("SYSTEM", "g2-autonomous-scheduler"),
            correlation_id=attempt_id,
            execution_attempt_id=attempt_id,
            plan_id=plan_id,
            plan_revision_id=revision_id,
            task_id=task_id,
            knowledge_set=KnowledgeSetInput(),
            policy_id=DEFAULT_POLICY_ID,
            policy_version=DEFAULT_POLICY_VERSION,
            knowledge_scope={"mission_id": mission_id, "task_id": task_id},
        )
        return self.execution.start(request)

    def _context_message(self, *, mission_id: str, plan_id: str, revision_id: str, task_id: str, attempt: Any, agent: str) -> str:
        composed = self.runtime.replay_composed(mission_id)
        work_graph = composed.extension_state("r1_2_work_graph")
        task = work_graph.task(task_id) if isinstance(work_graph, WorkGraphState) else None
        mission = composed.core_state.mission
        goal = composed.core_state.goal(mission.active_goal_id) if mission and mission.active_goal_id else None
        envelope = {
            "schema": "aitest.session-context.v1",
            "authority": "R1_EVENT_STREAM",
            "conversation_is_not_truth": True,
            "mission_id": mission_id,
            "plan_id": plan_id,
            "plan_revision_id": revision_id,
            "task_id": task_id,
            "task": task.to_dict() if task is not None else None,
            "goal": goal.to_dict() if goal is not None else None,
            "attempt": attempt.to_dict() if hasattr(attempt, "to_dict") else _to_dict(attempt),
            "attempt_id": getattr(attempt, "attempt_id", None),
            "session_id": getattr(attempt, "runtime_session_id", None),
            "root_attempt_id": getattr(attempt, "root_attempt_id", None),
            "logical_agent": agent,
            "instruction": (
                "Resume only this durable Task. Read canonical tools before acting. "
                "Use observe_session for runtime rotation policy before long continuation. "
                "Report terminal outcome with the exact mission_id/task_id/attempt_id/session_id from this envelope. "
                "Do not reconstruct Mission state from conversation history and do not silently replan."
            ),
        }
        return "AITEST_CANONICAL_CONTEXT\n" + json.dumps(envelope, ensure_ascii=False, sort_keys=True)

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
        """Provision/reconcile Session+Attempt+LogicalAgent for an ACTIVE Task.

        R2.4 activation is durable before the external OpenCode side effect. If
        the process dies or OpenCode is unavailable after activation, a later
        call can deterministically repair the ACTIVE Task instead of silently
        losing it or creating a new Plan.
        """
        agent = self._agent_name(agent)
        composed = self.runtime.replay_composed(mission_id)
        execution_state = composed.extension_state("r1_3b_execution_resume")
        r25_state = composed.extension_state("r2_5_session_orchestration")
        latest = execution_state.latest_attempt(task_id) if execution_state is not None else None

        if latest is not None:
            session = composed.core_state.session(latest.runtime_session_id)
            actual_agent = agent
            if session is not None:
                actual_agent = str((session.attributes or {}).get("opencode_agent") or agent)
            logical_agent_id = self._logical_agent_id(actual_agent, task_id)
            binding = None
            if r25_state is not None:
                binding = next((item for item in r25_state.bindings if item.root_attempt_id == latest.root_attempt_id), None)
            if binding is None:
                binding_result = self.sessions.bind_logical_agent(
                    mission_id=mission_id,
                    binding_id=f"g2:binding:{latest.root_attempt_id}",
                    logical_agent_id=logical_agent_id,
                    root_attempt_id=latest.root_attempt_id,
                    attempt_id=latest.attempt_id,
                    task_id=task_id,
                    session_id=latest.runtime_session_id,
                    actor={"type": "SYSTEM", "id": "g2-r2.5-dispatch-repair"},
                    expected_seq=self.runtime.get_head_seq(mission_id),
                )
                binding = binding_result.record
                composed = self.runtime.replay_composed(mission_id)
                session = composed.core_state.session(latest.runtime_session_id)
            if session is None or session.status.value != "OPEN":
                rotated = self.rotate_session(mission_id, task_id=task_id, agent=actual_agent)
                return {**rotated, "status": "DISPATCH_REPAIRED_BY_ROTATION"}
            message = self._context_message(
                mission_id=mission_id, plan_id=plan_id, revision_id=revision_id,
                task_id=task_id, attempt=latest, agent=actual_agent,
            )
            try:
                response = self.session_provider.send_context(
                    session_id=latest.runtime_session_id, agent=actual_agent, text=message
                )
            except Exception:
                rotated = self.rotate_session(mission_id, task_id=task_id, agent=actual_agent)
                return {**rotated, "status": "DISPATCH_REPAIRED_BY_ROTATION"}
            return {
                "schema_version": G2_SCHEMA,
                "status": "ACTIVE_DISPATCH_RECOVERED",
                "truth_source": "R1_EVENT_STREAM",
                "conversation_is_not_truth": True,
                "task_id": task_id,
                "agent": actual_agent,
                "logical_agent_id": logical_agent_id,
                "session_id": latest.runtime_session_id,
                "attempt": latest.to_dict(),
                "logical_agent_binding": _to_dict(binding),
                "provider_response_observed": bool(response),
                "head_seq": self.runtime.get_head_seq(mission_id),
            }

        open_session = None
        for item in reversed(composed.core_state.sessions):
            attrs = dict(item.attributes or {})
            if item.status.value == "OPEN" and attrs.get("task_id") == task_id:
                open_session = item
                break
        if open_session is None:
            external = self.session_provider.create_session(
                title=f"AITest {agent} · {mission_id} · {task_id}",
                parent_id=parent_session_id,
            )
            try:
                self._open_core_session(
                    mission_id=mission_id, external=external, task_id=task_id, agent=agent, phase="TASK_EXECUTION"
                )
            except Exception:
                try:
                    self.session_provider.delete_session(external.session_id)
                finally:
                    raise
        else:
            external = ExternalSession(
                open_session.session_id,
                f"AITest {agent} · {mission_id} · {task_id}",
                str((open_session.attributes or {}).get("directory") or self.workspace_root),
                {},
            )

        logical = self._start_attempt(
            mission_id=mission_id, plan_id=plan_id, revision_id=revision_id,
            task_id=task_id, session_id=external.session_id,
        )
        logical_agent_id = self._logical_agent_id(agent, task_id)
        binding_id = f"g2:binding:{logical.attempt.root_attempt_id}"
        logical_binding = self.sessions.bind_logical_agent(
            mission_id=mission_id,
            binding_id=binding_id,
            logical_agent_id=logical_agent_id,
            root_attempt_id=logical.attempt.root_attempt_id,
            attempt_id=logical.attempt.attempt_id,
            task_id=task_id,
            session_id=external.session_id,
            actor={"type": "SYSTEM", "id": "g2-r2.5-session-orchestrator"},
            expected_seq=self.runtime.get_head_seq(mission_id),
        )
        message = self._context_message(
            mission_id=mission_id, plan_id=plan_id, revision_id=revision_id,
            task_id=task_id, attempt=logical.attempt, agent=agent,
        )
        response = self.session_provider.send_context(session_id=external.session_id, agent=agent, text=message)
        return {
            "schema_version": G2_SCHEMA,
            "status": "DISPATCHED",
            "truth_source": "R1_EVENT_STREAM",
            "conversation_is_not_truth": True,
            "task_id": task_id,
            "agent": agent,
            "logical_agent_id": logical_agent_id,
            "external_session": external.to_dict(),
            "attempt": logical.attempt.to_dict(),
            "logical_agent_binding": _to_dict(logical_binding.record),
            "context_cursor": logical.context.cursor.to_dict(),
            "context_semantic_digest": logical.context.semantic_digest,
            "provider_response_observed": bool(response),
            "head_seq": self.runtime.get_head_seq(mission_id),
        }

    def advance(self, mission_id: str, *, agent: str = DEFAULT_WORKER_AGENT, parent_session_id: str | None = None) -> dict[str, Any]:
        """Advance one bounded orchestration step without conversation-driven handoff."""
        result = self.dispatch_next(mission_id, agent=agent, parent_session_id=parent_session_id)
        return {**result, "orchestration_advanced": True}

    def dispatch_next(self, mission_id: str, *, agent: str, parent_session_id: str | None = None) -> dict[str, Any]:
        """Run one bounded R2.4 scheduling decision and create a real Session."""
        mission_id = _text(mission_id, "mission_id")
        agent = self._agent_name(agent)
        composed, work_graph, _goal, current_plan = self._active_plan_context(mission_id)
        if current_plan is None or current_plan.current_revision_id is None:
            raise RuntimeError("PLAN_REQUIRED_BEFORE_DISPATCH")
        revision_id = current_plan.current_revision_id
        active_tasks = [
            task for task in work_graph.tasks
            if task.plan_id == current_plan.plan_id
            and task.plan_revision_id == revision_id
            and task.lifecycle_state == TaskLifecycleState.ACTIVE
        ]
        if active_tasks:
            # G2R-1 narrow amendment: an ACTIVE Task normally retains crash-safe
            # recovery priority.  The only exception is an exact execution-lineage
            # ACTIVE branch suspended behind a canonical unresolved R2.6 HumanGate.
            # Such WAITING_HUMAN_ACTIVE branches do not consume the single runnable
            # g2-serial slot, so existing R2.4 READY selection may consider another
            # dependency-independent Task.  This is NOT general parallel scheduling.
            execution = composed.extension_state("r1_3b_execution_resume")
            human_gates = composed.extension_state("r2_6_human_gate")
            running_active = []
            resume_ready_active = []
            for task in active_tasks:
                latest = execution.latest_attempt(task.task_id) if execution is not None and hasattr(execution, "latest_attempt") else None
                exact_history = []
                if latest is not None and human_gates is not None:
                    for candidate in getattr(human_gates, "gates", ()):
                        if candidate.mission_id != mission_id or candidate.task_id != task.task_id or candidate.root_attempt_id != latest.root_attempt_id:
                            continue
                        origin = execution.attempt(candidate.origin_attempt_id) if hasattr(execution, "attempt") else None
                        if origin is not None and origin.task_id == task.task_id and origin.root_attempt_id == latest.root_attempt_id:
                            exact_history.append(candidate)
                exact_waiting = any(g.status == "PENDING" for g in exact_history)
                if exact_waiting:
                    continue
                if exact_history:
                    # A previously suspended branch whose exact canonical gate has
                    # completed is RESUME_READY. It must not preempt another ACTIVE
                    # branch that already owns the single runnable slot.
                    resume_ready_active.append(task)
                else:
                    running_active.append(task)
            prioritized_active = running_active or resume_ready_active
            if prioritized_active:
                return self._provision_active_task_session(
                    mission_id=mission_id, plan_id=current_plan.plan_id, revision_id=revision_id,
                    task_id=prioritized_active[0].task_id, agent=agent, parent_session_id=parent_session_id,
                )
        observed_at = _utc_now()
        resolution = self._opencode_resolution(observed_at=observed_at)
        candidate_tasks = [
            task
            for task in work_graph.tasks
            if task.plan_id == current_plan.plan_id and task.plan_revision_id == revision_id
        ]
        bindings = tuple(
            self._dispatch_binding(
                mission_id=mission_id,
                plan_id=current_plan.plan_id,
                revision_id=revision_id,
                task_id=task.task_id,
                resolution=resolution,
            )
            for task in candidate_tasks
        )
        report = evaluate_readiness(
            work_graph,
            mission_id=mission_id,
            plan_id=current_plan.plan_id,
            plan_revision_id=revision_id,
            observed_seq=self.runtime.get_head_seq(mission_id),
            resolution=resolution,
            dispatch_bindings=bindings,
            observed_at=observed_at,
        )
        if report.plan_complete:
            return {
                "schema_version": G2_SCHEMA,
                "status": "PLAN_COMPLETE",
                "truth_source": "R1_EVENT_STREAM",
                "readiness": report.to_dict(),
            }
        selected = select_ready_tasks(
            report,
            SchedulingPolicy("g2-serial", 1, 1),
            LoopBudget("g2-budget", 1000, 1000, _deadline(24), 1000),
            LoopProgress("g2-loop", "g2-budget", 0, 0, 0, observed_at, "g2-event-stream", canonical_sha256({"head": self.runtime.get_head_seq(mission_id)})),
        )
        if not selected:
            return {
                "schema_version": G2_SCHEMA,
                "status": report.next_state,
                "truth_source": "R1_EVENT_STREAM",
                "readiness": report.to_dict(),
                "legacy_fallback": "FORBIDDEN",
            }
        selected_task = selected[0]
        binding = selected_task.binding
        if binding is None:
            raise RuntimeError("R2_4_SELECTED_TASK_HAS_NO_BINDING")
        dispatch_request = make_dispatch_request(
            mission_id=mission_id,
            plan_id=current_plan.plan_id,
            plan_revision_id=revision_id,
            task_id=selected_task.task_id,
            binding=binding,
        )
        activation = self.runtime.execute(
            activation_command(
                dispatch_request,
                expected_seq=self.runtime.get_head_seq(mission_id),
                actor={"type": "SYSTEM", "id": "g2-r2.4-scheduler"},
            )
        )
        if not activation.ok:
            if activation.error is not None:
                raise activation.error
            raise RuntimeError("R2_4_TASK_ACTIVATION_REJECTED")

        dispatched = self._provision_active_task_session(
            mission_id=mission_id,
            plan_id=current_plan.plan_id,
            revision_id=revision_id,
            task_id=selected_task.task_id,
            agent=agent,
            parent_session_id=parent_session_id,
        )
        dispatched["readiness"] = report.to_dict()
        return dispatched

    def rotate_session(self, mission_id: str, *, task_id: str, agent: str) -> dict[str, Any]:
        """Create a successor OpenCode Session and resume the same root Attempt."""
        mission_id = _text(mission_id, "mission_id")
        task_id = _text(task_id, "task_id")
        agent = self._agent_name(agent)
        composed, work_graph, _goal, current_plan = self._active_plan_context(mission_id)
        execution_state = composed.extension_state("r1_3b_execution_resume")
        latest = execution_state.latest_attempt(task_id) if execution_state is not None else None
        if latest is None:
            raise RuntimeError(f"EXECUTION_ATTEMPT_NOT_FOUND_FOR_TASK: {task_id}")
        predecessor = composed.core_state.session(latest.runtime_session_id)
        if predecessor is None:
            raise RuntimeError("PREDECESSOR_SESSION_NOT_FOUND")
        external = self.session_provider.create_session(
            title=f"AITest {agent} resume · {mission_id} · {task_id}",
            parent_id=latest.runtime_session_id,
        )
        operation_id = f"g2:rotate:{latest.root_attempt_id}:{latest.ordinal + 1}"
        rotation = self.sessions.rotate_session(
            mission_id=mission_id,
            rotation_operation_id=operation_id,
            predecessor_session_id=latest.runtime_session_id,
            successor_session_id=external.session_id,
            resume_from_attempt_id=latest.attempt_id,
            execution_attempt_id=f"{latest.root_attempt_id}:resume:{latest.ordinal + 1}",
            plan_id=latest.plan_id,
            plan_revision_id=latest.plan_revision_id,
            task_id=latest.task_id,
            knowledge_set=KnowledgeSetInput(),
            knowledge_scope={"mission_id": mission_id, "task_id": task_id},
            policy_id=latest.policy_id,
            policy_version=latest.policy_version,
            # R2.5 LogicalAgent binding is immutable to the root Attempt.
            # Rotation therefore does not create a second binding; the same
            # LogicalAgent is recovered through the unchanged root_attempt_id.
            actor={"type": "SYSTEM", "id": "g2-r2.5-session-rotation"},
            expected_seq=self.runtime.get_head_seq(mission_id),
        )
        message = self._context_message(
            mission_id=mission_id,
            plan_id=latest.plan_id,
            revision_id=latest.plan_revision_id,
            task_id=task_id,
            attempt=rotation.attempt,
            agent=agent,
        )
        self.session_provider.send_context(session_id=external.session_id, agent=agent, text=message)
        return {
            "schema_version": G2_SCHEMA,
            "status": "ROTATED",
            "truth_source": "R1_EVENT_STREAM",
            "conversation_is_not_truth": True,
            "rotation_operation_id": operation_id,
            "predecessor_session_id": latest.runtime_session_id,
            "successor_session_id": external.session_id,
            "root_attempt_id": rotation.attempt.root_attempt_id,
            "logical_agent_id": self._logical_agent_id(agent, task_id),
            "predecessor_attempt_id": latest.attempt_id,
            "successor_attempt_id": rotation.attempt.attempt_id,
            "context_envelope": rotation.context_envelope.to_dict() if rotation.context_envelope is not None else None,
            "head_seq": self.runtime.get_head_seq(mission_id),
        }

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
        mission_id = _text(mission_id, "mission_id")
        task_id = _text(task_id, "task_id")
        attempt_id = _text(attempt_id, "attempt_id")
        session_id = _text(session_id, "session_id")
        composed = self.runtime.replay_composed(mission_id)
        execution_state = composed.extension_state("r1_3b_execution_resume")
        latest = execution_state.latest_attempt(task_id) if execution_state is not None else None
        if latest is None:
            raise RuntimeError("ACTIVE_EXECUTION_ATTEMPT_REQUIRED")
        if latest.attempt_id != attempt_id:
            raise RuntimeError(f"TASK_OUTCOME_ATTEMPT_MISMATCH: expected={latest.attempt_id} actual={attempt_id}")
        if latest.runtime_session_id != session_id:
            raise RuntimeError(f"TASK_OUTCOME_SESSION_MISMATCH: expected={latest.runtime_session_id} actual={session_id}")
        session = composed.core_state.session(session_id)
        if session is None or session.status.value not in {"OPEN", "SUSPENDED"}:
            raise RuntimeError("TASK_OUTCOME_SESSION_NOT_ACTIVE")
        completed = self.complete_task(
            mission_id, task_id=task_id, outcome=outcome, summary=summary, external_references=external_references
        )
        next_state = self.advance(mission_id)
        return {
            "schema_version": G2_SCHEMA,
            "status": completed["status"],
            "truth_source": "R1_EVENT_STREAM",
            "reported_attempt_id": attempt_id,
            "reported_session_id": session_id,
            "task_result": completed,
            "next": next_state,
        }

    def observe_session(
        self,
        mission_id: str,
        *,
        task_id: str,
        agent: str,
        observation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        mission_id = _text(mission_id, "mission_id")
        task_id = _text(task_id, "task_id")
        agent = self._agent_name(agent)
        composed = self.runtime.replay_composed(mission_id)
        execution_state = composed.extension_state("r1_3b_execution_resume")
        latest = execution_state.latest_attempt(task_id) if execution_state is not None else None
        if latest is None:
            raise RuntimeError("EXECUTION_ATTEMPT_NOT_FOUND_FOR_SESSION_OBSERVATION")
        values = dict(observation) if observation is not None else dict(self.session_provider.observe_session(latest.runtime_session_id))
        message_count = int(values.get("message_count") or 0)
        compaction_count = int(values.get("compaction_count") or 0)
        context_utilization = float(values.get("context_utilization") or 0.0)
        unhealthy = bool(values.get("unhealthy"))
        reasons: list[str] = []
        if unhealthy:
            reasons.append("SESSION_UNHEALTHY")
        if compaction_count >= ROTATE_COMPACTION_THRESHOLD:
            reasons.append("CONTEXT_COMPACTED")
        if message_count >= ROTATE_MESSAGE_THRESHOLD:
            reasons.append("MESSAGE_THRESHOLD")
        if context_utilization >= ROTATE_CONTEXT_UTILIZATION_THRESHOLD:
            reasons.append("CONTEXT_PRESSURE")
        if not reasons:
            return {
                "schema_version": G2_SCHEMA,
                "status": "KEEP",
                "truth_source": "R1_EVENT_STREAM",
                "session_id": latest.runtime_session_id,
                "attempt_id": latest.attempt_id,
                "root_attempt_id": latest.root_attempt_id,
                "observation": values,
                "rotation_reasons": [],
            }
        rotated = self.rotate_session(mission_id, task_id=task_id, agent=agent)
        return {
            "schema_version": G2_SCHEMA,
            "status": "ROTATED",
            "truth_source": "R1_EVENT_STREAM",
            "observation": values,
            "rotation_reasons": reasons,
            "rotation": rotated,
        }

    def complete_task(
        self,
        mission_id: str,
        *,
        task_id: str,
        outcome: str = "SUCCEEDED",
        summary: str,
        external_references: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        mission_id = _text(mission_id, "mission_id")
        task_id = _text(task_id, "task_id")
        target = _text(outcome, "outcome").upper()
        if target not in {"SUCCEEDED", "FAILED"}:
            raise ValueError("outcome must be SUCCEEDED or FAILED")
        composed = self.runtime.replay_composed(mission_id)
        work_graph = composed.extension_state("r1_2_work_graph")
        if not isinstance(work_graph, WorkGraphState):
            raise RuntimeError("R1_2_WORK_GRAPH_NOT_AVAILABLE")
        task = work_graph.task(task_id)
        if task is None:
            raise RuntimeError(f"TASK_NOT_FOUND: {task_id}")
        if task.lifecycle_state != TaskLifecycleState.ACTIVE:
            raise RuntimeError(f"TASK_NOT_ACTIVE: {task.lifecycle_state.value}")
        command_id = f"g2:task:{task_id}:{target}"
        result = self.runtime.execute(
            {
                "command_id": command_id,
                "type": "TRANSITION_TASK",
                "mission_id": mission_id,
                "expected_seq": self.runtime.get_head_seq(mission_id),
                "actor": {"type": "AGENT", "id": "g2-task-completion"},
                "payload": {
                    "plan_id": task.plan_id,
                    "plan_revision_id": task.plan_revision_id,
                    "task_id": task_id,
                    "target_state": target,
                    "reason_code": "AGENT_TASK_COMPLETED" if target == "SUCCEEDED" else "AGENT_TASK_FAILED",
                    "reason_summary": _text(summary, "summary"),
                    "outcome": {
                        "summary": _text(summary, "summary"),
                        "external_references": [dict(item) for item in (external_references or [])],
                    },
                },
                "correlation_id": command_id,
                "schema_version": 1,
            }
        )
        if not result.ok:
            if result.error is not None:
                raise result.error
            raise RuntimeError("TASK_COMPLETION_REJECTED")
        session_close = None
        after = self.runtime.replay_composed(mission_id)
        execution_state = after.extension_state("r1_3b_execution_resume")
        latest = execution_state.latest_attempt(task_id) if execution_state is not None else None
        if latest is not None:
            session = after.core_state.session(latest.runtime_session_id)
            if session is not None and session.status.value in {"OPEN", "SUSPENDED"}:
                close_id = f"g2:session:{session.session_id}:TASK_TERMINAL:CLOSE"
                close_result = self.runtime.execute(
                    {
                        "command_id": close_id,
                        "type": "CLOSE_SESSION",
                        "mission_id": mission_id,
                        "session_id": session.session_id,
                        "expected_seq": self.runtime.get_head_seq(mission_id),
                        "actor": {"type": "SYSTEM", "id": "g2-task-session-lifecycle"},
                        "payload": {"reason": "TASK_TERMINAL", "task_id": task_id, "task_outcome": target},
                        "idempotency_key": close_id,
                        "correlation_id": command_id,
                        "schema_version": 1,
                    }
                )
                if not close_result.ok:
                    if close_result.error is not None:
                        raise close_result.error
                    raise RuntimeError("TASK_SESSION_CLOSE_REJECTED")
                session_close = close_result.to_dict()
        return {
            "schema_version": G2_SCHEMA,
            "status": target,
            "truth_source": "R1_EVENT_STREAM",
            "task": self.runtime.replay_composed(mission_id).extension_state("r1_2_work_graph").task(task_id).to_dict(),
            "session_close": session_close,
            "head_seq": self.runtime.get_head_seq(mission_id),
        }

    def open_human_gate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        result = self.human_gates.open_gate(dict(request))
        return {
            "schema_version": G2_SCHEMA,
            "status": "WAITING_FOR_HUMAN",
            "truth_source": "R1_EVENT_STREAM",
            "gate": _to_dict(result.gate),
            "command": result.command_result.to_dict(),
        }

    def decide_human_gate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        result = self.human_gates.record_decision(dict(request))
        return {
            "schema_version": G2_SCHEMA,
            "status": "DECIDED",
            "truth_source": "R1_EVENT_STREAM",
            "gate": _to_dict(result.gate),
            "command": result.command_result.to_dict(),
        }


def default_service(runtime: RuntimeService, workspace_root: str | Path) -> AutonomousOrchestrationService:
    """Production composition: G2.1 Router/Supervisor over the real OpenCode provider."""
    from .g2_1.managed_orchestration import default_g21_service
    return default_g21_service(runtime, workspace_root)


__all__ = [
    "AutonomousOrchestrationService",
    "DirectoryScopedOpenCodeSessionProvider",
    "OpenCodeSessionAdmissionPending",
    "ExternalSession",
    "FakeOpenCodeSessionProvider",
    "G2_SCHEMA",
    "KNOWN_AGENT_NAMES",
    "OPENCODE_AGENT_CAPABILITY",
    "OpenCodeSessionProvider",
    "default_service",
]
