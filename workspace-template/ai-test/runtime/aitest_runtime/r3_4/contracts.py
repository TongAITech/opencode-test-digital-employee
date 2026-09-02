from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError, canonical_sha256


EXTENSION_ID = "r3_4_case_review_execution_readiness_oracle"
EXTENSION_VERSION = "1"
R34_SCHEMA_VERSION = 1

BUILD_REVIEW_CONTEXT = "R34_BUILD_REVIEW_CONTEXT"
REVIEW_CASE = "R34_REVIEW_CASE"
ASSESS_EXECUTION_READINESS = "R34_ASSESS_EXECUTION_READINESS"
RESOLVE_PRECONDITION = "R34_RESOLVE_PRECONDITION"
RESOLVE_TEST_DATA = "R34_RESOLVE_TEST_DATA"
APPROVE_ORACLE_SPECIFICATION = "R34_APPROVE_ORACLE_SPECIFICATION"
REGISTER_CASE_EXECUTION_ATTEMPT = "R34_REGISTER_CASE_EXECUTION_ATTEMPT"
EVALUATE_ORACLE = "R34_EVALUATE_ORACLE"
RECORD_TEST_RESULT = "R34_RECORD_TEST_RESULT"

REVIEWER_CONTEXT_BUILT = "r3.4.reviewer_context_built.v1"
CASE_REVIEWED = "r3.4.case_reviewed.v1"
EXECUTION_READINESS_ASSESSED = "r3.4.execution_readiness_assessed.v1"
PRECONDITION_RESOLVED = "r3.4.precondition_resolved.v1"
TEST_DATA_RESOLVED = "r3.4.test_data_resolved.v1"
ORACLE_SPECIFICATION_APPROVED = "r3.4.oracle_specification_approved.v1"
CASE_EXECUTION_ATTEMPT_REGISTERED = "r3.4.case_execution_attempt_registered.v1"
ORACLE_EVALUATED = "r3.4.oracle_evaluated.v1"
TEST_RESULT_RECORDED = "r3.4.test_result_recorded.v1"
SEMANTIC_REUSE = "r3.4.semantic_reuse.v1"

COMMAND_TYPES = frozenset({
    BUILD_REVIEW_CONTEXT, REVIEW_CASE, ASSESS_EXECUTION_READINESS,
    RESOLVE_PRECONDITION, RESOLVE_TEST_DATA, APPROVE_ORACLE_SPECIFICATION,
    REGISTER_CASE_EXECUTION_ATTEMPT, EVALUATE_ORACLE, RECORD_TEST_RESULT,
})
EVENT_TYPES = frozenset({
    REVIEWER_CONTEXT_BUILT, CASE_REVIEWED, EXECUTION_READINESS_ASSESSED,
    PRECONDITION_RESOLVED, TEST_DATA_RESOLVED, ORACLE_SPECIFICATION_APPROVED,
    CASE_EXECUTION_ATTEMPT_REGISTERED, ORACLE_EVALUATED, TEST_RESULT_RECORDED,
    SEMANTIC_REUSE,
})

REVIEW_DIMENSIONS = ("TRACEABILITY", "QUALITY", "COVERAGE", "ORACLE", "EVIDENCE")
REVIEW_DIMENSION_STATES = frozenset({"PASS", "FAIL", "BLOCKED", "INCONCLUSIVE"})
REVIEW_STATUSES = frozenset({"PENDING", "IN_REVIEW", "APPROVED", "REJECTED", "CHANGES_REQUESTED", "BLOCKED"})
READINESS_STATUSES = frozenset({"READY", "NOT_READY", "BLOCKED", "EXPIRED", "REASSESS_REQUIRED"})
RESOLUTION_STATES = frozenset({"RESOLVED", "UNRESOLVED", "BLOCKED", "CONFLICTED", "EXPIRED", "NOT_APPLICABLE"})
DATA_RESOLUTION_STATES = frozenset({"RESOLVED", "UNAVAILABLE", "BLOCKED", "CONFLICTED", "EXPIRED", "NOT_APPLICABLE"})
EXECUTION_STATUSES = frozenset({"CREATED", "RUNNING", "EXECUTION_SUCCEEDED", "EXECUTION_FAILED", "BLOCKED", "ABANDONED", "CANCELLED"})
ORACLE_DECISIONS = frozenset({"PASS", "FAIL", "INCONCLUSIVE", "EVIDENCE_INSUFFICIENT", "BLOCKED", "NOT_EVALUATED"})
BUSINESS_VALIDATIONS = frozenset({"PASS", "FAIL", "INCONCLUSIVE", "NOT_EVALUATED"})
RESULT_STATUSES = frozenset({"PASS", "FAIL", "BLOCKED", "INCONCLUSIVE", "EVIDENCE_INSUFFICIENT", "ERROR", "NOT_EXECUTED"})
EVIDENCE_SUFFICIENCY = frozenset({"SUFFICIENT", "INSUFFICIENT", "CONFLICTED"})
RECONCILIATION_SEMANTICS = frozenset({
    "OVERLAP", "REQUIREMENT_ONLY", "CHANGE_ONLY", "REQUIREMENT_CODE_GAP",
    "UNMAPPED", "PARTIAL", "UNCOVERED",
})


class R34Error(RuntimeError):
    """R3.4 contract, lineage, oracle and projection error."""


def _text(value: Any, name: str, code: str = "R3_4_SCHEMA_INVALID") -> str:
    if not isinstance(value, str) or not value.strip():
        raise R34Error(code, f"{name} must be a non-empty string")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R34Error("R3_4_SCHEMA_INVALID", f"{name} must be an object")
    return {str(key): _copy(item) for key, item in value.items()}


def _array(value: Any, name: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise R34Error("R3_4_SCHEMA_INVALID", f"{name} must be an array")
    return list(value)


def _copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_copy(item) for item in value)
    return value


def _json(value: Any) -> Any:
    if is_dataclass(value):
        return _json(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _text_tuple(value: Any, name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    values = tuple(_text(item, f"{name}[]") for item in _array(value, name))
    if not allow_empty and not values:
        raise R34Error("R3_4_SCHEMA_INVALID", f"{name} must not be empty")
    return values


def _mapping_tuple(value: Any, name: str) -> tuple[Mapping[str, Any], ...]:
    return tuple(_mapping(item, f"{name}[]") for item in _array(value, name))


def _status(value: Any, allowed: frozenset[str], name: str) -> str:
    value = _text(value, name)
    if value not in allowed:
        raise R34Error("R3_4_STATUS_INVALID", f"unsupported {name}: {value}")
    return value


def _fingerprint(value: Any, name: str) -> str:
    return _text(value, name)


def _created_seq(value: Any, name: str = "created_seq") -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise R34Error("R3_4_SCHEMA_INVALID", f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class R31Reference:
    derivation_version_id: str
    snapshot_id: str
    derivation_fingerprint: str
    source_bundle_digest: str
    provenance_bundle_digest: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _text(getattr(self, name), name))

    def to_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R31Reference":
        return cls(**{name: value[name] for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class R32Reference:
    derivation_version_id: str
    derivation_fingerprint: str
    reconciliation_id: str
    compare_identity_digest: str
    provider_envelope_digest: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _text(getattr(self, name), name))

    def to_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R32Reference":
        return cls(**{name: value[name] for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class R33CaseReference:
    strategy_version_id: str
    test_point_id: str
    tc_id: str
    case_version_id: str
    case_version_digest: str
    source_provenance_digest: str
    evidence_requirement_digest: str
    design_oracle_digest: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _text(getattr(self, name), name))

    def to_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R33CaseReference":
        return cls(**{name: value[name] for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class ReviewerContextSnapshot:
    reviewer_context_id: str
    version: int
    mission_id: str
    scope_identity: str
    r3_1_reference: R31Reference
    r3_2_reference: R32Reference
    r3_3_case_reference: R33CaseReference
    source_truth_refs: Mapping[str, Any]
    coverage_obligation_refs: tuple[str, ...]
    case_version_snapshot: Mapping[str, Any]
    review_policy_version: str
    review_policy_digest: str
    review_policy_snapshot: Mapping[str, Any]
    reviewer_context_digest: str
    source_provenance: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    created_seq: int = 0
    created_at: str = ""
    correlation_id: str = ""

    def __post_init__(self) -> None:
        for name in ("reviewer_context_id", "mission_id", "scope_identity", "review_policy_version", "review_policy_digest", "reviewer_context_digest", "created_at", "correlation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise R34Error("R3_4_SCHEMA_INVALID", "version must be positive")
        if not isinstance(self.r3_1_reference, R31Reference) or not isinstance(self.r3_2_reference, R32Reference) or not isinstance(self.r3_3_case_reference, R33CaseReference):
            raise R34Error("R3_4_SCHEMA_INVALID", "upstream references are invalid")
        object.__setattr__(self, "source_truth_refs", _mapping(self.source_truth_refs, "source_truth_refs"))
        object.__setattr__(self, "coverage_obligation_refs", _text_tuple(self.coverage_obligation_refs, "coverage_obligation_refs", allow_empty=False))
        object.__setattr__(self, "case_version_snapshot", _mapping(self.case_version_snapshot, "case_version_snapshot"))
        object.__setattr__(self, "review_policy_snapshot", _mapping(self.review_policy_snapshot, "review_policy_snapshot"))
        object.__setattr__(self, "source_provenance", _text_tuple(self.source_provenance, "source_provenance"))
        object.__setattr__(self, "evidence_refs", _text_tuple(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "created_seq", _created_seq(self.created_seq))

    def to_dict(self) -> dict[str, Any]:
        return {name: _json(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReviewerContextSnapshot":
        return cls(
            reviewer_context_id=value["reviewer_context_id"], version=value["version"], mission_id=value["mission_id"], scope_identity=value["scope_identity"],
            r3_1_reference=R31Reference.from_dict(value["r3_1_reference"]), r3_2_reference=R32Reference.from_dict(value["r3_2_reference"]),
            r3_3_case_reference=R33CaseReference.from_dict(value["r3_3_case_reference"]), source_truth_refs=value["source_truth_refs"],
            coverage_obligation_refs=tuple(value["coverage_obligation_refs"]), case_version_snapshot=value["case_version_snapshot"],
            review_policy_version=value["review_policy_version"], review_policy_digest=value["review_policy_digest"],
            review_policy_snapshot=value["review_policy_snapshot"], reviewer_context_digest=value["reviewer_context_digest"],
            source_provenance=tuple(value.get("source_provenance") or ()), evidence_refs=tuple(value.get("evidence_refs") or ()),
            created_seq=value.get("created_seq", 0), created_at=value["created_at"], correlation_id=value["correlation_id"],
        )


@dataclass(frozen=True)
class CaseReview:
    case_review_id: str
    review_version: int
    mission_id: str
    scope_identity: str
    case_version_id: str
    case_version_digest: str
    tc_id: str
    strategy_version_id: str
    test_point_id: str
    r3_1_reference: R31Reference
    r3_2_reference: R32Reference
    r3_3_case_reference: R33CaseReference
    reviewer_context_id: str
    reviewer_context_digest: str
    review_policy_version: str
    review_policy_digest: str
    reviewer_session_ref: str | None
    dimension_assessments: Mapping[str, str]
    findings: tuple[Mapping[str, Any], ...]
    coverage_semantics: tuple[str, ...]
    unmapped_or_partial_obligations: tuple[str, ...]
    oracle_specification_candidate_digest: str
    evidence_requirement_set_digest: str
    review_status: str
    approved_at: str | None
    approved_by: Mapping[str, str] | None
    source_provenance: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    review_fingerprint: str
    idempotency_key: str
    correlation_id: str
    created_seq: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        for name in ("case_review_id", "mission_id", "scope_identity", "case_version_id", "case_version_digest", "tc_id", "strategy_version_id", "test_point_id", "reviewer_context_id", "reviewer_context_digest", "review_policy_version", "review_policy_digest", "oracle_specification_candidate_digest", "evidence_requirement_set_digest", "review_fingerprint", "idempotency_key", "correlation_id", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.review_version, int) or isinstance(self.review_version, bool) or self.review_version < 1:
            raise R34Error("R3_4_SCHEMA_INVALID", "review_version must be positive")
        for name, cls in (("r3_1_reference", R31Reference), ("r3_2_reference", R32Reference), ("r3_3_case_reference", R33CaseReference)):
            if not isinstance(getattr(self, name), cls):
                raise R34Error("R3_4_SCHEMA_INVALID", f"{name} is invalid")
        object.__setattr__(self, "reviewer_session_ref", _optional_text(self.reviewer_session_ref, "reviewer_session_ref"))
        dimensions = _mapping(self.dimension_assessments, "dimension_assessments")
        if set(dimensions) != set(REVIEW_DIMENSIONS) or any(value not in REVIEW_DIMENSION_STATES for value in dimensions.values()):
            raise R34Error("R3_4_REVIEW_DIMENSION_INVALID", "all five review dimensions must have a valid state")
        object.__setattr__(self, "dimension_assessments", dimensions)
        object.__setattr__(self, "findings", _mapping_tuple(self.findings, "findings"))
        semantics = _text_tuple(self.coverage_semantics, "coverage_semantics")
        if any(item not in RECONCILIATION_SEMANTICS for item in semantics):
            raise R34Error("R3_4_COVERAGE_SEMANTICS_INVALID", "unsupported coverage semantic")
        object.__setattr__(self, "coverage_semantics", semantics)
        object.__setattr__(self, "unmapped_or_partial_obligations", _text_tuple(self.unmapped_or_partial_obligations, "unmapped_or_partial_obligations"))
        object.__setattr__(self, "review_status", _status(self.review_status, REVIEW_STATUSES, "review_status"))
        object.__setattr__(self, "approved_at", _optional_text(self.approved_at, "approved_at"))
        if self.approved_by is not None:
            actor = _mapping(self.approved_by, "approved_by")
            object.__setattr__(self, "approved_by", {"type": _text(actor.get("type"), "approved_by.type"), "id": _text(actor.get("id"), "approved_by.id")})
        object.__setattr__(self, "source_provenance", _text_tuple(self.source_provenance, "source_provenance"))
        object.__setattr__(self, "evidence_refs", _text_tuple(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "created_seq", _created_seq(self.created_seq))

    def to_dict(self) -> dict[str, Any]:
        return {name: _json(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CaseReview":
        return cls(
            case_review_id=value["case_review_id"], review_version=value["review_version"], mission_id=value["mission_id"], scope_identity=value["scope_identity"],
            case_version_id=value["case_version_id"], case_version_digest=value["case_version_digest"], tc_id=value["tc_id"], strategy_version_id=value["strategy_version_id"], test_point_id=value["test_point_id"],
            r3_1_reference=R31Reference.from_dict(value["r3_1_reference"]), r3_2_reference=R32Reference.from_dict(value["r3_2_reference"]), r3_3_case_reference=R33CaseReference.from_dict(value["r3_3_case_reference"]),
            reviewer_context_id=value["reviewer_context_id"], reviewer_context_digest=value["reviewer_context_digest"], review_policy_version=value["review_policy_version"], review_policy_digest=value["review_policy_digest"], reviewer_session_ref=value.get("reviewer_session_ref"),
            dimension_assessments=value["dimension_assessments"], findings=tuple(value.get("findings") or ()), coverage_semantics=tuple(value.get("coverage_semantics") or ()), unmapped_or_partial_obligations=tuple(value.get("unmapped_or_partial_obligations") or ()),
            oracle_specification_candidate_digest=value["oracle_specification_candidate_digest"], evidence_requirement_set_digest=value["evidence_requirement_set_digest"], review_status=value["review_status"], approved_at=value.get("approved_at"), approved_by=value.get("approved_by"),
            source_provenance=tuple(value.get("source_provenance") or ()), evidence_refs=tuple(value.get("evidence_refs") or ()), review_fingerprint=value["review_fingerprint"], idempotency_key=value["idempotency_key"], correlation_id=value["correlation_id"], created_seq=value.get("created_seq", 0), created_at=value["created_at"],
        )


@dataclass(frozen=True)
class PreconditionRequirement:
    precondition_requirement_id: str
    case_version_id: str
    requirement_kind: str
    condition_expression: str
    expected_state: Mapping[str, Any]
    source_refs: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    evidence_requirement_refs: tuple[str, ...]
    resolution_policy_version: str
    expiry_policy: Mapping[str, Any]
    required: bool = True
    created_seq: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        for name in ("precondition_requirement_id", "case_version_id", "requirement_kind", "condition_expression", "resolution_policy_version", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "expected_state", _mapping(self.expected_state, "expected_state"))
        object.__setattr__(self, "source_refs", _text_tuple(self.source_refs, "source_refs"))
        object.__setattr__(self, "provenance_refs", _text_tuple(self.provenance_refs, "provenance_refs"))
        object.__setattr__(self, "evidence_requirement_refs", _text_tuple(self.evidence_requirement_refs, "evidence_requirement_refs"))
        object.__setattr__(self, "expiry_policy", _mapping(self.expiry_policy, "expiry_policy"))
        if not isinstance(self.required, bool):
            raise R34Error("R3_4_SCHEMA_INVALID", "required must be boolean")
        object.__setattr__(self, "created_seq", _created_seq(self.created_seq))

    def to_dict(self) -> dict[str, Any]:
        return {name: _json(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PreconditionRequirement":
        return cls(**{name: value.get(name, ()) if name in {"source_refs", "provenance_refs", "evidence_requirement_refs"} else value.get(name, {}) if name in {"expected_state", "expiry_policy"} else value[name] for name in cls.__dataclass_fields__ if name not in {"created_seq", "created_at"}} , created_seq=value.get("created_seq", 0), created_at=value.get("created_at", "r3.4"))


@dataclass(frozen=True)
class PreconditionResolution:
    precondition_resolution_id: str
    requirement_id: str
    version: int
    resolution_state: str
    observed_state_ref: str | None
    runtime_fact_refs: tuple[str, ...]
    tool_execution_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    observation_digest: str
    resolved_at: str
    valid_until: str | None
    resolver_session_ref: str | None
    resolution_fingerprint: str
    provenance: tuple[str, ...]
    created_seq: int = 0

    def __post_init__(self) -> None:
        for name in ("precondition_resolution_id", "requirement_id", "observation_digest", "resolved_at", "resolution_fingerprint"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise R34Error("R3_4_SCHEMA_INVALID", "resolution version must be positive")
        object.__setattr__(self, "resolution_state", _status(self.resolution_state, RESOLUTION_STATES, "resolution_state"))
        object.__setattr__(self, "observed_state_ref", _optional_text(self.observed_state_ref, "observed_state_ref"))
        for name in ("runtime_fact_refs", "tool_execution_refs", "evidence_refs", "provenance"):
            object.__setattr__(self, name, _text_tuple(getattr(self, name), name))
        object.__setattr__(self, "valid_until", _optional_text(self.valid_until, "valid_until"))
        object.__setattr__(self, "resolver_session_ref", _optional_text(self.resolver_session_ref, "resolver_session_ref"))
        object.__setattr__(self, "created_seq", _created_seq(self.created_seq))

    def to_dict(self) -> dict[str, Any]:
        return {name: _json(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PreconditionResolution":
        return cls(**{name: tuple(value.get(name) or ()) if name in {"runtime_fact_refs", "tool_execution_refs", "evidence_refs", "provenance"} else value.get(name) for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class TestDataRequirement:
    test_data_requirement_id: str
    case_version_id: str
    data_kind: str
    data_contract: Mapping[str, Any]
    dataset_ref: str | None
    fixture_ref: str | None
    provider_capability_ref: str | None
    classification: str
    masking_policy_version: str
    isolation_policy_version: str
    seed_or_existing_policy: str
    cleanup_policy: str
    source_refs: tuple[str, ...]
    evidence_requirement_refs: tuple[str, ...]
    required: bool = True
    created_seq: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        for name in ("test_data_requirement_id", "case_version_id", "data_kind", "classification", "masking_policy_version", "isolation_policy_version", "seed_or_existing_policy", "cleanup_policy", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "data_contract", _mapping(self.data_contract, "data_contract"))
        for name in ("dataset_ref", "fixture_ref", "provider_capability_ref"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        object.__setattr__(self, "source_refs", _text_tuple(self.source_refs, "source_refs"))
        object.__setattr__(self, "evidence_requirement_refs", _text_tuple(self.evidence_requirement_refs, "evidence_requirement_refs"))
        if not isinstance(self.required, bool):
            raise R34Error("R3_4_SCHEMA_INVALID", "required must be boolean")
        object.__setattr__(self, "created_seq", _created_seq(self.created_seq))

    def to_dict(self) -> dict[str, Any]:
        return {name: _json(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TestDataRequirement":
        return cls(**{name: value.get(name, {}) if name == "data_contract" else tuple(value.get(name) or ()) if name in {"source_refs", "evidence_requirement_refs"} else value[name] for name in cls.__dataclass_fields__ if name not in {"created_seq", "created_at"}}, created_seq=value.get("created_seq", 0), created_at=value.get("created_at", "r3.4"))


@dataclass(frozen=True)
class TestDataResolution:
    test_data_resolution_id: str
    requirement_id: str
    version: int
    resolution_state: str
    resolved_dataset_ref: str | None
    dataset_digest: str | None
    lease_or_scope_ref: str | None
    runtime_fact_refs: tuple[str, ...]
    tool_execution_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    resolved_at: str
    valid_until: str | None
    resolution_fingerprint: str
    provenance: tuple[str, ...]
    created_seq: int = 0

    def __post_init__(self) -> None:
        for name in ("test_data_resolution_id", "requirement_id", "resolved_at", "resolution_fingerprint"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise R34Error("R3_4_SCHEMA_INVALID", "resolution version must be positive")
        object.__setattr__(self, "resolution_state", _status(self.resolution_state, DATA_RESOLUTION_STATES, "resolution_state"))
        for name in ("resolved_dataset_ref", "dataset_digest", "lease_or_scope_ref", "valid_until"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        for name in ("runtime_fact_refs", "tool_execution_refs", "evidence_refs", "provenance"):
            object.__setattr__(self, name, _text_tuple(getattr(self, name), name))
        object.__setattr__(self, "created_seq", _created_seq(self.created_seq))

    def to_dict(self) -> dict[str, Any]:
        return {name: _json(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TestDataResolution":
        return cls(**{name: tuple(value.get(name) or ()) if name in {"runtime_fact_refs", "tool_execution_refs", "evidence_refs", "provenance"} else value.get(name) for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class EvidenceRequirement:
    evidence_requirement_id: str
    set_id: str
    version: int
    case_version_id: str
    case_review_id: str
    oracle_specification_id: str | None
    capture_stage: str
    evidence_type: str
    required: bool
    minimum_verification: str
    observation_fields: tuple[Mapping[str, Any], ...]
    artifact_kind: str
    locator_policy: Mapping[str, Any]
    provenance_policy: Mapping[str, Any]
    source_refs: tuple[str, ...]
    requirement_refs: tuple[str, ...]
    evidence_requirement_fingerprint: str
    created_seq: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        for name in ("evidence_requirement_id", "set_id", "case_version_id", "case_review_id", "capture_stage", "evidence_type", "minimum_verification", "artifact_kind", "evidence_requirement_fingerprint", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise R34Error("R3_4_SCHEMA_INVALID", "evidence requirement version must be positive")
        object.__setattr__(self, "oracle_specification_id", _optional_text(self.oracle_specification_id, "oracle_specification_id"))
        if not isinstance(self.required, bool):
            raise R34Error("R3_4_SCHEMA_INVALID", "required must be boolean")
        object.__setattr__(self, "observation_fields", _mapping_tuple(self.observation_fields, "observation_fields"))
        object.__setattr__(self, "locator_policy", _mapping(self.locator_policy, "locator_policy"))
        object.__setattr__(self, "provenance_policy", _mapping(self.provenance_policy, "provenance_policy"))
        object.__setattr__(self, "source_refs", _text_tuple(self.source_refs, "source_refs"))
        object.__setattr__(self, "requirement_refs", _text_tuple(self.requirement_refs, "requirement_refs"))
        object.__setattr__(self, "created_seq", _created_seq(self.created_seq))

    def to_dict(self) -> dict[str, Any]:
        return {name: _json(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceRequirement":
        return cls(**{name: tuple(value.get(name) or ()) if name in {"observation_fields", "source_refs", "requirement_refs"} else value.get(name, {}) if name in {"locator_policy", "provenance_policy"} else value[name] for name in cls.__dataclass_fields__ if name not in {"created_seq", "created_at"}}, created_seq=value.get("created_seq", 0), created_at=value.get("created_at", "r3.4"))


@dataclass(frozen=True)
class OracleSpecification:
    oracle_specification_id: str
    oracle_version: int
    mission_id: str
    scope_identity: str
    case_version_id: str
    case_version_digest: str
    case_review_id: str
    review_digest: str
    business_property: str
    observation_schema: tuple[Mapping[str, Any], ...]
    pass_condition: str
    fail_condition: str
    insufficient_evidence_condition: str
    allowed_observation_refs: tuple[str, ...]
    evaluation_policy_version: str
    evaluation_policy_digest: str
    evidence_requirement_set_id: str
    evidence_requirement_digest: str
    source_refs: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    approved_by: Mapping[str, str]
    approved_at: str
    oracle_fingerprint: str
    immutability_guard_digest: str
    created_seq: int = 0

    def __post_init__(self) -> None:
        for name in ("oracle_specification_id", "mission_id", "scope_identity", "case_version_id", "case_version_digest", "case_review_id", "review_digest", "business_property", "pass_condition", "fail_condition", "insufficient_evidence_condition", "evaluation_policy_version", "evaluation_policy_digest", "evidence_requirement_set_id", "evidence_requirement_digest", "oracle_fingerprint", "immutability_guard_digest", "approved_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.oracle_version, int) or isinstance(self.oracle_version, bool) or self.oracle_version < 1:
            raise R34Error("R3_4_SCHEMA_INVALID", "oracle_version must be positive")
        object.__setattr__(self, "observation_schema", _mapping_tuple(self.observation_schema, "observation_schema"))
        if not self.observation_schema:
            raise R34Error("R3_4_ORACLE_REQUIRED", "observation_schema must not be empty")
        object.__setattr__(self, "allowed_observation_refs", _text_tuple(self.allowed_observation_refs, "allowed_observation_refs"))
        for name in ("source_refs", "provenance_refs", "evidence_refs"):
            object.__setattr__(self, name, _text_tuple(getattr(self, name), name))
        actor = _mapping(self.approved_by, "approved_by")
        object.__setattr__(self, "approved_by", {"type": _text(actor.get("type"), "approved_by.type"), "id": _text(actor.get("id"), "approved_by.id")})
        object.__setattr__(self, "created_seq", _created_seq(self.created_seq))

    def to_dict(self) -> dict[str, Any]:
        return {name: _json(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OracleSpecification":
        return cls(**{name: tuple(value.get(name) or ()) if name in {"observation_schema", "allowed_observation_refs", "source_refs", "provenance_refs", "evidence_refs"} else value[name] for name in cls.__dataclass_fields__ if name != "created_seq"}, created_seq=value.get("created_seq", 0))


@dataclass(frozen=True)
class ExecutionReadinessAssessment:
    execution_readiness_id: str
    version: int
    mission_id: str
    scope_identity: str
    case_version_id: str
    case_version_digest: str
    case_review_id: str
    review_digest: str
    oracle_specification_id: str
    oracle_specification_digest: str
    evidence_requirement_set_id: str
    evidence_requirement_digest: str
    precondition_requirement_refs: tuple[str, ...]
    precondition_resolution_refs: tuple[str, ...]
    test_data_requirement_refs: tuple[str, ...]
    test_data_resolution_refs: tuple[str, ...]
    runtime_fact_refs: tuple[str, ...]
    capability_refs: tuple[str, ...]
    environment_refs: tuple[str, ...]
    dimension_assessments: Mapping[str, str]
    readiness_status: str
    blockers: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    conflicts: tuple[str, ...]
    runtime_binding_plan: Mapping[str, Any]
    valid_until: str | None
    assessed_at: str
    assessed_by: Mapping[str, str]
    readiness_fingerprint: str
    source_provenance: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    created_seq: int = 0

    def __post_init__(self) -> None:
        for name in ("execution_readiness_id", "mission_id", "scope_identity", "case_version_id", "case_version_digest", "case_review_id", "review_digest", "oracle_specification_id", "oracle_specification_digest", "evidence_requirement_set_id", "evidence_requirement_digest", "assessed_at", "readiness_fingerprint"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise R34Error("R3_4_SCHEMA_INVALID", "readiness version must be positive")
        for name in ("precondition_requirement_refs", "precondition_resolution_refs", "test_data_requirement_refs", "test_data_resolution_refs", "runtime_fact_refs", "capability_refs", "environment_refs", "blockers", "missing_inputs", "conflicts", "source_provenance", "evidence_refs"):
            object.__setattr__(self, name, _text_tuple(getattr(self, name), name))
        object.__setattr__(self, "dimension_assessments", _mapping(self.dimension_assessments, "dimension_assessments"))
        object.__setattr__(self, "readiness_status", _status(self.readiness_status, READINESS_STATUSES, "readiness_status"))
        object.__setattr__(self, "runtime_binding_plan", _mapping(self.runtime_binding_plan, "runtime_binding_plan"))
        object.__setattr__(self, "valid_until", _optional_text(self.valid_until, "valid_until"))
        actor = _mapping(self.assessed_by, "assessed_by")
        object.__setattr__(self, "assessed_by", {"type": _text(actor.get("type"), "assessed_by.type"), "id": _text(actor.get("id"), "assessed_by.id")})
        object.__setattr__(self, "created_seq", _created_seq(self.created_seq))

    def to_dict(self) -> dict[str, Any]:
        return {name: _json(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionReadinessAssessment":
        return cls(**{name: tuple(value.get(name) or ()) if name in {"precondition_requirement_refs", "precondition_resolution_refs", "test_data_requirement_refs", "test_data_resolution_refs", "runtime_fact_refs", "capability_refs", "environment_refs", "blockers", "missing_inputs", "conflicts", "source_provenance", "evidence_refs"} else value.get(name, {}) if name in {"dimension_assessments", "runtime_binding_plan"} else value[name] for name in cls.__dataclass_fields__ if name != "created_seq"}, created_seq=value.get("created_seq", 0))


@dataclass(frozen=True)
class CaseExecutionAttempt:
    case_execution_attempt_id: str
    version: int
    mission_id: str
    scope_identity: str
    case_version_id: str
    case_version_digest: str
    case_review_id: str
    review_digest: str
    execution_readiness_id: str
    readiness_digest: str
    precondition_resolution_digest: str
    test_data_resolution_digest: str
    oracle_specification_id: str
    oracle_specification_digest: str
    evidence_requirement_set_id: str
    evidence_requirement_digest: str
    r1_runtime_attempt_id: str
    r1_root_attempt_id: str
    r1_attempt_lineage_digest: str
    runtime_session_id: str
    task_id: str
    plan_id: str
    plan_revision_id: str
    r2_executor_session_ref: str
    execution_status: str
    started_at: str
    completed_at: str | None
    execution_fact_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    source_provenance: tuple[str, ...]
    attempt_fingerprint: str
    idempotency_key: str
    correlation_id: str
    created_seq: int = 0

    def __post_init__(self) -> None:
        for name in ("case_execution_attempt_id", "mission_id", "scope_identity", "case_version_id", "case_version_digest", "case_review_id", "review_digest", "execution_readiness_id", "readiness_digest", "precondition_resolution_digest", "test_data_resolution_digest", "oracle_specification_id", "oracle_specification_digest", "evidence_requirement_set_id", "evidence_requirement_digest", "r1_runtime_attempt_id", "r1_root_attempt_id", "r1_attempt_lineage_digest", "runtime_session_id", "task_id", "plan_id", "plan_revision_id", "r2_executor_session_ref", "started_at", "attempt_fingerprint", "idempotency_key", "correlation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise R34Error("R3_4_SCHEMA_INVALID", "attempt version must be positive")
        object.__setattr__(self, "completed_at", _optional_text(self.completed_at, "completed_at"))
        object.__setattr__(self, "execution_status", _status(self.execution_status, EXECUTION_STATUSES, "execution_status"))
        for name in ("execution_fact_refs", "evidence_refs", "source_provenance"):
            object.__setattr__(self, name, _text_tuple(getattr(self, name), name))
        object.__setattr__(self, "created_seq", _created_seq(self.created_seq))

    def to_dict(self) -> dict[str, Any]:
        return {name: _json(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CaseExecutionAttempt":
        return cls(**{name: tuple(value.get(name) or ()) if name in {"execution_fact_refs", "evidence_refs", "source_provenance"} else value[name] for name in cls.__dataclass_fields__ if name != "created_seq"}, created_seq=value.get("created_seq", 0))


@dataclass(frozen=True)
class OracleEvaluation:
    oracle_evaluation_id: str
    version: int
    case_execution_attempt_id: str
    oracle_specification_id: str
    oracle_specification_digest: str
    observation_digest: str
    evidence_manifest_digest: str
    evidence_cutoff_ref: str
    evidence_sufficiency: str
    oracle_decision: str
    business_validation: str
    matched_observations: tuple[Mapping[str, Any], ...]
    unmet_conditions: tuple[str, ...]
    reasons: tuple[str, ...]
    evaluated_at: str
    evaluated_by: Mapping[str, str]
    provenance_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    evaluation_fingerprint: str
    supersedes_evaluation_id: str | None
    created_seq: int = 0

    def __post_init__(self) -> None:
        for name in ("oracle_evaluation_id", "case_execution_attempt_id", "oracle_specification_id", "oracle_specification_digest", "observation_digest", "evidence_manifest_digest", "evidence_cutoff_ref", "evaluated_at", "evaluation_fingerprint"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise R34Error("R3_4_SCHEMA_INVALID", "evaluation version must be positive")
        object.__setattr__(self, "evidence_sufficiency", _status(self.evidence_sufficiency, EVIDENCE_SUFFICIENCY, "evidence_sufficiency"))
        object.__setattr__(self, "oracle_decision", _status(self.oracle_decision, ORACLE_DECISIONS, "oracle_decision"))
        object.__setattr__(self, "business_validation", _status(self.business_validation, BUSINESS_VALIDATIONS, "business_validation"))
        object.__setattr__(self, "matched_observations", _mapping_tuple(self.matched_observations, "matched_observations"))
        object.__setattr__(self, "unmet_conditions", _text_tuple(self.unmet_conditions, "unmet_conditions"))
        object.__setattr__(self, "reasons", _text_tuple(self.reasons, "reasons"))
        actor = _mapping(self.evaluated_by, "evaluated_by")
        object.__setattr__(self, "evaluated_by", {"type": _text(actor.get("type"), "evaluated_by.type"), "id": _text(actor.get("id"), "evaluated_by.id")})
        object.__setattr__(self, "provenance_refs", _text_tuple(self.provenance_refs, "provenance_refs"))
        object.__setattr__(self, "evidence_refs", _text_tuple(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "supersedes_evaluation_id", _optional_text(self.supersedes_evaluation_id, "supersedes_evaluation_id"))
        object.__setattr__(self, "created_seq", _created_seq(self.created_seq))

    def to_dict(self) -> dict[str, Any]:
        return {name: _json(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OracleEvaluation":
        return cls(**{name: tuple(value.get(name) or ()) if name in {"matched_observations", "unmet_conditions", "reasons", "provenance_refs", "evidence_refs"} else value[name] for name in cls.__dataclass_fields__ if name != "created_seq"}, created_seq=value.get("created_seq", 0))


@dataclass(frozen=True)
class TestResult:
    test_result_id: str
    version: int
    case_execution_attempt_id: str
    case_version_id: str
    case_version_digest: str
    execution_status: str
    oracle_evaluation_id: str | None
    oracle_decision: str
    evidence_sufficiency: str
    business_validation_status: str
    result_status: str
    result_reason: str
    execution_fact_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    result_fingerprint: str
    created_at: str
    provenance_refs: tuple[str, ...]
    created_seq: int = 0

    def __post_init__(self) -> None:
        for name in ("test_result_id", "case_execution_attempt_id", "case_version_id", "case_version_digest", "result_reason", "result_fingerprint", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise R34Error("R3_4_SCHEMA_INVALID", "result version must be positive")
        object.__setattr__(self, "execution_status", _status(self.execution_status, EXECUTION_STATUSES, "execution_status"))
        object.__setattr__(self, "oracle_decision", _status(self.oracle_decision, ORACLE_DECISIONS, "oracle_decision"))
        object.__setattr__(self, "evidence_sufficiency", _status(self.evidence_sufficiency, EVIDENCE_SUFFICIENCY, "evidence_sufficiency"))
        object.__setattr__(self, "business_validation_status", _status(self.business_validation_status, BUSINESS_VALIDATIONS, "business_validation_status"))
        object.__setattr__(self, "result_status", _status(self.result_status, RESULT_STATUSES, "result_status"))
        object.__setattr__(self, "oracle_evaluation_id", _optional_text(self.oracle_evaluation_id, "oracle_evaluation_id"))
        for name in ("execution_fact_refs", "evidence_refs", "provenance_refs"):
            object.__setattr__(self, name, _text_tuple(getattr(self, name), name))
        object.__setattr__(self, "created_seq", _created_seq(self.created_seq))

    def to_dict(self) -> dict[str, Any]:
        return {name: _json(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TestResult":
        return cls(**{name: tuple(value.get(name) or ()) if name in {"execution_fact_refs", "evidence_refs", "provenance_refs"} else value[name] for name in cls.__dataclass_fields__ if name != "created_seq"}, created_seq=value.get("created_seq", 0))


@dataclass(frozen=True)
class R34ReuseReference:
    reuse_id: str
    entity_type: str
    entity_id: str
    fingerprint: str
    idempotency_key: str
    created_seq: int
    created_at: str
    correlation_id: str

    def __post_init__(self) -> None:
        for name in ("reuse_id", "entity_type", "entity_id", "fingerprint", "idempotency_key", "created_at", "correlation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "created_seq", _created_seq(self.created_seq))

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R34ReuseReference":
        return cls(**{name: value[name] for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class R34State:
    mission_id: str
    reviewer_contexts: tuple[ReviewerContextSnapshot, ...] = ()
    case_reviews: tuple[CaseReview, ...] = ()
    execution_readiness: tuple[ExecutionReadinessAssessment, ...] = ()
    precondition_requirements: tuple[PreconditionRequirement, ...] = ()
    precondition_resolutions: tuple[PreconditionResolution, ...] = ()
    test_data_requirements: tuple[TestDataRequirement, ...] = ()
    test_data_resolutions: tuple[TestDataResolution, ...] = ()
    oracle_specifications: tuple[OracleSpecification, ...] = ()
    evidence_requirements: tuple[EvidenceRequirement, ...] = ()
    case_execution_attempts: tuple[CaseExecutionAttempt, ...] = ()
    oracle_evaluations: tuple[OracleEvaluation, ...] = ()
    test_results: tuple[TestResult, ...] = ()
    reuses: tuple[R34ReuseReference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        type_map = {
            "reviewer_contexts": ReviewerContextSnapshot, "case_reviews": CaseReview, "execution_readiness": ExecutionReadinessAssessment,
            "precondition_requirements": PreconditionRequirement, "precondition_resolutions": PreconditionResolution, "test_data_requirements": TestDataRequirement,
            "test_data_resolutions": TestDataResolution, "oracle_specifications": OracleSpecification, "evidence_requirements": EvidenceRequirement,
            "case_execution_attempts": CaseExecutionAttempt, "oracle_evaluations": OracleEvaluation, "test_results": TestResult, "reuses": R34ReuseReference,
        }
        for name, cls in type_map.items():
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, cls) for item in values):
                raise R34Error("R3_4_SCHEMA_INVALID", f"{name} must be immutable typed tuples")
            ids = [getattr(item, next(iter(cls.__dataclass_fields__))) for item in values]
            if len(ids) != len(set(ids)):
                raise R34Error("R3_4_IDENTITY_CONFLICT", f"{name} identities must be unique")

    def _find(self, name: str, identity: str):
        return next((item for item in getattr(self, name) if getattr(item, next(iter(type(item).__dataclass_fields__))) == identity), None)

    def reviewer_context(self, identity: str) -> ReviewerContextSnapshot | None:
        return next((item for item in self.reviewer_contexts if item.reviewer_context_id == identity), None)

    def review(self, identity: str) -> CaseReview | None:
        return next((item for item in self.case_reviews if item.case_review_id == identity), None)

    def readiness(self, identity: str) -> ExecutionReadinessAssessment | None:
        return next((item for item in self.execution_readiness if item.execution_readiness_id == identity), None)

    def precondition_requirement(self, identity: str) -> PreconditionRequirement | None:
        return next((item for item in self.precondition_requirements if item.precondition_requirement_id == identity), None)

    def test_data_requirement(self, identity: str) -> TestDataRequirement | None:
        return next((item for item in self.test_data_requirements if item.test_data_requirement_id == identity), None)

    def oracle(self, identity: str) -> OracleSpecification | None:
        return next((item for item in self.oracle_specifications if item.oracle_specification_id == identity), None)

    def attempt(self, identity: str) -> CaseExecutionAttempt | None:
        return next((item for item in self.case_execution_attempts if item.case_execution_attempt_id == identity), None)

    def evaluation(self, identity: str) -> OracleEvaluation | None:
        return next((item for item in self.oracle_evaluations if item.oracle_evaluation_id == identity), None)

    def result(self, identity: str) -> TestResult | None:
        return next((item for item in self.test_results if item.test_result_id == identity), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "reviewer_contexts": [item.to_dict() for item in sorted(self.reviewer_contexts, key=lambda item: item.reviewer_context_id)],
            "case_reviews": [item.to_dict() for item in sorted(self.case_reviews, key=lambda item: item.case_review_id)],
            "execution_readiness": [item.to_dict() for item in sorted(self.execution_readiness, key=lambda item: item.execution_readiness_id)],
            "precondition_requirements": [item.to_dict() for item in sorted(self.precondition_requirements, key=lambda item: item.precondition_requirement_id)],
            "precondition_resolutions": [item.to_dict() for item in sorted(self.precondition_resolutions, key=lambda item: item.precondition_resolution_id)],
            "test_data_requirements": [item.to_dict() for item in sorted(self.test_data_requirements, key=lambda item: item.test_data_requirement_id)],
            "test_data_resolutions": [item.to_dict() for item in sorted(self.test_data_resolutions, key=lambda item: item.test_data_resolution_id)],
            "oracle_specifications": [item.to_dict() for item in sorted(self.oracle_specifications, key=lambda item: item.oracle_specification_id)],
            "evidence_requirements": [item.to_dict() for item in sorted(self.evidence_requirements, key=lambda item: item.evidence_requirement_id)],
            "case_execution_attempts": [item.to_dict() for item in sorted(self.case_execution_attempts, key=lambda item: item.case_execution_attempt_id)],
            "oracle_evaluations": [item.to_dict() for item in sorted(self.oracle_evaluations, key=lambda item: item.oracle_evaluation_id)],
            "test_results": [item.to_dict() for item in sorted(self.test_results, key=lambda item: item.test_result_id)],
            "reuses": [item.to_dict() for item in sorted(self.reuses, key=lambda item: item.reuse_id)],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R34State":
        return cls(
            mission_id=value["mission_id"], reviewer_contexts=tuple(ReviewerContextSnapshot.from_dict(item) for item in value.get("reviewer_contexts") or ()), case_reviews=tuple(CaseReview.from_dict(item) for item in value.get("case_reviews") or ()), execution_readiness=tuple(ExecutionReadinessAssessment.from_dict(item) for item in value.get("execution_readiness") or ()),
            precondition_requirements=tuple(PreconditionRequirement.from_dict(item) for item in value.get("precondition_requirements") or ()), precondition_resolutions=tuple(PreconditionResolution.from_dict(item) for item in value.get("precondition_resolutions") or ()), test_data_requirements=tuple(TestDataRequirement.from_dict(item) for item in value.get("test_data_requirements") or ()), test_data_resolutions=tuple(TestDataResolution.from_dict(item) for item in value.get("test_data_resolutions") or ()),
            oracle_specifications=tuple(OracleSpecification.from_dict(item) for item in value.get("oracle_specifications") or ()), evidence_requirements=tuple(EvidenceRequirement.from_dict(item) for item in value.get("evidence_requirements") or ()), case_execution_attempts=tuple(CaseExecutionAttempt.from_dict(item) for item in value.get("case_execution_attempts") or ()), oracle_evaluations=tuple(OracleEvaluation.from_dict(item) for item in value.get("oracle_evaluations") or ()), test_results=tuple(TestResult.from_dict(item) for item in value.get("test_results") or ()), reuses=tuple(R34ReuseReference.from_dict(item) for item in value.get("reuses") or ()),
        )


def request_from_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R34Error("R3_4_SCHEMA_INVALID", "request must be an object")
    result = dict(value)
    result.setdefault("idempotency_key", canonical_sha256(result))
    result.setdefault("correlation_id", result["idempotency_key"])
    return result


def record_digest(value: Any) -> str:
    return canonical_sha256(value)
