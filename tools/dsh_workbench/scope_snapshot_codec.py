"""Side-effect-free V3 structural codec; never verifies authority or provenance.

Contract source: 04ca971676509da9379ed53a29b495d2a32c325c.
No R1, PostgreSQL, Host authorization or request-digest protocol is implemented.
"""
import datetime
import hashlib
import json
from typing import NamedTuple


class ScopeStructureError(ValueError):
    pass


def _fail():
    raise ScopeStructureError('INVALID_SCOPE_STRUCTURE')


def _keys(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        _fail()


def _text(value):
    if type(value) is not str or not value.strip():
        _fail()
    try:
        value.encode('utf-8', errors='strict')
    except UnicodeError:
        _fail()
    return value


def _integer(value):
    if type(value) is not int or not 1 <= value <= 9223372036854775807:
        _fail()


def _sort(value):
    return value.encode('utf-8')


def _source(value, kind):
    fields = {
        'REQUIREMENT_IDENTITY': ('source_system', 'source_namespace', 'source_object_id', 'source_revision', 'source_ref'),
        'SYSTEM_VERSION_IDENTITY': ('source_system', 'source_namespace', 'source_object_id', 'source_revision'),
        'VERIFIED_REQUIREMENT_VERSION': ('source_link_ref', 'source_revision'),
        'SST_IDENTITY': ('source_system', 'source_namespace', 'source_object_id', 'source_revision', 'source_ref'),
        'VERIFIED_SST_LINK': ('source_link_ref', 'verified_source_revision'),
    }[kind]
    _keys(value, ('kind',) + fields)
    if value['kind'] != kind:
        _fail()
    for field in fields:
        _text(value[field])
    return dict(value)


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _reject_number(value):
    _fail()


def parse_snapshot_json(value):
    """Parse strictly, including rejection of duplicate keys and float tokens."""
    if type(value) is bytes:
        try:
            value = value.decode('utf-8', errors='strict')
        except UnicodeError:
            _fail()
    if type(value) is not str or value.startswith('\ufeff'):
        _fail()
    try:
        parsed = json.loads(value, object_pairs_hook=_pairs,
                            parse_float=_reject_number, parse_constant=_reject_number)
    except (ValueError, UnicodeError, RecursionError):
        _fail()
    # Return a detached, sorted structure, never the caller's mutable object.
    return json.loads(canonical_scope_bytes(parsed).decode('utf-8'))


def canonical_scope_bytes(snapshot):
    """Return canonical UTF-8 bytes after structural checks only."""
    _keys(snapshot, ('schema_version', 'project_id', 'batch_id', 'release_date',
                     'date_revision', 'relation_revision', 'access_scope_revision', 'filters', 'edges'))
    if type(snapshot['schema_version']) is not int or snapshot['schema_version'] != 1:
        _fail()
    for name in ('project_id', 'batch_id'):
        _text(snapshot[name])
    date = snapshot['release_date']
    try:
        if type(date) is not str or len(date) != 10 or datetime.date.fromisoformat(date).isoformat() != date:
            _fail()
    except (ValueError, TypeError):
        _fail()
    for name in ('date_revision', 'relation_revision', 'access_scope_revision'):
        _integer(snapshot[name])
    _keys(snapshot['filters'], ('requirement_ids', 'version_ids', 'sst_ids'))
    filters = {}
    for name, values in snapshot['filters'].items():
        if type(values) is not list:
            _fail()
        for value in values:
            _text(value)
        if len(set(values)) != len(values):
            _fail()
        filters[name] = sorted(values, key=_sort)
    edges = snapshot['edges']
    if type(edges) is not list or not edges:
        _fail()
    canonical, seen, identities, versions, split, sst_versions = [], set(), {}, {}, {}, {}
    def remember(kind, identity, source):
        key = (kind,) + identity
        proof = _json_bytes(source)
        if key in identities and identities[key] != proof:
            _fail()
        identities[key] = proof
    for edge in edges:
        _keys(edge, ('requirement_id', 'system_id', 'version_id', 'sst_id',
                     'requirement_source', 'version_source', 'brv_source', 'sst_source', 'brvs_source'))
        item = dict(edge)
        for name in ('requirement_id', 'system_id', 'version_id'):
            _text(edge[name])
        r, system, v, s = (edge[x] for x in ('requirement_id', 'system_id', 'version_id', 'sst_id'))
        if v in versions and versions[v] != system:
            _fail()
        versions[v] = system
        if s is not None:
            _text(s)
        key = (r, system, v, s)
        if key in seen:
            _fail()
        seen.add(key)
        for field, kind, identity in (
            ('requirement_source', 'REQUIREMENT_IDENTITY', (r,)),
            ('version_source', 'SYSTEM_VERSION_IDENTITY', (v,)),
            ('brv_source', 'VERIFIED_REQUIREMENT_VERSION', (r, v)),
        ):
            item[field] = _source(edge[field], kind)
            remember(kind, identity, item[field])
        brv = (r, v)
        if brv in split and split[brv] != (s is not None):
            _fail()
        split[brv] = s is not None
        if s is None:
            if edge['sst_source'] is not None or edge['brvs_source'] is not None:
                _fail()
        else:
            _text(s)
            if s in sst_versions and sst_versions[s] != v:
                _fail()
            sst_versions[s] = v
            for field, kind, identity in (
                ('sst_source', 'SST_IDENTITY', (v, s)),
                ('brvs_source', 'VERIFIED_SST_LINK', (r, v, s)),
            ):
                item[field] = _source(edge[field], kind)
                remember(kind, identity, item[field])
        canonical.append(item)
    for field, column in (('requirement_ids', 'requirement_id'), ('version_ids', 'version_id'), ('sst_ids', 'sst_id')):
        selected = set(filters[field])
        actual = {edge[column] for edge in canonical if edge[column] is not None}
        if selected and selected != actual:
            _fail()
    canonical.sort(key=lambda e: tuple((0, b'') if e[k] is None else (1, _sort(e[k]))
                                      for k in ('requirement_id', 'system_id', 'version_id', 'sst_id')))
    result = dict(snapshot, filters=filters, edges=canonical)
    return _json_bytes(result)


def scope_digest(snapshot):
    return hashlib.sha256(b'dsh.scope-snapshot.v1\n' + canonical_scope_bytes(snapshot)).hexdigest()


class CreationKey(NamedTuple):
    formal_authority_ref: str
    actor_ref: str
    project_id: str
    creation_key: str


def creation_key(formal_authority_ref, actor_ref, project_id, creation_key):
    """An immutable identity tuple, not an authorization grant or wire digest."""
    values = (formal_authority_ref, actor_ref, project_id, creation_key)
    for value in values:
        _text(value)
    return CreationKey(*values)


class AdmissionHold(NamedTuple):
    status: str
    reason: str


def unavailable_host_admission():
    """Pure default boundary: no callback, no token and no mutation capability."""
    return AdmissionHold('HOLD', 'HOST_CAPABILITY_UNAVAILABLE')
