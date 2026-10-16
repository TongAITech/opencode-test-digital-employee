from __future__ import annotations

import json
import sys
from pathlib import Path

from rc7_release.codegraph_mcp import _tool_name_is_read_only
from rc7_release.mcp_server import handle
from rc7_release.mcp_stdio import JsonLineMcpClient


FAKE_SERVER = r'''
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("method") == "initialize":
        result = {"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"fake-codegraph","version":"1"}}
    elif msg.get("method") == "notifications/initialized":
        continue
    elif msg.get("method") == "tools/list":
        result = {"tools":[
            {"name":"codegraph_symbol_search","description":"read","inputSchema":{"type":"object"}},
            {"name":"codegraph_build_index","description":"write","inputSchema":{"type":"object"}}
        ]}
    elif msg.get("method") == "tools/call":
        p = msg.get("params") or {}
        result = {"content":[{"type":"text","text":json.dumps({"called":p.get("name"),"args":p.get("arguments")})}]}
    else:
        result = {}
    if "id" in msg:
        sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":result}) + "\n")
        sys.stdout.flush()
'''


def test_json_line_mcp_client_uses_pipe_reader_threads_cross_platform(tmp_path: Path) -> None:
    server = tmp_path / "fake_mcp.py"
    server.write_text(FAKE_SERVER, encoding="utf-8")
    with JsonLineMcpClient([sys.executable, str(server)], cwd=tmp_path, timeout_seconds=10) as client:
        initialized = client.initialize()
        assert initialized["serverInfo"]["name"] == "fake-codegraph"
        tools = client.tools_list()
        assert {tool["name"] for tool in tools} == {"codegraph_symbol_search", "codegraph_build_index"}
        result = client.call_tool("codegraph_symbol_search", {"query": "TruthRuntime"})
        payload = json.loads(result["content"][0]["text"])
        assert payload["called"] == "codegraph_symbol_search"
        assert payload["args"]["query"] == "TruthRuntime"


def test_codegraph_dynamic_policy_admits_reads_and_blocks_mutation() -> None:
    assert _tool_name_is_read_only("codegraph_symbol_search") is True
    assert _tool_name_is_read_only("codegraph_get_dependency_graph") is True
    assert _tool_name_is_read_only("codegraph_build_index") is False
    assert _tool_name_is_read_only("codegraph_delete_index") is False


def test_rc7_mcp_lists_dynamic_codegraph_tools() -> None:
    listing = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    names = {tool["name"] for tool in listing["result"]["tools"]}
    assert "codegraph_mcp_tools" in names
    assert "codegraph_mcp_call" in names
