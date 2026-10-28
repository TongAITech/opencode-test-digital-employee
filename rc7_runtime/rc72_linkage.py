"""RC7.2 transition and ETU->existing WorkItem/Attempt linkage contracts.

RC7.2 deliberately reuses RC7 `Task` as the durable WorkItem and the inherited
R1 `execution_attempt` as real Attempt truth. These records bind the new ETU/
N1-N10 semantics to those proven execution identities instead of duplicating
another scheduler/execution store.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .models import ContractError
from .rc72_domain import AutonomousMissionNode


def _now() -> int:
    return int(time.time())


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("%s_REQUIRED" % name.upper())
    return value.strip()


def _strings(values: List[str], name: str) -> List[str]:
    if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
        raise ContractError("%s_INVALID" % name.upper())
    return values


class NodeTransitionKind(str, Enum):
    FORWARD = "FORWARD"
    DIAGNOSIS = "DIAGNOSIS"
    BACK_EDGE = "BACK_EDGE"
    BLOCKED = "BLOCKED"
    HUMAN_GATE = "HUMAN_GATE"
    RESUME = "RESUME"


class WorkItemAttemptState(str, Enum):
    RESERVED = "RESERVED"
    PREPARED = "PREPARED"
    RUNNING = "RUNNING"
    EVIDENCE_READY = "EVIDENCE_READY"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class NodeTransition:
    transition_id: str
    mission_id: str
    from_mission_node_id: str
    from_node_type: AutonomousMissionNode
    to_mission_node_id: str
    to_node_type: AutonomousMissionNode
    kind: NodeTransitionKind
    reason: str
    source_gate_id: Optional[str] = None
    back_edge_id: Optional[str] = None
    evidence_refs: List[str] = field(default_factory=list)
    created_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        for field_name in (
            "transition_id", "mission_id", "from_mission_node_id", "to_mission_node_id", "reason",
        ):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
        for field_name in ("from_node_type", "to_node_type"):
            value = getattr(self, field_name)
            if not isinstance(value, AutonomousMissionNode):
                try:
                    object.__setattr__(self, field_name, AutonomousMissionNode(str(value)))
                except ValueError as exc:
                    raise ContractError("%s_INVALID" % field_name.upper()) from exc
        if not isinstance(self.kind, NodeTransitionKind):
            try:
                object.__setattr__(self, "kind", NodeTransitionKind(str(self.kind)))
            except ValueError as exc:
                raise ContractError("NODE_TRANSITION_KIND_INVALID") from exc
        if self.source_gate_id is not None:
            object.__setattr__(self, "source_gate_id", _required(self.source_gate_id, "source_gate_id"))
        if self.back_edge_id is not None:
            object.__setattr__(self, "back_edge_id", _required(self.back_edge_id, "back_edge_id"))
        _strings(self.evidence_refs, "evidence_refs")
        if self.kind == NodeTransitionKind.FORWARD and not self.source_gate_id:
            raise ContractError("FORWARD_TRANSITION_REQUIRES_SOURCE_GATE")
        if self.kind == NodeTransitionKind.DIAGNOSIS and not self.evidence_refs:
            raise ContractError("DIAGNOSIS_TRANSITION_REQUIRES_EVIDENCE")
        if self.kind == NodeTransitionKind.BACK_EDGE and not self.back_edge_id:
            raise ContractError("BACK_EDGE_TRANSITION_REQUIRES_BACK_EDGE")
        if self.from_mission_node_id == self.to_mission_node_id and self.kind != NodeTransitionKind.RESUME:
            raise ContractError("NODE_TRANSITION_SELF_ROUTE_FORBIDDEN")


@dataclass
class WorkItemAttemptBinding:
    """Durable binding from RC7.2 ETU to inherited RC7 Task/Attempt authority.

    `workitem_id` is an existing `rc7_task.task_id`; `attempt_id` is a reserved
    or existing inherited `execution_attempt.attempt_id`. Lease fields are refs
    only in Phase 1; the concrete governed lease lifecycles are implemented in
    Phase 7 without changing this durable lineage.
    """

    binding_id: str
    mission_id: str
    etu_id: str
    workitem_id: str
    case_id: str
    attempt_id: str
    state: WorkItemAttemptState = WorkItemAttemptState.RESERVED
    worker_id: Optional[str] = None
    session_id: Optional[str] = None
    task_lease_ref: Optional[str] = None
    capability_lease_refs: List[str] = field(default_factory=list)
    resource_lease_refs: List[str] = field(default_factory=list)
    parent_attempt_id: Optional[str] = None
    created_at: int = field(default_factory=_now)
    updated_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        for field_name in ("binding_id", "mission_id", "etu_id", "workitem_id", "case_id", "attempt_id"):
            setattr(self, field_name, _required(getattr(self, field_name), field_name))
        if not isinstance(self.state, WorkItemAttemptState):
            try:
                self.state = WorkItemAttemptState(str(self.state))
            except ValueError as exc:
                raise ContractError("WORKITEM_ATTEMPT_STATE_INVALID") from exc
        for field_name in ("worker_id", "session_id", "task_lease_ref", "parent_attempt_id"):
            value = getattr(self, field_name)
            if value is not None:
                setattr(self, field_name, _required(value, field_name))
        if isinstance(self.capability_lease_refs, tuple):
            self.capability_lease_refs = list(self.capability_lease_refs)
        if isinstance(self.resource_lease_refs, tuple):
            self.resource_lease_refs = list(self.resource_lease_refs)
        _strings(self.capability_lease_refs, "capability_lease_refs")
        _strings(self.resource_lease_refs, "resource_lease_refs")
        if self.state in {
            WorkItemAttemptState.PREPARED,
            WorkItemAttemptState.RUNNING,
            WorkItemAttemptState.EVIDENCE_READY,
            WorkItemAttemptState.COMPLETED,
            WorkItemAttemptState.BLOCKED,
        }:
            if not self.worker_id or not self.session_id:
                raise ContractError("ACTIVE_ATTEMPT_REQUIRES_WORKER_SESSION")
        if self.state in {
            WorkItemAttemptState.RUNNING,
            WorkItemAttemptState.EVIDENCE_READY,
            WorkItemAttemptState.COMPLETED,
            WorkItemAttemptState.BLOCKED,
        } and not self.task_lease_ref:
            raise ContractError("EXECUTING_ATTEMPT_REQUIRES_TASK_LEASE_REF")
