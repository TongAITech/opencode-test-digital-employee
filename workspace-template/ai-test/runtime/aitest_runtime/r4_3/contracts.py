from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from aitest_runtime.durable_core.canonical import canonical_json, canonical_sha256
from aitest_runtime.r4_1.contracts import (
    Availability,
    FieldValidationState,
    Freshness,
    TypedReference,
)

from .errors import (
    FIX_DETECTION_CONFLICT,
    FIX_DETECTION_INCONCLUSIVE,
    FIX_LINK_INVALID,
    FIX_SOURCE_STALE,
    SCOPE_MISMATCH,
    R43Error,
)


EXTENSION_ID = "r4_3_confirmed_defect_fix_resolution_lifecycle"
EXTENSION_VERSION = "1.0.0"
SCHEMA_VERSION = 1
DETECTION_POLICY_VERSION = "r4.3-fix-detection-policy-v1"

R4_3_OPEN_CONFIRMED_DEFECT_LIFECYCLE = "R4_3_OPEN_CONFIRMED_DEFECT_LIFECYCLE.v1"
R4_3_RECORD_FIX_LINK = "R4_3_RECORD_FIX_LINK.v1"
R4_3_REQUEST_FIX_DETECTION = "R4_3_REQUEST_FIX_DETECTION.v1"
R4_3_RECORD_FIX_DETECTION_ASSESSMENT = "R4_3_RECORD_FIX_DETECTION_ASSESSMENT.v1"

R43_LIFECYCLE_OPENED = "r4.3.confirmed_defect_lifecycle_opened.v1"
R43_FIX_LINK_RECORDED = "r4.3.fix_link_recorded.v1"
R43_FIX_DETECTION_REQUESTED = "r4.3.fix_detection_requested.v1"
R43_FIX_DETECTION_ASSESSMENT_RECORDED = "r4.3.fix_detection_assessment_recorded.v1"

COMMAND_TYPES = frozenset(
    {
        R4_3_OPEN_CONFIRMED_DEFECT_LIFECYCLE,
        R4_3_RECORD_FIX_LINK,
        R4_3_REQUEST_FIX_DETECTION,
        R4_3_RECORD_FIX_DETECTION_ASSESSMENT,
    }
)
EVENT_TYPES = frozenset(
    {
        R43_LIFECYCLE_OPENED,
        R43_FIX_LINK_RECORDED,
        R43_FIX_DETECTION_REQUESTED,
        R43_FIX_DETECTION_ASSESSMENT_RECORDED,
    }
)


class LifecycleState(str, Enum):
    CONFIRMED = "CONFIRMED"
    FIX_LINKED = "FIX_LINKED"
    FIX_DETECTION_PENDING = "FIX_DETECTION_PENDING"
    FIX_DETECTED = "FIX_DETECTED"
    FIX_NOT_DETECTED = "FIX_NOT_DETECTED"
    FIX_DETECTION_UNKNOWN = "FIX_DETECTION_UNKNOWN"
    BLOCKED = "BLOCKED"


ConfirmedDefectLifecycleState = LifecycleState


class FixLinkOrigin(str, Enum):
    EXPLICIT_CLAIM = "EXPLICIT_CLAIM"
    SOURCE_DETECTED_CANDIDATE = "SOURCE_DETECTED_CANDIDATE"
    INFERRED_CANDIDATE = "INFERRED_CANDIDATE"
    LEGACY_ADAPTER_CLAIM = "LEGACY_ADAPTER_CLAIM"


class ObservationKind(str, Enum):
    SOURCE_REVISION = "SOURCE_REVISION"
    BUILD_CONTENT = "BUILD_CONTENT"
    DEPLOYMENT_CONTENT = "DEPLOYMENT_CONTENT"
    ENVIRONMENT_BINDING = "ENVIRONMENT_BINDING"
    MANUAL_ATTESTATION = "MANUAL_ATTESTATION"
    LEGACY_ADAPTER = "LEGACY_ADAPTER"


class DetectionScope(str, Enum):
    SOURCE = "SOURCE"
    BUILD = "BUILD"
    DEPLOYMENT = "DEPLOYMENT"


class FixDetectionOutcome(str, Enum):
    DETECTED = "DETECTED"
    NOT_DETECTED = "NOT_DETECTED"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    CONFLICT = "CONFLICT"


FixDetectionAssessmentOutcome = FixDetectionOutcome
DetectionOutcome = FixDetectionOutcome
FixSourceObservationKind = ObservationKind


class EvidenceClass(str, Enum):
    SOURCE_REVISION_EVIDENCE = "SOURCE_REVISION_EVIDENCE"
    BUILD_CONTENT_EVIDENCE = "BUILD_CONTENT_EVIDENCE"
    DEPLOYMENT_CONTENT_EVIDENCE = "DEPLOYMENT_CONTENT_EVIDENCE"
    ENVIRONMENT_DEPLOYMENT_EVIDENCE = "ENVIRONMENT_DEPLOYMENT_EVIDENCE"
    MANUAL_ATTESTATION = "MANUAL_ATTESTATION"
    LEGACY_ADAPTER_EVIDENCE = "LEGACY_ADAPTER_EVIDENCE"


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN = frozenset(
    {
        "raw", "raw_payload", "raw_content", "payload", "body", "content", "diff", "patch",
        "transcript", "secret", "token", "cookie", "password", "credential", "access_token",
    }
)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R43Error("R4_3_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise R43Error("R4_3_SCHEMA_INVALID", f"{name} must be a lowercase SHA-256 digest")
    return value


def _seq(value: Any, name: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise R43Error("R4_3_SCHEMA_INVALID", f"{name} must be an integer >= {minimum}")
    return value


def _json(value: Any, name: str = "value") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise R43Error("R4_3_SCHEMA_INVALID", f"{name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower().replace("-", "_") in _FORBIDDEN:
                raise R43Error("R4_3_SCHEMA_INVALID", f"{name} contains a forbidden raw/source field")
            result[key_text] = _json(item, f"{name}.{key_text}")
        return result
    if isinstance(value, (list, tuple)):
        return [_json(item, f"{name}[]") for item in value]
    raise R43Error("R4_3_SCHEMA_INVALID", f"{name} contains an unsupported value")


def _enum(cls: type[Enum], value: Any, name: str) -> Any:
    try:
        return cls(value)
    except (TypeError, ValueError) as exc:
        raise R43Error("R4_3_SCHEMA_INVALID", f"{name} contains an unsupported enum value") from exc


def _ref(value: Any, name: str) -> TypedReference:
    if isinstance(value, Mapping):
        value = TypedReference.from_dict(value)
    if not isinstance(value, TypedReference):
        raise R43Error("R4_3_REFERENCE_INVALID", f"{name} must be a TypedReference")
    return value


def reference_sort_key(reference: TypedReference) -> tuple[str, str, str, int, str, str, str]:
    return (
        reference.ref_type,
        reference.object_id,
        str(reference.object_version),
        reference.revision,
        "" if reference.source_cursor is None else str(reference.source_cursor),
        reference.source_digest,
        canonical_json(reference.to_dict()),
    )


def canonical_references(value: Iterable[TypedReference | Mapping[str, Any]]) -> tuple[TypedReference, ...]:
    refs = tuple(_ref(item, "reference") for item in value)
    return tuple(sorted(refs, key=reference_sort_key))


def _refs(value: Any, name: str, *, sort: bool = True) -> tuple[TypedReference, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise R43Error("R4_3_REFERENCE_INVALID", f"{name} must be an array of TypedReference values")
    refs = canonical_references(value) if sort else tuple(_ref(item, f"{name}[]") for item in value)
    if len({canonical_json(item.to_dict()) for item in refs}) != len(refs):
        raise R43Error("R4_3_REFERENCE_INVALID", f"{name} must not contain duplicate references")
    return refs


def _optional_ref(value: Any, name: str) -> TypedReference | None:
    return None if value is None else _ref(value, name)


def _texts(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise R43Error("R4_3_SCHEMA_INVALID", f"{name} must be an array")
    result = tuple(sorted({_text(item, f"{name}[]") for item in value}))
    return result


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise R43Error("R4_3_SCHEMA_INVALID", f"{name} must be an object")
    return MappingProxyType(_json(value, name))


def _export(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, TypedReference):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _export(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_export(item) for item in value]
    return value


def _ref_payload(value: TypedReference | None) -> dict[str, Any] | None:
    return value.to_dict() if value is not None else None


def _require_ref_type(reference: TypedReference, expected: str, name: str) -> None:
    if reference.ref_type != expected:
        raise R43Error("R4_3_REFERENCE_INVALID", f"{name} must have ref_type={expected}")


def _finish_digest(obj: Any, field_name: str, body: Mapping[str, Any], supplied: str | None) -> None:
    expected = canonical_sha256(body)
    if supplied is not None and supplied != expected:
        raise R43Error("R4_3_DIGEST_MISMATCH", f"{field_name} does not match its canonical immutable body")
    object.__setattr__(obj, field_name, expected)


def lifecycle_identity(
    owner_mission_id: str,
    assessment_ref: TypedReference,
    assessment_digest: str,
    quality_version_ref: TypedReference,
    campaign_refs: Iterable[TypedReference],
) -> str:
    return canonical_sha256([
        _text(owner_mission_id, "owner_mission_id"),
        _ref(assessment_ref, "r3_6_defect_assessment_ref").to_dict(),
        _digest(assessment_digest, "r3_6_assessment_digest"),
        _ref(quality_version_ref, "quality_version_ref").to_dict(),
        [item.to_dict() for item in canonical_references(campaign_refs)],
    ])


def lifecycle_id_for(*args: Any, **kwargs: Any) -> str:
    return f"r4.3:lifecycle:{lifecycle_identity(*args, **kwargs)}"


def _lifecycle_digest_payload(value: "ConfirmedDefectLifecycle") -> dict[str, Any]:
    return {
        "lifecycle_id": value.lifecycle_id,
        "stream_owner_mission_id": value.stream_owner_mission_id,
        "r3_6_defect_assessment_ref": value.r3_6_defect_assessment_ref.to_dict(),
        "r3_6_assessment_digest": value.r3_6_assessment_digest,
        "quality_version_ref": value.quality_version_ref.to_dict(),
        "campaign_refs": [item.to_dict() for item in value.campaign_refs],
        "severity_refs": [item.to_dict() for item in value.severity_refs],
        "priority_refs": [item.to_dict() for item in value.priority_refs],
        "rca_refs": [item.to_dict() for item in value.rca_refs],
        "evidence_refs": [item.to_dict() for item in value.evidence_refs],
        "origin_lineage": _export(value.origin_lineage),
    }


@dataclass(frozen=True)
class ConfirmedDefectLifecycle:
    lifecycle_id: str
    stream_owner_mission_id: str
    r3_6_defect_assessment_ref: TypedReference
    r3_6_assessment_digest: str
    quality_version_ref: TypedReference
    campaign_refs: tuple[TypedReference, ...]
    state: LifecycleState
    lifecycle_digest: str | None
    created_seq: int
    created_at: str
    correlation_id: str
    severity_refs: tuple[TypedReference, ...] = ()
    priority_refs: tuple[TypedReference, ...] = ()
    rca_refs: tuple[TypedReference, ...] = ()
    evidence_refs: tuple[TypedReference, ...] = ()
    fix_link_refs: tuple[TypedReference, ...] = ()
    fix_detection_refs: tuple[TypedReference, ...] = ()
    origin_lineage: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "lifecycle_id", _text(self.lifecycle_id, "lifecycle_id"))
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        assessment_ref = _ref(self.r3_6_defect_assessment_ref, "r3_6_defect_assessment_ref")
        _require_ref_type(assessment_ref, "R3_6_DEFECT_ASSESSMENT", "r3_6_defect_assessment_ref")
        object.__setattr__(self, "r3_6_defect_assessment_ref", assessment_ref)
        object.__setattr__(self, "r3_6_assessment_digest", _digest(self.r3_6_assessment_digest, "r3_6_assessment_digest"))
        if assessment_ref.source_digest != self.r3_6_assessment_digest:
            raise R43Error("R3_ASSESSMENT_DIGEST_CONFLICT", "R3.6 reference digest differs from lifecycle digest")
        qv = _ref(self.quality_version_ref, "quality_version_ref")
        _require_ref_type(qv, "QUALITY_VERSION", "quality_version_ref")
        object.__setattr__(self, "quality_version_ref", qv)
        campaigns = _refs(self.campaign_refs, "campaign_refs")
        if not campaigns:
            raise R43Error("R4_3_SCHEMA_INVALID", "campaign_refs must contain at least one Campaign")
        for item in campaigns:
            _require_ref_type(item, "TEST_CAMPAIGN", "campaign_refs[]")
        object.__setattr__(self, "campaign_refs", campaigns)
        object.__setattr__(self, "state", _enum(LifecycleState, self.state, "state"))
        for name in ("severity_refs", "priority_refs", "rca_refs", "evidence_refs", "fix_link_refs", "fix_detection_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage"))
        if not self.origin_lineage or self.origin_lineage.get("mission_id") not in (None, self.stream_owner_mission_id):
            raise R43Error(SCOPE_MISMATCH, "origin_lineage mission does not match lifecycle owner")
        object.__setattr__(self, "created_seq", _seq(self.created_seq, "created_seq"))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        expected_id = lifecycle_id_for(
            self.stream_owner_mission_id,
            self.r3_6_defect_assessment_ref,
            self.r3_6_assessment_digest,
            self.quality_version_ref,
            self.campaign_refs,
        )
        if self.lifecycle_id != expected_id:
            raise R43Error("R4_3_IDENTITY_INVALID", "lifecycle_id is not the canonical lifecycle identity")
        _finish_digest(self, "lifecycle_digest", _lifecycle_digest_payload(self), self.lifecycle_digest)

    def immutable_payload(self) -> dict[str, Any]:
        return _lifecycle_digest_payload(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.immutable_payload(),
            "state": self.state.value,
            "lifecycle_digest": self.lifecycle_digest,
            "created_seq": self.created_seq,
            "created_at": self.created_at,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConfirmedDefectLifecycle":
        return cls(
            lifecycle_id=value["lifecycle_id"], stream_owner_mission_id=value["stream_owner_mission_id"],
            r3_6_defect_assessment_ref=value["r3_6_defect_assessment_ref"],
            r3_6_assessment_digest=value["r3_6_assessment_digest"], quality_version_ref=value["quality_version_ref"],
            campaign_refs=tuple(value.get("campaign_refs") or ()), state=value.get("state", LifecycleState.CONFIRMED.value),
            lifecycle_digest=value.get("lifecycle_digest"), created_seq=value.get("created_seq", 1),
            created_at=value.get("created_at", "replayed"), correlation_id=value.get("correlation_id", "replayed"),
            severity_refs=tuple(value.get("severity_refs") or ()), priority_refs=tuple(value.get("priority_refs") or ()),
            rca_refs=tuple(value.get("rca_refs") or ()), evidence_refs=tuple(value.get("evidence_refs") or ()),
            fix_link_refs=tuple(value.get("fix_link_refs") or ()), fix_detection_refs=tuple(value.get("fix_detection_refs") or ()),
            origin_lineage=value.get("origin_lineage") or {},
        )


def lifecycle_from_input(value: Mapping[str, Any], *, created_seq: int, created_at: str, correlation_id: str) -> ConfirmedDefectLifecycle:
    return ConfirmedDefectLifecycle(
        lifecycle_id=value["lifecycle_id"], stream_owner_mission_id=value["stream_owner_mission_id"],
        r3_6_defect_assessment_ref=value["r3_6_defect_assessment_ref"], r3_6_assessment_digest=value["r3_6_assessment_digest"],
        quality_version_ref=value["quality_version_ref"], campaign_refs=tuple(value.get("campaign_refs") or ()),
        state=value.get("state", LifecycleState.CONFIRMED.value), lifecycle_digest=value.get("lifecycle_digest"),
        created_seq=created_seq, created_at=created_at, correlation_id=correlation_id,
        severity_refs=tuple(value.get("severity_refs") or ()), priority_refs=tuple(value.get("priority_refs") or ()),
        rca_refs=tuple(value.get("rca_refs") or ()), evidence_refs=tuple(value.get("evidence_refs") or ()),
        fix_link_refs=tuple(value.get("fix_link_refs") or ()), fix_detection_refs=tuple(value.get("fix_detection_refs") or ()),
        origin_lineage=value.get("origin_lineage") or {},
    )


def _fix_link_digest_payload(value: "FixLink") -> dict[str, Any]:
    return {
        "fix_link_id": value.fix_link_id,
        "stream_owner_mission_id": value.stream_owner_mission_id,
        "confirmed_defect_lifecycle_ref": value.confirmed_defect_lifecycle_ref.to_dict(),
        "fix_candidate_refs": [item.to_dict() for item in value.fix_candidate_refs],
        "source_change_refs": [item.to_dict() for item in value.source_change_refs],
        "commit_patch_pr_refs": [item.to_dict() for item in value.commit_patch_pr_refs],
        "build_ref": _ref_payload(value.build_ref), "deployment_ref": _ref_payload(value.deployment_ref),
        "environment_ref": _ref_payload(value.environment_ref),
        "claimed_scope_refs": [item.to_dict() for item in value.claimed_scope_refs],
        "link_origin": value.link_origin.value, "actor_id": value.actor_id,
        "source_ref": _ref_payload(value.source_ref), "confidence": value.confidence,
        "rationale_refs": list(value.rationale_refs), "freshness": value.freshness.value,
        "availability": value.availability.value, "provenance_refs": [item.to_dict() for item in value.provenance_refs],
        "supersedes_fix_link_ref": _ref_payload(value.supersedes_fix_link_ref), "attempt_key": value.attempt_key,
    }


def fix_link_identity(value: "FixLink") -> str:
    body = {
        "confirmed_defect_lifecycle_ref": value.confirmed_defect_lifecycle_ref.to_dict(),
        "fix_candidate_refs": [item.to_dict() for item in value.fix_candidate_refs],
        "source_change_refs": [item.to_dict() for item in value.source_change_refs],
        "commit_patch_pr_refs": [item.to_dict() for item in value.commit_patch_pr_refs],
        "build_ref": _ref_payload(value.build_ref), "deployment_ref": _ref_payload(value.deployment_ref),
        "environment_ref": _ref_payload(value.environment_ref),
        "claimed_scope_refs": [item.to_dict() for item in value.claimed_scope_refs],
        "link_origin": value.link_origin.value, "attempt_key": value.attempt_key,
        "source_revision_cursor": [
            [item.source_digest, item.source_cursor, item.revision]
            for item in canonical_references(value.source_change_refs + value.commit_patch_pr_refs + ((value.source_ref,) if value.source_ref else ()))
        ],
    }
    return canonical_sha256(body)


def fix_link_id_for(value: "FixLink") -> str:
    return f"r4.3:fix-link:{fix_link_identity(value)}"


@dataclass(frozen=True)
class FixLink:
    fix_link_id: str
    stream_owner_mission_id: str
    confirmed_defect_lifecycle_ref: TypedReference
    fix_candidate_refs: tuple[TypedReference, ...]
    source_change_refs: tuple[TypedReference, ...]
    commit_patch_pr_refs: tuple[TypedReference, ...]
    claimed_scope_refs: tuple[TypedReference, ...]
    link_origin: FixLinkOrigin
    actor_id: str
    source_ref: TypedReference | None
    confidence: float | None
    rationale_refs: tuple[str, ...]
    freshness: Freshness
    availability: Availability
    provenance_refs: tuple[TypedReference, ...]
    supersedes_fix_link_ref: TypedReference | None
    attempt_key: str
    link_digest: str | None
    created_seq: int
    created_at: str
    correlation_id: str
    build_ref: TypedReference | None = None
    deployment_ref: TypedReference | None = None
    environment_ref: TypedReference | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fix_link_id", _text(self.fix_link_id, "fix_link_id"))
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        lifecycle_ref = _ref(self.confirmed_defect_lifecycle_ref, "confirmed_defect_lifecycle_ref")
        _require_ref_type(lifecycle_ref, "R4_3_CONFIRMED_DEFECT_LIFECYCLE", "confirmed_defect_lifecycle_ref")
        object.__setattr__(self, "confirmed_defect_lifecycle_ref", lifecycle_ref)
        for name in ("fix_candidate_refs", "source_change_refs", "commit_patch_pr_refs", "claimed_scope_refs", "provenance_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        object.__setattr__(self, "build_ref", _optional_ref(self.build_ref, "build_ref"))
        object.__setattr__(self, "deployment_ref", _optional_ref(self.deployment_ref, "deployment_ref"))
        object.__setattr__(self, "environment_ref", _optional_ref(self.environment_ref, "environment_ref"))
        object.__setattr__(self, "source_ref", _optional_ref(self.source_ref, "source_ref"))
        object.__setattr__(self, "supersedes_fix_link_ref", _optional_ref(self.supersedes_fix_link_ref, "supersedes_fix_link_ref"))
        object.__setattr__(self, "link_origin", _enum(FixLinkOrigin, self.link_origin, "link_origin"))
        object.__setattr__(self, "actor_id", _text(self.actor_id, "actor_id"))
        object.__setattr__(self, "rationale_refs", _texts(self.rationale_refs, "rationale_refs"))
        object.__setattr__(self, "attempt_key", _text(self.attempt_key, "attempt_key"))
        object.__setattr__(self, "freshness", _enum(Freshness, self.freshness, "freshness"))
        object.__setattr__(self, "availability", _enum(Availability, self.availability, "availability"))
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(self.confidence, (float, int)) or not 0 <= self.confidence <= 1:
                raise R43Error("R4_3_SCHEMA_INVALID", "confidence must be between 0 and 1")
            object.__setattr__(self, "confidence", float(self.confidence))
        if self.link_origin is FixLinkOrigin.INFERRED_CANDIDATE and (
            self.confidence is None or not self.rationale_refs or not self.provenance_refs
        ):
            raise R43Error(FIX_LINK_INVALID, "INFERRED_CANDIDATE requires confidence, rationale_refs, and provenance_refs")
        object.__setattr__(self, "created_seq", _seq(self.created_seq, "created_seq"))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        expected_id = fix_link_id_for(self)
        if self.fix_link_id != expected_id:
            raise R43Error("R4_3_IDENTITY_INVALID", "fix_link_id is not the canonical immutable identity")
        _finish_digest(self, "link_digest", _fix_link_digest_payload(self), self.link_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            **_fix_link_digest_payload(self), "link_digest": self.link_digest,
            "created_seq": self.created_seq, "created_at": self.created_at, "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FixLink":
        return cls(
            fix_link_id=value["fix_link_id"], stream_owner_mission_id=value["stream_owner_mission_id"],
            confirmed_defect_lifecycle_ref=value["confirmed_defect_lifecycle_ref"],
            fix_candidate_refs=tuple(value.get("fix_candidate_refs") or ()), source_change_refs=tuple(value.get("source_change_refs") or ()),
            commit_patch_pr_refs=tuple(value.get("commit_patch_pr_refs") or ()), build_ref=value.get("build_ref"),
            deployment_ref=value.get("deployment_ref"), environment_ref=value.get("environment_ref"),
            claimed_scope_refs=tuple(value.get("claimed_scope_refs") or ()), link_origin=value["link_origin"],
            actor_id=value["actor_id"], source_ref=value.get("source_ref"), confidence=value.get("confidence"),
            rationale_refs=tuple(value.get("rationale_refs") or ()), freshness=value["freshness"],
            availability=value["availability"], provenance_refs=tuple(value.get("provenance_refs") or ()),
            supersedes_fix_link_ref=value.get("supersedes_fix_link_ref"), attempt_key=value["attempt_key"],
            link_digest=value.get("link_digest"), created_seq=value.get("created_seq", 1),
            created_at=value.get("created_at", "replayed"), correlation_id=value.get("correlation_id", "replayed"),
        )


def fix_link_from_input(value: Mapping[str, Any], *, created_seq: int, created_at: str, correlation_id: str) -> FixLink:
    return FixLink(
        fix_link_id=value["fix_link_id"], stream_owner_mission_id=value["stream_owner_mission_id"],
        confirmed_defect_lifecycle_ref=value["confirmed_defect_lifecycle_ref"], fix_candidate_refs=tuple(value.get("fix_candidate_refs") or ()),
        source_change_refs=tuple(value.get("source_change_refs") or ()), commit_patch_pr_refs=tuple(value.get("commit_patch_pr_refs") or ()),
        build_ref=value.get("build_ref"), deployment_ref=value.get("deployment_ref"), environment_ref=value.get("environment_ref"),
        claimed_scope_refs=tuple(value.get("claimed_scope_refs") or ()), link_origin=value["link_origin"], actor_id=value["actor_id"],
        source_ref=value.get("source_ref"), confidence=value.get("confidence"), rationale_refs=tuple(value.get("rationale_refs") or ()),
        freshness=value.get("freshness", Freshness.CURRENT.value), availability=value.get("availability", Availability.AVAILABLE.value),
        provenance_refs=tuple(value.get("provenance_refs") or ()), supersedes_fix_link_ref=value.get("supersedes_fix_link_ref"),
        attempt_key=value["attempt_key"], link_digest=value.get("link_digest"), created_seq=created_seq,
        created_at=created_at, correlation_id=correlation_id,
    )


@dataclass(frozen=True)
class FixSourceObservation:
    observation_kind: ObservationKind
    primary_ref: TypedReference
    related_refs: tuple[TypedReference, ...]
    scope_refs: tuple[TypedReference, ...]
    provenance_refs: tuple[TypedReference, ...]
    received_at: str
    correlation_id: str
    adapter_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_kind", _enum(ObservationKind, self.observation_kind, "observation_kind"))
        object.__setattr__(self, "primary_ref", _ref(self.primary_ref, "primary_ref"))
        for name in ("related_refs", "scope_refs", "provenance_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        object.__setattr__(self, "received_at", _text(self.received_at, "received_at"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "adapter_version", _text(self.adapter_version, "adapter_version"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_kind": self.observation_kind.value, "primary_ref": self.primary_ref.to_dict(),
            "related_refs": [item.to_dict() for item in self.related_refs], "scope_refs": [item.to_dict() for item in self.scope_refs],
            "provenance_refs": [item.to_dict() for item in self.provenance_refs], "received_at": self.received_at,
            "correlation_id": self.correlation_id, "adapter_version": self.adapter_version,
        }


def _detection_digest_payload(value: "FixDetectionAssessment") -> dict[str, Any]:
    return {
        "stream_owner_mission_id": value.stream_owner_mission_id,
        "confirmed_defect_lifecycle_ref": value.confirmed_defect_lifecycle_ref.to_dict(),
        "fix_link_ref": value.fix_link_ref.to_dict(), "quality_version_ref": value.quality_version_ref.to_dict(),
        "campaign_ref": value.campaign_ref.to_dict(), "detection_scope": value.detection_scope.value,
        "source_revision_refs": [item.to_dict() for item in value.source_revision_refs],
        "build_refs": [item.to_dict() for item in value.build_refs], "deployment_refs": [item.to_dict() for item in value.deployment_refs],
        "environment_refs": [item.to_dict() for item in value.environment_refs], "observation_refs": [item.to_dict() for item in value.observation_refs],
        "detection_basis": [item.value for item in value.detection_basis], "outcome": value.outcome.value,
        "reason_refs": list(value.reason_refs), "freshness": value.freshness.value, "availability": value.availability.value,
        "field_validation_state": value.field_validation_state.value, "evidence_refs": [item.to_dict() for item in value.evidence_refs],
        "detection_policy_version": value.detection_policy_version,
    }


def detection_identity(value: "FixDetectionAssessment") -> str:
    return canonical_sha256(_detection_digest_payload(value))


def detection_id_for(value: "FixDetectionAssessment") -> str:
    return f"r4.3:fix-detection:{detection_identity(value)}"


@dataclass(frozen=True)
class FixDetectionAssessment:
    fix_detection_id: str
    stream_owner_mission_id: str
    confirmed_defect_lifecycle_ref: TypedReference
    fix_link_ref: TypedReference
    quality_version_ref: TypedReference
    campaign_ref: TypedReference
    detection_scope: DetectionScope
    source_revision_refs: tuple[TypedReference, ...]
    build_refs: tuple[TypedReference, ...]
    deployment_refs: tuple[TypedReference, ...]
    environment_refs: tuple[TypedReference, ...]
    observation_refs: tuple[TypedReference, ...]
    detection_basis: tuple[EvidenceClass, ...]
    outcome: FixDetectionOutcome
    reason_refs: tuple[str, ...]
    freshness: Freshness
    availability: Availability
    field_validation_state: FieldValidationState
    evidence_refs: tuple[TypedReference, ...]
    detection_policy_version: str
    detection_digest: str | None
    created_seq: int
    created_at: str
    correlation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "fix_detection_id", _text(self.fix_detection_id, "fix_detection_id"))
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        for name, expected in (
            ("confirmed_defect_lifecycle_ref", "R4_3_CONFIRMED_DEFECT_LIFECYCLE"),
            ("fix_link_ref", "R4_3_FIX_LINK"), ("quality_version_ref", "QUALITY_VERSION"), ("campaign_ref", "TEST_CAMPAIGN"),
        ):
            ref = _ref(getattr(self, name), name)
            _require_ref_type(ref, expected, name)
            object.__setattr__(self, name, ref)
        object.__setattr__(self, "detection_scope", _enum(DetectionScope, self.detection_scope, "detection_scope"))
        for name in ("source_revision_refs", "build_refs", "deployment_refs", "environment_refs", "observation_refs", "evidence_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        basis = self.detection_basis
        if isinstance(basis, str):
            basis = (basis,)
        if not isinstance(basis, (list, tuple, set, frozenset)):
            raise R43Error("R4_3_SCHEMA_INVALID", "detection_basis must be an array of EvidenceClass values")
        object.__setattr__(self, "detection_basis", tuple(sorted({_enum(EvidenceClass, item, "detection_basis[]") for item in basis}, key=lambda item: item.value)))
        object.__setattr__(self, "outcome", _enum(FixDetectionOutcome, self.outcome, "outcome"))
        object.__setattr__(self, "reason_refs", _texts(self.reason_refs, "reason_refs"))
        object.__setattr__(self, "freshness", _enum(Freshness, self.freshness, "freshness"))
        object.__setattr__(self, "availability", _enum(Availability, self.availability, "availability"))
        object.__setattr__(self, "field_validation_state", _enum(FieldValidationState, self.field_validation_state, "field_validation_state"))
        object.__setattr__(self, "detection_policy_version", _text(self.detection_policy_version, "detection_policy_version"))
        object.__setattr__(self, "created_seq", _seq(self.created_seq, "created_seq"))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        expected_id = detection_id_for(self)
        if self.fix_detection_id != expected_id:
            raise R43Error("R4_3_IDENTITY_INVALID", "fix_detection_id is not the canonical immutable identity")
        _finish_digest(self, "detection_digest", _detection_digest_payload(self), self.detection_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fix_detection_id": self.fix_detection_id, **_detection_digest_payload(self), "detection_digest": self.detection_digest,
            "created_seq": self.created_seq, "created_at": self.created_at, "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FixDetectionAssessment":
        return cls(
            fix_detection_id=value["fix_detection_id"], stream_owner_mission_id=value["stream_owner_mission_id"],
            confirmed_defect_lifecycle_ref=value["confirmed_defect_lifecycle_ref"], fix_link_ref=value["fix_link_ref"],
            quality_version_ref=value["quality_version_ref"], campaign_ref=value["campaign_ref"], detection_scope=value["detection_scope"],
            source_revision_refs=tuple(value.get("source_revision_refs") or ()), build_refs=tuple(value.get("build_refs") or ()),
            deployment_refs=tuple(value.get("deployment_refs") or ()), environment_refs=tuple(value.get("environment_refs") or ()),
            observation_refs=tuple(value.get("observation_refs") or ()), detection_basis=tuple(value.get("detection_basis") or ()),
            outcome=value["outcome"], reason_refs=tuple(value.get("reason_refs") or ()), freshness=value["freshness"],
            availability=value["availability"], field_validation_state=value["field_validation_state"],
            evidence_refs=tuple(value.get("evidence_refs") or ()), detection_policy_version=value.get("detection_policy_version", DETECTION_POLICY_VERSION),
            detection_digest=value.get("detection_digest"), created_seq=value.get("created_seq", 1),
            created_at=value.get("created_at", "replayed"), correlation_id=value.get("correlation_id", "replayed"),
        )


def fix_detection_from_input(value: Mapping[str, Any], *, created_seq: int, created_at: str, correlation_id: str) -> FixDetectionAssessment:
    return FixDetectionAssessment(
        fix_detection_id=value["fix_detection_id"], stream_owner_mission_id=value["stream_owner_mission_id"],
        confirmed_defect_lifecycle_ref=value["confirmed_defect_lifecycle_ref"], fix_link_ref=value["fix_link_ref"],
        quality_version_ref=value["quality_version_ref"], campaign_ref=value["campaign_ref"], detection_scope=value["detection_scope"],
        source_revision_refs=tuple(value.get("source_revision_refs") or ()), build_refs=tuple(value.get("build_refs") or ()),
        deployment_refs=tuple(value.get("deployment_refs") or ()), environment_refs=tuple(value.get("environment_refs") or ()),
        observation_refs=tuple(value.get("observation_refs") or ()), detection_basis=tuple(value.get("detection_basis") or ()),
        outcome=value["outcome"], reason_refs=tuple(value.get("reason_refs") or ()),
        freshness=value.get("freshness", Freshness.UNKNOWN.value), availability=value.get("availability", Availability.UNKNOWN.value),
        field_validation_state=value.get("field_validation_state", FieldValidationState.PENDING.value),
        evidence_refs=tuple(value.get("evidence_refs") or ()), detection_policy_version=value.get("detection_policy_version", DETECTION_POLICY_VERSION),
        detection_digest=value.get("detection_digest"), created_seq=created_seq, created_at=created_at, correlation_id=correlation_id,
    )


@dataclass(frozen=True)
class FixDetectionRequest:
    request_id: str
    stream_owner_mission_id: str
    confirmed_defect_lifecycle_ref: TypedReference
    fix_link_ref: TypedReference
    quality_version_ref: TypedReference
    campaign_ref: TypedReference
    detection_scope: DetectionScope
    detection_policy_version: str
    created_seq: int
    created_at: str
    correlation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _text(self.request_id, "request_id"))
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        for name, expected in (
            ("confirmed_defect_lifecycle_ref", "R4_3_CONFIRMED_DEFECT_LIFECYCLE"),
            ("fix_link_ref", "R4_3_FIX_LINK"), ("quality_version_ref", "QUALITY_VERSION"), ("campaign_ref", "TEST_CAMPAIGN"),
        ):
            ref = _ref(getattr(self, name), name)
            _require_ref_type(ref, expected, name)
            object.__setattr__(self, name, ref)
        object.__setattr__(self, "detection_scope", _enum(DetectionScope, self.detection_scope, "detection_scope"))
        object.__setattr__(self, "detection_policy_version", _text(self.detection_policy_version, "detection_policy_version"))
        object.__setattr__(self, "created_seq", _seq(self.created_seq, "created_seq"))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id, "stream_owner_mission_id": self.stream_owner_mission_id,
            "confirmed_defect_lifecycle_ref": self.confirmed_defect_lifecycle_ref.to_dict(), "fix_link_ref": self.fix_link_ref.to_dict(),
            "quality_version_ref": self.quality_version_ref.to_dict(), "campaign_ref": self.campaign_ref.to_dict(),
            "detection_scope": self.detection_scope.value, "detection_policy_version": self.detection_policy_version,
            "created_seq": self.created_seq, "created_at": self.created_at, "correlation_id": self.correlation_id,
        }


def request_from_input(value: Mapping[str, Any], *, created_seq: int, created_at: str, correlation_id: str) -> FixDetectionRequest:
    return FixDetectionRequest(
        request_id=_text(value["request_id"], "request_id"), stream_owner_mission_id=_text(value["stream_owner_mission_id"], "stream_owner_mission_id"),
        confirmed_defect_lifecycle_ref=_ref(value["confirmed_defect_lifecycle_ref"], "confirmed_defect_lifecycle_ref"),
        fix_link_ref=_ref(value["fix_link_ref"], "fix_link_ref"), quality_version_ref=_ref(value["quality_version_ref"], "quality_version_ref"),
        campaign_ref=_ref(value["campaign_ref"], "campaign_ref"), detection_scope=_enum(DetectionScope, value["detection_scope"], "detection_scope"),
        detection_policy_version=_text(value.get("detection_policy_version", DETECTION_POLICY_VERSION), "detection_policy_version"),
        created_seq=created_seq, created_at=created_at, correlation_id=correlation_id,
    )


def assessment_order(value: FixDetectionAssessment) -> tuple[int, str, int, str]:
    refs = value.source_revision_refs + value.build_refs + value.deployment_refs + value.environment_refs + value.observation_refs
    revisions = [item.revision for item in refs]
    cursors = [str(item.source_cursor) for item in refs if item.source_cursor is not None]
    return (max(revisions, default=0), max(cursors, default=""), value.created_seq, value.fix_detection_id)


def _lifecycle_ref(value: ConfirmedDefectLifecycle) -> TypedReference:
    return TypedReference(
        ref_type="R4_3_CONFIRMED_DEFECT_LIFECYCLE", object_id=value.lifecycle_id, object_version="1", revision=1,
        source_digest=value.lifecycle_digest or canonical_sha256(value.to_dict()), source_cursor=value.created_seq,
        origin=R43_LIFECYCLE_OPENED, observed_at=value.created_at, freshness=Freshness.CURRENT,
        availability=Availability.AVAILABLE, field_validation_state=FieldValidationState.PASSED, correlation_id=value.correlation_id,
    )


def _fix_link_ref(value: FixLink) -> TypedReference:
    return TypedReference(
        ref_type="R4_3_FIX_LINK", object_id=value.fix_link_id, object_version="1", revision=1,
        source_digest=value.link_digest or canonical_sha256(value.to_dict()), source_cursor=value.created_seq,
        origin=R43_FIX_LINK_RECORDED, observed_at=value.created_at, freshness=Freshness.CURRENT,
        availability=Availability.AVAILABLE, field_validation_state=FieldValidationState.PASSED, correlation_id=value.correlation_id,
    )


def _assessment_ref(value: FixDetectionAssessment) -> TypedReference:
    return TypedReference(
        ref_type="R4_3_FIX_DETECTION_ASSESSMENT", object_id=value.fix_detection_id, object_version="1", revision=1,
        source_digest=value.detection_digest or canonical_sha256(value.to_dict()), source_cursor=value.created_seq,
        origin=R43_FIX_DETECTION_ASSESSMENT_RECORDED, observed_at=value.created_at, freshness=value.freshness,
        availability=value.availability, field_validation_state=value.field_validation_state, correlation_id=value.correlation_id,
    )


def lifecycle_ref(value: ConfirmedDefectLifecycle) -> TypedReference:
    return _lifecycle_ref(value)


def fix_link_ref(value: FixLink) -> TypedReference:
    return _fix_link_ref(value)


def detection_ref(value: FixDetectionAssessment) -> TypedReference:
    return _assessment_ref(value)


def validate_detection_rules(value: FixDetectionAssessment, link: FixLink | None = None) -> None:
    if value.detection_policy_version != DETECTION_POLICY_VERSION:
        raise R43Error("R4_3_POLICY_INVALID", "unsupported fix detection policy version")
    basis = set(value.detection_basis)
    if value.outcome is FixDetectionOutcome.DETECTED:
        if value.freshness is not Freshness.CURRENT or value.availability is not Availability.AVAILABLE:
            raise R43Error(FIX_SOURCE_STALE if value.freshness is Freshness.STALE else "FIX_SOURCE_UNAVAILABLE", "stale or unavailable evidence cannot produce DETECTED")
        if value.field_validation_state in {FieldValidationState.FAILED, FieldValidationState.UNAVAILABLE}:
            raise R43Error("FIX_SOURCE_UNAVAILABLE", "failed or unavailable fields cannot produce DETECTED")
        if EvidenceClass.MANUAL_ATTESTATION in basis or EvidenceClass.LEGACY_ADAPTER_EVIDENCE in basis:
            if not (basis - {EvidenceClass.MANUAL_ATTESTATION, EvidenceClass.LEGACY_ADAPTER_EVIDENCE}):
                raise R43Error(FIX_DETECTION_INCONCLUSIVE, "manual-only and legacy-only evidence cannot produce DETECTED")
        if value.detection_scope is DetectionScope.SOURCE and (
            not value.source_revision_refs or EvidenceClass.SOURCE_REVISION_EVIDENCE not in basis
        ):
            raise R43Error(FIX_DETECTION_INCONCLUSIVE, "SOURCE DETECTED requires exact source revision evidence")
        if value.detection_scope is DetectionScope.BUILD and (
            not value.build_refs or not value.source_revision_refs or EvidenceClass.BUILD_CONTENT_EVIDENCE not in basis
        ):
            raise R43Error(FIX_DETECTION_INCONCLUSIVE, "BUILD DETECTED requires build content and source digest evidence")
        if value.detection_scope is DetectionScope.DEPLOYMENT and (
            not value.deployment_refs or not value.environment_refs
            or EvidenceClass.DEPLOYMENT_CONTENT_EVIDENCE not in basis
            or EvidenceClass.ENVIRONMENT_DEPLOYMENT_EVIDENCE not in basis
        ):
            raise R43Error(FIX_DETECTION_INCONCLUSIVE, "DEPLOYMENT DETECTED requires deployment content and target binding")
        if link is not None:
            if value.detection_scope is DetectionScope.DEPLOYMENT and link.deployment_ref is None:
                raise R43Error(SCOPE_MISMATCH, "deployment detection has no linked deployment scope")
            if value.detection_scope is DetectionScope.BUILD and link.build_ref is None:
                raise R43Error(SCOPE_MISMATCH, "build detection has no linked build scope")
            if value.detection_scope is DetectionScope.SOURCE and not (link.source_change_refs or link.commit_patch_pr_refs or link.source_ref):
                raise R43Error(SCOPE_MISMATCH, "source detection has no linked source scope")
            if link.deployment_ref is not None and value.deployment_refs:
                linked = link.deployment_ref
                if any(item.object_id == linked.object_id and item.source_digest != linked.source_digest for item in value.deployment_refs):
                    raise R43Error(SCOPE_MISMATCH, "deployment identity or digest differs from the immutable FixLink scope")
            if link.environment_ref is not None and value.environment_refs:
                linked = link.environment_ref
                if any(item.object_id != linked.object_id or item.source_digest != linked.source_digest for item in value.environment_refs):
                    raise R43Error(SCOPE_MISMATCH, "target environment binding differs from the immutable FixLink scope")
            if link.claimed_scope_refs and value.source_revision_refs:
                claimed = {item.object_id for item in link.claimed_scope_refs}
                observed = {item.object_id for item in value.source_revision_refs}
                claimed_branches = {item for item in claimed if item.startswith("branch:")}
                observed_branches = {item for item in observed if item.startswith("branch:")}
                if claimed_branches and observed_branches and claimed_branches != observed_branches:
                    raise R43Error(SCOPE_MISMATCH, "source branch scope differs from the immutable FixLink claim")
            if link.deployment_ref is not None and link.deployment_ref.freshness is Freshness.STALE:
                if value.detection_scope is DetectionScope.DEPLOYMENT:
                    raise R43Error(FIX_SOURCE_STALE, "stale FixLink deployment scope cannot be current DETECTED")
        if value.detection_scope is DetectionScope.BUILD:
            source_digests = {item.source_digest for item in value.source_revision_refs}
            build_digests = {item.source_digest for item in value.build_refs}
            if source_digests != build_digests:
                raise R43Error(SCOPE_MISMATCH, "build content digest does not match source revision digest")
        if value.detection_scope is DetectionScope.DEPLOYMENT:
            deployment_ids = {item.object_id for item in value.deployment_refs}
            environment_ids = {item.object_id for item in value.environment_refs}
            if not deployment_ids or not environment_ids:
                raise R43Error(SCOPE_MISMATCH, "deployment and environment identities are required")
            if any(item.freshness is not Freshness.CURRENT for item in value.deployment_refs + value.environment_refs):
                raise R43Error(FIX_SOURCE_STALE, "stale deployment evidence cannot produce DETECTED")
    if value.outcome is FixDetectionOutcome.NOT_DETECTED:
        if value.availability is not Availability.AVAILABLE or value.freshness is not Freshness.CURRENT or not value.evidence_refs or not value.reason_refs:
            raise R43Error(FIX_DETECTION_INCONCLUSIVE, "NOT_DETECTED requires current, available, queryable evidence")
    if value.outcome is FixDetectionOutcome.BLOCKED:
        missing_identity = value.detection_scope is DetectionScope.SOURCE and not value.source_revision_refs or value.detection_scope is DetectionScope.BUILD and not value.build_refs or value.detection_scope is DetectionScope.DEPLOYMENT and (not value.deployment_refs or not value.environment_refs)
        if value.availability is Availability.AVAILABLE and value.freshness is Freshness.CURRENT and value.field_validation_state is FieldValidationState.PASSED and not missing_identity:
            raise R43Error(FIX_DETECTION_INCONCLUSIVE, "BLOCKED requires unavailable evidence or a critical missing identity")
    if value.outcome is FixDetectionOutcome.CONFLICT:
        all_refs = value.source_revision_refs + value.build_refs + value.deployment_refs + value.environment_refs
        by_identity: dict[tuple[str, str], set[str]] = {}
        for item in all_refs:
            by_identity.setdefault((item.ref_type, item.object_id), set()).add(item.source_digest)
        contradictory = any(len(digests) > 1 for digests in by_identity.values())
        if not value.reason_refs or value.availability is not Availability.AVAILABLE or not contradictory:
            raise R43Error(FIX_DETECTION_CONFLICT, "CONFLICT requires available contradictory observations and reasons")


def make_lifecycle(
    *, owner_mission_id: str, r3_6_defect_assessment_ref: TypedReference, r3_6_assessment_digest: str,
    quality_version_ref: TypedReference, campaign_refs: Iterable[TypedReference], correlation_id: str,
    created_seq: int = 1, created_at: str = "constructed", **kwargs: Any,
) -> ConfirmedDefectLifecycle:
    kwargs.setdefault("origin_lineage", {"mission_id": owner_mission_id, "source": "r3.6.event-stream"})
    return ConfirmedDefectLifecycle(
        lifecycle_id=lifecycle_id_for(owner_mission_id, r3_6_defect_assessment_ref, r3_6_assessment_digest, quality_version_ref, tuple(campaign_refs)),
        stream_owner_mission_id=owner_mission_id, r3_6_defect_assessment_ref=r3_6_defect_assessment_ref,
        r3_6_assessment_digest=r3_6_assessment_digest, quality_version_ref=quality_version_ref,
        campaign_refs=tuple(campaign_refs), state=LifecycleState.CONFIRMED, lifecycle_digest=None,
        created_seq=created_seq, created_at=created_at, correlation_id=correlation_id, **kwargs,
    )


def make_fix_link(
    *,
    stream_owner_mission_id: str,
    confirmed_defect_lifecycle_ref: TypedReference,
    fix_candidate_refs: Iterable[TypedReference] = (),
    source_change_refs: Iterable[TypedReference] = (),
    commit_patch_pr_refs: Iterable[TypedReference] = (),
    build_ref: TypedReference | None = None,
    deployment_ref: TypedReference | None = None,
    environment_ref: TypedReference | None = None,
    claimed_scope_refs: Iterable[TypedReference] = (),
    link_origin: FixLinkOrigin | str = FixLinkOrigin.EXPLICIT_CLAIM,
    actor_id: str = "SYSTEM",
    source_ref: TypedReference | None = None,
    confidence: float | None = None,
    rationale_refs: Iterable[str] = (),
    freshness: Freshness | str = Freshness.CURRENT,
    availability: Availability | str = Availability.AVAILABLE,
    provenance_refs: Iterable[TypedReference] = (),
    supersedes_fix_link_ref: TypedReference | None = None,
    attempt_key: str = "attempt-1",
    correlation_id: str = "r4.3:fix-link",
    created_seq: int = 1,
    created_at: str = "constructed",
) -> FixLink:
    raw = dict(
        stream_owner_mission_id=stream_owner_mission_id, confirmed_defect_lifecycle_ref=confirmed_defect_lifecycle_ref,
        fix_candidate_refs=canonical_references(fix_candidate_refs), source_change_refs=canonical_references(source_change_refs),
        commit_patch_pr_refs=canonical_references(commit_patch_pr_refs), build_ref=_optional_ref(build_ref, "build_ref"),
        deployment_ref=_optional_ref(deployment_ref, "deployment_ref"), environment_ref=_optional_ref(environment_ref, "environment_ref"),
        claimed_scope_refs=canonical_references(claimed_scope_refs), link_origin=FixLinkOrigin(link_origin), actor_id=actor_id,
        source_ref=_optional_ref(source_ref, "source_ref"), confidence=confidence, rationale_refs=_texts(rationale_refs, "rationale_refs"),
        freshness=Freshness(freshness), availability=Availability(availability), provenance_refs=canonical_references(provenance_refs),
        supersedes_fix_link_ref=_optional_ref(supersedes_fix_link_ref, "supersedes_fix_link_ref"), attempt_key=attempt_key,
    )
    provisional = object.__new__(FixLink)
    for key, value in raw.items():
        object.__setattr__(provisional, key, value)
    identifier = fix_link_id_for(provisional)
    return FixLink(fix_link_id=identifier, link_digest=None, created_seq=created_seq, created_at=created_at, correlation_id=correlation_id, **raw)


def make_detection(
    *,
    stream_owner_mission_id: str,
    confirmed_defect_lifecycle_ref: TypedReference,
    fix_link_ref: TypedReference,
    quality_version_ref: TypedReference,
    campaign_ref: TypedReference,
    detection_scope: DetectionScope | str,
    source_revision_refs: Iterable[TypedReference] = (),
    build_refs: Iterable[TypedReference] = (),
    deployment_refs: Iterable[TypedReference] = (),
    environment_refs: Iterable[TypedReference] = (),
    observation_refs: Iterable[TypedReference] = (),
    detection_basis: Iterable[EvidenceClass | str] = (),
    outcome: FixDetectionOutcome | str = FixDetectionOutcome.UNKNOWN,
    reason_refs: Iterable[str] = (),
    freshness: Freshness | str = Freshness.UNKNOWN,
    availability: Availability | str = Availability.UNKNOWN,
    field_validation_state: FieldValidationState | str = FieldValidationState.PENDING,
    evidence_refs: Iterable[TypedReference] = (),
    detection_policy_version: str = DETECTION_POLICY_VERSION,
    detection_digest: str | None = None,
    correlation_id: str = "r4.3:fix-detection",
    created_seq: int = 1,
    created_at: str = "constructed",
) -> FixDetectionAssessment:
    raw = dict(
        stream_owner_mission_id=stream_owner_mission_id, confirmed_defect_lifecycle_ref=confirmed_defect_lifecycle_ref,
        fix_link_ref=fix_link_ref, quality_version_ref=quality_version_ref, campaign_ref=campaign_ref,
        detection_scope=DetectionScope(detection_scope), source_revision_refs=canonical_references(source_revision_refs),
        build_refs=canonical_references(build_refs), deployment_refs=canonical_references(deployment_refs),
        environment_refs=canonical_references(environment_refs), observation_refs=canonical_references(observation_refs),
        detection_basis=tuple(sorted({EvidenceClass(item) for item in detection_basis}, key=lambda item: item.value)),
        outcome=FixDetectionOutcome(outcome), reason_refs=_texts(reason_refs, "reason_refs"), freshness=Freshness(freshness),
        availability=Availability(availability), field_validation_state=FieldValidationState(field_validation_state),
        evidence_refs=canonical_references(evidence_refs), detection_policy_version=detection_policy_version,
    )
    provisional = object.__new__(FixDetectionAssessment)
    for key, value in raw.items():
        object.__setattr__(provisional, key, value)
    identifier = detection_id_for(provisional)
    return FixDetectionAssessment(fix_detection_id=identifier, detection_digest=detection_digest, created_seq=created_seq, created_at=created_at, correlation_id=correlation_id, **raw)


__all__ = [
    "EXTENSION_ID", "EXTENSION_VERSION", "SCHEMA_VERSION", "DETECTION_POLICY_VERSION", "COMMAND_TYPES", "EVENT_TYPES",
    "R4_3_OPEN_CONFIRMED_DEFECT_LIFECYCLE", "R4_3_RECORD_FIX_LINK", "R4_3_REQUEST_FIX_DETECTION", "R4_3_RECORD_FIX_DETECTION_ASSESSMENT",
    "R43_LIFECYCLE_OPENED", "R43_FIX_LINK_RECORDED", "R43_FIX_DETECTION_REQUESTED", "R43_FIX_DETECTION_ASSESSMENT_RECORDED",
    "LifecycleState", "ConfirmedDefectLifecycleState", "FixLinkOrigin", "ObservationKind", "FixSourceObservationKind", "DetectionScope", "FixDetectionOutcome", "FixDetectionAssessmentOutcome", "DetectionOutcome", "EvidenceClass",
    "ConfirmedDefectLifecycle", "FixLink", "FixSourceObservation", "FixDetectionAssessment", "FixDetectionRequest", "R43State",
    "lifecycle_identity", "lifecycle_id_for", "fix_link_identity", "fix_link_id_for", "detection_identity", "detection_id_for",
    "lifecycle_from_input", "fix_link_from_input", "fix_detection_from_input", "request_from_input", "canonical_references",
    "reference_sort_key", "lifecycle_ref", "fix_link_ref", "detection_ref", "validate_detection_rules", "make_lifecycle", "make_fix_link", "make_detection",
]


@dataclass(frozen=True)
class R43State:
    mission_id: str
    confirmed_defect_lifecycles: tuple[ConfirmedDefectLifecycle, ...] = ()
    fix_links: tuple[FixLink, ...] = ()
    fix_detection_requests: tuple[FixDetectionRequest, ...] = ()
    fix_detection_assessments: tuple[FixDetectionAssessment, ...] = ()
    lifecycle_by_assessment_scope: Mapping[str, str] = field(default_factory=dict)
    links_by_lifecycle: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    links_by_fix_candidate: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    detections_by_fix_link: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    latest_detection_by_scope: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        for name, cls in (("confirmed_defect_lifecycles", ConfirmedDefectLifecycle), ("fix_links", FixLink), ("fix_detection_requests", FixDetectionRequest), ("fix_detection_assessments", FixDetectionAssessment)):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, cls) for item in values):
                raise R43Error("R4_3_STATE_INVALID", f"{name} must be immutable typed tuples")
        object.__setattr__(self, "lifecycle_by_assessment_scope", MappingProxyType(dict(self.lifecycle_by_assessment_scope)))
        object.__setattr__(self, "links_by_lifecycle", MappingProxyType({str(k): tuple(v) for k, v in self.links_by_lifecycle.items()}))
        object.__setattr__(self, "links_by_fix_candidate", MappingProxyType({str(k): tuple(v) for k, v in self.links_by_fix_candidate.items()}))
        object.__setattr__(self, "detections_by_fix_link", MappingProxyType({str(k): tuple(v) for k, v in self.detections_by_fix_link.items()}))
        object.__setattr__(self, "latest_detection_by_scope", MappingProxyType(dict(self.latest_detection_by_scope)))

    def lifecycle(self, value: str) -> ConfirmedDefectLifecycle | None:
        return next((item for item in self.confirmed_defect_lifecycles if item.lifecycle_id == value), None)

    def fix_link(self, value: str) -> FixLink | None:
        return next((item for item in self.fix_links if item.fix_link_id == value), None)

    def detection(self, value: str) -> FixDetectionAssessment | None:
        return next((item for item in self.fix_detection_assessments if item.fix_detection_id == value), None)

    def request(self, value: str) -> FixDetectionRequest | None:
        return next((item for item in self.fix_detection_requests if item.request_id == value), None)

    def to_dict(self) -> dict[str, Any]:
        # Requests are operational pending state, deliberately not an additional canonical/projection record.
        return {
            "mission_id": self.mission_id,
            "confirmed_defect_lifecycles": [item.to_dict() for item in sorted(self.confirmed_defect_lifecycles, key=lambda x: x.lifecycle_id)],
            "fix_links": [item.to_dict() for item in sorted(self.fix_links, key=lambda x: x.fix_link_id)],
            "fix_detection_assessments": [item.to_dict() for item in sorted(self.fix_detection_assessments, key=lambda x: x.fix_detection_id)],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R43State":
        return cls(
            mission_id=value["mission_id"],
            confirmed_defect_lifecycles=tuple(ConfirmedDefectLifecycle.from_dict(item) for item in value.get("confirmed_defect_lifecycles") or ()),
            fix_links=tuple(FixLink.from_dict(item) for item in value.get("fix_links") or ()),
            fix_detection_assessments=tuple(FixDetectionAssessment.from_dict(item) for item in value.get("fix_detection_assessments") or ()),
        )
