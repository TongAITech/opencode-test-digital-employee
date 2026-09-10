"""Read host-owned message identity; model arguments are never provenance."""
from __future__ import annotations
import hashlib
import math
import os
import time
from typing import Any, Mapping
from urllib.parse import quote

from .interaction_admission import (ActualHostUserTurn, AdmissionError, decide,
    literal_start_proposal, mission_intake, parse_proposal)
from .r2_1.contracts import validate_secret_boundary

MAX_HOST_TURN_BYTES = 16384
MAX_HOST_TURN_AGE_MS = 15 * 60 * 1000
MAX_CLOCK_SKEW_MS = 30 * 1000


def actual_host_user_turn(provider: Any, *, now_ms: int | None = None) -> ActualHostUserTurn:
    # The official tool bridge overwrites these values from its ToolContext.
    # A direct local process is a trusted internal boundary, not a remote API.
    session = os.environ.get('AITEST_HOST_SESSION_ID', '')
    tool_message = os.environ.get('AITEST_HOST_MESSAGE_ID', '')
    if not session or not tool_message:
        raise AdmissionError('HOST_USER_TURN_REQUIRED')
    if len(session) > 256 or len(tool_message) > 256:
        raise AdmissionError('HOST_USER_TURN_IDENTITY_INVALID')
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    def read(message_id: str) -> dict[str, Any]:
        value = provider._request('GET', '/session/' + quote(session, safe='') + '/message/' + quote(message_id, safe='') + '?' + provider._directory_query())
        if not isinstance(value, dict) or not isinstance(value.get('info'), dict):
            raise AdmissionError('HOST_USER_TURN_RESPONSE_INVALID')
        info = value['info']
        if info.get('sessionID') != session or info.get('id') != message_id:
            raise AdmissionError('HOST_USER_TURN_IDENTITY_MISMATCH')
        if info.get('synthetic') or info.get('ignored'):
            raise AdmissionError('HOST_SYNTHETIC_MESSAGE_FORBIDDEN')
        return value
    current = read(tool_message)
    parent = None
    if current['info'].get('role') == 'assistant':
        parent = current['info'].get('parentID')
        if not isinstance(parent, str) or not parent or parent == tool_message or len(parent) > 256:
            raise AdmissionError('HOST_USER_PARENT_REQUIRED')
        current = read(parent)
    info = current['info']
    if info.get('role') != 'user':
        raise AdmissionError('HOST_USER_TURN_REQUIRED')
    created = info.get('time', {}).get('created') if isinstance(info.get('time'), dict) else None
    if isinstance(created, bool) or not isinstance(created, (int, float)) or not math.isfinite(created):
        raise AdmissionError('HOST_USER_TURN_TIMESTAMP_REQUIRED')
    created = int(created)
    if created > now_ms + MAX_CLOCK_SKEW_MS:
        raise AdmissionError('HOST_USER_TURN_TIMESTAMP_IN_FUTURE')
    if created < now_ms - MAX_HOST_TURN_AGE_MS:
        raise AdmissionError('HOST_USER_TURN_EXPIRED')
    parts = current.get('parts')
    if not isinstance(parts, list):
        raise AdmissionError('HOST_USER_TURN_PARTS_INVALID')
    text_parts = []
    for part in parts:
        if not isinstance(part, Mapping): raise AdmissionError('HOST_USER_TURN_PART_INVALID')
        if part.get('type') != 'text' or part.get('synthetic') or part.get('ignored'): continue
        if ('messageID' in part and part['messageID'] != info['id']) or ('sessionID' in part and part['sessionID'] != session):
            raise AdmissionError('HOST_USER_TURN_PART_IDENTITY_MISMATCH')
        if not isinstance(part.get('text'), str): raise AdmissionError('HOST_USER_TURN_TEXT_INVALID')
        text_parts.append(part['text'])
    text = '\n'.join(text_parts)
    if not text.strip() or len(text.encode('utf-8')) > MAX_HOST_TURN_BYTES:
        raise AdmissionError('HOST_USER_TURN_EMPTY_OR_OVER_BUDGET')
    validate_secret_boundary({'user_request': text})
    return ActualHostUserTurn(session, info['id'], tool_message, parent, text,
                              hashlib.sha256(text.encode('utf-8')).hexdigest(),
                              created, created + MAX_HOST_TURN_AGE_MS)


def validate_host_payload(payload: Mapping[str, Any], turn: ActualHostUserTurn) -> None:
    if not isinstance(payload, Mapping) or set(payload) - {'user_request', 'scope', 'proposal'}:
        raise AdmissionError('HOST_INTAKE_PAYLOAD_FIELDS_FORBIDDEN')
    if 'user_request' in payload and payload['user_request'] != turn.text:
        raise AdmissionError('USER_REQUEST_MUST_MATCH_HOST_MESSAGE')
    if 'proposal' in payload and 'scope' in payload:
        raise AdmissionError('SCOPE_MUST_BELONG_TO_ITS_OPERATION')


def hosted_user_intake(provider: Any, payload: Mapping[str, Any], *, now_ms: int | None = None) -> dict[str, Any]:
    """Validated R2 request construction only, not replay consumption/execution.

    The product entry uses hosted_interaction so same-R1 receipt ownership and
    zero/one/many durable context resolution precede actual service dispatch.
    """
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    turn = actual_host_user_turn(provider, now_ms=now_ms)
    validate_host_payload(payload, turn)
    proposal = payload.get('proposal') or literal_start_proposal(turn, payload.get('scope'))
    operations = parse_proposal(proposal, turn)
    if len(operations) != 1: raise AdmissionError('SINGLE_START_TEST_OPERATION_REQUIRED')
    admitted = decide(turn, operations[0], [], now_ms=now_ms)
    return mission_intake(turn, admitted)
