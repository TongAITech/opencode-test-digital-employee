"""Reject tool/MCP resource counters when reading DSH provider inference usage.

A root event may contain valid provider usage AND separately embedded tool
results. Filter each nested tool subtree rather than rejecting the whole root.
Never promote a tool's token-like resource counters into model MEASURED usage.
"""
from __future__ import annotations

from typing import Any, Mapping


_TOOL_KINDS = {
    "tool", "tool_call", "tool_result", "function_call", "function_result",
    "mcp", "mcp_call", "mcp_result", "stderr", "session",
}
_TOOL_BRANCH_KEYS = {
    "tool", "tools", "tool_call", "tool_calls", "tool_result", "tool_results",
    "tool_output", "tool_outputs", "function_call", "function_calls",
    "function_result", "function_results", "mcp", "mcp_call", "mcp_calls",
    "mcp_result", "mcp_results",
}


def is_tool_usage_node(mapping: Mapping[str, Any]) -> bool:
    kind = str(
        mapping.get("type") or mapping.get("event") or mapping.get("kind") or ""
    ).strip().lower()
    role = str(mapping.get("role") or "").strip().lower()
    return (
        kind in _TOOL_KINDS
        or kind.startswith(("tool.", "tool_", "mcp.", "mcp_", "function."))
        or role in {"tool", "user", "system"}
        or (isinstance(mapping.get("tool_name"), str) and bool(mapping.get("tool_name")))
    )


def is_tool_branch_key(key: Any) -> bool:
    return str(key).lower() in _TOOL_BRANCH_KEYS
