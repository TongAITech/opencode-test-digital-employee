from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from aitest_runtime.r4_1.contracts import TypedReference

from .contracts import FixSourceObservation, ObservationKind
from .errors import R43Error


_FORBIDDEN = frozenset(
    {
        "raw", "raw_payload", "raw_content", "payload", "body", "content", "diff", "patch",
        "transcript", "secret", "token", "cookie", "password", "credential", "access_token",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _reject_raw(value: Any, path: str = "observation") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _FORBIDDEN:
                raise R43Error("R4_3_SOURCE_RAW_FORBIDDEN", f"{path} contains forbidden source-content field: {key}")
            _reject_raw(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_raw(item, f"{path}[{index}]")


def _ref(value: Any, name: str) -> TypedReference:
    if isinstance(value, Mapping):
        value = TypedReference.from_dict(value)
    if not isinstance(value, TypedReference):
        raise R43Error("R4_3_SOURCE_REFERENCE_INVALID", f"{name} must be a TypedReference")
    return value


def _refs(value: Any, name: str) -> tuple[TypedReference, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise R43Error("R4_3_SOURCE_REFERENCE_INVALID", f"{name} must be an array of TypedReference values")
    return tuple(_ref(item, f"{name}[]") for item in value)


def normalize_source_observation(value: FixSourceObservation | Mapping[str, Any]) -> FixSourceObservation:
    """Normalize only the source-neutral bounded observation shape."""
    if isinstance(value, FixSourceObservation):
        return value
    if not isinstance(value, Mapping):
        raise R43Error("R4_3_SOURCE_INVALID", "source observation must be a typed observation object")
    _reject_raw(value)
    allowed = {
        "observation_kind", "primary_ref", "related_refs", "scope_refs", "provenance_refs",
        "received_at", "correlation_id", "adapter_version",
    }
    if set(value) != allowed:
        unknown = sorted(set(value) - allowed)
        missing = sorted(allowed - set(value))
        raise R43Error("R4_3_SOURCE_INVALID", f"source observation fields mismatch; missing={missing}, unknown={unknown}")
    return FixSourceObservation(
        observation_kind=value["observation_kind"], primary_ref=_ref(value["primary_ref"], "primary_ref"),
        related_refs=_refs(value.get("related_refs"), "related_refs"), scope_refs=_refs(value.get("scope_refs"), "scope_refs"),
        provenance_refs=_refs(value.get("provenance_refs"), "provenance_refs"), received_at=value["received_at"],
        correlation_id=value["correlation_id"], adapter_version=value["adapter_version"],
    )


def adapt_typed_reference(
    value: TypedReference | Mapping[str, Any],
    *,
    observation_kind: ObservationKind | str = ObservationKind.SOURCE_REVISION,
    related_refs: tuple[TypedReference, ...] = (),
    scope_refs: tuple[TypedReference, ...] = (),
    provenance_refs: tuple[TypedReference, ...] = (),
    received_at: str | None = None,
    correlation_id: str = "r4.3:typed-reference-adapter",
    adapter_version: str = "r4.3.typed-reference.v1",
) -> FixSourceObservation:
    ref = _ref(value, "primary_ref")
    return FixSourceObservation(
        observation_kind=observation_kind, primary_ref=ref, related_refs=related_refs, scope_refs=scope_refs,
        provenance_refs=provenance_refs, received_at=received_at or _now(), correlation_id=correlation_id,
        adapter_version=adapter_version,
    )


def normalize_manual_source(
    value: TypedReference | Mapping[str, Any],
    *,
    related_refs: tuple[TypedReference, ...] = (),
    scope_refs: tuple[TypedReference, ...] = (),
    provenance_refs: tuple[TypedReference, ...] = (),
    received_at: str | None = None,
    correlation_id: str = "r4.3:manual-adapter",
    adapter_version: str = "r4.3.manual.v1",
) -> FixSourceObservation:
    if isinstance(value, Mapping) and "primary_ref" in value:
        raw = dict(value)
        raw.setdefault("observation_kind", ObservationKind.MANUAL_ATTESTATION.value)
        raw.setdefault("related_refs", list(related_refs))
        raw.setdefault("scope_refs", list(scope_refs))
        raw.setdefault("provenance_refs", list(provenance_refs))
        raw.setdefault("received_at", received_at or _now())
        raw.setdefault("correlation_id", correlation_id)
        raw.setdefault("adapter_version", adapter_version)
        return normalize_source_observation(raw)
    return adapt_typed_reference(
        value, observation_kind=ObservationKind.MANUAL_ATTESTATION, related_refs=related_refs,
        scope_refs=scope_refs, provenance_refs=provenance_refs, received_at=received_at,
        correlation_id=correlation_id, adapter_version=adapter_version,
    )


def normalize_legacy_source(value: TypedReference | Mapping[str, Any], **kwargs: Any) -> FixSourceObservation:
    return adapt_typed_reference(value, observation_kind=ObservationKind.LEGACY_ADAPTER, **kwargs)


__all__ = [
    "FixSourceObservation", "ObservationKind", "adapt_typed_reference", "normalize_source_observation",
    "normalize_manual_source", "normalize_legacy_source",
]
