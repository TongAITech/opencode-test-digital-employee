"""dsh-node assignment bootstrap around the canonical NodeTeamRuntime.

Center leases a WorkItem to a node.  This adapter is the node-local entry point
that turns that lease into a node-local dsh-agent-teams attempt while preserving
Center authority.  It is identical for SINGLE_NODE and DISTRIBUTED placement:
physical placement changes, the WorkItem -> node -> team -> agent -> tool model
does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from .control_plane import CenterControlPlane
from .node_team_runtime import (
    DshAgentTeamsGateway,
    ExecutionProvenance,
    NodeTeamRuntime,
    NodeTeamRuntimeError,
    TeamProfile,
)


class DshNodeRuntimeAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class NodeWorkAssignment:
    mission_id: str
    work_item_id: str
    node_id: str
    team_profile: TeamProfile
    workspace_ref: str
    repo_ref: Optional[str] = None
    evidence_contract: Tuple[str, ...] = ()
    forbidden_actions: Tuple[str, ...] = ()
    trace_context: Optional[Dict[str, str]] = None

    def __post_init__(self) -> None:
        for name in ("mission_id", "work_item_id", "node_id", "workspace_ref"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise DshNodeRuntimeAdapterError("%s_REQUIRED" % name.upper())
            object.__setattr__(self, name, value.strip())
        if not isinstance(self.team_profile, TeamProfile):
            raise DshNodeRuntimeAdapterError("TEAM_PROFILE_REQUIRED")
        if self.repo_ref is not None:
            if not isinstance(self.repo_ref, str) or not self.repo_ref.strip():
                raise DshNodeRuntimeAdapterError("REPO_REF_INVALID")
            object.__setattr__(self, "repo_ref", self.repo_ref.strip())
        object.__setattr__(self, "evidence_contract", self._normalized_upper(self.evidence_contract, "EVIDENCE_CONTRACT"))
        object.__setattr__(self, "forbidden_actions", self._normalized_upper(self.forbidden_actions, "FORBIDDEN_ACTIONS"))
        if self.trace_context is None:
            object.__setattr__(self, "trace_context", {})
        elif not isinstance(self.trace_context, dict):
            raise DshNodeRuntimeAdapterError("TRACE_CONTEXT_INVALID")
        else:
            normalized = {}
            for key, value in self.trace_context.items():
                if not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip():
                    raise DshNodeRuntimeAdapterError("TRACE_CONTEXT_INVALID")
                normalized[key.strip()] = value.strip()
            object.__setattr__(self, "trace_context", normalized)

    @staticmethod
    def _normalized_upper(values: Sequence[str], name: str) -> Tuple[str, ...]:
        if not isinstance(values, (tuple, list)):
            raise DshNodeRuntimeAdapterError("%s_INVALID" % name)
        result = []
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise DshNodeRuntimeAdapterError("%s_INVALID" % name)
            normalized = value.strip().upper()
            if normalized not in result:
                result.append(normalized)
        return tuple(result)


class _AssignmentContextGateway:
    def __init__(self, delegate: DshAgentTeamsGateway, assignment: NodeWorkAssignment) -> None:
        self.delegate = delegate
        self.assignment = assignment

    def _context(self, context: Dict[str, object]) -> Dict[str, object]:
        merged = dict(context)
        merged.update(
            {
                "workspace_ref": self.assignment.workspace_ref,
                "repo_ref": self.assignment.repo_ref,
                "evidence_contract": list(self.assignment.evidence_contract),
                "forbidden_actions": list(self.assignment.forbidden_actions),
                "trace_context": dict(self.assignment.trace_context or {}),
            }
        )
        return merged

    def start_team(self, *, profile_id: str, member_roles: Sequence[str], context: Dict[str, object]) -> str:
        return self.delegate.start_team(
            profile_id=profile_id,
            member_roles=member_roles,
            context=self._context(context),
        )

    def dispatch_member(self, *, team_id: str, role: str, context: Dict[str, object]) -> str:
        return self.delegate.dispatch_member(
            team_id=team_id,
            role=role,
            context=self._context(context),
        )

    def start_tool(
        self,
        *,
        team_id: str,
        agent_id: str,
        tool_id: str,
        action: str,
        payload: Dict[str, object]
    ) -> str:
        return self.delegate.start_tool(
            team_id=team_id,
            agent_id=agent_id,
            tool_id=tool_id,
            action=action,
            payload=payload,
        )

    def complete_team(self, *, team_id: str) -> None:
        self.delegate.complete_team(team_id=team_id)

    def abort_team(self, *, team_id: str, reason: str) -> None:
        self.delegate.abort_team(team_id=team_id, reason=reason)


class DshNodeAttempt:
    """One lease-bound local attempt; Center still owns final evaluation."""

    def __init__(self, runtime: NodeTeamRuntime, assignment: NodeWorkAssignment, claim: ExecutionProvenance) -> None:
        self.runtime = runtime
        self.assignment = assignment
        self.claim = claim

    @property
    def attempt_id(self) -> str:
        return self.claim.attempt_id

    @property
    def team_id(self) -> Optional[str]:
        return self.runtime.team_id

    def dispatch_member(self, role: str) -> str:
        return self.runtime.dispatch_member(role)

    def start_tool(
        self,
        *,
        agent_id: str,
        tool_id: str,
        action: str,
        payload: Optional[Dict[str, object]] = None,
    ) -> str:
        normalized = (action or "").strip().upper()
        if normalized in self.assignment.forbidden_actions:
            raise DshNodeRuntimeAdapterError("WORK_ASSIGNMENT_ACTION_FORBIDDEN:%s" % normalized)
        return self.runtime.start_tool(
            agent_id=agent_id,
            tool_id=tool_id,
            action=action,
            payload=payload,
            attempt_id=self.attempt_id,
        )

    def emit_evidence(
        self,
        *,
        agent_id: str,
        tool_id: str,
        evidence_id: str,
        evidence_type: str,
        refs: Optional[Sequence[str]] = None,
    ) -> ExecutionProvenance:
        normalized = (evidence_type or "").strip().upper()
        if self.assignment.evidence_contract and normalized not in self.assignment.evidence_contract:
            raise DshNodeRuntimeAdapterError("EVIDENCE_TYPE_OUTSIDE_CONTRACT:%s" % normalized)
        return self.runtime.emit_evidence(
            agent_id=agent_id,
            tool_id=tool_id,
            evidence_id=evidence_id,
            evidence_type=evidence_type,
            refs=refs,
            attempt_id=self.attempt_id,
        )

    def complete_and_submit(self) -> ExecutionProvenance:
        self.runtime.complete_team()
        return self.runtime.submit_result()

    def abort(self, reason: str) -> None:
        self.runtime.abort(reason)


class DshNodeRuntimeAdapter:
    """Bootstrap leased work on one concrete dsh-node."""

    def __init__(
        self,
        control_plane: CenterControlPlane,
        gateway: DshAgentTeamsGateway,
        *,
        node_id: str,
    ) -> None:
        if not isinstance(control_plane, CenterControlPlane):
            raise DshNodeRuntimeAdapterError("CENTER_CONTROL_PLANE_REQUIRED")
        if not isinstance(node_id, str) or not node_id.strip():
            raise DshNodeRuntimeAdapterError("NODE_ID_REQUIRED")
        self.control_plane = control_plane
        self.gateway = gateway
        self.node_id = node_id.strip()

    def start_assignment(self, assignment: NodeWorkAssignment) -> DshNodeAttempt:
        if not isinstance(assignment, NodeWorkAssignment):
            raise DshNodeRuntimeAdapterError("NODE_WORK_ASSIGNMENT_REQUIRED")
        if assignment.node_id != self.node_id:
            raise DshNodeRuntimeAdapterError("ASSIGNMENT_NODE_MISMATCH")
        runtime = NodeTeamRuntime(
            self.control_plane,
            _AssignmentContextGateway(self.gateway, assignment),
            mission_id=assignment.mission_id,
            work_item_id=assignment.work_item_id,
            node_id=assignment.node_id,
            team_profile=assignment.team_profile,
        )
        claim = runtime.claim()
        runtime.start_team()
        return DshNodeAttempt(runtime, assignment, claim)
