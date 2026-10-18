from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from rc6_runtime.agent_runtime import AgentRuntimeError
from rc6_runtime.authority import AuthorityRuntime
from rc6_runtime.truth import TruthRuntime
from rc7_release import dsh
from rc7_runtime.authorized_dsh_launcher import (
    ALLOWED_TOOLS_ENV,
    Rc7AuthorizedDshHeadlessWorkerLauncher,
)
from rc7_runtime.mcp_tool_authority import McpToolAuthorityError, authorize_mcp_tool


REQ_READ = "mcp__pfc_aitest_rc7__read_text"
REQ_TRUTH = "mcp__pfc_aitest_rc7__truth_query"
CODE_DIFF = "mcp__pfc_aitest_rc7__git_diff"


def test_generated_dsh_patch_has_package_local_fail_closed_tool_filter(tmp_path: Path) -> None:
    patch = dsh.write_patch(tmp_path / "rc7.patch.yml", tmp_path, "/usr/bin/python3")
    text = patch.read_text(encoding="utf-8")
    plugin = tmp_path / dsh.TOOL_POLICY_PLUGIN_NAME

    assert plugin.is_file()
    source = plugin.read_text(encoding="utf-8")
    assert "scope.tools.restrict({ allow })" in source
    assert "PFC_RC7_DSH_ALLOWED_TOOLS" in source
    assert "capabilityAliases.has(tool)" in source
    assert "return []" in source
    assert "name: './rc7-tool-policy.ts'" in text
    assert "rc7_release.mcp_server_authorized" in text
    assert "rc7_release.mcp_server_field" not in text


class _TaskTruth:
    def __init__(self, row):
        self.row = dict(row)

    def query(self, kind, **filters):
        assert kind == "rc7_task"
        if filters.get("task_id") != self.row.get("task_id"):
            return []
        return [dict(self.row)]


def _requirement_task(**overrides):
    row = {
        "task_id": "TASK-REQ-1",
        "mission_id": "MISSION-1",
        "node": "REQUIREMENT_ANALYSIS",
        "state": "RUNNING",
        "lease_owner": "worker-1",
    }
    row.update(overrides)
    return row


def test_mcp_authority_allows_only_tools_from_durable_node_policy() -> None:
    truth = _TaskTruth(_requirement_task())
    row = authorize_mcp_tool(
        truth,
        mission_id="MISSION-1",
        task_id="TASK-REQ-1",
        worker_id="worker-1",
        tool_name="read_text",
    )
    assert row["node"] == "REQUIREMENT_ANALYSIS"

    with pytest.raises(McpToolAuthorityError, match="MCP_AUTH_TOOL_NOT_ALLOWED"):
        authorize_mcp_tool(
            truth,
            mission_id="MISSION-1",
            task_id="TASK-REQ-1",
            worker_id="worker-1",
            tool_name="git_diff",
        )

    with pytest.raises(McpToolAuthorityError, match="MCP_AUTH_WORKER_NOT_LEASE_OWNER"):
        authorize_mcp_tool(
            truth,
            mission_id="MISSION-1",
            task_id="TASK-REQ-1",
            worker_id="worker-other",
            tool_name="read_text",
        )


def _launcher(tmp_path: Path, tool_name: str, captured: dict):
    dsh_bin = tmp_path / "dsh"
    dsh_bin.write_text("stub", encoding="utf-8")
    patch = tmp_path / "patch.yml"
    patch.write_text("stub", encoding="utf-8")
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    authority = AuthorityRuntime(b"0123456789abcdef-rc7-tool-authority")

    def runner(command, **kwargs):
        captured["env"] = dict(kwargs.get("env") or {})
        stdout = "\n".join(
            [
                json.dumps({"type": "session", "sessionId": "session-rc7-authority"}),
                json.dumps({"type": "tool_call", "tool": tool_name, "callId": "call-1"}),
                json.dumps({"type": "tool_result", "callId": "call-1", "status": "success"}),
                json.dumps({"type": "final", "text": json.dumps({"ok": True})}),
            ]
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    launcher = Rc7AuthorizedDshHeadlessWorkerLauncher(
        dsh_bin=str(dsh_bin),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=authority,
        coordinator_instance_id="coordinator-1",
        release_id="R-1",
        state_root=str(tmp_path / "state"),
        command_runner=runner,
    )
    assignment = launcher.assign(
        agent_id="requirement-analysis",
        role="REQUIREMENT_ANALYZER",
        phase="REQUIREMENT_ANALYSIS",
        mission_id="MISSION-1",
        attempt_id="attempt-1",
        scope="REQ-1",
        input_refs=("file://README.md",),
        allowed_artifact_types=("rc7_requirement_candidate",),
        allowed_tools=(REQ_READ, REQ_TRUTH, "filesystem"),
    )
    return launcher, assignment, truth


def test_authorized_launcher_exports_exact_signed_lease_to_dsh(tmp_path: Path) -> None:
    captured = {}
    launcher, assignment, _truth = _launcher(tmp_path, REQ_READ, captured)
    invocation, output = launcher.execute(assignment, "analyze")

    assert invocation.result == "PASS"
    assert output == {"ok": True}
    exported = json.loads(captured["env"][ALLOWED_TOOLS_ENV])
    assert exported == [REQ_READ, REQ_TRUTH, "filesystem"]


def test_authorized_launcher_rejects_observed_unleased_generic_tool(tmp_path: Path) -> None:
    captured = {}
    launcher, assignment, truth = _launcher(tmp_path, "write", captured)

    with pytest.raises(AgentRuntimeError, match="LEASE_TOOL_AUTHORIZATION_FAILED"):
        launcher.execute(assignment, "analyze")

    event_names = [event["event_type"] for event in truth.store.iter_raw()]
    assert "ROUTING_INTEGRITY_FAIL" in event_names
    assert "HANDOFF_RETURNED" not in event_names
