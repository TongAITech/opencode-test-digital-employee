from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.r4_1.contracts import TypedReference

from .contracts import (
    ContinuousTestTrigger,
    TriggerKind,
    build_trigger,
)
from .errors import INVALID_TRIGGER, R42Error


@dataclass(frozen=True)
class SourceObservation:
    """Transient, source-neutral observation used before durable normalization."""

    reference: TypedReference
    scope_refs: tuple[TypedReference, ...] = ()
    provenance_refs: tuple[TypedReference, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.reference, TypedReference):
            raise R42Error(INVALID_TRIGGER, "SourceObservation.reference must be a TypedReference")
        if not isinstance(self.scope_refs, tuple) or any(not isinstance(item, TypedReference) for item in self.scope_refs):
            raise R42Error(INVALID_TRIGGER, "SourceObservation.scope_refs must be an immutable TypedReference tuple")
        if not isinstance(self.provenance_refs, tuple) or any(not isinstance(item, TypedReference) for item in self.provenance_refs):
            raise R42Error(INVALID_TRIGGER, "SourceObservation.provenance_refs must be an immutable TypedReference tuple")

    @classmethod
    def from_typed_reference(
        cls,
        reference: TypedReference | Mapping[str, Any],
        *,
        scope_refs: tuple[TypedReference, ...] = (),
        provenance_refs: tuple[TypedReference, ...] = (),
    ) -> "SourceObservation":
        if isinstance(reference, Mapping):
            reference = TypedReference.from_dict(reference)
        return cls(reference, tuple(scope_refs), tuple(provenance_refs))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceObservation":
        raw = dict(value)
        if any(key in raw for key in ("payload", "raw", "raw_payload", "source_payload")):
            raise R42Error(INVALID_TRIGGER, "raw source payload is forbidden at the R4.2 normalization boundary")
        reference = raw.get("reference", raw.get("source_ref"))
        if reference is None:
            reference = raw
        if not isinstance(reference, (TypedReference, Mapping)):
            raise R42Error(INVALID_TRIGGER, "SourceObservation requires a typed reference")
        return cls.from_typed_reference(
            reference,
            scope_refs=tuple(TypedReference.from_dict(item) if isinstance(item, Mapping) else item for item in raw.get("scope_refs") or ()),
            provenance_refs=tuple(TypedReference.from_dict(item) if isinstance(item, Mapping) else item for item in raw.get("provenance_refs") or ()),
        )


def adapt_typed_reference(
    reference: TypedReference | Mapping[str, Any],
    *,
    scope_refs: tuple[TypedReference, ...] = (),
    provenance_refs: tuple[TypedReference, ...] = (),
) -> SourceObservation:
    return SourceObservation.from_typed_reference(reference, scope_refs=scope_refs, provenance_refs=provenance_refs)


def normalize_source_observation(
    observation: SourceObservation | TypedReference | Mapping[str, Any],
    *,
    stream_owner_mission_id: str,
    quality_version_ref: TypedReference | Mapping[str, Any],
    campaign_ref: TypedReference | Mapping[str, Any],
    trigger_kind: TriggerKind | str,
    received_at: str,
    correlation_id: str,
    current_selection_ref: TypedReference | Mapping[str, Any] | None = None,
    open_epoch: str | int = 0,
) -> ContinuousTestTrigger:
    if isinstance(observation, SourceObservation):
        value = observation
    elif isinstance(observation, TypedReference):
        value = SourceObservation(observation)
    elif isinstance(observation, Mapping):
        value = SourceObservation.from_mapping(observation)
    else:
        raise R42Error(INVALID_TRIGGER, "unsupported SourceObservation value")
    return build_trigger(
        stream_owner_mission_id=stream_owner_mission_id,
        quality_version_ref=quality_version_ref,
        campaign_ref=campaign_ref,
        trigger_kind=trigger_kind,
        source_ref=value.reference,
        scope_refs=value.scope_refs,
        received_at=received_at,
        correlation_id=correlation_id,
        provenance_refs=value.provenance_refs,
        current_selection_ref=current_selection_ref,
        open_epoch=open_epoch,
    )


def normalize_manual_source(
    *,
    source_ref: TypedReference | Mapping[str, Any],
    stream_owner_mission_id: str,
    quality_version_ref: TypedReference | Mapping[str, Any],
    campaign_ref: TypedReference | Mapping[str, Any],
    trigger_kind: TriggerKind | str = TriggerKind.MANUAL_REASSESSMENT,
    scope_refs: tuple[TypedReference, ...] = (),
    provenance_refs: tuple[TypedReference, ...] = (),
    received_at: str,
    correlation_id: str,
    current_selection_ref: TypedReference | Mapping[str, Any] | None = None,
    open_epoch: str | int = 0,
) -> ContinuousTestTrigger:
    """Controlled explicit manual normalization; no provider-specific adapter."""
    return normalize_source_observation(
        SourceObservation.from_typed_reference(source_ref, scope_refs=tuple(scope_refs), provenance_refs=tuple(provenance_refs)),
        stream_owner_mission_id=stream_owner_mission_id,
        quality_version_ref=quality_version_ref,
        campaign_ref=campaign_ref,
        trigger_kind=trigger_kind,
        received_at=received_at,
        correlation_id=correlation_id,
        current_selection_ref=current_selection_ref,
        open_epoch=open_epoch,
    )


__all__ = ["SourceObservation", "adapt_typed_reference", "normalize_manual_source", "normalize_source_observation"]

