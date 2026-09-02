from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from aitest_runtime.durable_core import canonical_sha256

from .errors import (
    R41_DIGEST_MISMATCH,
    R41_IDENTITY_CONFLICT,
    R41_REFERENCE_INVALID,
    R41_SCHEMA_INVALID,
    R41Error,
)


EXTENSION_ID = "r4_1_quality_version_campaign_foundation"
EXTENSION_VERSION = "1.0.0"
R41_SCHEMA_VERSION = 1

CREATE_QUALITY_VERSION = "R4_1_CREATE_QUALITY_VERSION.v1"
CREATE_TEST_CAMPAIGN = "R4_1_CREATE_TEST_CAMPAIGN.v1"
RECORD_CAMPAIGN_SELECTION_REVISION = "R4_1_RECORD_CAMPAIGN_SELECTION_REVISION.v1"

QUALITY_VERSION_CREATED = "r4.1.quality_version_created.v1"
TEST_CAMPAIGN_CREATED = "r4.1.test_campaign_created.v1"
CAMPAIGN_SELECTION_REVISION_RECORDED = "r4.1.campaign_selection_revision_recorded.v1"

COMMAND_TYPES = frozenset({CREATE_QUALITY_VERSION, CREATE_TEST_CAMPAIGN, RECORD_CAMPAIGN_SELECTION_REVISION})
EVENT_TYPES = frozenset({QUALITY_VERSION_CREATED, TEST_CAMPAIGN_CREATED, CAMPAIGN_SELECTION_REVISION_RECORDED})


class Freshness(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class Availability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class FieldValidationState(str, Enum):
    PASSED = "PASSED"
    PENDING = "PENDING"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class QualityVersionLifecycle(str, Enum):
    ABSENT = "ABSENT"
    CREATED = "CREATED"


class CampaignKind(str, Enum):
    BASELINE = "BASELINE"
    SCOPED_EVALUATION = "SCOPED_EVALUATION"


class TestCampaignLifecycle(str, Enum):
    CREATED = "CREATED"
    SELECTION_RECORDED = "SELECTION_RECORDED"


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TYPED_REFERENCE_FIELDS = frozenset(
    {
        "ref_type",
        "object_id",
        "object_version",
        "revision",
        "source_digest",
        "source_cursor",
        "origin",
        "observed_at",
        "freshness",
        "availability",
        "field_validation_state",
        "correlation_id",
    }
)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R41Error(R41_SCHEMA_INVALID, f"{name} must be a non-empty string")
    return value


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise R41Error(R41_SCHEMA_INVALID, f"{name} must be a lowercase SHA-256 digest")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise R41Error(R41_SCHEMA_INVALID, f"{name} must be a positive integer")
    return value


def _json_value(value: Any, name: str = "value") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise R41Error(R41_SCHEMA_INVALID, f"{name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise R41Error(R41_SCHEMA_INVALID, f"{name} object keys must be strings")
            normalized[key] = _json_value(item, f"{name}.{key}")
        return normalized
    if isinstance(value, (list, tuple)):
        return [_json_value(item, f"{name}[]") for item in value]
    raise R41Error(R41_SCHEMA_INVALID, f"{name} must contain canonical JSON values")


def _export(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _export(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_export(item) for item in value]
    if isinstance(value, list):
        return [_export(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R41Error(R41_SCHEMA_INVALID, f"{name} must be an object")
    return _json_value(value, name)


def _tuple_refs(value: Any, name: str) -> tuple["TypedReference", ...]:
    if not isinstance(value, (list, tuple)):
        raise R41Error(R41_SCHEMA_INVALID, f"{name} must be an array of TypedReference values")
    refs = tuple(TypedReference.from_dict(item) if isinstance(item, Mapping) else item for item in value)
    if any(not isinstance(item, TypedReference) for item in refs):
        raise R41Error(R41_REFERENCE_INVALID, f"{name} must contain TypedReference values")
    return refs


def _optional_ref(value: Any, name: str) -> "TypedReference | None":
    if value is None:
        return None
    if isinstance(value, Mapping):
        value = TypedReference.from_dict(value)
    if not isinstance(value, TypedReference):
        raise R41Error(R41_REFERENCE_INVALID, f"{name} must be a TypedReference or null")
    return value


def _require_ref_type(reference: "TypedReference", expected: str, name: str) -> None:
    if reference.ref_type != expected:
        raise R41Error(R41_REFERENCE_INVALID, f"{name} must have ref_type={expected}")


@dataclass(frozen=True)
class TypedReference:
    ref_type: str
    object_id: str
    object_version: str | int
    revision: int
    source_digest: str
    source_cursor: str | int | None
    origin: str
    observed_at: str
    freshness: Freshness
    availability: Availability
    field_validation_state: FieldValidationState
    correlation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref_type", _text(self.ref_type, "ref_type"))
        object.__setattr__(self, "object_id", _text(self.object_id, "object_id"))
        if isinstance(self.object_version, bool) or not isinstance(self.object_version, (str, int)):
            raise R41Error(R41_SCHEMA_INVALID, "object_version must be a string or integer")
        if isinstance(self.object_version, str) and not self.object_version.strip():
            raise R41Error(R41_SCHEMA_INVALID, "object_version must be non-empty")
        object.__setattr__(self, "revision", _positive_int(self.revision, "revision"))
        object.__setattr__(self, "source_digest", _digest(self.source_digest, "source_digest"))
        if self.source_cursor is not None and (isinstance(self.source_cursor, bool) or not isinstance(self.source_cursor, (str, int))):
            raise R41Error(R41_SCHEMA_INVALID, "source_cursor must be a string, integer, or null when unavailable")
        if isinstance(self.source_cursor, str) and not self.source_cursor.strip():
            raise R41Error(R41_SCHEMA_INVALID, "source_cursor must be non-empty")
        object.__setattr__(self, "origin", _text(self.origin, "origin"))
        object.__setattr__(self, "observed_at", _text(self.observed_at, "observed_at"))
        try:
            object.__setattr__(self, "freshness", Freshness(self.freshness))
            object.__setattr__(self, "availability", Availability(self.availability))
            object.__setattr__(self, "field_validation_state", FieldValidationState(self.field_validation_state))
        except (TypeError, ValueError) as exc:
            raise R41Error(R41_SCHEMA_INVALID, "TypedReference contains an unsupported enum value") from exc
        if self.source_cursor is None and self.availability is Availability.AVAILABLE:
            raise R41Error(R41_SCHEMA_INVALID, "AVAILABLE TypedReference requires a source_cursor")
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref_type": self.ref_type,
            "object_id": self.object_id,
            "object_version": self.object_version,
            "revision": self.revision,
            "source_digest": self.source_digest,
            "source_cursor": self.source_cursor,
            "origin": self.origin,
            "observed_at": self.observed_at,
            "freshness": self.freshness.value,
            "availability": self.availability.value,
            "field_validation_state": self.field_validation_state.value,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TypedReference":
        if not isinstance(value, Mapping) or set(value) != _TYPED_REFERENCE_FIELDS:
            raise R41Error(R41_REFERENCE_INVALID, "TypedReference must contain exactly its declared fields")
        return cls(
            ref_type=value["ref_type"],
            object_id=value["object_id"],
            object_version=value["object_version"],
            revision=value["revision"],
            source_digest=value["source_digest"],
            source_cursor=value["source_cursor"],
            origin=value["origin"],
            observed_at=value["observed_at"],
            freshness=value["freshness"],
            availability=value["availability"],
            field_validation_state=value["field_validation_state"],
            correlation_id=value["correlation_id"],
        )


def _reference_payload(reference: TypedReference | None) -> dict[str, Any] | None:
    return reference.to_dict() if reference is not None else None


def _qv_digest_payload(value: "QualityVersion") -> dict[str, Any]:
    return {
        "quality_version_id": value.quality_version_id,
        "stream_owner_mission_id": value.stream_owner_mission_id,
        "project_ref": value.project_ref.to_dict(),
        "sut_ref": value.sut_ref.to_dict(),
        "environment_scope": _export(value.environment_scope),
        "version_label": value.version_label,
        "requirement_baseline_refs": [item.to_dict() for item in value.requirement_baseline_refs],
        "sst_baseline_refs": [item.to_dict() for item in value.sst_baseline_refs],
        "design_baseline_refs": [item.to_dict() for item in value.design_baseline_refs],
        "source_refs": [item.to_dict() for item in value.source_refs],
        "scope_digest": value.scope_digest,
        "predecessor_version_ref": _reference_payload(value.predecessor_version_ref),
        "field_validation_state_ref": value.field_validation_state_ref.to_dict(),
    }


def _campaign_digest_payload(value: "TestCampaign") -> dict[str, Any]:
    return {
        "campaign_id": value.campaign_id,
        "stream_owner_mission_id": value.stream_owner_mission_id,
        "quality_version_ref": value.quality_version_ref.to_dict(),
        "campaign_key": value.campaign_key,
        "campaign_kind": value.campaign_kind.value,
        "provenance": [item.to_dict() for item in value.provenance],
    }


def _selection_digest_payload(value: "CampaignSelectionRevision") -> dict[str, Any]:
    return {
        "selection_revision_id": value.selection_revision_id,
        "stream_owner_mission_id": value.stream_owner_mission_id,
        "campaign_ref": value.campaign_ref.to_dict(),
        "supersedes_revision_ref": _reference_payload(value.supersedes_revision_ref),
        "selected_input_refs": [item.to_dict() for item in value.selected_input_refs],
        "excluded_scope": _export(value.excluded_scope),
        "unknown_scope": _export(value.unknown_scope),
        "blocked_scope": _export(value.blocked_scope),
        "source_refs": [item.to_dict() for item in value.source_refs],
    }


@dataclass(frozen=True)
class QualityVersion:
    quality_version_id: str
    stream_owner_mission_id: str
    project_ref: TypedReference
    sut_ref: TypedReference
    environment_scope: Mapping[str, Any]
    version_label: str
    requirement_baseline_refs: tuple[TypedReference, ...]
    sst_baseline_refs: tuple[TypedReference, ...]
    design_baseline_refs: tuple[TypedReference, ...]
    source_refs: tuple[TypedReference, ...]
    scope_digest: str
    version_digest: str
    predecessor_version_ref: TypedReference | None
    field_validation_state_ref: TypedReference
    created_seq: int
    created_at: str
    correlation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "quality_version_id", _text(self.quality_version_id, "quality_version_id"))
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        if not isinstance(self.project_ref, TypedReference) or not isinstance(self.sut_ref, TypedReference):
            raise R41Error(R41_REFERENCE_INVALID, "project_ref and sut_ref must be TypedReference values")
        _require_ref_type(self.project_ref, "PROJECT", "project_ref")
        _require_ref_type(self.sut_ref, "SUT", "sut_ref")
        object.__setattr__(self, "environment_scope", _mapping(self.environment_scope, "environment_scope"))
        object.__setattr__(self, "version_label", _text(self.version_label, "version_label"))
        for name in ("requirement_baseline_refs", "sst_baseline_refs", "design_baseline_refs", "source_refs"):
            object.__setattr__(self, name, _tuple_refs(getattr(self, name), name))
        object.__setattr__(self, "scope_digest", _digest(self.scope_digest, "scope_digest"))
        object.__setattr__(self, "version_digest", _digest(self.version_digest, "version_digest"))
        object.__setattr__(self, "predecessor_version_ref", _optional_ref(self.predecessor_version_ref, "predecessor_version_ref"))
        if self.predecessor_version_ref is not None:
            _require_ref_type(self.predecessor_version_ref, "QUALITY_VERSION", "predecessor_version_ref")
        if not isinstance(self.field_validation_state_ref, TypedReference):
            raise R41Error(R41_REFERENCE_INVALID, "field_validation_state_ref must be a TypedReference")
        _require_ref_type(self.field_validation_state_ref, "FIELD_VALIDATION_STATE", "field_validation_state_ref")
        object.__setattr__(self, "created_seq", _positive_int(self.created_seq, "created_seq"))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        if self.version_digest != canonical_sha256(_qv_digest_payload(self)):
            raise R41Error(R41_DIGEST_MISMATCH, "version_digest does not cover the canonical QualityVersion payload")

    @property
    def lifecycle_state(self) -> QualityVersionLifecycle:
        return QualityVersionLifecycle.CREATED

    def immutable_payload(self) -> dict[str, Any]:
        return _qv_digest_payload(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.immutable_payload(),
            "version_digest": self.version_digest,
            "created_seq": self.created_seq,
            "created_at": self.created_at,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QualityVersion":
        if set(value) != QUALITY_VERSION_INPUT_FIELDS | {"created_seq", "created_at", "correlation_id"}:
            raise R41Error(R41_SCHEMA_INVALID, "QualityVersion state contains unknown or missing fields")
        return cls(
            quality_version_id=value["quality_version_id"], stream_owner_mission_id=value["stream_owner_mission_id"],
            project_ref=TypedReference.from_dict(value["project_ref"]), sut_ref=TypedReference.from_dict(value["sut_ref"]),
            environment_scope=value["environment_scope"], version_label=value["version_label"],
            requirement_baseline_refs=tuple(TypedReference.from_dict(item) for item in value.get("requirement_baseline_refs") or ()),
            sst_baseline_refs=tuple(TypedReference.from_dict(item) for item in value.get("sst_baseline_refs") or ()),
            design_baseline_refs=tuple(TypedReference.from_dict(item) for item in value.get("design_baseline_refs") or ()),
            source_refs=tuple(TypedReference.from_dict(item) for item in value.get("source_refs") or ()),
            scope_digest=value["scope_digest"], version_digest=value["version_digest"],
            predecessor_version_ref=_optional_ref(value.get("predecessor_version_ref"), "predecessor_version_ref"),
            field_validation_state_ref=TypedReference.from_dict(value["field_validation_state_ref"]),
            created_seq=value["created_seq"], created_at=value["created_at"], correlation_id=value["correlation_id"],
        )


@dataclass(frozen=True)
class TestCampaign:
    campaign_id: str
    stream_owner_mission_id: str
    quality_version_ref: TypedReference
    campaign_key: str
    campaign_kind: CampaignKind
    campaign_digest: str
    baseline_selection_revision_ref: TypedReference | None
    current_selection_revision_ref: TypedReference | None
    provenance: tuple[TypedReference, ...]
    created_seq: int
    created_at: str
    correlation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "campaign_id", _text(self.campaign_id, "campaign_id"))
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        if not isinstance(self.quality_version_ref, TypedReference):
            raise R41Error(R41_REFERENCE_INVALID, "quality_version_ref must be a TypedReference")
        _require_ref_type(self.quality_version_ref, "QUALITY_VERSION", "quality_version_ref")
        object.__setattr__(self, "campaign_key", _text(self.campaign_key, "campaign_key"))
        try:
            object.__setattr__(self, "campaign_kind", CampaignKind(self.campaign_kind))
        except (TypeError, ValueError) as exc:
            raise R41Error(R41_SCHEMA_INVALID, "campaign_kind must be BASELINE or SCOPED_EVALUATION") from exc
        object.__setattr__(self, "campaign_digest", _digest(self.campaign_digest, "campaign_digest"))
        object.__setattr__(self, "baseline_selection_revision_ref", _optional_ref(self.baseline_selection_revision_ref, "baseline_selection_revision_ref"))
        object.__setattr__(self, "current_selection_revision_ref", _optional_ref(self.current_selection_revision_ref, "current_selection_revision_ref"))
        for name in ("baseline_selection_revision_ref", "current_selection_revision_ref"):
            reference = getattr(self, name)
            if reference is not None:
                _require_ref_type(reference, "CAMPAIGN_SELECTION_REVISION", name)
        object.__setattr__(self, "provenance", _tuple_refs(self.provenance, "provenance"))
        object.__setattr__(self, "created_seq", _positive_int(self.created_seq, "created_seq"))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        if self.campaign_digest != canonical_sha256(_campaign_digest_payload(self)):
            raise R41Error(R41_DIGEST_MISMATCH, "campaign_digest does not cover the canonical TestCampaign payload")

    def immutable_payload(self) -> dict[str, Any]:
        return _campaign_digest_payload(self)

    @property
    def lifecycle_state(self) -> TestCampaignLifecycle:
        return TestCampaignLifecycle.SELECTION_RECORDED if self.current_selection_revision_ref else TestCampaignLifecycle.CREATED

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.immutable_payload(),
            "baseline_selection_revision_ref": _reference_payload(self.baseline_selection_revision_ref),
            "current_selection_revision_ref": _reference_payload(self.current_selection_revision_ref),
            "campaign_digest": self.campaign_digest,
            "created_seq": self.created_seq,
            "created_at": self.created_at,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TestCampaign":
        if set(value) != CAMPAIGN_INPUT_FIELDS | {"created_seq", "created_at", "correlation_id"}:
            raise R41Error(R41_SCHEMA_INVALID, "TestCampaign state contains unknown or missing fields")
        return cls(
            campaign_id=value["campaign_id"], stream_owner_mission_id=value["stream_owner_mission_id"],
            quality_version_ref=TypedReference.from_dict(value["quality_version_ref"]), campaign_key=value["campaign_key"],
            campaign_kind=value["campaign_kind"], campaign_digest=value["campaign_digest"],
            baseline_selection_revision_ref=_optional_ref(value.get("baseline_selection_revision_ref"), "baseline_selection_revision_ref"),
            current_selection_revision_ref=_optional_ref(value.get("current_selection_revision_ref"), "current_selection_revision_ref"),
            provenance=tuple(TypedReference.from_dict(item) for item in value.get("provenance") or ()),
            created_seq=value["created_seq"], created_at=value["created_at"], correlation_id=value["correlation_id"],
        )


@dataclass(frozen=True)
class CampaignSelectionRevision:
    selection_revision_id: str
    stream_owner_mission_id: str
    campaign_ref: TypedReference
    supersedes_revision_ref: TypedReference | None
    selected_input_refs: tuple[TypedReference, ...]
    excluded_scope: Mapping[str, Any]
    unknown_scope: Mapping[str, Any]
    blocked_scope: Mapping[str, Any]
    source_refs: tuple[TypedReference, ...]
    revision_digest: str
    created_seq: int
    created_at: str
    correlation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "selection_revision_id", _text(self.selection_revision_id, "selection_revision_id"))
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        if not isinstance(self.campaign_ref, TypedReference):
            raise R41Error(R41_REFERENCE_INVALID, "campaign_ref must be a TypedReference")
        _require_ref_type(self.campaign_ref, "TEST_CAMPAIGN", "campaign_ref")
        object.__setattr__(self, "supersedes_revision_ref", _optional_ref(self.supersedes_revision_ref, "supersedes_revision_ref"))
        if self.supersedes_revision_ref is not None:
            _require_ref_type(self.supersedes_revision_ref, "CAMPAIGN_SELECTION_REVISION", "supersedes_revision_ref")
        object.__setattr__(self, "selected_input_refs", _tuple_refs(self.selected_input_refs, "selected_input_refs"))
        object.__setattr__(self, "excluded_scope", _mapping(self.excluded_scope, "excluded_scope"))
        object.__setattr__(self, "unknown_scope", _mapping(self.unknown_scope, "unknown_scope"))
        object.__setattr__(self, "blocked_scope", _mapping(self.blocked_scope, "blocked_scope"))
        object.__setattr__(self, "source_refs", _tuple_refs(self.source_refs, "source_refs"))
        object.__setattr__(self, "revision_digest", _digest(self.revision_digest, "revision_digest"))
        object.__setattr__(self, "created_seq", _positive_int(self.created_seq, "created_seq"))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        if self.revision_digest != canonical_sha256(_selection_digest_payload(self)):
            raise R41Error(R41_DIGEST_MISMATCH, "revision_digest does not cover the canonical selection payload")

    def immutable_payload(self) -> dict[str, Any]:
        return _selection_digest_payload(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.immutable_payload(),
            "revision_digest": self.revision_digest,
            "created_seq": self.created_seq,
            "created_at": self.created_at,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignSelectionRevision":
        if set(value) != SELECTION_INPUT_FIELDS | {"created_seq", "created_at", "correlation_id"}:
            raise R41Error(R41_SCHEMA_INVALID, "CampaignSelectionRevision state contains unknown or missing fields")
        return cls(
            selection_revision_id=value["selection_revision_id"], stream_owner_mission_id=value["stream_owner_mission_id"],
            campaign_ref=TypedReference.from_dict(value["campaign_ref"]),
            supersedes_revision_ref=_optional_ref(value.get("supersedes_revision_ref"), "supersedes_revision_ref"),
            selected_input_refs=tuple(TypedReference.from_dict(item) for item in value.get("selected_input_refs") or ()),
            excluded_scope=value["excluded_scope"], unknown_scope=value["unknown_scope"], blocked_scope=value["blocked_scope"],
            source_refs=tuple(TypedReference.from_dict(item) for item in value.get("source_refs") or ()),
            revision_digest=value["revision_digest"], created_seq=value["created_seq"],
            created_at=value["created_at"], correlation_id=value["correlation_id"],
        )


@dataclass(frozen=True)
class R41State:
    mission_id: str
    quality_versions: tuple[QualityVersion, ...] = ()
    test_campaigns: tuple[TestCampaign, ...] = ()
    selection_revisions: tuple[CampaignSelectionRevision, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        for name, cls in (
            ("quality_versions", QualityVersion),
            ("test_campaigns", TestCampaign),
            ("selection_revisions", CampaignSelectionRevision),
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, cls) for item in values):
                raise R41Error(R41_SCHEMA_INVALID, f"{name} must be immutable typed tuples")
            id_field = {
                "quality_versions": "quality_version_id",
                "test_campaigns": "campaign_id",
                "selection_revisions": "selection_revision_id",
            }[name]
            ids = [getattr(item, id_field) for item in values]
            if len(ids) != len(set(ids)):
                raise R41Error(R41_IDENTITY_CONFLICT, f"{name} identities must be unique")

    def quality_version(self, object_id: str) -> QualityVersion | None:
        return next((item for item in self.quality_versions if item.quality_version_id == object_id), None)

    def campaign(self, object_id: str) -> TestCampaign | None:
        return next((item for item in self.test_campaigns if item.campaign_id == object_id), None)

    def selection_revision(self, object_id: str) -> CampaignSelectionRevision | None:
        return next((item for item in self.selection_revisions if item.selection_revision_id == object_id), None)

    def campaign_revisions(self, campaign_id: str) -> tuple[CampaignSelectionRevision, ...]:
        return tuple(item for item in self.selection_revisions if item.campaign_ref.object_id == campaign_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "quality_versions": [item.to_dict() for item in sorted(self.quality_versions, key=lambda item: item.quality_version_id)],
            "test_campaigns": [item.to_dict() for item in sorted(self.test_campaigns, key=lambda item: item.campaign_id)],
            "selection_revisions": [item.to_dict() for item in sorted(self.selection_revisions, key=lambda item: item.selection_revision_id)],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R41State":
        if set(value) != {"mission_id", "quality_versions", "test_campaigns", "selection_revisions"}:
            raise R41Error(R41_SCHEMA_INVALID, "R41State contains unknown or missing fields")
        return cls(
            mission_id=value["mission_id"],
            quality_versions=tuple(QualityVersion.from_dict(item) for item in value.get("quality_versions") or ()),
            test_campaigns=tuple(TestCampaign.from_dict(item) for item in value.get("test_campaigns") or ()),
            selection_revisions=tuple(CampaignSelectionRevision.from_dict(item) for item in value.get("selection_revisions") or ()),
        )


def _qv_digest_payload_from_input(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _require_fields(value, QUALITY_VERSION_INPUT_FIELDS, "QualityVersion")
    return {
        "quality_version_id": _text(raw["quality_version_id"], "quality_version_id"),
        "stream_owner_mission_id": _text(raw["stream_owner_mission_id"], "stream_owner_mission_id"),
        "project_ref": TypedReference.from_dict(raw["project_ref"]).to_dict(),
        "sut_ref": TypedReference.from_dict(raw["sut_ref"]).to_dict(),
        "environment_scope": _mapping(raw["environment_scope"], "environment_scope"),
        "version_label": _text(raw["version_label"], "version_label"),
        "requirement_baseline_refs": [item.to_dict() for item in _tuple_refs(raw["requirement_baseline_refs"], "requirement_baseline_refs")],
        "sst_baseline_refs": [item.to_dict() for item in _tuple_refs(raw["sst_baseline_refs"], "sst_baseline_refs")],
        "design_baseline_refs": [item.to_dict() for item in _tuple_refs(raw["design_baseline_refs"], "design_baseline_refs")],
        "source_refs": [item.to_dict() for item in _tuple_refs(raw["source_refs"], "source_refs")],
        "scope_digest": _digest(raw["scope_digest"], "scope_digest"),
        "predecessor_version_ref": _reference_payload(_optional_ref(raw["predecessor_version_ref"], "predecessor_version_ref")),
        "field_validation_state_ref": TypedReference.from_dict(raw["field_validation_state_ref"]).to_dict(),
    }


def _campaign_digest_payload_from_input(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _require_fields(value, CAMPAIGN_INPUT_FIELDS, "TestCampaign")
    return {
        "campaign_id": _text(raw["campaign_id"], "campaign_id"),
        "stream_owner_mission_id": _text(raw["stream_owner_mission_id"], "stream_owner_mission_id"),
        "quality_version_ref": TypedReference.from_dict(raw["quality_version_ref"]).to_dict(),
        "campaign_key": _text(raw["campaign_key"], "campaign_key"),
        "campaign_kind": CampaignKind(raw["campaign_kind"]).value,
        "provenance": [item.to_dict() for item in _tuple_refs(raw["provenance"], "provenance")],
    }


def _selection_digest_payload_from_input(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _require_fields(value, SELECTION_INPUT_FIELDS, "CampaignSelectionRevision")
    return {
        "selection_revision_id": _text(raw["selection_revision_id"], "selection_revision_id"),
        "stream_owner_mission_id": _text(raw["stream_owner_mission_id"], "stream_owner_mission_id"),
        "campaign_ref": TypedReference.from_dict(raw["campaign_ref"]).to_dict(),
        "supersedes_revision_ref": _reference_payload(_optional_ref(raw["supersedes_revision_ref"], "supersedes_revision_ref")),
        "selected_input_refs": [item.to_dict() for item in _tuple_refs(raw["selected_input_refs"], "selected_input_refs")],
        "excluded_scope": _mapping(raw["excluded_scope"], "excluded_scope"),
        "unknown_scope": _mapping(raw["unknown_scope"], "unknown_scope"),
        "blocked_scope": _mapping(raw["blocked_scope"], "blocked_scope"),
        "source_refs": [item.to_dict() for item in _tuple_refs(raw["source_refs"], "source_refs")],
    }


def quality_version_digest(value: QualityVersion | Mapping[str, Any]) -> str:
    if isinstance(value, QualityVersion):
        return canonical_sha256(_qv_digest_payload(value))
    if isinstance(value, Mapping):
        return canonical_sha256(_qv_digest_payload_from_input(value))
    raise R41Error(R41_SCHEMA_INVALID, "quality_version_digest requires a QualityVersion or input mapping")


def campaign_digest(value: TestCampaign | Mapping[str, Any]) -> str:
    if isinstance(value, TestCampaign):
        return canonical_sha256(_campaign_digest_payload(value))
    if isinstance(value, Mapping):
        return canonical_sha256(_campaign_digest_payload_from_input(value))
    raise R41Error(R41_SCHEMA_INVALID, "campaign_digest requires a TestCampaign or input mapping")


def selection_revision_digest(value: CampaignSelectionRevision | Mapping[str, Any]) -> str:
    if isinstance(value, CampaignSelectionRevision):
        return canonical_sha256(_selection_digest_payload(value))
    if isinstance(value, Mapping):
        return canonical_sha256(_selection_digest_payload_from_input(value))
    raise R41Error(R41_SCHEMA_INVALID, "selection_revision_digest requires a CampaignSelectionRevision or input mapping")


QUALITY_VERSION_INPUT_FIELDS = frozenset(
    {
        "quality_version_id", "stream_owner_mission_id", "project_ref", "sut_ref", "environment_scope",
        "version_label", "requirement_baseline_refs", "sst_baseline_refs", "design_baseline_refs", "source_refs",
        "scope_digest", "version_digest", "predecessor_version_ref", "field_validation_state_ref",
    }
)
CAMPAIGN_INPUT_FIELDS = frozenset(
    {
        "campaign_id", "stream_owner_mission_id", "quality_version_ref", "campaign_key", "campaign_kind",
        "campaign_digest", "baseline_selection_revision_ref", "current_selection_revision_ref", "provenance",
    }
)
SELECTION_INPUT_FIELDS = frozenset(
    {
        "selection_revision_id", "stream_owner_mission_id", "campaign_ref", "supersedes_revision_ref",
        "selected_input_refs", "excluded_scope", "unknown_scope", "blocked_scope", "source_refs", "revision_digest",
    }
)


def _require_fields(payload: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise R41Error(R41_SCHEMA_INVALID, f"{name} payload contains unknown or missing fields")
    return dict(payload)


def quality_version_from_input(payload: Mapping[str, Any], *, created_seq: int, created_at: str, correlation_id: str) -> QualityVersion:
    raw = _require_fields(payload, QUALITY_VERSION_INPUT_FIELDS, "QualityVersion")
    return QualityVersion(
        quality_version_id=raw["quality_version_id"], stream_owner_mission_id=raw["stream_owner_mission_id"],
        project_ref=TypedReference.from_dict(raw["project_ref"]), sut_ref=TypedReference.from_dict(raw["sut_ref"]),
        environment_scope=raw["environment_scope"], version_label=raw["version_label"],
        requirement_baseline_refs=_tuple_refs(raw["requirement_baseline_refs"], "requirement_baseline_refs"),
        sst_baseline_refs=_tuple_refs(raw["sst_baseline_refs"], "sst_baseline_refs"),
        design_baseline_refs=_tuple_refs(raw["design_baseline_refs"], "design_baseline_refs"),
        source_refs=_tuple_refs(raw["source_refs"], "source_refs"), scope_digest=raw["scope_digest"],
        version_digest=raw["version_digest"], predecessor_version_ref=_optional_ref(raw["predecessor_version_ref"], "predecessor_version_ref"),
        field_validation_state_ref=TypedReference.from_dict(raw["field_validation_state_ref"]),
        created_seq=created_seq, created_at=created_at, correlation_id=correlation_id,
    )


def campaign_from_input(payload: Mapping[str, Any], *, created_seq: int, created_at: str, correlation_id: str) -> TestCampaign:
    raw = _require_fields(payload, CAMPAIGN_INPUT_FIELDS, "TestCampaign")
    return TestCampaign(
        campaign_id=raw["campaign_id"], stream_owner_mission_id=raw["stream_owner_mission_id"],
        quality_version_ref=TypedReference.from_dict(raw["quality_version_ref"]), campaign_key=raw["campaign_key"],
        campaign_kind=raw["campaign_kind"], campaign_digest=raw["campaign_digest"],
        baseline_selection_revision_ref=_optional_ref(raw["baseline_selection_revision_ref"], "baseline_selection_revision_ref"),
        current_selection_revision_ref=_optional_ref(raw["current_selection_revision_ref"], "current_selection_revision_ref"),
        provenance=_tuple_refs(raw["provenance"], "provenance"), created_seq=created_seq,
        created_at=created_at, correlation_id=correlation_id,
    )


def selection_from_input(payload: Mapping[str, Any], *, created_seq: int, created_at: str, correlation_id: str) -> CampaignSelectionRevision:
    raw = _require_fields(payload, SELECTION_INPUT_FIELDS, "CampaignSelectionRevision")
    return CampaignSelectionRevision(
        selection_revision_id=raw["selection_revision_id"], stream_owner_mission_id=raw["stream_owner_mission_id"],
        campaign_ref=TypedReference.from_dict(raw["campaign_ref"]),
        supersedes_revision_ref=_optional_ref(raw["supersedes_revision_ref"], "supersedes_revision_ref"),
        selected_input_refs=_tuple_refs(raw["selected_input_refs"], "selected_input_refs"),
        excluded_scope=raw["excluded_scope"], unknown_scope=raw["unknown_scope"], blocked_scope=raw["blocked_scope"],
        source_refs=_tuple_refs(raw["source_refs"], "source_refs"), revision_digest=raw["revision_digest"],
        created_seq=created_seq, created_at=created_at, correlation_id=correlation_id,
    )


def input_payload(value: QualityVersion | TestCampaign | CampaignSelectionRevision) -> dict[str, Any]:
    if isinstance(value, QualityVersion):
        return {key: value.to_dict()[key] for key in QUALITY_VERSION_INPUT_FIELDS}
    if isinstance(value, TestCampaign):
        return {key: value.to_dict()[key] for key in CAMPAIGN_INPUT_FIELDS}
    if isinstance(value, CampaignSelectionRevision):
        return {key: value.to_dict()[key] for key in SELECTION_INPUT_FIELDS}
    raise R41Error(R41_SCHEMA_INVALID, "unsupported R4.1 aggregate value")
