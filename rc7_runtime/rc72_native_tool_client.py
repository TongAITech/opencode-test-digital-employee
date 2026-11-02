"""Child-side RPC projection; no signing key or tool implementation lives here."""
import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from .models import ContractError
from .rc72_native_n5_tool_gate import URL_ENV, TOKEN_ENV, CONTEXT_ENV


def call_native_tool(request_id, tool, arguments, *, timeout_seconds=15):
    url, token = os.environ.get(URL_ENV, ''), os.environ.get(TOKEN_ENV, '')
    parts = urlsplit(url)
    if (parts.scheme != 'http' or parts.hostname != '127.0.0.1' or parts.path != '/call'
            or parts.username or parts.password or parts.query or parts.fragment or not parts.port or not token):
        raise ContractError('NATIVE_TOOL_PARENT_ENDPOINT_REQUIRED')
    payload = json.dumps(dict(request_id=request_id, tool=tool, arguments=arguments), allow_nan=False).encode()
    request = Request(url, data=payload, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}, method='POST')
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            result = json.loads(response.read(1024 * 1024))
    except HTTPError as exc:
        try:
            reason = json.loads(exc.read(65536)).get('error', 'NATIVE_TOOL_PARENT_DENIED')
        except (ValueError, TypeError):
            reason = 'NATIVE_TOOL_PARENT_DENIED'
        raise ContractError(reason) from None
    if not isinstance(result, dict) or set(result) != {'result', 'call_id'}:
        raise ContractError('NATIVE_TOOL_PARENT_RESPONSE_INVALID')
    return result


def handle_native_mcp_call(message):
    params = message.get('params')
    if not isinstance(params, dict) or not isinstance(params.get('arguments'), dict):
        raise ContractError('NATIVE_TOOL_MCP_ARGUMENTS_REQUIRED')
    arguments = dict(params['arguments'])
    expected = json.loads(os.environ.get(CONTEXT_ENV, '{}'))
    if not expected or arguments.pop('mission_context', None) != expected:
        raise ContractError('NATIVE_TOOL_MCP_IDENTITY_CLAIM_MISMATCH')
    name = params.get('name')
    allowed = json.loads(os.environ.get('PFC_RC7_DSH_ALLOWED_TOOLS', '[]'))
    qualified = 'mcp__pfc_aitest_rc7__' + str(name)
    tool = name if name in allowed else qualified
    if tool not in allowed:
        raise ContractError('NATIVE_TOOL_MCP_NAME_FORBIDDEN')
    result = call_native_tool('mcp-' + str(message.get('id')), tool, arguments)
    return dict(jsonrpc='2.0', id=message.get('id'), result=dict(isError=False,
        content=[dict(type='text', text=json.dumps(result['result'], sort_keys=True))],
        _meta=dict(rc72_native_tool_call_ref=result['call_id'])))


def native_tool_schemas():
    allowed = json.loads(os.environ.get('PFC_RC7_DSH_ALLOWED_TOOLS', '[]'))
    return [dict(name=name[len('mcp__pfc_aitest_rc7__'):],
        description='Exact scoped N5 operation through the live parent authority; no canonical PASS authority.',
        inputSchema=dict(type='object', additionalProperties=False, required=['data_ref', 'precondition_refs', 'mission_context'],
            properties=dict(data_ref=dict(type='string'), precondition_refs=dict(type='array', items=dict(type='string')),
                mission_context=dict(type='object', additionalProperties=False, required=['mission_id', 'task_id', 'worker_id'],
                    properties={key: dict(type='string') for key in ('mission_id', 'task_id', 'worker_id')}))))
        for name in allowed if isinstance(name, str) and name.startswith('mcp__pfc_aitest_rc7__')]
