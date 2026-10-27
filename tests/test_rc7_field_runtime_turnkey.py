from __future__ import annotations

from pathlib import Path

import pytest

from rc7_release import mcp_server_field_validation as server


WORKER_ENV = {
    "PFC_RC7_MCP_MISSION_ID": "mission-1",
    "PFC_RC7_MCP_TASK_ID": "task-1",
    "PFC_RC7_MCP_WORKER_ID": "worker-1",
    "PFC_RC7_MCP_LEASE_ID": "lease-1",
    "PFC_RC7_MCP_SCOPE_REF": "task:task-1",
    "PFC_RC7_DSH_ALLOWED_TOOLS": '["runtime_status"]',
}


def _clear_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in WORKER_ENV:
        monkeypatch.delenv(key, raising=False)


def test_interactive_control_authorizes_live_registered_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_worker(monkeypatch)
    monkeypatch.setenv(server.SESSION_MODE_ENV, server.INTERACTIVE_CONTROL)

    calls = []

    def fake_field(message):
        if message.get("method") == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "result": {"tools": [{"name": "runtime_status"}, {"name": "truth_query"}]},
            }
        calls.append(message)
        return {"jsonrpc": "2.0", "id": message.get("id"), "result": {"content": []}}

    monkeypatch.setattr(server.field, "handle", fake_field)
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "runtime_status", "arguments": {}},
        }
    )
    assert not response["result"].get("isError")
    assert calls and calls[0]["params"]["name"] == "runtime_status"


def test_interactive_control_denies_unregistered_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_worker(monkeypatch)
    monkeypatch.setenv(server.SESSION_MODE_ENV, server.INTERACTIVE_CONTROL)
    monkeypatch.setattr(
        server.field,
        "handle",
        lambda message: {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {"tools": [{"name": "runtime_status"}]},
        },
    )
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "not_registered_anywhere", "arguments": {}},
        }
    )
    assert response["result"]["isError"] is True
    assert "MCP_AUTH_TOOL_NOT_REGISTERED_INTERACTIVE:not_registered_anywhere" in response["result"]["content"][0]["text"]


def test_complete_worker_projection_overrides_inherited_interactive_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(server.SESSION_MODE_ENV, server.INTERACTIVE_CONTROL)
    for key, value in WORKER_ENV.items():
        monkeypatch.setenv(key, value)

    marker = {"strict": True}
    monkeypatch.setattr(server.strict, "handle", lambda message: marker)
    monkeypatch.setattr(server.field, "handle", lambda message: (_ for _ in ()).throw(AssertionError("field path leaked into worker")))
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "runtime_status", "arguments": {}},
        }
    )
    assert response is marker
    assert server._session_mode() == server.LEASE_BOUND_WORKER


def test_missing_interactive_session_mode_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_worker(monkeypatch)
    monkeypatch.delenv(server.SESSION_MODE_ENV, raising=False)
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "runtime_status", "arguments": {}},
        }
    )
    assert response["result"]["isError"] is True
    assert "MCP_AUTH_SESSION_MODE_REQUIRED" in response["result"]["content"][0]["text"]


def test_field_dsh_policy_is_live_registry_bound_and_worker_fail_closed() -> None:
    root = Path(__file__).resolve().parents[1]
    policy = (root / "rc7_release" / "rc71_field_tool_policy.ts").read_text(encoding="utf-8")
    assert "scope.tools.schemas(agent)" in policy
    assert "interactiveAllowSet" in policy
    assert "workerProjectionPresent()" in policy
    assert "RC7_DSH_ALLOWED_TOOLS_EMPTY" in policy
    assert "RC7_DSH_TOOL_NOT_REGISTERED" in policy
    assert "includes('*')" in policy


def test_startup_is_thin_no_package_manager_and_resets_stale_worker_projection() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "packaging" / "rc7" / "start-rc7.1.sh").read_text(encoding="utf-8")
    lowered = script.lower()
    assert "npm install" not in lowered
    assert "pnpm" not in lowered
    assert "pip install" not in lowered
    assert 'PFC_RC7_DSH_SESSION_MODE="INTERACTIVE_CONTROL"' in script
    assert "unset PFC_RC7_DSH_ALLOWED_TOOLS" in script
    assert "rc7_release.mcp_server_field_validation" in script
    assert "rc71_field_tool_policy.ts" in script
    assert 'exec "$DSH" --profile "$PROFILE" --patch "$PATCH"' in script
