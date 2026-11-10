"""Compact binding structural codec, contract 3266cb2d; no authority or I/O.

A BOUND_STRUCTURAL_ONLY result never proves PREPARE, creation or authorization.
This module does not serialize entire Missions or integrate formal runtime code.
"""
import datetime
import json
import math
import re
from types import MappingProxyType
from typing import NamedTuple, Optional


class BindingStructureError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _error(code='BINDING_STRUCTURE_INVALID'):
    raise BindingStructureError(code)


def _text(value, code='BINDING_STRUCTURE_INVALID'):
    if type(value) is not str or not value.strip():
        _error(code)
    try:
        value.encode('utf-8', 'strict')
    except UnicodeError:
        _error(code)


def _keys(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        _error()


def _schema(value):
    if type(value) is not int:
        _error()
    if value != 1:
        _error('BINDING_SCHEMA_UNSUPPORTED')


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


class ScopeIdentity(NamedTuple):
    classification: str
    mission_id: str
    release_id: str
    binding_bytes: Optional[bytes]


class ParsedMission(NamedTuple):
    scope: ScopeIdentity
    envelope: object


def parse_scope(envelope):
    """Check only managed scope fields of a DTO; leave unknown outer semantics."""
    if type(envelope) is not dict:
        _error('MISSION_ENVELOPE_INVALID')
    for field in ('mission_id', 'release_id'):
        _text(envelope.get(field), 'MISSION_ENVELOPE_INVALID')
    if 'scope_binding' not in envelope:
        if 'project_id' in envelope or 'batch_id' in envelope:
            _error('BINDING_FLAT_ONLY_UNQUALIFIED')
        return ScopeIdentity('LEGACY_UNBOUND', envelope['mission_id'], envelope['release_id'], None)
    binding = envelope['scope_binding']
    if binding is None:
        _error('BINDING_EXPLICIT_NULL')
    _keys(binding, ('schema_version', 'mission_id', 'project_id', 'batch_id',
                    'binding_ref', 'snapshot_ref', 'scope_digest', 'release_date',
                    'date_revision', 'relation_revision', 'access_scope_revision',
                    'creation_key_scope', 'request_digest', 'mapping', 'creation_operation_ref'))
    _schema(binding['schema_version'])
    for field in ('mission_id', 'project_id', 'batch_id', 'binding_ref', 'snapshot_ref', 'creation_operation_ref'):
        _text(binding[field])
    for field in ('scope_digest', 'request_digest'):
        if type(binding[field]) is not str or re.fullmatch('[0-9a-f]{64}', binding[field]) is None:
            _error()
    date = binding['release_date']
    try:
        if type(date) is not str or len(date) != 10 or datetime.date.fromisoformat(date).isoformat() != date:
            _error()
    except (ValueError, TypeError):
        _error()
    for field in ('date_revision', 'relation_revision', 'access_scope_revision'):
        if type(binding[field]) is not int or not 1 <= binding[field] <= 9223372036854775807:
            _error()
    key = binding['creation_key_scope']
    _keys(key, ('formal_authority_ref', 'actor_ref', 'project_id', 'creation_key'))
    for value in key.values():
        _text(value)
    mapping = binding['mapping']
    _keys(mapping, ('schema_version', 'formal_authority_ref', 'project_id', 'batch_id',
                    'runtime_release_id', 'mapping_ref', 'mapping_policy'))
    _schema(mapping['schema_version'])
    for field, value in mapping.items():
        if field != 'schema_version':
            _text(value)
    if mapping['mapping_policy'] != 'ALLOCATE_NEW_RELEASE_V1':
        _error()
    if (mapping['formal_authority_ref'] != key['formal_authority_ref'] or
            mapping['project_id'] != key['project_id'] or
            key['project_id'] != binding['project_id'] or
            mapping['batch_id'] != binding['batch_id'] or
            mapping['runtime_release_id'] != envelope['release_id'] or
            binding['mission_id'] != envelope['mission_id']):
        _error('BINDING_IDENTITY_CONFLICT')
    for field in ('project_id', 'batch_id'):
        _text(envelope.get(field), 'BINDING_MIRROR_CONFLICT')
        if envelope[field] != binding[field]:
            _error('BINDING_MIRROR_CONFLICT')
    return ScopeIdentity('BOUND_STRUCTURAL_ONLY', envelope['mission_id'], envelope['release_id'], _canonical(binding))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _error('MISSION_JSON_INVALID')
        result[key] = value
    return result


def _constant(value):
    _error('MISSION_JSON_INVALID')


def _freeze_raw(value):
    if type(value) is dict:
        for key in value:
            try:
                key.encode('utf-8', 'strict')
            except UnicodeError:
                _error('MISSION_JSON_INVALID')
        return MappingProxyType({key: _freeze_raw(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze_raw(item) for item in value)
    if type(value) is float and not math.isfinite(value):
        _error('MISSION_JSON_INVALID')
    if type(value) is str:
        try:
            value.encode('utf-8', 'strict')
        except UnicodeError:
            _error('MISSION_JSON_INVALID')
    return value


def parse_mission_json(raw):
    """Strict raw JSON with finite unknown outer floats; deep immutable output."""
    try:
        if type(raw) is bytes:
            raw = raw.decode('utf-8', 'strict')
        if type(raw) is not str or raw.startswith('\ufeff'):
            _error('MISSION_JSON_INVALID')
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
        frozen = _freeze_raw(value)
    except BindingStructureError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        _error('MISSION_JSON_INVALID')
    return ParsedMission(parse_scope(value), frozen)


def serialize_scope(scope):
    """A detached scope fragment only, never the outer Mission payload."""
    if type(scope) is not ScopeIdentity:
        _error('MISSION_ENVELOPE_INVALID')
    _text(scope.mission_id, 'MISSION_ENVELOPE_INVALID')
    _text(scope.release_id, 'MISSION_ENVELOPE_INVALID')
    if scope.classification == 'LEGACY_UNBOUND' and scope.binding_bytes is None:
        return {}
    if scope.classification != 'BOUND_STRUCTURAL_ONLY' or type(scope.binding_bytes) is not bytes:
        _error()
    # Public NamedTuple construction cannot bypass structural checks.
    try:
        binding = json.loads(scope.binding_bytes.decode('utf-8', 'strict'),
                             object_pairs_hook=_pairs, parse_constant=_constant)
        _freeze_raw(binding)
    except BindingStructureError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        _error('MISSION_JSON_INVALID')
    envelope = {'mission_id': scope.mission_id, 'release_id': scope.release_id,
                'scope_binding': binding}
    if type(binding) is dict:
        envelope.update(project_id=binding.get('project_id'), batch_id=binding.get('batch_id'))
    checked = parse_scope(envelope)
    binding = json.loads(checked.binding_bytes)
    return {'scope_binding': binding, 'project_id': binding['project_id'], 'batch_id': binding['batch_id']}


def require_unchanged(previous, candidate):
    """Pure structural equality, never a concurrency CAS or write permission."""
    old, new = parse_scope(previous), parse_scope(candidate)
    if old != new:
        _error('BINDING_IMMUTABLE_CONFLICT')
    return True
