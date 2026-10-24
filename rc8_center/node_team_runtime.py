"""Lease-bound dsh-node -> node-local dsh-agent-teams runtime contract.

This module closes the control-plane/runtime gap without pretending that a
specific in-bank dsh-agent-teams CLI/API has already been proven.  The concrete
team gateway is injected.  Everything around it is fail-closed and bound to the
Center lease/R1 truth:

* the Director role cannot execute domain tools or emit domain evidence;
* the active Center lease id is the attempt id, so a re-lease makes the old
  runtime stale even when the work returns to the same physical node;
* node/team/agent/tool/evidence provenance is written into the existing R1
  RuntimeEventEnvelope rather than a parallel event store;
* a team cannot emit evidence before the matching tool invocation exists.

The real bank adapter must implement ``DshAgentTeamsGateway`` against the
observed DSH integration surface and pass reality tests before the integration
may be called BANK_REALITY_VERIFIED.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Protocol, Sequence, Tuple

from rc8_runtime import RuntimeEventEnvelope, RuntimeProducerKind

from .control_plane import CenterControlPlane, CenterControlError, WorkItemRecord
from .distributed_orchestration import ActorRole, DirectorExecutionFence


class NodeTeamRuntimeError(ValueError):
    pass


class NodeTeamLifecycle(str, Enum):
    PLACED = "PLACED"
    LEASED = "LEASED"
    NODE_CLAIMED = "NODE_CLAIMED"
    TEAM_STARTED = "TEAM_STARTED"
    TEAM_MEMBER_DISPATCHED = "TEAM_MEMBER_DISPATCHED"
    TOOL_EXECUTION_STARTED = "TOOL_EXECUTION_STARTED"
    EVIDENCE_EMITTED = "EVIDENCE_EMITTED"
    TEAM_COMPLETED = "TEAM_COMPLETED"
    NODE_RESULT_SUBMITTED = "NODE_RESULT_SUBMITTED"
    CENTER_EVALUATED = "CENTER_EVALUATED"
    TEAM_FORMATION_FAILED = "TEAM_FORMATION_FAILED"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    TEAM_ABORTED = "TEAM_ABORTED"
    STALE_ATTEMPT = "STALE_ATTEMPT"


_FAILURE_STATES = {
    NodeTeamLifecycle.TEAM_FORMATION_FAILED,
    NodeTeamLifecycle.TOOL_UNAVAILABLE,
    NodeTeamLifecycle.TEAM_ABORTED,
    NodeTeamLifecycle.STALE_ATTEMPT,
}

_TERMINAL_STATES = _FAILURE_STATES | {NodeTeamLifecycle.CENTER_EVALUATED}


@dataclass(frozen=True)
class TeamProfile:
    profile_id: str
    member_roles: Tuple[str, ...]

    def __post_init__(self) -> None:
        profile_id = (self.profile_id or "").strip()
        if not profile_id:
            raise NodeTeamRuntimeError("TEAM_PROFILE_ID_REQUIRED")
        roles = tuple((value or "").strip() for value in self.member_roles)
        if not roles or any(not value for value in roles):
            raise NodeTeamRuntimeError("TEAM_PROFILE_MEMBER_ROLES_REQUIRED")
        if len(set(roles)) != len(roles):
            raise NodeTeamRuntimeError("TEAM_PROFILE_MEMBER_ROLE_DUPLICATE")
        object.__setattr__(self, "profile_id", profile_id)
        object.__setattr__(self, "member_roles", roles)


@dataclass(frozen=True)
class ExecutionProvenance:
    mission_id: str
    stage_id: str
    test_run_id: str
    work_item_id: str
    attempt_id: str
    node_id: str
    team_id: Optional[str] = None
    agent_id: Optional[str] = None
    tool_id: Optional[str] = None
    evidence_id: Optional[str] = None

    def __post_init__(self) -> None:
        for name in (
            "mission_id",
            "stage_id",
            "test_run_id",
            "work_item_id",
            "attempt_id",
            "node_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise NodeTeamRuntimeError("%s_REQUIRED" % name.upper())
        for name in ("team_id", "agent_id", "tool_id", "evidence_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise NodeTeamRuntimeError("%s_INVALID" % name.upper())

    def as_event_data(self) -> Dict[str, object]:
        data: Dict[str, object] = {
            "mission_id": self.mission_id,
            "stage_id": self.stage_id,
            "test_run_id": self.test_run_id,
            "work_item_id": self.work_item_id,
            "attempt_id": self.attempt_id,
            "node_id": self.node_id,
        }
        for name in ("team_id", "agent_id", "tool_id", "evidence_id"):
            value = getattr(self, name)
            if value is not None:
                data[name] = value
        return data


class DshAgentTeamsGateway(Protocol):
    """Observed-in-bank adapter boundary; this protocol itself is not reality proof."""

    def start_team(
        self,
        *,
        profile_id: str,
        member_roles: Sequence[str],
        context: Dict[str, object]
    ) -> str:
        ...

    def dispatch_member(self, *, team_id: str, role: str, context: Dict[str, object]) -> str:
        ...

    def start_tool(
        self,
        *,
        team_id: str,
        agent_id: str,
        tool_id: str,
        action: str,
        payload: Dict[str, object]
    ) -> str:
        ...

    def complete_team(self, *, team_id: str) -> None:
        ...

    def abort_team(self, *, team_id: str, reason: str) -> None:
        ...


class NodeTeamRuntime:
    """A single leased WorkItem attempt running on one dsh-node.

    Upstream Center owns placement and lease creation.  This runtime begins at
    LEASED and emits NODE_CLAIMED onward.  It deliberately does not manufacture
    PLACED/LEASED events because the component that performed those actions must
    be their producer.
    """

    def __init__(
        self,
        control_plane: CenterControlPlane,
        gateway: DshAgentTeamsGateway,
        *,
        mission_id: str,
        work_item_id: str,
        node_id: str,
        team_profile: TeamProfile
    ) -> None:
        self.control_plane = control_plane
        self.gateway = gateway
        self.mission_id = self._required(mission_id, "mission_id")
        self.work_item_id = self._required(work_item_id, "work_item_id")
        self.node_id = self._required(node_id, "node_id")
        if not isinstance(team_profile, TeamProfile):
            raise NodeTeamRuntimeError("TEAM_PROFILE_REQUIRED")
        self.team_profile = team_profile
        self.state = NodeTeamLifecycle.LEASED
        self.attempt_id: Optional[str] = None
        self.test_run_id: Optional[str] = None
        self.stage_id: Optional[str] = None
        self.team_id: Optional[str] = None
        self._agents: Dict[str, str] = {}
        self._tool_invocations: Dict[Tuple[str, str], str] = {}
        self._evidence_ids: List[str] = []

    @staticmethod
    def _required(value: str, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise NodeTeamRuntimeError("%s_REQUIRED" % name.upper())
        return value.strip()

    def claim(self) -> ExecutionProvenance:
        self._require_not_terminal()
        if self.attempt_id is not None:
            raise NodeTeamRuntimeError("WORK_ITEM_ALREADY_CLAIMED")
        current = self._current_work()
        if current.lease_owner_node_id != self.node_id:
            raise NodeTeamRuntimeError("WORK_ITEM_ASSIGNED_TO_DIFFERENT_NODE")
        if not current.lease_id:
            raise NodeTeamRuntimeError("ACTIVE_WORK_ITEM_LEASE_REQUIRED")

        running = self.control_plane.start_work_item(self.work_item_id, self.node_id)
        if not running.lease_id:
            raise NodeTeamRuntimeError("LEASE_ID_REQUIRED_FOR_ATTEMPT")
        self.attempt_id = running.lease_id
        self.test_run_id = running.identity.test_run_id
        self.stage_id = running.identity.stage
        self.state = NodeTeamLifecycle.NODE_CLAIMED
        provenance = self._provenance()
        self._emit(
            NodeTeamLifecycle.NODE_CLAIMED,
            ActorRole.DSH_NODE,
            RuntimeProducerKind.NODE_AGENT,
            self.node_id,
            provenance,
        )
        return provenance

    def start_team(self, *, actor_role: ActorRole = ActorRole.DSH_NODE) -> str:
        self._require_claimed()
        if actor_role != ActorRole.DSH_NODE:
            raise NodeTeamRuntimeError("NODE_LOCAL_TEAM_MUST_BE_STARTED_BY_DSH_NODE")
        if self.team_id is not None:
            raise NodeTeamRuntimeError("TEAM_ALREADY_STARTED")
        self._assert_active_attempt()
        context = self._provenance().as_event_data()
        try:
            team_id = self.gateway.start_team(
                profile_id=self.team_profile.profile_id,
                member_roles=self.team_profile.member_roles,
                context=context,
            )
        except Exception as exc:
            self.state = NodeTeamLifecycle.TEAM_FORMATION_FAILED
            self._emit(
                NodeTeamLifecycle.TEAM_FORMATION_FAILED,
                ActorRole.DSH_NODE,
                RuntimeProducerKind.NODE_AGENT,
                self.node_id,
                self._provenance(),
                extra={"reason": str(exc)},
            )
            raise NodeTeamRuntimeError("TEAM_FORMATION_FAILED") from exc
        self.team_id = self._required(team_id, "team_id")
        self.state = NodeTeamLifecycle.TEAM_STARTED
        self._emit(
            NodeTeamLifecycle.TEAM_STARTED,
            ActorRole.DSH_NODE,
            RuntimeProducerKind.NODE_AGENT,
            self.node_id,
            self._provenance(team_id=self.team_id),
            extra={"team_profile": self.team_profile.profile_id},
        )
        return self.team_id

    def dispatch_member(self, role: str, *, actor_role: ActorRole = ActorRole.DSH_NODE) -> str:
        self._require_team_active()
        if actor_role != ActorRole.DSH_NODE:
            raise NodeTeamRuntimeError("TEAM_MEMBER_DISPATCH_MUST_BE_BY_DSH_NODE")
        role = self._required(role, "team_member_role")
        if role not in self.team_profile.member_roles:
            raise NodeTeamRuntimeError("TEAM_MEMBER_ROLE_NOT_IN_PROFILE")
        if role in self._agents:
            return self._agents[role]
        self._assert_active_attempt()
        agent_id = self.gateway.dispatch_member(
            team_id=self.team_id or "",
            role=role,
            context=self._provenance(team_id=self.team_id).as_event_data(),
        )
        agent_id = self._required(agent_id, "agent_id")
        self._agents[role] = agent_id
        if self.state in {NodeTeamLifecycle.TEAM_STARTED, NodeTeamLifecycle.TEAM_MEMBER_DISPATCHED}:
            self.state = NodeTeamLifecycle.TEAM_MEMBER_DISPATCHED
        self._emit(
            NodeTeamLifecycle.TEAM_MEMBER_DISPATCHED,
            ActorRole.DSH_NODE,
            RuntimeProducerKind.NODE_AGENT,
            self.node_id,
            self._provenance(team_id=self.team_id, agent_id=agent_id),
            extra={"member_role": role},
        )
        return agent_id

    def start_tool(
        self,
        *,
        agent_id: str,
        tool_id: str,
        action: str,
        payload: Optional[Dict[str, object]] = None,
        actor_role: ActorRole = ActorRole.TEAM_WORKER,
        attempt_id: Optional[str] = None
    ) -> str:
        self._require_team_active()
        agent_id = self._required(agent_id, "agent_id")
        tool_id = self._required(tool_id, "tool_id")
        action = self._required(action, "domain_action").upper()
        self._require_known_agent(agent_id)
        self._assert_attempt_argument(attempt_id)
        if actor_role == ActorRole.DIRECTOR:
            DirectorExecutionFence.authorize(actor_role, action)
            raise CenterControlError("DIRECTOR_DOMAIN_EXECUTION_FORBIDDEN:%s" % action)
        if actor_role != ActorRole.TEAM_WORKER:
            raise NodeTeamRuntimeError("DOMAIN_TOOL_REQUIRES_TEAM_WORKER")
        DirectorExecutionFence.authorize(actor_role, action)
        self._assert_active_attempt()
        try:
            invocation_id = self.gateway.start_tool(
                team_id=self.team_id or "",
                agent_id=agent_id,
                tool_id=tool_id,
                action=action,
                payload=dict(payload or {}),
            )
        except Exception as exc:
            self.state = NodeTeamLifecycle.TOOL_UNAVAILABLE
            self._emit(
                NodeTeamLifecycle.TOOL_UNAVAILABLE,
                ActorRole.TEAM_WORKER,
                RuntimeProducerKind.WORKER,
                agent_id,
                self._provenance(team_id=self.team_id, agent_id=agent_id, tool_id=tool_id),
                extra={"domain_action": action, "reason": str(exc)},
            )
            raise NodeTeamRuntimeError("TOOL_UNAVAILABLE") from exc
        invocation_id = self._required(invocation_id, "tool_invocation_id")
        self._tool_invocations[(agent_id, tool_id)] = invocation_id
        self.state = NodeTeamLifecycle.TOOL_EXECUTION_STARTED
        self._emit(
            NodeTeamLifecycle.TOOL_EXECUTION_STARTED,
            ActorRole.TEAM_WORKER,
            RuntimeProducerKind.WORKER,
            agent_id,
            self._provenance(team_id=self.team_id, agent_id=agent_id, tool_id=tool_id),
            extra={"domain_action": action, "tool_invocation_id": invocation_id},
        )
        return invocation_id

    def emit_evidence(
        self,
        *,
        agent_id: str,
        tool_id: str,
        evidence_id: str,
        evidence_type: str,
        refs: Optional[Sequence[str]] = None,
        actor_role: ActorRole = ActorRole.TEAM_WORKER,
        attempt_id: Optional[str] = None
    ) -> ExecutionProvenance:
        self._require_team_active()
        agent_id = self._required(agent_id, "agent_id")
        tool_id = self._required(tool_id, "tool_id")
        evidence_id = self._required(evidence_id, "evidence_id")
        evidence_type = self._required(evidence_type, "evidence_type").upper()
        self._require_known_agent(agent_id)
        self._assert_attempt_argument(attempt_id)
        if actor_role == ActorRole.DIRECTOR:
            if not DirectorExecutionFence.evidence_counts_for_sufficiency(actor_role, evidence_type):
                raise CenterControlError("DIRECTOR_DOMAIN_EXECUTION_FORBIDDEN:%s" % evidence_type)
            raise CenterControlError("DIRECTOR_DOMAIN_EVIDENCE_FORBIDDEN:%s" % evidence_type)
        if actor_role != ActorRole.TEAM_WORKER:
            raise NodeTeamRuntimeError("DOMAIN_EVIDENCE_REQUIRES_TEAM_WORKER")
        if (agent_id, tool_id) not in self._tool_invocations:
            raise NodeTeamRuntimeError("EVIDENCE_REQUIRES_TOOL_EXECUTION")
        self._assert_active_attempt()
        if evidence_id not in self._evidence_ids:
            self._evidence_ids.append(evidence_id)
        self.state = NodeTeamLifecycle.EVIDENCE_EMITTED
        provenance = self._provenance(
            team_id=self.team_id,
            agent_id=agent_id,
            tool_id=tool_id,
            evidence_id=evidence_id,
        )
        event_refs = [self._required(value, "evidence_ref") for value in (refs or [])]
        self._emit(
            NodeTeamLifecycle.EVIDENCE_EMITTED,
            ActorRole.TEAM_WORKER,
            RuntimeProducerKind.TOOL,
            tool_id,
            provenance,
            refs=event_refs,
            extra={
                "evidence_type": evidence_type,
                "tool_invocation_id": self._tool_invocations[(agent_id, tool_id)],
            },
        )
        return provenance

    def complete_team(self, *, actor_role: ActorRole = ActorRole.DSH_NODE) -> None:
        self._require_team_active()
        if actor_role != ActorRole.DSH_NODE:
            raise NodeTeamRuntimeError("TEAM_COMPLETION_MUST_BE_BY_DSH_NODE")
        if not self._evidence_ids:
            raise NodeTeamRuntimeError("TEAM_COMPLETION_REQUIRES_EVIDENCE")
        self._assert_active_attempt()
        self.gateway.complete_team(team_id=self.team_id or "")
        self.state = NodeTeamLifecycle.TEAM_COMPLETED
        self._emit(
            NodeTeamLifecycle.TEAM_COMPLETED,
            ActorRole.DSH_NODE,
            RuntimeProducerKind.NODE_AGENT,
            self.node_id,
            self._provenance(team_id=self.team_id),
            refs=list(self._evidence_ids),
        )

    def submit_result(self, *, actor_role: ActorRole = ActorRole.DSH_NODE) -> ExecutionProvenance:
        if self.state != NodeTeamLifecycle.TEAM_COMPLETED:
            raise NodeTeamRuntimeError("NODE_RESULT_REQUIRES_COMPLETED_TEAM")
        if actor_role != ActorRole.DSH_NODE:
            raise NodeTeamRuntimeError("NODE_RESULT_MUST_BE_SUBMITTED_BY_DSH_NODE")
        self._assert_active_attempt()
        self.state = NodeTeamLifecycle.NODE_RESULT_SUBMITTED
        provenance = self._provenance(team_id=self.team_id)
        self._emit(
            NodeTeamLifecycle.NODE_RESULT_SUBMITTED,
            ActorRole.DSH_NODE,
            RuntimeProducerKind.NODE_AGENT,
            self.node_id,
            provenance,
            refs=list(self._evidence_ids),
        )
        return provenance

    def center_evaluate(self, *, accepted: bool, evaluator_ref: str) -> None:
        if self.state != NodeTeamLifecycle.NODE_RESULT_SUBMITTED:
            raise NodeTeamRuntimeError("CENTER_EVALUATION_REQUIRES_NODE_RESULT")
        evaluator_ref = self._required(evaluator_ref, "evaluator_ref")
        self._assert_active_attempt()
        self._emit(
            NodeTeamLifecycle.CENTER_EVALUATED,
            ActorRole.CENTER,
            RuntimeProducerKind.NODE_AGENT,
            evaluator_ref,
            self._provenance(team_id=self.team_id),
            refs=list(self._evidence_ids),
            extra={"accepted": bool(accepted)},
        )
        self.state = NodeTeamLifecycle.CENTER_EVALUATED
        if accepted:
            self.control_plane.complete_work_item(self.work_item_id, self.node_id)

    def abort(self, reason: str, *, actor_role: ActorRole = ActorRole.DSH_NODE) -> None:
        self._require_team_active()
        if actor_role != ActorRole.DSH_NODE:
            raise NodeTeamRuntimeError("TEAM_ABORT_MUST_BE_BY_DSH_NODE")
        reason = self._required(reason, "abort_reason")
        self._assert_active_attempt()
        if self.team_id is not None:
            self.gateway.abort_team(team_id=self.team_id, reason=reason)
        self.state = NodeTeamLifecycle.TEAM_ABORTED
        self._emit(
            NodeTeamLifecycle.TEAM_ABORTED,
            ActorRole.DSH_NODE,
            RuntimeProducerKind.NODE_AGENT,
            self.node_id,
            self._provenance(team_id=self.team_id),
            extra={"reason": reason},
        )

    def _current_work(self) -> WorkItemRecord:
        work = self.control_plane.repository.get_work_item(self.work_item_id)
        if work is None:
            raise NodeTeamRuntimeError("WORK_ITEM_NOT_FOUND")
        return work

    def _assert_active_attempt(self) -> WorkItemRecord:
        if self.attempt_id is None or self.test_run_id is None:
            raise NodeTeamRuntimeError("NODE_CLAIM_REQUIRED")
        work = self._current_work()
        if work.lease_owner_node_id != self.node_id:
            self.state = NodeTeamLifecycle.STALE_ATTEMPT
            raise NodeTeamRuntimeError("STALE_ATTEMPT:LEASE_OWNER_CHANGED")
        if work.lease_id != self.attempt_id:
            self.state = NodeTeamLifecycle.STALE_ATTEMPT
            raise NodeTeamRuntimeError("STALE_ATTEMPT:LEASE_ID_CHANGED")
        try:
            return self.control_plane.authorize_work_item_write(
                test_run_id=self.test_run_id,
                work_item_id=self.work_item_id,
                node_id=self.node_id,
            )
        except CenterControlError as exc:
            self.state = NodeTeamLifecycle.STALE_ATTEMPT
            raise NodeTeamRuntimeError("STALE_ATTEMPT:ACTIVE_LEASE_REQUIRED") from exc

    def _assert_attempt_argument(self, attempt_id: Optional[str]) -> None:
        if attempt_id is None:
            return
        value = self._required(attempt_id, "attempt_id")
        if self.attempt_id is None or value != self.attempt_id:
            raise NodeTeamRuntimeError("STALE_ATTEMPT:ATTEMPT_ID_MISMATCH")

    def _require_claimed(self) -> None:
        self._require_not_terminal()
        if self.attempt_id is None or self.state == NodeTeamLifecycle.LEASED:
            raise NodeTeamRuntimeError("NODE_CLAIM_REQUIRED")

    def _require_team_active(self) -> None:
        self._require_not_terminal()
        if self.team_id is None:
            raise NodeTeamRuntimeError("TEAM_START_REQUIRED")
        if self.state in {NodeTeamLifecycle.TEAM_COMPLETED, NodeTeamLifecycle.NODE_RESULT_SUBMITTED}:
            raise NodeTeamRuntimeError("TEAM_ALREADY_COMPLETED")

    def _require_not_terminal(self) -> None:
        if self.state in _TERMINAL_STATES:
            raise NodeTeamRuntimeError("NODE_TEAM_RUNTIME_TERMINAL:%s" % self.state.value)

    def _require_known_agent(self, agent_id: str) -> None:
        if agent_id not in self._agents.values():
            raise NodeTeamRuntimeError("AGENT_NOT_DISPATCHED_BY_LOCAL_TEAM")

    def _provenance(
        self,
        *,
        team_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        tool_id: Optional[str] = None,
        evidence_id: Optional[str] = None
    ) -> ExecutionProvenance:
        if self.attempt_id is None or self.test_run_id is None or self.stage_id is None:
            raise NodeTeamRuntimeError("NODE_CLAIM_REQUIRED")
        return ExecutionProvenance(
            mission_id=self.mission_id,
            stage_id=self.stage_id,
            test_run_id=self.test_run_id,
            work_item_id=self.work_item_id,
            attempt_id=self.attempt_id,
            node_id=self.node_id,
            team_id=team_id,
            agent_id=agent_id,
            tool_id=tool_id,
            evidence_id=evidence_id,
        )

    def _emit(
        self,
        event_type: NodeTeamLifecycle,
        actor_role: ActorRole,
        producer_kind: RuntimeProducerKind,
        producer_ref: str,
        provenance: ExecutionProvenance,
        *,
        refs: Optional[Sequence[str]] = None,
        extra: Optional[Dict[str, object]] = None
    ) -> Dict[str, object]:
        self._assert_active_attempt()
        data = provenance.as_event_data()
        data["actor_role"] = actor_role.value
        data.update(dict(extra or {}))
        sequence = self.control_plane.runtime_ledger.latest_node_sequence(
            test_run_id=provenance.test_run_id,
            node_id=provenance.node_id,
        ) + 1
        event = RuntimeEventEnvelope(
            event_id=str(uuid.uuid4()),
            test_run_id=provenance.test_run_id,
            work_item_id=provenance.work_item_id,
            node_id=provenance.node_id,
            producer_kind=producer_kind,
            producer_ref=producer_ref,
            event_type=event_type.value,
            sequence=sequence,
            attempt_id=provenance.attempt_id,
            refs=list(refs or []),
            data=data,
        )
        return self.control_plane.append_runtime_event(event)
