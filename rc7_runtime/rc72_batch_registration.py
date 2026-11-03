"""Register original release metadata, without Mission bootstrap or Field facts."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import time

from .models import ContractError
from .rc72_domain import ReleaseBatch
from .rc72_ledger_lock import ledger_lock

SCHEMA = 'RC72_RELEASE_BATCH_INPUT_V1'
FIELDS = {'schema', 'release_id', 'source_commit', 'release_batch_id', 'mission_id',
          'name', 'planned_release_time', 'version_ids', 'application_ids', 'requirement_ids'}
REGISTRATION_FIELDS = {'schema', 'source_commit', 'input_sha256', 'source_ref', 'registered_at'}


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ContractError('MISSION_BATCH_DUPLICATE_INPUT_KEY')
        result[key] = value
    return result


def read_batch_input(path, *, release_id, source_commit, release_batch_id):
    """Validate before opening/creating a ledger; never interpret PASS claims."""
    path = Path(path).expanduser().resolve()
    try:
        with path.open('rb') as stream:
            raw = stream.read(1048577)
        if len(raw) > 1048576:
            raise ContractError('MISSION_BATCH_INPUT_TOO_LARGE')
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs)
    except ContractError:
        raise
    except (OSError, ValueError, UnicodeError):
        raise ContractError('MISSION_BATCH_INPUT_UNREADABLE') from None
    if not isinstance(data, dict) or set(data) != FIELDS or data['schema'] != SCHEMA:
        raise ContractError('MISSION_BATCH_EXACT_INPUT_FIELDS_REQUIRED')
    if (not isinstance(source_commit, str) or not re.fullmatch('[0-9a-f]{40}', source_commit)
            or data['source_commit'] != source_commit or data['release_id'] != release_id
            or data['release_batch_id'] != release_batch_id):
        raise ContractError('MISSION_BATCH_RELEASE_SOURCE_MISMATCH')
    for name in ('release_id', 'release_batch_id', 'mission_id', 'name'):
        value = data[name]
        if not isinstance(value, str) or not value or value.strip() != value:
            raise ContractError('MISSION_BATCH_EXACT_IDENTITY_REQUIRED')
    for name in ('version_ids', 'application_ids', 'requirement_ids'):
        value = data[name]
        if (not isinstance(value, list) or not value
                or any(not isinstance(x, str) or not x or x.strip() != x for x in value)
                or len(set(value)) != len(value)):
            raise ContractError('MISSION_BATCH_COMPLETE_ORIGINAL_IDS_REQUIRED')
    planned = data['planned_release_time']
    if planned is not None and (not isinstance(planned, str) or not planned or planned.strip() != planned):
        raise ContractError('MISSION_BATCH_PLANNED_TIME_INVALID')
    batch = ReleaseBatch(**{k: v for k, v in data.items() if k not in {'schema', 'release_id', 'source_commit'}})
    return dict(asdict(batch), release_id=release_id, artifact_version=1,
        registration=dict(schema=SCHEMA, source_commit=source_commit,
            input_sha256=hashlib.sha256(raw).hexdigest(), source_ref=path.as_uri(), registered_at=int(time.time())))


def validate_registration(value):
    if (not isinstance(value, dict) or set(value) != REGISTRATION_FIELDS or value['schema'] != SCHEMA
            or any(not isinstance(value[k], str) or not re.fullmatch('[0-9a-f]{%d}' % size, value[k])
                   for k, size in (('source_commit', 40), ('input_sha256', 64)))
            or not isinstance(value['source_ref'], str) or not value['source_ref'].startswith('file://')
            or not isinstance(value['registered_at'], int) or isinstance(value['registered_at'], bool)
            or value['registered_at'] < 0):
        raise ContractError('MISSION_BATCH_REGISTRATION_INVALID')


def register_batch(truth, payload):
    """One atomic batch+input binding; exact cold retry does not append again."""
    from .rc72_truth import validate_release_batch
    allowed = (FIELDS - {'schema', 'source_commit'}) | {
        'state', 'readiness', 'created_at', 'updated_at', 'registration', 'artifact_type', 'artifact_version'}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ContractError('MISSION_BATCH_INITIAL_METADATA_ONLY')
    payload = validate_release_batch(payload)
    validate_registration(payload.get('registration'))
    if payload['state'] != 'REGISTERED' or payload['readiness'] != 'UNKNOWN' or payload['artifact_version'] != 1:
        raise ContractError('MISSION_BATCH_INITIAL_METADATA_ONLY')
    with ledger_lock(truth, busy='MISSION_BATCH_REGISTRATION_BUSY'):
        rows = truth.query('rc72_release_batch', release_batch_id=payload['release_batch_id'])
        if rows:
            current = rows[0]
            old = current.get('registration', {})
            keys = FIELDS - {'schema', 'source_commit'}
            if (len(rows) != 1 or any(current.get(k) != payload[k] for k in keys)
                    or any(old.get(k) != payload['registration'][k] for k in ('schema', 'source_commit', 'input_sha256'))):
                raise ContractError('MISSION_BATCH_REGISTRATION_CONFLICT')
        else:
            if truth.query('rc72_release_batch', mission_id=payload['mission_id']):
                raise ContractError('MISSION_BATCH_MISSION_ALREADY_BOUND')
            truth.append_atomic('RC72_RELEASE_BATCH_UPSERTED', payload)
        return dict(status='REGISTERED', release_batch_id=payload['release_batch_id'],
            mission_id=payload['mission_id'], release_id=payload['release_id'],
            source_commit=payload['registration']['source_commit'],
            input_sha256=payload['registration']['input_sha256'], field_verified=False, bank_final=False)
