from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from rc7_release import mcp_server_authorized
from rc7_runtime.authorized_dsh_launcher import Rc7AuthorizedDshHeadlessWorkerLauncher
from rc7_runtime.bank_dsh_tool_policy import mcp_tool
from rc7_runtime.mcp_tool_authority import (
    McpToolAuthorityError,
    authorize_mcp_tool,
    authorize_mcp_tool_with_runtime_lease,
)


REQ_READ = mcp_tool("read_text")
REQ_TRUTH = mcp_tool("truth_query")
REQ_RUNTIME = mcp_tool("runtime_status")
CODE_DIFF = mcp_tool("git_diff")


class _ProjectedTruth:
    def __init__(self, *, task_state="OUTPUT_PRODUCED", artifact_task="TASK-REQ-1"):
        self.rows = {
            "rc7_task": [
                {
                    "task_id": "TASK-REQ-1",
                    "mission_id": "MISSION-1",
                    "node": "REQUIREMENT_ANALYSIS",
                    "state": task_state,
                    "lease_owner": "wrk-producer",
                }
            ],
            "rc7_artifact": [
                {
                    "artifact_id": "ART-REQ-1",
                    "mission_id": "MISSION-1",
                    "producer_task_id": artifact_task,
                }
            ],
            "agent_runtime_event": [
                {
                    "id": "ARE-REVIEWER-ADMITTED",
                    "mission_id": "MISSION-1",
                    "event_name": "WORKER_ADMITTED",
                    "worker_instance_id": "wrk-reviewer",
                    "lease_id": "lease-reviewer",
                    "scope": "ART-REQ-1",
                },
                {
                    "id": "ARE-PRODUCER-ADMITTED",
                    "mission_id": "MISSION-1",
                    "event_name": "WORKER_ADMITTED",
                    "worker_instance_id": "wrk-producer",
                    "lease_id": "lease-producer",
                    "scope": "task:TASK-REQ-1",
                },
            ],
        }

    def query(self, kind, **filters):
        rows = self.rows.get(kind, [])
        return [
            dict(row)
            for row in rows
            if all(row.get(key) == value for key, value in filters.items() if value is not None)
        ]


def test_runtime_lease_allows_independent_requirement_reviewer_on_candidate_scope() -> None:
    truth = _ProjectedTruth()
    row = authorize_mcp_tool_with_runtime_lease(
        truth,
        mission_id="MISSION-1",
        task_id="TASK-REQ-1",
        worker_id="wrk-reviewer",
        lease_id="lease-reviewer",
        scope_ref="ART-REQ-1",
        allowed_tools=(REQ_RUNTIME, REQ_TRUTH, REQ_READ),
        tool_name="runtime_status",
    )
    assert row["lease_owner"] == "wrk-producer"
    assert row["state"] == "OUTPUT_PRODUCED"


def test_runtime_lease_rejects_tool_not_in_this_workers_projected_lease() -> None:
    truth = _ProjectedTruth()
    with pytest.raises(McpToolAuthorityError, match="RUNTIME_LEASE_TOOL_NOT_ALLOWED"):
        authorize_mcp_tool_with_runtime_lease(
            truth,
            mission_id="MISSION-1",
            task_id="TASK-REQ-1",
            worker_id="wrk-reviewer",
            lease_id="lease-reviewer",
            scope_ref="ART-REQ-1",
            allowed_tools=(REQ_RUNTIME,),
            tool_name="read_text",
        )


def test_runtime_lease_rejects_artifact_scope_for_different_task() -> None:
    truth = _ProjectedTruth(artifact_task="TASK-OTHER")
    with pytest.raises(McpToolAuthorityError, match="SCOPE_TASK_MISMATCH"):
        authorize_mcp_tool_with_runtime_lease(
            truth,
            mission_id="MISSION-1",
            task_id="TASK-REQ-1",
            worker_id="wrk-reviewer",
            lease_id="lease-reviewer",
            scope_ref="ART-REQ-1",
            allowed_tools=(REQ_RUNTIME,),
            tool_name="runtime_status",
        )


def test_legacy_producer_authority_does_not_inherit_reviewer_only_tool() -> None:
    truth = _ProjectedTruth(task_state="RUNNING")
    with pytest.raises(McpToolAuthorityError, match="TOOL_NOT_ALLOWED"):
        authorize_mcp_tool(
            truth,
            mission_id="MISSION-1",
            task_id="TASK-REQ-1",
            worker_id="wrk-producer",
            tool_name="runtime_status",
        )


def test_mcp_server_fails_closed_when_mission_context_is_missing() -> None:
    result = mcp_server_authorized.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "read_text", "arguments": {"path": "README.md"}},
        }
    )
    assert result["result"]["isError"] is True
    assert "MCP_AUTH_MISSION_CONTEXT_REQUIRED" in result["result"]["content"][0]["text"]


def test_mcp_server_rejects_model_claim_that_differs_from_runtime_projection(monkeypatch) -> None:
    monkeypatch.setenv("PFC_RC7_MCP_MISSION_ID", "MISSION-1")
    monkeypatch.setenv("PFC_RC7_MCP_TASK_ID", "TASK-REQ-1")
    monkeypatch.setenv("PFC_RC7_MCP_WORKER_ID", "wrk-real")
    monkeypatch.setenv("PFC_RC7_MCP_LEASE_ID", "lease-real")
    monkeypatch.setenv("PFC_RC7_MCP_SCOPE_REF", "task:TASK-REQ-1")
    monkeypatch.setenv("PFC_RC7_DSH_ALLOWED_TOOLS", json.dumps([REQ_READ]))
    result = mcp_server_authorized.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "read_text",
                "arguments": {
                    "path": "README.md",
                    "mission_context": {
                        "mission_id": "MISSION-1",
                        "task_id": "TASK-REQ-1",
                        "worker_id": "rc7-worker-requirement-analysis",
                    },
                },
            },
        }
    )
    assert result["result"]["isError"] is True
    assert "MCP_AUTH_CONTEXT_WORKER_ID_MISMATCH" in result["result"]["content"][0]["text"]


def test_absolute_read_path_inside_workspace_is_canonicalized_without_mutating_claim(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "docs" / "README_zh-CN.md"
    source.parent.mkdir(parents=True)
    source.write_text("real source", encoding="utf-8")
    monkeypatch.setenv("PFC_WORKSPACE", str(workspace))

    message = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "read_text",
            "arguments": {
                "path": str(source.resolve()),
                "mission_context": {
                    "mission_id": "MISSION-1",
                    "task_id": "TASK-REQ-1",
                    "worker_id": "wrk-real",
                },
            },
        },
    }
    delegated = mcp_server_authorized._canonicalize_scoped_source_path(message)

    assert delegated["params"]["arguments"]["path"] == "docs/README_zh-CN.md"
    assert delegated["params"]["arguments"]["scope"] == "workspace"
    assert message["params"]["arguments"]["path"] == str(source.resolve())
    assert "scope" not in message["params"]["arguments"]


def test_absolute_read_path_outside_workspace_is_rejected(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    monkeypatch.setenv("PFC_WORKSPACE", str(workspace))

    message = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "read_text",
            "arguments": {
                "path": str(outside.resolve()),
                "mission_context": {
                    "mission_id": "MISSION-1",
                    "task_id": "TASK-REQ-1",
                    "worker_id": "wrk-real",
                },
            },
        },
    }
    with pytest.raises(McpToolAuthorityError, match="MCP_AUTH_SOURCE_PATH_OUTSIDE_SCOPE"):
        mcp_server_authorized._canonicalize_scoped_source_path(message)


def test_relative_read_path_remains_unchanged(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("PFC_WORKSPACE", str(workspace))
    message = {
        "method": "tools/call",
        "params": {
            "name": "read_text",
            "arguments": {
                "path": "docs/README.md",
                "scope": "workspace",
                "mission_context": {
                    "mission_id": "MISSION-1",
                    "task_id": "TASK-REQ-1",
                    "worker_id": "wrk-real",
                },
            },
        },
    }
    delegated = mcp_server_authorized._canonicalize_scoped_source_path(message)
    assert delegated["params"]["arguments"]["path"] == "docs/README.md"
    assert delegated["params"]["arguments"]["scope"] == "workspace"


def test_launcher_binds_exact_runtime_identity_into_prompt() -> None:
    assignment = SimpleNamespace(
        mission_id="MISSION-1",
        worker_instance_id="wrk-real",
    )
    text = Rc7AuthorizedDshHeadlessWorkerLauncher._bind_runtime_identity_prompt(
        "ORIGINAL_PROMPT",
        assignment,
        "TASK-REQ-1",
    )
    first = text.splitlines()[0]
    assert first.startswith("RC7_RUNTIME_MISSION_CONTEXT=")
    context = json.loads(first.split("=", 1)[1])
    assert context == {
        "mission_id": "MISSION-1",
        "task_id": "TASK-REQ-1",
        "worker_id": "wrk-real",
    }
    assert "ORIGINAL_PROMPT" in text
