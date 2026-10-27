"""RC7.1 registry-bound Field MCP entrypoint.

Interactive Field sessions may execute any MCP tool that is actually registered
by the current Bank-field server. This is intentionally not a wildcard and not
a static allowlist. Worker execution remains delegated to the existing strict
signed-lease authority path.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Mapping, Set

from rc7_release import mcp_server_authorized as strict
from rc7_release import mcp_server_field as field
from rc7_runtime.mcp_tool_authority import McpToolAuthorityError


SESSION_MODE_ENV = "PFC_RC7_DSH_SESSION_MODE"
INTERACTIVE_CONTROL = "INTERACTIVE_CONTROL"
LEASE_BOUND_WORKER = "LEASE_BOUND_WORKER"
_WORKER_PROJECTION_ENVS = (
    "PFC_RC7_MCP_MISSION_ID",
    "PFC_RC7_MCP_TASK_ID",
    "PFC_RC7_MCP_WORKER_ID",
    "PFC_RC7_MCP_LEASE_ID",
    "PFC_RC7_MCP_SCOPE_REF",
    "PFC_RC7_DSH_ALLOWED_TOOLS",
)


def _worker_projection_present() -> bool:
    return all(str(os.environ.get(key) or "").strip() for key in _WORKER_PROJECTION_ENVS)


def _session_mode() -> str:
    # A complete Worker projection always wins. This prevents a child Worker
    # from inheriting Field Full Access from the parent DSH process.
    if _worker_projection_present():
        return LEASE_BOUND_WORKER
    raw = str(os.environ.get(SESSION_MODE_ENV) or "").strip().upper()
    if raw in (INTERACTIVE_CONTROL, LEASE_BOUND_WORKER):
        return raw
    if not raw:
        raise McpToolAuthorityError("MCP_AUTH_SESSION_MODE_REQUIRED")
    raise McpToolAuthorityError("MCP_AUTH_SESSION_MODE_INVALID:%s" % raw)


def _registered_mcp_tool_names() -> Set[str]:
    response = field.handle({"jsonrpc": "2.0", "id": "rc71-registry", "method": "tools/list"})
    if not isinstance(response, Mapping):
        raise McpToolAuthorityError("MCP_AUTH_TOOL_REGISTRY_UNAVAILABLE")
    result = response.get("result")
    tools = result.get("tools") if isinstance(result, Mapping) else None
    if not isinstance(tools, list):
        raise McpToolAuthorityError("MCP_AUTH_TOOL_REGISTRY_UNAVAILABLE")
    names = {
        str(tool.get("name") or "").strip()
        for tool in tools
        if isinstance(tool, Mapping)
        and str(tool.get("name") or "").strip()
        and "*" not in str(tool.get("name") or "")
    }
    if not names:
        raise McpToolAuthorityError("MCP_AUTH_REGISTERED_TOOLS_EMPTY")
    return names


def _authorize_interactive(message: Mapping[str, Any]) -> None:
    params = message.get("params") or {}
    if not isinstance(params, Mapping):
        raise McpToolAuthorityError("MCP_AUTH_PARAMS_REQUIRED")
    name = str(params.get("name") or "").strip()
    arguments = params.get("arguments") or {}
    if not name or not isinstance(arguments, Mapping):
        raise McpToolAuthorityError("MCP_AUTH_TOOL_AND_ARGUMENTS_REQUIRED")
    if "*" in name:
        raise McpToolAuthorityError("MCP_AUTH_WILDCARD_TOOL_FORBIDDEN")
    if name not in _registered_mcp_tool_names():
        raise McpToolAuthorityError("MCP_AUTH_TOOL_NOT_REGISTERED_INTERACTIVE:%s" % name)


def _error(msg_id: object, exc: Exception) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "isError": True,
            "content": [{"type": "text", "text": str(exc)}],
        },
    }


def handle(message: Dict[str, Any]):
    method = message.get("method")
    if method != "tools/call":
        # initialize/tools-list are non-executing protocol operations and retain
        # the canonical RC7 field server behavior.
        return strict.handle(message)

    try:
        mode = _session_mode()
        if mode == LEASE_BOUND_WORKER:
            return strict.handle(message)

        _authorize_interactive(message)
        delegated = strict._canonicalize_scoped_source_path(message)
        # Tool-specific guards, Human Gates, state machines and input contracts
        # still execute inside the real field implementation.
        return field.handle(delegated)
    except Exception as exc:
        return _error(message.get("id"), exc)


def main() -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            response = handle(json.loads(raw))
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": str(exc)},
            }
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
