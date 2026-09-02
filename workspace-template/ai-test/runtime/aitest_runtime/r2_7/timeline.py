"""Historical timeline and current-observation boundaries for R2.7."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import (
    CANONICAL_EVENT,
    CURRENT_OBSERVATION,
    DERIVED_EVENT,
    R2_7_ACTION_REQUEST_INVALID,
    R27Error,
)


def _plain(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _non_empty_sequence(value: Any, name: str) -> list[Any]:
    if not isinstance(value, (list, tuple)) or not value:
        raise R27Error(R2_7_ACTION_REQUEST_INVALID, f"{name} must be a non-empty array")
    return [_plain(item) for item in value]


def canonical_timeline_item(event: Any) -> dict[str, Any]:
    """Convert one EventEnvelope into a canonical historical item."""

    raw = _plain(event)
    if not isinstance(raw, Mapping):
        raise R27Error(R2_7_ACTION_REQUEST_INVALID, "canonical timeline item must be an object")
    item = dict(raw)
    if item.get("kind") == CURRENT_OBSERVATION:
        raise R27Error(R2_7_ACTION_REQUEST_INVALID, "current observations cannot enter historical_timeline")
    item["kind"] = CANONICAL_EVENT
    if not isinstance(item.get("seq"), int) or isinstance(item.get("seq"), bool) or item["seq"] < 0:
        raise R27Error(R2_7_ACTION_REQUEST_INVALID, "canonical timeline item requires a non-negative seq")
    return item


def derived_timeline_item(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the provenance required for a derived historical item."""

    if not isinstance(value, Mapping):
        raise R27Error(R2_7_ACTION_REQUEST_INVALID, "derived timeline item must be an object")
    item = dict(_plain(value))
    if item.get("kind", DERIVED_EVENT) != DERIVED_EVENT:
        raise R27Error(R2_7_ACTION_REQUEST_INVALID, "historical derived item kind must be DERIVED_EVENT")
    item["kind"] = DERIVED_EVENT
    item["source_refs"] = _non_empty_sequence(item.get("source_refs"), "derived source_refs")
    item["source_seqs"] = _non_empty_sequence(item.get("source_seqs"), "derived source_seqs")
    if any(isinstance(seq, bool) or not isinstance(seq, int) or seq < 0 for seq in item["source_seqs"]):
        raise R27Error(R2_7_ACTION_REQUEST_INVALID, "derived source_seqs must contain non-negative integers")
    derivation = item.get("derivation")
    if not isinstance(derivation, str) or not derivation.strip():
        raise R27Error(R2_7_ACTION_REQUEST_INVALID, "derived item requires derivation")
    version = item.get("version")
    if not isinstance(version, (str, int)) or isinstance(version, bool) or not str(version).strip():
        raise R27Error(R2_7_ACTION_REQUEST_INVALID, "derived item requires version")
    item.setdefault("seq", max(item["source_seqs"]))
    return item


def build_historical_timeline(
    events: Iterable[Any],
    derived_items: Iterable[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], ...]:
    """Build only canonical/derived historical items in sequence order."""

    values = [canonical_timeline_item(event) for event in events]
    values.extend(derived_timeline_item(item) for item in derived_items)
    values.sort(key=lambda item: (int(item.get("seq", 0)), item.get("kind", ""), str(item.get("event_id", ""))))
    return tuple(values)


def build_current_observations(values: Iterable[Any] = ()) -> tuple[dict[str, Any], ...]:
    """Normalize non-durable observations without placing them in history."""

    result: list[dict[str, Any]] = []
    for value in values:
        raw = _plain(value)
        if not isinstance(raw, Mapping):
            raise R27Error(R2_7_ACTION_REQUEST_INVALID, "current observation must be an object")
        item = dict(raw)
        if item.get("kind") in {CANONICAL_EVENT, DERIVED_EVENT}:
            raise R27Error(R2_7_ACTION_REQUEST_INVALID, "historical item cannot be relabeled as current observation")
        item["kind"] = CURRENT_OBSERVATION
        result.append(item)
    return tuple(result)


class RuntimeOperationsTimeline:
    """Small stateless facade kept separate from the query aggregator."""

    build_historical_timeline = staticmethod(build_historical_timeline)
    build_current_observations = staticmethod(build_current_observations)


TimelineBuilder = RuntimeOperationsTimeline


__all__ = [
    "RuntimeOperationsTimeline",
    "TimelineBuilder",
    "build_current_observations",
    "build_historical_timeline",
    "canonical_timeline_item",
    "derived_timeline_item",
]
