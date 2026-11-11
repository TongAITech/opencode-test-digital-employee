"""Recover a formal creation receipt from one strict, pinned R1 snapshot."""

from collections import Counter
import hashlib
import json
from typing import NamedTuple

from .formal_mission_event import (
    FORMAL_MISSION_EVENT_TYPE, FormalMissionCreationKey, FormalMissionEvent,
    parse_formal_mission_event,
)
from .r1_snapshot_events import iter_r1_snapshot_records


class FormalMissionReceiptError(ValueError):
    pass


class FormalMissionReceipt(NamedTuple):
    event: FormalMissionEvent
    canonical_bytes: bytes
    receipt_hash: str


def _unique_identities(event):
    return (
        ("creation_key", event.creation_key),
        ("mission", event.scope.mission_id),
        ("release", event.mapping.runtime_release_id),
        ("runtime_batch", event.mapping.runtime_release_batch_id),
        ("operation", event.mapping.creation_operation_ref),
        ("mapping", event.mapping.mapping_ref),
        ("binding", event.binding_ref),
        ("receipt", event.receipt_ref),
    )


def lookup_formal_mission_receipt(snapshot, creation_key):
    """Return the original receipt, or None when this snapshot has no such event.

    The caller supplies the key from the authorized lookup context and pins
    the corresponding physical ledger bytes. This function only verifies
    receipt source identities and encoding. It performs no authorization,
    storage, projection, or initialization.
    """
    if (type(creation_key) is not FormalMissionCreationKey or
            any(type(value) is not str or not value for value in creation_key)):
        raise FormalMissionReceiptError("FORMAL_MISSION_CREATION_KEY_INVALID")

    event_ids = Counter()
    sequences = Counter()
    legacy_missions = set()
    formal_events = []
    seen = set()
    matched = None
    for record in iter_r1_snapshot_records(snapshot):
        raw = record.event
        event_id = raw.get("event_id")
        seq = raw.get("seq")
        if type(event_id) is str:
            event_ids[event_id] += 1
        if isinstance(seq, int):
            sequences[seq] += 1
        kind = raw.get("event_type")
        if type(kind) is not str or not kind:
            raise FormalMissionReceiptError("FORMAL_MISSION_SOURCE_EVENT_INVALID")
        if kind == "RC7_MISSION_UPSERTED":
            payload = raw.get("payload")
            mission_id = payload.get("mission_id") if type(payload) is dict else None
            if type(mission_id) is str:
                legacy_missions.add(mission_id.strip())
        if kind != FORMAL_MISSION_EVENT_TYPE:
            continue

        event = parse_formal_mission_event(record.raw_line)
        if event.creation_key.formal_authority_ref != creation_key.formal_authority_ref:
            raise FormalMissionReceiptError("FORMAL_MISSION_AUTHORITY_CONFLICT")
        identities = _unique_identities(event)
        if any(identity in seen for identity in identities):
            raise FormalMissionReceiptError("FORMAL_MISSION_SOURCE_CONFLICT")
        seen.update(identities)
        formal_events.append(event)
        if event.creation_key == creation_key:
            matched = event

    for event in formal_events:
        if (event_ids[event.event_id] != 1 or sequences[event.seq] != 1 or
                event.scope.mission_id in legacy_missions):
            raise FormalMissionReceiptError("FORMAL_MISSION_SOURCE_CONFLICT")
    if matched is None:
        return None
    payload = {
        "schema_version": 1,
        "creation_key_scope": matched.creation_key._asdict(),
        "request_digest": matched.request_digest,
        "creation_operation_ref": matched.mapping.creation_operation_ref,
        "runtime_batch_mapping": matched.mapping._asdict(),
        "binding_ref": matched.binding_ref,
        "event_ref": matched.event_id,
        "event_sha256": matched.event_sha256,
        "receipt_ref": matched.receipt_ref,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(b"dsh.mission-create-receipt.v1\n" + encoded).hexdigest()
    return FormalMissionReceipt(matched, encoded, digest)
