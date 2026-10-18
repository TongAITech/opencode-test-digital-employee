"""Authority-enforcing Bank-field RC7 MCP process entrypoint.

This wrapper is intentionally thin: the existing field server remains the tool
implementation and execution-chain authority.  Before delegating any tool call
that carries mission_context, this layer validates canonical R1 Task ownership
and the node-specific Bank DSH tool policy so a model cannot execute a tool that
was merely discoverable in MCP but not granted to its leased Task.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, Mapping

from rc7_release import mcp_server_field as field
from rc7_runtime.mcp_tool_authority import authorize_mcp_tool


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
    if message.get("method") == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name") or "").strip()
        arguments = params.get("arguments") or {}
        context = arguments.get("mission_context") if isinstance(arguments, Mapping) else None
        if isinstance(context, Mapping):
            try:
                authorize_mcp_tool(
                    field._truth(),
                    mission_id=str(context.get("mission_id") or ""),
                    task_id=str(context.get("task_id") or ""),
                    worker_id=str(context.get("worker_id") or ""),
                    tool_name=name,
                )
            except Exception as exc:
                return _error(message.get("id"), exc)
    return field.handle(message)


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
