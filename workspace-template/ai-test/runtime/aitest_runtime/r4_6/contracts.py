from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, canonical_sha256
from aitest_runtime.r4_1.contracts import (
    Availability,
    FieldValidationState,
    Freshness,
    TypedReference,
)
from aitest_runtime.r4_5.contracts import HumanGateLinkage
from aitest_runtime.r3_e1.contracts import (
    KnowledgeFact,
    KnowledgeScopeIdentity,
    KnowledgeSourceRef,
    KnowledgeVersion,
)
from .errors import (
    R46_DIGEST_CONFLICT,
    R46_IDENTITY_CONFLICT,
    R46_SCHEMA_INVALID,
    R46Error,
)


EXTENSION_ID = "r4_6_validated_learning_promotion_boundary"
EXTENSION_VERSION = 1
SCHEMA_VERSION = 1

R4_6_RECORD_CANDIDATE_REVISION = "R4_6_RECORD_CANDIDATE_REVISION.v1"
R4_6_RECORD_PROMOTION_ELIGIBILITY = "R4_6_RECORD_PROMOTION_ELIGIBILITY.v1"
R4_6_CREATE_PROMOTION_REQUEST = "R4_6_CREATE_PROMOTION_REQUEST.v1"
R4_6_SUBMIT_PROMOTION_REQUEST = "R4_6_SUBMIT_PROMOTION_REQUEST.v1"
R4_6_RECORD_PROMOTION_RECEIPT = "R4_6_RECORD_PROMOTION_RECEIPT.v1"
R4_6_RECORD_CANDIDATE_DISPOSITION = "R4_6_RECORD_CANDIDATE_DISPOSITION.v1"
COMMAND_TYPES = frozenset({
    R4_6_RECORD_CANDIDATE_REVISION,
    R4_6_RECORD_PROMOTION_ELIGIBILITY,
    R4_6_CREATE_PROMOTION_REQUEST,
    R4_6_SUBMIT_PROMOTION_REQUEST,
    R4_6_RECORD_PROMOTION_RECEIPT,
    R4_6_RECORD_CANDIDATE_DISPOSITION,
})

R46_CANDIDATE_REVISION_RECORDED = "r4.6.candidate_revision_recorded.v1"
R46_PROMOTION_ELIGIBILITY_RECORDED = "r4.6.promotion_eligibility_recorded.v1"
R46_PROMOTION_REQUEST_CREATED = "r4.6.promotion_request_created.v1"
R46_PROMOTION_REQUEST_SUBMITTED = "r4.6.promotion_request_submitted.v1"
R46_PROMOTION_RECEIPT_RECORDED = "r4.6.promotion_receipt_recorded.v1"
R46_CANDIDATE_DISPOSITION_RECORDED = "r4.6.candidate_disposition_recorded.v1"
EVENT_TYPES = frozenset({
    R46_CANDIDATE_REVISION_RECORDED,
    R46_PROMOTION_ELIGIBILITY_RECORDED,
    R46_PROMOTION_REQUEST_CREATED,
    R46_PROMOTION_REQUEST_SUBMITTED,
    R46_PROMOTION_RECEIPT_RECORDED,
    R46_CANDIDATE_DISPOSITION_RECORDED,
})


class CandidateType(str, Enum):
    DEFECT_LEARNING = "DEFECT_LEARNING"
    TEST_STRATEGY_LEARNING = "TEST_STRATEGY_LEARNING"
    ORACLE_LEARNING = "ORACLE_LEARNING"
    BUSINESS_JOURNEY_LEARNING = "BUSINESS_JOURNEY_LEARNING"
    ENVIRONMENT_OR_RUNTIME_LEARNING = "ENVIRONMENT_OR_RUNTIME_LEARNING"
    HUMAN_TAUGHT_LEARNING = "HUMAN_TAUGHT_LEARNING"
    KNOWLEDGE_CORRECTION_LEARNING = "KNOWLEDGE_CORRECTION_LEARNING"


class CandidateClaimKind(str, Enum):
    FACT = "FACT"
    RULE = "RULE"
    HEURISTIC = "HEURISTIC"
    WORKFLOW_INFERENCE = "WORKFLOW_INFERENCE"
    ORACLE_CONSTRAINT = "ORACLE_CONSTRAINT"
    JOURNEY_CONSTRAINT = "JOURNEY_CONSTRAINT"
    ENVIRONMENT_CONSTRAINT = "ENVIRONMENT_CONSTRAINT"
    CORRECTION = "CORRECTION"


class CandidateValidationOutcome(str, Enum):
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    INCOMPLETE = "INCOMPLETE"
    BLOCKED = "BLOCKED"
    CONFLICT = "CONFLICT"


class CandidateLifecycleState(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"


class PromotionEligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    BLOCKED = "BLOCKED"
    INCOMPLETE = "INCOMPLETE"
    CONFLICT = "CONFLICT"
    STALE = "STALE"


class CandidateDispositionKind(str, Enum):
    INVALIDATE = "INVALIDATE"
    STALE = "STALE"
    SUPERSEDE = "SUPERSEDE"
    REVALIDATE = "REVALIDATE"
    PROVENANCE_ONLY = "PROVENANCE_ONLY"


class PromotionRequestState(str, Enum):
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    CONFLICT = "CONFLICT"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class PromotionReceiptStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    CONFLICT = "CONFLICT"
    DUPLICATE = "DUPLICATE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class R46ScopeClass(str, Enum):
    PERSONAL_PRIVATE = "PERSONAL_PRIVATE"
    MISSION_LOCAL = "MISSION_LOCAL"
    PROJECT_SHARED = "PROJECT_SHARED"
    CANONICAL_KNOWLEDGE_SCOPE = "CANONICAL_KNOWLEDGE_SCOPE"


class R46ScopeWideningDecision(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    EXPLICITLY_ALLOWED = "EXPLICITLY_ALLOWED"
    DENIED = "DENIED"
    REQUIRES_HUMAN_GATE = "REQUIRES_HUMAN_GATE"


class R46ProvenanceClass(str, Enum):
    R3_4_REQUIREMENT_OR_JOURNEY = "R3_4_REQUIREMENT_OR_JOURNEY"
    R3_4_COVERAGE = "R3_4_COVERAGE"
    R3_4_ORACLE = "R3_4_ORACLE"
    R3_4_EVIDENCE = "R3_4_EVIDENCE"
    R3_4_TEST_RESULT = "R3_4_TEST_RESULT"
    R3_6_DEFECT_ASSESSMENT = "R3_6_DEFECT_ASSESSMENT"
    R3_6_EVIDENCE_ASSESSMENT = "R3_6_EVIDENCE_ASSESSMENT"
    R3_6_REPRODUCIBILITY = "R3_6_REPRODUCIBILITY"
    R3_6_FALSE_POSITIVE = "R3_6_FALSE_POSITIVE"
    R3_6_RCA = "R3_6_RCA"
    R3_7_TEST_SUFFICIENCY = "R3_7_TEST_SUFFICIENCY"
    R4_1_QUALITY_VERSION = "R4_1_QUALITY_VERSION"
    R4_1_TEST_CAMPAIGN = "R4_1_TEST_CAMPAIGN"
    R4_1_SELECTION_REVISION = "R4_1_SELECTION_REVISION"
    R4_2_TRIGGER = "R4_2_TRIGGER"
    R4_2_IMPACT_ASSESSMENT = "R4_2_IMPACT_ASSESSMENT"
    R4_3_CONFIRMED_DEFECT_LIFECYCLE = "R4_3_CONFIRMED_DEFECT_LIFECYCLE"
    R4_3_FIX_LINK = "R4_3_FIX_LINK"
    R4_3_FIX_DETECTION = "R4_3_FIX_DETECTION"
    R4_4_POST_FIX_VALIDATION = "R4_4_POST_FIX_VALIDATION"
    R4_4_FIX_VALIDATION = "R4_4_FIX_VALIDATION"
    R4_4_REGRESSION_WORKSET = "R4_4_REGRESSION_WORKSET"
    R4_4_REGRESSION_CLOSURE = "R4_4_REGRESSION_CLOSURE"
    R4_4_SUFFICIENCY_HANDOFF = "R4_4_SUFFICIENCY_HANDOFF"
    R4_5_RELEASE_RISK = "R4_5_RELEASE_RISK"
    R4_5_RELEASE_READINESS = "R4_5_RELEASE_READINESS"
    R3_E1_KNOWLEDGE_VERSION = "R3_E1_KNOWLEDGE_VERSION"
    FIELD_VALIDATION = "FIELD_VALIDATION"
    HUMAN_TEACHING = "HUMAN_TEACHING"
    MODEL_PROPOSAL = "MODEL_PROPOSAL"


class R46FreshnessRequirement(str, Enum):
    CURRENT_ONLY = "CURRENT_ONLY"
    CURRENT_OR_UNKNOWN = "CURRENT_OR_UNKNOWN"
    ANY_OBSERVED = "ANY_OBSERVED"


class R46AvailabilityRequirement(str, Enum):
    AVAILABLE_ONLY = "AVAILABLE_ONLY"
    AVAILABLE_OR_UNKNOWN = "AVAILABLE_OR_UNKNOWN"
    ANY_RECORDED = "ANY_RECORDED"


class R46FieldValidationRequirement(str, Enum):
    PASSED_REQUIRED = "PASSED_REQUIRED"
    NOT_REQUIRED = "NOT_REQUIRED"
    CURRENT_STATE_ONLY = "CURRENT_STATE_ONLY"


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R46Error(R46_SCHEMA_INVALID, f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _digest(value: Any, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    result = _text(value, name).lower()
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise R46Error(R46_SCHEMA_INVALID, f"{name} must be a lowercase SHA-256 digest")
    return result


def _seq(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise R46Error(R46_SCHEMA_INVALID, f"{name} must be an integer >= {minimum}")
    return value


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as exc:
        raise R46Error(R46_SCHEMA_INVALID, f"{name} is invalid") from exc


def _json(value: Any, name: str = "value") -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise R46Error(R46_SCHEMA_INVALID, f"{name} object keys must be strings")
            result[key] = _json(item, f"{name}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return tuple(_json(item, f"{name}[]") for item in value)
    if hasattr(value, "to_dict"):
        return _json(value.to_dict(), name)
    raise R46Error(R46_SCHEMA_INVALID, f"{name} contains unsupported data")


def _export(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, ActorRef):
        return value.to_dict()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _export(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_export(item) for item in value]
    return value


def _strict(value: Mapping[str, Any], allowed: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R46Error(R46_SCHEMA_INVALID, f"{name} must be an object")
    raw = dict(value)
    unknown = set(raw) - allowed
    if unknown:
        raise R46Error(R46_SCHEMA_INVALID, f"{name} contains unknown fields", {"unknown": sorted(unknown)})
    return raw


def _refs(value: Any, name: str, ref_type: type[Any] = TypedReference) -> tuple[Any, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise R46Error(R46_SCHEMA_INVALID, f"{name} must be an array")
    result = []
    for item in value:
        if isinstance(item, ref_type):
            result.append(item)
        elif isinstance(item, Mapping):
            result.append(ref_type.from_dict(item))
        else:
            raise R46Error(R46_SCHEMA_INVALID, f"{name} contains invalid references")
    return tuple(result)


def _optional_ref(value: Any, cls: type[Any], name: str) -> Any | None:
    if value is None:
        return None
    if isinstance(value, cls):
        return value
    if isinstance(value, Mapping) and hasattr(cls, "from_dict"):
        return cls.from_dict(value)
    raise R46Error(R46_SCHEMA_INVALID, f"{name} is invalid")


def _enum_tuple(value: Any, enum_type: type[Enum], name: str) -> tuple[Enum, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise R46Error(R46_SCHEMA_INVALID, f"{name} must be an array")
    result = tuple(_enum(enum_type, item, name) for item in value)
    if len(set(result)) != len(result):
        raise R46Error(R46_SCHEMA_INVALID, f"{name} must be unique")
    return result


def _finish_digest(obj: Any, field_name: str, supplied: str | None) -> None:
    body = {
        item.name: _export(getattr(obj, item.name))
        for item in fields(obj)
        if item.name not in {field_name, "record_digest", "created_at"}
    }
    expected = canonical_sha256(body)
    if supplied not in (None, "", "pending", expected):
        raise R46Error(R46_DIGEST_CONFLICT, f"{field_name} does not match canonical record")
    object.__setattr__(obj, field_name, expected)


def _common_init(obj: Any) -> None:
    object.__setattr__(obj, "owner_mission_id", _text(obj.owner_mission_id, "owner_mission_id"))
    object.__setattr__(obj, "owner_stream_key", _text(obj.owner_stream_key, "owner_stream_key"))
    object.__setattr__(obj, "revision", _seq(obj.revision, "revision", 1))
    object.__setattr__(obj, "as_of_seq", _seq(obj.as_of_seq, "as_of_seq"))
    object.__setattr__(obj, "source_cursor", _seq(obj.source_cursor, "source_cursor"))
    object.__setattr__(obj, "correlation_id", _text(obj.correlation_id, "correlation_id"))
    object.__setattr__(obj, "causation_id", _text(obj.causation_id, "causation_id"))
    actor = obj.created_by if isinstance(obj.created_by, ActorRef) else ActorRef(str(obj.created_by.get("type")), str(obj.created_by.get("id"))) if isinstance(obj.created_by, Mapping) else None
    if actor is None:
        raise R46Error(R46_SCHEMA_INVALID, "created_by must be ActorRef")
    object.__setattr__(obj, "created_by", actor)
    object.__setattr__(obj, "created_seq", _seq(obj.created_seq, "created_seq"))
    object.__setattr__(obj, "created_at", _text(obj.created_at, "created_at"))


@dataclass(frozen=True)
class R46ScopeReference:
    scope_class: R46ScopeClass | str
    project_id: str | None = None
    environment_id: str | None = None
    version_scope: str | None = None
    mission_id: str | None = None
    owner_ref: str | None = None
    knowledge_scope_identity: KnowledgeScopeIdentity | None = None
    scope_widening_decision: R46ScopeWideningDecision | str = R46ScopeWideningDecision.NOT_APPLICABLE
    scope_policy_digest: str = ""
    scope_digest: str | None = None

    def __post_init__(self) -> None:
        scope = _enum(R46ScopeClass, self.scope_class, "scope_class")
        object.__setattr__(self, "scope_class", scope)
        for name in ("project_id", "environment_id", "version_scope", "mission_id", "owner_ref"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        if self.knowledge_scope_identity is not None and not isinstance(self.knowledge_scope_identity, KnowledgeScopeIdentity):
            object.__setattr__(self, "knowledge_scope_identity", KnowledgeScopeIdentity.from_dict(self.knowledge_scope_identity))
        if scope is R46ScopeClass.PROJECT_SHARED and not self.project_id:
            raise R46Error(R46_SCHEMA_INVALID, "PROJECT_SHARED requires project_id")
        if scope is R46ScopeClass.CANONICAL_KNOWLEDGE_SCOPE:
            if not self.project_id or not self.environment_id or not self.version_scope or not isinstance(self.knowledge_scope_identity, KnowledgeScopeIdentity):
                raise R46Error(R46_SCOPE_MISMATCH, "canonical Knowledge scope requires exact project/environment/version identity")
            if self.knowledge_scope_identity.to_dict() != {"project_id": self.project_id, "environment_id": self.environment_id, "version_scope": self.version_scope}:
                raise R46Error(R46_SCOPE_MISMATCH, "scope fields differ from KnowledgeScopeIdentity")
        if scope is R46ScopeClass.MISSION_LOCAL and not self.mission_id:
            raise R46Error(R46_SCHEMA_INVALID, "MISSION_LOCAL requires mission_id")
        if scope is R46ScopeClass.PERSONAL_PRIVATE and not self.owner_ref:
            raise R46Error(R46_SCHEMA_INVALID, "PERSONAL_PRIVATE requires owner_ref")
        object.__setattr__(self, "scope_widening_decision", _enum(R46ScopeWideningDecision, self.scope_widening_decision, "scope_widening_decision"))
        object.__setattr__(self, "scope_policy_digest", _digest(self.scope_policy_digest, "scope_policy_digest"))
        _finish_digest(self, "scope_digest", self.scope_digest)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R46ScopeReference":
        return cls(**_strict(value, {item.name for item in fields(cls)}, "R46ScopeReference"))


R46ProvenanceReference = TypedReference


@dataclass(frozen=True)
class R46CandidateClaim:
    claim_kind: CandidateClaimKind | str
    claim_schema_version: int
    normalized_claim: Mapping[str, Any]
    bounded_attributes: Mapping[str, Any]
    claim_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_kind", _enum(CandidateClaimKind, self.claim_kind, "claim_kind"))
        if self.claim_schema_version != 1:
            raise R46Error(R46_SCHEMA_INVALID, "claim_schema_version must be 1")
        normalized = _json(self.normalized_claim, "normalized_claim")
        bounded = _json(self.bounded_attributes, "bounded_attributes")
        if not isinstance(normalized, Mapping) or not isinstance(bounded, Mapping):
            raise R46Error(R46_SCHEMA_INVALID, "claim objects must be mappings")
        if len(bounded) > 64 or len(str(_export(normalized)).encode()) > 16384:
            raise R46Error(R46_SCHEMA_INVALID, "candidate claim exceeds bounded limits")
        object.__setattr__(self, "normalized_claim", dict(normalized))
        object.__setattr__(self, "bounded_attributes", dict(bounded))
        expected = canonical_sha256({"claim_kind": self.claim_kind.value, "claim_schema_version": 1, "normalized_claim": self.normalized_claim, "bounded_attributes": self.bounded_attributes})
        supplied = self.claim_digest
        if supplied not in (None, "", "pending", expected):
            raise R46Error(R46_DIGEST_CONFLICT, "claim_digest does not match claim")
        object.__setattr__(self, "claim_digest", expected)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R46CandidateClaim":
        return cls(**_strict(value, {item.name for item in fields(cls)}, "R46CandidateClaim"))


@dataclass(frozen=True)
class R46PolicySnapshot:
    policy_id: str
    policy_version: str | int
    policy_digest: str
    policy_scope: R46ScopeReference
    required_provenance_classes: tuple[R46ProvenanceClass | str, ...]
    conditional_provenance_classes: tuple[R46ProvenanceClass | str, ...]
    context_provenance_classes: tuple[R46ProvenanceClass | str, ...]
    freshness_requirement: R46FreshnessRequirement | str
    availability_requirement: R46AvailabilityRequirement | str
    field_validation_requirement: R46FieldValidationRequirement | str
    approval_required: bool
    allowed_human_gate_outcomes: tuple[str, ...]
    allowed_human_gate_routes: tuple[str, ...]
    target_scope_requirements: Mapping[str, Any]
    as_of_cursor: int
    snapshot_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        if isinstance(self.policy_version, bool) or not isinstance(self.policy_version, (str, int)):
            raise R46Error(R46_SCHEMA_INVALID, "policy_version must be string or integer")
        object.__setattr__(self, "policy_digest", _digest(self.policy_digest, "policy_digest"))
        if not isinstance(self.policy_scope, R46ScopeReference):
            object.__setattr__(self, "policy_scope", R46ScopeReference.from_dict(self.policy_scope))
        for name in ("required_provenance_classes", "conditional_provenance_classes", "context_provenance_classes"):
            object.__setattr__(self, name, _enum_tuple(getattr(self, name), R46ProvenanceClass, name))
        required = set(self.required_provenance_classes)
        conditional = set(self.conditional_provenance_classes)
        context = set(self.context_provenance_classes)
        if required & conditional or required & context or conditional & context:
            raise R46Error(R46_SCHEMA_INVALID, "provenance class arrays must be non-overlapping")
        object.__setattr__(self, "freshness_requirement", _enum(R46FreshnessRequirement, self.freshness_requirement, "freshness_requirement"))
        object.__setattr__(self, "availability_requirement", _enum(R46AvailabilityRequirement, self.availability_requirement, "availability_requirement"))
        object.__setattr__(self, "field_validation_requirement", _enum(R46FieldValidationRequirement, self.field_validation_requirement, "field_validation_requirement"))
        if not isinstance(self.approval_required, bool):
            raise R46Error(R46_SCHEMA_INVALID, "approval_required must be boolean")
        object.__setattr__(self, "allowed_human_gate_outcomes", tuple(_text(v, "allowed_human_gate_outcomes[]") for v in (self.allowed_human_gate_outcomes or ())))
        object.__setattr__(self, "allowed_human_gate_routes", tuple(_text(v, "allowed_human_gate_routes[]") for v in (self.allowed_human_gate_routes or ())))
        object.__setattr__(self, "target_scope_requirements", dict(_json(self.target_scope_requirements, "target_scope_requirements")))
        object.__setattr__(self, "as_of_cursor", _seq(self.as_of_cursor, "as_of_cursor"))
        _finish_digest(self, "snapshot_digest", self.snapshot_digest)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R46PolicySnapshot":
        return cls(**_strict(value, {item.name for item in fields(cls)}, "R46PolicySnapshot"))


@dataclass(frozen=True)
class R46KnowledgeAuthorityResultRef:
    authority_extension_id: str
    operation_command_id: str
    operation_outcome: str
    duplicate_of: str | None
    authority_mission_id: str
    fact_id: str
    version_id: str
    version_number: int
    scope_identity: KnowledgeScopeIdentity
    knowledge_status: str
    payload_digest: str
    fingerprint: str
    first_seq: int
    last_seq: int
    state_hash: str
    authority_cursor: int
    result_digest: str | None = None

    def __post_init__(self) -> None:
        if self.authority_extension_id != "r3_e1_durable_knowledge_substrate":
            raise R46Error(R46_SCOPE_MISMATCH, "authority_extension_id must be R3.E1")
        for name in ("operation_command_id", "authority_mission_id", "fact_id", "version_id", "knowledge_status", "fingerprint", "state_hash"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.operation_outcome not in {"APPLIED", "DUPLICATE"}:
            raise R46Error(R46_SCHEMA_INVALID, "operation_outcome must be APPLIED or DUPLICATE")
        object.__setattr__(self, "duplicate_of", _optional_text(self.duplicate_of, "duplicate_of"))
        object.__setattr__(self, "version_number", _seq(self.version_number, "version_number", 1))
        if not isinstance(self.scope_identity, KnowledgeScopeIdentity):
            object.__setattr__(self, "scope_identity", KnowledgeScopeIdentity.from_dict(self.scope_identity))
        object.__setattr__(self, "payload_digest", _digest(self.payload_digest, "payload_digest"))
        object.__setattr__(self, "first_seq", _seq(self.first_seq, "first_seq"))
        object.__setattr__(self, "last_seq", _seq(self.last_seq, "last_seq"))
        object.__setattr__(self, "authority_cursor", _seq(self.authority_cursor, "authority_cursor"))
        _finish_digest(self, "result_digest", self.result_digest)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R46KnowledgeAuthorityResultRef":
        return cls(**_strict(value, {item.name for item in fields(cls)}, "R46KnowledgeAuthorityResultRef"))


@dataclass(frozen=True)
class _CommonDurable:
    owner_mission_id: str = ""
    owner_stream_key: str = ""
    revision: int = 1
    record_digest: str | None = None
    as_of_seq: int = 0
    source_cursor: int = 0
    correlation_id: str = "r4.6"
    causation_id: str = "r4.6"
    created_by: ActorRef | Mapping[str, Any] = ActorRef("SYSTEM", "r4.6")
    created_seq: int = 0
    created_at: str = "seq:0"


@dataclass(frozen=True)
class R46CandidateRevision(_CommonDurable):
    candidate_id: str = "pending"
    candidate_type: CandidateType | str = CandidateType.DEFECT_LEARNING
    candidate_claim: R46CandidateClaim | Mapping[str, Any] = None  # type: ignore[assignment]
    source_scope: R46ScopeReference | Mapping[str, Any] = None  # type: ignore[assignment]
    candidate_scope: R46ScopeReference | Mapping[str, Any] = None  # type: ignore[assignment]
    promotion_target_scope: R46ScopeReference | Mapping[str, Any] = None  # type: ignore[assignment]
    policy_snapshot: R46PolicySnapshot | Mapping[str, Any] = None  # type: ignore[assignment]
    authoritative_provenance_refs: tuple[TypedReference, ...] = ()
    evidence_refs: tuple[TypedReference, ...] = ()
    validation_facts: Mapping[str, Any] = None  # type: ignore[assignment]
    validation_outcome: CandidateValidationOutcome | str = CandidateValidationOutcome.INCOMPLETE
    lifecycle_state: CandidateLifecycleState | str = CandidateLifecycleState.CURRENT
    parent_revision_ref: TypedReference | Mapping[str, Any] | None = None
    supersedes_ref: TypedReference | Mapping[str, Any] | None = None
    invalidated_by_ref: TypedReference | Mapping[str, Any] | None = None
    revalidation_ref: TypedReference | Mapping[str, Any] | None = None
    field_validation_state: FieldValidationState | str = FieldValidationState.PENDING
    freshness: Freshness | str = Freshness.UNKNOWN
    availability: Availability | str = Availability.UNKNOWN
    conflict_refs: tuple[TypedReference, ...] = ()
    candidate_digest: str | None = None
    revision_digest: str | None = None

    def __post_init__(self) -> None:
        _common_init(self)
        object.__setattr__(self, "candidate_type", _enum(CandidateType, self.candidate_type, "candidate_type"))
        object.__setattr__(self, "candidate_claim", self.candidate_claim if isinstance(self.candidate_claim, R46CandidateClaim) else R46CandidateClaim.from_dict(self.candidate_claim))
        for name in ("source_scope", "candidate_scope", "promotion_target_scope"):
            value = getattr(self, name)
            object.__setattr__(self, name, value if isinstance(value, R46ScopeReference) else R46ScopeReference.from_dict(value))
        value = self.policy_snapshot
        object.__setattr__(self, "policy_snapshot", value if isinstance(value, R46PolicySnapshot) else R46PolicySnapshot.from_dict(value))
        object.__setattr__(self, "authoritative_provenance_refs", _refs(self.authoritative_provenance_refs, "authoritative_provenance_refs"))
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "validation_facts", dict(_json(self.validation_facts or {}, "validation_facts")))
        object.__setattr__(self, "validation_outcome", _enum(CandidateValidationOutcome, self.validation_outcome, "validation_outcome"))
        object.__setattr__(self, "lifecycle_state", _enum(CandidateLifecycleState, self.lifecycle_state, "lifecycle_state"))
        for name in ("parent_revision_ref", "supersedes_ref", "invalidated_by_ref", "revalidation_ref"):
            object.__setattr__(self, name, _optional_ref(getattr(self, name), TypedReference, name))
        object.__setattr__(self, "field_validation_state", _enum(FieldValidationState, self.field_validation_state, "field_validation_state"))
        object.__setattr__(self, "freshness", _enum(Freshness, self.freshness, "freshness"))
        object.__setattr__(self, "availability", _enum(Availability, self.availability, "availability"))
        object.__setattr__(self, "conflict_refs", _refs(self.conflict_refs, "conflict_refs"))
        expected_candidate = canonical_sha256({
            "candidate_type": self.candidate_type.value,
            "candidate_claim": self.candidate_claim.to_dict(),
            "source_scope": self.source_scope.to_dict(),
            "candidate_scope": self.candidate_scope.to_dict(),
            "promotion_target_scope": self.promotion_target_scope.to_dict(),
            "policy_snapshot": self.policy_snapshot.to_dict(),
            "authoritative_provenance_refs": [_export(item) for item in self.authoritative_provenance_refs],
            "evidence_refs": [_export(item) for item in self.evidence_refs],
            "validation_facts": self.validation_facts,
            "validation_outcome": self.validation_outcome.value,
            "lifecycle_state": self.lifecycle_state.value,
            "field_validation_state": self.field_validation_state.value,
            "freshness": self.freshness.value,
            "availability": self.availability.value,
            "conflict_refs": [_export(item) for item in self.conflict_refs],
        })
        if self.candidate_digest not in (None, "", "pending", expected_candidate):
            raise R46Error(R46_DIGEST_CONFLICT, "candidate_digest does not match candidate")
        object.__setattr__(self, "candidate_digest", expected_candidate)
        expected_revision = canonical_sha256({"candidate_id": self.candidate_id, "parent_revision_ref": _export(self.parent_revision_ref), "candidate_digest": expected_candidate, "source_cursor": self.source_cursor})
        if self.revision_digest not in (None, "", "pending", expected_revision):
            raise R46Error(R46_DIGEST_CONFLICT, "revision_digest does not match revision")
        object.__setattr__(self, "revision_digest", expected_revision)
        _finish_digest(self, "record_digest", self.record_digest)

    @property
    def revision_id(self) -> str:
        return candidate_revision_id_for(self.candidate_id, self.parent_revision_ref, self.revision_digest)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R46CandidateRevision":
        return cls(**_strict(value, {item.name for item in fields(cls)}, "R46CandidateRevision"))


@dataclass(frozen=True)
class R46ValidatedLearningCandidate:
    candidate_id: str
    owner_mission_id: str
    owner_stream_key: str
    current_revision_ref: TypedReference | None
    current_revision: R46CandidateRevision | None
    current_revision_digest: str | None
    current_validation_outcome: CandidateValidationOutcome | str | None
    current_lifecycle_state: CandidateLifecycleState | str | None
    current_eligibility_ref: TypedReference | None = None
    current_request_ref: TypedReference | None = None
    conflict_refs: tuple[TypedReference, ...] = ()
    superseded_refs: tuple[TypedReference, ...] = ()
    invalidated_refs: tuple[TypedReference, ...] = ()
    revalidation_refs: tuple[TypedReference, ...] = ()
    resolution_revision: int = 0
    resolution_digest: str = ""
    as_of_seq: int = 0
    source_cursor: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "owner_mission_id", _text(self.owner_mission_id, "owner_mission_id"))
        object.__setattr__(self, "owner_stream_key", _text(self.owner_stream_key, "owner_stream_key"))
        for name in ("current_revision_ref", "current_eligibility_ref", "current_request_ref"):
            object.__setattr__(self, name, _optional_ref(getattr(self, name), TypedReference, name))
        for name in ("conflict_refs", "superseded_refs", "invalidated_refs", "revalidation_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        if self.current_revision is not None and not isinstance(self.current_revision, R46CandidateRevision):
            object.__setattr__(self, "current_revision", R46CandidateRevision.from_dict(self.current_revision))
        if self.current_validation_outcome is not None:
            object.__setattr__(self, "current_validation_outcome", _enum(CandidateValidationOutcome, self.current_validation_outcome, "current_validation_outcome"))
        if self.current_lifecycle_state is not None:
            object.__setattr__(self, "current_lifecycle_state", _enum(CandidateLifecycleState, self.current_lifecycle_state, "current_lifecycle_state"))
        object.__setattr__(self, "current_revision_digest", _digest(self.current_revision_digest, "current_revision_digest", optional=True))
        object.__setattr__(self, "resolution_revision", _seq(self.resolution_revision, "resolution_revision"))
        object.__setattr__(self, "as_of_seq", _seq(self.as_of_seq, "as_of_seq"))
        object.__setattr__(self, "source_cursor", _seq(self.source_cursor, "source_cursor"))
        expected = canonical_sha256({"candidate_id": self.candidate_id, "current_revision_ref": _export(self.current_revision_ref), "current_revision_digest": self.current_revision_digest, "current_lifecycle_state": _export(self.current_lifecycle_state), "current_eligibility_ref": _export(self.current_eligibility_ref), "current_request_ref": _export(self.current_request_ref), "conflict_refs": [_export(item) for item in self.conflict_refs], "resolution_revision": self.resolution_revision, "as_of_seq": self.as_of_seq, "source_cursor": self.source_cursor})
        if self.resolution_digest not in ("", "pending", expected):
            raise R46Error(R46_DIGEST_CONFLICT, "resolution_digest does not match candidate resolution")
        object.__setattr__(self, "resolution_digest", expected)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R46ValidatedLearningCandidate":
        return cls(**_strict(value, {item.name for item in fields(cls)}, "R46ValidatedLearningCandidate"))


@dataclass(frozen=True)
class R46PromotionEligibilityAssessment(_CommonDurable):
    eligibility_id: str = "pending"
    candidate_revision_ref: TypedReference | Mapping[str, Any] = None  # type: ignore[assignment]
    candidate_revision_digest: str = ""
    policy_snapshot: R46PolicySnapshot | Mapping[str, Any] = None  # type: ignore[assignment]
    status: PromotionEligibilityStatus | str = PromotionEligibilityStatus.INCOMPLETE
    observed_required_provenance_refs: tuple[TypedReference, ...] = ()
    observed_conditional_provenance_refs: tuple[TypedReference, ...] = ()
    observed_context_refs: tuple[TypedReference, ...] = ()
    freshness: Freshness | str = Freshness.UNKNOWN
    availability: Availability | str = Availability.UNKNOWN
    field_validation_state: FieldValidationState | str = FieldValidationState.PENDING
    human_gate_required: bool = False
    human_gate_linkage: HumanGateLinkage | Mapping[str, Any] | None = None
    knowledge_target_scope: R46ScopeReference | Mapping[str, Any] = None  # type: ignore[assignment]
    knowledge_target_requirements: Mapping[str, Any] = None  # type: ignore[assignment]
    conflict_refs: tuple[TypedReference, ...] = ()
    blocking_refs: tuple[TypedReference, ...] = ()
    unknown_refs: tuple[TypedReference, ...] = ()
    incomplete_refs: tuple[TypedReference, ...] = ()
    assessment_digest: str | None = None

    def __post_init__(self) -> None:
        _common_init(self)
        object.__setattr__(self, "candidate_revision_ref", _optional_ref(self.candidate_revision_ref, TypedReference, "candidate_revision_ref"))
        object.__setattr__(self, "candidate_revision_digest", _digest(self.candidate_revision_digest, "candidate_revision_digest"))
        object.__setattr__(self, "policy_snapshot", self.policy_snapshot if isinstance(self.policy_snapshot, R46PolicySnapshot) else R46PolicySnapshot.from_dict(self.policy_snapshot))
        object.__setattr__(self, "status", _enum(PromotionEligibilityStatus, self.status, "status"))
        for name in ("observed_required_provenance_refs", "observed_conditional_provenance_refs", "observed_context_refs", "conflict_refs", "blocking_refs", "unknown_refs", "incomplete_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        object.__setattr__(self, "freshness", _enum(Freshness, self.freshness, "freshness"))
        object.__setattr__(self, "availability", _enum(Availability, self.availability, "availability"))
        object.__setattr__(self, "field_validation_state", _enum(FieldValidationState, self.field_validation_state, "field_validation_state"))
        if not isinstance(self.human_gate_required, bool):
            raise R46Error(R46_SCHEMA_INVALID, "human_gate_required must be boolean")
        object.__setattr__(self, "human_gate_linkage", _optional_ref(self.human_gate_linkage, HumanGateLinkage, "human_gate_linkage"))
        object.__setattr__(self, "knowledge_target_scope", self.knowledge_target_scope if isinstance(self.knowledge_target_scope, R46ScopeReference) else R46ScopeReference.from_dict(self.knowledge_target_scope))
        object.__setattr__(self, "knowledge_target_requirements", dict(_json(self.knowledge_target_requirements or {}, "knowledge_target_requirements")))
        _finish_digest(self, "assessment_digest", self.assessment_digest)
        _finish_digest(self, "record_digest", self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R46PromotionEligibilityAssessment":
        return cls(**_strict(value, {item.name for item in fields(cls)}, "R46PromotionEligibilityAssessment"))


@dataclass(frozen=True)
class R46KnowledgePromotionRequest(_CommonDurable):
    request_id: str = "pending"
    candidate_revision_ref: TypedReference | Mapping[str, Any] = None  # type: ignore[assignment]
    candidate_revision_digest: str = ""
    eligibility_ref: TypedReference | Mapping[str, Any] = None  # type: ignore[assignment]
    eligibility_digest: str = ""
    promotion_target_scope: R46ScopeReference | Mapping[str, Any] = None  # type: ignore[assignment]
    target_fact_id: str = ""
    target_version_id: str = ""
    requested_knowledge_status: str = ""
    expected_source_ref_ids: tuple[str, ...] = ()
    expected_knowledge_input_digest: str = ""
    policy_snapshot: R46PolicySnapshot | Mapping[str, Any] = None  # type: ignore[assignment]
    human_gate_linkage: HumanGateLinkage | Mapping[str, Any] | None = None
    idempotency_identity: str = ""
    state: PromotionRequestState | str = PromotionRequestState.READY
    submission_attempt: int = 0
    authority_command_id: str | None = None
    authority_idempotency_key: str | None = None
    request_digest: str | None = None

    def __post_init__(self) -> None:
        _common_init(self)
        object.__setattr__(self, "request_id", _text(self.request_id, "request_id"))
        object.__setattr__(self, "candidate_revision_ref", _optional_ref(self.candidate_revision_ref, TypedReference, "candidate_revision_ref"))
        object.__setattr__(self, "candidate_revision_digest", _digest(self.candidate_revision_digest, "candidate_revision_digest"))
        object.__setattr__(self, "eligibility_ref", _optional_ref(self.eligibility_ref, TypedReference, "eligibility_ref"))
        object.__setattr__(self, "eligibility_digest", _digest(self.eligibility_digest, "eligibility_digest"))
        object.__setattr__(self, "promotion_target_scope", self.promotion_target_scope if isinstance(self.promotion_target_scope, R46ScopeReference) else R46ScopeReference.from_dict(self.promotion_target_scope))
        for name in ("target_fact_id", "target_version_id", "requested_knowledge_status", "expected_knowledge_input_digest", "idempotency_identity"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "expected_source_ref_ids", tuple(_text(item, "expected_source_ref_ids[]") for item in (self.expected_source_ref_ids or ())))
        object.__setattr__(self, "expected_knowledge_input_digest", _digest(self.expected_knowledge_input_digest, "expected_knowledge_input_digest"))
        object.__setattr__(self, "policy_snapshot", self.policy_snapshot if isinstance(self.policy_snapshot, R46PolicySnapshot) else R46PolicySnapshot.from_dict(self.policy_snapshot))
        object.__setattr__(self, "human_gate_linkage", _optional_ref(self.human_gate_linkage, HumanGateLinkage, "human_gate_linkage"))
        object.__setattr__(self, "state", _enum(PromotionRequestState, self.state, "state"))
        object.__setattr__(self, "submission_attempt", _seq(self.submission_attempt, "submission_attempt"))
        object.__setattr__(self, "authority_command_id", _optional_text(self.authority_command_id, "authority_command_id"))
        object.__setattr__(self, "authority_idempotency_key", _optional_text(self.authority_idempotency_key, "authority_idempotency_key"))
        request_body = {
            item.name: _export(getattr(self, item.name))
            for item in fields(self)
            if item.name not in {"request_digest", "record_digest", "created_at", "state", "submission_attempt", "authority_command_id", "authority_idempotency_key", "correlation_id", "causation_id", "created_by", "created_seq"}
        }
        expected_request = canonical_sha256(request_body)
        if self.request_digest not in (None, "", "pending", expected_request):
            raise R46Error(R46_DIGEST_CONFLICT, "request_digest does not match canonical record")
        object.__setattr__(self, "request_digest", expected_request)
        _finish_digest(self, "record_digest", self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R46KnowledgePromotionRequest":
        return cls(**_strict(value, {item.name for item in fields(cls)}, "R46KnowledgePromotionRequest"))


@dataclass(frozen=True)
class R46KnowledgePromotionReceipt(_CommonDurable):
    receipt_id: str = "pending"
    request_ref: TypedReference | Mapping[str, Any] = None  # type: ignore[assignment]
    request_digest: str = ""
    candidate_revision_ref: TypedReference | Mapping[str, Any] = None  # type: ignore[assignment]
    candidate_revision_digest: str = ""
    status: PromotionReceiptStatus | str = PromotionReceiptStatus.RECONCILIATION_REQUIRED
    authority_result_ref: R46KnowledgeAuthorityResultRef | Mapping[str, Any] | None = None
    canonical_knowledge_ref: R46KnowledgeAuthorityResultRef | Mapping[str, Any] | None = None
    reason_refs: tuple[TypedReference, ...] = ()
    error_code: str | None = None
    reconciled_from_existing: bool = False
    receipt_digest: str | None = None

    def __post_init__(self) -> None:
        _common_init(self)
        object.__setattr__(self, "receipt_id", _text(self.receipt_id, "receipt_id"))
        object.__setattr__(self, "request_ref", _optional_ref(self.request_ref, TypedReference, "request_ref"))
        object.__setattr__(self, "request_digest", _digest(self.request_digest, "request_digest"))
        object.__setattr__(self, "candidate_revision_ref", _optional_ref(self.candidate_revision_ref, TypedReference, "candidate_revision_ref"))
        object.__setattr__(self, "candidate_revision_digest", _digest(self.candidate_revision_digest, "candidate_revision_digest"))
        object.__setattr__(self, "status", _enum(PromotionReceiptStatus, self.status, "status"))
        object.__setattr__(self, "authority_result_ref", _optional_ref(self.authority_result_ref, R46KnowledgeAuthorityResultRef, "authority_result_ref"))
        object.__setattr__(self, "canonical_knowledge_ref", _optional_ref(self.canonical_knowledge_ref, R46KnowledgeAuthorityResultRef, "canonical_knowledge_ref"))
        object.__setattr__(self, "reason_refs", _refs(self.reason_refs, "reason_refs"))
        object.__setattr__(self, "error_code", _optional_text(self.error_code, "error_code"))
        if not isinstance(self.reconciled_from_existing, bool):
            raise R46Error(R46_SCHEMA_INVALID, "reconciled_from_existing must be boolean")
        if self.status in {PromotionReceiptStatus.ACCEPTED, PromotionReceiptStatus.DUPLICATE} and self.canonical_knowledge_ref is None:
            raise R46Error(R46_REFERENCE_INVALID, "successful receipt requires canonical authority reference")
        if self.status not in {PromotionReceiptStatus.ACCEPTED, PromotionReceiptStatus.DUPLICATE} and self.canonical_knowledge_ref is not None:
            raise R46Error(R46_REFERENCE_INVALID, "non-success receipt cannot contain canonical Knowledge reference")
        _finish_digest(self, "receipt_digest", self.receipt_digest)
        _finish_digest(self, "record_digest", self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R46KnowledgePromotionReceipt":
        return cls(**_strict(value, {item.name for item in fields(cls)}, "R46KnowledgePromotionReceipt"))


@dataclass(frozen=True)
class R46CandidateDisposition(_CommonDurable):
    disposition_id: str = "pending"
    target_candidate_revision_ref: TypedReference | Mapping[str, Any] = None  # type: ignore[assignment]
    target_candidate_revision_digest: str = ""
    trigger_kind: str = ""
    cause_refs: tuple[TypedReference, ...] = ()
    disposition_kind: CandidateDispositionKind | str = CandidateDispositionKind.REVALIDATE
    policy_revision: str | int = 1
    policy_digest: str = ""
    replacement_revision_ref: TypedReference | Mapping[str, Any] | None = None
    revalidation_ref: TypedReference | Mapping[str, Any] | None = None
    reason_refs: tuple[TypedReference, ...] = ()
    disposition_digest: str | None = None

    def __post_init__(self) -> None:
        _common_init(self)
        object.__setattr__(self, "disposition_id", _text(self.disposition_id, "disposition_id"))
        object.__setattr__(self, "target_candidate_revision_ref", _optional_ref(self.target_candidate_revision_ref, TypedReference, "target_candidate_revision_ref"))
        object.__setattr__(self, "target_candidate_revision_digest", _digest(self.target_candidate_revision_digest, "target_candidate_revision_digest"))
        object.__setattr__(self, "trigger_kind", _text(self.trigger_kind, "trigger_kind"))
        object.__setattr__(self, "cause_refs", _refs(self.cause_refs, "cause_refs"))
        object.__setattr__(self, "disposition_kind", _enum(CandidateDispositionKind, self.disposition_kind, "disposition_kind"))
        if isinstance(self.policy_revision, bool) or not isinstance(self.policy_revision, (str, int)):
            raise R46Error(R46_SCHEMA_INVALID, "policy_revision must be string or integer")
        object.__setattr__(self, "policy_digest", _digest(self.policy_digest, "policy_digest"))
        object.__setattr__(self, "replacement_revision_ref", _optional_ref(self.replacement_revision_ref, TypedReference, "replacement_revision_ref"))
        object.__setattr__(self, "revalidation_ref", _optional_ref(self.revalidation_ref, TypedReference, "revalidation_ref"))
        object.__setattr__(self, "reason_refs", _refs(self.reason_refs, "reason_refs"))
        _finish_digest(self, "disposition_digest", self.disposition_digest)
        _finish_digest(self, "record_digest", self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R46CandidateDisposition":
        return cls(**_strict(value, {item.name for item in fields(cls)}, "R46CandidateDisposition"))


@dataclass(frozen=True)
class R46CandidateCurrentResolution:
    candidate_id: str
    current: R46ValidatedLearningCandidate | None
    status: str
    conflict_refs: tuple[TypedReference, ...] = ()
    resolution_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "current", self.current if self.current is None or isinstance(self.current, R46ValidatedLearningCandidate) else R46ValidatedLearningCandidate.from_dict(self.current))
        object.__setattr__(self, "status", _text(self.status, "status"))
        object.__setattr__(self, "conflict_refs", _refs(self.conflict_refs, "conflict_refs"))
        expected = canonical_sha256({"candidate_id": self.candidate_id, "current": _export(self.current), "status": self.status, "conflict_refs": [_export(item) for item in self.conflict_refs]})
        if self.resolution_digest not in ("", "pending", expected):
            raise R46Error(R46_DIGEST_CONFLICT, "resolution_digest does not match current resolution")
        object.__setattr__(self, "resolution_digest", expected)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R46CandidateCurrentResolution":
        return cls(**_strict(value, {item.name for item in fields(cls)}, "R46CandidateCurrentResolution"))


@dataclass(frozen=True)
class R46State:
    mission_id: str
    candidate_revisions: tuple[R46CandidateRevision, ...] = ()
    eligibility_assessments: tuple[R46PromotionEligibilityAssessment, ...] = ()
    promotion_requests: tuple[R46KnowledgePromotionRequest, ...] = ()
    promotion_receipts: tuple[R46KnowledgePromotionReceipt, ...] = ()
    candidate_dispositions: tuple[R46CandidateDisposition, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        for name, cls in (("candidate_revisions", R46CandidateRevision), ("eligibility_assessments", R46PromotionEligibilityAssessment), ("promotion_requests", R46KnowledgePromotionRequest), ("promotion_receipts", R46KnowledgePromotionReceipt), ("candidate_dispositions", R46CandidateDisposition)):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, cls) for item in values):
                raise R46Error(R46_SCHEMA_INVALID, f"{name} must contain immutable typed records")
            identity_field = {
                "candidate_revisions": "revision_id",
                "eligibility_assessments": "eligibility_id",
                "promotion_requests": "request_id",
                "promotion_receipts": "receipt_id",
                "candidate_dispositions": "disposition_id",
            }[name]
            ids = [getattr(item, identity_field) for item in values]
            if len(ids) != len(set(ids)):
                raise R46Error(R46_IDENTITY_CONFLICT, f"{name} contains duplicate identity")
            for item in values:
                if item.owner_mission_id != self.mission_id:
                    raise R46Error("R4_6_SCOPE_MISMATCH", f"{name} contains cross-Mission record")

    def candidate_revision(self, revision_id: str) -> R46CandidateRevision | None:
        return next((item for item in self.candidate_revisions if item.revision_id == revision_id or item.candidate_id == revision_id), None)

    def candidate(self, candidate_id: str) -> R46ValidatedLearningCandidate | None:
        resolution = self.current_candidate(candidate_id)
        return resolution.current

    def eligibility(self, eligibility_id: str) -> R46PromotionEligibilityAssessment | None:
        return next((item for item in self.eligibility_assessments if item.eligibility_id == eligibility_id), None)

    def request(self, request_id: str) -> R46KnowledgePromotionRequest | None:
        return next((item for item in self.promotion_requests if item.request_id == request_id), None)

    def receipt(self, receipt_id: str) -> R46KnowledgePromotionReceipt | None:
        return next((item for item in self.promotion_receipts if item.receipt_id == receipt_id), None)

    def receipt_for_request(self, request_id: str) -> R46KnowledgePromotionReceipt | None:
        return next((item for item in reversed(self.promotion_receipts) if item.request_ref and item.request_ref.object_id == request_id), None)

    def disposition(self, disposition_id: str) -> R46CandidateDisposition | None:
        return next((item for item in self.candidate_dispositions if item.disposition_id == disposition_id), None)

    def current_candidate(self, candidate_id: str) -> R46CandidateCurrentResolution:
        revisions = [item for item in self.candidate_revisions if item.candidate_id == candidate_id]
        if not revisions:
            return R46CandidateCurrentResolution(candidate_id, None, "NOT_FOUND")
        invalidated = {item.target_candidate_revision_ref.object_id for item in self.candidate_dispositions if item.disposition_kind is CandidateDispositionKind.INVALIDATE and item.target_candidate_revision_ref}
        superseded = {item.target_candidate_revision_ref.object_id for item in self.candidate_dispositions if item.disposition_kind is CandidateDispositionKind.SUPERSEDE and item.target_candidate_revision_ref}
        active = [item for item in revisions if item.revision_id not in invalidated and item.revision_id not in superseded and item.lifecycle_state not in {CandidateLifecycleState.INVALIDATED, CandidateLifecycleState.SUPERSEDED}]
        if len(active) != 1:
            refs = tuple(item.parent_revision_ref for item in active if item.parent_revision_ref is not None)
            return R46CandidateCurrentResolution(candidate_id, None, "CONFLICT", refs)
        item = active[0]
        revision_ref = TypedReference(
            "R4_6_CANDIDATE_REVISION",
            item.revision_id,
            item.revision,
            item.revision,
            item.record_digest,
            item.source_cursor,
            "r4.6",
            item.created_at,
            item.freshness,
            item.availability,
            item.field_validation_state,
            item.correlation_id,
        )
        candidate = R46ValidatedLearningCandidate(candidate_id, self.mission_id, item.owner_stream_key, revision_ref, item, item.revision_digest, item.validation_outcome, item.lifecycle_state, None, None, (), (), (), (), item.revision, "pending", item.as_of_seq, item.source_cursor)
        return R46CandidateCurrentResolution(candidate_id, candidate, "CURRENT")

    def to_dict(self) -> dict[str, Any]:
        return {"mission_id": self.mission_id, "candidate_revisions": [_export(item) for item in self.candidate_revisions], "eligibility_assessments": [_export(item) for item in self.eligibility_assessments], "promotion_requests": [_export(item) for item in self.promotion_requests], "promotion_receipts": [_export(item) for item in self.promotion_receipts], "candidate_dispositions": [_export(item) for item in self.candidate_dispositions]}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R46State":
        return cls(str(value["mission_id"]), tuple(R46CandidateRevision.from_dict(item) for item in value.get("candidate_revisions") or ()), tuple(R46PromotionEligibilityAssessment.from_dict(item) for item in value.get("eligibility_assessments") or ()), tuple(R46KnowledgePromotionRequest.from_dict(item) for item in value.get("promotion_requests") or ()), tuple(R46KnowledgePromotionReceipt.from_dict(item) for item in value.get("promotion_receipts") or ()), tuple(R46CandidateDisposition.from_dict(item) for item in value.get("candidate_dispositions") or ()))


@dataclass(frozen=True)
class R46OperationResult:
    command_result: CommandResult
    entity: Any | None = None

    @property
    def ok(self) -> bool:
        return self.command_result.ok

    @property
    def outcome(self) -> str:
        return self.command_result.outcome

    @property
    def error_code(self) -> str | None:
        return self.command_result.error_code

    @property
    def first_seq(self) -> int | None:
        return self.command_result.first_seq

    @property
    def last_seq(self) -> int | None:
        return self.command_result.last_seq

    @property
    def duplicate_of(self) -> str | None:
        return self.command_result.duplicate_of

    @property
    def state_hash(self) -> str | None:
        return self.command_result.state_hash

    def to_dict(self) -> dict[str, Any]:
        return {**self.command_result.to_dict(), "entity": _export(self.entity)}


def _identity_payload(value: Any) -> Any:
    return _export(value)


def candidate_id_for(candidate_type: Any, normalized_claim_digest: Any, candidate_scope: Any, target_scope: Any) -> str:
    return canonical_sha256({"candidate_type": _identity_payload(candidate_type), "normalized_claim_digest": _identity_payload(normalized_claim_digest), "candidate_scope": _identity_payload(candidate_scope), "target_scope": _identity_payload(target_scope)})


def candidate_revision_id_for(candidate_id: str, parent_revision_ref: Any, candidate_revision_semantics: Any) -> str:
    return canonical_sha256({"candidate_id": candidate_id, "parent_revision_ref": _identity_payload(parent_revision_ref), "candidate_revision_semantics": _identity_payload(candidate_revision_semantics)})


def eligibility_id_for(candidate_revision_ref: Any, candidate_revision_digest: str, policy_digest: str, input_snapshot: Any) -> str:
    return canonical_sha256({"candidate_revision_ref": _identity_payload(candidate_revision_ref), "candidate_revision_digest": candidate_revision_digest, "policy_digest": policy_digest, "input_snapshot": _identity_payload(input_snapshot)})


def promotion_request_id_for(candidate_revision_ref: Any, eligibility_ref: Any, target_scope: Any, requested_status: str, human_gate_linkage: Any) -> str:
    return canonical_sha256({"candidate_revision_ref": _identity_payload(candidate_revision_ref), "eligibility_ref": _identity_payload(eligibility_ref), "target_scope": _identity_payload(target_scope), "requested_status": requested_status, "human_gate_linkage": _identity_payload(human_gate_linkage)})


def receipt_id_for(request_ref: Any, authority_operation_identity: Any, result_digest: str) -> str:
    return canonical_sha256({"request_ref": _identity_payload(request_ref), "authority_operation_identity": _identity_payload(authority_operation_identity), "result_digest": result_digest})


def disposition_id_for(candidate_revision_ref: Any, disposition_kind: Any, trigger_refs: Any, policy_digest: str, source_cursor: int) -> str:
    return canonical_sha256({"candidate_revision_ref": _identity_payload(candidate_revision_ref), "disposition_kind": _identity_payload(disposition_kind), "trigger_refs": _identity_payload(trigger_refs), "policy_digest": policy_digest, "source_cursor": source_cursor})


def record_digest(value: Any) -> str:
    if hasattr(value, "to_dict"):
        raw = dict(value.to_dict())
        raw.pop("record_digest", None)
        raw.pop("created_at", None)
        return canonical_sha256(raw)
    if isinstance(value, Mapping):
        raw = dict(value)
        raw.pop("record_digest", None)
        raw.pop("created_at", None)
        return canonical_sha256(raw)
    return canonical_sha256(value)
