from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


_DEFECT_HUNTER_ROLE = "DEFECT_HUNTER"
_DEFECT_HUNTER_AGENT = "aitest-diagnosis"
_R1_TRUTH_SOURCE = "R1_EVENT_STREAM"
_EVIDENCE_REQUEST_MODES = frozenset({"EXISTING_TYPED_REFS", "NEW_GOVERNED_ACTION"})


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{name} must be a non-empty mapping")
    if any(not isinstance(key, str) or not key for key in value):
        raise ValueError(f"{name} keys must be non-empty strings")
    return dict(value)


def _reference(value: Any, name: str) -> dict[str, Any]:
    reference = _mapping(value, name)
    has_identity = any(
        key == "id" or key.endswith("_id") or key.endswith("_ref")
        for key in reference
    )
    has_digest = any(key == "digest" or key.endswith("_digest") for key in reference)
    if not has_identity or not has_digest:
        raise ValueError(f"{name} must carry typed identity and digest lineage")
    return reference


def _references(value: Any, name: str, *, required: bool = False) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be an array of references")
    references = tuple(_reference(item, f"{name}[]") for item in value)
    if required and not references:
        raise ValueError(f"{name} must not be empty")
    return references


def _strings(value: Any, name: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be an array of strings")
    strings = tuple(_text(item, f"{name}[]") for item in value)
    if required and not strings:
        raise ValueError(f"{name} must not be empty")
    return strings


def _mappings(value: Any, name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be an array of mappings")
    return tuple(_mapping(item, f"{name}[]") for item in value)


@dataclass(frozen=True)
class G5WorkerBinding:
    """Validated view of existing Router/R2.5 binding truth; never durable state."""

    mission_id: str
    task_id: str
    current_attempt_id: str
    root_attempt_id: str
    current_session_id: str
    logical_agent_id: str
    router_role: str = field(default=_DEFECT_HUNTER_ROLE, init=False)
    agent_name: str = field(default=_DEFECT_HUNTER_AGENT, init=False)
    r2_5_binding_id: str
    r2_5_anchor_attempt_id: str
    r2_5_anchor_session_id: str

    def __post_init__(self) -> None:
        for name in (
            "mission_id", "task_id", "current_attempt_id", "root_attempt_id",
            "current_session_id", "logical_agent_id", "r2_5_binding_id",
            "r2_5_anchor_attempt_id", "r2_5_anchor_session_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "task_id": self.task_id,
            "current_attempt_id": self.current_attempt_id,
            "root_attempt_id": self.root_attempt_id,
            "current_session_id": self.current_session_id,
            "logical_agent_id": self.logical_agent_id,
            "router_role": self.router_role,
            "agent_name": self.agent_name,
            "r2_5_binding_id": self.r2_5_binding_id,
            "r2_5_anchor_attempt_id": self.r2_5_anchor_attempt_id,
            "r2_5_anchor_session_id": self.r2_5_anchor_session_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "G5WorkerBinding":
        if value.get("router_role") != _DEFECT_HUNTER_ROLE:
            raise ValueError("router_role must be DEFECT_HUNTER")
        if value.get("agent_name") != _DEFECT_HUNTER_AGENT:
            raise ValueError("agent_name must be aitest-diagnosis")
        return cls(
            mission_id=value["mission_id"],
            task_id=value["task_id"],
            current_attempt_id=value["current_attempt_id"],
            root_attempt_id=value["root_attempt_id"],
            current_session_id=value["current_session_id"],
            logical_agent_id=value["logical_agent_id"],
            r2_5_binding_id=value["r2_5_binding_id"],
            r2_5_anchor_attempt_id=value["r2_5_anchor_attempt_id"],
            r2_5_anchor_session_id=value["r2_5_anchor_session_id"],
        )


@dataclass(frozen=True)
class G4ObservationAdmission:
    """Exact non-durable lineage envelope for a governed G4 observation."""

    mission_id: str
    g4_goal_id: str
    observation_ref: Mapping[str, Any]
    step_result_ref: Mapping[str, Any]
    oracle_result: str
    scope: Mapping[str, Any]
    quality_version_ref: Mapping[str, Any]
    campaign_refs: tuple[Mapping[str, Any], ...]
    case_ref: Mapping[str, Any]
    case_version: str
    case_value_link_ref: Mapping[str, Any]
    strategy_refs: tuple[Mapping[str, Any], ...]
    execution_batch_ref: Mapping[str, Any]
    execution_attempt_ref: Mapping[str, Any]
    step_cursor_ref: Mapping[str, Any]
    expected_ref: Mapping[str, Any]
    actual_refs: tuple[Mapping[str, Any], ...]
    evidence_refs: tuple[Mapping[str, Any], ...]
    source_identity_ref: Mapping[str, Any]
    execution_node_ref: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        object.__setattr__(self, "g4_goal_id", _text(self.g4_goal_id, "g4_goal_id"))
        object.__setattr__(self, "oracle_result", _text(self.oracle_result, "oracle_result").upper())
        object.__setattr__(self, "scope", _mapping(self.scope, "scope"))
        object.__setattr__(self, "case_version", _text(self.case_version, "case_version"))
        for name in (
            "observation_ref", "step_result_ref", "quality_version_ref", "case_ref",
            "case_value_link_ref", "execution_batch_ref", "execution_attempt_ref",
            "step_cursor_ref", "expected_ref", "source_identity_ref", "execution_node_ref",
        ):
            object.__setattr__(self, name, _reference(getattr(self, name), name))
        for name in ("campaign_refs", "strategy_refs", "actual_refs", "evidence_refs"):
            object.__setattr__(self, name, _references(getattr(self, name), name, required=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "g4_goal_id": self.g4_goal_id,
            "observation_ref": dict(self.observation_ref),
            "step_result_ref": dict(self.step_result_ref),
            "oracle_result": self.oracle_result,
            "scope": dict(self.scope),
            "quality_version_ref": dict(self.quality_version_ref),
            "campaign_refs": [dict(item) for item in self.campaign_refs],
            "case_ref": dict(self.case_ref),
            "case_version": self.case_version,
            "case_value_link_ref": dict(self.case_value_link_ref),
            "strategy_refs": [dict(item) for item in self.strategy_refs],
            "execution_batch_ref": dict(self.execution_batch_ref),
            "execution_attempt_ref": dict(self.execution_attempt_ref),
            "step_cursor_ref": dict(self.step_cursor_ref),
            "expected_ref": dict(self.expected_ref),
            "actual_refs": [dict(item) for item in self.actual_refs],
            "evidence_refs": [dict(item) for item in self.evidence_refs],
            "source_identity_ref": dict(self.source_identity_ref),
            "execution_node_ref": dict(self.execution_node_ref),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "G4ObservationAdmission":
        return cls(
            mission_id=value["mission_id"],
            g4_goal_id=value["g4_goal_id"],
            observation_ref=value["observation_ref"],
            step_result_ref=value["step_result_ref"],
            oracle_result=value["oracle_result"],
            scope=value["scope"],
            quality_version_ref=value["quality_version_ref"],
            campaign_refs=tuple(value["campaign_refs"]),
            case_ref=value["case_ref"],
            case_version=value["case_version"],
            case_value_link_ref=value["case_value_link_ref"],
            strategy_refs=tuple(value["strategy_refs"]),
            execution_batch_ref=value["execution_batch_ref"],
            execution_attempt_ref=value["execution_attempt_ref"],
            step_cursor_ref=value["step_cursor_ref"],
            expected_ref=value["expected_ref"],
            actual_refs=tuple(value["actual_refs"]),
            evidence_refs=tuple(value["evidence_refs"]),
            source_identity_ref=value["source_identity_ref"],
            execution_node_ref=value["execution_node_ref"],
        )


@dataclass(frozen=True)
class GovernedEvidenceRequest:
    """Request envelope only; it is never Task or Plan truth."""

    request_id: str
    mission_id: str
    candidate_id: str
    mode: str
    requested_channels: tuple[str, ...]
    evidence_gap: str
    required_scope: Mapping[str, Any]
    risk_class: str
    preferred_role: str
    existing_task_refs: tuple[Mapping[str, Any], ...]
    planner_constraints: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        for name in ("request_id", "mission_id", "candidate_id", "evidence_gap"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        mode = _text(self.mode, "mode").upper()
        if mode not in _EVIDENCE_REQUEST_MODES:
            raise ValueError("mode must be EXISTING_TYPED_REFS or NEW_GOVERNED_ACTION")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "requested_channels", _strings(self.requested_channels, "requested_channels", required=True))
        object.__setattr__(self, "required_scope", _mapping(self.required_scope, "required_scope"))
        object.__setattr__(self, "risk_class", _text(self.risk_class, "risk_class").upper())
        object.__setattr__(self, "preferred_role", _text(self.preferred_role, "preferred_role").upper())
        object.__setattr__(self, "existing_task_refs", _references(self.existing_task_refs, "existing_task_refs"))
        object.__setattr__(self, "planner_constraints", _mappings(self.planner_constraints, "planner_constraints"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "mission_id": self.mission_id,
            "candidate_id": self.candidate_id,
            "mode": self.mode,
            "requested_channels": list(self.requested_channels),
            "evidence_gap": self.evidence_gap,
            "required_scope": dict(self.required_scope),
            "risk_class": self.risk_class,
            "preferred_role": self.preferred_role,
            "existing_task_refs": [dict(item) for item in self.existing_task_refs],
            "planner_constraints": [dict(item) for item in self.planner_constraints],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GovernedEvidenceRequest":
        return cls(
            request_id=value["request_id"],
            mission_id=value["mission_id"],
            candidate_id=value["candidate_id"],
            mode=value["mode"],
            requested_channels=tuple(value["requested_channels"]),
            evidence_gap=value["evidence_gap"],
            required_scope=value["required_scope"],
            risk_class=value["risk_class"],
            preferred_role=value["preferred_role"],
            existing_task_refs=tuple(value.get("existing_task_refs") or ()),
            planner_constraints=tuple(value.get("planner_constraints") or ()),
        )


class DuplicateCorrelationDecision(str, Enum):
    NONE = "NONE"
    SAME_OPEN_CANDIDATE = "SAME_OPEN_CANDIDATE"
    SAME_CONFIRMED_LIFECYCLE = "SAME_CONFIRMED_LIFECYCLE"
    AMBIGUOUS_REVIEW_REQUIRED = "AMBIGUOUS_REVIEW_REQUIRED"


@dataclass(frozen=True)
class G5OperationResult:
    """Non-durable product result envelope over canonical R1 truth."""

    truth_source: str = field(default=_R1_TRUTH_SOURCE, init=False)
    status: str
    mission_id: str | None = None
    head_seq: int | None = None
    canonical_refs: tuple[Mapping[str, Any], ...] = ()
    next_required_action: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _text(self.status, "status").upper())
        object.__setattr__(self, "mission_id", _optional_text(self.mission_id, "mission_id"))
        if self.head_seq is not None and (isinstance(self.head_seq, bool) or not isinstance(self.head_seq, int) or self.head_seq < 0):
            raise ValueError("head_seq must be a non-negative integer or null")
        object.__setattr__(self, "canonical_refs", _references(self.canonical_refs, "canonical_refs"))
        object.__setattr__(self, "next_required_action", _optional_text(self.next_required_action, "next_required_action"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "truth_source": self.truth_source,
            "status": self.status,
            "mission_id": self.mission_id,
            "head_seq": self.head_seq,
            "canonical_refs": [dict(item) for item in self.canonical_refs],
            "next_required_action": self.next_required_action,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "G5OperationResult":
        if value.get("truth_source") != _R1_TRUTH_SOURCE:
            raise ValueError("truth_source must be R1_EVENT_STREAM")
        return cls(
            status=value["status"],
            mission_id=value.get("mission_id"),
            head_seq=value.get("head_seq"),
            canonical_refs=tuple(value.get("canonical_refs") or ()),
            next_required_action=value.get("next_required_action"),
        )
