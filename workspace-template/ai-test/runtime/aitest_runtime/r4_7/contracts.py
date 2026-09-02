from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Mapping, Protocol

from aitest_runtime.durable_core import ActorRef, CommandResult, canonical_sha256

from .errors import (
    R47_DIGEST_CONFLICT,
    R47_IDENTITY_CONFLICT,
    R47_SCHEMA_INVALID,
    R47Error,
)


EXTENSION_ID = "r4_7_legacy_reconciliation_operational_projections"
EXTENSION_VERSION = "1.0.0"
SCHEMA_VERSION = 1

# The seven commands and seven events are the only R4.7 durable public actions.
R4_7_RECORD_LEGACY_SOURCE_OBSERVATION = "R4_7_RECORD_LEGACY_SOURCE_OBSERVATION.v1"
R4_7_RECORD_RECONCILIATION_ASSESSMENT = "R4_7_RECORD_RECONCILIATION_ASSESSMENT.v1"
R4_7_RECORD_LEGACY_CANONICAL_MAPPING = "R4_7_RECORD_LEGACY_CANONICAL_MAPPING.v1"
R4_7_RECORD_RECONCILIATION_DECISION = "R4_7_RECORD_RECONCILIATION_DECISION.v1"
R4_7_CREATE_CANONICAL_HANDOFF = "R4_7_CREATE_CANONICAL_HANDOFF.v1"
R4_7_SUBMIT_CANONICAL_HANDOFF = "R4_7_SUBMIT_CANONICAL_HANDOFF.v1"
R4_7_RECORD_RECONCILIATION_RECEIPT = "R4_7_RECORD_RECONCILIATION_RECEIPT.v1"

# Compatibility spellings used by the detailed design vocabulary.  They are aliases,
# not additional commands and therefore do not widen the command registry.
R4_7_OBSERVE_LEGACY_SOURCE = R4_7_RECORD_LEGACY_SOURCE_OBSERVATION
R4_7_ASSESS_RECONCILIATION = R4_7_RECORD_RECONCILIATION_ASSESSMENT
R4_7_MAP_LEGACY_CANONICAL = R4_7_RECORD_LEGACY_CANONICAL_MAPPING
R4_7_DECIDE_RECONCILIATION = R4_7_RECORD_RECONCILIATION_DECISION
R4_7_RECONCILE_RECEIPT = R4_7_RECORD_RECONCILIATION_RECEIPT

COMMAND_TYPES = frozenset(
    {
        R4_7_RECORD_LEGACY_SOURCE_OBSERVATION,
        R4_7_RECORD_RECONCILIATION_ASSESSMENT,
        R4_7_RECORD_LEGACY_CANONICAL_MAPPING,
        R4_7_RECORD_RECONCILIATION_DECISION,
        R4_7_CREATE_CANONICAL_HANDOFF,
        R4_7_SUBMIT_CANONICAL_HANDOFF,
        R4_7_RECORD_RECONCILIATION_RECEIPT,
    }
)

R47_LEGACY_SOURCE_OBSERVATION_RECORDED = "r4.7.legacy_source_observation_recorded.v1"
R47_RECONCILIATION_ASSESSMENT_RECORDED = "r4.7.reconciliation_assessment_recorded.v1"
R47_LEGACY_CANONICAL_MAPPING_RECORDED = "r4.7.legacy_canonical_mapping_recorded.v1"
R47_RECONCILIATION_DECISION_RECORDED = "r4.7.reconciliation_decision_recorded.v1"
R47_CANONICAL_HANDOFF_CREATED = "r4.7.canonical_handoff_created.v1"
R47_CANONICAL_HANDOFF_SUBMITTED = "r4.7.canonical_handoff_submitted.v1"
R47_RECONCILIATION_RECEIPT_RECORDED = "r4.7.reconciliation_receipt_recorded.v1"

EVENT_TYPES = frozenset(
    {
        R47_LEGACY_SOURCE_OBSERVATION_RECORDED,
        R47_RECONCILIATION_ASSESSMENT_RECORDED,
        R47_LEGACY_CANONICAL_MAPPING_RECORDED,
        R47_RECONCILIATION_DECISION_RECORDED,
        R47_CANONICAL_HANDOFF_CREATED,
        R47_CANONICAL_HANDOFF_SUBMITTED,
        R47_RECONCILIATION_RECEIPT_RECORDED,
    }
)


class SourceFamily(str, Enum):
    LEGACY_KNOWLEDGE = "LEGACY_KNOWLEDGE"
    LEGACY_TEACHING = "LEGACY_TEACHING"
    LEGACY_SKILL_METADATA = "LEGACY_SKILL_METADATA"
    LEGACY_PROJECT_TRUTH = "LEGACY_PROJECT_TRUTH"
    LEGACY_RUNTIME_STATE = "LEGACY_RUNTIME_STATE"
    LEGACY_DEFECT = "LEGACY_DEFECT"
    LEGACY_TEST_STATE = "LEGACY_TEST_STATE"
    LEGACY_CAMPAIGN_OR_SCHEDULER = "LEGACY_CAMPAIGN_OR_SCHEDULER"
    LEGACY_ARTIFACT = "LEGACY_ARTIFACT"
    LEGACY_MIGRATION_REPORT = "LEGACY_MIGRATION_REPORT"
    LEGACY_LOCAL_CACHE = "LEGACY_LOCAL_CACHE"
    LEGACY_BROWSER_OR_TRACE = "LEGACY_BROWSER_OR_TRACE"
    LEGACY_REFERENCE_FILE = "LEGACY_REFERENCE_FILE"
    UNKNOWN = "UNKNOWN"


class SourceValueState(str, Enum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class SourceAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class SourceFreshness(str, Enum):
    CURRENT = "CURRENT"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"


class ActiveWriterState(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    UNKNOWN = "UNKNOWN"


class AssessmentOutcome(str, Enum):
    MAPPABLE = "MAPPABLE"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    HANDOFF_REQUIRED = "HANDOFF_REQUIRED"
    NO_CANONICAL_TARGET = "NO_CANONICAL_TARGET"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    CONFLICT = "CONFLICT"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    STALE = "STALE"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"


class IdentityRelation(str, Enum):
    EXACT = "EXACT"
    PARTIAL = "PARTIAL"
    DIFFERENT = "DIFFERENT"
    UNKNOWN = "UNKNOWN"


class ScopeRelation(str, Enum):
    EXACT = "EXACT"
    NARROWER = "NARROWER"
    WIDER = "WIDER"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


class ContentRelation(str, Enum):
    SAME_DIGEST = "SAME_DIGEST"
    DIFFERENT_DIGEST = "DIFFERENT_DIGEST"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class MappingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    STALE = "STALE"
    CONFLICTED = "CONFLICTED"


class MappingEvidence(str, Enum):
    EXACT_IDENTITY_AND_DIGEST = "EXACT_IDENTITY_AND_DIGEST"
    EXACT_IDENTITY_ONLY = "EXACT_IDENTITY_ONLY"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    UNRESOLVED = "UNRESOLVED"


class CanonicalAuthority(str, Enum):
    R1 = "R1"
    R2 = "R2"
    R2_6 = "R2_6"
    R3 = "R3"
    R3_E1 = "R3_E1"
    R4_1 = "R4_1"
    R4_2 = "R4_2"
    R4_3 = "R4_3"
    R4_4 = "R4_4"
    R4_5 = "R4_5"
    R4_6 = "R4_6"
    NO_CANONICAL_TARGET = "NO_CANONICAL_TARGET"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class DecisionKind(str, Enum):
    REFERENCE_ONLY = "REFERENCE_ONLY"
    NO_ACTION = "NO_ACTION"
    REQUEST_CANONICAL_HANDOFF = "REQUEST_CANONICAL_HANDOFF"
    RECONCILE_EXISTING = "RECONCILE_EXISTING"
    BLOCK = "BLOCK"
    REJECT = "REJECT"
    REVALIDATE = "REVALIDATE"
    MARK_CONFLICT = "MARK_CONFLICT"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class ReceiptStatus(str, Enum):
    REFERENCE_ONLY = "REFERENCE_ONLY"
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    CONFLICT = "CONFLICT"


class HandoffState(str, Enum):
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    CONFLICT = "CONFLICT"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class HandoffKind(str, Enum):
    KNOWLEDGE_PROMOTION = "KNOWLEDGE_PROMOTION"
    EXISTING_KNOWLEDGE_RECONCILIATION = "EXISTING_KNOWLEDGE_RECONCILIATION"
    REFERENCE_ONLY = "REFERENCE_ONLY"


class ResolutionStatus(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
    CONFLICT = "CONFLICT"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    COMPLETED = "COMPLETED"
    NO_ACTION = "NO_ACTION"


class ShadowTruthStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    NOT_CUT_OVER = "NOT_CUT_OVER"


class ExistingKnowledgeReconciliation(str, Enum):
    SAME = "SAME"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


def _text(value: Any, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise R47Error(R47_SCHEMA_INVALID, f"{name} must be a non-empty string")
    return value.strip()


def _digest(value: Any, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    text = _text(value, name)
    assert text is not None
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text.lower()):
        raise R47Error(R47_SCHEMA_INVALID, f"{name} must be a lowercase SHA-256 digest")
    return text.lower()


def _seq(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise R47Error(R47_SCHEMA_INVALID, f"{name} must be an integer >= {minimum}")
    return value


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as exc:
        raise R47Error(R47_SCHEMA_INVALID, f"{name} is invalid") from exc


def _json(value: Any, name: str = "value") -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return _json(value.to_dict(), name)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise R47Error(R47_SCHEMA_INVALID, f"{name} object keys must be strings")
            result[key] = _json(item, f"{name}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return tuple(_json(item, f"{name}[]") for item in value)
    raise R47Error(R47_SCHEMA_INVALID, f"{name} contains unsupported data")


def _export(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, ActorRef):
        return value.to_dict()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _export(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_export(item) for item in value]
    return value


def _strict(value: Mapping[str, Any], cls_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R47Error(R47_SCHEMA_INVALID, f"{cls_name} must be an object")
    raw = dict(value)
    allowed = {item.name for item in fields(_CLASS_REGISTRY[cls_name])}
    unknown = set(raw) - allowed
    if unknown:
        raise R47Error(R47_SCHEMA_INVALID, f"{cls_name} contains unknown fields", {"unknown": sorted(unknown)})
    return raw


def _optional_mapping(value: Any, name: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    normalized = _json(value, name)
    if not isinstance(normalized, Mapping):
        raise R47Error(R47_SCHEMA_INVALID, f"{name} must be an object")
    return dict(normalized)


def _finish_digest(obj: Any, field_name: str, supplied: str | None, *, excluded: set[str] | None = None) -> None:
    excluded = set(excluded or ()) | {
        field_name,
        "record_digest",
        "created_at",
        "created_seq",
        "created_by",
        "correlation_id",
        "causation_id",
        "owner_stream_key",
    }
    body = {item.name: _export(getattr(obj, item.name)) for item in fields(obj) if item.name not in excluded}
    expected = canonical_sha256(body)
    if supplied not in (None, "", "pending", expected):
        raise R47Error(R47_DIGEST_CONFLICT, f"{field_name} does not match canonical record")
    object.__setattr__(obj, field_name, expected)


def source_identity_key_for(
    source_family: SourceFamily | str,
    source_system_id: str,
    source_object_identity: str | None,
    native_id: str | None,
) -> str:
    return canonical_sha256(
        {
            "source_family": _export(_enum(SourceFamily, source_family, "source_family")),
            "source_system_id": source_system_id,
            "source_object_identity": source_object_identity,
            "native_id": native_id,
        }
    )


def observation_content_digest_for(observation_schema_version: int, source_scope: Mapping[str, Any], normalized_observation: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "observation_schema_version": observation_schema_version,
            "source_scope": _export(source_scope),
            "normalized_observation": _export(normalized_observation),
        }
    )


def observation_id_for(source_identity_key: str, observation_content_digest: str) -> str:
    return "r4.7:observation:" + canonical_sha256({"source_identity_key": source_identity_key, "observation_content_digest": observation_content_digest})


def observation_digest_for(source_identity_key: str, observation_content_digest: str, observation_schema_version: int) -> str:
    return "r4.7:observation-digest:" + canonical_sha256(
        {
            "source_identity_key": source_identity_key,
            "observation_content_digest": observation_content_digest,
            "observation_schema_version": observation_schema_version,
        }
    )


def source_identity_key(value: SourceSelector | Mapping[str, Any]) -> str:
    if isinstance(value, SourceSelector):
        return value.source_identity_key
    return source_identity_key_for(value["source_family"], str(value["source_system_id"]), value.get("source_object_identity"), value.get("native_id"))


def observation_content_digest(value: LegacySourceObservationInput | Mapping[str, Any]) -> str:
    if isinstance(value, LegacySourceObservationInput):
        return value.observation_content_digest or ""
    return observation_content_digest_for(int(value.get("observation_schema_version", SCHEMA_VERSION)), dict(value.get("source_scope") or {}), dict(value.get("normalized_observation") or {}))


def observation_id(value: LegacySourceObservationInput | Mapping[str, Any]) -> str:
    if isinstance(value, LegacySourceObservationInput):
        return observation_id_for(value.source_identity_key, value.observation_content_digest or "")
    return observation_id_for(source_identity_key(value), observation_content_digest(value))


def observation_digest(value: LegacySourceObservationInput | Mapping[str, Any]) -> str:
    if isinstance(value, LegacySourceObservationInput):
        return observation_digest_for(value.source_identity_key, value.observation_content_digest or "", value.observation_schema_version)
    version = int(value.get("observation_schema_version", SCHEMA_VERSION))
    return observation_digest_for(source_identity_key(value), observation_content_digest(value), version)


def record_digest(value: Any) -> str:
    return canonical_sha256(_export(value))


def _ref_id(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: value[key] for key in ("object_id", "source_digest", "object_version", "revision") if key in value}
    return value.to_dict() if hasattr(value, "to_dict") else value


@dataclass(frozen=True)
class SourceSelector:
    source_family: SourceFamily | str
    source_system_id: str
    source_object_identity: str | None = None
    native_id: str | None = None
    source_location: str | None = None
    source_scope: Mapping[str, Any] = None  # type: ignore[assignment]
    native_revision: str | None = None
    source_cursor: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_family", _enum(SourceFamily, self.source_family, "source_family"))
        object.__setattr__(self, "source_system_id", _text(self.source_system_id, "source_system_id"))
        for name in ("source_object_identity", "native_id", "source_location", "native_revision"):
            object.__setattr__(self, name, _text(getattr(self, name), name, optional=True))
        if not self.source_object_identity and not self.native_id:
            raise R47Error(R47_SCHEMA_INVALID, "source_object_identity or native_id is required")
        object.__setattr__(self, "source_scope", dict(_optional_mapping(self.source_scope or {}, "source_scope") or {}))
        object.__setattr__(self, "source_cursor", None if self.source_cursor is None else _seq(self.source_cursor, "source_cursor"))

    @property
    def source_identity_key(self) -> str:
        return source_identity_key_for(self.source_family, self.source_system_id, self.source_object_identity, self.native_id)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceSelector":
        return cls(**_strict(value, "SourceSelector"))


@dataclass(frozen=True)
class LegacySourceObservationInput:
    source_family: SourceFamily | str = SourceFamily.UNKNOWN
    source_system_id: str = "unknown"
    adapter_id: str = "unknown"
    source_object_identity: str | None = None
    source_location: str | None = None
    native_id: str | None = None
    native_revision: str | None = None
    native_revision_state: SourceValueState | str = SourceValueState.UNKNOWN
    native_source_digest: str | None = None
    native_source_digest_state: SourceValueState | str = SourceValueState.UNKNOWN
    observation_content_digest: str | None = None
    native_content_relation: ContentRelation | str = ContentRelation.UNKNOWN
    source_scope: Mapping[str, Any] = None  # type: ignore[assignment]
    observed_at: str = "unknown"
    source_cursor: int | None = None
    source_cursor_state: SourceValueState | str = SourceValueState.UNKNOWN
    availability: SourceAvailability | str = SourceAvailability.UNKNOWN
    freshness: SourceFreshness | str = SourceFreshness.UNKNOWN
    active_writer_state: ActiveWriterState | str = ActiveWriterState.UNKNOWN
    writer_authority: str | None = None
    raw_status: str | None = None
    raw_version: str | None = None
    raw_provenance: Mapping[str, Any] = None  # type: ignore[assignment]
    normalized_observation: Mapping[str, Any] = None  # type: ignore[assignment]
    bounded_payload_ref: str | None = None
    observation_schema_version: int = SCHEMA_VERSION
    previous_observation_ref: str | None = None
    supersedes_observation_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_family", _enum(SourceFamily, self.source_family, "source_family"))
        for name in ("source_system_id", "adapter_id", "observed_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("source_object_identity", "source_location", "native_id", "native_revision", "native_source_digest", "writer_authority", "raw_status", "raw_version", "bounded_payload_ref", "previous_observation_ref", "supersedes_observation_ref"):
            object.__setattr__(self, name, _text(getattr(self, name), name, optional=True))
        if not self.source_object_identity and not self.native_id:
            raise R47Error(R47_SCHEMA_INVALID, "source_object_identity or native_id is required")
        object.__setattr__(self, "native_revision_state", _enum(SourceValueState, self.native_revision_state, "native_revision_state"))
        object.__setattr__(self, "native_source_digest_state", _enum(SourceValueState, self.native_source_digest_state, "native_source_digest_state"))
        if self.native_source_digest is not None:
            _digest(self.native_source_digest, "native_source_digest")
        if self.observation_content_digest is not None:
            _digest(self.observation_content_digest, "observation_content_digest")
        object.__setattr__(self, "native_content_relation", _enum(ContentRelation, self.native_content_relation, "native_content_relation"))
        object.__setattr__(self, "source_scope", dict(_optional_mapping(self.source_scope or {}, "source_scope") or {}))
        object.__setattr__(self, "source_cursor", None if self.source_cursor is None else _seq(self.source_cursor, "source_cursor"))
        object.__setattr__(self, "source_cursor_state", _enum(SourceValueState, self.source_cursor_state, "source_cursor_state"))
        object.__setattr__(self, "availability", _enum(SourceAvailability, self.availability, "availability"))
        object.__setattr__(self, "freshness", _enum(SourceFreshness, self.freshness, "freshness"))
        object.__setattr__(self, "active_writer_state", _enum(ActiveWriterState, self.active_writer_state, "active_writer_state"))
        object.__setattr__(self, "raw_provenance", dict(_optional_mapping(self.raw_provenance or {}, "raw_provenance") or {}))
        object.__setattr__(self, "normalized_observation", dict(_optional_mapping(self.normalized_observation or {}, "normalized_observation") or {}))
        if self.observation_schema_version != SCHEMA_VERSION:
            raise R47Error(R47_SCHEMA_INVALID, "observation_schema_version must be 1")
        computed = observation_content_digest_for(self.observation_schema_version, self.source_scope, self.normalized_observation)
        if self.observation_content_digest not in (None, computed):
            raise R47Error(R47_DIGEST_CONFLICT, "observation_content_digest does not match bounded observation")
        object.__setattr__(self, "observation_content_digest", computed)

    @property
    def source_identity_key(self) -> str:
        return source_identity_key_for(self.source_family, self.source_system_id, self.source_object_identity, self.native_id)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegacySourceObservationInput":
        return cls(**_strict(value, "LegacySourceObservationInput"))


@dataclass(frozen=True)
class _CommonDurable:
    owner_mission_id: str = ""
    owner_stream_key: str = ""
    revision: int = 1
    record_digest: str | None = None
    as_of_seq: int = 0
    correlation_id: str = "r4.7"
    causation_id: str = "r4.7"
    created_by: ActorRef | Mapping[str, Any] = ActorRef("SYSTEM", "r4.7")
    created_seq: int = 1
    created_at: str = "seq:1"

    def _common_post_init(self) -> None:
        object.__setattr__(self, "owner_mission_id", _text(self.owner_mission_id, "owner_mission_id"))
        object.__setattr__(self, "owner_stream_key", _text(self.owner_stream_key, "owner_stream_key"))
        object.__setattr__(self, "revision", _seq(self.revision, "revision", 1))
        object.__setattr__(self, "as_of_seq", _seq(self.as_of_seq, "as_of_seq"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "causation_id", _text(self.causation_id, "causation_id"))
        actor = self.created_by if isinstance(self.created_by, ActorRef) else ActorRef(str(self.created_by.get("type")), str(self.created_by.get("id"))) if isinstance(self.created_by, Mapping) else None
        if actor is None:
            raise R47Error(R47_SCHEMA_INVALID, "created_by must be ActorRef")
        object.__setattr__(self, "created_by", actor)
        object.__setattr__(self, "created_seq", _seq(self.created_seq, "created_seq", 1))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))


@dataclass(frozen=True)
class LegacySourceObservation(_CommonDurable):
    observation_id: str = "pending"
    source_family: SourceFamily | str = SourceFamily.UNKNOWN
    source_system_id: str = "unknown"
    adapter_id: str = "unknown"
    source_object_identity: str | None = None
    source_location: str | None = None
    native_id: str | None = None
    native_revision: str | None = None
    native_revision_state: SourceValueState | str = SourceValueState.UNKNOWN
    native_source_digest: str | None = None
    native_source_digest_state: SourceValueState | str = SourceValueState.UNKNOWN
    observation_content_digest: str | None = None
    observation_digest: str | None = None
    native_content_relation: ContentRelation | str = ContentRelation.UNKNOWN
    source_scope: Mapping[str, Any] = None  # type: ignore[assignment]
    observed_at: str = "unknown"
    source_cursor: int | None = None
    source_cursor_state: SourceValueState | str = SourceValueState.UNKNOWN
    availability: SourceAvailability | str = SourceAvailability.UNKNOWN
    freshness: SourceFreshness | str = SourceFreshness.UNKNOWN
    active_writer_state: ActiveWriterState | str = ActiveWriterState.UNKNOWN
    writer_authority: str | None = None
    raw_status: str | None = None
    raw_version: str | None = None
    raw_provenance: Mapping[str, Any] = None  # type: ignore[assignment]
    normalized_observation: Mapping[str, Any] = None  # type: ignore[assignment]
    bounded_payload_ref: str | None = None
    observation_schema_version: int = SCHEMA_VERSION
    previous_observation_ref: str | None = None
    supersedes_observation_ref: str | None = None

    def __post_init__(self) -> None:
        self._common_post_init()
        value = LegacySourceObservationInput(
            source_family=self.source_family, source_system_id=self.source_system_id, adapter_id=self.adapter_id,
            source_object_identity=self.source_object_identity, source_location=self.source_location, native_id=self.native_id,
            native_revision=self.native_revision, native_revision_state=self.native_revision_state, native_source_digest=self.native_source_digest,
            native_source_digest_state=self.native_source_digest_state, observation_content_digest=self.observation_content_digest,
            native_content_relation=self.native_content_relation, source_scope=self.source_scope or {}, observed_at=self.observed_at,
            source_cursor=self.source_cursor, source_cursor_state=self.source_cursor_state, availability=self.availability,
            freshness=self.freshness, active_writer_state=self.active_writer_state, writer_authority=self.writer_authority,
            raw_status=self.raw_status, raw_version=self.raw_version, raw_provenance=self.raw_provenance or {},
            normalized_observation=self.normalized_observation or {}, bounded_payload_ref=self.bounded_payload_ref,
            observation_schema_version=self.observation_schema_version, previous_observation_ref=self.previous_observation_ref,
            supersedes_observation_ref=self.supersedes_observation_ref,
        )
        for item in fields(value):
            object.__setattr__(self, item.name, getattr(value, item.name))
        identity_key = self.source_identity_key
        expected_id = observation_id_for(identity_key, value.observation_content_digest or "")
        if self.observation_id not in {"pending", "", expected_id}:
            raise R47Error(R47_IDENTITY_CONFLICT, "observation_id does not match source identity/content")
        object.__setattr__(self, "observation_id", expected_id)
        expected_digest = observation_digest_for(identity_key, value.observation_content_digest or "", self.observation_schema_version)
        if self.observation_digest not in (None, "", "pending", expected_digest):
            raise R47Error(R47_DIGEST_CONFLICT, "observation_digest does not match source identity/content")
        object.__setattr__(self, "observation_digest", expected_digest)
        stable_observation_digest = canonical_sha256(
            {
                "source_identity_key": identity_key,
                "observation_content_digest": value.observation_content_digest,
                "observation_schema_version": self.observation_schema_version,
            }
        )
        if self.record_digest not in (None, "", "pending", stable_observation_digest):
            raise R47Error(R47_DIGEST_CONFLICT, "record_digest does not match observation identity/content")
        object.__setattr__(self, "record_digest", stable_observation_digest)

    @property
    def source_identity_key(self) -> str:
        return source_identity_key_for(self.source_family, self.source_system_id, self.source_object_identity, self.native_id)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegacySourceObservation":
        return cls(**_strict(value, "LegacySourceObservation"))


def _ref(value: Any) -> Any:
    if isinstance(value, Mapping):
        return dict(value)
    return value.to_dict() if hasattr(value, "to_dict") else value


def _text_tuple(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (tuple, list)):
        raise R47Error(R47_SCHEMA_INVALID, f"{name} must be an array")
    return tuple(_text(item, f"{name}[]") for item in value)  # type: ignore[misc]


@dataclass(frozen=True)
class ReconciliationAssessment(_CommonDurable):
    assessment_id: str = "pending"
    observation_ref: Any = None
    observation_digest: str = ""
    outcome: AssessmentOutcome | str = AssessmentOutcome.UNKNOWN
    source_identity_completeness: str = "UNKNOWN"
    provenance_completeness: str = "UNKNOWN"
    scope_completeness: str = "UNKNOWN"
    source_availability: SourceAvailability | str = SourceAvailability.UNKNOWN
    source_freshness: SourceFreshness | str = SourceFreshness.UNKNOWN
    active_writer_risk: str = "UNKNOWN"
    canonical_target_discoverability: str = "UNKNOWN"
    canonical_target_exactness: str = "UNKNOWN"
    legacy_canonical_conflict: str = "UNKNOWN"
    field_validation_relevance: str = "UNKNOWN"
    human_approval_requirement: str = "UNKNOWN"
    migration_eligibility: str = "UNKNOWN"
    shadow_truth_risk: ShadowTruthStatus | str = ShadowTruthStatus.IDENTIFIED
    out_of_scope_status: str = "IN_SCOPE"
    policy_snapshot_ref: Any = None

    def __post_init__(self) -> None:
        self._common_post_init()
        object.__setattr__(self, "assessment_id", _text(self.assessment_id, "assessment_id"))
        object.__setattr__(self, "observation_ref", _ref(self.observation_ref))
        object.__setattr__(self, "observation_digest", _digest(self.observation_digest, "observation_digest"))
        object.__setattr__(self, "outcome", _enum(AssessmentOutcome, self.outcome, "outcome"))
        for name in ("source_identity_completeness", "provenance_completeness", "scope_completeness", "active_writer_risk", "canonical_target_discoverability", "canonical_target_exactness", "legacy_canonical_conflict", "field_validation_relevance", "human_approval_requirement", "migration_eligibility", "out_of_scope_status"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "source_availability", _enum(SourceAvailability, self.source_availability, "source_availability"))
        object.__setattr__(self, "source_freshness", _enum(SourceFreshness, self.source_freshness, "source_freshness"))
        object.__setattr__(self, "shadow_truth_risk", _enum(ShadowTruthStatus, self.shadow_truth_risk, "shadow_truth_risk"))
        object.__setattr__(self, "policy_snapshot_ref", _ref(self.policy_snapshot_ref) if self.policy_snapshot_ref is not None else None)
        _finish_digest(self, "record_digest", self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReconciliationAssessment":
        return cls(**_strict(value, "ReconciliationAssessment"))


@dataclass(frozen=True)
class LegacyCanonicalMapping(_CommonDurable):
    mapping_id: str = "pending"
    observation_ref: Any = None
    observation_digest: str = ""
    target_authority: CanonicalAuthority | str = CanonicalAuthority.NO_CANONICAL_TARGET
    target_object_type: str = ""
    target_object_ref: str | None = None
    target_object_version: str | None = None
    target_object_digest: str | None = None
    identity_relation: IdentityRelation | str = IdentityRelation.UNKNOWN
    scope_relation: ScopeRelation | str = ScopeRelation.UNKNOWN
    content_relation: ContentRelation | str = ContentRelation.UNKNOWN
    mapping_evidence: MappingEvidence | str = MappingEvidence.UNRESOLVED
    mapping_status: MappingStatus | str = MappingStatus.PROPOSED
    conflict_refs: tuple[Any, ...] = ()
    policy_snapshot_ref: Any = None

    def __post_init__(self) -> None:
        self._common_post_init()
        object.__setattr__(self, "mapping_id", _text(self.mapping_id, "mapping_id"))
        object.__setattr__(self, "observation_ref", _ref(self.observation_ref))
        object.__setattr__(self, "observation_digest", _digest(self.observation_digest, "observation_digest"))
        object.__setattr__(self, "target_authority", _enum(CanonicalAuthority, self.target_authority, "target_authority"))
        object.__setattr__(self, "target_object_type", _text(self.target_object_type, "target_object_type"))
        for name in ("target_object_ref", "target_object_version", "target_object_digest"):
            object.__setattr__(self, name, _text(getattr(self, name), name, optional=True))
        if self.target_object_digest is not None:
            _digest(self.target_object_digest, "target_object_digest")
        for name, enum_type in (("identity_relation", IdentityRelation), ("scope_relation", ScopeRelation), ("content_relation", ContentRelation), ("mapping_evidence", MappingEvidence), ("mapping_status", MappingStatus)):
            object.__setattr__(self, name, _enum(enum_type, getattr(self, name), name))
        object.__setattr__(self, "conflict_refs", tuple(_ref(item) for item in (self.conflict_refs or ())))
        object.__setattr__(self, "policy_snapshot_ref", _ref(self.policy_snapshot_ref) if self.policy_snapshot_ref is not None else None)
        _finish_digest(self, "record_digest", self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegacyCanonicalMapping":
        return cls(**_strict(value, "LegacyCanonicalMapping"))


@dataclass(frozen=True)
class ReconciliationDecision(_CommonDurable):
    decision_id: str = "pending"
    assessment_ref: Any = None
    assessment_digest: str = ""
    mapping_ref: Any = None
    mapping_digest: str = ""
    decision: DecisionKind | str = DecisionKind.NO_ACTION
    policy_snapshot_ref: Any = None
    human_gate_linkage: Any = None
    reason_refs: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        self._common_post_init()
        object.__setattr__(self, "decision_id", _text(self.decision_id, "decision_id"))
        object.__setattr__(self, "assessment_ref", _ref(self.assessment_ref))
        object.__setattr__(self, "assessment_digest", _digest(self.assessment_digest, "assessment_digest"))
        object.__setattr__(self, "mapping_ref", _ref(self.mapping_ref))
        object.__setattr__(self, "mapping_digest", _digest(self.mapping_digest, "mapping_digest"))
        object.__setattr__(self, "decision", _enum(DecisionKind, self.decision, "decision"))
        object.__setattr__(self, "policy_snapshot_ref", _ref(self.policy_snapshot_ref) if self.policy_snapshot_ref is not None else None)
        object.__setattr__(self, "human_gate_linkage", _ref(self.human_gate_linkage) if self.human_gate_linkage is not None else None)
        object.__setattr__(self, "reason_refs", tuple(_ref(item) for item in (self.reason_refs or ())))
        _finish_digest(self, "record_digest", self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReconciliationDecision":
        return cls(**_strict(value, "ReconciliationDecision"))


def handoff_id_for(value: Mapping[str, Any]) -> str:
    keys = ("decision_ref", "decision_digest", "target_authority", "target_scope_ref", "target_object_ref", "target_object_digest", "handoff_kind", "source_observation_ref", "source_observation_digest", "assessment_ref", "mapping_ref", "policy_snapshot_ref")
    return "r4.7:handoff:" + canonical_sha256({key: _export(value.get(key)) for key in keys})


@dataclass(frozen=True)
class CanonicalHandoffLinkage(_CommonDurable):
    handoff_id: str = "pending"
    decision_ref: Any = None
    decision_digest: str = ""
    target_authority: CanonicalAuthority | str = CanonicalAuthority.NO_CANONICAL_TARGET
    target_scope_ref: Any = None
    target_object_ref: str | None = None
    target_object_digest: str | None = None
    handoff_kind: HandoffKind | str = HandoffKind.REFERENCE_ONLY
    request_ref: str | None = None
    authority_command_id: str | None = None
    authority_idempotency_key: str | None = None
    authority_result_ref: str | None = None
    authority_result_digest: str | None = None
    state: HandoffState | str = HandoffState.READY
    source_observation_ref: Any = None
    source_observation_digest: str = ""
    assessment_ref: Any = None
    mapping_ref: Any = None
    policy_snapshot_ref: Any = None
    source_cursor: int = 0

    def __post_init__(self) -> None:
        self._common_post_init()
        object.__setattr__(self, "handoff_id", _text(self.handoff_id, "handoff_id"))
        for name in ("decision_ref", "target_scope_ref", "source_observation_ref", "assessment_ref", "mapping_ref", "policy_snapshot_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name)) if getattr(self, name) is not None else None)
        object.__setattr__(self, "decision_digest", _digest(self.decision_digest, "decision_digest"))
        object.__setattr__(self, "target_authority", _enum(CanonicalAuthority, self.target_authority, "target_authority"))
        for name in ("target_object_ref", "target_object_digest", "request_ref", "authority_command_id", "authority_idempotency_key", "authority_result_ref", "authority_result_digest"):
            object.__setattr__(self, name, _text(getattr(self, name), name, optional=True))
        for name in ("target_object_digest", "authority_result_digest"):
            if getattr(self, name) is not None:
                _digest(getattr(self, name), name)
        object.__setattr__(self, "handoff_kind", _enum(HandoffKind, self.handoff_kind, "handoff_kind"))
        object.__setattr__(self, "state", _enum(HandoffState, self.state, "state"))
        object.__setattr__(self, "source_observation_digest", _digest(self.source_observation_digest, "source_observation_digest"))
        object.__setattr__(self, "source_cursor", _seq(self.source_cursor, "source_cursor"))
        if self.handoff_id in {"pending", ""}:
            object.__setattr__(self, "handoff_id", handoff_id_for(self.to_dict()))
        expected_request = "r4.7:request:" + self.handoff_id
        expected_command = "r4.7:authority-command:" + self.handoff_id
        expected_key = "r4.7:authority-idempotency:" + self.handoff_id
        if self.request_ref is None:
            object.__setattr__(self, "request_ref", expected_request)
        if self.authority_command_id is None and self.handoff_kind is not HandoffKind.REFERENCE_ONLY:
            object.__setattr__(self, "authority_command_id", expected_command)
        if self.authority_idempotency_key is None and self.handoff_kind is not HandoffKind.REFERENCE_ONLY:
            object.__setattr__(self, "authority_idempotency_key", expected_key)
        _finish_digest(self, "record_digest", self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CanonicalHandoffLinkage":
        return cls(**_strict(value, "CanonicalHandoffLinkage"))


def receipt_id_for(handoff_id: str, handoff_digest: str, authority_operation_id: str | None, canonical_result_ref: str | None, canonical_result_digest: str | None) -> str:
    semantic = (handoff_id, handoff_digest, authority_operation_id, canonical_result_ref, canonical_result_digest)
    return "r4.7:receipt:" + canonical_sha256(semantic)


@dataclass(frozen=True)
class ReconciliationReceipt(_CommonDurable):
    receipt_id: str = "pending"
    source_observation_ref: Any = None
    source_observation_digest: str = ""
    assessment_ref: Any = None
    assessment_digest: str = ""
    mapping_ref: Any = None
    mapping_digest: str = ""
    decision_ref: Any = None
    decision_digest: str = ""
    handoff_ref: Any = None
    handoff_digest: str = ""
    handoff_authority: CanonicalAuthority | str = CanonicalAuthority.NO_CANONICAL_TARGET
    handoff_request_ref: str | None = None
    canonical_result_ref: str | None = None
    canonical_result_digest: str | None = None
    result_status: ReceiptStatus | str = ReceiptStatus.RECONCILIATION_REQUIRED
    duplicate_of: str | None = None
    reconciled_from_existing: bool = False
    reason_code: str | None = None
    authority_operation_id: str | None = None
    source_cursor: int = 0

    def __post_init__(self) -> None:
        self._common_post_init()
        object.__setattr__(self, "receipt_id", _text(self.receipt_id, "receipt_id"))
        for name in ("source_observation_ref", "assessment_ref", "mapping_ref", "decision_ref", "handoff_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name)) if getattr(self, name) is not None else None)
        for name in ("source_observation_digest", "assessment_digest", "mapping_digest", "decision_digest", "handoff_digest"):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        object.__setattr__(self, "handoff_authority", _enum(CanonicalAuthority, self.handoff_authority, "handoff_authority"))
        for name in ("handoff_request_ref", "canonical_result_ref", "canonical_result_digest", "duplicate_of", "reason_code", "authority_operation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name, optional=True))
        if self.canonical_result_digest is not None:
            _digest(self.canonical_result_digest, "canonical_result_digest")
        object.__setattr__(self, "result_status", _enum(ReceiptStatus, self.result_status, "result_status"))
        if not isinstance(self.reconciled_from_existing, bool):
            raise R47Error(R47_SCHEMA_INVALID, "reconciled_from_existing must be boolean")
        object.__setattr__(self, "source_cursor", _seq(self.source_cursor, "source_cursor"))
        _finish_digest(self, "record_digest", self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReconciliationReceipt":
        return cls(**_strict(value, "ReconciliationReceipt"))


@dataclass(frozen=True)
class RebuildCheckpoint(_CommonDurable):
    rebuild_checkpoint_id: str = "pending"
    projection_set: tuple[str, ...] = ()
    projection_set_digest: str = ""
    source_event_cursor: int = 0
    attempt_id: str = ""
    result: str = "UNKNOWN"
    state_hash: str = ""
    verification_result: str = "UNKNOWN"
    error_code: str | None = None
    error_provenance: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._common_post_init()
        object.__setattr__(self, "rebuild_checkpoint_id", _text(self.rebuild_checkpoint_id, "rebuild_checkpoint_id"))
        object.__setattr__(self, "projection_set", _text_tuple(self.projection_set, "projection_set"))
        object.__setattr__(self, "projection_set_digest", _digest(self.projection_set_digest, "projection_set_digest"))
        object.__setattr__(self, "source_event_cursor", _seq(self.source_event_cursor, "source_event_cursor"))
        object.__setattr__(self, "attempt_id", _text(self.attempt_id, "attempt_id"))
        object.__setattr__(self, "result", _text(self.result, "result"))
        object.__setattr__(self, "state_hash", _digest(self.state_hash, "state_hash"))
        object.__setattr__(self, "verification_result", _text(self.verification_result, "verification_result"))
        object.__setattr__(self, "error_code", _text(self.error_code, "error_code", optional=True))
        object.__setattr__(self, "error_provenance", dict(_optional_mapping(self.error_provenance or {}, "error_provenance") or {}))
        _finish_digest(self, "record_digest", self.record_digest)

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RebuildCheckpoint":
        return cls(**_strict(value, "RebuildCheckpoint"))


@dataclass(frozen=True)
class CurrentReconciliationResolution:
    owner_mission_id: str
    case_id: str
    current_observation_ref: Any = None
    current_observation_digest: str | None = None
    current_assessment_ref: Any = None
    current_assessment_digest: str | None = None
    current_mapping_ref: Any = None
    current_mapping_digest: str | None = None
    current_decision_ref: Any = None
    current_decision_digest: str | None = None
    current_handoff_ref: Any = None
    current_handoff_digest: str | None = None
    current_receipt_ref: Any = None
    current_receipt_digest: str | None = None
    status: ResolutionStatus | str = ResolutionStatus.UNKNOWN
    as_of_seq: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_mission_id", _text(self.owner_mission_id, "owner_mission_id"))
        object.__setattr__(self, "case_id", _text(self.case_id, "case_id"))
        for name in ("current_observation_ref", "current_assessment_ref", "current_mapping_ref", "current_decision_ref", "current_handoff_ref", "current_receipt_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name)) if getattr(self, name) is not None else None)
        for name in ("current_observation_digest", "current_assessment_digest", "current_mapping_digest", "current_decision_digest", "current_handoff_digest", "current_receipt_digest"):
            if getattr(self, name) is not None:
                _digest(getattr(self, name), name)
        object.__setattr__(self, "status", _enum(ResolutionStatus, self.status, "status"))
        object.__setattr__(self, "as_of_seq", _seq(self.as_of_seq, "as_of_seq"))

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CurrentReconciliationResolution":
        allowed = {item.name for item in fields(cls)}
        raw = dict(value)
        unknown = set(raw) - allowed
        if unknown:
            raise R47Error(R47_SCHEMA_INVALID, f"CurrentReconciliationResolution contains unknown fields", {"unknown": sorted(unknown)})
        return cls(**raw)


@dataclass(frozen=True)
class ReconciliationCase:
    owner_mission_id: str
    case_id: str
    current_observation_ref: Any = None
    current_assessment_ref: Any = None
    current_mapping_ref: Any = None
    current_decision_ref: Any = None
    current_handoff_ref: Any = None
    current_receipt_ref: Any = None
    resolution: CurrentReconciliationResolution | Mapping[str, Any] | None = None
    as_of_seq: int = 0
    state_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_mission_id", _text(self.owner_mission_id, "owner_mission_id"))
        object.__setattr__(self, "case_id", _text(self.case_id, "case_id"))
        for name in ("current_observation_ref", "current_assessment_ref", "current_mapping_ref", "current_decision_ref", "current_handoff_ref", "current_receipt_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name)) if getattr(self, name) is not None else None)
        if self.resolution is not None and not isinstance(self.resolution, CurrentReconciliationResolution):
            object.__setattr__(self, "resolution", CurrentReconciliationResolution.from_dict(self.resolution))
        object.__setattr__(self, "as_of_seq", _seq(self.as_of_seq, "as_of_seq"))
        body = {name: _export(getattr(self, name)) for name in ("owner_mission_id", "case_id", "current_observation_ref", "current_assessment_ref", "current_mapping_ref", "current_decision_ref", "current_handoff_ref", "current_receipt_ref", "resolution", "as_of_seq")}
        expected = canonical_sha256(body)
        if self.state_hash not in (None, "", "pending", expected):
            raise R47Error(R47_DIGEST_CONFLICT, "state_hash does not match case state")
        object.__setattr__(self, "state_hash", expected)

    @property
    def status(self) -> ResolutionStatus:
        return self.resolution.status if self.resolution is not None else ResolutionStatus.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {item.name: _export(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReconciliationCase":
        allowed = {item.name for item in fields(cls)}
        raw = dict(value)
        unknown = set(raw) - allowed
        if unknown:
            raise R47Error(R47_SCHEMA_INVALID, f"ReconciliationCase contains unknown fields", {"unknown": sorted(unknown)})
        return cls(**raw)


@dataclass(frozen=True)
class R47State:
    mission_id: str
    observations: tuple[LegacySourceObservation, ...] = ()
    assessments: tuple[ReconciliationAssessment, ...] = ()
    mappings: tuple[LegacyCanonicalMapping, ...] = ()
    decisions: tuple[ReconciliationDecision, ...] = ()
    handoffs: tuple[CanonicalHandoffLinkage, ...] = ()
    receipts: tuple[ReconciliationReceipt, ...] = ()

    def observation(self, identity: str) -> LegacySourceObservation | None:
        return next((item for item in self.observations if item.observation_id == identity or item.observation_digest == identity), None)

    def assessment(self, identity: str) -> ReconciliationAssessment | None:
        return next((item for item in self.assessments if item.assessment_id == identity or item.record_digest == identity), None)

    def mapping(self, identity: str) -> LegacyCanonicalMapping | None:
        return next((item for item in self.mappings if item.mapping_id == identity or item.record_digest == identity), None)

    def decision(self, identity: str) -> ReconciliationDecision | None:
        return next((item for item in self.decisions if item.decision_id == identity or item.record_digest == identity), None)

    def handoff(self, identity: str) -> CanonicalHandoffLinkage | None:
        values = [item for item in self.handoffs if item.handoff_id == identity or item.record_digest == identity]
        return max(values, key=lambda item: (item.revision, item.created_seq), default=None)

    def receipt(self, identity: str) -> ReconciliationReceipt | None:
        values = [item for item in self.receipts if item.receipt_id == identity or item.record_digest == identity]
        return max(values, key=lambda item: (item.revision, item.created_seq), default=None)

    def case(self, case_id: str) -> ReconciliationCase | None:
        values = self._case_values(case_id)
        return _case_from_values(self.mission_id, case_id, values, self._as_of_seq(case_id)) if values is not None else None

    def cases(self) -> tuple[ReconciliationCase, ...]:
        ids = sorted({item.observation_ref.get("object_id") for item in self.assessments if isinstance(item.observation_ref, Mapping) and item.observation_ref.get("object_id")} | {item.observation_id for item in self.observations})
        result = []
        for case_id in ids:
            value = self.case(case_id)
            if value is not None:
                result.append(value)
        return tuple(result)

    def _case_values(self, case_id: str) -> dict[str, Any] | None:
        observation = self.observation(case_id)
        if observation is None:
            observation = next((item for item in self.observations if item.source_identity_key == case_id), None)
        observation_ref = {"object_id": observation.observation_id, "source_digest": observation.record_digest} if observation else None
        assessment = next((item for item in reversed(self.assessments) if _ref_id(item.observation_ref) == _ref_id(observation_ref) or _ref_id(item.observation_ref) == {"object_id": case_id}), None)
        assessment_ref = {"object_id": assessment.assessment_id, "source_digest": assessment.record_digest} if assessment else None
        mapping = next((item for item in reversed(self.mappings) if _ref_id(item.observation_ref) == _ref_id(observation_ref)), None)
        mapping_ref = {"object_id": mapping.mapping_id, "source_digest": mapping.record_digest} if mapping else None
        decision = next((item for item in reversed(self.decisions) if _ref_id(item.mapping_ref) == _ref_id(mapping_ref)), None)
        decision_ref = {"object_id": decision.decision_id, "source_digest": decision.record_digest} if decision else None
        handoff = next((item for item in reversed(self.handoffs) if _ref_id(item.decision_ref) == _ref_id(decision_ref)), None)
        handoff_ref = {"object_id": handoff.handoff_id, "source_digest": handoff.record_digest} if handoff else None
        receipt = next((item for item in reversed(self.receipts) if _ref_id(item.handoff_ref) == _ref_id(handoff_ref)), None)
        receipt_ref = {"object_id": receipt.receipt_id, "source_digest": receipt.record_digest} if receipt else None
        if not any(value is not None for value in (observation, assessment, mapping, decision, handoff, receipt)):
            return None
        status = _resolution_status(observation, assessment, mapping, decision, handoff, receipt)
        return {"observation": observation, "assessment": assessment, "mapping": mapping, "decision": decision, "handoff": handoff, "receipt": receipt, "status": status, "refs": (observation_ref, assessment_ref, mapping_ref, decision_ref, handoff_ref, receipt_ref)}

    def _as_of_seq(self, case_id: str) -> int:
        value = self._case_values(case_id)
        if not value:
            return 0
        return max((getattr(item, "created_seq", 0) for item in value.values() if hasattr(item, "created_seq")), default=0)

    def to_dict(self) -> dict[str, Any]:
        return {"mission_id": self.mission_id, "observations": [_export(item) for item in self.observations], "assessments": [_export(item) for item in self.assessments], "mappings": [_export(item) for item in self.mappings], "decisions": [_export(item) for item in self.decisions], "handoffs": [_export(item) for item in self.handoffs], "receipts": [_export(item) for item in self.receipts]}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R47State":
        raw = dict(value)
        return cls(
            str(raw["mission_id"]),
            tuple(LegacySourceObservation.from_dict(item) for item in raw.get("observations", ())),
            tuple(ReconciliationAssessment.from_dict(item) for item in raw.get("assessments", ())),
            tuple(LegacyCanonicalMapping.from_dict(item) for item in raw.get("mappings", ())),
            tuple(ReconciliationDecision.from_dict(item) for item in raw.get("decisions", ())),
            tuple(CanonicalHandoffLinkage.from_dict(item) for item in raw.get("handoffs", ())),
            tuple(ReconciliationReceipt.from_dict(item) for item in raw.get("receipts", ())),
        )


def _resolution_status(observation: Any, assessment: Any, mapping: Any, decision: Any, handoff: Any, receipt: Any) -> ResolutionStatus:
    if receipt is not None:
        return {ReceiptStatus.ACCEPTED: ResolutionStatus.COMPLETED, ReceiptStatus.DUPLICATE: ResolutionStatus.COMPLETED, ReceiptStatus.REFERENCE_ONLY: ResolutionStatus.NO_ACTION, ReceiptStatus.REJECTED: ResolutionStatus.CONFLICT, ReceiptStatus.BLOCKED: ResolutionStatus.BLOCKED, ReceiptStatus.CONFLICT: ResolutionStatus.CONFLICT, ReceiptStatus.RECONCILIATION_REQUIRED: ResolutionStatus.REVALIDATION_REQUIRED}[receipt.result_status]
    if handoff is not None:
        return {HandoffState.READY: ResolutionStatus.CURRENT, HandoffState.SUBMITTED: ResolutionStatus.CURRENT, HandoffState.COMPLETED: ResolutionStatus.COMPLETED, HandoffState.REJECTED: ResolutionStatus.CONFLICT, HandoffState.BLOCKED: ResolutionStatus.BLOCKED, HandoffState.CONFLICT: ResolutionStatus.CONFLICT, HandoffState.RECONCILIATION_REQUIRED: ResolutionStatus.REVALIDATION_REQUIRED}[handoff.state]
    if decision is not None:
        return {DecisionKind.MARK_CONFLICT: ResolutionStatus.CONFLICT, DecisionKind.BLOCK: ResolutionStatus.BLOCKED, DecisionKind.REVALIDATE: ResolutionStatus.REVALIDATION_REQUIRED, DecisionKind.OUT_OF_SCOPE: ResolutionStatus.NO_ACTION}.get(decision.decision, ResolutionStatus.CURRENT)
    if assessment is not None:
        return {AssessmentOutcome.CONFLICT: ResolutionStatus.CONFLICT, AssessmentOutcome.BLOCKED: ResolutionStatus.BLOCKED, AssessmentOutcome.STALE: ResolutionStatus.STALE, AssessmentOutcome.REVALIDATION_REQUIRED: ResolutionStatus.REVALIDATION_REQUIRED, AssessmentOutcome.OUT_OF_SCOPE: ResolutionStatus.NO_ACTION}.get(assessment.outcome, ResolutionStatus.CURRENT)
    return ResolutionStatus.CURRENT if observation is not None else ResolutionStatus.UNKNOWN


def _case_from_values(mission_id: str, case_id: str, values: Mapping[str, Any], as_of_seq: int) -> ReconciliationCase:
    observation, assessment, mapping, decision, handoff, receipt = (values.get(name) for name in ("observation", "assessment", "mapping", "decision", "handoff", "receipt"))
    refs = values.get("refs", (None,) * 6)
    status = values["status"]
    resolution = CurrentReconciliationResolution(
        owner_mission_id=mission_id,
        case_id=case_id,
        current_observation_ref=refs[0], current_observation_digest=getattr(observation, "record_digest", None),
        current_assessment_ref=refs[1], current_assessment_digest=getattr(assessment, "record_digest", None),
        current_mapping_ref=refs[2], current_mapping_digest=getattr(mapping, "record_digest", None),
        current_decision_ref=refs[3], current_decision_digest=getattr(decision, "record_digest", None),
        current_handoff_ref=refs[4], current_handoff_digest=getattr(handoff, "record_digest", None),
        current_receipt_ref=refs[5], current_receipt_digest=getattr(receipt, "record_digest", None),
        status=status, as_of_seq=as_of_seq,
    )
    return ReconciliationCase(mission_id, case_id, refs[0], refs[1], refs[2], refs[3], refs[4], refs[5], resolution, as_of_seq)


@dataclass(frozen=True)
class R47OperationResult:
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

    def to_dict(self) -> dict[str, Any]:
        value = self.command_result.to_dict()
        value["entity"] = self.entity.to_dict() if hasattr(self.entity, "to_dict") else self.entity
        return value


class LegacySourceAdapter(Protocol):
    adapter_id: str
    source_families: frozenset[SourceFamily]

    def can_read(self, selector: SourceSelector) -> bool: ...

    def observe(self, selector: SourceSelector, *, owner_mission_id: str, actor: ActorRef, correlation_id: str, causation_id: str) -> LegacySourceObservationInput: ...


_CLASS_REGISTRY: dict[str, type[Any]] = {}
for _name, _class in list(globals().items()):
    if isinstance(_class, type) and _name in {"SourceSelector", "LegacySourceObservationInput", "LegacySourceObservation", "ReconciliationAssessment", "LegacyCanonicalMapping", "ReconciliationDecision", "CanonicalHandoffLinkage", "ReconciliationReceipt", "RebuildCheckpoint"}:
        _CLASS_REGISTRY[_name] = _class


__all__ = [
    "EXTENSION_ID", "EXTENSION_VERSION", "SCHEMA_VERSION", "COMMAND_TYPES", "EVENT_TYPES",
    "R4_7_RECORD_LEGACY_SOURCE_OBSERVATION", "R4_7_RECORD_RECONCILIATION_ASSESSMENT", "R4_7_RECORD_LEGACY_CANONICAL_MAPPING", "R4_7_RECORD_RECONCILIATION_DECISION", "R4_7_CREATE_CANONICAL_HANDOFF", "R4_7_SUBMIT_CANONICAL_HANDOFF", "R4_7_RECORD_RECONCILIATION_RECEIPT",
    "R47_LEGACY_SOURCE_OBSERVATION_RECORDED", "R47_RECONCILIATION_ASSESSMENT_RECORDED", "R47_LEGACY_CANONICAL_MAPPING_RECORDED", "R47_RECONCILIATION_DECISION_RECORDED", "R47_CANONICAL_HANDOFF_CREATED", "R47_CANONICAL_HANDOFF_SUBMITTED", "R47_RECONCILIATION_RECEIPT_RECORDED",
    "SourceSelector", "SourceFamily", "SourceValueState", "SourceAvailability", "SourceFreshness", "ActiveWriterState", "AssessmentOutcome", "IdentityRelation", "ScopeRelation", "ContentRelation", "MappingStatus", "MappingEvidence", "CanonicalAuthority", "DecisionKind", "ReceiptStatus", "HandoffState", "HandoffKind", "ResolutionStatus", "ShadowTruthStatus", "ExistingKnowledgeReconciliation",
    "ReconciliationCase", "LegacySourceObservationInput", "LegacySourceObservation", "ReconciliationAssessment", "LegacyCanonicalMapping", "ReconciliationDecision", "CanonicalHandoffLinkage", "ReconciliationReceipt", "RebuildCheckpoint", "CurrentReconciliationResolution", "LegacySourceAdapter", "R47State", "R47OperationResult", "source_identity_key_for", "observation_content_digest_for", "observation_id_for", "observation_digest_for", "source_identity_key", "observation_content_digest", "observation_id", "observation_digest", "record_digest", "handoff_id_for", "receipt_id_for",
]
