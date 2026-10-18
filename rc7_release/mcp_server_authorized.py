"""Authority-enforcing Bank-field RC7 MCP process entrypoint.

Every tool call is fail-closed. Model-supplied mission_context is only a claim:
it must exactly match the parent launcher's trusted runtime projection. The
projected lease facts are then bound back to canonical R1 WORKER_ADMITTED,
scope and node policy before delegating to the field tool implementation.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Mapping

from rc7_release import mcp_server_field as field
from rc7_runtime.mcp_tool_authority import (
    McpToolAuthorityError,
    authorize_mcp_tool_with_runtime_lease,
)


_ALLOWED_TOOLS_ENV = "PFC_RC7_DSH_ALLOWED_TOOLS"
_MISSION_ID_ENV = "PFC_RC7_MCP_MISSION_ID"
_TASK_ID_ENV = "PFC_RC7_MCP_TASK_ID"
_WORKER_ID_ENV = "PFC_RC7_MCP_WORKER_ID"
_LEASE_ID_ENV = "PFC_RC7_MCP_LEASE_ID"
_SCOPE_REF_ENV = "PFC_RC7_MCP_SCOPE_REF"
_SOURCE_SCOPE_ENVS = {
    "workspace": "PFC_WORKSPACE",
    "state": "PFC_AITEST_STATE_DIR",
}


def _error(msg_id: object, exc: Exception) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "isError": True,
            "content": [{"type": "text", "text": str(exc)}],
        },
    }


def _truthful_initialize(response: object) -> object:
    if not isinstance(response, dict):
        return response
    result = response.get("result")
    if isinstance(result, dict):
        result["protocolVersion"] = field.PROTOCOL_VERSION
    return response


def _runtime_projection() -> Dict[str, object]:
    mission_id = str(os.environ.get(_MISSION_ID_ENV) or "").strip()
    task_id = str(os.environ.get(_TASK_ID_ENV) or "").strip()
    worker_id = str(os.environ.get(_WORKER_ID_ENV) or "").strip()
    lease_id = str(os.environ.get(_LEASE_ID_ENV) or "").strip()
    scope_ref = str(os.environ.get(_SCOPE_REF_ENV) or "").strip()
    raw_tools = str(os.environ.get(_ALLOWED_TOOLS_ENV) or "").strip()
    if not all((mission_id, task_id, worker_id, lease_id, scope_ref, raw_tools)):
        raise McpToolAuthorityError("MCP_AUTH_RUNTIME_LEASE_CONTEXT_REQUIRED")
    try:
        allowed_tools = json.loads(raw_tools)
    except Exception as exc:
        raise McpToolAuthorityError("MCP_AUTH_RUNTIME_ALLOWED_TOOLS_INVALID") from exc
    if not isinstance(allowed_tools, list) or not allowed_tools or not all(
        isinstance(value, str) and value.strip() for value in allowed_tools
    ):
        raise McpToolAuthorityError("MCP_AUTH_RUNTIME_ALLOWED_TOOLS_INVALID")
    return {
        "mission_id": mission_id,
        "task_id": task_id,
        "worker_id": worker_id,
        "lease_id": lease_id,
        "scope_ref": scope_ref,
        "allowed_tools": tuple(value.strip() for value in allowed_tools),
    }


def _authorize_call(message: Mapping[str, Any]) -> None:
    params = message.get("params") or {}
    if not isinstance(params, Mapping):
        raise McpToolAuthorityError("MCP_AUTH_PARAMS_REQUIRED")
    name = str(params.get("name") or "").strip()
    arguments = params.get("arguments") or {}
    if not name or not isinstance(arguments, Mapping):
        raise McpToolAuthorityError("MCP_AUTH_TOOL_AND_ARGUMENTS_REQUIRED")
    context = arguments.get("mission_context")
    if not isinstance(context, Mapping):
        raise McpToolAuthorityError("MCP_AUTH_MISSION_CONTEXT_REQUIRED")

    projected = _runtime_projection()
    for key in ("mission_id", "task_id", "worker_id"):
        claimed = str(context.get(key) or "").strip()
        expected = str(projected[key])
        if not claimed:
            raise McpToolAuthorityError("MCP_AUTH_MISSION_CONTEXT_REQUIRED:%s" % key)
        if claimed != expected:
            raise McpToolAuthorityError("MCP_AUTH_CONTEXT_%s_MISMATCH" % key.upper())

    authorize_mcp_tool_with_runtime_lease(
        field._truth(),
        mission_id=str(projected["mission_id"]),
        task_id=str(projected["task_id"]),
        worker_id=str(projected["worker_id"]),
        lease_id=str(projected["lease_id"]),
        scope_ref=str(projected["scope_ref"]),
        allowed_tools=projected["allowed_tools"],
        tool_name=name,
    )


def _canonicalize_scoped_source_path(message: Dict[str, Any]) -> Dict[str, Any]:
    """Translate trusted in-scope absolute read_text paths to its relative contract.

    Durable input references are canonical file:// URIs, while the read_text MCP
    contract deliberately accepts only paths relative to an approved scope root.
    DSH may therefore receive an absolute path compiled from a durable input ref.
    This adapter narrows that path back to the configured scope only when the
    fully resolved target is contained by that scope. It never makes arbitrary
    absolute paths readable and leaves already-relative calls unchanged.
    """
    delegated = copy.deepcopy(message)
    params = delegated.get("params") or {}
    if not isinstance(params, dict) or str(params.get("name") or "").strip() != "read_text":
        return delegated
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return delegated
    raw_path = arguments.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return delegated
    target = Path(raw_path.strip()).expanduser()
    if not target.is_absolute():
        return delegated

    scope = str(arguments.get("scope") or "workspace").strip()
    env_name = _SOURCE_SCOPE_ENVS.get(scope)
    if env_name is None:
        raise McpToolAuthorityError("MCP_AUTH_SOURCE_SCOPE_INVALID")
    root_value = str(os.environ.get(env_name) or "").strip()
    if not root_value and scope == "workspace":
        root_value = str(os.environ.get("PFC_AITEST_HOME") or "").strip()
    if not root_value:
        raise McpToolAuthorityError("MCP_AUTH_SOURCE_SCOPE_ROOT_REQUIRED:%s" % scope)

    root = Path(root_value).expanduser().resolve()
    resolved = target.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise McpToolAuthorityError("MCP_AUTH_SOURCE_PATH_OUTSIDE_SCOPE") from exc
    if not relative.parts:
        raise McpToolAuthorityError("MCP_AUTH_SOURCE_PATH_FILE_REQUIRED")
    arguments["path"] = relative.as_posix()
    arguments["scope"] = scope
    params["arguments"] = arguments
    delegated["params"] = params
    return delegated


def handle(message: Dict[str, Any]):
    method = message.get("method")
    delegated = message
    if method == "tools/call":
        try:
            _authorize_call(message)
            delegated = _canonicalize_scoped_source_path(message)
        except Exception as exc:
            return _error(message.get("id"), exc)
    response = field.handle(delegated)
    if method == "initialize":
        return _truthful_initialize(response)
    return response


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
