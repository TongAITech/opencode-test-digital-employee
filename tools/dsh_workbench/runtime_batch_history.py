"""Check a mapped RC7.2 batch against decoded events from one R1 snapshot."""

from typing import NamedTuple

from rc6_runtime.contracts import DomainValidationError
from rc7_runtime.rc72_truth import validate_release_batch

from .runtime_batch_mapping import RuntimeBatchMapping


class RuntimeBatchHistoryError(ValueError):
    pass


class RuntimeBatchHistory(NamedTuple):
    initial_event_id: str
    latest_event_id: str
    latest_version: int


def verify_runtime_batch_history(events, mapping):
    """Return batch history or None for a missing batch in this snapshot.

    The caller must pin the original ledger bytes, decode strictly, and verify
    its authority and the mapping's creation event independently.
    """
    if type(mapping) is not RuntimeBatchMapping:
        raise RuntimeBatchHistoryError("RUNTIME_BATCH_MAPPING_REQUIRED")
    expected = (mapping.runtime_release_batch_id, mapping.runtime_release_id, mapping.mission_id)
    if any(type(value) is not str or not value for value in expected):
        raise RuntimeBatchHistoryError("RUNTIME_BATCH_MAPPING_REQUIRED")
    history = None
    seen = set()
    latest_seq = 0
    for event in events:
        if type(event) is not dict or any(type(key) is not str for key in event):
            raise RuntimeBatchHistoryError("RUNTIME_BATCH_EVENT_INVALID")
        kind = event.get("event_type")
        if type(kind) is not str:
            raise RuntimeBatchHistoryError("RUNTIME_BATCH_EVENT_INVALID")
        if kind != "RC72_RELEASE_BATCH_UPSERTED":
            continue
        payload = event.get("payload")
        if type(payload) is not dict or any(type(key) is not str for key in payload):
            raise RuntimeBatchHistoryError("RUNTIME_BATCH_EVENT_INVALID")
        identity = tuple(payload.get(key) for key in ("release_batch_id", "release_id", "mission_id"))
        entity_id = event.get("entity_id")
        if any(type(value) is not str or not value for value in (*identity, entity_id)):
            raise RuntimeBatchHistoryError("RUNTIME_BATCH_EVENT_INVALID")
        if entity_id != identity[0]:
            raise RuntimeBatchHistoryError("RUNTIME_BATCH_EVENT_INVALID")
        if identity[0] != expected[0] and identity[2] != expected[2]:
            continue
        if identity != expected:
            raise RuntimeBatchHistoryError("RUNTIME_BATCH_HISTORY_CONFLICT")

        event_id = event.get("event_id")
        version = payload.get("artifact_version")
        seq = event.get("seq")
        entity_version = event.get("entity_version")
        if (event.get("entity_type") != "rc72_release_batch" or
                any(field in payload for field in ("intents", "conditions", "cases")) or
                type(event_id) is not str or not event_id or event_id in seen or
                type(seq) is not int or seq <= latest_seq or
                type(version) is not int or type(entity_version) is not int or version != entity_version or
                (history is None and version != 1) or
                (history is not None and version <= history.latest_version)):
            raise RuntimeBatchHistoryError("RUNTIME_BATCH_EVENT_INVALID")
        try:
            validate_release_batch(payload)
        except DomainValidationError as error:
            raise RuntimeBatchHistoryError("RUNTIME_BATCH_EVENT_INVALID") from error
        seen.add(event_id)
        latest_seq = seq
        history = RuntimeBatchHistory(history.initial_event_id if history else event_id, event_id, version)
    return history
