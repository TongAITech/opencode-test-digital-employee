"""Canonical RC7 control-plane domain models.

These models deliberately do not embed conversation history or provider/model
identities. Mission state is durable; worker sessions are disposable.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ContractError(ValueError):
    """Raised when an RC7 canonical contract is invalid."""


class MissionStatus(str, Enum):
    REGISTERED = "REGISTERED"
    RUNNING = "RUNNING"
    EVALUATING = "EVALUATING"
    REPAIRING = "REPAIRING"
    WAITING_HUMAN = "WAITING_HUMAN"
    BLOCKED = "BLOCKED"
    CONVERGED = "CONVERGED"
    CLOSED = "CLOSED"


class TaskStatus(str, Enum):
    REGISTERED = "REGISTERED"
    READY = "READY"
    LEASED = "LEASED"
    RUNNING = "RUNNING"
    OUTPUT_PRODUCED = "OUTPUT_PRODUCED"
    EVALUATING = "EVALUATING"
    PASS = "PASS"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    BLOCKED = "BLOCKED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    STALE = "STALE"


class ArtifactStatus(str, Enum):
    VALID = "VALID"
    STALE = "STALE"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
    SUPERSEDED = "SUPERSEDED"


class GapStatus(str, Enum):
    OPEN = "OPEN"
    PLANNED = "PLANNED"
    REPAIRING = "REPAIRING"
    EVIDENCE_PENDING = "EVIDENCE_PENDING"
    RESOLVED = "RESOLVED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    BLOCKED = "BLOCKED"
    WAIVED = "WAIVED"
    DUPLICATE = "DUPLICATE"
    SUPERSEDED = "SUPERSEDED"


class GapSeverity(str, Enum):
    BLOCKER = "BLOCKER"
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EvaluationResult(str, Enum):
    PASS = "PASS"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    BLOCKED = "BLOCKED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"


def _now() -> int:
    return int(time.time())


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("%s_REQUIRED" % name.upper())
    return value.strip()


def _string_list(values: List[str], name: str) -> List[str]:
    if not isinstance(values, list):
        raise ContractError("%s_MUST_BE_LIST" % name.upper())
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ContractError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
    return values


@dataclass
class Mission:
    mission_id: str
    release_id: str
    goal: str
    state: MissionStatus = MissionStatus.REGISTERED
    sufficiency_state: str = "UNKNOWN"
    artifact_refs: List[str] = field(default_factory=list)
    open_gap_ids: List[str] = field(default_factory=list)
    active_task_ids: List[str] = field(default_factory=list)
    residual_risk_ids: List[str] = field(default_factory=list)
    latest_evaluation_id: Optional[str] = None
    revision: int = 1
    created_at: int = field(default_factory=_now)
    updated_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.mission_id = _required(self.mission_id, "mission_id")
        self.release_id = _required(self.release_id, "release_id")
        self.goal = _required(self.goal, "goal")
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ContractError("MISSION_REVISION_INVALID")
        _string_list(self.artifact_refs, "artifact_refs")
        _string_list(self.open_gap_ids, "open_gap_ids")
        _string_list(self.active_task_ids, "active_task_ids")
        _string_list(self.residual_risk_ids, "residual_risk_ids")


@dataclass
class Task:
    task_id: str
    mission_id: str
    node: str
    task_type: str
    objective: str
    state: TaskStatus = TaskStatus.REGISTERED
    required_capabilities: List[str] = field(default_factory=list)
    dependency_task_ids: List[str] = field(default_factory=list)
    input_artifact_refs: List[str] = field(default_factory=list)
    gap_refs: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    priority: int = 100
    lease_owner: Optional[str] = None
    output_artifact_refs: List[str] = field(default_factory=list)
    evaluation_id: Optional[str] = None
    created_at: int = field(default_factory=_now)
    updated_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.task_id = _required(self.task_id, "task_id")
        self.mission_id = _required(self.mission_id, "mission_id")
        self.node = _required(self.node, "node")
        self.task_type = _required(self.task_type, "task_type")
        self.objective = _required(self.objective, "objective")
        if not isinstance(self.priority, int) or self.priority < 0:
            raise ContractError("TASK_PRIORITY_INVALID")
        _string_list(self.required_capabilities, "required_capabilities")
        _string_list(self.dependency_task_ids, "dependency_task_ids")
        _string_list(self.input_artifact_refs, "input_artifact_refs")
        _string_list(self.gap_refs, "gap_refs")
        _string_list(self.acceptance_criteria, "acceptance_criteria")
        _string_list(self.output_artifact_refs, "output_artifact_refs")
        if self.task_id in self.dependency_task_ids:
            raise ContractError("TASK_SELF_DEPENDENCY_FORBIDDEN")


@dataclass
class Artifact:
    artifact_id: str
    mission_id: str
    artifact_type: str
    producer_task_id: str
    content_ref: str
    version: int = 1
    state: ArtifactStatus = ArtifactStatus.VALID
    parent_refs: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    content_hash: Optional[str] = None
    created_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.artifact_id = _required(self.artifact_id, "artifact_id")
        self.mission_id = _required(self.mission_id, "mission_id")
        self.artifact_type = _required(self.artifact_type, "artifact_type")
        self.producer_task_id = _required(self.producer_task_id, "producer_task_id")
        self.content_ref = _required(self.content_ref, "content_ref")
        if not isinstance(self.version, int) or self.version < 1:
            raise ContractError("ARTIFACT_VERSION_INVALID")
        _string_list(self.parent_refs, "parent_refs")
        _string_list(self.evidence_refs, "evidence_refs")


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    mission_id: str
    kind: str
    source_ref: str
    content_ref: str
    subject_refs: List[str] = field(default_factory=list)
    content_hash: Optional[str] = None
    created_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _required(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "mission_id", _required(self.mission_id, "mission_id"))
        object.__setattr__(self, "kind", _required(self.kind, "kind"))
        object.__setattr__(self, "source_ref", _required(self.source_ref, "source_ref"))
        object.__setattr__(self, "content_ref", _required(self.content_ref, "content_ref"))
        _string_list(self.subject_refs, "subject_refs")


@dataclass
class Gap:
    gap_id: str
    mission_id: str
    source_node: str
    category: str
    severity: GapSeverity
    target_node: str
    description: str
    state: GapStatus = GapStatus.OPEN
    subject_refs: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    root_gap_id: Optional[str] = None
    acceptance_criteria: List[str] = field(default_factory=list)
    resolution_evaluation_id: Optional[str] = None
    created_at: int = field(default_factory=_now)
    updated_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.gap_id = _required(self.gap_id, "gap_id")
        self.mission_id = _required(self.mission_id, "mission_id")
        self.source_node = _required(self.source_node, "source_node")
        self.category = _required(self.category, "category")
        self.target_node = _required(self.target_node, "target_node")
        self.description = _required(self.description, "description")
        _string_list(self.subject_refs, "subject_refs")
        _string_list(self.evidence_refs, "evidence_refs")
        _string_list(self.acceptance_criteria, "acceptance_criteria")


@dataclass(frozen=True)
class Evaluation:
    evaluation_id: str
    mission_id: str
    node: str
    artifact_refs: List[str]
    result: EvaluationResult
    evaluator_ref: str
    dimensions: Dict[str, Any] = field(default_factory=dict)
    gap_refs: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    created_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluation_id", _required(self.evaluation_id, "evaluation_id"))
        object.__setattr__(self, "mission_id", _required(self.mission_id, "mission_id"))
        object.__setattr__(self, "node", _required(self.node, "node"))
        object.__setattr__(self, "evaluator_ref", _required(self.evaluator_ref, "evaluator_ref"))
        _string_list(self.artifact_refs, "artifact_refs")
        _string_list(self.gap_refs, "gap_refs")
        _string_list(self.evidence_refs, "evidence_refs")
        if not isinstance(self.dimensions, dict):
            raise ContractError("EVALUATION_DIMENSIONS_MUST_BE_OBJECT")


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    mission_id: str
    event_type: str
    subject_type: str
    subject_id: str
    refs: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    occurred_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _required(self.event_id, "event_id"))
        object.__setattr__(self, "mission_id", _required(self.mission_id, "mission_id"))
        object.__setattr__(self, "event_type", _required(self.event_type, "event_type"))
        object.__setattr__(self, "subject_type", _required(self.subject_type, "subject_type"))
        object.__setattr__(self, "subject_id", _required(self.subject_id, "subject_id"))
        _string_list(self.refs, "refs")
        if not isinstance(self.data, dict):
            raise ContractError("EVENT_DATA_MUST_BE_OBJECT")


def to_payload(value: Any) -> Dict[str, Any]:
    """Return a JSON-friendly payload while preserving canonical enum values."""
    data = asdict(value)
    for key, item in list(data.items()):
        if isinstance(item, Enum):
            data[key] = item.value
    return data
