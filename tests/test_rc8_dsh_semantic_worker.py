from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from rc8_node.dsh_semantic_worker import DshSemanticWorker, DshSemanticWorkerError


READ_TOOL = "mcp__pfc_aitest_rc7__read_text"


def _request(tmp_path: Path) -> Path:
    path = tmp_path / "semantic-request.json"
    path.write_text(json.dumps({"allowed_evidence_refs": ["snapshot:abc"]}), encoding="utf-8")
    return path


def _events(*, include_result: bool = True, evidence_ref: str = "snapshot:abc") -> bytes:
    semantic = {
        "summary": "impact summary",
        "changes": [],
        "impact_chains": [],
        "risks": [],
        "test_impacts": [],
        "unknowns": [],
        "claims": [{"claim": "snapshot is analyzed", "evidence_refs": [evidence_ref]}],
        "sufficiency": {"state": "PASS", "reason": "evidence covered"},
    }
    rows = [
        {"type": "session", "sessionID": "session-ci-semantic-1"},
        {"type": "tool_call", "tool_name": READ_TOOL, "tool_call_id": "call-read-1"},
    ]
    if include_result:
        rows.append({"type": "tool_result", "tool_call_id": "call-read-1", "result": {"ok": True}})
    rows.append(
        {
            "type": "assistant",
            "text": "[PFC_STAGE:code-analysis-semantic]\n[PFC_ASSERTION:code-analysis-semantic]\n" + json.dumps(semantic),
        }
    )
    return ("\n".join(json.dumps(row) for row in rows) + "\n").encode("utf-8")


def test_real_dsh_contract_requires_session_read_call_result_markers_and_json(tmp_path: Path) -> None:
    request = _request(tmp_path)

    def runner(command, **kwargs):
        assert command[:3] == ["dsh-ci-double", "--profile", "headless"]
        assert "--json" in command
        return subprocess.CompletedProcess(command, 0, stdout=_events(), stderr=b"")

    worker = DshSemanticWorker(
        str(tmp_path),
        dsh_command="dsh-ci-double",
        timeout_seconds=60,
        command_runner=runner,
    )
    result = worker.execute(request_path=str(request))
    assert result.state == "PASS"
    assert result.classification == "DSH_SEMANTIC_WORKER_VERIFIED"
    assert result.session_id == "session-ci-semantic-1"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool_name"] == READ_TOOL
    assert len(result.tool_results) == 1
    assert result.semantic_analysis["sufficiency"]["state"] == "PASS"
    assert Path(result.raw_jsonl_path).is_file()
    assert Path(result.provenance_path).is_file()


def test_dsh_contract_rejects_tool_call_without_result(tmp_path: Path) -> None:
    request = _request(tmp_path)

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=_events(include_result=False), stderr=b"")

    worker = DshSemanticWorker(
        str(tmp_path),
        dsh_command="dsh-ci-double",
        timeout_seconds=60,
        command_runner=runner,
    )
    with pytest.raises(DshSemanticWorkerError, match="DSH_SEMANTIC_TOOL_RESULT_MISSING"):
        worker.execute(request_path=str(request))


def test_dsh_contract_rejects_missing_required_read_tool(tmp_path: Path) -> None:
    request = _request(tmp_path)
    rows = [
        {"type": "session", "sessionID": "session-ci-semantic-2"},
        {"type": "tool_call", "tool_name": "SomeOtherTool", "tool_call_id": "call-1"},
        {"type": "tool_result", "tool_call_id": "call-1", "result": {"ok": True}},
        {"type": "assistant", "text": "[PFC_STAGE:code-analysis-semantic]\n[PFC_ASSERTION:code-analysis-semantic]\n{}"},
    ]

    def runner(command, **kwargs):
        stdout = ("\n".join(json.dumps(row) for row in rows) + "\n").encode("utf-8")
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    worker = DshSemanticWorker(str(tmp_path), dsh_command="dsh-ci-double", timeout_seconds=60, command_runner=runner)
    with pytest.raises(DshSemanticWorkerError, match="DSH_SEMANTIC_REQUEST_READ_TOOL_MISSING"):
        worker.execute(request_path=str(request))
