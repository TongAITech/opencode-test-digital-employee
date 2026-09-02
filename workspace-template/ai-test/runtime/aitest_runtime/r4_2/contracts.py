from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.r4_1.contracts import (
    Availability,
    FieldValidationState,
    Freshness,
    TypedReference,
)

from .errors import (
    IMPACT_INPUT_INVALID,
    INVALID_TRIGGER,
    R2_BRIDGE_REJECTED,
    R42Error,
)


EXTENSION_ID = "r4_2_continuous_trigger_impact_r2_bridge"
EXTENSION_VERSION = "1.0.0"
SCHEMA_VERSION = 1
ASSESSMENT_POLICY_VERSION = "r4.2-impact-policy-v1"

R4_2_RECORD_TRIGGER_RECEIPT = "R4_2_RECORD_TRIGGER_RECEIPT.v1"
R4_2_RECORD_IMPACT_ASSESSMENT = "R4_2_RECORD_IMPACT_ASSESSMENT.v1"
R4_2_LINK_SELECTION_REVISION = "R4_2_LINK_SELECTION_REVISION.v1"
R4_2_REQUEST_R2_PLAN_REVISION_BRIDGE = "R4_2_REQUEST_R2_PLAN_REVISION_BRIDGE.v1"
R4_2_RECORD_R2_BRIDGE_RESULT = "R4_2_RECORD_R2_BRIDGE_RESULT.v1"

R42_TRIGGER_RECORDED = "r4.2.trigger_recorded.v1"
R42_IMPACT_ASSESSMENT_RECORDED = "r4.2.impact_assessment_recorded.v1"
R42_SELECTION_REVISION_LINKED = "r4.2.selection_revision_linked.v1"
R42_R2_PLAN_REVISION_BRIDGE_REQUESTED = "r4.2.r2_plan_revision_bridge_requested.v1"
R42_R2_PLAN_REVISION_BRIDGE_RESULT_RECORDED = "r4.2.r2_plan_revision_bridge_result_recorded.v1"

COMMAND_TYPES = frozenset(
    {
        R4_2_RECORD_TRIGGER_RECEIPT,
        R4_2_RECORD_IMPACT_ASSESSMENT,
        R4_2_LINK_SELECTION_REVISION,
        R4_2_REQUEST_R2_PLAN_REVISION_BRIDGE,
        R4_2_RECORD_R2_BRIDGE_RESULT,
    }
)
EVENT_TYPES = frozenset(
    {
        R42_TRIGGER_RECORDED,
        R42_IMPACT_ASSESSMENT_RECORDED,
        R42_SELECTION_REVISION_LINKED,
        R42_R2_PLAN_REVISION_BRIDGE_REQUESTED,
        R42_R2_PLAN_REVISION_BRIDGE_RESULT_RECORDED,
    }
)


class TriggerKind(str, Enum):
    REQUIREMENT_CHANGED = "REQUIREMENT_CHANGED"
    SST_CHANGED = "SST_CHANGED"
    DESIGN_CHANGED = "DESIGN_CHANGED"
    CODE_CHANGED = "CODE_CHANGED"
    CHANGE_IMPACT_CHANGED = "CHANGE_IMPACT_CHANGED"
    DEPLOYMENT_CHANGED = "DEPLOYMENT_CHANGED"
    DEPLOYMENT_ROLLED_BACK = "DEPLOYMENT_ROLLED_BACK"
    DEFECT_FIX_CHANGED = "DEFECT_FIX_CHANGED"
    ENVIRONMENT_RECOVERED = "ENVIRONMENT_RECOVERED"
    RESOURCE_RECOVERED = "RESOURCE_RECOVERED"
    MANUAL_REASSESSMENT = "MANUAL_REASSESSMENT"


class Materiality(str, Enum):
    NONE = "NONE"
    MATERIAL = "MATERIAL"
    UNKNOWN = "UNKNOWN"


class ImpactDecision(str, Enum):
    NO_MATERIAL_IMPACT = "NO_MATERIAL_IMPACT"
    SELECTION_REVISION_REQUIRED = "SELECTION_REVISION_REQUIRED"
    BLOCKED = "BLOCKED"
    INCONCLUSIVE = "INCONCLUSIVE"


class SourceEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class BridgeStatus(str, Enum):
    R2_REQUESTED = "R2_REQUESTED"
    R2_REVISION_LINKED = "R2_REVISION_LINKED"
    R2_NO_CHANGE = "R2_NO_CHANGE"
    R2_REJECTED = "R2_REJECTED"
    R2_UNAVAILABLE = "R2_UNAVAILABLE"
    R2_RESULT_CONFLICT = "R2_RESULT_CONFLICT"


_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R42Error("R4_2_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise R42Error("R4_2_SCHEMA_INVALID", f"{name} must be a lowercase SHA-256 digest")
    return value


def _seq(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise R42Error("R4_2_SCHEMA_INVALID", f"{name} must be an integer >= {minimum}")
    return value


def _json(value: Any, name: str = "value") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise R42Error("R4_2_SCHEMA_INVALID", f"{name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise R42Error("R4_2_SCHEMA_INVALID", f"{name} object keys must be strings")
            result[key] = _json(item, f"{name}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_json(item, f"{name}[]") for item in value]
    raise R42Error("R4_2_SCHEMA_INVALID", f"{name} contains an unsupported value")


def _ref(value: Any, name: str) -> TypedReference:
    if isinstance(value, Mapping):
        value = TypedReference.from_dict(value)
    if not isinstance(value, TypedReference):
        raise R42Error("R4_2_REFERENCE_INVALID", f"{name} must be a TypedReference")
    return value


def _refs(value: Any, name: str) -> tuple[TypedReference, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise R42Error("R4_2_REFERENCE_INVALID", f"{name} must be an array of TypedReference values")
    result = tuple(_ref(item, f"{name}[]") for item in value)
    return tuple(sorted(result, key=reference_sort_key))


def _optional_ref(value: Any, name: str) -> TypedReference | None:
    if value is None:
        return None
    return _ref(value, name)


def _enum(cls: type[Enum], value: Any, name: str) -> Any:
    try:
        return cls(value)
    except (TypeError, ValueError) as exc:
        raise R42Error("R4_2_SCHEMA_INVALID", f"{name} contains an unsupported enum value") from exc


def _export(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, TypedReference):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(k): _export(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_export(item) for item in value]
    return value


def reference_sort_key(reference: TypedReference) -> tuple[str, str, str, int, str, str]:
    cursor = "" if reference.source_cursor is None else str(reference.source_cursor)
    return (
        reference.ref_type,
        reference.object_id,
        str(reference.object_version),
        reference.revision,
        cursor,
        reference.source_digest,
    )


def canonical_references(value: Iterable[TypedReference]) -> tuple[TypedReference, ...]:
    return tuple(sorted(tuple(value), key=reference_sort_key))


def source_stream_key(reference: TypedReference | Mapping[str, Any]) -> str:
    ref = _ref(reference, "source_ref")
    return canonical_sha256([ref.origin, ref.ref_type, ref.object_id])


def scope_identity(scope_refs: Iterable[TypedReference | Mapping[str, Any]]) -> str:
    return canonical_sha256([item.to_dict() for item in canonical_references(_ref(v, "scope_ref") for v in scope_refs)])


def trigger_identity(
    mission_id: str,
    quality_version_ref: TypedReference,
    campaign_ref: TypedReference,
    trigger_kind: TriggerKind | str,
    source_ref: TypedReference,
    scope_refs: Iterable[TypedReference],
) -> str:
    source = _ref(source_ref, "source_ref")
    return canonical_sha256(
        [
            _text(mission_id, "stream_owner_mission_id"),
            _ref(quality_version_ref, "quality_version_ref").object_id,
            _ref(campaign_ref, "campaign_ref").object_id,
            _enum(TriggerKind, trigger_kind, "trigger_kind").value,
            source_stream_key(source),
            source.revision,
            source.source_cursor,
            scope_identity(scope_refs),
        ]
    )


def trigger_id_for(*args: Any, **kwargs: Any) -> str:
    return f"r4.2:trigger:{trigger_identity(*args, **kwargs)}"


def dedupe_key_for(identity: str) -> str:
    return f"r4.2:dedupe:{_digest(identity, 'trigger_identity')}"


def coalescing_key_for(
    mission_id: str,
    quality_version_ref: TypedReference,
    campaign_ref: TypedReference,
    scope_refs: Iterable[TypedReference],
    current_selection_ref: TypedReference | None = None,
    open_epoch: str | int = 0,
) -> str:
    values = [
        _text(mission_id, "mission_id"),
        _ref(quality_version_ref, "quality_version_ref").object_id,
        _ref(campaign_ref, "campaign_ref").object_id,
        scope_identity(scope_refs),
        _optional_ref(current_selection_ref, "current_selection_ref").object_id if current_selection_ref else None,
        open_epoch,
    ]
    from aitest_runtime.durable_core import canonical_json
    return f"r4.2:coalesce({canonical_json(values)})"


def _trigger_digest_payload(value: "ContinuousTestTrigger") -> dict[str, Any]:
    return {
        "trigger_id": value.trigger_id,
        "stream_owner_mission_id": value.stream_owner_mission_id,
        "quality_version_ref": value.quality_version_ref.to_dict(),
        "campaign_ref": value.campaign_ref.to_dict(),
        "trigger_kind": value.trigger_kind.value,
        "source_ref": value.source_ref.to_dict(),
        "scope_refs": [item.to_dict() for item in value.scope_refs],
        "received_at": value.received_at,
        "dedupe_key": value.dedupe_key,
        "coalescing_key": value.coalescing_key,
        "correlation_id": value.correlation_id,
        "provenance_refs": [item.to_dict() for item in value.provenance_refs],
        "freshness": value.freshness.value,
        "availability": value.availability.value,
        "field_validation_state": value.field_validation_state.value,
        "source_eligibility": value.source_eligibility.value,
    }


@dataclass(frozen=True)
class ContinuousTestTrigger:
    trigger_id: str
    stream_owner_mission_id: str
    quality_version_ref: TypedReference
    campaign_ref: TypedReference
    trigger_kind: TriggerKind
    source_ref: TypedReference
    scope_refs: tuple[TypedReference, ...]
    received_at: str
    dedupe_key: str
    coalescing_key: str
    correlation_id: str
    provenance_refs: tuple[TypedReference, ...]
    freshness: Freshness
    availability: Availability
    field_validation_state: FieldValidationState
    trigger_digest: str
    source_eligibility: SourceEligibility

    def __post_init__(self) -> None:
        object.__setattr__(self, "trigger_id", _text(self.trigger_id, "trigger_id"))
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        object.__setattr__(self, "quality_version_ref", _ref(self.quality_version_ref, "quality_version_ref"))
        object.__setattr__(self, "campaign_ref", _ref(self.campaign_ref, "campaign_ref"))
        object.__setattr__(self, "trigger_kind", _enum(TriggerKind, self.trigger_kind, "trigger_kind"))
        object.__setattr__(self, "source_ref", _ref(self.source_ref, "source_ref"))
        object.__setattr__(self, "scope_refs", _refs(self.scope_refs, "scope_refs"))
        object.__setattr__(self, "provenance_refs", _refs(self.provenance_refs, "provenance_refs"))
        object.__setattr__(self, "received_at", _text(self.received_at, "received_at"))
        object.__setattr__(self, "dedupe_key", _text(self.dedupe_key, "dedupe_key"))
        object.__setattr__(self, "coalescing_key", _text(self.coalescing_key, "coalescing_key"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "freshness", _enum(Freshness, self.freshness, "freshness"))
        object.__setattr__(self, "availability", _enum(Availability, self.availability, "availability"))
        object.__setattr__(self, "field_validation_state", _enum(FieldValidationState, self.field_validation_state, "field_validation_state"))
        object.__setattr__(self, "trigger_digest", _digest(self.trigger_digest, "trigger_digest"))
        object.__setattr__(self, "source_eligibility", _enum(SourceEligibility, self.source_eligibility, "source_eligibility"))
        if self.source_ref.source_cursor is None and self.source_ref.availability is Availability.AVAILABLE:
            raise R42Error(INVALID_TRIGGER, "AVAILABLE source references require source_cursor")
        expected_identity = trigger_identity(
            self.stream_owner_mission_id, self.quality_version_ref, self.campaign_ref,
            self.trigger_kind, self.source_ref, self.scope_refs,
        )
        if self.trigger_id != f"r4.2:trigger:{expected_identity}":
            raise R42Error(INVALID_TRIGGER, "trigger_id is not the canonical trigger identity")
        if self.dedupe_key != dedupe_key_for(expected_identity):
            raise R42Error(INVALID_TRIGGER, "dedupe_key is not the canonical trigger identity")
        expected_eligibility = source_eligibility_for(self.source_ref, self.freshness, self.availability, self.field_validation_state)
        if self.source_eligibility is not expected_eligibility:
            raise R42Error(INVALID_TRIGGER, "source_eligibility does not match source freshness and availability")
        if self.trigger_digest != canonical_sha256(_trigger_digest_payload(self)):
            raise R42Error("R4_2_DIGEST_MISMATCH", "trigger_digest does not cover immutable receipt semantics")

    @property
    def source_stream_key(self) -> str:
        return source_stream_key(self.source_ref)

    @property
    def source_revision(self) -> int:
        return self.source_ref.revision

    @property
    def source_cursor(self) -> str | int | None:
        return self.source_ref.source_cursor

    def to_dict(self) -> dict[str, Any]:
        return {**_trigger_digest_payload(self), "trigger_digest": self.trigger_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContinuousTestTrigger":
        required = {
            "trigger_id", "stream_owner_mission_id", "quality_version_ref", "campaign_ref", "trigger_kind",
            "source_ref", "scope_refs", "received_at", "dedupe_key", "coalescing_key", "correlation_id",
            "provenance_refs", "freshness", "availability", "field_validation_state", "trigger_digest", "source_eligibility",
        }
        if set(value) != required:
            raise R42Error("R4_2_SCHEMA_INVALID", "ContinuousTestTrigger contains unknown or missing fields")
        return cls(
            trigger_id=value["trigger_id"], stream_owner_mission_id=value["stream_owner_mission_id"],
            quality_version_ref=_ref(value["quality_version_ref"], "quality_version_ref"),
            campaign_ref=_ref(value["campaign_ref"], "campaign_ref"), trigger_kind=value["trigger_kind"],
            source_ref=_ref(value["source_ref"], "source_ref"), scope_refs=_refs(value["scope_refs"], "scope_refs"),
            received_at=value["received_at"], dedupe_key=value["dedupe_key"], coalescing_key=value["coalescing_key"],
            correlation_id=value["correlation_id"], provenance_refs=_refs(value["provenance_refs"], "provenance_refs"),
            freshness=value["freshness"], availability=value["availability"], field_validation_state=value["field_validation_state"],
            trigger_digest=value["trigger_digest"], source_eligibility=value["source_eligibility"],
        )


def source_eligibility_for(
    source_ref: TypedReference,
    freshness: Freshness | str,
    availability: Availability | str,
    validation: FieldValidationState | str,
) -> SourceEligibility:
    fresh = _enum(Freshness, freshness, "freshness")
    available = _enum(Availability, availability, "availability")
    validated = _enum(FieldValidationState, validation, "field_validation_state")
    if fresh is Freshness.STALE:
        return SourceEligibility.STALE
    if available is not Availability.AVAILABLE or validated is not FieldValidationState.PASSED:
        return SourceEligibility.UNAVAILABLE
    return SourceEligibility.ELIGIBLE


def build_trigger(
    *,
    stream_owner_mission_id: str,
    quality_version_ref: TypedReference | Mapping[str, Any],
    campaign_ref: TypedReference | Mapping[str, Any],
    trigger_kind: TriggerKind | str,
    source_ref: TypedReference | Mapping[str, Any],
    scope_refs: Iterable[TypedReference | Mapping[str, Any]] = (),
    received_at: str,
    correlation_id: str,
    provenance_refs: Iterable[TypedReference | Mapping[str, Any]] = (),
    current_selection_ref: TypedReference | Mapping[str, Any] | None = None,
    open_epoch: str | int = 0,
) -> ContinuousTestTrigger:
    quality = _ref(quality_version_ref, "quality_version_ref")
    campaign = _ref(campaign_ref, "campaign_ref")
    source = _ref(source_ref, "source_ref")
    scope = _refs(tuple(scope_refs), "scope_refs")
    kind = _enum(TriggerKind, trigger_kind, "trigger_kind")
    identity = trigger_identity(stream_owner_mission_id, quality, campaign, kind, source, scope)
    eligibility = source_eligibility_for(source, source.freshness, source.availability, source.field_validation_state)
    values = dict(
        trigger_id=f"r4.2:trigger:{identity}", stream_owner_mission_id=stream_owner_mission_id,
        quality_version_ref=quality, campaign_ref=campaign, trigger_kind=kind, source_ref=source,
        scope_refs=scope, received_at=received_at, dedupe_key=dedupe_key_for(identity),
        coalescing_key=coalescing_key_for(stream_owner_mission_id, quality, campaign, scope, _optional_ref(current_selection_ref, "current_selection_ref"), open_epoch),
        correlation_id=correlation_id, provenance_refs=_refs(tuple(provenance_refs), "provenance_refs"),
        freshness=source.freshness, availability=source.availability, field_validation_state=source.field_validation_state,
        source_eligibility=eligibility,
    )
    values["trigger_digest"] = "0" * 64
    # Compute the digest without weakening the constructor's invariant.
    provisional = object.__new__(ContinuousTestTrigger)
    for key, item in values.items():
        object.__setattr__(provisional, key, item)
    values["trigger_digest"] = canonical_sha256(_trigger_digest_payload(provisional))
    return ContinuousTestTrigger(**values)


def _assessment_digest_payload(value: "ImpactAssessment") -> dict[str, Any]:
    return {
        "impact_assessment_id": value.impact_assessment_id,
        "stream_owner_mission_id": value.stream_owner_mission_id,
        "quality_version_ref": value.quality_version_ref.to_dict(),
        "campaign_ref": value.campaign_ref.to_dict(),
        "trigger_refs": [item.to_dict() for item in value.trigger_refs],
        "r3_requirement_coverage_refs": [item.to_dict() for item in value.r3_requirement_coverage_refs],
        "r3_change_impact_refs": [item.to_dict() for item in value.r3_change_impact_refs],
        "affected_refs": [item.to_dict() for item in value.affected_refs],
        "unaffected_refs": [item.to_dict() for item in value.unaffected_refs],
        "unknown_refs": [item.to_dict() for item in value.unknown_refs],
        "blocked_refs": [item.to_dict() for item in value.blocked_refs],
        "unmapped_unresolved_refs": [item.to_dict() for item in value.unmapped_unresolved_refs],
        "materiality": value.materiality.value,
        "decision": value.decision.value,
        "reason_refs": [item.to_dict() for item in value.reason_refs],
        "source_digests": list(value.source_digests),
        "assessment_policy_version": value.assessment_policy_version,
        "input_set_digest": value.input_set_digest,
    }


def assessment_id_for(coalescing_key: str, input_set_digest: str, exact_r3_refs: Iterable[TypedReference], policy: str) -> str:
    refs = [item.to_dict() for item in canonical_references(exact_r3_refs)]
    return f"r4.2:impact:{canonical_sha256([coalescing_key, input_set_digest, refs, policy])}"


@dataclass(frozen=True)
class ImpactAssessment:
    impact_assessment_id: str
    stream_owner_mission_id: str
    quality_version_ref: TypedReference
    campaign_ref: TypedReference
    trigger_refs: tuple[TypedReference, ...]
    r3_requirement_coverage_refs: tuple[TypedReference, ...]
    r3_change_impact_refs: tuple[TypedReference, ...]
    affected_refs: tuple[TypedReference, ...]
    unaffected_refs: tuple[TypedReference, ...]
    unknown_refs: tuple[TypedReference, ...]
    blocked_refs: tuple[TypedReference, ...]
    unmapped_unresolved_refs: tuple[TypedReference, ...]
    materiality: Materiality
    decision: ImpactDecision
    reason_refs: tuple[TypedReference, ...]
    source_digests: tuple[str, ...]
    assessment_policy_version: str
    input_set_digest: str
    assessment_digest: str
    created_seq: int
    created_at: str
    correlation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "impact_assessment_id", _text(self.impact_assessment_id, "impact_assessment_id"))
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        for name in ("quality_version_ref", "campaign_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        for name in (
            "trigger_refs", "r3_requirement_coverage_refs", "r3_change_impact_refs", "affected_refs", "unaffected_refs",
            "unknown_refs", "blocked_refs", "unmapped_unresolved_refs", "reason_refs",
        ):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        object.__setattr__(self, "materiality", _enum(Materiality, self.materiality, "materiality"))
        object.__setattr__(self, "decision", _enum(ImpactDecision, self.decision, "decision"))
        object.__setattr__(self, "source_digests", tuple(sorted(_digest(item, "source_digests[]") for item in self.source_digests)))
        object.__setattr__(self, "assessment_policy_version", _text(self.assessment_policy_version, "assessment_policy_version"))
        object.__setattr__(self, "input_set_digest", _digest(self.input_set_digest, "input_set_digest"))
        object.__setattr__(self, "assessment_digest", _digest(self.assessment_digest, "assessment_digest"))
        object.__setattr__(self, "created_seq", _seq(self.created_seq, "created_seq", 1))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        if self.assessment_digest != canonical_sha256(_assessment_digest_payload(self)):
            raise R42Error("R4_2_DIGEST_MISMATCH", "assessment_digest does not cover immutable assessment semantics")

    def to_dict(self) -> dict[str, Any]:
        return {**_assessment_digest_payload(self), "assessment_digest": self.assessment_digest, "created_seq": self.created_seq, "created_at": self.created_at, "correlation_id": self.correlation_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ImpactAssessment":
        required = {
            "impact_assessment_id", "stream_owner_mission_id", "quality_version_ref", "campaign_ref", "trigger_refs",
            "r3_requirement_coverage_refs", "r3_change_impact_refs", "affected_refs", "unaffected_refs", "unknown_refs",
            "blocked_refs", "unmapped_unresolved_refs", "materiality", "decision", "reason_refs", "source_digests",
            "assessment_policy_version", "input_set_digest", "assessment_digest", "created_seq", "created_at", "correlation_id",
        }
        if set(value) != required:
            raise R42Error("R4_2_SCHEMA_INVALID", "ImpactAssessment contains unknown or missing fields")
        return cls(
            impact_assessment_id=value["impact_assessment_id"], stream_owner_mission_id=value["stream_owner_mission_id"],
            quality_version_ref=_ref(value["quality_version_ref"], "quality_version_ref"), campaign_ref=_ref(value["campaign_ref"], "campaign_ref"),
            trigger_refs=_refs(value["trigger_refs"], "trigger_refs"), r3_requirement_coverage_refs=_refs(value["r3_requirement_coverage_refs"], "r3_requirement_coverage_refs"),
            r3_change_impact_refs=_refs(value["r3_change_impact_refs"], "r3_change_impact_refs"), affected_refs=_refs(value["affected_refs"], "affected_refs"),
            unaffected_refs=_refs(value["unaffected_refs"], "unaffected_refs"), unknown_refs=_refs(value["unknown_refs"], "unknown_refs"),
            blocked_refs=_refs(value["blocked_refs"], "blocked_refs"), unmapped_unresolved_refs=_refs(value["unmapped_unresolved_refs"], "unmapped_unresolved_refs"),
            materiality=value["materiality"], decision=value["decision"], reason_refs=_refs(value["reason_refs"], "reason_refs"),
            source_digests=tuple(value["source_digests"]), assessment_policy_version=value["assessment_policy_version"],
            input_set_digest=value["input_set_digest"], assessment_digest=value["assessment_digest"], created_seq=value["created_seq"],
            created_at=value["created_at"], correlation_id=value["correlation_id"],
        )


def _link_digest_payload(value: "SelectionRevisionLink") -> dict[str, Any]:
    return {
        "selection_link_id": value.selection_link_id,
        "impact_assessment_ref": value.impact_assessment_ref.to_dict(),
        "campaign_ref": value.campaign_ref.to_dict(),
        "r4_1_selection_revision_ref": value.r4_1_selection_revision_ref.to_dict(),
        "selection_revision_digest": value.selection_revision_digest,
        "correlation_id": value.correlation_id,
    }


@dataclass(frozen=True)
class SelectionRevisionLink:
    selection_link_id: str
    impact_assessment_ref: TypedReference
    campaign_ref: TypedReference
    r4_1_selection_revision_ref: TypedReference
    selection_revision_digest: str
    link_digest: str
    created_seq: int
    created_at: str
    correlation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "selection_link_id", _text(self.selection_link_id, "selection_link_id"))
        for name in ("impact_assessment_ref", "campaign_ref", "r4_1_selection_revision_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        object.__setattr__(self, "selection_revision_digest", _digest(self.selection_revision_digest, "selection_revision_digest"))
        object.__setattr__(self, "link_digest", _digest(self.link_digest, "link_digest"))
        object.__setattr__(self, "created_seq", _seq(self.created_seq, "created_seq", 1))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        if self.link_digest != canonical_sha256(_link_digest_payload(self)):
            raise R42Error("R4_2_DIGEST_MISMATCH", "link_digest does not cover immutable linkage semantics")

    def to_dict(self) -> dict[str, Any]:
        return {**_link_digest_payload(self), "link_digest": self.link_digest, "created_seq": self.created_seq, "created_at": self.created_at}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SelectionRevisionLink":
        required = {"selection_link_id", "impact_assessment_ref", "campaign_ref", "r4_1_selection_revision_ref", "selection_revision_digest", "link_digest", "created_seq", "created_at", "correlation_id"}
        if set(value) != required:
            raise R42Error("R4_2_SCHEMA_INVALID", "SelectionRevisionLink contains unknown or missing fields")
        return cls(
            selection_link_id=value["selection_link_id"], impact_assessment_ref=_ref(value["impact_assessment_ref"], "impact_assessment_ref"),
            campaign_ref=_ref(value["campaign_ref"], "campaign_ref"), r4_1_selection_revision_ref=_ref(value["r4_1_selection_revision_ref"], "r4_1_selection_revision_ref"),
            selection_revision_digest=value["selection_revision_digest"], link_digest=value["link_digest"], created_seq=value["created_seq"], created_at=value["created_at"], correlation_id=value["correlation_id"],
        )


def _intent_digest_payload(value: "PlanRevisionIntent") -> dict[str, Any]:
    return {
        "plan_revision_intent_id": value.plan_revision_intent_id,
        "stream_owner_mission_id": value.stream_owner_mission_id,
        "campaign_ref": value.campaign_ref.to_dict(),
        "campaign_selection_revision_ref": value.campaign_selection_revision_ref.to_dict(),
        "impact_assessment_ref": value.impact_assessment_ref.to_dict(),
        "target_r2_mission_ref": value.target_r2_mission_ref.to_dict(),
        "goal_input_ref": value.goal_input_ref.to_dict(),
        "scope_input_ref": value.scope_input_ref.to_dict(),
        "planner_request_id": value.planner_request_id,
        "r2_planner_input_digest": value.r2_planner_input_digest,
        "correlation_id": value.correlation_id,
        "idempotency_key": value.idempotency_key,
        "requested_at": value.requested_at,
        "provenance_refs": [item.to_dict() for item in value.provenance_refs],
    }


@dataclass(frozen=True)
class PlanRevisionIntent:
    plan_revision_intent_id: str
    stream_owner_mission_id: str
    campaign_ref: TypedReference
    campaign_selection_revision_ref: TypedReference
    impact_assessment_ref: TypedReference
    target_r2_mission_ref: TypedReference
    goal_input_ref: TypedReference
    scope_input_ref: TypedReference
    planner_request_id: str
    r4_intent_digest: str
    r2_planner_input_digest: str
    correlation_id: str
    idempotency_key: str
    requested_at: str
    provenance_refs: tuple[TypedReference, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_revision_intent_id", _text(self.plan_revision_intent_id, "plan_revision_intent_id"))
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        for name in ("campaign_ref", "campaign_selection_revision_ref", "impact_assessment_ref", "target_r2_mission_ref", "goal_input_ref", "scope_input_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        if self.target_r2_mission_ref.object_id != self.stream_owner_mission_id:
            raise R42Error(R2_BRIDGE_REJECTED, "target R2 Mission must equal stream_owner_mission_id")
        for name in ("planner_request_id", "correlation_id", "idempotency_key", "requested_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "r4_intent_digest", _digest(self.r4_intent_digest, "r4_intent_digest"))
        object.__setattr__(self, "r2_planner_input_digest", _digest(self.r2_planner_input_digest, "r2_planner_input_digest"))
        object.__setattr__(self, "provenance_refs", _refs(self.provenance_refs, "provenance_refs"))
        if self.r4_intent_digest != canonical_sha256(_intent_digest_payload(self)):
            raise R42Error("R4_2_DIGEST_MISMATCH", "r4_intent_digest does not cover immutable intent semantics")

    def to_dict(self) -> dict[str, Any]:
        return {**_intent_digest_payload(self), "r4_intent_digest": self.r4_intent_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PlanRevisionIntent":
        required = {"plan_revision_intent_id", "stream_owner_mission_id", "campaign_ref", "campaign_selection_revision_ref", "impact_assessment_ref", "target_r2_mission_ref", "goal_input_ref", "scope_input_ref", "planner_request_id", "r4_intent_digest", "r2_planner_input_digest", "correlation_id", "idempotency_key", "requested_at", "provenance_refs"}
        if set(value) != required:
            raise R42Error("R4_2_SCHEMA_INVALID", "PlanRevisionIntent contains unknown or missing fields")
        return cls(
            plan_revision_intent_id=value["plan_revision_intent_id"], stream_owner_mission_id=value["stream_owner_mission_id"], campaign_ref=_ref(value["campaign_ref"], "campaign_ref"),
            campaign_selection_revision_ref=_ref(value["campaign_selection_revision_ref"], "campaign_selection_revision_ref"), impact_assessment_ref=_ref(value["impact_assessment_ref"], "impact_assessment_ref"), target_r2_mission_ref=_ref(value["target_r2_mission_ref"], "target_r2_mission_ref"), goal_input_ref=_ref(value["goal_input_ref"], "goal_input_ref"), scope_input_ref=_ref(value["scope_input_ref"], "scope_input_ref"), planner_request_id=value["planner_request_id"], r4_intent_digest=value["r4_intent_digest"], r2_planner_input_digest=value["r2_planner_input_digest"], correlation_id=value["correlation_id"], idempotency_key=value["idempotency_key"], requested_at=value["requested_at"], provenance_refs=_refs(value["provenance_refs"], "provenance_refs"),
        )


def _receipt_payload(value: "PlanRevisionBridgeReceipt") -> dict[str, Any]:
    return {
        "bridge_receipt_id": value.bridge_receipt_id,
        "stream_owner_mission_id": value.stream_owner_mission_id,
        "campaign_ref": value.campaign_ref.to_dict(),
        "impact_assessment_ref": value.impact_assessment_ref.to_dict(),
        "selection_revision_ref": value.selection_revision_ref.to_dict(),
        "plan_revision_intent_ref": value.plan_revision_intent_ref.to_dict(),
        "planner_request_id": value.planner_request_id,
        "r2_planner_input_digest": value.r2_planner_input_digest,
        "r2_outcome": value.r2_outcome,
        "r2_plan_ref": value.r2_plan_ref.to_dict() if value.r2_plan_ref else None,
        "r2_revision_ref": value.r2_revision_ref.to_dict() if value.r2_revision_ref else None,
        "r2_content_hash": value.r2_content_hash,
        "r2_result_digest": value.r2_result_digest,
        "bridge_status": value.bridge_status.value,
        "correlation_id": value.correlation_id,
    }


@dataclass(frozen=True)
class PlanRevisionBridgeReceipt:
    bridge_receipt_id: str
    stream_owner_mission_id: str
    campaign_ref: TypedReference
    impact_assessment_ref: TypedReference
    selection_revision_ref: TypedReference
    plan_revision_intent_ref: TypedReference
    planner_request_id: str
    r2_planner_input_digest: str
    r2_outcome: str
    r2_plan_ref: TypedReference | None
    r2_revision_ref: TypedReference | None
    r2_content_hash: str | None
    r2_result_digest: str
    bridge_status: BridgeStatus
    correlation_id: str
    created_seq: int
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "bridge_receipt_id", _text(self.bridge_receipt_id, "bridge_receipt_id"))
        object.__setattr__(self, "stream_owner_mission_id", _text(self.stream_owner_mission_id, "stream_owner_mission_id"))
        for name in ("campaign_ref", "impact_assessment_ref", "selection_revision_ref", "plan_revision_intent_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        object.__setattr__(self, "planner_request_id", _text(self.planner_request_id, "planner_request_id"))
        object.__setattr__(self, "r2_planner_input_digest", _digest(self.r2_planner_input_digest, "r2_planner_input_digest"))
        object.__setattr__(self, "r2_outcome", _text(self.r2_outcome, "r2_outcome"))
        object.__setattr__(self, "r2_plan_ref", _optional_ref(self.r2_plan_ref, "r2_plan_ref"))
        object.__setattr__(self, "r2_revision_ref", _optional_ref(self.r2_revision_ref, "r2_revision_ref"))
        if self.r2_content_hash is not None:
            object.__setattr__(self, "r2_content_hash", _digest(self.r2_content_hash, "r2_content_hash"))
        object.__setattr__(self, "r2_result_digest", _digest(self.r2_result_digest, "r2_result_digest"))
        object.__setattr__(self, "bridge_status", _enum(BridgeStatus, self.bridge_status, "bridge_status"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "created_seq", _seq(self.created_seq, "created_seq", 1))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))

    def to_dict(self) -> dict[str, Any]:
        return {**_receipt_payload(self), "created_seq": self.created_seq, "created_at": self.created_at}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PlanRevisionBridgeReceipt":
        required = {"bridge_receipt_id", "stream_owner_mission_id", "campaign_ref", "impact_assessment_ref", "selection_revision_ref", "plan_revision_intent_ref", "planner_request_id", "r2_planner_input_digest", "r2_outcome", "r2_plan_ref", "r2_revision_ref", "r2_content_hash", "r2_result_digest", "bridge_status", "correlation_id", "created_seq", "created_at"}
        if set(value) != required:
            raise R42Error("R4_2_SCHEMA_INVALID", "PlanRevisionBridgeReceipt contains unknown or missing fields")
        return cls(
            bridge_receipt_id=value["bridge_receipt_id"], stream_owner_mission_id=value["stream_owner_mission_id"], campaign_ref=_ref(value["campaign_ref"], "campaign_ref"), impact_assessment_ref=_ref(value["impact_assessment_ref"], "impact_assessment_ref"), selection_revision_ref=_ref(value["selection_revision_ref"], "selection_revision_ref"), plan_revision_intent_ref=_ref(value["plan_revision_intent_ref"], "plan_revision_intent_ref"), planner_request_id=value["planner_request_id"], r2_planner_input_digest=value["r2_planner_input_digest"], r2_outcome=value["r2_outcome"], r2_plan_ref=_optional_ref(value["r2_plan_ref"], "r2_plan_ref"), r2_revision_ref=_optional_ref(value["r2_revision_ref"], "r2_revision_ref"), r2_content_hash=value["r2_content_hash"], r2_result_digest=value["r2_result_digest"], bridge_status=value["bridge_status"], correlation_id=value["correlation_id"], created_seq=value["created_seq"], created_at=value["created_at"],
        )


@dataclass(frozen=True)
class R3ReferenceObservation:
    """Transient classification metadata around an exact R3 reference."""

    reference: TypedReference
    semantic: str
    resolution: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reference", _ref(self.reference, "reference"))
        object.__setattr__(self, "semantic", _text(self.semantic, "semantic").upper())
        if self.resolution is not None:
            object.__setattr__(self, "resolution", _text(self.resolution, "resolution").upper())


def _observation(value: Any, default_semantic: str) -> R3ReferenceObservation:
    if isinstance(value, R3ReferenceObservation):
        return value
    if isinstance(value, TypedReference):
        text = value.ref_type.upper()
        semantic = next((item for item in ("OVERLAP", "REQUIREMENT_ONLY", "CHANGE_ONLY", "REQUIREMENT_CODE_GAP") if item in text), default_semantic)
        resolution = next((item for item in ("RESOLVED", "PARTIAL", "UNMAPPED") if item in text), None)
        return R3ReferenceObservation(value, semantic, resolution)
    if isinstance(value, Mapping):
        raw = dict(value)
        reference = raw.get("reference", raw.get("ref", raw.get("typed_reference", raw)))
        if isinstance(reference, Mapping) and set(reference) >= {"ref_type", "object_id", "object_version", "revision", "source_digest", "source_cursor", "origin", "observed_at", "freshness", "availability", "field_validation_state", "correlation_id"}:
            return R3ReferenceObservation(_ref(reference, "r3.reference"), raw.get("semantic", raw.get("kind", default_semantic)), raw.get("resolution", raw.get("impact_resolution")))
    raise R42Error(IMPACT_INPUT_INVALID, "R3 input must preserve an exact TypedReference")


def build_impact_assessment(
    *,
    stream_owner_mission_id: str,
    quality_version_ref: TypedReference,
    campaign_ref: TypedReference,
    trigger_refs: Iterable[TypedReference],
    r3_requirement_coverage_refs: Iterable[Any] = (),
    r3_change_impact_refs: Iterable[Any] = (),
    coalescing_key: str,
    source_digests: Iterable[str] = (),
    assessment_policy_version: str = ASSESSMENT_POLICY_VERSION,
    created_at: str,
    correlation_id: str,
) -> ImpactAssessment:
    req_obs = tuple(_observation(item, "REQUIREMENT_ONLY") for item in r3_requirement_coverage_refs)
    change_obs = tuple(_observation(item, "CHANGE_ONLY") for item in r3_change_impact_refs)
    observations = req_obs + change_obs
    exact_r3_refs = canonical_references(item.reference for item in observations)
    identity_groups: dict[tuple[str, str, int, str | int | None], set[str]] = {}
    for item in exact_r3_refs:
        identity_groups.setdefault((item.ref_type, item.object_id, item.revision, item.source_cursor), set()).add(item.source_digest)
    digest_conflict = any(len(values) > 1 for values in identity_groups.values())
    trigger_values = _refs(tuple(trigger_refs), "trigger_refs")
    source_values = tuple(sorted(set(_digest(item, "source_digests[]") for item in source_digests) | {item.source_digest for item in exact_r3_refs}))
    blocked: list[TypedReference] = []
    unknown: list[TypedReference] = []
    affected: list[TypedReference] = []
    unaffected: list[TypedReference] = []
    unmapped: list[TypedReference] = []
    reasons: list[TypedReference] = []
    if digest_conflict:
        blocked.extend(exact_r3_refs)
    for item in observations:
        ref = item.reference
        semantic = item.semantic.upper()
        resolution = (item.resolution or "").upper()
        if ref.availability is not Availability.AVAILABLE:
            blocked.append(ref)
            continue
        if ref.freshness is Freshness.STALE:
            unknown.append(ref)
            continue
        if semantic in {"OVERLAP", "CHANGE_ONLY"} and resolution == "RESOLVED":
            affected.append(ref)
        elif semantic in {"OVERLAP", "CHANGE_ONLY"} and resolution == "PARTIAL":
            unknown.append(ref)
        elif semantic in {"OVERLAP", "CHANGE_ONLY"} and resolution == "UNMAPPED":
            unmapped.append(ref)
        elif semantic == "REQUIREMENT_CODE_GAP":
            unmapped.append(ref)
        elif semantic == "REQUIREMENT_ONLY":
            unaffected.append(ref)
        else:
            unknown.append(ref)
    blocked = list(canonical_references(blocked))
    unknown = list(canonical_references(unknown))
    affected = list(canonical_references(affected))
    unaffected = list(canonical_references(unaffected))
    unmapped = list(canonical_references(unmapped))
    if not observations:
        decision, materiality = ImpactDecision.BLOCKED, Materiality.UNKNOWN
    elif blocked:
        decision, materiality = ImpactDecision.BLOCKED, Materiality.UNKNOWN
        reasons.extend(blocked)
    elif unknown or unmapped:
        decision, materiality = ImpactDecision.INCONCLUSIVE, Materiality.UNKNOWN
        reasons.extend(unknown + unmapped)
    elif affected:
        decision, materiality = ImpactDecision.SELECTION_REVISION_REQUIRED, Materiality.MATERIAL
        reasons.extend(affected)
    else:
        decision, materiality = ImpactDecision.NO_MATERIAL_IMPACT, Materiality.NONE
        reasons.extend(unaffected)
    input_set_digest = canonical_sha256({
        "trigger_refs": [item.to_dict() for item in trigger_values],
        "r3_refs": [item.to_dict() for item in exact_r3_refs],
        "source_digests": list(source_values),
    })
    assessment_id = assessment_id_for(coalescing_key, input_set_digest, exact_r3_refs, assessment_policy_version)
    values = dict(
        impact_assessment_id=assessment_id, stream_owner_mission_id=stream_owner_mission_id,
        quality_version_ref=_ref(quality_version_ref, "quality_version_ref"), campaign_ref=_ref(campaign_ref, "campaign_ref"),
        trigger_refs=trigger_values, r3_requirement_coverage_refs=tuple(item.reference for item in req_obs), r3_change_impact_refs=tuple(item.reference for item in change_obs),
        affected_refs=tuple(affected), unaffected_refs=tuple(unaffected), unknown_refs=tuple(unknown), blocked_refs=tuple(blocked), unmapped_unresolved_refs=tuple(unmapped),
        materiality=materiality, decision=decision, reason_refs=tuple(canonical_references(reasons)), source_digests=source_values,
        assessment_policy_version=assessment_policy_version, input_set_digest=input_set_digest, created_seq=1, created_at=created_at, correlation_id=correlation_id,
    )
    provisional = object.__new__(ImpactAssessment)
    for key, item in values.items():
        object.__setattr__(provisional, key, item)
    values["assessment_digest"] = canonical_sha256(_assessment_digest_payload(provisional))
    return ImpactAssessment(**values)


def selection_link_digest(value: Mapping[str, Any] | SelectionRevisionLink) -> str:
    if isinstance(value, SelectionRevisionLink):
        return canonical_sha256(_link_digest_payload(value))
    raw = dict(value)
    return canonical_sha256({key: _export(raw[key]) for key in ("selection_link_id", "impact_assessment_ref", "campaign_ref", "r4_1_selection_revision_ref", "selection_revision_digest", "correlation_id")})


def plan_revision_intent_digest(value: Mapping[str, Any] | PlanRevisionIntent) -> str:
    if isinstance(value, PlanRevisionIntent):
        return canonical_sha256(_intent_digest_payload(value))
    raw = dict(value)
    payload = {key: _export(raw[key]) for key in ("plan_revision_intent_id", "stream_owner_mission_id", "campaign_ref", "campaign_selection_revision_ref", "impact_assessment_ref", "target_r2_mission_ref", "goal_input_ref", "scope_input_ref", "planner_request_id", "r2_planner_input_digest", "correlation_id", "idempotency_key", "requested_at", "provenance_refs")}
    payload["provenance_refs"] = [item.to_dict() for item in canonical_references(_ref(item, "provenance_ref") for item in raw["provenance_refs"])]
    return canonical_sha256(payload)


def bridge_receipt_id_for(assessment_id: str, selection_revision_id: str) -> str:
    return f"r4.2:bridge:{canonical_sha256([assessment_id, selection_revision_id])}"


def command_id_for(command_type: str, entity_id: str) -> str:
    prefixes = {
        R4_2_RECORD_TRIGGER_RECEIPT: "trigger",
        R4_2_RECORD_IMPACT_ASSESSMENT: "impact",
        R4_2_LINK_SELECTION_REVISION: "selection-link",
        R4_2_REQUEST_R2_PLAN_REVISION_BRIDGE: "bridge-request",
        R4_2_RECORD_R2_BRIDGE_RESULT: "bridge-result",
    }
    if command_type not in prefixes:
        raise R42Error("R4_2_COMMAND_INVALID", f"unsupported R4.2 command: {command_type}")
    return f"r4.2:{prefixes[command_type]}:{entity_id}"


def ref_for(ref_type: str, object_id: str, *, digest: str, cursor: str | int | None, observed_at: str, correlation_id: str, origin: str = "r4.2") -> TypedReference:
    return TypedReference(
        ref_type=ref_type, object_id=object_id, object_version="1", revision=1,
        source_digest=_digest(digest, "digest"), source_cursor=cursor, origin=origin, observed_at=observed_at,
        freshness=Freshness.CURRENT, availability=Availability.AVAILABLE if cursor is not None else Availability.UNAVAILABLE,
        field_validation_state=FieldValidationState.PASSED, correlation_id=correlation_id,
    )


@dataclass(frozen=True)
class R42State:
    mission_id: str
    triggers: tuple[ContinuousTestTrigger, ...] = ()
    assessments: tuple[ImpactAssessment, ...] = ()
    selection_links: tuple[SelectionRevisionLink, ...] = ()
    plan_revision_intents: tuple[PlanRevisionIntent, ...] = ()
    bridge_receipts: tuple[PlanRevisionBridgeReceipt, ...] = ()
    trigger_id_index: tuple[tuple[str, int], ...] = ()
    dedupe_index: tuple[tuple[str, str], ...] = ()
    coalescing_index: tuple[tuple[str, str], ...] = ()
    assessment_id_index: tuple[tuple[str, str], ...] = ()
    planner_request_index: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        for name, cls in (("triggers", ContinuousTestTrigger), ("assessments", ImpactAssessment), ("selection_links", SelectionRevisionLink), ("plan_revision_intents", PlanRevisionIntent), ("bridge_receipts", PlanRevisionBridgeReceipt)):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, cls) for item in values):
                raise R42Error("R4_2_SCHEMA_INVALID", f"{name} must contain immutable typed values")
            if name != "selection_links" and any(item.stream_owner_mission_id != self.mission_id for item in values):
                raise R42Error("R4_2_MISSION_INVALID", f"{name} contains a cross-Mission value")
        object.__setattr__(self, "triggers", tuple(sorted(self.triggers, key=lambda item: item.trigger_id)))
        object.__setattr__(self, "assessments", tuple(sorted(self.assessments, key=lambda item: item.impact_assessment_id)))
        object.__setattr__(self, "selection_links", tuple(sorted(self.selection_links, key=lambda item: item.selection_link_id)))
        object.__setattr__(self, "plan_revision_intents", tuple(sorted(self.plan_revision_intents, key=lambda item: item.plan_revision_intent_id)))
        object.__setattr__(self, "bridge_receipts", tuple(sorted(self.bridge_receipts, key=lambda item: item.bridge_receipt_id)))
        ids = {
            "triggers": [item.trigger_id for item in self.triggers], "assessments": [item.impact_assessment_id for item in self.assessments],
            "selection_links": [item.selection_link_id for item in self.selection_links], "plan_revision_intents": [item.plan_revision_intent_id for item in self.plan_revision_intents], "bridge_receipts": [item.bridge_receipt_id for item in self.bridge_receipts],
        }
        if any(len(values) != len(set(values)) for values in ids.values()):
            raise R42Error("R4_2_IDENTITY_CONFLICT", "R4.2 aggregate identities must be unique")
        object.__setattr__(self, "trigger_id_index", tuple((item.trigger_id, index) for index, item in enumerate(self.triggers)))
        object.__setattr__(self, "dedupe_index", tuple(sorted((item.dedupe_key, item.trigger_id) for item in self.triggers)))
        object.__setattr__(self, "coalescing_index", tuple(sorted((item.coalescing_key, item.trigger_id) for item in self.triggers)))
        object.__setattr__(self, "assessment_id_index", tuple((item.impact_assessment_id, index) for index, item in enumerate(self.assessments)))
        object.__setattr__(self, "planner_request_index", tuple(sorted((item.planner_request_id, item.bridge_receipt_id) for item in self.bridge_receipts)))

    def trigger(self, identity: str) -> ContinuousTestTrigger | None:
        return next((item for item in self.triggers if item.trigger_id == identity), None)

    def assessment(self, identity: str) -> ImpactAssessment | None:
        return next((item for item in self.assessments if item.impact_assessment_id == identity), None)

    def selection_link(self, identity: str) -> SelectionRevisionLink | None:
        return next((item for item in self.selection_links if item.selection_link_id == identity), None)

    def intent(self, identity: str) -> PlanRevisionIntent | None:
        return next((item for item in self.plan_revision_intents if item.plan_revision_intent_id == identity), None)

    def bridge_receipt(self, identity: str) -> PlanRevisionBridgeReceipt | None:
        return next((item for item in self.bridge_receipts if item.bridge_receipt_id == identity), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "triggers": [item.to_dict() for item in self.triggers],
            "assessments": [item.to_dict() for item in self.assessments],
            "selection_links": [item.to_dict() for item in self.selection_links],
            "plan_revision_intents": [item.to_dict() for item in self.plan_revision_intents],
            "bridge_receipts": [item.to_dict() for item in self.bridge_receipts],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R42State":
        required = {"mission_id", "triggers", "assessments", "selection_links", "plan_revision_intents", "bridge_receipts"}
        if set(value) != required:
            raise R42Error("R4_2_SCHEMA_INVALID", "R42State contains unknown or missing fields")
        return cls(
            mission_id=value["mission_id"], triggers=tuple(ContinuousTestTrigger.from_dict(item) for item in value.get("triggers") or ()),
            assessments=tuple(ImpactAssessment.from_dict(item) for item in value.get("assessments") or ()), selection_links=tuple(SelectionRevisionLink.from_dict(item) for item in value.get("selection_links") or ()),
            plan_revision_intents=tuple(PlanRevisionIntent.from_dict(item) for item in value.get("plan_revision_intents") or ()), bridge_receipts=tuple(PlanRevisionBridgeReceipt.from_dict(item) for item in value.get("bridge_receipts") or ()),
        )


TRIGGER_INPUT_FIELDS = frozenset(ContinuousTestTrigger.__dataclass_fields__)
ASSESSMENT_INPUT_FIELDS = frozenset(set(ImpactAssessment.__dataclass_fields__) - {"created_seq", "created_at"})
SELECTION_LINK_INPUT_FIELDS = frozenset(set(SelectionRevisionLink.__dataclass_fields__) - {"created_seq", "created_at"})
PLAN_INTENT_INPUT_FIELDS = frozenset(PlanRevisionIntent.__dataclass_fields__)
BRIDGE_RECEIPT_INPUT_FIELDS = frozenset(set(PlanRevisionBridgeReceipt.__dataclass_fields__) - {"created_seq", "created_at"})


__all__ = [name for name in globals() if not name.startswith("_")]
