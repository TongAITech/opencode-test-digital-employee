from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .mcp_stdio import JsonLineMcpClient, McpStdioError
from .professional_tools import ProfessionalToolError, _repo_path, _resolve_binary


_MUTATING_WORDS = {
    "index",
    "build",
    "init",
    "write",
    "update",
    "delete",
    "remove",
    "clean",
    "watch",
    "serve",
    "install",
    "uninstall",
    "config",
    "migrate",
    "import",
    "export",
    "apply",
    "fix",
}
_READ_HINTS = {
    "search",
    "get",
    "list",
    "graph",
    "file",
    "files",
    "node",
    "symbol",
    "reference",
    "references",
    "caller",
    "callers",
    "callee",
    "callees",
    "dependency",
    "dependencies",
    "dependent",
    "dependents",
    "impact",
    "query",
}


def _tool_name_is_read_only(name: str) -> bool:
    lowered = name.lower().replace("-", "_")
    tokens = {token for token in lowered.split("_") if token}
    if tokens & _MUTATING_WORDS:
        return False
    return bool(tokens & _READ_HINTS)


def _client(repo: Path, timeout_seconds: int) -> JsonLineMcpClient:
    binary = _resolve_binary("PFC_CODEGRAPH_BIN")
    env = os.environ.copy()
    return JsonLineMcpClient([binary], cwd=repo, env=env, timeout_seconds=timeout_seconds)


def list_codegraph_tools(*, repo_path: str = ".", timeout_seconds: int = 30) -> Dict[str, Any]:
    repo = _repo_path(repo_path)
    try:
        with _client(repo, timeout_seconds) as client:
            initialized = client.initialize()
            tools = client.tools_list()
    except McpStdioError as exc:
        raise ProfessionalToolError("CODEGRAPH_MCP_DISCOVERY_FAILED:%s" % exc) from exc
    rows: List[Dict[str, Any]] = []
    for item in tools:
        name = str(item.get("name") or "")
        rows.append(
            {
                "name": name,
                "description": item.get("description"),
                "inputSchema": item.get("inputSchema") if isinstance(item.get("inputSchema"), dict) else {},
                "read_only_allowed": _tool_name_is_read_only(name),
            }
        )
    return {
        "tool": "codegraph_mcp_tools",
        "repo": str(repo),
        "server_info": initialized.get("serverInfo"),
        "tool_count": len(rows),
        "tools": rows,
    }


def call_codegraph_tool(
    *,
    tool_name: str,
    arguments: Optional[Mapping[str, Any]] = None,
    repo_path: str = ".",
    timeout_seconds: int = 60,
) -> Dict[str, Any]:
    repo = _repo_path(repo_path)
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise ProfessionalToolError("CODEGRAPH_MCP_TOOL_NAME_REQUIRED")
    requested = tool_name.strip()
    try:
        with _client(repo, timeout_seconds) as client:
            initialized = client.initialize()
            tools = client.tools_list()
            by_name = {str(item.get("name") or ""): item for item in tools if isinstance(item, dict)}
            if requested not in by_name:
                raise ProfessionalToolError("CODEGRAPH_MCP_TOOL_NOT_DISCOVERED:%s" % requested)
            if not _tool_name_is_read_only(requested):
                raise ProfessionalToolError("CODEGRAPH_MCP_MUTATING_TOOL_FORBIDDEN:%s" % requested)
            result = client.call_tool(requested, dict(arguments or {}))
    except ProfessionalToolError:
        raise
    except McpStdioError as exc:
        raise ProfessionalToolError("CODEGRAPH_MCP_CALL_FAILED:%s" % exc) from exc
    return {
        "tool": "codegraph_mcp_call",
        "repo": str(repo),
        "server_info": initialized.get("serverInfo"),
        "tool_name": requested,
        "arguments": dict(arguments or {}),
        "result": result,
    }
