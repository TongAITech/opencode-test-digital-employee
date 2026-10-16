from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_release import mcp_server
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.mission_conformance import MissionConformanceChecker
from rc7_runtime.models import Evaluation, EvaluationResult, Mission, Task, TaskStatus
from rc7_runtime.node_tool_conformance import (
    NODE_TOOL_CALL_KIND,
    NodeToolConformanceChecker,
    NodeToolConformanceError,
    contract_enabled,
    persist_contract,
    record_successful_call,
)
from rc7_runtime.truth_overlay import append_entity


RELEASE = "REL-NODE-TOOLS"
MISSION = "MISSION-NODE-TOOLS"
WORKER = "WORKER-CODE-001"


def _code_task(*, state: TaskStatus = TaskStatus.RUNNING, worker: str = WORKER) -> Task:
    return Task(
        task_id="TASK-CODE",
        mission_id=MISSION,
        node="CODE_ANALYSIS",
        task_type="PRODUCE",
        objective="Analyze actual changed code",
        state=state,
        required_capabilities=["code_reasoning", "code_reality"],
        lease_owner=worker,
    )


def _seed_code_task(r1: Path) -> TruthRuntime:
    truth = TruthRuntime(r1)
    append_entity(
        truth,
        Mission(mission_id=MISSION, release_id=RELEASE, goal="prove node tool calls"),
        release_id=RELEASE,
        artifact_version=1,
    )
    append_entity(truth, _code_task(), release_id=RELEASE, artifact_version=1)
    persist_contract(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        task_ids=["TASK-CODE"],
    )
    return truth


def test_code_analysis_requires_real_durable_tool_calls(tmp_path: Path) -> None:
    truth = _seed_code_task(tmp_path / "r1.jsonl")
    checker = NodeToolConformanceChecker(truth)
    initial = checker.check_task(MISSION, "TASK-CODE")
    assert initial.status == "FAIL"
    assert set(initial.missing_capabilities) == {
        "SOURCE_REVISION_READ",
        "SOURCE_DIFF",
        "CODEGRAPH_DISCOVERY",
        "CODEGRAPH_QUERY",
    }

    for tool in ("git_show_revision", "git_diff", "codegraph_mcp_tools", "codegraph_mcp_call"):
        record_successful_call(
            truth,
            mission_id=MISSION,
            task_id="TASK-CODE",
            worker_id=WORKER,
            tool_name=tool,
            result={"tool": tool, "status": "PASS"},
        )

    result = checker.check_task(MISSION, "TASK-CODE")
    assert result.status == "PASS"
    assert not result.missing_capabilities
    assert set(result.observed_tools) == {
        "git_show_revision",
        "git_diff",
        "codegraph_mcp_tools",
        "codegraph_mcp_call",
    }
    evidence = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == NODE_TOOL_CALL_KIND
    ]
    assert len(evidence) == 4


def test_tool_call_evidence_rejects_wrong_worker(tmp_path: Path) -> None:
    truth = _seed_code_task(tmp_path / "r1.jsonl")
    with pytest.raises(NodeToolConformanceError, match="NODE_TOOL_CALL_WORKER_NOT_TASK_OWNER"):
        record_successful_call(
            truth,
            mission_id=MISSION,
            task_id="TASK-CODE",
            worker_id="OTHER-WORKER",
            tool_name="git_diff",
            result={"status": "PASS"},
        )


def test_new_bank_v2_mission_persists_node_tool_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "b" * 40)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    result = start_or_resume(
        r1_path=str(r1),
        mission_id="BANK-NODE-TOOLS",
        release_id="REL-BANK",
        goal="real bank mission tool conformance",
    )
    assert result["graph_version"] == "v2"
    assert result["node_tool_contract_enabled"] is True
    truth = TruthRuntime(r1)
    assert contract_enabled(truth, "BANK-NODE-TOOLS") is True


def test_mcp_successful_call_auto_records_r1_evidence(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("PFC_AITEST_HOME", str(tmp_path))
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(state))
    truth = _seed_code_task(state / "r1" / "event-stream.jsonl")
    monkeypatch.setattr(
        mcp_server,
        "git_show_revision",
        lambda **kwargs: {"tool": "git_show_revision", "revision": "a" * 40},
    )
    response = mcp_server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "git_show_revision",
                "arguments": {
                    "repo_path": ".",
                    "mission_context": {
                        "mission_id": MISSION,
                        "task_id": "TASK-CODE",
                        "worker_id": WORKER,
                    },
                },
            },
        }
    )
    assert response["result"].get("isError") is not True
    rows = [
        row for row in TruthRuntime(state / "r1" / "event-stream.jsonl").query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == NODE_TOOL_CALL_KIND
    ]
    assert len(rows) == 1
    assert rows[0]["source_ref"].endswith("/git_show_revision")


def test_mission_conformance_fails_closed_for_pass_without_required_tool_calls(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "c" * 40)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id="BANK-CONFORMANCE",
        release_id="REL-C",
        goal="fail closed on fake pass",
    )
    truth = TruthRuntime(r1)
    row = [
        item for item in truth.query("rc7_task", mission_id="BANK-CONFORMANCE")
        if item.get("node") == "CODE_ANALYSIS"
    ][0]
    evaluation = Evaluation(
        evaluation_id="EVAL-CODE-FAKE-PASS",
        mission_id="BANK-CONFORMANCE",
        node="CODE_ANALYSIS",
        artifact_refs=[],
        result=EvaluationResult.PASS,
        evaluator_ref="AUTHORITY-CODE",
    )
    append_entity(truth, evaluation, release_id="REL-C", artifact_version=1)
    fake_pass = Task(
        task_id=str(row["task_id"]),
        mission_id="BANK-CONFORMANCE",
        node="CODE_ANALYSIS",
        task_type="PRODUCE",
        objective=str(row["objective"]),
        state=TaskStatus.PASS,
        required_capabilities=list(row.get("required_capabilities") or []),
        dependency_task_ids=list(row.get("dependency_task_ids") or []),
        input_artifact_refs=list(row.get("input_artifact_refs") or []),
        gap_refs=list(row.get("gap_refs") or []),
        acceptance_criteria=list(row.get("acceptance_criteria") or []),
        priority=int(row.get("priority", 100)),
        lease_owner=None,
        output_artifact_refs=[],
        evaluation_id=evaluation.evaluation_id,
    )
    append_entity(truth, fake_pass, release_id="REL-C", artifact_version=int(row["artifact_version"]) + 1)
    result = MissionConformanceChecker(truth).check("BANK-CONFORMANCE")
    assert result.status == "FAIL"
    assert any(
        item.startswith("NODE_TOOL_CONFORMANCE_FAILED:CODE_ANALYSIS:")
        for item in result.violations
    )
