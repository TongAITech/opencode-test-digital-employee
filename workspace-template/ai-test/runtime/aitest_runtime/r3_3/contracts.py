from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError, canonical_sha256
from aitest_runtime.r3_2.contracts import R31Reference


EXTENSION_ID = "r3_3_test_strategy_standard_case_design"
EXTENSION_VERSION = "1"
R33_SCHEMA_VERSION = 1

CREATE_TEST_STRATEGY = "R33_CREATE_TEST_STRATEGY"
DESIGN_CASE_BATCH = "R33_DESIGN_CASE_BATCH"

STRATEGY_CREATED = "r3.3.strategy_created.v1"
CASE_BATCH_DESIGNED = "r3.3.case_batch_designed.v1"
DESIGN_REUSED = "r3.3.design_reused.v1"

COMMAND_TYPES = frozenset({CREATE_TEST_STRATEGY, DESIGN_CASE_BATCH})
EVENT_TYPES = frozenset({STRATEGY_CREATED, CASE_BATCH_DESIGNED, DESIGN_REUSED})

LAYER_IDS = tuple(f"L{index}" for index in range(1, 8))
LAYER_DECISIONS = frozenset({"SELECTED", "NOT_SELECTED", "BLOCKED", "UNRESOLVED"})
DESIGNABILITIES = frozenset({"DESIGNABLE", "PARTIAL", "BLOCKED", "UNMAPPED"})
STRATEGY_STATUSES = frozenset({"DRAFT", "DESIGN_BLOCKED", "DESIGNED"})
CASE_STATUSES = frozenset({"DRAFT", "DRAFT_WITH_GAPS", "DESIGN_BLOCKED"})
BATCH_STATUSES = frozenset({"PENDING", "IN_PROGRESS", "COMPLETED", "BLOCKED"})
MAPPING_RELATIONS = frozenset({"IMPLEMENTS", "PARTIALLY_IMPLEMENTS", "SUPPORTS_DATA", "OBSERVES"})
MAPPING_STATES = frozenset({"PROPOSED", "EVIDENCE_BACKED", "PARTIAL", "STALE", "UNMAPPED"})
RECONCILIATION_SEMANTICS = frozenset({
    "OVERLAP", "REQUIREMENT_ONLY", "CHANGE_ONLY", "REQUIREMENT_CODE_GAP", "UNMAPPED",
})
RISK_BANDS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
RISK_DIMENSIONS = (
    "business_criticality",
    "change_magnitude",
    "impact_breadth",
    "change_uncertainty",
    "critical_journey_criticality",
    "historical_failure_signal",
    "security_data_sensitivity",
    "performance_sensitivity",
    "evidence_gap_penalty",
)


class R33Error(RuntimeError):
    """R3.3 contract, source-reference, design and projection error."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R33Error("R3_3_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R33Error("R3_3_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _array(value: Any, name: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise R33Error("R3_3_SCHEMA_INVALID", f"{name} must be an array")
    return list(value)


def _text_tuple(value: Any, name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    values = tuple(_text(item, f"{name}[]") for item in _array(value, name))
    if not allow_empty and not values:
        raise R33Error("R3_3_SCHEMA_INVALID", f"{name} must not be empty")
    return values


def _non_negative(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise R33Error("R3_3_SCHEMA_INVALID", f"{name} must be a non-negative integer")
    return value


def _positive(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise R33Error("R3_3_SCHEMA_INVALID", f"{name} must be a positive integer")
    return value


def _number(value: Any, name: str, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise R33Error("R3_3_SCHEMA_INVALID", f"{name} must be numeric")
    result = float(value)
    if result < minimum or (maximum is not None and result > maximum):
        raise R33Error("R3_3_SCHEMA_INVALID", f"{name} is outside its allowed range")
    return result


def _copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_copy(item) for item in value)
    return value


def _json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _mapping_tuple(value: Any, name: str) -> tuple[Mapping[str, Any], ...]:
    result = []
    for item in _array(value, name):
        result.append(_mapping(item, f"{name}[]"))
    return tuple(result)


@dataclass(frozen=True)
class R32Reference:
    derivation_version_id: str
    derivation_fingerprint: str
    reconciliation_id: str
    compare_identity_digest: str
    provider_envelope_digest: str

    def __post_init__(self) -> None:
        for name in (
            "derivation_version_id", "derivation_fingerprint", "reconciliation_id",
            "compare_identity_digest", "provider_envelope_digest",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))

    def to_dict(self) -> dict[str, str]:
        return {
            "derivation_version_id": self.derivation_version_id,
            "derivation_fingerprint": self.derivation_fingerprint,
            "reconciliation_id": self.reconciliation_id,
            "compare_identity_digest": self.compare_identity_digest,
            "provider_envelope_digest": self.provider_envelope_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R32Reference":
        return cls(
            derivation_version_id=value["derivation_version_id"],
            derivation_fingerprint=value["derivation_fingerprint"],
            reconciliation_id=value["reconciliation_id"],
            compare_identity_digest=value["compare_identity_digest"],
            provider_envelope_digest=value["provider_envelope_digest"],
        )


@dataclass(frozen=True)
class RiskVector:
    dimensions: Mapping[str, int]
    policy_version: str
    weights: Mapping[str, float]
    thresholds: Mapping[str, float]
    score: float
    band: str
    overrides: tuple[Mapping[str, Any], ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        values = {str(key): _non_negative(value, f"risk dimension {key}") for key, value in _mapping(self.dimensions, "dimensions").items()}
        missing = set(RISK_DIMENSIONS) - set(values)
        if missing:
            raise R33Error("R3_3_RISK_VECTOR_INVALID", f"missing risk dimensions: {sorted(missing)}")
        if any(value > 5 for value in values.values()):
            raise R33Error("R3_3_RISK_VECTOR_INVALID", "risk dimensions must be between 0 and 5")
        object.__setattr__(self, "dimensions", values)
        object.__setattr__(self, "policy_version", _text(self.policy_version, "policy_version"))
        object.__setattr__(self, "weights", {str(key): _number(value, f"weights.{key}") for key, value in _mapping(self.weights, "weights").items()})
        object.__setattr__(self, "thresholds", {str(key): _number(value, f"thresholds.{key}", maximum=100) for key, value in _mapping(self.thresholds, "thresholds").items()})
        object.__setattr__(self, "score", _number(self.score, "score", maximum=100))
        if self.band not in RISK_BANDS:
            raise R33Error("R3_3_RISK_VECTOR_INVALID", f"invalid risk band: {self.band}")
        object.__setattr__(self, "overrides", _mapping_tuple(self.overrides, "overrides"))
        object.__setattr__(self, "evidence_refs", _text_tuple(self.evidence_refs, "evidence_refs"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensions": dict(self.dimensions),
            "policy_version": self.policy_version,
            "weights": dict(self.weights),
            "thresholds": dict(self.thresholds),
            "score": self.score,
            "band": self.band,
            "overrides": [_json(item) for item in self.overrides],
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RiskVector":
        return cls(
            dimensions=value["dimensions"], policy_version=value["policy_version"],
            weights=value["weights"], thresholds=value["thresholds"], score=value["score"],
            band=value["band"], overrides=tuple(value.get("overrides") or ()),
            evidence_refs=tuple(value.get("evidence_refs") or ()),
        )


@dataclass(frozen=True)
class LayerDecision:
    layer_id: str
    decision: str
    rationale: str
    trigger_refs: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    profile_version: str = "r3.3.layer-profile.v1"
    required_inputs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.layer_id not in LAYER_IDS:
            raise R33Error("R3_3_LAYER_PROFILE_INVALID", f"invalid layer_id: {self.layer_id}")
        if self.decision not in LAYER_DECISIONS:
            raise R33Error("R3_3_LAYER_DECISION_INVALID", f"invalid layer decision: {self.decision}")
        object.__setattr__(self, "rationale", _text(self.rationale, "rationale"))
        object.__setattr__(self, "trigger_refs", _text_tuple(self.trigger_refs, "trigger_refs"))
        object.__setattr__(self, "missing_inputs", _text_tuple(self.missing_inputs, "missing_inputs"))
        object.__setattr__(self, "profile_version", _text(self.profile_version, "profile_version"))
        object.__setattr__(self, "required_inputs", _copy(_mapping(self.required_inputs, "required_inputs")))

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer_id": self.layer_id, "decision": self.decision, "rationale": self.rationale,
            "trigger_refs": list(self.trigger_refs), "missing_inputs": list(self.missing_inputs),
            "profile_version": self.profile_version, "required_inputs": _json(self.required_inputs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LayerDecision":
        return cls(
            layer_id=value["layer_id"], decision=value["decision"], rationale=value["rationale"],
            trigger_refs=tuple(value.get("trigger_refs") or ()), missing_inputs=tuple(value.get("missing_inputs") or ()),
            profile_version=value.get("profile_version", "r3.3.layer-profile.v1"),
            required_inputs=value.get("required_inputs") or {},
        )


@dataclass(frozen=True)
class TestPoint:
    point_id: str
    strategy_version_id: str
    source_members: tuple[Mapping[str, Any], ...]
    coverage_obligation_refs: tuple[str, ...]
    change_impact_obligation_refs: tuple[str, ...]
    target_refs: tuple[str, ...]
    code_refs: tuple[str, ...]
    page_refs: tuple[str, ...]
    api_refs: tuple[str, ...]
    journey_refs: tuple[str, ...]
    behavior_contract: Mapping[str, Any]
    state_transition_refs: tuple[str, ...]
    risk_vector: RiskVector
    risk_band: str
    risk_evidence_refs: tuple[str, ...]
    layer_decisions: tuple[LayerDecision, ...]
    oracle_contract_ref: str | None
    oracle_design_digest: str | None
    evidence_requirement_refs: tuple[str, ...]
    designability: str
    batch_id: str
    deterministic_order: int
    gaps: tuple[str, ...] = ()
    source_provenance: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "point_id", _text(self.point_id, "point_id"))
        object.__setattr__(self, "strategy_version_id", _text(self.strategy_version_id, "strategy_version_id"))
        object.__setattr__(self, "source_members", _mapping_tuple(self.source_members, "source_members"))
        for name in (
            "coverage_obligation_refs", "change_impact_obligation_refs", "target_refs", "code_refs",
            "page_refs", "api_refs", "journey_refs", "state_transition_refs", "risk_evidence_refs",
            "evidence_requirement_refs", "gaps", "source_provenance",
        ):
            object.__setattr__(self, name, _text_tuple(getattr(self, name), name))
        object.__setattr__(self, "behavior_contract", _copy(_mapping(self.behavior_contract, "behavior_contract")))
        if not isinstance(self.risk_vector, RiskVector):
            raise R33Error("R3_3_SCHEMA_INVALID", "risk_vector must be a RiskVector")
        if self.risk_band not in RISK_BANDS:
            raise R33Error("R3_3_RISK_VECTOR_INVALID", "invalid point risk band")
        if not isinstance(self.layer_decisions, tuple) or len(self.layer_decisions) != 7 or any(not isinstance(item, LayerDecision) for item in self.layer_decisions):
            raise R33Error("R3_3_LAYER_DECISION_INVALID", "every TestPoint must retain exactly seven LayerDecision records")
        object.__setattr__(self, "oracle_contract_ref", _optional_text(self.oracle_contract_ref, "oracle_contract_ref"))
        object.__setattr__(self, "oracle_design_digest", _optional_text(self.oracle_design_digest, "oracle_design_digest"))
        object.__setattr__(self, "designability", _text(self.designability, "designability"))
        if self.designability not in DESIGNABILITIES:
            raise R33Error("R3_3_DESIGNABILITY_INVALID", f"invalid designability: {self.designability}")
        object.__setattr__(self, "batch_id", _text(self.batch_id, "batch_id"))
        object.__setattr__(self, "deterministic_order", _non_negative(self.deterministic_order, "deterministic_order"))
        object.__setattr__(self, "metadata", _copy(_mapping(self.metadata, "metadata")))

    def to_dict(self) -> dict[str, Any]:
        return {
            "point_id": self.point_id, "strategy_version_id": self.strategy_version_id,
            "source_members": [_json(item) for item in self.source_members],
            "coverage_obligation_refs": list(self.coverage_obligation_refs),
            "change_impact_obligation_refs": list(self.change_impact_obligation_refs),
            "target_refs": list(self.target_refs), "code_refs": list(self.code_refs),
            "page_refs": list(self.page_refs), "api_refs": list(self.api_refs),
            "journey_refs": list(self.journey_refs), "behavior_contract": _json(self.behavior_contract),
            "state_transition_refs": list(self.state_transition_refs),
            "risk_vector": self.risk_vector.to_dict(), "risk_band": self.risk_band,
            "risk_evidence_refs": list(self.risk_evidence_refs),
            "layer_decisions": [item.to_dict() for item in self.layer_decisions],
            "oracle_contract_ref": self.oracle_contract_ref, "oracle_design_digest": self.oracle_design_digest,
            "evidence_requirement_refs": list(self.evidence_requirement_refs),
            "designability": self.designability, "batch_id": self.batch_id,
            "deterministic_order": self.deterministic_order, "gaps": list(self.gaps),
            "source_provenance": list(self.source_provenance), "metadata": _json(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TestPoint":
        return cls(
            point_id=value["point_id"], strategy_version_id=value["strategy_version_id"],
            source_members=tuple(value.get("source_members") or ()),
            coverage_obligation_refs=tuple(value.get("coverage_obligation_refs") or ()),
            change_impact_obligation_refs=tuple(value.get("change_impact_obligation_refs") or ()),
            target_refs=tuple(value.get("target_refs") or ()), code_refs=tuple(value.get("code_refs") or ()),
            page_refs=tuple(value.get("page_refs") or ()), api_refs=tuple(value.get("api_refs") or ()),
            journey_refs=tuple(value.get("journey_refs") or ()), behavior_contract=value.get("behavior_contract") or {},
            state_transition_refs=tuple(value.get("state_transition_refs") or ()),
            risk_vector=RiskVector.from_dict(value["risk_vector"]), risk_band=value["risk_band"],
            risk_evidence_refs=tuple(value.get("risk_evidence_refs") or ()),
            layer_decisions=tuple(LayerDecision.from_dict(item) for item in value.get("layer_decisions") or ()),
            oracle_contract_ref=value.get("oracle_contract_ref"), oracle_design_digest=value.get("oracle_design_digest"),
            evidence_requirement_refs=tuple(value.get("evidence_requirement_refs") or ()),
            designability=value["designability"], batch_id=value["batch_id"],
            deterministic_order=value["deterministic_order"], gaps=tuple(value.get("gaps") or ()),
            source_provenance=tuple(value.get("source_provenance") or ()), metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True)
class StandardTestCase:
    tc_id: str
    case_version_id: str
    version: int
    lifecycle_status: str
    strategy_version_id: str
    test_point_id: str
    batch_id: str
    coverage_obligation_refs: tuple[str, ...]
    requirement_id: str | None
    sst_id: str | None
    design_refs: tuple[str, ...]
    code_refs: tuple[str, ...]
    change_impact_refs: tuple[str, ...]
    reconciliation_semantics: tuple[str, ...]
    risk_refs: tuple[str, ...]
    layer_id: str
    layer_profile_version: str
    case_type: str
    priority: str
    risk: RiskVector
    source_context: Mapping[str, Any]
    objective: str
    title: str
    preconditions: tuple[Mapping[str, Any], ...]
    test_data: tuple[Mapping[str, Any], ...]
    environment_and_boundary: Mapping[str, Any]
    steps: tuple[Mapping[str, Any], ...]
    expected_results: tuple[Mapping[str, Any], ...]
    postconditions: tuple[Mapping[str, Any], ...]
    oracle_contract: Mapping[str, Any]
    evidence_requirements: tuple[Mapping[str, Any], ...]
    execution_profile: Mapping[str, Any]
    automation_mapping_refs: tuple[str, ...]
    specification_status: str
    source_provenance: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    supersedes_case_version_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("tc_id", "case_version_id", "strategy_version_id", "test_point_id", "batch_id", "layer_id", "layer_profile_version", "case_type", "priority", "objective", "title", "specification_status"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "version", _positive(self.version, "version"))
        if self.lifecycle_status not in CASE_STATUSES:
            raise R33Error("R3_3_CASE_STATUS_INVALID", f"invalid case lifecycle_status: {self.lifecycle_status}")
        if self.layer_id not in LAYER_IDS:
            raise R33Error("R3_3_LAYER_PROFILE_INVALID", f"invalid case layer_id: {self.layer_id}")
        for name in (
            "coverage_obligation_refs", "design_refs", "code_refs", "change_impact_refs",
            "reconciliation_semantics", "risk_refs", "automation_mapping_refs", "source_provenance", "evidence_refs",
        ):
            object.__setattr__(self, name, _text_tuple(getattr(self, name), name))
        for name in ("requirement_id", "sst_id", "supersedes_case_version_id"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        for name in ("source_context", "environment_and_boundary", "oracle_contract", "execution_profile"):
            object.__setattr__(self, name, _copy(_mapping(getattr(self, name), name)))
        for name in ("preconditions", "test_data", "steps", "expected_results", "postconditions", "evidence_requirements"):
            object.__setattr__(self, name, _mapping_tuple(getattr(self, name), name))
        if not isinstance(self.risk, RiskVector):
            raise R33Error("R3_3_SCHEMA_INVALID", "case risk must be a RiskVector")
        if not self.evidence_requirements:
            raise R33Error("R3_3_EVIDENCE_REQUIRED", "StandardTestCase must carry evidence requirements")
        if not self.oracle_contract.get("business_property") or not self.oracle_contract.get("observation_fields"):
            raise R33Error("R3_3_ORACLE_REQUIRED", "StandardTestCase oracle contract is incomplete")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tc_id": self.tc_id, "case_version_id": self.case_version_id, "version": self.version,
            "lifecycle_status": self.lifecycle_status, "strategy_version_id": self.strategy_version_id,
            "test_point_id": self.test_point_id, "batch_id": self.batch_id,
            "coverage_obligation_refs": list(self.coverage_obligation_refs), "requirement_id": self.requirement_id,
            "sst_id": self.sst_id, "design_refs": list(self.design_refs), "code_refs": list(self.code_refs),
            "change_impact_refs": list(self.change_impact_refs), "reconciliation_semantics": list(self.reconciliation_semantics),
            "risk_refs": list(self.risk_refs), "layer_id": self.layer_id, "layer_profile_version": self.layer_profile_version,
            "case_type": self.case_type, "priority": self.priority, "risk": self.risk.to_dict(),
            "source_context": _json(self.source_context), "objective": self.objective, "title": self.title,
            "preconditions": [_json(item) for item in self.preconditions], "test_data": [_json(item) for item in self.test_data],
            "environment_and_boundary": _json(self.environment_and_boundary),
            "steps": [_json(item) for item in self.steps], "expected_results": [_json(item) for item in self.expected_results],
            "postconditions": [_json(item) for item in self.postconditions], "oracle_contract": _json(self.oracle_contract),
            "evidence_requirements": [_json(item) for item in self.evidence_requirements],
            "execution_profile": _json(self.execution_profile),
            "automation_mapping_refs": list(self.automation_mapping_refs), "specification_status": self.specification_status,
            "source_provenance": list(self.source_provenance), "evidence_refs": list(self.evidence_refs),
            "supersedes_case_version_id": self.supersedes_case_version_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StandardTestCase":
        return cls(
            tc_id=value["tc_id"], case_version_id=value["case_version_id"], version=value["version"],
            lifecycle_status=value["lifecycle_status"], strategy_version_id=value["strategy_version_id"],
            test_point_id=value["test_point_id"], batch_id=value["batch_id"],
            coverage_obligation_refs=tuple(value.get("coverage_obligation_refs") or ()),
            requirement_id=value.get("requirement_id"), sst_id=value.get("sst_id"),
            design_refs=tuple(value.get("design_refs") or ()), code_refs=tuple(value.get("code_refs") or ()),
            change_impact_refs=tuple(value.get("change_impact_refs") or ()),
            reconciliation_semantics=tuple(value.get("reconciliation_semantics") or ()),
            risk_refs=tuple(value.get("risk_refs") or ()), layer_id=value["layer_id"],
            layer_profile_version=value["layer_profile_version"], case_type=value["case_type"],
            priority=value["priority"], risk=RiskVector.from_dict(value["risk"]),
            source_context=value.get("source_context") or {}, objective=value["objective"], title=value["title"],
            preconditions=tuple(value.get("preconditions") or ()), test_data=tuple(value.get("test_data") or ()),
            environment_and_boundary=value.get("environment_and_boundary") or {},
            steps=tuple(value.get("steps") or ()), expected_results=tuple(value.get("expected_results") or ()),
            postconditions=tuple(value.get("postconditions") or ()), oracle_contract=value.get("oracle_contract") or {},
            evidence_requirements=tuple(value.get("evidence_requirements") or ()),
            execution_profile=value.get("execution_profile") or {},
            automation_mapping_refs=tuple(value.get("automation_mapping_refs") or ()),
            specification_status=value["specification_status"],
            source_provenance=tuple(value.get("source_provenance") or ()),
            evidence_refs=tuple(value.get("evidence_refs") or ()),
            supersedes_case_version_id=value.get("supersedes_case_version_id"),
        )


@dataclass(frozen=True)
class AutomationMapping:
    mapping_id: str
    case_version_id: str
    automation_asset_ref: str
    automation_method_refs: tuple[str, ...]
    implementation_type: str
    adapter_ref: str | None
    provider_ref: str | None
    mapping_relation: str
    mapping_state: str
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    mapping_policy_version: str

    def __post_init__(self) -> None:
        for name in ("mapping_id", "case_version_id", "automation_asset_ref", "implementation_type", "mapping_relation", "mapping_state", "mapping_policy_version"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "automation_method_refs", _text_tuple(self.automation_method_refs, "automation_method_refs", allow_empty=False))
        object.__setattr__(self, "adapter_ref", _optional_text(self.adapter_ref, "adapter_ref"))
        object.__setattr__(self, "provider_ref", _optional_text(self.provider_ref, "provider_ref"))
        if self.mapping_relation not in MAPPING_RELATIONS:
            raise R33Error("R3_3_MAPPING_INVALID", f"invalid mapping_relation: {self.mapping_relation}")
        if self.mapping_state not in MAPPING_STATES:
            raise R33Error("R3_3_MAPPING_INVALID", f"invalid mapping_state: {self.mapping_state}")
        object.__setattr__(self, "source_refs", _text_tuple(self.source_refs, "source_refs"))
        object.__setattr__(self, "evidence_refs", _text_tuple(self.evidence_refs, "evidence_refs"))
 
    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_id": self.mapping_id, "case_version_id": self.case_version_id,
            "automation_asset_ref": self.automation_asset_ref, "automation_method_refs": list(self.automation_method_refs),
            "implementation_type": self.implementation_type, "adapter_ref": self.adapter_ref, "provider_ref": self.provider_ref,
            "mapping_relation": self.mapping_relation, "mapping_state": self.mapping_state,
            "source_refs": list(self.source_refs), "evidence_refs": list(self.evidence_refs),
            "mapping_policy_version": self.mapping_policy_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AutomationMapping":
        return cls(
            mapping_id=value["mapping_id"], case_version_id=value["case_version_id"],
            automation_asset_ref=value["automation_asset_ref"], automation_method_refs=tuple(value.get("automation_method_refs") or ()),
            implementation_type=value["implementation_type"], adapter_ref=value.get("adapter_ref"), provider_ref=value.get("provider_ref"),
            mapping_relation=value["mapping_relation"], mapping_state=value["mapping_state"],
            source_refs=tuple(value.get("source_refs") or ()), evidence_refs=tuple(value.get("evidence_refs") or ()),
            mapping_policy_version=value["mapping_policy_version"],
        )


@dataclass(frozen=True)
class CaseBatch:
    batch_id: str
    strategy_version_id: str
    batch_order: int
    batch_cursor: str
    batch_limit: int
    batch_status: str
    designer_session_ref: str | None
    test_point_refs: tuple[str, ...]
    standard_case_version_refs: tuple[str, ...]
    automation_mapping_refs: tuple[str, ...]
    blocked_point_refs: tuple[str, ...]
    next_cursor: str | None
    group_key: str
    source_evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("batch_id", "strategy_version_id", "group_key"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.batch_cursor, str):
            raise R33Error("R3_3_BATCH_INVALID", "batch_cursor must be a string")
        object.__setattr__(self, "batch_order", _non_negative(self.batch_order, "batch_order"))
        object.__setattr__(self, "batch_limit", _positive(self.batch_limit, "batch_limit"))
        if self.batch_status not in BATCH_STATUSES:
            raise R33Error("R3_3_BATCH_INVALID", f"invalid batch status: {self.batch_status}")
        object.__setattr__(self, "designer_session_ref", _optional_text(self.designer_session_ref, "designer_session_ref"))
        for name in ("test_point_refs", "standard_case_version_refs", "automation_mapping_refs", "blocked_point_refs", "source_evidence_refs"):
            object.__setattr__(self, name, _text_tuple(getattr(self, name), name))
        object.__setattr__(self, "next_cursor", _optional_text(self.next_cursor, "next_cursor"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id, "strategy_version_id": self.strategy_version_id,
            "batch_order": self.batch_order, "batch_cursor": self.batch_cursor,
            "batch_limit": self.batch_limit, "batch_status": self.batch_status,
            "designer_session_ref": self.designer_session_ref, "test_point_refs": list(self.test_point_refs),
            "standard_case_version_refs": list(self.standard_case_version_refs),
            "automation_mapping_refs": list(self.automation_mapping_refs),
            "blocked_point_refs": list(self.blocked_point_refs), "next_cursor": self.next_cursor,
            "group_key": self.group_key, "source_evidence_refs": list(self.source_evidence_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CaseBatch":
        return cls(
            batch_id=value["batch_id"], strategy_version_id=value["strategy_version_id"],
            batch_order=value["batch_order"], batch_cursor=value["batch_cursor"],
            batch_limit=value["batch_limit"], batch_status=value["batch_status"],
            designer_session_ref=value.get("designer_session_ref"),
            test_point_refs=tuple(value.get("test_point_refs") or ()),
            standard_case_version_refs=tuple(value.get("standard_case_version_refs") or ()),
            automation_mapping_refs=tuple(value.get("automation_mapping_refs") or ()),
            blocked_point_refs=tuple(value.get("blocked_point_refs") or ()),
            next_cursor=value.get("next_cursor"), group_key=value["group_key"],
            source_evidence_refs=tuple(value.get("source_evidence_refs") or ()),
        )


@dataclass(frozen=True)
class TestStrategy:
    strategy_id: str
    strategy_version_id: str
    mission_id: str
    scope_identity: str
    r3_1_reference: R31Reference
    r3_2_reference: R32Reference
    risk_bundle_reference: Mapping[str, Any]
    risk_policy_version: str
    risk_policy_digest: str
    layer_taxonomy_version: str
    profile_catalog_digest: str
    case_design_policy_version: str
    batching_policy_version: str
    source_member_counts: Mapping[str, int]
    selected_profile_counts: Mapping[str, int]
    decision_counts: Mapping[str, int]
    coverage_obligation_count: int
    change_impact_obligation_count: int
    test_point_count: int
    standard_case_count: int
    automation_mapping_count: int
    automation_method_count: int
    strategy_status: str
    strategy_fingerprint: str
    idempotency_key: str
    requested_by: Mapping[str, str]
    correlation_id: str
    source_provenance: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    automation_inventory_ref: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        for name in ("strategy_id", "strategy_version_id", "mission_id", "scope_identity", "risk_policy_version", "risk_policy_digest", "layer_taxonomy_version", "profile_catalog_digest", "case_design_policy_version", "batching_policy_version", "strategy_fingerprint", "idempotency_key", "correlation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.strategy_status not in STRATEGY_STATUSES:
            raise R33Error("R3_3_STRATEGY_STATUS_INVALID", f"invalid strategy status: {self.strategy_status}")
        if not isinstance(self.r3_1_reference, R31Reference) or not isinstance(self.r3_2_reference, R32Reference):
            raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "strategy source references are invalid")
        for name in ("risk_bundle_reference",):
            object.__setattr__(self, name, _copy(_mapping(getattr(self, name), name)))
        object.__setattr__(self, "automation_inventory_ref", None if self.automation_inventory_ref is None else _copy(_mapping(self.automation_inventory_ref, "automation_inventory_ref")))
        for name in ("source_member_counts", "selected_profile_counts", "decision_counts"):
            values = {str(key): _non_negative(value, f"{name}.{key}") for key, value in _mapping(getattr(self, name), name).items()}
            object.__setattr__(self, name, values)
        for name in ("coverage_obligation_count", "change_impact_obligation_count", "test_point_count", "standard_case_count", "automation_mapping_count", "automation_method_count"):
            object.__setattr__(self, name, _non_negative(getattr(self, name), name))
        object.__setattr__(self, "requested_by", _copy(_mapping(self.requested_by, "requested_by")))
        object.__setattr__(self, "source_provenance", _text_tuple(self.source_provenance, "source_provenance"))
        object.__setattr__(self, "evidence_refs", _text_tuple(self.evidence_refs, "evidence_refs"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id, "strategy_version_id": self.strategy_version_id,
            "mission_id": self.mission_id, "scope_identity": self.scope_identity,
            "r3_1_reference": self.r3_1_reference.to_dict(), "r3_2_reference": self.r3_2_reference.to_dict(),
            "risk_bundle_reference": _json(self.risk_bundle_reference),
            "risk_policy_version": self.risk_policy_version, "risk_policy_digest": self.risk_policy_digest,
            "layer_taxonomy_version": self.layer_taxonomy_version, "profile_catalog_digest": self.profile_catalog_digest,
            "case_design_policy_version": self.case_design_policy_version, "batching_policy_version": self.batching_policy_version,
            "source_member_counts": dict(self.source_member_counts), "selected_profile_counts": dict(self.selected_profile_counts),
            "decision_counts": dict(self.decision_counts), "coverage_obligation_count": self.coverage_obligation_count,
            "change_impact_obligation_count": self.change_impact_obligation_count, "test_point_count": self.test_point_count,
            "standard_case_count": self.standard_case_count, "automation_mapping_count": self.automation_mapping_count,
            "automation_method_count": self.automation_method_count, "strategy_status": self.strategy_status,
            "strategy_fingerprint": self.strategy_fingerprint, "idempotency_key": self.idempotency_key,
            "requested_by": dict(self.requested_by), "correlation_id": self.correlation_id,
            "source_provenance": list(self.source_provenance), "evidence_refs": list(self.evidence_refs),
            "automation_inventory_ref": _json(self.automation_inventory_ref),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TestStrategy":
        return cls(
            strategy_id=value["strategy_id"], strategy_version_id=value["strategy_version_id"],
            mission_id=value["mission_id"], scope_identity=value["scope_identity"],
            r3_1_reference=R31Reference.from_dict(value["r3_1_reference"]),
            r3_2_reference=R32Reference.from_dict(value["r3_2_reference"]),
            risk_bundle_reference=value.get("risk_bundle_reference") or {},
            risk_policy_version=value["risk_policy_version"], risk_policy_digest=value["risk_policy_digest"],
            layer_taxonomy_version=value["layer_taxonomy_version"], profile_catalog_digest=value["profile_catalog_digest"],
            case_design_policy_version=value["case_design_policy_version"], batching_policy_version=value["batching_policy_version"],
            source_member_counts=value.get("source_member_counts") or {}, selected_profile_counts=value.get("selected_profile_counts") or {},
            decision_counts=value.get("decision_counts") or {}, coverage_obligation_count=value["coverage_obligation_count"],
            change_impact_obligation_count=value["change_impact_obligation_count"], test_point_count=value["test_point_count"],
            standard_case_count=value["standard_case_count"], automation_mapping_count=value["automation_mapping_count"],
            automation_method_count=value["automation_method_count"], strategy_status=value["strategy_status"],
            strategy_fingerprint=value["strategy_fingerprint"], idempotency_key=value["idempotency_key"],
            requested_by=value["requested_by"], correlation_id=value["correlation_id"],
            source_provenance=tuple(value.get("source_provenance") or ()), evidence_refs=tuple(value.get("evidence_refs") or ()),
            automation_inventory_ref=value.get("automation_inventory_ref"),
        )


@dataclass(frozen=True)
class R33ReuseReference:
    reuse_id: str
    strategy_version_id: str
    strategy_fingerprint: str
    idempotency_key: str
    batch_id: str | None
    created_seq: int
    created_at: str
    correlation_id: str

    def __post_init__(self) -> None:
        for name in ("reuse_id", "strategy_version_id", "strategy_fingerprint", "idempotency_key", "created_at", "correlation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "batch_id", _optional_text(self.batch_id, "batch_id"))
        object.__setattr__(self, "created_seq", _positive(self.created_seq, "created_seq"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "reuse_id": self.reuse_id, "strategy_version_id": self.strategy_version_id,
            "strategy_fingerprint": self.strategy_fingerprint, "idempotency_key": self.idempotency_key,
            "batch_id": self.batch_id, "created_seq": self.created_seq, "created_at": self.created_at,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R33ReuseReference":
        return cls(
            reuse_id=value["reuse_id"], strategy_version_id=value["strategy_version_id"],
            strategy_fingerprint=value["strategy_fingerprint"], idempotency_key=value["idempotency_key"],
            batch_id=value.get("batch_id"), created_seq=value["created_seq"], created_at=value["created_at"],
            correlation_id=value["correlation_id"],
        )


@dataclass(frozen=True)
class R33State:
    mission_id: str
    strategies: tuple[TestStrategy, ...] = ()
    test_points: tuple[TestPoint, ...] = ()
    batches: tuple[CaseBatch, ...] = ()
    standard_cases: tuple[StandardTestCase, ...] = ()
    automation_mappings: tuple[AutomationMapping, ...] = ()
    reuses: tuple[R33ReuseReference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        for name, cls in (
            ("strategies", TestStrategy), ("test_points", TestPoint), ("batches", CaseBatch),
            ("standard_cases", StandardTestCase), ("automation_mappings", AutomationMapping),
            ("reuses", R33ReuseReference),
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, cls) for item in values):
                raise R33Error("R3_3_SCHEMA_INVALID", f"{name} must contain immutable typed values")
            field_name = next(iter(cls.__dataclass_fields__))
            ids = [getattr(item, field_name) for item in values]
            if len(ids) != len(set(ids)):
                raise R33Error("R3_3_IDENTITY_CONFLICT", f"{name} identities must be unique")

    def strategy(self, fingerprint: str) -> TestStrategy | None:
        return next((item for item in self.strategies if item.strategy_fingerprint == fingerprint), None)

    def strategy_by_id(self, strategy_version_id: str) -> TestStrategy | None:
        return next((item for item in self.strategies if item.strategy_version_id == strategy_version_id), None)

    def batch(self, batch_id: str) -> CaseBatch | None:
        return next((item for item in self.batches if item.batch_id == batch_id), None)

    def reuse(self, idempotency_key: str, batch_id: str | None = None) -> R33ReuseReference | None:
        return next((item for item in self.reuses if item.idempotency_key == idempotency_key and (batch_id is None or item.batch_id == batch_id)), None)

    def points_for(self, strategy_version_id: str) -> tuple[TestPoint, ...]:
        return tuple(sorted((item for item in self.test_points if item.strategy_version_id == strategy_version_id), key=lambda item: item.deterministic_order))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "strategies": [item.to_dict() for item in sorted(self.strategies, key=lambda item: item.strategy_version_id)],
            "test_points": [item.to_dict() for item in sorted(self.test_points, key=lambda item: item.point_id)],
            "batches": [item.to_dict() for item in sorted(self.batches, key=lambda item: item.batch_id)],
            "standard_cases": [item.to_dict() for item in sorted(self.standard_cases, key=lambda item: item.case_version_id)],
            "automation_mappings": [item.to_dict() for item in sorted(self.automation_mappings, key=lambda item: item.mapping_id)],
            "reuses": [item.to_dict() for item in sorted(self.reuses, key=lambda item: item.reuse_id)],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R33State":
        return cls(
            mission_id=value["mission_id"],
            strategies=tuple(TestStrategy.from_dict(item) for item in value.get("strategies") or ()),
            test_points=tuple(TestPoint.from_dict(item) for item in value.get("test_points") or ()),
            batches=tuple(CaseBatch.from_dict(item) for item in value.get("batches") or ()),
            standard_cases=tuple(StandardTestCase.from_dict(item) for item in value.get("standard_cases") or ()),
            automation_mappings=tuple(AutomationMapping.from_dict(item) for item in value.get("automation_mappings") or ()),
            reuses=tuple(R33ReuseReference.from_dict(item) for item in value.get("reuses") or ()),
        )


@dataclass(frozen=True)
class StrategyRequest:
    mission_id: str
    scope_identity: str
    r3_1_reference: R31Reference
    r3_2_reference: R32Reference
    risk_inputs: Mapping[str, Any]
    risk_policy_version: str
    layer_taxonomy_version: str
    case_design_policy_version: str
    batching_policy_version: str
    automation_inventory_ref: Mapping[str, Any] | None
    idempotency_key: str
    requested_by: Mapping[str, str]
    correlation_id: str

    def __post_init__(self) -> None:
        for name in ("mission_id", "scope_identity", "risk_policy_version", "layer_taxonomy_version", "case_design_policy_version", "batching_policy_version", "idempotency_key", "correlation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.r3_1_reference, R31Reference) or not isinstance(self.r3_2_reference, R32Reference):
            raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "request source references are invalid")
        object.__setattr__(self, "risk_inputs", _copy(_mapping(self.risk_inputs, "risk_inputs")))
        object.__setattr__(self, "automation_inventory_ref", None if self.automation_inventory_ref is None else _copy(_mapping(self.automation_inventory_ref, "automation_inventory_ref")))
        actor = _mapping(self.requested_by, "requested_by")
        object.__setattr__(self, "requested_by", {"type": _text(actor.get("type"), "requested_by.type"), "id": _text(actor.get("id"), "requested_by.id")})

    @classmethod
    def from_payload(cls, value: Mapping[str, Any], *, command_mission_id: str | None = None, correlation_id: str | None = None) -> "StrategyRequest":
        payload = _mapping(value, "strategy request")
        required = {
            "mission_id", "scope_identity", "r3_1_reference", "r3_2_reference", "risk_inputs",
            "risk_policy_version", "layer_taxonomy_version", "case_design_policy_version",
            "batching_policy_version", "automation_inventory_ref", "idempotency_key", "requested_by",
        }
        if set(payload) != required:
            raise R33Error("R3_3_SCHEMA_INVALID", "strategy request contains unknown or missing fields")
        result = cls(
            mission_id=payload["mission_id"], scope_identity=payload["scope_identity"],
            r3_1_reference=R31Reference.from_dict(payload["r3_1_reference"]),
            r3_2_reference=R32Reference.from_dict(payload["r3_2_reference"]),
            risk_inputs=payload["risk_inputs"], risk_policy_version=payload["risk_policy_version"],
            layer_taxonomy_version=payload["layer_taxonomy_version"],
            case_design_policy_version=payload["case_design_policy_version"],
            batching_policy_version=payload["batching_policy_version"],
            automation_inventory_ref=payload.get("automation_inventory_ref"),
            idempotency_key=payload["idempotency_key"], requested_by=payload["requested_by"],
            correlation_id=correlation_id or payload["idempotency_key"],
        )
        if command_mission_id is not None and result.mission_id != command_mission_id:
            raise R33Error("R3_3_MISSION_IDENTITY_MISMATCH", "strategy request mission differs from command mission")
        return result

    def to_payload(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id, "scope_identity": self.scope_identity,
            "r3_1_reference": self.r3_1_reference.to_dict(), "r3_2_reference": self.r3_2_reference.to_dict(),
            "risk_inputs": _json(self.risk_inputs), "risk_policy_version": self.risk_policy_version,
            "layer_taxonomy_version": self.layer_taxonomy_version, "case_design_policy_version": self.case_design_policy_version,
            "batching_policy_version": self.batching_policy_version,
            "automation_inventory_ref": _json(self.automation_inventory_ref),
            "idempotency_key": self.idempotency_key, "requested_by": dict(self.requested_by),
        }


@dataclass(frozen=True)
class BatchDesignRequest:
    strategy_version_id: str
    batch_id: str | None
    expected_strategy_fingerprint: str
    batch_cursor: str
    batch_limit: int
    designer_session_ref: str | None
    idempotency_key: str
    correlation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_version_id", _text(self.strategy_version_id, "strategy_version_id"))
        object.__setattr__(self, "batch_id", _optional_text(self.batch_id, "batch_id"))
        object.__setattr__(self, "expected_strategy_fingerprint", _text(self.expected_strategy_fingerprint, "expected_strategy_fingerprint"))
        object.__setattr__(self, "batch_cursor", self.batch_cursor if isinstance(self.batch_cursor, str) else str(self.batch_cursor))
        object.__setattr__(self, "batch_limit", _positive(self.batch_limit, "batch_limit"))
        object.__setattr__(self, "designer_session_ref", _optional_text(self.designer_session_ref, "designer_session_ref"))
        object.__setattr__(self, "idempotency_key", _text(self.idempotency_key, "idempotency_key"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))

    @classmethod
    def from_payload(cls, value: Mapping[str, Any], *, command_mission_id: str | None = None, correlation_id: str | None = None) -> "BatchDesignRequest":
        payload = _mapping(value, "batch design request")
        required = {
            "strategy_version_id", "batch_id", "expected_strategy_fingerprint", "batch_cursor",
            "batch_limit", "designer_session_ref", "idempotency_key",
        }
        if set(payload) != required:
            raise R33Error("R3_3_SCHEMA_INVALID", "batch design request contains unknown or missing fields")
        return cls(
            strategy_version_id=payload["strategy_version_id"], batch_id=payload.get("batch_id"),
            expected_strategy_fingerprint=payload["expected_strategy_fingerprint"],
            batch_cursor=payload["batch_cursor"], batch_limit=payload["batch_limit"],
            designer_session_ref=payload.get("designer_session_ref"),
            idempotency_key=payload["idempotency_key"], correlation_id=correlation_id or payload["idempotency_key"],
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "strategy_version_id": self.strategy_version_id, "batch_id": self.batch_id,
            "expected_strategy_fingerprint": self.expected_strategy_fingerprint,
            "batch_cursor": self.batch_cursor, "batch_limit": self.batch_limit,
            "designer_session_ref": self.designer_session_ref, "idempotency_key": self.idempotency_key,
        }
