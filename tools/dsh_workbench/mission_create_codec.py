"""Pure canonical Mission request and PREPARE selection encodings."""

import hashlib
import json
from typing import NamedTuple

from .mission_scope_binding_codec import BindingStructureError, parse_scope
from .runtime_batch_mapping import RuntimeBatchMapping, parse_runtime_batch_mapping


class MissionCreateWireError(ValueError):
    """A structurally invalid or oversized formal creation encoding."""


class MissionCreateWire(NamedTuple):
    canonical_bytes: bytes
    digest: str


_KEY_FIELDS = ("formal_authority_ref", "actor_ref", "project_id", "creation_key")
_FILTER_FIELDS = ("requirement_ids", "version_ids", "sst_ids")
_BINDING_REFS = ("mission_id", "project_id", "batch_id", "binding_ref", "snapshot_ref",
                 "creation_operation_ref")
_BINDING_MAPPING_REFS = ("formal_authority_ref", "project_id", "batch_id", "runtime_release_id", "mapping_ref")
_REVISIONS = ("date_revision", "relation_revision", "access_scope_revision")
_MAPPING_POLICY = "ALLOCATE_NEW_RELEASE_V1"
_GOAL_EDGE_WHITESPACE = frozenset(
    "\u0009\u000a\u000b\u000c\u000d\u001c\u001d\u001e\u001f\u0020"
    "\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007"
    "\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
)
_MAX_WIRE_BYTES = 65536


def _invalid():
    raise MissionCreateWireError("MISSION_CREATE_WIRE_INVALID")


def _fields(value, fields):
    if type(value) is not dict or any(type(key) is not str for key in value) or value.keys() != set(fields):
        _invalid()


def _utf8(value):
    if type(value) is not str or not value or "\0" in value:
        _invalid()
    try:
        return value.encode("utf-8", "strict")
    except UnicodeError:
        _invalid()


def _identifier(value, limit=None):
    data = _utf8(value)
    if not value.strip() or (limit is not None and len(data) > limit):
        _invalid()


def _references(value, fields):
    for field in fields:
        _identifier(value[field], 384)


def _command(command):
    _fields(command, ("goal",))
    goal = command["goal"]
    if (len(_utf8(goal)) > 4096 or goal[0] in _GOAL_EDGE_WHITESPACE or
            goal[-1] in _GOAL_EDGE_WHITESPACE):
        _invalid()
    return {"goal": goal}


def _version(value, version):
    if type(value) is not int or value != version:
        _invalid()


def _mapping_policy(value):
    if type(value) is not str or value != _MAPPING_POLICY:
        _invalid()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _reject_number(token):
    _invalid()


def _decoded(value):
    if type(value) is not bytes:
        return value
    if len(value) > _MAX_WIRE_BYTES:
        raise MissionCreateWireError("MISSION_CREATE_WIRE_TOO_LARGE")
    try:
        return json.loads(value.decode("utf-8", "strict"), object_pairs_hook=_unique_object,
                          parse_float=_reject_number, parse_constant=_reject_number)
    except (ValueError, RecursionError):
        _invalid()


def _wire(value, domain):
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(canonical) > _MAX_WIRE_BYTES:
        raise MissionCreateWireError("MISSION_CREATE_WIRE_TOO_LARGE")
    return MissionCreateWire(canonical, hashlib.sha256(domain + b"\n" + canonical).hexdigest())


def encode_mission_create_request(value):
    """Encode the exact V1 digest preimage, without authorization or storage.

    Accept a plain decoded object or strict UTF-8 JSON bytes. For persisted
    inputs, the caller must compare the output bytes to the original bytes.
    """
    value = _decoded(value)
    _fields(value, ("schema_version", "command", "scope_binding", "runtime_batch_mapping"))
    _version(value["schema_version"], 1)
    command = _command(value["command"])
    binding = value["scope_binding"]
    _fields(binding, _BINDING_REFS + _REVISIONS + (
        "schema_version", "scope_digest", "release_date", "creation_key_scope", "mapping",
    ))
    _references(binding, _BINDING_REFS)
    key = binding["creation_key_scope"]
    _fields(key, _KEY_FIELDS)
    _references(key, _KEY_FIELDS)
    mapping = binding["mapping"]
    _fields(mapping, _BINDING_MAPPING_REFS + ("schema_version", "mapping_policy"))
    _references(mapping, _BINDING_MAPPING_REFS)
    _mapping_policy(mapping["mapping_policy"])

    descriptor = value["runtime_batch_mapping"]
    _fields(descriptor, RuntimeBatchMapping._fields)
    _references(descriptor, RuntimeBatchMapping._fields[1:])
    try:
        # The shared compact validator requires a digest field. The placeholder
        # is used only for validation and never enters the digest preimage.
        scope = parse_scope({
            "mission_id": binding["mission_id"],
            "release_id": mapping["runtime_release_id"],
            "project_id": binding["project_id"],
            "batch_id": binding["batch_id"],
            "scope_binding": dict(binding, request_digest="0" * 64),
        })
        checked = parse_runtime_batch_mapping(descriptor, scope)
    except BindingStructureError as error:
        raise MissionCreateWireError("MISSION_CREATE_WIRE_INVALID") from error
    return _wire({"schema_version": 1, "command": command, "scope_binding": binding,
                  "runtime_batch_mapping": checked._asdict()}, b"dsh.mission-create.v1")


def encode_mission_prepare_selection(value):
    """Encode the exact V2 selection, sorting filter IDs as required by V3."""
    value = _decoded(value)
    _fields(value, _KEY_FIELDS + ("schema_version", "batch_id", "filters", "mapping_policy", "command"))
    _version(value["schema_version"], 2)
    _references(value, _KEY_FIELDS + ("batch_id",))
    _mapping_policy(value["mapping_policy"])
    command = _command(value["command"])
    filters = value["filters"]
    _fields(filters, _FILTER_FIELDS)
    canonical_filters = {}
    for field in _FILTER_FIELDS:
        ids = filters[field]
        if type(ids) is not list:
            _invalid()
        for identifier in ids:
            _identifier(identifier)
        if len(set(ids)) != len(ids):
            _invalid()
        canonical_filters[field] = sorted(ids, key=lambda identifier: identifier.encode("utf-8"))
    return _wire(dict(value, command=command, filters=canonical_filters),
                 b"dsh.mission-prepare-selection.v2")
