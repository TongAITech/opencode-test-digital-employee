from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Mapping

from aitest_runtime.durable_core import canonical_sha256

from .errors import (
    R45_DIGEST_CONFLICT,
    R45_IDENTITY_CONFLICT,
    R45_SCHEMA_INVALID,
    R45Error,
)


EXTENSION_ID = "r4_5_release_risk_wait_resume_readiness"
EXTENSION_VERSION = "1"
SCHEMA_VERSION = 1

R4_5_EVALUATE_RELEASE_RISK = "R4_5_EVALUATE_RELEASE_RISK.v1"
R4_5_EVALUATE_RELEASE_READINESS = "R4_5_EVALUATE_RELEASE_READINESS.v1"
R4_5_OPEN_RELEASE_WAIT = "R4_5_OPEN_RELEASE_WAIT.v1"
R4_5_RECORD_WAKE_LINKAGE = "R4_5_RECORD_WAKE_LINKAGE.v1"
R4_5_EVALUATE_RESUME_ELIGIBILITY = "R4_5_EVALUATE_RESUME_ELIGIBILITY.v1"
R4_5_RECORD_RESUME_INTENT = "R4_5_RECORD_RESUME_INTENT.v1"
R4_5_RECONCILE_R2_RESUME_RECEIPT = "R4_5_RECONCILE_R2_RESUME_RECEIPT.v1"
R4_5_RECORD_READINESS_DISPOSITION = "R4_5_RECORD_READINESS_DISPOSITION.v1"

COMMAND_TYPES = frozenset(
    {
        R4_5_EVALUATE_RELEASE_RISK,
        R4_5_EVALUATE_RELEASE_READINESS,
        R4_5_OPEN_RELEASE_WAIT,
        R4_5_RECORD_WAKE_LINKAGE,
        R4_5_EVALUATE_RESUME_ELIGIBILITY,
        R4_5_RECORD_RESUME_INTENT,
        R4_5_RECONCILE_R2_RESUME_RECEIPT,
        R4_5_RECORD_READINESS_DISPOSITION,
    }
)

R45_RELEASE_RISK_ASSESSED = "r4.5.release_risk_assessed.v1"
R45_RELEASE_READINESS_ASSESSED = "r4.5.release_readiness_assessed.v1"
R45_RELEASE_WAIT_OPENED = "r4.5.release_wait_opened.v1"
R45_WAKE_LINKAGE_RECORDED = "r4.5.wake_linkage_recorded.v1"
R45_RESUME_ELIGIBILITY_ASSESSED = "r4.5.resume_eligibility_assessed.v1"
R45_RESUME_INTENT_RECORDED = "r4.5.resume_intent_recorded.v1"
R45_R2_RESUME_RECEIPT_RECONCILED = "r4.5.r2_resume_receipt_reconciled.v1"
R45_READINESS_DISPOSITION_RECORDED = "r4.5.readiness_disposition_recorded.v1"

EVENT_TYPES = frozenset(
    {
        R45_RELEASE_RISK_ASSESSED,
        R45_RELEASE_READINESS_ASSESSED,
        R45_RELEASE_WAIT_OPENED,
        R45_WAKE_LINKAGE_RECORDED,
        R45_RESUME_ELIGIBILITY_ASSESSED,
        R45_RESUME_INTENT_RECORDED,
        R45_R2_RESUME_RECEIPT_RECONCILED,
        R45_READINESS_DISPOSITION_RECORDED,
    }
)


class ReleaseRiskOutcome(str, Enum):
    CONFLICT = "CONFLICT"
    STALE = "STALE"
    BLOCKED = "BLOCKED"
    INCOMPLETE = "INCOMPLETE"
    RISK_PRESENT = "RISK_PRESENT"
    WITHIN_POLICY = "WITHIN_POLICY"


class ReadinessVerdict(str, Enum):
    READY = "READY"
    NOT_READY = "NOT_READY"
    BLOCKED = "BLOCKED"
    WAITING = "WAITING"


class ReadinessLifecycleState(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class WaitReason(str, Enum):
    CHANGE_REQUIRED = "CHANGE_REQUIRED"
    DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"
    VALIDATION_INCOMPLETE = "VALIDATION_INCOMPLETE"
    SUFFICIENCY_BLOCKED = "SUFFICIENCY_BLOCKED"
    RESOURCE_UNAVAILABLE = "RESOURCE_UNAVAILABLE"
    ENVIRONMENT_UNAVAILABLE = "ENVIRONMENT_UNAVAILABLE"
    HUMAN_GATE_PENDING = "HUMAN_GATE_PENDING"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SOURCE_STALE = "SOURCE_STALE"
    QUOTA_UNAVAILABLE = "QUOTA_UNAVAILABLE"


class ResumeEligibilityOutcome(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    CONFLICT = "CONFLICT"


class ReadinessDisposition(str, Enum):
    REVOKE = "REVOKE"
    STALE = "STALE"
    REEVALUATE = "REEVALUATE"
    PROVENANCE_ONLY = "PROVENANCE_ONLY"


class WaitLifecycleState(str, Enum):
    CURRENT = "CURRENT"
    RESOLVED = "RESOLVED"
    SUPERSEDED = "SUPERSEDED"


class WakeKind(str, Enum):
    R4_2_TRIGGER = "R4_2_TRIGGER"
    CHANGE_IMPACT_CHANGED = "CHANGE_IMPACT_CHANGED"
    DEFECT_CHANGED = "DEFECT_CHANGED"
    FIX_CHANGED = "FIX_CHANGED"
    POST_FIX_VALIDATION_CHANGED = "POST_FIX_VALIDATION_CHANGED"
    TEST_SUFFICIENCY_CHANGED = "TEST_SUFFICIENCY_CHANGED"
    DEPLOYMENT_CHANGED = "DEPLOYMENT_CHANGED"
    ENVIRONMENT_CHANGED = "ENVIRONMENT_CHANGED"
    RESOURCE_RECOVERED = "RESOURCE_RECOVERED"
    HUMAN_GATE_RESOLVED = "HUMAN_GATE_RESOLVED"
    MANUAL_REASSESSMENT = "MANUAL_REASSESSMENT"


class R2ResumeReceiptStatus(str, Enum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class R45FieldValidationState(str, Enum):
    PASSED = "PASSED"
    PENDING = "PENDING"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ScopedReferenceAccessMode(str, Enum):
    LOCAL = "LOCAL"
    READ_ONLY_CROSS_MISSION = "READ_ONLY_CROSS_MISSION"


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R45Error(R45_SCHEMA_INVALID, f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _digest(value: Any, name: str) -> str:
    text = _text(value, name).lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise R45Error(R45_SCHEMA_INVALID, f"{name} must be a lowercase SHA-256 digest")
    return text


def _seq(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise R45Error(R45_SCHEMA_INVALID, f"{name} must be an integer >= {minimum}")
    return value


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as exc:
        raise R45Error(R45_SCHEMA_INVALID, f"{name} is invalid") from exc


def _json(value: Any, name: str = "value") -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise R45Error(R45_SCHEMA_INVALID, f"{name} object keys must be strings")
            result[key] = _json(item, f"{name}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return tuple(_json(item, f"{name}[]") for item in value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json(value.to_dict(), name)
    raise R45Error(R45_SCHEMA_INVALID, f"{name} contains an unsupported value")


def _export(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _export(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_export(item) for item in value]
    return value


def _tuple_text(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise R45Error(R45_SCHEMA_INVALID, f"{name} must be an array")
    result = tuple(_text(item, f"{name}[]") for item in value)
    if len(result) != len(set(result)):
        raise R45Error(R45_SCHEMA_INVALID, f"{name} must contain unique values")
    return result


def _strict(value: Mapping[str, Any], required: set[str], optional: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R45Error(R45_SCHEMA_INVALID, f"{name} must be an object")
    raw = dict(value)
    missing = required - set(raw)
    unknown = set(raw) - required - optional
    if missing or unknown:
        raise R45Error(
            R45_SCHEMA_INVALID,
            f"{name} has invalid fields",
            {"missing": sorted(missing), "unknown": sorted(unknown)},
        )
    return raw


def _reference(value: Any, name: str, *, optional: bool = False) -> "ScopedReference | None":
    if value is None and optional:
        return None
    if isinstance(value, ScopedReference):
        return value
    return ScopedReference.from_dict(value)


def _references(value: Any, name: str) -> tuple["ScopedReference", ...]:
    if not isinstance(value, (list, tuple)):
        raise R45Error(R45_SCHEMA_INVALID, f"{name} must be an array")
    return tuple(_reference(item, f"{name}[]") for item in value)


def _finish_id(obj: Any, field_name: str, expected: str, supplied: str | None) -> None:
    if supplied in (None, "", "pending"):
        object.__setattr__(obj, field_name, expected)
    elif supplied != expected:
        raise R45Error(R45_IDENTITY_CONFLICT, f"{field_name} does not match its canonical identity")


def _finish_digest(obj: Any, field_name: str, body: Mapping[str, Any], supplied: str | None) -> None:
    expected = canonical_sha256(body)
    if supplied not in (None, "", expected):
        raise R45Error(R45_DIGEST_CONFLICT, f"{field_name} does not match its immutable record")
    object.__setattr__(obj, field_name, expected)


def _field_body(obj: Any, digest_name: str) -> dict[str, Any]:
    return {
        item.name: _export(getattr(obj, item.name))
        for item in fields(obj)
        if item.name != digest_name
    }


def normalize_field_validation_state(value: Any) -> R45FieldValidationState:
    """Normalize representation only; this never upgrades PENDING to PASSED."""
    if isinstance(value, str):
        value = value.upper()
    return _enum(R45FieldValidationState, value, "field_validation_state")  # type: ignore[return-value]


@dataclass(frozen=True)
class ScopedReference:
    ref_kind: str
    stream_owner_mission_id: str
    object_id: str
    object_revision: str | int
    object_digest: str
    source_seq: int
    access_mode: ScopedReferenceAccessMode | str
    source_cursor: int | None = None
    source_stream_key: str | None = None
    relation_kind: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref_kind", _text(self.ref_kind, "ref_kind"))
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        object.__setattr__(self, "object_id", _text(self.object_id, "object_id"))
        if not isinstance(self.object_revision, (str, int)) or isinstance(self.object_revision, bool):
            raise R45Error(R45_SCHEMA_INVALID, "object_revision must be a string or integer")
        if isinstance(self.object_revision, str):
            object.__setattr__(self, "object_revision", _text(self.object_revision, "object_revision"))
        object.__setattr__(self, "object_digest", _digest(self.object_digest, "object_digest"))
        object.__setattr__(self, "source_seq", _seq(self.source_seq, "source_seq"))
        object.__setattr__(self, "access_mode", _enum(ScopedReferenceAccessMode, self.access_mode, "access_mode"))
        if self.source_cursor is not None:
            object.__setattr__(self, "source_cursor", _seq(self.source_cursor, "source_cursor"))
        object.__setattr__(self, "source_stream_key", _optional_text(self.source_stream_key, "source_stream_key"))
        object.__setattr__(self, "relation_kind", _optional_text(self.relation_kind, "relation_kind"))

    def to_dict(self) -> dict[str, Any]:
        value = {
            "ref_kind": self.ref_kind,
            "stream_owner_mission_id": self.stream_owner_mission_id,
            "object_id": self.object_id,
            "object_revision": self.object_revision,
            "object_digest": self.object_digest,
            "source_seq": self.source_seq,
            "access_mode": self.access_mode.value,
        }
        if self.source_cursor is not None:
            value["source_cursor"] = self.source_cursor
        if self.source_stream_key is not None:
            value["source_stream_key"] = self.source_stream_key
        if self.relation_kind is not None:
            value["relation_kind"] = self.relation_kind
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ScopedReference":
        raw = _strict(
            value,
            {"ref_kind", "stream_owner_mission_id", "object_id", "object_revision", "object_digest", "source_seq", "access_mode"},
            {"source_cursor", "source_stream_key", "relation_kind"},
            "ScopedReference",
        )
        return cls(**raw)


@dataclass(frozen=True)
class ReleaseScope:
    scope_id: str
    stream_owner_mission_id: str
    scope_kind: str
    revision: str | int
    scope_digest: str
    source_cursor: int | None = None
    referenced_mission_ids: tuple[str, ...] = ()
    source_refs: tuple[ScopedReference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_id", _text(self.scope_id, "scope_id"))
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        object.__setattr__(self, "scope_kind", _text(self.scope_kind, "scope_kind"))
        if not isinstance(self.revision, (str, int)) or isinstance(self.revision, bool):
            raise R45Error(R45_SCHEMA_INVALID, "revision must be a string or integer")
        if isinstance(self.revision, str):
            object.__setattr__(self, "revision", _text(self.revision, "revision"))
        object.__setattr__(self, "scope_digest", _digest(self.scope_digest, "scope_digest"))
        if self.source_cursor is not None:
            object.__setattr__(self, "source_cursor", _seq(self.source_cursor, "source_cursor"))
        object.__setattr__(self, "referenced_mission_ids", _tuple_text(self.referenced_mission_ids, "referenced_mission_ids"))
        object.__setattr__(self, "source_refs", _references(self.source_refs, "source_refs"))

    def to_dict(self) -> dict[str, Any]:
        value = {
            "scope_id": self.scope_id,
            "stream_owner_mission_id": self.stream_owner_mission_id,
            "scope_kind": self.scope_kind,
            "revision": self.revision,
            "scope_digest": self.scope_digest,
        }
        if self.source_cursor is not None:
            value["source_cursor"] = self.source_cursor
        if self.referenced_mission_ids:
            value["referenced_mission_ids"] = list(self.referenced_mission_ids)
        if self.source_refs:
            value["source_refs"] = [item.to_dict() for item in self.source_refs]
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReleaseScope":
        raw = _strict(
            value,
            {"scope_id", "stream_owner_mission_id", "scope_kind", "revision", "scope_digest"},
            {"source_cursor", "referenced_mission_ids", "source_refs"},
            "ReleaseScope",
        )
        return cls(**raw)


@dataclass(frozen=True)
class PolicySnapshot:
    policy_id: str
    policy_version: str
    policy_digest: str
    scope: ReleaseScope
    effective_boundary: Any
    deterministic_rule_provenance: Any
    required_input_classes: tuple[str, ...]
    conditional_input_classes: tuple[str, ...]
    approval_requirements: Any
    field_validation_requirement: Any
    as_of_cursor: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        object.__setattr__(self, "policy_version", _text(self.policy_version, "policy_version"))
        object.__setattr__(self, "policy_digest", _digest(self.policy_digest, "policy_digest"))
        object.__setattr__(self, "scope", self.scope if isinstance(self.scope, ReleaseScope) else ReleaseScope.from_dict(self.scope))
        object.__setattr__(self, "effective_boundary", _json(self.effective_boundary, "effective_boundary"))
        object.__setattr__(self, "deterministic_rule_provenance", _json(self.deterministic_rule_provenance, "deterministic_rule_provenance"))
        object.__setattr__(self, "required_input_classes", _tuple_text(self.required_input_classes, "required_input_classes"))
        object.__setattr__(self, "conditional_input_classes", _tuple_text(self.conditional_input_classes, "conditional_input_classes"))
        object.__setattr__(self, "approval_requirements", _json(self.approval_requirements, "approval_requirements"))
        object.__setattr__(self, "field_validation_requirement", _json(self.field_validation_requirement, "field_validation_requirement"))
        object.__setattr__(self, "as_of_cursor", _seq(self.as_of_cursor, "as_of_cursor"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_digest": self.policy_digest,
            "scope": self.scope.to_dict(),
            "effective_boundary": _export(self.effective_boundary),
            "deterministic_rule_provenance": _export(self.deterministic_rule_provenance),
            "required_input_classes": list(self.required_input_classes),
            "conditional_input_classes": list(self.conditional_input_classes),
            "approval_requirements": _export(self.approval_requirements),
            "field_validation_requirement": _export(self.field_validation_requirement),
            "as_of_cursor": self.as_of_cursor,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PolicySnapshot":
        required = {
            "policy_id", "policy_version", "policy_digest", "scope", "effective_boundary",
            "deterministic_rule_provenance", "required_input_classes", "conditional_input_classes",
            "approval_requirements", "field_validation_requirement", "as_of_cursor",
        }
        return cls(**_strict(value, required, set(), "PolicySnapshot"))


@dataclass(frozen=True)
class InputSnapshot:
    snapshot_id: str
    stream_owner_mission_id: str
    release_scope: ReleaseScope
    source_refs: tuple[ScopedReference, ...]
    source_digests: tuple[str, ...]
    freshness: str
    availability: str
    field_validation_state: R45FieldValidationState | str
    policy_identity: Any
    remaining_risk_refs: tuple[ScopedReference, ...]
    blocked_refs: tuple[ScopedReference, ...]
    unknown_refs: tuple[ScopedReference, ...]
    conflict_refs: tuple[ScopedReference, ...]
    as_of_seq: int
    source_cursor: int
    snapshot_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", _text(self.snapshot_id, "snapshot_id"))
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        object.__setattr__(self, "release_scope", self.release_scope if isinstance(self.release_scope, ReleaseScope) else ReleaseScope.from_dict(self.release_scope))
        object.__setattr__(self, "source_refs", _references(self.source_refs, "source_refs"))
        object.__setattr__(self, "source_digests", tuple(_digest(item, "source_digests[]") for item in self.source_digests))
        object.__setattr__(self, "freshness", _text(self.freshness, "freshness").upper())
        object.__setattr__(self, "availability", _text(self.availability, "availability").upper())
        object.__setattr__(self, "field_validation_state", normalize_field_validation_state(self.field_validation_state))
        object.__setattr__(self, "policy_identity", _json(self.policy_identity, "policy_identity"))
        for name in ("remaining_risk_refs", "blocked_refs", "unknown_refs", "conflict_refs"):
            object.__setattr__(self, name, _references(getattr(self, name), name))
        object.__setattr__(self, "as_of_seq", _seq(self.as_of_seq, "as_of_seq"))
        object.__setattr__(self, "source_cursor", _seq(self.source_cursor, "source_cursor"))
        _finish_digest(self, "snapshot_digest", _field_body(self, "snapshot_digest"), self.snapshot_digest)

    def to_dict(self) -> dict[str, Any]:
        return {**_field_body(self, "snapshot_digest"), "snapshot_digest": self.snapshot_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InputSnapshot":
        required = {
            "snapshot_id", "stream_owner_mission_id", "release_scope", "source_refs", "source_digests",
            "freshness", "availability", "field_validation_state", "policy_identity", "remaining_risk_refs",
            "blocked_refs", "unknown_refs", "conflict_refs", "as_of_seq", "source_cursor", "snapshot_digest",
        }
        return cls(**_strict(value, required, set(), "InputSnapshot"))


@dataclass(frozen=True)
class HumanGateLinkage:
    gate_ref: ScopedReference
    gate_id: str
    gate_revision: str | int
    decision_outcome: str
    decision_digest: str
    continuation_revision: str | int
    continuation_state: str
    continuation_route: str
    continuation_reference: ScopedReference | None
    actor_ref: ScopedReference
    policy_ref: ScopedReference
    source_cursor: int
    expiry_ref: ScopedReference | None = None
    review_ref: ScopedReference | None = None

    def __post_init__(self) -> None:
        for name in ("gate_ref", "actor_ref", "policy_ref"):
            object.__setattr__(self, name, _reference(getattr(self, name), name))
        object.__setattr__(self, "gate_id", _text(self.gate_id, "gate_id"))
        if not isinstance(self.gate_revision, (str, int)) or isinstance(self.gate_revision, bool):
            raise R45Error(R45_SCHEMA_INVALID, "gate_revision must be a string or integer")
        if isinstance(self.gate_revision, str):
            object.__setattr__(self, "gate_revision", _text(self.gate_revision, "gate_revision"))
        object.__setattr__(self, "decision_outcome", _text(self.decision_outcome, "decision_outcome").upper())
        object.__setattr__(self, "decision_digest", _digest(self.decision_digest, "decision_digest"))
        if not isinstance(self.continuation_revision, (str, int)) or isinstance(self.continuation_revision, bool):
            raise R45Error(R45_SCHEMA_INVALID, "continuation_revision must be a string or integer")
        if isinstance(self.continuation_revision, str):
            object.__setattr__(self, "continuation_revision", _text(self.continuation_revision, "continuation_revision"))
        object.__setattr__(self, "continuation_state", _text(self.continuation_state, "continuation_state").upper())
        object.__setattr__(self, "continuation_route", _text(self.continuation_route, "continuation_route"))
        object.__setattr__(self, "continuation_reference", _reference(self.continuation_reference, "continuation_reference", optional=True))
        object.__setattr__(self, "expiry_ref", _reference(self.expiry_ref, "expiry_ref", optional=True))
        object.__setattr__(self, "review_ref", _reference(self.review_ref, "review_ref", optional=True))
        object.__setattr__(self, "source_cursor", _seq(self.source_cursor, "source_cursor"))

    def to_dict(self) -> dict[str, Any]:
        return _field_body(self, "__none__")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HumanGateLinkage":
        required = {
            "gate_ref", "gate_id", "gate_revision", "decision_outcome", "decision_digest", "continuation_revision",
            "continuation_state", "continuation_route", "continuation_reference", "actor_ref", "policy_ref", "source_cursor",
        }
        return cls(**_strict(value, required, {"expiry_ref", "review_ref"}, "HumanGateLinkage"))


@dataclass(frozen=True)
class R2ResumeTarget:
    stream_owner_mission_id: str
    rotation_operation_id: str
    predecessor_session_id: str
    successor_session_id: str
    predecessor_attempt_id: str
    execution_attempt_id: str
    task_id: str
    plan_id: str
    plan_revision_id: str
    expected_seq: int
    root_attempt_id: str | None = None
    policy_id: str | None = None
    policy_version: str | None = None
    knowledge_scope: Any = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        for name in (
            "rotation_operation_id", "predecessor_session_id", "successor_session_id", "predecessor_attempt_id",
            "execution_attempt_id", "task_id", "plan_id", "plan_revision_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "expected_seq", _seq(self.expected_seq, "expected_seq"))
        for name in ("root_attempt_id", "policy_id", "policy_version"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        object.__setattr__(self, "knowledge_scope", _json(self.knowledge_scope, "knowledge_scope"))

    def to_dict(self) -> dict[str, Any]:
        value = _field_body(self, "__none__")
        return {key: value[key] for key in value if value[key] is not None}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R2ResumeTarget":
        required = {
            "stream_owner_mission_id", "rotation_operation_id", "predecessor_session_id", "successor_session_id",
            "predecessor_attempt_id", "execution_attempt_id", "task_id", "plan_id", "plan_revision_id", "expected_seq",
        }
        return cls(**_strict(value, required, {"root_attempt_id", "policy_id", "policy_version", "knowledge_scope"}, "R2ResumeTarget"))


@dataclass(frozen=True)
class ReleaseRiskAssessment:
    risk_assessment_id: str
    stream_owner_mission_id: str
    release_scope: ReleaseScope
    revision: str | int
    outcome: ReleaseRiskOutcome | str
    policy_snapshot: PolicySnapshot
    input_snapshot: InputSnapshot
    blocking_refs: tuple[ScopedReference, ...]
    unknown_refs: tuple[ScopedReference, ...]
    conflict_refs: tuple[ScopedReference, ...]
    source_refs: tuple[ScopedReference, ...]
    as_of_seq: int
    source_cursor: int
    correlation_id: str
    causation_id: str
    created_by: Any
    created_seq: int
    created_at: str
    record_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        object.__setattr__(self, "release_scope", self.release_scope if isinstance(self.release_scope, ReleaseScope) else ReleaseScope.from_dict(self.release_scope))
        object.__setattr__(self, "revision", self.revision if isinstance(self.revision, int) else _text(self.revision, "revision"))
        object.__setattr__(self, "outcome", _enum(ReleaseRiskOutcome, self.outcome, "outcome"))
        object.__setattr__(self, "policy_snapshot", self.policy_snapshot if isinstance(self.policy_snapshot, PolicySnapshot) else PolicySnapshot.from_dict(self.policy_snapshot))
        object.__setattr__(self, "input_snapshot", self.input_snapshot if isinstance(self.input_snapshot, InputSnapshot) else InputSnapshot.from_dict(self.input_snapshot))
        for name in ("blocking_refs", "unknown_refs", "conflict_refs", "source_refs"):
            object.__setattr__(self, name, _references(getattr(self, name), name))
        for name in ("as_of_seq", "source_cursor", "created_seq"):
            object.__setattr__(self, name, _seq(getattr(self, name), name))
        for name in ("correlation_id", "causation_id", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "created_by", _json(self.created_by, "created_by"))
        expected = risk_revision_id(self.stream_owner_mission_id, self.release_scope, self.input_snapshot, self.policy_snapshot, self.source_cursor)
        _finish_id(self, "risk_assessment_id", expected, self.risk_assessment_id)
        _finish_digest(self, "record_digest", _field_body(self, "record_digest"), self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {**_field_body(self, "record_digest"), "record_digest": self.record_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReleaseRiskAssessment":
        required = {
            "risk_assessment_id", "stream_owner_mission_id", "release_scope", "revision", "outcome", "policy_snapshot",
            "input_snapshot", "blocking_refs", "unknown_refs", "conflict_refs", "source_refs", "as_of_seq", "source_cursor",
            "correlation_id", "causation_id", "created_by", "created_seq", "created_at", "record_digest",
        }
        return cls(**_strict(value, required, set(), "ReleaseRiskAssessment"))


@dataclass(frozen=True)
class ReleaseReadinessAssessment:
    readiness_assessment_id: str
    stream_owner_mission_id: str
    release_scope: ReleaseScope
    revision: str | int
    risk_assessment_ref: ScopedReference
    verdict: ReadinessVerdict | str
    lifecycle_state: ReadinessLifecycleState | str
    current_r3_7_decision_ref: ScopedReference
    current_r4_4_closure_ref: ScopedReference
    current_quality_version_ref: ScopedReference
    current_campaign_ref: ScopedReference
    current_selection_revision_ref: ScopedReference
    deployment_ref: ScopedReference
    environment_ref: ScopedReference
    policy_snapshot: PolicySnapshot
    human_gate_linkage: HumanGateLinkage
    field_validation_state: R45FieldValidationState | str
    source_freshness: str
    source_availability: str
    unresolved_conflict_refs: tuple[ScopedReference, ...]
    unresolved_blocker_refs: tuple[ScopedReference, ...]
    as_of_seq: int
    source_cursor: int
    correlation_id: str
    causation_id: str
    created_by: Any
    created_seq: int
    created_at: str
    record_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        object.__setattr__(self, "release_scope", self.release_scope if isinstance(self.release_scope, ReleaseScope) else ReleaseScope.from_dict(self.release_scope))
        object.__setattr__(self, "revision", self.revision if isinstance(self.revision, int) else _text(self.revision, "revision"))
        object.__setattr__(self, "risk_assessment_ref", _reference(self.risk_assessment_ref, "risk_assessment_ref"))
        object.__setattr__(self, "verdict", _enum(ReadinessVerdict, self.verdict, "verdict"))
        object.__setattr__(self, "lifecycle_state", _enum(ReadinessLifecycleState, self.lifecycle_state, "lifecycle_state"))
        for name in (
            "current_r3_7_decision_ref", "current_r4_4_closure_ref", "current_quality_version_ref", "current_campaign_ref",
            "current_selection_revision_ref", "deployment_ref", "environment_ref",
        ):
            object.__setattr__(self, name, _reference(getattr(self, name), name))
        object.__setattr__(self, "policy_snapshot", self.policy_snapshot if isinstance(self.policy_snapshot, PolicySnapshot) else PolicySnapshot.from_dict(self.policy_snapshot))
        object.__setattr__(self, "human_gate_linkage", self.human_gate_linkage if isinstance(self.human_gate_linkage, HumanGateLinkage) else HumanGateLinkage.from_dict(self.human_gate_linkage))
        object.__setattr__(self, "field_validation_state", normalize_field_validation_state(self.field_validation_state))
        object.__setattr__(self, "source_freshness", _text(self.source_freshness, "source_freshness").upper())
        object.__setattr__(self, "source_availability", _text(self.source_availability, "source_availability").upper())
        for name in ("unresolved_conflict_refs", "unresolved_blocker_refs"):
            object.__setattr__(self, name, _references(getattr(self, name), name))
        for name in ("as_of_seq", "source_cursor", "created_seq"):
            object.__setattr__(self, name, _seq(getattr(self, name), name))
        for name in ("correlation_id", "causation_id", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "created_by", _json(self.created_by, "created_by"))
        expected = readiness_revision_id(
            self.stream_owner_mission_id, self.release_scope, self.risk_assessment_ref,
            self.current_r3_7_decision_ref, self.current_r4_4_closure_ref, self.current_quality_version_ref,
            self.current_campaign_ref, self.current_selection_revision_ref, self.deployment_ref, self.environment_ref,
            self.policy_snapshot, self.human_gate_linkage, self.field_validation_state,
            self.source_freshness, self.source_availability, self.source_cursor,
        )
        _finish_id(self, "readiness_assessment_id", expected, self.readiness_assessment_id)
        _finish_digest(self, "record_digest", _field_body(self, "record_digest"), self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {**_field_body(self, "record_digest"), "record_digest": self.record_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReleaseReadinessAssessment":
        required = {
            "readiness_assessment_id", "stream_owner_mission_id", "release_scope", "revision", "risk_assessment_ref", "verdict",
            "lifecycle_state", "current_r3_7_decision_ref", "current_r4_4_closure_ref", "current_quality_version_ref",
            "current_campaign_ref", "current_selection_revision_ref", "deployment_ref", "environment_ref", "policy_snapshot",
            "human_gate_linkage", "field_validation_state", "source_freshness", "source_availability", "unresolved_conflict_refs",
            "unresolved_blocker_refs", "as_of_seq", "source_cursor", "correlation_id", "causation_id", "created_by",
            "created_seq", "created_at", "record_digest",
        }
        return cls(**_strict(value, required, set(), "ReleaseReadinessAssessment"))


@dataclass(frozen=True)
class ReleaseWaitState:
    wait_id: str
    stream_owner_mission_id: str
    release_scope: ReleaseScope
    readiness_revision_ref: ScopedReference
    risk_assessment_ref: ScopedReference
    wait_reason: WaitReason | str
    lifecycle_state: WaitLifecycleState | str
    blocking_refs: tuple[ScopedReference, ...]
    source_refs: tuple[ScopedReference, ...]
    wake_criteria: Any
    policy_snapshot: PolicySnapshot
    created_cursor: int
    as_of_seq: int
    correlation_id: str
    causation_id: str
    created_by: Any
    created_seq: int
    created_at: str
    record_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        object.__setattr__(self, "release_scope", self.release_scope if isinstance(self.release_scope, ReleaseScope) else ReleaseScope.from_dict(self.release_scope))
        object.__setattr__(self, "readiness_revision_ref", _reference(self.readiness_revision_ref, "readiness_revision_ref"))
        object.__setattr__(self, "risk_assessment_ref", _reference(self.risk_assessment_ref, "risk_assessment_ref"))
        object.__setattr__(self, "wait_reason", _enum(WaitReason, self.wait_reason, "wait_reason"))
        object.__setattr__(self, "lifecycle_state", _enum(WaitLifecycleState, self.lifecycle_state, "lifecycle_state"))
        object.__setattr__(self, "blocking_refs", _references(self.blocking_refs, "blocking_refs"))
        object.__setattr__(self, "source_refs", _references(self.source_refs, "source_refs"))
        object.__setattr__(self, "wake_criteria", _json(self.wake_criteria, "wake_criteria"))
        object.__setattr__(self, "policy_snapshot", self.policy_snapshot if isinstance(self.policy_snapshot, PolicySnapshot) else PolicySnapshot.from_dict(self.policy_snapshot))
        for name in ("created_cursor", "as_of_seq", "created_seq"):
            object.__setattr__(self, name, _seq(getattr(self, name), name))
        for name in ("correlation_id", "causation_id", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "created_by", _json(self.created_by, "created_by"))
        expected = wait_id(
            self.stream_owner_mission_id, self.release_scope, self.readiness_revision_ref, self.risk_assessment_ref,
            self.wait_reason, self.blocking_refs, self.source_refs, self.wake_criteria, self.policy_snapshot,
        )
        _finish_id(self, "wait_id", expected, self.wait_id)
        _finish_digest(self, "record_digest", _field_body(self, "record_digest"), self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {**_field_body(self, "record_digest"), "record_digest": self.record_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReleaseWaitState":
        required = {
            "wait_id", "stream_owner_mission_id", "release_scope", "readiness_revision_ref", "risk_assessment_ref", "wait_reason",
            "lifecycle_state", "blocking_refs", "source_refs", "wake_criteria", "policy_snapshot", "created_cursor", "as_of_seq",
            "correlation_id", "causation_id", "created_by", "created_seq", "created_at", "record_digest",
        }
        return cls(**_strict(value, required, set(), "ReleaseWaitState"))


@dataclass(frozen=True)
class WakeLinkage:
    wake_linkage_id: str
    stream_owner_mission_id: str
    release_scope: ReleaseScope
    wait_ref: ScopedReference
    wake_kind: WakeKind | str
    source_ref: ScopedReference
    source_digest: str
    source_cursor: int
    coalescing_key: str
    linkage_state: str
    as_of_seq: int
    correlation_id: str
    causation_id: str
    created_by: Any
    created_seq: int
    created_at: str
    record_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        object.__setattr__(self, "release_scope", self.release_scope if isinstance(self.release_scope, ReleaseScope) else ReleaseScope.from_dict(self.release_scope))
        object.__setattr__(self, "wait_ref", _reference(self.wait_ref, "wait_ref"))
        object.__setattr__(self, "wake_kind", _enum(WakeKind, self.wake_kind, "wake_kind"))
        object.__setattr__(self, "source_ref", _reference(self.source_ref, "source_ref"))
        object.__setattr__(self, "source_digest", _digest(self.source_digest, "source_digest"))
        object.__setattr__(self, "source_cursor", _seq(self.source_cursor, "source_cursor"))
        object.__setattr__(self, "coalescing_key", _text(self.coalescing_key, "coalescing_key"))
        object.__setattr__(self, "linkage_state", _text(self.linkage_state, "linkage_state").upper())
        for name in ("as_of_seq", "created_seq"):
            object.__setattr__(self, name, _seq(getattr(self, name), name))
        for name in ("correlation_id", "causation_id", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "created_by", _json(self.created_by, "created_by"))
        expected = wake_linkage_id(
            self.stream_owner_mission_id, self.release_scope, self.wait_ref, self.wake_kind,
            self.source_ref, self.source_digest, self.source_cursor, self.coalescing_key,
        )
        _finish_id(self, "wake_linkage_id", expected, self.wake_linkage_id)
        _finish_digest(self, "record_digest", _field_body(self, "record_digest"), self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {**_field_body(self, "record_digest"), "record_digest": self.record_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WakeLinkage":
        required = {
            "wake_linkage_id", "stream_owner_mission_id", "release_scope", "wait_ref", "wake_kind", "source_ref",
            "source_digest", "source_cursor", "coalescing_key", "linkage_state", "as_of_seq", "correlation_id",
            "causation_id", "created_by", "created_seq", "created_at", "record_digest",
        }
        return cls(**_strict(value, required, set(), "WakeLinkage"))


@dataclass(frozen=True)
class ResumeEligibilityAssessment:
    eligibility_id: str
    stream_owner_mission_id: str
    release_scope: ReleaseScope
    revision: str | int
    readiness_revision_ref: ScopedReference
    wait_ref: ScopedReference
    wake_refs: tuple[ScopedReference, ...]
    outcome: ResumeEligibilityOutcome | str
    blocking_reason_evaluation: Any
    source_state: Any
    human_gate_refs: tuple[ScopedReference, ...]
    upstream_current_refs: tuple[ScopedReference, ...]
    r2_target: R2ResumeTarget
    eligibility_digest: str | None
    as_of_cursor: int
    as_of_seq: int
    correlation_id: str
    causation_id: str
    created_by: Any
    created_seq: int
    created_at: str
    record_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        object.__setattr__(self, "release_scope", self.release_scope if isinstance(self.release_scope, ReleaseScope) else ReleaseScope.from_dict(self.release_scope))
        object.__setattr__(self, "revision", self.revision if isinstance(self.revision, int) else _text(self.revision, "revision"))
        object.__setattr__(self, "readiness_revision_ref", _reference(self.readiness_revision_ref, "readiness_revision_ref"))
        object.__setattr__(self, "wait_ref", _reference(self.wait_ref, "wait_ref"))
        object.__setattr__(self, "wake_refs", _references(self.wake_refs, "wake_refs"))
        object.__setattr__(self, "outcome", _enum(ResumeEligibilityOutcome, self.outcome, "outcome"))
        object.__setattr__(self, "blocking_reason_evaluation", _json(self.blocking_reason_evaluation, "blocking_reason_evaluation"))
        object.__setattr__(self, "source_state", _json(self.source_state, "source_state"))
        object.__setattr__(self, "human_gate_refs", _references(self.human_gate_refs, "human_gate_refs"))
        object.__setattr__(self, "upstream_current_refs", _references(self.upstream_current_refs, "upstream_current_refs"))
        object.__setattr__(self, "r2_target", self.r2_target if isinstance(self.r2_target, R2ResumeTarget) else R2ResumeTarget.from_dict(self.r2_target))
        if self.eligibility_digest is not None:
            object.__setattr__(self, "eligibility_digest", _digest(self.eligibility_digest, "eligibility_digest"))
        for name in ("as_of_cursor", "as_of_seq", "created_seq"):
            object.__setattr__(self, name, _seq(getattr(self, name), name))
        for name in ("correlation_id", "causation_id", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "created_by", _json(self.created_by, "created_by"))
        expected = eligibility_id(
            self.stream_owner_mission_id, self.release_scope, self.revision, self.readiness_revision_ref,
            self.wait_ref, self.wake_refs, self.r2_target, self.source_state, self.human_gate_refs,
            self.upstream_current_refs, self.as_of_cursor,
        )
        _finish_id(self, "eligibility_id", expected, self.eligibility_id)
        eligibility_body = {
            item.name: _export(getattr(self, item.name))
            for item in fields(self)
            if item.name not in {"eligibility_digest", "record_digest"}
        }
        _finish_digest(self, "eligibility_digest", eligibility_body, self.eligibility_digest)
        _finish_digest(self, "record_digest", _field_body(self, "record_digest"), self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {**_field_body(self, "record_digest"), "record_digest": self.record_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResumeEligibilityAssessment":
        required = {
            "eligibility_id", "stream_owner_mission_id", "release_scope", "revision", "readiness_revision_ref", "wait_ref",
            "wake_refs", "outcome", "blocking_reason_evaluation", "source_state", "human_gate_refs", "upstream_current_refs",
            "r2_target", "eligibility_digest", "as_of_cursor", "as_of_seq", "correlation_id", "causation_id", "created_by",
            "created_seq", "created_at", "record_digest",
        }
        return cls(**_strict(value, required, set(), "ResumeEligibilityAssessment"))


@dataclass(frozen=True)
class ReadinessDispositionLinkage:
    disposition_id: str
    stream_owner_mission_id: str
    release_scope: ReleaseScope
    readiness_ref: ScopedReference
    disposition: ReadinessDisposition | str
    source_refs: tuple[ScopedReference, ...]
    reason: Any
    as_of_seq: int
    source_cursor: int
    correlation_id: str
    causation_id: str
    created_by: Any
    created_seq: int
    created_at: str
    record_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        object.__setattr__(self, "release_scope", self.release_scope if isinstance(self.release_scope, ReleaseScope) else ReleaseScope.from_dict(self.release_scope))
        object.__setattr__(self, "readiness_ref", _reference(self.readiness_ref, "readiness_ref"))
        object.__setattr__(self, "disposition", _enum(ReadinessDisposition, self.disposition, "disposition"))
        object.__setattr__(self, "source_refs", _references(self.source_refs, "source_refs"))
        object.__setattr__(self, "reason", _json(self.reason, "reason"))
        for name in ("as_of_seq", "source_cursor", "created_seq"):
            object.__setattr__(self, name, _seq(getattr(self, name), name))
        for name in ("correlation_id", "causation_id", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "created_by", _json(self.created_by, "created_by"))
        expected = disposition_id(self.stream_owner_mission_id, self.release_scope, self.readiness_ref, self.disposition, self.source_refs, self.reason, self.source_cursor)
        _finish_id(self, "disposition_id", expected, self.disposition_id)
        _finish_digest(self, "record_digest", _field_body(self, "record_digest"), self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {**_field_body(self, "record_digest"), "record_digest": self.record_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReadinessDispositionLinkage":
        required = {
            "disposition_id", "stream_owner_mission_id", "release_scope", "readiness_ref", "disposition", "source_refs",
            "reason", "as_of_seq", "source_cursor", "correlation_id", "causation_id", "created_by", "created_seq",
            "created_at", "record_digest",
        }
        return cls(**_strict(value, required, set(), "ReadinessDispositionLinkage"))


@dataclass(frozen=True)
class R2ResumeIntent:
    resume_intent_id: str
    stream_owner_mission_id: str
    release_scope: ReleaseScope
    revision: str | int
    eligibility_ref: ScopedReference
    readiness_ref: ScopedReference
    wait_ref: ScopedReference
    r2_target: R2ResumeTarget
    r2_authorization_ref: ScopedReference
    continuation_ref: ScopedReference | None
    resume_identity: Any
    idempotency_identity: Any
    intent_provenance: Any
    as_of_seq: int
    source_cursor: int
    correlation_id: str
    causation_id: str
    created_by: Any
    created_seq: int
    created_at: str
    supersedes_ref: ScopedReference | None
    record_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        object.__setattr__(self, "release_scope", self.release_scope if isinstance(self.release_scope, ReleaseScope) else ReleaseScope.from_dict(self.release_scope))
        object.__setattr__(self, "revision", self.revision if isinstance(self.revision, int) else _text(self.revision, "revision"))
        for name in ("eligibility_ref", "readiness_ref", "wait_ref", "r2_authorization_ref"):
            object.__setattr__(self, name, _reference(getattr(self, name), name))
        object.__setattr__(self, "r2_target", self.r2_target if isinstance(self.r2_target, R2ResumeTarget) else R2ResumeTarget.from_dict(self.r2_target))
        object.__setattr__(self, "continuation_ref", _reference(self.continuation_ref, "continuation_ref", optional=True))
        for name in ("resume_identity", "idempotency_identity", "intent_provenance"):
            object.__setattr__(self, name, _json(getattr(self, name), name))
        for name in ("as_of_seq", "source_cursor", "created_seq"):
            object.__setattr__(self, name, _seq(getattr(self, name), name))
        for name in ("correlation_id", "causation_id", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "created_by", _json(self.created_by, "created_by"))
        object.__setattr__(self, "supersedes_ref", _reference(self.supersedes_ref, "supersedes_ref", optional=True))
        expected = resume_intent_id(
            self.stream_owner_mission_id, self.release_scope, self.revision, self.eligibility_ref, self.readiness_ref,
            self.wait_ref, self.r2_target, self.r2_authorization_ref, self.continuation_ref,
            self.resume_identity, self.idempotency_identity,
        )
        _finish_id(self, "resume_intent_id", expected, self.resume_intent_id)
        _finish_digest(self, "record_digest", _field_body(self, "record_digest"), self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {**_field_body(self, "record_digest"), "record_digest": self.record_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R2ResumeIntent":
        required = {
            "resume_intent_id", "stream_owner_mission_id", "release_scope", "revision", "eligibility_ref", "readiness_ref",
            "wait_ref", "r2_target", "r2_authorization_ref", "continuation_ref", "resume_identity", "idempotency_identity",
            "intent_provenance", "as_of_seq", "source_cursor", "correlation_id", "causation_id", "created_by", "created_seq",
            "created_at", "supersedes_ref", "record_digest",
        }
        return cls(**_strict(value, required, set(), "R2ResumeIntent"))


@dataclass(frozen=True)
class R2ResumeReceipt:
    resume_receipt_id: str
    stream_owner_mission_id: str
    release_scope: ReleaseScope
    revision: str | int
    resume_intent_ref: ScopedReference
    receipt_id: str
    receipt_status: R2ResumeReceiptStatus | str
    r2_result_ref: ScopedReference
    r2_result_digest: str
    r2_authorization_ref: ScopedReference
    continuation_ref: ScopedReference | None
    receipt_cursor: int
    receipt_provenance: Any
    reconciled_from_existing_result: bool
    as_of_seq: int
    correlation_id: str
    causation_id: str
    created_by: Any
    created_seq: int
    created_at: str
    record_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        object.__setattr__(self, "release_scope", self.release_scope if isinstance(self.release_scope, ReleaseScope) else ReleaseScope.from_dict(self.release_scope))
        object.__setattr__(self, "revision", self.revision if isinstance(self.revision, int) else _text(self.revision, "revision"))
        object.__setattr__(self, "resume_intent_ref", _reference(self.resume_intent_ref, "resume_intent_ref"))
        object.__setattr__(self, "receipt_id", _text(self.receipt_id, "receipt_id"))
        object.__setattr__(self, "receipt_status", _enum(R2ResumeReceiptStatus, self.receipt_status, "receipt_status"))
        object.__setattr__(self, "r2_result_ref", _reference(self.r2_result_ref, "r2_result_ref"))
        object.__setattr__(self, "r2_result_digest", _digest(self.r2_result_digest, "r2_result_digest"))
        object.__setattr__(self, "r2_authorization_ref", _reference(self.r2_authorization_ref, "r2_authorization_ref"))
        object.__setattr__(self, "continuation_ref", _reference(self.continuation_ref, "continuation_ref", optional=True))
        for name in ("receipt_cursor", "as_of_seq", "created_seq"):
            object.__setattr__(self, name, _seq(getattr(self, name), name))
        if not isinstance(self.reconciled_from_existing_result, bool):
            raise R45Error(R45_SCHEMA_INVALID, "reconciled_from_existing_result must be a boolean")
        object.__setattr__(self, "receipt_provenance", _json(self.receipt_provenance, "receipt_provenance"))
        for name in ("correlation_id", "causation_id", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "created_by", _json(self.created_by, "created_by"))
        expected = resume_receipt_id(
            self.stream_owner_mission_id, self.release_scope, self.revision, self.resume_intent_ref, self.receipt_id,
            self.receipt_status, self.r2_result_ref, self.r2_result_digest, self.r2_authorization_ref, self.continuation_ref,
        )
        _finish_id(self, "resume_receipt_id", expected, self.resume_receipt_id)
        _finish_digest(self, "record_digest", _field_body(self, "record_digest"), self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {**_field_body(self, "record_digest"), "record_digest": self.record_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R2ResumeReceipt":
        required = {
            "resume_receipt_id", "stream_owner_mission_id", "release_scope", "revision", "resume_intent_ref", "receipt_id",
            "receipt_status", "r2_result_ref", "r2_result_digest", "r2_authorization_ref", "continuation_ref", "receipt_cursor",
            "receipt_provenance", "reconciled_from_existing_result", "as_of_seq", "correlation_id", "causation_id", "created_by",
            "created_seq", "created_at", "record_digest",
        }
        return cls(**_strict(value, required, set(), "R2ResumeReceipt"))


@dataclass(frozen=True)
class CurrentReadinessResolution:
    stream_owner_mission_id: str
    release_scope: ReleaseScope
    current_risk_ref: ScopedReference | None
    current_readiness_ref: ScopedReference | None
    current_wait_ref: ScopedReference | None
    current_eligibility_ref: ScopedReference | None
    current_disposition_ref: ScopedReference | None
    resolution_state: str
    resolution_revision: str | int
    resolution_digest: str | None
    as_of_seq: int
    source_cursor: int
    superseded_refs: tuple[ScopedReference, ...] = ()
    revoked_refs: tuple[ScopedReference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        object.__setattr__(self, "release_scope", self.release_scope if isinstance(self.release_scope, ReleaseScope) else ReleaseScope.from_dict(self.release_scope))
        for name in ("current_risk_ref", "current_readiness_ref", "current_wait_ref", "current_eligibility_ref", "current_disposition_ref"):
            object.__setattr__(self, name, _reference(getattr(self, name), name, optional=True))
        object.__setattr__(self, "resolution_state", _text(self.resolution_state, "resolution_state").upper())
        object.__setattr__(self, "resolution_revision", self.resolution_revision if isinstance(self.resolution_revision, int) else _text(self.resolution_revision, "resolution_revision"))
        if self.resolution_digest is not None:
            object.__setattr__(self, "resolution_digest", _digest(self.resolution_digest, "resolution_digest"))
        object.__setattr__(self, "as_of_seq", _seq(self.as_of_seq, "as_of_seq"))
        object.__setattr__(self, "source_cursor", _seq(self.source_cursor, "source_cursor"))
        object.__setattr__(self, "superseded_refs", _references(self.superseded_refs, "superseded_refs"))
        object.__setattr__(self, "revoked_refs", _references(self.revoked_refs, "revoked_refs"))
        _finish_digest(self, "resolution_digest", _field_body(self, "resolution_digest"), self.resolution_digest)

    def to_dict(self) -> dict[str, Any]:
        return {**_field_body(self, "resolution_digest"), "resolution_digest": self.resolution_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CurrentReadinessResolution":
        required = {
            "stream_owner_mission_id", "release_scope", "current_risk_ref", "current_readiness_ref", "current_wait_ref",
            "current_eligibility_ref", "current_disposition_ref", "resolution_state", "resolution_revision", "resolution_digest",
            "as_of_seq", "source_cursor",
        }
        return cls(**_strict(value, required, {"superseded_refs", "revoked_refs"}, "CurrentReadinessResolution"))


def _dict(value: Any) -> dict[str, Any]:
    return _export(value)


def risk_revision_id(stream_owner_mission_id: str, release_scope: ReleaseScope | Mapping[str, Any], input_snapshot: InputSnapshot | Mapping[str, Any], policy_snapshot: PolicySnapshot | Mapping[str, Any], source_cursor: int) -> str:
    return canonical_sha256({
        "stream_owner_mission_id": stream_owner_mission_id,
        "release_scope": _dict(release_scope),
        "input_snapshot": _dict(input_snapshot),
        "policy_snapshot": _dict(policy_snapshot),
        "source_cursor": source_cursor,
    })


def readiness_revision_id(
    stream_owner_mission_id: str, release_scope: ReleaseScope | Mapping[str, Any], risk_assessment_ref: ScopedReference | Mapping[str, Any],
    current_r3_7_decision_ref: ScopedReference | Mapping[str, Any], current_r4_4_closure_ref: ScopedReference | Mapping[str, Any],
    current_quality_version_ref: ScopedReference | Mapping[str, Any], current_campaign_ref: ScopedReference | Mapping[str, Any],
    current_selection_revision_ref: ScopedReference | Mapping[str, Any], deployment_ref: ScopedReference | Mapping[str, Any],
    environment_ref: ScopedReference | Mapping[str, Any], policy_snapshot: PolicySnapshot | Mapping[str, Any],
    human_gate_linkage: HumanGateLinkage | Mapping[str, Any], field_validation_state: R45FieldValidationState | str,
    source_freshness: str, source_availability: str, source_cursor: int,
) -> str:
    return canonical_sha256({
        "stream_owner_mission_id": stream_owner_mission_id,
        "release_scope": _dict(release_scope),
        "risk_assessment_ref": _dict(risk_assessment_ref),
        "current_r3_7_decision_ref": _dict(current_r3_7_decision_ref),
        "current_r4_4_closure_ref": _dict(current_r4_4_closure_ref),
        "current_quality_version_ref": _dict(current_quality_version_ref),
        "current_campaign_ref": _dict(current_campaign_ref),
        "current_selection_revision_ref": _dict(current_selection_revision_ref),
        "deployment_ref": _dict(deployment_ref),
        "environment_ref": _dict(environment_ref),
        "policy_snapshot": _dict(policy_snapshot),
        "human_gate_linkage": _dict(human_gate_linkage),
        "field_validation_state": _export(field_validation_state),
        "source_freshness": source_freshness,
        "source_availability": source_availability,
        "source_cursor": source_cursor,
    })


def wait_id(stream_owner_mission_id: str, release_scope: Any, readiness_revision_ref: Any, risk_assessment_ref: Any, wait_reason: Any, blocking_refs: Any, source_refs: Any, wake_criteria: Any, policy_snapshot: Any) -> str:
    return canonical_sha256({
        "stream_owner_mission_id": stream_owner_mission_id,
        "release_scope": _dict(release_scope),
        "readiness_revision_ref": _dict(readiness_revision_ref),
        "risk_assessment_ref": _dict(risk_assessment_ref),
        "wait_reason": _export(wait_reason),
        "blocking_refs": _export(blocking_refs),
        "source_refs": _export(source_refs),
        "wake_criteria": _export(wake_criteria),
        "policy_snapshot": _dict(policy_snapshot),
    })


def wake_linkage_id(stream_owner_mission_id: str, release_scope: Any, wait_ref: Any, wake_kind: Any, source_ref: Any, source_digest: str, source_cursor: int, coalescing_key: str) -> str:
    return canonical_sha256({
        "stream_owner_mission_id": stream_owner_mission_id,
        "release_scope": _dict(release_scope),
        "wait_ref": _dict(wait_ref),
        "wake_kind": _export(wake_kind),
        "source_ref": _dict(source_ref),
        "source_digest": source_digest,
        "source_cursor": source_cursor,
        "coalescing_key": coalescing_key,
    })


def eligibility_id(stream_owner_mission_id: str, release_scope: Any, revision: Any, readiness_revision_ref: Any, wait_ref: Any, wake_refs: Any, r2_target: Any, source_state: Any, human_gate_refs: Any, upstream_current_refs: Any, as_of_cursor: int) -> str:
    return canonical_sha256({
        "stream_owner_mission_id": stream_owner_mission_id,
        "release_scope": _dict(release_scope),
        "revision": revision,
        "readiness_revision_ref": _dict(readiness_revision_ref),
        "wait_ref": _dict(wait_ref),
        "wake_refs": _export(wake_refs),
        "r2_target": _dict(r2_target),
        "source_state": _export(source_state),
        "human_gate_refs": _export(human_gate_refs),
        "upstream_current_refs": _export(upstream_current_refs),
        "as_of_cursor": as_of_cursor,
    })


def disposition_id(stream_owner_mission_id: str, release_scope: Any, readiness_ref: Any, disposition: Any, source_refs: Any, reason: Any, source_cursor: int) -> str:
    return canonical_sha256({
        "stream_owner_mission_id": stream_owner_mission_id,
        "release_scope": _dict(release_scope),
        "readiness_ref": _dict(readiness_ref),
        "disposition": _export(disposition),
        "source_refs": _export(source_refs),
        "reason": _export(reason),
        "source_cursor": source_cursor,
    })


def resume_intent_id(stream_owner_mission_id: str, release_scope: Any, revision: Any, eligibility_ref: Any, readiness_ref: Any, wait_ref: Any, r2_target: Any, r2_authorization_ref: Any, continuation_ref: Any, resume_identity: Any, idempotency_identity: Any) -> str:
    return canonical_sha256({
        "stream_owner_mission_id": stream_owner_mission_id,
        "release_scope": _dict(release_scope),
        "revision": revision,
        "eligibility_ref": _dict(eligibility_ref),
        "readiness_ref": _dict(readiness_ref),
        "wait_ref": _dict(wait_ref),
        "r2_target": _dict(r2_target),
        "r2_authorization_ref": _dict(r2_authorization_ref),
        "continuation_ref": _dict(continuation_ref) if continuation_ref is not None else None,
        "resume_identity": _export(resume_identity),
        "idempotency_identity": _export(idempotency_identity),
    })


def resume_receipt_id(stream_owner_mission_id: str, release_scope: Any, revision: Any, resume_intent_ref: Any, receipt_id: str, receipt_status: Any, r2_result_ref: Any, r2_result_digest: str, r2_authorization_ref: Any, continuation_ref: Any) -> str:
    return canonical_sha256({
        "stream_owner_mission_id": stream_owner_mission_id,
        "release_scope": _dict(release_scope),
        "revision": revision,
        "resume_intent_ref": _dict(resume_intent_ref),
        "receipt_id": receipt_id,
        "receipt_status": _export(receipt_status),
        "r2_result_ref": _dict(r2_result_ref),
        "r2_result_digest": r2_result_digest,
        "r2_authorization_ref": _dict(r2_authorization_ref),
        "continuation_ref": _dict(continuation_ref) if continuation_ref is not None else None,
    })


def record_digest(value: Any) -> str:
    if hasattr(value, "to_dict"):
        raw = dict(value.to_dict())
    else:
        raw = dict(value)
    raw.pop("record_digest", None)
    return canonical_sha256(raw)


__all__ = [
    "EXTENSION_ID", "EXTENSION_VERSION", "SCHEMA_VERSION", "COMMAND_TYPES", "EVENT_TYPES",
    "R4_5_EVALUATE_RELEASE_RISK", "R4_5_EVALUATE_RELEASE_READINESS", "R4_5_OPEN_RELEASE_WAIT",
    "R4_5_RECORD_WAKE_LINKAGE", "R4_5_EVALUATE_RESUME_ELIGIBILITY", "R4_5_RECORD_RESUME_INTENT",
    "R4_5_RECONCILE_R2_RESUME_RECEIPT", "R4_5_RECORD_READINESS_DISPOSITION",
    "R45_RELEASE_RISK_ASSESSED", "R45_RELEASE_READINESS_ASSESSED", "R45_RELEASE_WAIT_OPENED",
    "R45_WAKE_LINKAGE_RECORDED", "R45_RESUME_ELIGIBILITY_ASSESSED", "R45_RESUME_INTENT_RECORDED",
    "R45_R2_RESUME_RECEIPT_RECONCILED", "R45_READINESS_DISPOSITION_RECORDED",
    "ReleaseRiskOutcome", "ReadinessVerdict", "ReadinessLifecycleState", "WaitReason", "ResumeEligibilityOutcome",
    "ReadinessDisposition", "WaitLifecycleState", "WakeKind", "R2ResumeReceiptStatus", "R45FieldValidationState",
    "ScopedReferenceAccessMode", "ScopedReference", "ReleaseScope", "PolicySnapshot", "InputSnapshot",
    "HumanGateLinkage", "R2ResumeTarget", "ReleaseRiskAssessment", "ReleaseReadinessAssessment", "ReleaseWaitState",
    "WakeLinkage", "ResumeEligibilityAssessment", "ReadinessDispositionLinkage", "R2ResumeIntent", "R2ResumeReceipt",
    "CurrentReadinessResolution", "normalize_field_validation_state", "risk_revision_id", "readiness_revision_id",
    "wait_id", "wake_linkage_id", "eligibility_id", "disposition_id", "resume_intent_id", "resume_receipt_id", "record_digest",
]
