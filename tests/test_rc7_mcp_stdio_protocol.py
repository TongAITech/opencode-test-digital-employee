from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from rc7_release import mcp_server_field as field


def _start(tmp_path: Path) -> subprocess.Popen[str]:
    env = dict(os.environ)
    env["PFC_AITEST_HOME"] = str(tmp_path)
    env["PFC_AITEST_STATE_DIR"] = str(tmp_path / "state")
    env["PFC_WORKSPACE"] = str(tmp_path)
    return subprocess.Popen(
        [sys.executable, "-m", "rc7_release.mcp_server_authorized"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def _write(process: subprocess.Popen[str], payload: dict) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _read(process: subprocess.Popen[str]) -> dict:
    assert process.stdout is not None
    line = process.stdout.readline()
    assert line, "MCP server closed stdout before returning a response"
    return json.loads(line)


def _close(process: subprocess.Popen[str]) -> tuple[str, str]:
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    process.stdin.close()
    process.wait(timeout=5)
    stdout = process.stdout.read()
    stderr = process.stderr.read()
    assert process.returncode == 0, stderr
    return stdout, stderr


def test_modern_discovery_probe_fails_fast_as_legacy_and_process_exits(tmp_path: Path) -> None:
    process = _start(tmp_path)
    _write(
        process,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": {"protocolVersion": "2026-07-28"},
        },
    )
    response = _read(process)
    assert response["id"] == 1
    assert response["error"]["code"] == -32601
    _close(process)


def test_legacy_initialize_lists_and_calls_runtime_status_then_exits(tmp_path: Path) -> None:
    process = _start(tmp_path)
    _write(
        process,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "rc7-regression", "version": "1"},
            },
        },
    )
    initialized = _read(process)
    assert initialized["result"]["protocolVersion"] == field.PROTOCOL_VERSION
    assert initialized["result"]["serverInfo"]["name"] == field.SERVER_NAME

    _write(process, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    _write(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    listed = _read(process)
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert "runtime_status" in names

    _write(
        process,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "runtime_status", "arguments": {}},
        },
    )
    called = _read(process)
    assert called["id"] == 3
    assert called["result"]["content"][0]["type"] == "text"
    assert called["result"]["content"][0]["text"] == "MCP_AUTH_MISSION_CONTEXT_REQUIRED"

    _close(process)
