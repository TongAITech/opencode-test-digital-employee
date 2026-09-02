from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Mapping

from aitest_runtime.durable_core import canonical_sha256

from .errors import (
    CASE_NOT_APPROVED,
    CASE_VERSION_CONFLICT,
    EXECUTION_BINDING_MISSING,
    FIX_DETECTION_NOT_READY,
    ORACLE_NOT_APPROVED,
    ORACLE_VERSION_CONFLICT,
    R44Error,
    RESULT_INCOMPLETE,
    VALIDATION_SCOPE_MISMATCH,
)


EXTENSION_ID = "r4_4_fix_validation_targeted_regression_closure"
EXTENSION_VERSION = "1"
SCHEMA_VERSION = 1

R4_4_OPEN_POST_FIX_VALIDATION = "R4_4_OPEN_POST_FIX_VALIDATION.v1"
R4_4_ASSEMBLE_TARGETED_REGRESSION_WORKSET = "R4_4_ASSEMBLE_TARGETED_REGRESSION_WORKSET.v1"
R4_4_RECORD_EXECUTION_LINKAGE = "R4_4_RECORD_EXECUTION_LINKAGE.v1"
R4_4_RECORD_FIX_VALIDATION_ASSESSMENT = "R4_4_RECORD_FIX_VALIDATION_ASSESSMENT.v1"
R4_4_RECORD_REGRESSION_CLOSURE = "R4_4_RECORD_REGRESSION_CLOSURE.v1"
R4_4_REQUEST_R3_SUFFICIENCY_EVALUATION = "R4_4_REQUEST_R3_SUFFICIENCY_EVALUATION.v1"
R4_4_ACK_R3_SUFFICIENCY_EVALUATION = "R4_4_ACK_R3_SUFFICIENCY_EVALUATION.v1"
R4_4_SUPERSEDE_OPERATION = "R4_4_SUPERSEDE_OPERATION.v1"
COMMAND_TYPES = frozenset({
    R4_4_OPEN_POST_FIX_VALIDATION,
    R4_4_ASSEMBLE_TARGETED_REGRESSION_WORKSET,
    R4_4_RECORD_EXECUTION_LINKAGE,
    R4_4_RECORD_FIX_VALIDATION_ASSESSMENT,
    R4_4_RECORD_REGRESSION_CLOSURE,
    R4_4_REQUEST_R3_SUFFICIENCY_EVALUATION,
    R4_4_ACK_R3_SUFFICIENCY_EVALUATION,
    R4_4_SUPERSEDE_OPERATION,
})

R44_POST_FIX_VALIDATION_OPENED = "r4.4.post_fix_validation_opened.v1"
R44_TARGETED_REGRESSION_WORKSET_ASSEMBLED = "r4.4.targeted_regression_workset_assembled.v1"
R44_EXECUTION_LINKAGE_RECORDED = "r4.4.execution_linkage_recorded.v1"
R44_FIX_VALIDATION_ASSESSED = "r4.4.fix_validation_assessed.v1"
R44_REGRESSION_CLOSURE_RECORDED = "r4.4.regression_closure_recorded.v1"
R44_R3_SUFFICIENCY_EVALUATION_REQUESTED = "r4.4.r3_sufficiency_evaluation_requested.v1"
R44_R3_SUFFICIENCY_EVALUATION_ACKNOWLEDGED = "r4.4.r3_sufficiency_evaluation_acknowledged.v1"
R44_OPERATION_SUPERSEDED = "r4.4.operation_superseded.v1"
EVENT_TYPES = frozenset({
    R44_POST_FIX_VALIDATION_OPENED,
    R44_TARGETED_REGRESSION_WORKSET_ASSEMBLED,
    R44_EXECUTION_LINKAGE_RECORDED,
    R44_FIX_VALIDATION_ASSESSED,
    R44_REGRESSION_CLOSURE_RECORDED,
    R44_R3_SUFFICIENCY_EVALUATION_REQUESTED,
    R44_R3_SUFFICIENCY_EVALUATION_ACKNOWLEDGED,
    R44_OPERATION_SUPERSEDED,
})

PROJECTION_TABLES = frozenset({
    "r44_validation_cycles",
    "r44_targeted_regression_worksets",
    "r44_execution_linkages",
    "r44_fix_validation_assessments",
    "r44_regression_closures",
    "r44_sufficiency_handoff_receipts",
})


class FixValidationOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    INCOMPLETE = "INCOMPLETE"
    CONFLICT = "CONFLICT"


class RegressionTrackingState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    READY = "READY"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"


class RegressionClosureOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    INCOMPLETE = "INCOMPLETE"
    CONFLICT = "CONFLICT"


class PostFixOperationalState(str, Enum):
    VALIDATION_PENDING = "VALIDATION_PENDING"
    VALIDATION_BLOCKED = "VALIDATION_BLOCKED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    REGRESSION_PENDING = "REGRESSION_PENDING"
    REGRESSION_RUNNING = "REGRESSION_RUNNING"
    REGRESSION_FAILED = "REGRESSION_FAILED"
    INCOMPLETE = "INCOMPLETE"
    SUPERSEDED = "SUPERSEDED"
    POST_FIX_VALIDATION_COMPLETE = "POST_FIX_VALIDATION_COMPLETE"


class SufficiencyHandoffStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    BLOCKED = "BLOCKED"
    CONFLICT = "CONFLICT"


class ExecutionLinkageStatus(str, Enum):
    PENDING = "PENDING"
    RECONCILED = "RECONCILED"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    CONFLICT = "CONFLICT"


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R44Error("R4_4_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _digest(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value in (None, ""):
        return ""
    value = _text(value, name).lower()
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise R44Error("R4_4_DIGEST_INVALID", f"{name} must be a lowercase SHA-256 digest")
    return value


def _seq(value: Any, name: str = "created_seq") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise R44Error("R4_4_SCHEMA_INVALID", f"{name} must be a non-negative integer")
    return value


def _tuple_text(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise R44Error("R4_4_SCHEMA_INVALID", f"{name} must be an array")
    result = tuple(_text(item, f"{name}[]") for item in value)
    if len(result) != len(set(result)):
        raise R44Error("R4_4_SCHEMA_INVALID", f"{name} must contain unique values")
    return result


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise R44Error("R4_4_SCHEMA_INVALID", f"{name} must be an object")
    return {str(k): v for k, v in value.items()}


def _enum(value: Any, enum_type: type[Enum], name: str) -> Enum:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as exc:
        raise R44Error("R4_4_SCHEMA_INVALID", f"{name} is invalid") from exc


@dataclass(frozen=True)
class ExactReference:
    ref_type: str
    object_id: str
    object_version: str = "1"
    revision: int = 1
    source_digest: str = ""
    source_cursor: int = 0
    origin: str = "r4.4"
    observed_at: str = "unknown"
    freshness: str = "CURRENT"
    availability: str = "AVAILABLE"
    field_validation_state: str = "PASSED"
    correlation_id: str = "r4.4"

    def __post_init__(self) -> None:
        for name in ("ref_type", "object_id", "object_version", "origin", "observed_at", "freshness", "availability", "field_validation_state", "correlation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "revision", max(1, _seq(self.revision, "revision")))
        object.__setattr__(self, "source_cursor", _seq(self.source_cursor, "source_cursor"))
        digest = self.source_digest or canonical_sha256({"ref_type": self.ref_type, "object_id": self.object_id, "object_version": self.object_version, "revision": self.revision})
        object.__setattr__(self, "source_digest", _digest(digest, "source_digest"))

    @property
    def id(self) -> str:
        return self.object_id

    @property
    def digest(self) -> str:
        return self.source_digest

    @property
    def kind(self) -> str:
        return self.ref_type

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref_type": self.ref_type, "object_id": self.object_id, "object_version": self.object_version,
            "revision": self.revision, "source_digest": self.source_digest, "source_cursor": self.source_cursor,
            "origin": self.origin, "observed_at": self.observed_at, "freshness": self.freshness,
            "availability": self.availability, "field_validation_state": self.field_validation_state,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ExactReference":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise R44Error("R4_4_REFERENCE_INVALID", "reference must be an object")
        raw = dict(value)
        return cls(
            ref_type=raw.get("ref_type", raw.get("kind", raw.get("type", "REFERENCE"))),
            object_id=raw.get("object_id", raw.get("ref_id", raw.get("id"))),
            object_version=raw.get("object_version", raw.get("version", "1")),
            revision=raw.get("revision", 1), source_digest=raw.get("source_digest", raw.get("digest", raw.get("fingerprint", ""))),
            source_cursor=raw.get("source_cursor", raw.get("cursor", 0)), origin=raw.get("origin", "r4.4"),
            observed_at=raw.get("observed_at", "unknown"), freshness=raw.get("freshness", "CURRENT"),
            availability=raw.get("availability", "AVAILABLE"), field_validation_state=raw.get("field_validation_state", "PASSED"),
            correlation_id=raw.get("correlation_id", "r4.4"),
        )


Reference = ExactReference
TypedReference = ExactReference


def make_reference(ref_type: str, object_id: str, digest: str | None = None, **kwargs: Any) -> ExactReference:
    return ExactReference(ref_type, object_id, source_digest=digest or "", **kwargs)


def _refs(value: Any, name: str) -> tuple[ExactReference, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise R44Error("R4_4_SCHEMA_INVALID", f"{name} must be an array")
    return tuple(ExactReference.from_dict(item) for item in value)


def _ref(value: Any, name: str, *, required: bool = True) -> ExactReference | None:
    if value is None and not required:
        return None
    return ExactReference.from_dict(value)


def _dicts(value: Any, name: str) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise R44Error("R4_4_SCHEMA_INVALID", f"{name} must be an array")
    return tuple(_mapping(item, f"{name}[]") for item in value)


def _finish(obj: Any, field_name: str, body: Mapping[str, Any], supplied: str | None) -> None:
    expected = canonical_sha256(body)
    if supplied not in (None, "", expected):
        raise R44Error("R4_4_DIGEST_CONFLICT", f"{field_name} does not match immutable object body")
    object.__setattr__(obj, field_name, expected)


@dataclass(frozen=True)
class ExecutableCaseBinding:
    binding_id: str
    case_version_ref: ExactReference
    step_ordinal: int
    step_identity: str
    adapter_kind: str
    capability_id: str
    capability_version: int
    provider_binding_ref: ExactReference
    input_ref: ExactReference
    input_digest: str
    side_effect_policy: str
    environment_refs: tuple[ExactReference, ...] = ()
    config_refs: tuple[ExactReference, ...] = ()
    authorization_refs: tuple[ExactReference, ...] = ()
    human_gate_refs: tuple[ExactReference, ...] = ()
    binding_version: str = "1"
    mapping_provenance: tuple[ExactReference, ...] = ()
    binding_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_id", _text(self.binding_id, "binding_id"))
        object.__setattr__(self, "case_version_ref", _ref(self.case_version_ref, "case_version_ref"))
        object.__setattr__(self, "provider_binding_ref", _ref(self.provider_binding_ref, "provider_binding_ref"))
        object.__setattr__(self, "input_ref", _ref(self.input_ref, "input_ref"))
        object.__setattr__(self, "step_ordinal", _seq(self.step_ordinal, "step_ordinal"))
        for name in ("step_identity", "adapter_kind", "capability_id", "side_effect_policy", "binding_version"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if isinstance(self.capability_version, bool) or not isinstance(self.capability_version, int) or self.capability_version < 1:
            raise R44Error("R4_4_SCHEMA_INVALID", "capability_version must be positive")
        object.__setattr__(self, "input_digest", _digest(self.input_digest, "input_digest"))
        if self.input_digest != self.input_ref.source_digest:
            raise R44Error("R4_4_BINDING_INVALID", "executable binding input digest does not match its exact input reference")
        for name in ("environment_refs", "config_refs", "authorization_refs", "human_gate_refs", "mapping_provenance"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
            if not getattr(self, name):
                raise R44Error("R4_4_BINDING_INVALID", f"executable binding requires {name}")
        body = self.immutable_payload()
        _finish(self, "binding_digest", body, self.binding_digest)

    def immutable_payload(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id, "case_version_ref": self.case_version_ref.to_dict(), "step_ordinal": self.step_ordinal,
            "step_identity": self.step_identity, "adapter_kind": self.adapter_kind, "capability_id": self.capability_id,
            "capability_version": self.capability_version, "provider_binding_ref": self.provider_binding_ref.to_dict(),
            "input_ref": self.input_ref.to_dict(), "input_digest": self.input_digest, "side_effect_policy": self.side_effect_policy,
            "environment_refs": [item.to_dict() for item in self.environment_refs], "config_refs": [item.to_dict() for item in self.config_refs],
            "authorization_refs": [item.to_dict() for item in self.authorization_refs], "human_gate_refs": [item.to_dict() for item in self.human_gate_refs],
            "binding_version": self.binding_version, "mapping_provenance": [item.to_dict() for item in self.mapping_provenance],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.immutable_payload(), "binding_digest": self.binding_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutableCaseBinding":
        raw = dict(value)
        return cls(
            binding_id=raw["binding_id"], case_version_ref=raw["case_version_ref"], step_ordinal=raw.get("step_ordinal", 0),
            step_identity=raw.get("step_identity", raw.get("step_id", "step")), adapter_kind=raw.get("adapter_kind", "UNKNOWN"),
            capability_id=raw.get("capability_id", "capability"), capability_version=raw.get("capability_version", 1),
            provider_binding_ref=raw["provider_binding_ref"], input_ref=raw["input_ref"], input_digest=raw["input_digest"],
            side_effect_policy=raw.get("side_effect_policy", "NONE"), environment_refs=tuple(raw.get("environment_refs") or ()),
            config_refs=tuple(raw.get("config_refs") or ()), authorization_refs=tuple(raw.get("authorization_refs") or ()),
            human_gate_refs=tuple(raw.get("human_gate_refs") or ()), binding_version=raw.get("binding_version", "1"),
            mapping_provenance=tuple(raw.get("mapping_provenance") or ()), binding_digest=raw.get("binding_digest"),
        )


@dataclass(frozen=True)
class ValidationExecutionIntent:
    execution_intent_id: str
    cycle_ref: ExactReference
    case_ref: ExactReference
    oracle_ref: ExactReference
    binding_ref: ExactReference
    target_scope: Mapping[str, Any]
    mission_ref: ExactReference
    plan_ref: ExactReference
    plan_revision_ref: ExactReference
    task_id: str
    dispatch_id: str
    correlation_id: str
    idempotency_key: str
    binding_digest: str
    intent_digest: str | None = None

    def __post_init__(self) -> None:
        for name in ("execution_intent_id", "task_id", "dispatch_id", "correlation_id", "idempotency_key"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("cycle_ref", "case_ref", "oracle_ref", "binding_ref", "mission_ref", "plan_ref", "plan_revision_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        object.__setattr__(self, "target_scope", _mapping(self.target_scope, "target_scope"))
        object.__setattr__(self, "binding_digest", _digest(self.binding_digest, "binding_digest"))
        if self.binding_ref.source_digest != self.binding_digest:
            raise R44Error("R4_4_BINDING_INVALID", "execution intent binding digest does not match its exact binding reference")
        _finish(self, "intent_digest", self.immutable_payload(), self.intent_digest)

    def immutable_payload(self) -> dict[str, Any]:
        return {
            "execution_intent_id": self.execution_intent_id, "cycle_ref": self.cycle_ref.to_dict(), "case_ref": self.case_ref.to_dict(),
            "oracle_ref": self.oracle_ref.to_dict(), "binding_ref": self.binding_ref.to_dict(), "target_scope": dict(self.target_scope),
            "mission_ref": self.mission_ref.to_dict(), "plan_ref": self.plan_ref.to_dict(), "plan_revision_ref": self.plan_revision_ref.to_dict(),
            "task_id": self.task_id, "dispatch_id": self.dispatch_id, "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key, "binding_digest": self.binding_digest,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.immutable_payload(), "intent_digest": self.intent_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValidationExecutionIntent":
        return cls(**dict(value))


@dataclass(frozen=True)
class PostFixValidationCycle:
    cycle_id: str
    stream_owner_mission_id: str
    quality_version_ref: ExactReference
    campaign_ref: ExactReference
    confirmed_defect_lifecycle_ref: ExactReference
    fix_link_ref: ExactReference
    fix_detection_ref: ExactReference
    target_environment_ref: ExactReference
    target_deployment_ref: ExactReference
    target_build_ref: ExactReference | None = None
    validation_case_refs: tuple[ExactReference, ...] = ()
    validation_case_version_digests: tuple[str, ...] = ()
    case_review_refs: tuple[ExactReference, ...] = ()
    execution_readiness_refs: tuple[ExactReference, ...] = ()
    oracle_specification_refs: tuple[ExactReference, ...] = ()
    evidence_requirement_refs: tuple[ExactReference, ...] = ()
    validation_policy_version: str = "r4.4.validation.v1"
    current_operational_state: PostFixOperationalState | str = PostFixOperationalState.VALIDATION_PENDING
    supersedes_cycle_ref: ExactReference | None = None
    origin_lineage: Mapping[str, Any] = field(default_factory=dict)
    created_seq: int = 0
    created_at: str = "pending"
    correlation_id: str = "r4.4"
    cycle_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cycle_id", _text(self.cycle_id, "cycle_id"))
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        for name in ("quality_version_ref", "campaign_ref", "confirmed_defect_lifecycle_ref", "fix_link_ref", "fix_detection_ref", "target_environment_ref", "target_deployment_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        object.__setattr__(self, "target_build_ref", _ref(self.target_build_ref, "target_build_ref", required=False))
        for name in ("validation_case_refs", "case_review_refs", "execution_readiness_refs", "oracle_specification_refs", "evidence_requirement_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        object.__setattr__(self, "validation_case_version_digests", tuple(_digest(item, "validation_case_version_digests[]") for item in (self.validation_case_version_digests or ())))
        if len(self.validation_case_refs) != len(self.validation_case_version_digests):
            raise R44Error("CASE_VERSION_CONFLICT", "cycle case refs and exact case version digests must have equal cardinality")
        if any(item.source_digest != digest for item, digest in zip(self.validation_case_refs, self.validation_case_version_digests)):
            raise R44Error("CASE_VERSION_CONFLICT", "cycle case version digest does not match its exact case reference")
        object.__setattr__(self, "validation_policy_version", _text(self.validation_policy_version, "validation_policy_version"))
        object.__setattr__(self, "current_operational_state", _enum(self.current_operational_state, PostFixOperationalState, "current_operational_state"))
        object.__setattr__(self, "supersedes_cycle_ref", _ref(self.supersedes_cycle_ref, "supersedes_cycle_ref", required=False))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage"))
        object.__setattr__(self, "created_seq", _seq(self.created_seq))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        _finish(self, "cycle_digest", self.immutable_payload(), self.cycle_digest)

    def immutable_payload(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id, "stream_owner_mission_id": self.stream_owner_mission_id,
            "quality_version_ref": self.quality_version_ref.to_dict(), "campaign_ref": self.campaign_ref.to_dict(),
            "confirmed_defect_lifecycle_ref": self.confirmed_defect_lifecycle_ref.to_dict(), "fix_link_ref": self.fix_link_ref.to_dict(),
            "fix_detection_ref": self.fix_detection_ref.to_dict(), "target_environment_ref": self.target_environment_ref.to_dict(),
            "target_deployment_ref": self.target_deployment_ref.to_dict(), "target_build_ref": self.target_build_ref.to_dict() if self.target_build_ref else None,
            "validation_case_refs": [item.to_dict() for item in self.validation_case_refs], "validation_case_version_digests": list(self.validation_case_version_digests),
            "case_review_refs": [item.to_dict() for item in self.case_review_refs], "execution_readiness_refs": [item.to_dict() for item in self.execution_readiness_refs],
            "oracle_specification_refs": [item.to_dict() for item in self.oracle_specification_refs], "evidence_requirement_refs": [item.to_dict() for item in self.evidence_requirement_refs],
            "validation_policy_version": self.validation_policy_version, "supersedes_cycle_ref": self.supersedes_cycle_ref.to_dict() if self.supersedes_cycle_ref else None,
            "origin_lineage": dict(self.origin_lineage),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.immutable_payload(), "current_operational_state": self.current_operational_state.value, "created_seq": self.created_seq, "created_at": self.created_at, "correlation_id": self.correlation_id, "cycle_digest": self.cycle_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PostFixValidationCycle":
        return cls(**dict(value))


@dataclass(frozen=True)
class TargetedRegressionWorkSet:
    workset_id: str
    owner_mission_id: str
    cycle_ref: ExactReference
    quality_version_ref: ExactReference
    campaign_ref: ExactReference
    fix_link_ref: ExactReference
    fix_detection_ref: ExactReference
    coverage_refs: tuple[ExactReference, ...] = ()
    change_impact_refs: tuple[ExactReference, ...] = ()
    reconciliation_refs: tuple[ExactReference, ...] = ()
    test_strategy_refs: tuple[ExactReference, ...] = ()
    impact_assessment_refs: tuple[ExactReference, ...] = ()
    campaign_selection_revision_refs: tuple[ExactReference, ...] = ()
    selected_case_refs: tuple[ExactReference, ...] = ()
    selected_case_version_digests: tuple[str, ...] = ()
    inclusion_basis_refs: tuple[ExactReference, ...] = ()
    unknown_scope_refs: tuple[ExactReference, ...] = ()
    blocked_scope_refs: tuple[ExactReference, ...] = ()
    excluded_scope_refs: tuple[ExactReference, ...] = ()
    selection_policy_version: str = "r4.4.regression-selection.v1"
    selection_as_of_cursor: int = 0
    selection_complete: bool = True
    tracking_state: RegressionTrackingState | str = RegressionTrackingState.NOT_STARTED
    completed_case_refs: tuple[ExactReference, ...] = ()
    failed_case_refs: tuple[ExactReference, ...] = ()
    pending_case_refs: tuple[ExactReference, ...] = ()
    supersedes_workset_ref: ExactReference | None = None
    workset_digest: str | None = None
    created_seq: int = 0
    created_at: str = "pending"
    correlation_id: str = "r4.4"

    def __post_init__(self) -> None:
        object.__setattr__(self, "workset_id", _text(self.workset_id, "workset_id"))
        object.__setattr__(self, "owner_mission_id", _text(self.owner_mission_id, "owner_mission_id"))
        for name in ("cycle_ref", "quality_version_ref", "campaign_ref", "fix_link_ref", "fix_detection_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        for name in ("coverage_refs", "change_impact_refs", "reconciliation_refs", "test_strategy_refs", "impact_assessment_refs", "campaign_selection_revision_refs", "selected_case_refs", "inclusion_basis_refs", "unknown_scope_refs", "blocked_scope_refs", "excluded_scope_refs", "completed_case_refs", "failed_case_refs", "pending_case_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        object.__setattr__(self, "selected_case_version_digests", tuple(_digest(item, "selected_case_version_digests[]") for item in (self.selected_case_version_digests or ())))
        if len(self.selected_case_refs) != len(self.selected_case_version_digests):
            raise R44Error("CASE_VERSION_CONFLICT", "workset case refs and exact case version digests must have equal cardinality")
        if any(item.source_digest != digest for item, digest in zip(self.selected_case_refs, self.selected_case_version_digests)):
            raise R44Error("CASE_VERSION_CONFLICT", "workset case version digest does not match its exact case reference")
        object.__setattr__(self, "selection_policy_version", _text(self.selection_policy_version, "selection_policy_version"))
        object.__setattr__(self, "selection_as_of_cursor", _seq(self.selection_as_of_cursor, "selection_as_of_cursor"))
        if not isinstance(self.selection_complete, bool):
            raise R44Error("R4_4_SCHEMA_INVALID", "selection_complete must be boolean")
        object.__setattr__(self, "tracking_state", _enum(self.tracking_state, RegressionTrackingState, "tracking_state"))
        object.__setattr__(self, "supersedes_workset_ref", _ref(self.supersedes_workset_ref, "supersedes_workset_ref", required=False))
        object.__setattr__(self, "created_seq", _seq(self.created_seq))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        _finish(self, "workset_digest", self.immutable_payload(), self.workset_digest)

    def immutable_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"workset_id": self.workset_id, "owner_mission_id": self.owner_mission_id}
        for name in ("cycle_ref", "quality_version_ref", "campaign_ref", "fix_link_ref", "fix_detection_ref"):
            payload[name] = getattr(self, name).to_dict()
        for name in ("coverage_refs", "change_impact_refs", "reconciliation_refs", "test_strategy_refs", "impact_assessment_refs", "campaign_selection_revision_refs", "selected_case_refs", "inclusion_basis_refs", "unknown_scope_refs", "blocked_scope_refs", "excluded_scope_refs", "completed_case_refs", "failed_case_refs", "pending_case_refs"):
            payload[name] = [item.to_dict() for item in getattr(self, name)]
        payload.update({"selected_case_version_digests": list(self.selected_case_version_digests), "selection_policy_version": self.selection_policy_version, "selection_as_of_cursor": self.selection_as_of_cursor, "selection_complete": self.selection_complete, "supersedes_workset_ref": self.supersedes_workset_ref.to_dict() if self.supersedes_workset_ref else None})
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {**self.immutable_payload(), "tracking_state": self.tracking_state.value, "workset_digest": self.workset_digest, "created_seq": self.created_seq, "created_at": self.created_at, "correlation_id": self.correlation_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TargetedRegressionWorkSet":
        return cls(**dict(value))


@dataclass(frozen=True)
class ExecutionLinkage:
    linkage_id: str
    cycle_ref: ExactReference
    workset_ref: ExactReference | None
    case_ref: ExactReference
    case_version_digest: str
    oracle_ref: ExactReference
    intent_ref: ExactReference
    binding_ref: ExactReference
    r2_lineage_refs: tuple[ExactReference, ...]
    r1_attempt_refs: tuple[ExactReference, ...]
    tool_execution_refs: tuple[ExactReference, ...]
    evidence_refs: tuple[ExactReference, ...]
    r3_case_execution_attempt_refs: tuple[ExactReference, ...]
    oracle_evaluation_refs: tuple[ExactReference, ...]
    test_result_refs: tuple[ExactReference, ...]
    status: ExecutionLinkageStatus | str = ExecutionLinkageStatus.PENDING
    linkage_digest: str | None = None
    created_seq: int = 0
    created_at: str = "pending"
    correlation_id: str = "r4.4"

    def __post_init__(self) -> None:
        object.__setattr__(self, "linkage_id", _text(self.linkage_id, "linkage_id"))
        object.__setattr__(self, "cycle_ref", _ref(self.cycle_ref, "cycle_ref"))
        object.__setattr__(self, "workset_ref", _ref(self.workset_ref, "workset_ref", required=False))
        object.__setattr__(self, "case_ref", _ref(self.case_ref, "case_ref"))
        object.__setattr__(self, "oracle_ref", _ref(self.oracle_ref, "oracle_ref"))
        object.__setattr__(self, "intent_ref", _ref(self.intent_ref, "intent_ref"))
        object.__setattr__(self, "binding_ref", _ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "case_version_digest", _digest(self.case_version_digest, "case_version_digest"))
        if self.case_version_digest != self.case_ref.source_digest:
            raise R44Error("CASE_VERSION_CONFLICT", "execution linkage case version digest does not match its exact case reference")
        for name in ("r2_lineage_refs", "r1_attempt_refs", "tool_execution_refs", "evidence_refs", "r3_case_execution_attempt_refs", "oracle_evaluation_refs", "test_result_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        object.__setattr__(self, "status", _enum(self.status, ExecutionLinkageStatus, "status"))
        object.__setattr__(self, "created_seq", _seq(self.created_seq))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        _finish(self, "linkage_digest", self.immutable_payload(), self.linkage_digest)

    def immutable_payload(self) -> dict[str, Any]:
        payload = {"linkage_id": self.linkage_id, "cycle_ref": self.cycle_ref.to_dict(), "workset_ref": self.workset_ref.to_dict() if self.workset_ref else None, "case_ref": self.case_ref.to_dict(), "case_version_digest": self.case_version_digest, "oracle_ref": self.oracle_ref.to_dict(), "intent_ref": self.intent_ref.to_dict(), "binding_ref": self.binding_ref.to_dict()}
        for name in ("r2_lineage_refs", "r1_attempt_refs", "tool_execution_refs", "evidence_refs", "r3_case_execution_attempt_refs", "oracle_evaluation_refs", "test_result_refs"):
            payload[name] = [item.to_dict() for item in getattr(self, name)]
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {**self.immutable_payload(), "status": self.status.value, "linkage_digest": self.linkage_digest, "created_seq": self.created_seq, "created_at": self.created_at, "correlation_id": self.correlation_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionLinkage":
        return cls(**dict(value))


@dataclass(frozen=True)
class FixValidationAssessment:
    fix_validation_id: str
    stream_owner_mission_id: str
    cycle_ref: ExactReference
    confirmed_defect_lifecycle_ref: ExactReference
    fix_link_ref: ExactReference
    fix_detection_ref: ExactReference
    quality_version_ref: ExactReference
    campaign_ref: ExactReference
    target_environment_ref: ExactReference
    target_deployment_ref: ExactReference
    validation_case_refs: tuple[ExactReference, ...]
    case_review_refs: tuple[ExactReference, ...]
    oracle_specification_refs: tuple[ExactReference, ...]
    execution_intent_refs: tuple[ExactReference, ...]
    r2_lineage_refs: tuple[ExactReference, ...]
    r1_attempt_refs: tuple[ExactReference, ...]
    tool_execution_refs: tuple[ExactReference, ...]
    evidence_refs: tuple[ExactReference, ...]
    r3_case_execution_attempt_refs: tuple[ExactReference, ...]
    oracle_evaluation_refs: tuple[ExactReference, ...]
    test_result_refs: tuple[ExactReference, ...]
    outcome: FixValidationOutcome | str
    reason_refs: tuple[str, ...] = ()
    freshness: str = "CURRENT"
    availability: str = "AVAILABLE"
    field_validation_state: str = "PASSED"
    validation_policy_version: str = "r4.4.validation.v1"
    admission_ready: bool = False
    case_approved: bool = False
    execution_readiness: str = "UNKNOWN"
    oracle_approved: bool = False
    attempt_status: str = "UNKNOWN"
    oracle_decision: str = "UNKNOWN"
    test_result: str = "UNKNOWN"
    evidence_sufficiency: str = "UNKNOWN"
    lineage_complete: bool = False
    mandatory_cases_passed: bool = False
    human_gate_state: str = "NOT_REQUIRED"
    validation_digest: str | None = None
    created_seq: int = 0
    created_at: str = "pending"
    correlation_id: str = "r4.4"

    def __post_init__(self) -> None:
        for name in ("fix_validation_id", "stream_owner_mission_id", "freshness", "availability", "field_validation_state", "validation_policy_version", "execution_readiness", "attempt_status", "oracle_decision", "test_result", "evidence_sufficiency", "human_gate_state", "created_at", "correlation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("cycle_ref", "confirmed_defect_lifecycle_ref", "fix_link_ref", "fix_detection_ref", "quality_version_ref", "campaign_ref", "target_environment_ref", "target_deployment_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        for name in ("validation_case_refs", "case_review_refs", "oracle_specification_refs", "execution_intent_refs", "r2_lineage_refs", "r1_attempt_refs", "tool_execution_refs", "evidence_refs", "r3_case_execution_attempt_refs", "oracle_evaluation_refs", "test_result_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        object.__setattr__(self, "outcome", _enum(self.outcome, FixValidationOutcome, "outcome"))
        object.__setattr__(self, "reason_refs", _tuple_text(self.reason_refs, "reason_refs"))
        for name in ("admission_ready", "case_approved", "oracle_approved", "lineage_complete", "mandatory_cases_passed"):
            if not isinstance(getattr(self, name), bool):
                raise R44Error("R4_4_SCHEMA_INVALID", f"{name} must be boolean")
        object.__setattr__(self, "created_seq", _seq(self.created_seq))
        _finish(self, "validation_digest", self.immutable_payload(), self.validation_digest)

    def immutable_payload(self) -> dict[str, Any]:
        payload = {"fix_validation_id": self.fix_validation_id, "stream_owner_mission_id": self.stream_owner_mission_id}
        for name in ("cycle_ref", "confirmed_defect_lifecycle_ref", "fix_link_ref", "fix_detection_ref", "quality_version_ref", "campaign_ref", "target_environment_ref", "target_deployment_ref"):
            payload[name] = getattr(self, name).to_dict()
        for name in ("validation_case_refs", "case_review_refs", "oracle_specification_refs", "execution_intent_refs", "r2_lineage_refs", "r1_attempt_refs", "tool_execution_refs", "evidence_refs", "r3_case_execution_attempt_refs", "oracle_evaluation_refs", "test_result_refs"):
            payload[name] = [item.to_dict() for item in getattr(self, name)]
        payload.update({"reason_refs": list(self.reason_refs), "freshness": self.freshness, "availability": self.availability, "field_validation_state": self.field_validation_state, "validation_policy_version": self.validation_policy_version, "admission_ready": self.admission_ready, "case_approved": self.case_approved, "execution_readiness": self.execution_readiness, "oracle_approved": self.oracle_approved, "attempt_status": self.attempt_status, "oracle_decision": self.oracle_decision, "test_result": self.test_result, "evidence_sufficiency": self.evidence_sufficiency, "lineage_complete": self.lineage_complete, "mandatory_cases_passed": self.mandatory_cases_passed, "human_gate_state": self.human_gate_state})
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {**self.immutable_payload(), "outcome": self.outcome.value, "validation_digest": self.validation_digest, "created_seq": self.created_seq, "created_at": self.created_at, "correlation_id": self.correlation_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FixValidationAssessment":
        return cls(**dict(value))

    @property
    def can_pass(self) -> bool:
        required_lineage = (
            "validation_case_refs", "case_review_refs", "oracle_specification_refs", "execution_intent_refs",
            "r2_lineage_refs", "r1_attempt_refs", "tool_execution_refs", "evidence_refs",
            "r3_case_execution_attempt_refs", "oracle_evaluation_refs", "test_result_refs",
        )
        return self.outcome is FixValidationOutcome.PASS and all((
            self.admission_ready, self.freshness == "CURRENT", self.availability == "AVAILABLE", self.field_validation_state == "PASSED",
            self.case_approved, self.execution_readiness == "READY", self.oracle_approved, self.attempt_status == "COMPLETED",
            self.oracle_decision == "PASS", self.test_result == "PASS", self.evidence_sufficiency in {"SUFFICIENT", "VERIFIED"},
            self.lineage_complete, self.mandatory_cases_passed, self.human_gate_state in {"NOT_REQUIRED", "APPROVED", "PASSED"},
            *(bool(getattr(self, name)) for name in required_lineage),
        ))


@dataclass(frozen=True)
class TargetedRegressionClosure:
    closure_id: str
    workset_ref: ExactReference
    cycle_ref: ExactReference
    selected_case_refs: tuple[ExactReference, ...]
    completed_case_refs: tuple[ExactReference, ...]
    failed_case_refs: tuple[ExactReference, ...]
    blocked_case_refs: tuple[ExactReference, ...]
    pending_case_refs: tuple[ExactReference, ...]
    unknown_case_refs: tuple[ExactReference, ...]
    result_refs: tuple[ExactReference, ...]
    outcome: RegressionClosureOutcome | str
    reason_refs: tuple[str, ...] = ()
    selection_complete: bool = True
    current_conflict: bool = False
    closure_digest: str | None = None
    created_seq: int = 0
    created_at: str = "pending"
    correlation_id: str = "r4.4"

    def __post_init__(self) -> None:
        for name in ("closure_id", "created_at", "correlation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("workset_ref", "cycle_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        for name in ("selected_case_refs", "completed_case_refs", "failed_case_refs", "blocked_case_refs", "pending_case_refs", "unknown_case_refs", "result_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        object.__setattr__(self, "outcome", _enum(self.outcome, RegressionClosureOutcome, "outcome"))
        object.__setattr__(self, "reason_refs", _tuple_text(self.reason_refs, "reason_refs"))
        if not isinstance(self.selection_complete, bool) or not isinstance(self.current_conflict, bool):
            raise R44Error("R4_4_SCHEMA_INVALID", "closure boolean fields are invalid")
        object.__setattr__(self, "created_seq", _seq(self.created_seq))
        _finish(self, "closure_digest", self.immutable_payload(), self.closure_digest)

    def immutable_payload(self) -> dict[str, Any]:
        payload = {"closure_id": self.closure_id, "workset_ref": self.workset_ref.to_dict(), "cycle_ref": self.cycle_ref.to_dict()}
        for name in ("selected_case_refs", "completed_case_refs", "failed_case_refs", "blocked_case_refs", "pending_case_refs", "unknown_case_refs", "result_refs"):
            payload[name] = [item.to_dict() for item in getattr(self, name)]
        payload.update({"reason_refs": list(self.reason_refs), "selection_complete": self.selection_complete, "current_conflict": self.current_conflict})
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {**self.immutable_payload(), "outcome": self.outcome.value, "closure_digest": self.closure_digest, "created_seq": self.created_seq, "created_at": self.created_at, "correlation_id": self.correlation_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TargetedRegressionClosure":
        return cls(**dict(value))

    @property
    def can_pass(self) -> bool:
        selected = {canonical_sha256(item.to_dict()) for item in self.selected_case_refs}
        completed = {canonical_sha256(item.to_dict()) for item in self.completed_case_refs}
        failed = {canonical_sha256(item.to_dict()) for item in self.failed_case_refs}
        return self.outcome is RegressionClosureOutcome.PASS and self.selection_complete and not self.blocked_case_refs and not self.pending_case_refs and not self.unknown_case_refs and not self.current_conflict and len(self.completed_case_refs) == len(self.selected_case_refs) and completed == selected and not (completed & failed) and len(self.result_refs) >= len(self.selected_case_refs)


@dataclass(frozen=True)
class SufficiencyHandoffReceipt:
    receipt_id: str
    handoff_request_id: str
    cycle_ref: ExactReference
    workset_ref: ExactReference
    input_digest: str
    input_as_of_cursor: int
    result_refs: tuple[ExactReference, ...]
    evidence_refs: tuple[ExactReference, ...]
    request_status: SufficiencyHandoffStatus | str
    decision_ref: ExactReference | None = None
    decision_digest: str | None = None
    decision_status: str | None = None
    retry_provenance: Mapping[str, Any] = field(default_factory=dict)
    created_seq: int = 0
    created_at: str = "pending"
    correlation_id: str = "r4.4"
    receipt_digest: str | None = None

    def __post_init__(self) -> None:
        for name in ("receipt_id", "handoff_request_id", "created_at", "correlation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("cycle_ref", "workset_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        object.__setattr__(self, "input_digest", _digest(self.input_digest, "input_digest"))
        object.__setattr__(self, "input_as_of_cursor", _seq(self.input_as_of_cursor, "input_as_of_cursor"))
        object.__setattr__(self, "result_refs", _refs(self.result_refs, "result_refs"))
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "request_status", _enum(self.request_status, SufficiencyHandoffStatus, "request_status"))
        object.__setattr__(self, "decision_ref", _ref(self.decision_ref, "decision_ref", required=False))
        if self.decision_digest is not None:
            object.__setattr__(self, "decision_digest", _digest(self.decision_digest, "decision_digest"))
        object.__setattr__(self, "decision_status", _optional_text(self.decision_status, "decision_status"))
        object.__setattr__(self, "retry_provenance", _mapping(self.retry_provenance, "retry_provenance"))
        object.__setattr__(self, "created_seq", _seq(self.created_seq))
        _finish(self, "receipt_digest", self.immutable_payload(), self.receipt_digest)

    def immutable_payload(self) -> dict[str, Any]:
        return {"receipt_id": self.receipt_id, "handoff_request_id": self.handoff_request_id, "cycle_ref": self.cycle_ref.to_dict(), "workset_ref": self.workset_ref.to_dict(), "input_digest": self.input_digest, "input_as_of_cursor": self.input_as_of_cursor, "result_refs": [item.to_dict() for item in self.result_refs], "evidence_refs": [item.to_dict() for item in self.evidence_refs], "decision_ref": self.decision_ref.to_dict() if self.decision_ref else None, "decision_digest": self.decision_digest, "decision_status": self.decision_status, "retry_provenance": dict(self.retry_provenance)}

    def to_dict(self) -> dict[str, Any]:
        return {**self.immutable_payload(), "request_status": self.request_status.value, "created_seq": self.created_seq, "created_at": self.created_at, "correlation_id": self.correlation_id, "receipt_digest": self.receipt_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SufficiencyHandoffReceipt":
        return cls(**dict(value))


def _identity(prefix: str, payload: Any) -> str:
    return f"r4.4:{prefix}:{canonical_sha256(payload)}"


def cycle_id_for(value: Mapping[str, Any] | PostFixValidationCycle) -> str:
    raw = value.immutable_payload() if hasattr(value, "immutable_payload") else dict(value)
    raw = dict(raw)
    raw.pop("cycle_id", None)
    return _identity("cycle", raw)


def workset_id_for(value: Mapping[str, Any] | TargetedRegressionWorkSet) -> str:
    raw = value.immutable_payload() if hasattr(value, "immutable_payload") else dict(value)
    raw = dict(raw)
    raw.pop("workset_id", None)
    return _identity("workset", raw)


def binding_id_for(value: Mapping[str, Any]) -> str:
    raw = dict(value)
    raw.pop("binding_id", None)
    return _identity("binding", raw)


def execution_intent_id_for(value: Mapping[str, Any] | ValidationExecutionIntent) -> str:
    raw = value.immutable_payload() if hasattr(value, "immutable_payload") else dict(value)
    raw = dict(raw)
    raw.pop("execution_intent_id", None)
    return _identity("execution-intent", raw)


def linkage_id_for(value: Mapping[str, Any]) -> str:
    return _identity("linkage", dict(value))


def validation_id_for(value: Mapping[str, Any]) -> str:
    return _identity("fix-validation", dict(value))


def closure_id_for(value: Mapping[str, Any]) -> str:
    return _identity("closure", dict(value))


def admission_ready(
    detection: Mapping[str, Any],
    *,
    target_deployment_ref: ExactReference | Mapping[str, Any],
    target_environment_ref: ExactReference | Mapping[str, Any],
) -> bool:
    detection = dict(detection)
    deployment = ExactReference.from_dict(target_deployment_ref)
    environment = ExactReference.from_dict(target_environment_ref)
    deployments = _refs(detection.get("deployment_refs") or (), "deployment_refs")
    environments = _refs(detection.get("environment_refs") or (), "environment_refs")
    evidence = _refs(detection.get("evidence_refs") or (), "evidence_refs")
    return bool(
        str(detection.get("outcome")) == "DETECTED"
        and str(detection.get("detection_scope")) == "DEPLOYMENT"
        and str(detection.get("freshness")) == "CURRENT"
        and str(detection.get("availability")) == "AVAILABLE"
        and "MANUAL_ATTESTATION" not in {str(item) for item in (detection.get("detection_basis") or ())}
        and any(item.object_id == deployment.object_id and item.source_digest == deployment.source_digest for item in deployments)
        and any(item.object_id == environment.object_id and item.source_digest == environment.source_digest for item in environments)
        and any(item.object_id == deployment.object_id and item.source_digest == deployment.source_digest for item in evidence)
        and any(item.object_id == environment.object_id and item.source_digest == environment.source_digest for item in evidence)
    )


def validate_fix_detection_admission(
    detection: Mapping[str, Any],
    *,
    target_deployment_ref: ExactReference | Mapping[str, Any],
    target_environment_ref: ExactReference | Mapping[str, Any],
) -> dict[str, Any]:
    ready = admission_ready(detection, target_deployment_ref=target_deployment_ref, target_environment_ref=target_environment_ref)
    outcome = str(detection.get("outcome"))
    scope = str(detection.get("detection_scope"))
    code = "REAL_SUT_READY" if ready else (FIX_DETECTION_NOT_READY if outcome in {"NOT_DETECTED", "UNKNOWN", "BLOCKED", "CONFLICT"} or scope != "DEPLOYMENT" else VALIDATION_SCOPE_MISMATCH)
    return {"ready": ready, "code": code, "outcome": outcome, "scope": scope, "blockers": [] if ready else [code]}


def _required_ref_fields(value: Any) -> tuple[str, ...]:
    return tuple(item.name for item in fields(value) if item.name.endswith("_ref") or item.name.endswith("_refs"))


__all__ = [name for name in globals() if not name.startswith("_")]
