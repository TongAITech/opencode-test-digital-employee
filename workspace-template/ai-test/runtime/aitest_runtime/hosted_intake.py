"""Bind an OpenCode tool call to its actual User message before R2.2 intake."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import os
import re
from typing import Any, Mapping
from urllib.parse import quote

from .r2_2.contracts import normalize_scope
from .r2_1.contracts import validate_secret_boundary


def hosted_user_intake(provider: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    # These values are set from ToolContext by the host bridge, never tool args.
    session = os.environ.get('AITEST_HOST_SESSION_ID', '')
    message = os.environ.get('AITEST_HOST_MESSAGE_ID', '')
    if not session or not message:
        raise RuntimeError('HOST_USER_TURN_REQUIRED')
    def read(message_id):
        value = provider._request('GET', '/session/' + quote(session, safe='') + '/message/' + quote(message_id, safe='') + '?' + provider._directory_query())
        info = value.get('info', {}) if isinstance(value, dict) else {}
        if info.get('sessionID') != session or info.get('id') != message_id:
            raise RuntimeError('HOST_USER_TURN_IDENTITY_MISMATCH')
        return value
    current = read(message)
    if current['info'].get('role') == 'assistant':
        parent = current['info'].get('parentID')
        if not parent: raise RuntimeError('HOST_USER_PARENT_REQUIRED')
        current = read(parent)
    info = current['info']
    if info.get('role') != 'user': raise RuntimeError('HOST_USER_TURN_REQUIRED')
    text = '\n'.join(str(p.get('text', '')) for p in current.get('parts', [])
                     if p.get('type') == 'text' and not p.get('synthetic') and not p.get('ignored')).strip()
    if not text or len(text.encode('utf-8')) > 16384:
        raise RuntimeError('HOST_USER_TURN_EMPTY_OR_OVER_BUDGET')
    validate_secret_boundary({'user_request': text})
    if set(payload) - {'user_request', 'scope'}:
        raise ValueError('Hosted start_test accepts user_request and explicit scope only; Runtime supplies provenance')
    if payload.get('user_request') and payload['user_request'].strip() != text:
        raise ValueError('USER_REQUEST_MUST_MATCH_HOST_MESSAGE')
    scope = payload.get('scope')
    if scope is None:
        scope = {'mode': 'EXPLICIT_SET'}
        # Preserve the literal release label. No inference of project/repository
        # identity, nor assertion that this is the bank current release.
        match = re.fullmatch(r'(?:请)?(?:开始)?测试\s*([A-Za-z][A-Za-z0-9_.-]*\d[A-Za-z0-9_.-]*)', text)
        if match: scope['version'] = match.group(1)
    scope = normalize_scope(scope)
    if set(scope) - {'mode', 'project_id', 'version', 'requirements'}:
        raise ValueError('Hosted scope permits literal project_id/version/requirements only')
    for key, value in scope.items():
        if key == 'mode': continue
        values = value if isinstance(value, list) else [value]
        if any(not isinstance(item, str) or item not in text for item in values):
            raise ValueError('HOST_SCOPE_MUST_BE_EXPLICIT_IN_USER_TURN')
    created = info.get('time', {}).get('created')
    if not isinstance(created, (int, float)): raise RuntimeError('HOST_USER_TURN_TIMESTAMP_REQUIRED')
    source_ref = f'opencode://session/{session}/message/{info["id"]}'
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    return {'intake_id': 'host-turn-' + hashlib.sha256(source_ref.encode()).hexdigest(),
            'operation': 'CREATE', 'scope': scope,
            'goal': {'title': text, 'intent': text, 'constraints': ['Unknown bank facts require governed binding; user intent is not release or coverage truth.']},
            'source': {'kind': 'USER', 'source_ref': source_ref, 'source_digest': digest,
                       'observed_at': datetime.fromtimestamp(created / 1000, timezone.utc).isoformat(),
                       'valid_until': None, 'source_precedence': 1},
            'actor': {'type': 'USER', 'id': 'opencode-user-turn'}}
