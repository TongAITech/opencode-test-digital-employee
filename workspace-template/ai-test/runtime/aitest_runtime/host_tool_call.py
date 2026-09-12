"""Actual Host tool-part verification. Model parameters carry no caller authority."""
from __future__ import annotations
import os
from urllib.parse import quote
from .durable_core import canonical_json, canonical_sha256
from .general_work.execution_contract import require
from .interaction_admission import AdmissionError


def actual_tool_call(provider, *, agent, tool, action, payload, expected_input=None):
    sid, mid, cid = (os.environ.get(k, '') for k in
        ('AITEST_HOST_SESSION_ID', 'AITEST_HOST_MESSAGE_ID', 'AITEST_HOST_CALL_ID'))
    if not sid or not mid or not cid:
        raise AdmissionError('HOST_USER_TURN_REQUIRED')
    require(all(len(x) <= 256 for x in (sid, mid, cid)), 'HOST_CALL_IDENTITY_INVALID')
    row = provider._request('GET', '/session/' + quote(sid, safe='') + '/message/' +
        quote(mid, safe='') + '?' + provider._directory_query())
    require(isinstance(row, dict) and len(canonical_json(row).encode()) <= 262144,
        'HOST_CALL_MESSAGE_INVALID_OR_OVER_BUDGET')
    info = row.get('info')
    require(isinstance(info, dict) and info.get('sessionID') == sid and info.get('id') == mid
        and info.get('role') == 'assistant' and info.get('agent') == agent
        and not info.get('synthetic') and not info.get('ignored'), 'HOST_CALL_AGENT_MISMATCH')
    parts = row.get('parts')
    require(isinstance(parts, list), 'HOST_CALL_PARTS_INVALID')
    # Count by actual call identity first: a duplicate with different input is
    # still ambiguous and must not pass by filtering to the favorable input.
    matches = [p for p in parts if isinstance(p, dict) and p.get('type') == 'tool'
        and p.get('callID') == cid]
    require(len(matches) == 1, 'ACTUAL_TOOL_CALL_REQUIRED')
    p = matches[0]; state = p.get('state')
    allowed_tools = (tool,) if isinstance(tool, str) else tuple(tool)
    expected = {'action': action, 'payload': payload} if expected_input is None else expected_input
    require(p.get('tool') in allowed_tools and p.get('sessionID') == sid and p.get('messageID') == mid
        and not p.get('synthetic') and not p.get('ignored') and isinstance(state, dict)
        and state.get('status') == 'running' and state.get('input') == expected,
        'ACTUAL_TOOL_CALL_REQUIRED')
    return {'session_id': sid, 'message_id': mid, 'call_id': cid, 'tool': p['tool'],
        'input_digest': canonical_sha256(expected)}
