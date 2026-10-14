from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

from rc6_release import mcp_server as rc6
from .professional_tools import codegraph_probe, codegraph_query, git_diff, git_show_revision
from .source_tools import read_text


PROTOCOL_VERSION = rc6.PROTOCOL_VERSION
SERVER_NAME = "pfc-aitest-rc7"
SERVER_VERSION = "7.0-closed-loop-runtime-candidate"


def _object(properties: Dict[str, Any], required=None, *, additional: bool = False) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required or []),
        "additionalProperties": additional,
    }


def _extra_tools():
    s = {"type": "string"}
    a = {"type": "array", "items": s}
    return [
        {
            "name": "read_text",
            "description": "Read one UTF-8 source file contained by PFC_WORKSPACE or PFC_AITEST_STATE_DIR. Read-only and path-escape protected.",
            "inputSchema": _object(
                {
                    "path": s,
                    "scope": {"type": "string", "enum": ["workspace", "state"]},
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 1000000},
                },
                ["path"],
            ),
        },
        {
            "name": "git_show_revision",
            "description": "Read one Git commit identity from a workspace-contained repository. Read-only; shell is never used.",
            "inputSchema": _object(
                {"repo_path": s, "ref": s},
            ),
        },
        {
            "name": "git_diff",
            "description": "Read resolved Git revisions, changed files and diff between two refs. Read-only; paths are workspace-contained.",
            "inputSchema": _object(
                {
                    "repo_path": s,
                    "base_ref": s,
                    "head_ref": s,
                    "paths": a,
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 1000000},
                },
                ["base_ref", "head_ref"],
            ),
        },
        {
            "name": "codegraph_probe",
            "description": "Probe the configured CodeGraph executable with --help only. This does not establish query readiness by itself.",
            "inputSchema": _object({"repo_path": s}),
        },
        {
            "name": "codegraph_query",
            "description": "Execute one allowlisted read-only CodeGraph query in the configured workspace. Index/build/write/update operations are rejected.",
            "inputSchema": _object(
                {
                    "repo_path": s,
                    "args": a,
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300},
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 1000000},
                },
                ["args"],
            ),
        },
    ]


def _text(value: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, sort_keys=True)}]}


def _call_extra(name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if name == "read_text":
        return _text(
            read_text(
                path=arguments["path"],
                scope=str(arguments.get("scope") or "workspace"),
                max_chars=int(arguments.get("max_chars", 200000)),
            )
        )
    if name == "git_show_revision":
        return _text(
            git_show_revision(
                repo_path=str(arguments.get("repo_path") or "."),
                ref=str(arguments.get("ref") or "HEAD"),
            )
        )
    if name == "git_diff":
        return _text(
            git_diff(
                repo_path=str(arguments.get("repo_path") or "."),
                base_ref=arguments["base_ref"],
                head_ref=arguments["head_ref"],
                paths=arguments.get("paths") or (),
                max_chars=int(arguments.get("max_chars", 200000)),
            )
        )
    if name == "codegraph_probe":
        return _text(codegraph_probe(repo_path=str(arguments.get("repo_path") or ".")))
    if name == "codegraph_query":
        return _text(
            codegraph_query(
                args=arguments["args"],
                repo_path=str(arguments.get("repo_path") or "."),
                timeout_seconds=int(arguments.get("timeout_seconds", 60)),
                max_chars=int(arguments.get("max_chars", 200000)),
            )
        )
    return None


def handle(message: Dict[str, Any]):
    method = message.get("method")
    msg_id = message.get("id")
    if method == "initialize":
        response = rc6.handle(message)
        if isinstance(response, dict) and isinstance(response.get("result"), dict):
            response["result"]["serverInfo"] = {"name": SERVER_NAME, "version": SERVER_VERSION}
            response["result"]["instructions"] = (
                "RC7 closed-loop testing control plane. RC6 governed tools remain available. "
                "read_text reads real source files from controlled roots. git_show_revision/git_diff "
                "are real read-only Git execution. codegraph_query is a fixed-binary, workspace-contained, "
                "allowlisted read-only query adapter. Tool calls are runtime evidence only; Workers never "
                "own PASS authority."
            )
        return response
    if method == "tools/list":
        base = rc6.handle(message)
        if not isinstance(base, dict):
            raise RuntimeError("RC6_TOOL_LIST_INVALID")
        result = base.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise RuntimeError("RC6_TOOL_LIST_INVALID")
        result["tools"] = list(result["tools"]) + _extra_tools()
        return base
    if method == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name") or "")
        if any(tool["name"] == name for tool in _extra_tools()):
            try:
                result = _call_extra(name, params.get("arguments") or {})
                return {"jsonrpc": "2.0", "id": msg_id, "result": result}
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": str(exc)}],
                    },
                }
    return rc6.handle(message)


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
