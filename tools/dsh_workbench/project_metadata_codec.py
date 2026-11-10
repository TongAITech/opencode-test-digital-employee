"""Pure M1 rename protocol, never an authorization or database admission token.

No HTTP/SQL/R1 imports or mutable DTOs. All limits apply before canonical hashing.
The project argument identifies the route target only; it supplies no authority.
"""
import hashlib
import json
import re
from dataclasses import dataclass

ACTION = 'project.metadata.update/v1'
NAME_POLICY = 'project-name/utf8-exact-v1'
MAX_BODY_BYTES = 16384
MAX_REVISION = 9223372036854775807
_REQUEST_ID = re.compile(r'[A-Za-z0-9._:-]{1,128}\Z', re.ASCII)
_REVISION = re.compile(r'[1-9][0-9]{0,18}\Z', re.ASCII)


class MetadataProtocolError(ValueError):
    """Stable non-reflective code; deliberately excludes request text."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _fail(code):
    raise MetadataProtocolError(code)


def _utf8(value, code):
    if type(value) is not str:
        _fail(code)
    try:
        return value.encode('utf-8', 'strict')
    except UnicodeError:
        _fail(code)


def normalize_name(value):
    """Return canonical name; ASCII space trim only, no Unicode normalization."""
    _utf8(value, 'NAME_INVALID_UTF8_OR_TYPE')
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        _fail('NAME_CONTROL_FORBIDDEN')
    name = value.strip(' ')
    if not 1 <= len(name) <= 128:
        _fail('NAME_SCALAR_LIMIT')
    if len(name.encode('utf-8')) > 512:
        _fail('NAME_BYTE_LIMIT')
    return name


def parse_revision(value):
    if type(value) is not str or not _REVISION.fullmatch(value):
        _fail('REVISION_INVALID')
    if int(value) > MAX_REVISION:
        _fail('REVISION_INVALID')
    return value


@dataclass(frozen=True)
class MetadataRenameRequest:
    """Deep immutable syntax result, NOT a verified principal/scope/admission.

    No current database value is consulted: even equal names are not NO_CHANGE.
    Replayed canonical bytes and digest identify syntax, not committed outcomes.
    """
    __slots__ = ('project_id', 'request_id', 'expected_metadata_revision',
                 'expected_access_scope_revision', 'name', 'reason')

    project_id: str
    request_id: str
    expected_metadata_revision: str
    expected_access_scope_revision: str
    name: str
    reason: str

    def __post_init__(self):
        # Public construction is still syntax-only, but cannot introduce mutable
        # fields or noncanonical state into this immutable value object.
        if not _utf8(self.project_id, 'PROJECT_TARGET_INVALID'):
            _fail('PROJECT_TARGET_INVALID')
        if type(self.request_id) is not str or not _REQUEST_ID.fullmatch(self.request_id):
            _fail('REQUEST_ID_INVALID')
        parse_revision(self.expected_metadata_revision)
        parse_revision(self.expected_access_scope_revision)
        if normalize_name(self.name) != self.name:
            _fail('NAME_NOT_CANONICAL')
        if len(_utf8(self.reason, 'REASON_INVALID_UTF8_OR_TYPE')) > 2048:
            _fail('REASON_BYTE_LIMIT')

    @property
    def name_key(self):
        return self.name.encode('utf-8')

    @property
    def canonical_bytes(self):
        return _canonical(self, ACTION)

    @property
    def payload_digest(self):
        return hashlib.sha256(self.canonical_bytes).hexdigest()


def _canonical(request, action):
    # Internal action domain is fixed by public parsing; never accepted from body.
    payload = {
        'schema': 'dsh-workbench/project-metadata-request/v1',
        'action': action,
        'name_policy': NAME_POLICY,
        'project_id': request.project_id,
        'request_id': request.request_id,
        'expected_metadata_revision': request.expected_metadata_revision,
        'expected_access_scope_revision': request.expected_access_scope_revision,
        'changes': {'name': request.name},
        'reason': request.reason,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail('JSON_DUPLICATE_KEY')
        result[key] = value
    return result


def _number(_value):
    # This protocol contains no JSON-number field (revision is decimal string).
    _fail('JSON_NUMBER_FORBIDDEN')


def parse_rename_request(raw, project_id):
    """Parse raw UTF8 JSON bytes without making business or authority decisions.

    Escaped surrogates are rejected throughout the decoded JSON tree, including
    unknown fields. Body budget is raw bytes, before JSON whitespace unescaping.
    Only the name's U+0020 edges are normalized. Reason is preserved exactly.
    """
    target = _utf8(project_id, 'PROJECT_TARGET_INVALID')
    if not target:
        _fail('PROJECT_TARGET_INVALID')
    if type(raw) is not bytes:
        _fail('BODY_BYTES_REQUIRED')
    if len(raw) > MAX_BODY_BYTES:
        _fail('BODY_BYTE_LIMIT')
    try:
        text = raw.decode('utf-8', 'strict')
    except UnicodeError:
        _fail('JSON_INVALID_UTF8')
    try:
        value = json.loads(text, object_pairs_hook=_object,
                           parse_int=_number, parse_float=_number,
                           parse_constant=_number)
    except MetadataProtocolError:
        raise
    except (ValueError, RecursionError):
        _fail('JSON_INVALID')
    # No recursive walk: depth is attacker-controlled. Visit iteratively.
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is str:
            _utf8(item, 'JSON_INVALID_UNICODE')
        elif type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
    if type(value) is not dict or set(value) != {
            'request_id', 'expected_metadata_revision',
            'expected_access_scope_revision', 'changes', 'reason'}:
        _fail('REQUEST_FIELDS_INVALID')
    if type(value['changes']) is not dict or set(value['changes']) != {'name'}:
        _fail('CHANGES_FIELDS_INVALID')
    request_id = value['request_id']
    if type(request_id) is not str or not _REQUEST_ID.fullmatch(request_id):
        _fail('REQUEST_ID_INVALID')
    metadata_revision = parse_revision(value['expected_metadata_revision'])
    access_revision = parse_revision(value['expected_access_scope_revision'])
    name = normalize_name(value['changes']['name'])
    reason = value['reason']
    if len(_utf8(reason, 'REASON_INVALID_UTF8_OR_TYPE')) > 2048:
        _fail('REASON_BYTE_LIMIT')
    return MetadataRenameRequest(project_id, request_id, metadata_revision,
                                 access_revision, name, reason)
