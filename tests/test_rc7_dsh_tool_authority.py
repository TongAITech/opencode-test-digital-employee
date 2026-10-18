from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from rc6_runtime.agent_runtime import AgentRuntimeError
from rc6_runtime.truth import TruthRuntime
from rc7_release import dsh
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.authorized_dsh_launcher import (
    ALLOWED_TOOLS_ENV,
    Rc7AuthorizedDshHeadlessWorkerLauncher,
)
from rc7_runtime.dsh_worker_bridge import DshTaskWorkerBridge
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
    assert "scope.tools.guard" in source
    assert "system-prompt/assemble" in source
    assert "scope.tools.schemas(agent)" in source
    assert "RC7_DSH_REQUIRED_TOOL_NOT_REGISTERED" in source
    assert "PFC_RC7_DSH_ALLOWED_TOOLS" in source
    assert "capabilityAliases.has(tool)" in source
    assert "return []" in source
    assert "first assistant action MUST be one native structured call" in source
    assert "Do not emit planning, reasoning, or narration before that first call" in source
    assert "name: './rc7-tool-policy.ts'" in text
    assert "rc7_release.mcp_server_authorized" in text
    assert "rc7_release.mcp_server_field" not in text
    assert "reconnect:" in text
    assert "enabled: false" in text


def test_headless_profile_requires_immediate_native_tool_action() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "validation/dsh/rc7-headless-minimal.patch.yml").read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "Do not narrate reasoning, planning, or intended tool use" in normalized
    assert "first assistant action MUST be a native structured call" in normalized
    assert "emit no prose before that call" in normalized


def test_worker_first_action_compiles_exact_leased_read_and_input_path() -> None:
    task = SimpleNamespace(
        input_artifact_refs=(
            "file://validation/agiletc_fixture/project/README.md",
            "file://validation/agiletc_fixture/docs/requirements.md",
        )
    )
    assignment = SimpleNamespace(allowed_tools=(REQ_READ, REQ_TRUTH))

    directive = DshTaskWorkerBridge.first_action_directive(task, assignment)

    assert directive.startswith("MANDATORY_FIRST_ACTION=")
    first_line = directive.splitlines()[0]
    action = json.loads(first_line.split("=", 1)[1])
    assert action == {
        "tool": REQ_READ,
        "arguments": {"path": "validation/agiletc_fixture/project/README.md"},
    }
    assert "Before any assistant prose, emit this exact native structured tool call" in directive
    assert "Do not explain, plan, restate, or simulate it" in directive


def test_worker_first_action_never_widens_lease_or_invents_source() -> None:
    task = SimpleNamespace(input_artifact_refs=("file://validation/input.md",))
    no_read = SimpleNamespace(allowed_tools=(REQ_TRUTH, CODE_DIFF))
    no_file = SimpleNamespace(input_artifact_refs=("artifact://ART-1",))
    read_assignment = SimpleNamespace(allowed_tools=(REQ_READ, REQ_TRUTH))

    assert DshTaskWorkerBridge.first_action_directive(task, no_read) == ""
    assert DshTaskWorkerBridge.first_action_directive(no_file, read_assignment) == ""


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


def _launcher(tmp_path: Path, tool_name: str | None, captured: dict):
    dsh_bin = tmp_path / "dsh"
    dsh_bin.write_text("stub", encoding="utf-8")
    patch = tmp_path / "patch.yml"
    patch.write_text("stub", encoding="utf-8")
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    authority = RC7AuthorityRuntime(b"0123456789abcdef-rc7-tool-authority")

    def runner(command, **kwargs):
        captured["env"] = dict(kwargs.get("env") or {})
        rows = [
            {"type": "session", "sessionId": "session-rc7-authority"},
        ]
        if tool_name is not None:
            rows.extend(
                [
                    {"type": "tool_call", "tool": tool_name, "callId": "call-1"},
                    {"type": "tool_result", "callId": "call-1", "status": "success"},
                    {"type": "final", "text": json.dumps({"ok": True})},
                ]
            )
        else:
            rows.extend(
                [
                    {
                        "type": "text",
                        "text": "I should call the read tool next, but this is only narration.",
                    },
                    {
                        "type": "status",
                        "phase": "step_end",
                        "reason": {"kind": "max-tokens"},
                    },
                    {"type": "final", "text": json.dumps({"ok": True})},
                ]
            )
        stdout = "\n".join(json.dumps(row) for row in rows)
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
        role="RC7_REQUIREMENT_WORKER",
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


def test_authorized_launcher_rejects_text_only_max_tokens_as_tool_call(tmp_path: Path) -> None:
    captured = {}
    launcher, assignment, truth = _launcher(tmp_path, None, captured)

    with pytest.raises(AgentRuntimeError, match="REAL_TOOL_CALL_MISSING"):
        launcher.execute(assignment, "analyze")

    rows = list(truth.store.iter_raw())
    event_names = [row["event_type"] for row in rows]
    serialized = json.dumps(rows, sort_keys=True)
    assert "REAL_TOOL_CALL_MISSING" in serialized
    assert "WORKER_TOOL_CALLED" not in event_names
    assert "HANDOFF_RETURNED" not in event_names


def test_authorized_launcher_persists_partial_output_when_dsh_times_out(tmp_path: Path) -> None:
    dsh_bin = tmp_path / "dsh"
    dsh_bin.write_text("stub", encoding="utf-8")
    patch = tmp_path / "patch.yml"
    patch.write_text("stub", encoding="utf-8")
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    authority = RC7AuthorityRuntime(b"0123456789abcdef-rc7-timeout-evidence")
    partial = "\n".join(
        [
            json.dumps({"type": "session", "sessionId": "session-timeout-partial"}),
            json.dumps({"type": "thinking", "text": "still reasoning"}),
            json.dumps({"type": "tool_call", "tool": REQ_READ, "callId": "partial-call"}),
        ]
    )

    def timeout_runner(command, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=7,
            output=partial.encode("utf-8"),
            stderr=b"partial stderr",
        )

    launcher = Rc7AuthorizedDshHeadlessWorkerLauncher(
        dsh_bin=str(dsh_bin),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=authority,
        coordinator_instance_id="coordinator-timeout",
        release_id="R-TIMEOUT",
        state_root=str(tmp_path / "state"),
        timeout_seconds=7,
        command_runner=timeout_runner,
    )
    assignment = launcher.assign(
        agent_id="requirement-analysis",
        role="RC7_REQUIREMENT_WORKER",
        phase="REQUIREMENT_ANALYSIS",
        mission_id="MISSION-TIMEOUT",
        attempt_id="attempt-timeout",
        scope="REQ-TIMEOUT",
        input_refs=("file://README.md",),
        allowed_artifact_types=("rc7_requirement_candidate",),
        allowed_tools=(REQ_READ, REQ_TRUTH),
    )

    with pytest.raises(AgentRuntimeError, match="DSH_LAUNCH_FAILED"):
        launcher.execute(assignment, "analyze")

    raw_path = (
        tmp_path
        / "state"
        / "worker-evidence"
        / "MISSION-TIMEOUT"
        / (assignment.assignment_id + ".jsonl")
    )
    assert raw_path.is_file()
    raw = raw_path.read_text(encoding="utf-8")
    assert "session-timeout-partial" in raw
    assert "partial-call" in raw
    assert "partial stderr" in raw

    rows = list(truth.store.iter_raw())
    serialized = json.dumps(rows, sort_keys=True)
    assert "DSH_WORKER_TIMEOUT_PARTIAL" in serialized
    assert '"partial_tool_call_count": 1' in serialized
    assert "session-timeout-partial" in serialized

    event_names = [row["event_type"] for row in rows]
    assert "WORKER_TOOL_CALLED" not in event_names
    assert "HANDOFF_RETURNED" not in event_names
