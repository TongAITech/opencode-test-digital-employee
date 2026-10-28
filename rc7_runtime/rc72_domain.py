"""RC7.2 canonical Autonomous Test Runtime domain model.

This module extends the RC7 control-plane model without mutating persisted
RC7.1 Mission graph identities. The entities here are deliberately session
independent: a Worker/LLM conversation may disappear while these records remain
recoverable from R1 truth.

ReleaseBatch is the highest business root. Test assets must preserve the
ReleaseBatch -> Requirement -> SST -> TestObligation lineage. Coverage is a
feedback signal attached to an obligation; it is never an alternative root.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .models import ContractError


def _now() -> int:
    return int(time.time())


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("%s_REQUIRED" % name.upper())
    return value.strip()


def _strings(values: List[str], name: str, *, allow_empty: bool = True) -> List[str]:
    if not isinstance(values, list):
        raise ContractError("%s_MUST_BE_LIST" % name.upper())
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ContractError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
    if not allow_empty and not values:
        raise ContractError("%s_REQUIRED" % name.upper())
    return values


def _optional_time(value: Optional[int], name: str) -> Optional[int]:
    if value is not None and (not isinstance(value, int) or value < 0):
        raise ContractError("%s_INVALID" % name.upper())
    return value


class AutonomousMissionNode(str, Enum):
    """Frozen RC7.2 N1-N10 semantic backbone."""

    N1_REALITY = "N1_REALITY"
    N2_REQUIREMENT = "N2_REQUIREMENT"
    N3_CODE_ANALYSIS = "N3_CODE_ANALYSIS"
    N4_TEST_DESIGN = "N4_TEST_DESIGN"
    N5_TEST_DATA = "N5_TEST_DATA"
    N6_EXECUTABLE_READINESS = "N6_EXECUTABLE_READINESS"
    N7_EXECUTION = "N7_EXECUTION"
    N8_DIAGNOSIS_RECOVERY = "N8_DIAGNOSIS_RECOVERY"
    N9_DEFECT = "N9_DEFECT"
    N10_RELEASE_CONVERGENCE = "N10_RELEASE_CONVERGENCE"

    @classmethod
    def ordered(cls) -> tuple:
        return (
            cls.N1_REALITY,
            cls.N2_REQUIREMENT,
            cls.N3_CODE_ANALYSIS,
            cls.N4_TEST_DESIGN,
            cls.N5_TEST_DATA,
            cls.N6_EXECUTABLE_READINESS,
            cls.N7_EXECUTION,
            cls.N8_DIAGNOSIS_RECOVERY,
            cls.N9_DEFECT,
            cls.N10_RELEASE_CONVERGENCE,
        )


class MissionNodeState(str, Enum):
    """Exact high-level states frozen by the N1-N10 state-machine contract."""

    NOT_STARTED = "NOT_STARTED"
    READY = "READY"
    RUNNING = "RUNNING"
    REVIEW_PENDING = "REVIEW_PENDING"
    PASS = "PASS"
    NEEDS_REVISION = "NEEDS_REVISION"
    BLOCKED = "BLOCKED"
    HUMAN_GATE = "HUMAN_GATE"
    STALE = "STALE"


class NodeGateDecision(str, Enum):
    PASS = "PASS"
    NEEDS_REVISION = "NEEDS_REVISION"
    BLOCKED = "BLOCKED"
    HUMAN_GATE = "HUMAN_GATE"


class ObligationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    READY = "READY"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    EXCLUDED = "EXCLUDED"


class ETUState(str, Enum):
    REGISTERED = "REGISTERED"
    READY = "READY"
    LEASED = "LEASED"
    RUNNING = "RUNNING"
    EVIDENCE_READY = "EVIDENCE_READY"
    PASS = "PASS"
    NEEDS_REVISION = "NEEDS_REVISION"
    BLOCKED = "BLOCKED"
    SPLIT_REQUIRED = "SPLIT_REQUIRED"
    MERGED = "MERGED"
    STALE = "STALE"


class BackEdgeState(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    SUPERSEDED = "SUPERSEDED"


@dataclass
class ReleaseBatch:
    release_batch_id: str
    mission_id: str
    name: str
    planned_release_time: Optional[str] = None
    version_ids: List[str] = field(default_factory=list)
    application_ids: List[str] = field(default_factory=list)
    requirement_ids: List[str] = field(default_factory=list)
    state: str = "REGISTERED"
    readiness: str = "UNKNOWN"
    created_at: int = field(default_factory=_now)
    updated_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.release_batch_id = _required(self.release_batch_id, "release_batch_id")
        self.mission_id = _required(self.mission_id, "mission_id")
        self.name = _required(self.name, "name")
        self.state = _required(self.state, "state").upper()
        self.readiness = _required(self.readiness, "readiness").upper()
        _strings(self.version_ids, "version_ids")
        _strings(self.application_ids, "application_ids")
        _strings(self.requirement_ids, "requirement_ids")
        if self.planned_release_time is not None:
            self.planned_release_time = _required(self.planned_release_time, "planned_release_time")


@dataclass
class MissionNodeRecord:
    mission_node_id: str
    mission_id: str
    node_type: AutonomousMissionNode
    scope_ref: str
    state: MissionNodeState = MissionNodeState.NOT_STARTED
    active_delivery_version: Optional[int] = None
    delivery_refs: List[str] = field(default_factory=list)
    gate_refs: List[str] = field(default_factory=list)
    open_gap_refs: List[str] = field(default_factory=list)
    entered_at: Optional[int] = None
    exited_at: Optional[int] = None
    blocked_reason: Optional[str] = None
    revision: int = 1
    created_at: int = field(default_factory=_now)
    updated_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.mission_node_id = _required(self.mission_node_id, "mission_node_id")
        self.mission_id = _required(self.mission_id, "mission_id")
        self.scope_ref = _required(self.scope_ref, "scope_ref")
        if not isinstance(self.node_type, AutonomousMissionNode):
            try:
                self.node_type = AutonomousMissionNode(str(self.node_type))
            except ValueError as exc:
                raise ContractError("MISSION_NODE_TYPE_INVALID") from exc
        if not isinstance(self.state, MissionNodeState):
            try:
                self.state = MissionNodeState(str(self.state))
            except ValueError as exc:
                raise ContractError("MISSION_NODE_STATE_INVALID") from exc
        if self.active_delivery_version is not None:
            if not isinstance(self.active_delivery_version, int) or self.active_delivery_version < 1:
                raise ContractError("MISSION_NODE_ACTIVE_DELIVERY_VERSION_INVALID")
        _strings(self.delivery_refs, "delivery_refs")
        _strings(self.gate_refs, "gate_refs")
        _strings(self.open_gap_refs, "open_gap_refs")
        _optional_time(self.entered_at, "entered_at")
        _optional_time(self.exited_at, "exited_at")
        if self.blocked_reason is not None:
            self.blocked_reason = _required(self.blocked_reason, "blocked_reason")
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ContractError("MISSION_NODE_REVISION_INVALID")


@dataclass(frozen=True)
class NodeDelivery:
    delivery_id: str
    mission_id: str
    mission_node_id: str
    node_type: AutonomousMissionNode
    version: int
    producer_ref: str
    input_refs: List[str] = field(default_factory=list)
    artifact_refs: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    known_gaps: List[str] = field(default_factory=list)
    created_by_workitems: List[str] = field(default_factory=list)
    sufficiency_score: Optional[float] = None
    created_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "delivery_id", _required(self.delivery_id, "delivery_id"))
        object.__setattr__(self, "mission_id", _required(self.mission_id, "mission_id"))
        object.__setattr__(self, "mission_node_id", _required(self.mission_node_id, "mission_node_id"))
        object.__setattr__(self, "producer_ref", _required(self.producer_ref, "producer_ref"))
        if not isinstance(self.node_type, AutonomousMissionNode):
            try:
                object.__setattr__(self, "node_type", AutonomousMissionNode(str(self.node_type)))
            except ValueError as exc:
                raise ContractError("NODE_DELIVERY_NODE_TYPE_INVALID") from exc
        if not isinstance(self.version, int) or self.version < 1:
            raise ContractError("NODE_DELIVERY_VERSION_INVALID")
        _strings(self.input_refs, "input_refs")
        _strings(self.artifact_refs, "artifact_refs")
        _strings(self.evidence_refs, "evidence_refs")
        _strings(self.known_gaps, "known_gaps")
        _strings(self.created_by_workitems, "created_by_workitems")
        if self.sufficiency_score is not None:
            if not isinstance(self.sufficiency_score, (int, float)) or not 0.0 <= float(self.sufficiency_score) <= 1.0:
                raise ContractError("NODE_DELIVERY_SUFFICIENCY_SCORE_INVALID")


@dataclass(frozen=True)
class NodeGate:
    gate_id: str
    mission_id: str
    mission_node_id: str
    node_type: AutonomousMissionNode
    delivery_id: str
    decision: NodeGateDecision
    reviewer_worker_id: str
    reviewer_session_id: str
    criteria: List[str] = field(default_factory=list)
    passed: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    return_node: Optional[AutonomousMissionNode] = None
    reason: Optional[str] = None
    created_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "gate_id", _required(self.gate_id, "gate_id"))
        object.__setattr__(self, "mission_id", _required(self.mission_id, "mission_id"))
        object.__setattr__(self, "mission_node_id", _required(self.mission_node_id, "mission_node_id"))
        object.__setattr__(self, "delivery_id", _required(self.delivery_id, "delivery_id"))
        object.__setattr__(self, "reviewer_worker_id", _required(self.reviewer_worker_id, "reviewer_worker_id"))
        object.__setattr__(self, "reviewer_session_id", _required(self.reviewer_session_id, "reviewer_session_id"))
        if not isinstance(self.node_type, AutonomousMissionNode):
            try:
                object.__setattr__(self, "node_type", AutonomousMissionNode(str(self.node_type)))
            except ValueError as exc:
                raise ContractError("NODE_GATE_NODE_TYPE_INVALID") from exc
        if not isinstance(self.decision, NodeGateDecision):
            try:
                object.__setattr__(self, "decision", NodeGateDecision(str(self.decision)))
            except ValueError as exc:
                raise ContractError("NODE_GATE_DECISION_INVALID") from exc
        _strings(self.criteria, "criteria", allow_empty=False)
        _strings(self.passed, "passed")
        _strings(self.failed, "failed")
        _strings(self.evidence_refs, "evidence_refs")
        if self.decision == NodeGateDecision.PASS and self.failed:
            raise ContractError("NODE_GATE_PASS_CANNOT_HAVE_FAILED_CRITERIA")
        if self.decision == NodeGateDecision.NEEDS_REVISION:
            if self.return_node is None:
                raise ContractError("NODE_GATE_REVISION_REQUIRES_RETURN_NODE")
            if not isinstance(self.return_node, AutonomousMissionNode):
                try:
                    object.__setattr__(self, "return_node", AutonomousMissionNode(str(self.return_node)))
                except ValueError as exc:
                    raise ContractError("NODE_GATE_RETURN_NODE_INVALID") from exc
        elif self.return_node is not None and not isinstance(self.return_node, AutonomousMissionNode):
            try:
                object.__setattr__(self, "return_node", AutonomousMissionNode(str(self.return_node)))
            except ValueError as exc:
                raise ContractError("NODE_GATE_RETURN_NODE_INVALID") from exc
        if self.reason is not None:
            object.__setattr__(self, "reason", _required(self.reason, "reason"))


@dataclass
class TestObligation:
    obligation_id: str
    mission_id: str
    release_batch_id: str
    requirement_id: str
    sst_id: str
    application_id: str
    business_scenario: str
    business_rule: str
    risk_level: str
    test_level: str
    code_slice_refs: List[str] = field(default_factory=list)
    change_refs: List[str] = field(default_factory=list)
    oracle_refs: List[str] = field(default_factory=list)
    coverage_targets: List[str] = field(default_factory=list)
    status: ObligationStatus = ObligationStatus.REGISTERED
    created_at: int = field(default_factory=_now)
    updated_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        for name in (
            "obligation_id", "mission_id", "release_batch_id", "requirement_id", "sst_id",
            "application_id", "business_scenario", "business_rule", "risk_level", "test_level",
        ):
            setattr(self, name, _required(getattr(self, name), name))
        self.risk_level = self.risk_level.upper()
        self.test_level = self.test_level.upper()
        if not isinstance(self.status, ObligationStatus):
            try:
                self.status = ObligationStatus(str(self.status))
            except ValueError as exc:
                raise ContractError("TEST_OBLIGATION_STATUS_INVALID") from exc
        _strings(self.code_slice_refs, "code_slice_refs")
        _strings(self.change_refs, "change_refs")
        _strings(self.oracle_refs, "oracle_refs", allow_empty=False)
        _strings(self.coverage_targets, "coverage_targets")


@dataclass
class ExecutionTaskUnit:
    etu_id: str
    mission_id: str
    release_batch_id: str
    obligation_id: str
    case_ids: List[str]
    primary_goal: str
    primary_code_slice: str
    test_level: str
    primary_oracle: str
    data_domain: str
    required_capabilities: List[str] = field(default_factory=list)
    estimated_duration_minutes: int = 15
    estimated_cost: float = 0.0
    state: ETUState = ETUState.REGISTERED
    created_at: int = field(default_factory=_now)
    updated_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        for name in (
            "etu_id", "mission_id", "release_batch_id", "obligation_id", "primary_goal",
            "primary_code_slice", "test_level", "primary_oracle", "data_domain",
        ):
            setattr(self, name, _required(getattr(self, name), name))
        self.test_level = self.test_level.upper()
        _strings(self.case_ids, "case_ids", allow_empty=False)
        if len(self.case_ids) > 8:
            raise ContractError("ETU_CASE_COUNT_EXCEEDS_DEFAULT_MAX")
        _strings(self.required_capabilities, "required_capabilities")
        if not isinstance(self.estimated_duration_minutes, int) or self.estimated_duration_minutes <= 0:
            raise ContractError("ETU_ESTIMATED_DURATION_INVALID")
        if not isinstance(self.estimated_cost, (int, float)) or float(self.estimated_cost) < 0:
            raise ContractError("ETU_ESTIMATED_COST_INVALID")
        if not isinstance(self.state, ETUState):
            try:
                self.state = ETUState(str(self.state))
            except ValueError as exc:
                raise ContractError("ETU_STATE_INVALID") from exc


@dataclass(frozen=True)
class BackEdge:
    back_edge_id: str
    mission_id: str
    gap_id: str
    from_node: AutonomousMissionNode
    from_delivery_id: str
    return_node: AutonomousMissionNode
    reason: str
    invalidated_refs: List[str] = field(default_factory=list)
    resolved_by_delivery_id: Optional[str] = None
    state: BackEdgeState = BackEdgeState.OPEN
    created_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "back_edge_id", _required(self.back_edge_id, "back_edge_id"))
        object.__setattr__(self, "mission_id", _required(self.mission_id, "mission_id"))
        object.__setattr__(self, "gap_id", _required(self.gap_id, "gap_id"))
        object.__setattr__(self, "from_delivery_id", _required(self.from_delivery_id, "from_delivery_id"))
        object.__setattr__(self, "reason", _required(self.reason, "reason"))
        for attr in ("from_node", "return_node"):
            value = getattr(self, attr)
            if not isinstance(value, AutonomousMissionNode):
                try:
                    object.__setattr__(self, attr, AutonomousMissionNode(str(value)))
                except ValueError as exc:
                    raise ContractError("BACK_EDGE_%s_INVALID" % attr.upper()) from exc
        if not isinstance(self.state, BackEdgeState):
            try:
                object.__setattr__(self, "state", BackEdgeState(str(self.state)))
            except ValueError as exc:
                raise ContractError("BACK_EDGE_STATE_INVALID") from exc
        _strings(self.invalidated_refs, "invalidated_refs")
        if self.resolved_by_delivery_id is not None:
            object.__setattr__(self, "resolved_by_delivery_id", _required(self.resolved_by_delivery_id, "resolved_by_delivery_id"))
        if self.from_node == self.return_node:
            raise ContractError("BACK_EDGE_SELF_ROUTE_FORBIDDEN")
        if self.state == BackEdgeState.RESOLVED and not self.resolved_by_delivery_id:
            raise ContractError("BACK_EDGE_RESOLVED_REQUIRES_DELIVERY")


RC72_CANONICAL_NODE_ORDER = tuple(node.value for node in AutonomousMissionNode.ordered())
