from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from rc6_runtime import MissionRuntime

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "pfc-aitest-rc6"
SERVER_VERSION = "6.0-engineering-candidate"


def _home() -> Path:
    return Path(os.environ.get("PFC_AITEST_HOME", os.getcwd())).resolve()


def _state_root() -> Path:
    root = Path(os.environ.get("PFC_AITEST_STATE_DIR", str(_home() / "runtime-state"))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _mission_runtime() -> MissionRuntime:
    return MissionRuntime(str(_state_root() / "missions"))


def _text(value: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, sort_keys=True)}]}


def _tools() -> list[dict]:
    return [
        {
            "name": "runtime_status",
            "description": "Read RC6 runtime/build identity without mutating mission truth.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "mission_create",
            "description": "Create one durable RC6 Mission. Conversation/session is not Mission truth.",
            "inputSchema": {
                "type": "object",
                "properties": {"mission_id": {"type": "string"}, "release_id": {"type": "string"}},
                "required": ["mission_id", "release_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "mission_status",
            "description": "Load durable Mission state by mission_id.",
            "inputSchema": {
                "type": "object",
                "properties": {"mission_id": {"type": "string"}},
                "required": ["mission_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "mission_checkpoint",
            "description": "Create a small durable successor-session ResumeEnvelope; it never includes chat history.",
            "inputSchema": {
                "type": "object",
                "properties": {"mission_id": {"type": "string"}},
                "required": ["mission_id"],
                "additionalProperties": False,
            },
        },
    ]


def _runtime_status() -> dict:
    home = _home()
    def read(name: str) -> str | None:
        path = home / name
        return path.read_text(encoding="utf-8").strip() if path.is_file() else None
    return {
        "server": SERVER_NAME,
        "server_version": SERVER_VERSION,
        "release_status": read("RELEASE_STATUS") or "SOURCE_TREE",
        "build_id": read("BUILD_ID"),
        "source_commit": read("SOURCE_COMMIT"),
        "durable_truth": "R1_EVENT_STREAM",
        "mission_session_separated": True,
    }


def _call_tool(name: str, arguments: dict) -> dict:
    runtime = _mission_runtime()
    if name == "runtime_status":
        return _text(_runtime_status())
    if name == "mission_create":
        state = runtime.create(arguments["mission_id"], arguments["release_id"])
        return _text(asdict(state))
    if name == "mission_status":
        return _text(asdict(runtime.load(arguments["mission_id"])))
    if name == "mission_checkpoint":
        state = runtime.load(arguments["mission_id"])
        envelope = runtime.checkpoint(state)
        return _text(asdict(envelope))
    raise RuntimeError("UNKNOWN_TOOL")


def handle(message: dict) -> dict | None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": message.get("params", {}).get("protocolVersion") or PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": "RC6 MCP is a governed runtime control surface. Use pfc-full-chain-test skill; never treat chat text as Mission truth.",
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": _tools()}}
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            result = _call_tool(params.get("name", ""), params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"isError": True, "content": [{"type": "text", "text": str(exc)}]},
            }
    if msg_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
            response = handle(message)
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
