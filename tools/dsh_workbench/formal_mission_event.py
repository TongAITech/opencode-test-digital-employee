"""Detached validation for a single formal Scope Mission creation event."""

import hashlib
import json
from typing import NamedTuple

from .mission_create_codec import MissionCreateWireError, encode_mission_create_request
from .mission_scope_binding_codec import BindingStructureError, ScopeIdentity, parse_scope
from .r1_snapshot_events import R1SnapshotDecodeError, iter_r1_snapshot_records
from .runtime_batch_mapping import RuntimeBatchMapping, parse_runtime_batch_mapping


FORMAL_MISSION_EVENT_TYPE = "RC7_SCOPED_MISSION_CREATED_V1"


class FormalMissionEventError(ValueError):
    """The candidate is not a canonical formal creation line."""


class FormalMissionCreationKey(NamedTuple):
    formal_authority_ref: str
    actor_ref: str
    project_id: str
    creation_key: str


class FormalMissionEvent(NamedTuple):
    seq: int
    event_id: str
    receipt_ref: str
    creation_key: FormalMissionCreationKey
    scope: ScopeIdentity
    mapping: RuntimeBatchMapping
    binding_ref: str
    request_digest: str
    goal: str
    created_at: int
    event_sha256: str


_ENVELOPE = {
    "seq", "event_id", "event_type", "entity_type", "entity_id", "entity_version", "payload",
}
_EMPTY_REFERENCES = ("artifact_refs", "open_gap_ids", "active_task_ids", "residual_risk_ids")
_PAYLOAD = {
    "artifact_type", "artifact_version", "mission_id", "release_id", "goal", "state",
    "sufficiency_state", "latest_evaluation_id", "revision", "created_at", "updated_at",
    "project_id", "batch_id", "scope_binding", "runtime_batch_mapping", "receipt_ref",
    *_EMPTY_REFERENCES,
}


def _invalid():
    raise FormalMissionEventError("FORMAL_MISSION_EVENT_INVALID")


def _version_one(value):
    return type(value) is int and value == 1


def _reference(value):
    return type(value) is str and value.strip() and "\0" not in value and len(value.encode("utf-8")) <= 384


def parse_formal_mission_event(raw_line):
    """Verify one exact LF-terminated source line and return immutable facts.

    The caller still has to establish the ledger authority, whole-ledger
    uniqueness, permissions and receipt provenance.
    """
    if (type(raw_line) is not bytes or not raw_line.endswith(b"\n") or
            raw_line.endswith(b"\r\n") or raw_line.find(b"\n") != len(raw_line) - 1):
        _invalid()
    try:
        envelope = next(iter_r1_snapshot_records(raw_line)).event
    except (R1SnapshotDecodeError, StopIteration) as error:
        raise FormalMissionEventError("FORMAL_MISSION_EVENT_INVALID") from error

    if (envelope.keys() != _ENVELOPE or envelope["event_type"] != FORMAL_MISSION_EVENT_TYPE or
            envelope["entity_type"] != "rc7_mission" or not _version_one(envelope["entity_version"]) or
            type(envelope["seq"]) is not int or not 1 <= envelope["seq"] <= 9223372036854775807 or
            not _reference(envelope["event_id"])):
        _invalid()

    payload = envelope["payload"]
    if (type(payload) is not dict or payload.keys() != _PAYLOAD or
            payload["artifact_type"] != "rc7_mission" or not _version_one(payload["artifact_version"]) or
            not _version_one(payload["revision"]) or payload["state"] != "REGISTERED" or
            payload["sufficiency_state"] != "UNKNOWN" or payload["latest_evaluation_id"] is not None or
            any(payload[key] != [] for key in _EMPTY_REFERENCES) or
            type(payload["created_at"]) is not int or payload["created_at"] < 0 or
            type(payload["updated_at"]) is not int or payload["updated_at"] != payload["created_at"] or
            envelope["entity_id"] != payload["mission_id"] or not _reference(payload["receipt_ref"])):
        _invalid()

    try:
        scope = parse_scope(payload)
        if scope.classification != "BOUND_STRUCTURAL_ONLY":
            _invalid()
        mapping = parse_runtime_batch_mapping(payload["runtime_batch_mapping"], scope)
        if any(value != value.strip() for value in
               (scope.mission_id, scope.release_id, mapping.runtime_release_batch_id)):
            _invalid()
        binding = payload["scope_binding"]
        preimage = dict(binding)
        request_digest = preimage.pop("request_digest")
        request = encode_mission_create_request({
            "schema_version": 1,
            "command": {"goal": payload["goal"]},
            "scope_binding": preimage,
            "runtime_batch_mapping": payload["runtime_batch_mapping"],
        })
    except (BindingStructureError, MissionCreateWireError) as error:
        raise FormalMissionEventError("FORMAL_MISSION_EVENT_INVALID") from error

    if request.digest != request_digest:
        raise FormalMissionEventError("FORMAL_MISSION_EVENT_DIGEST_MISMATCH")
    body = raw_line[:-1]
    canonical = json.dumps(envelope, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    if body != canonical:
        raise FormalMissionEventError("FORMAL_MISSION_EVENT_NONCANONICAL")
    return FormalMissionEvent(
        seq=envelope["seq"], event_id=envelope["event_id"], receipt_ref=payload["receipt_ref"],
        creation_key=FormalMissionCreationKey(**binding["creation_key_scope"]),
        scope=scope, mapping=mapping, binding_ref=binding["binding_ref"], request_digest=request_digest,
        goal=payload["goal"], created_at=payload["created_at"], event_sha256=hashlib.sha256(body).hexdigest(),
    )
