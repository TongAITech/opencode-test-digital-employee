from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from rc6_runtime.authority import AuthorityRuntime
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.worker_contract import (
    RC7SkillBoundWorkerLauncher,
    RC7WorkerContractError,
    is_provider_backpressure,
    worker_parallelism,
)


def _launcher(tmp_path: Path, monkeypatch, *, include_skill: bool):
    dsh = tmp_path / "dsh"
    patch = tmp_path / "rc7.patch.yml"
    dsh.write_text("stub", encoding="utf-8")
    patch.write_text("stub", encoding="utf-8")
    truth = TruthRuntime(tmp_path / "r1.jsonl")

    def runner(command, **kwargs):
        prompt = command[-1]
        assert "pfc-requirement-analysis" in prompt
        rows = [{"type": "session", "session_id": "session-worker-rc7"}]
        if include_skill:
            rows.append(
                {
                    "type": "tool_call",
                    "tool_name": "skill",
                    "arguments": {"name": "pfc-requirement-analysis"},
                }
            )
            rows.append({"type": "tool_result", "tool_name": "skill", "ok": True})
        rows.extend(
            [
                {"type": "tool_call", "tool_name": "mcp__pfc_aitest_rc7__runtime_status"},
                {"type": "tool_result", "tool_name": "mcp__pfc_aitest_rc7__runtime_status", "ok": True},
                {"type": "final", "text": json.dumps({"qualification_payload": {"result": "ok"}})},
            ]
        )
        stdout = "\n".join(json.dumps(row) for row in rows)
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    launcher = RC7SkillBoundWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=AuthorityRuntime(b"0123456789abcdef-rc7-worker"),
        coordinator_instance_id="coord-rc7",
        release_id="R-7",
        state_root=str(tmp_path / "state"),
        command_runner=runner,
    )
    assignment = launcher.assign(
        agent_id="pfc-requirement-analysis",
        role="REQUIREMENT_ANALYZER",
        phase="REQUIREMENT_ANALYSIS",
        mission_id="M-7",
        attempt_id="A-1",
        scope="REQ-1",
        input_refs=("source://1",),
        allowed_artifact_types=("requirement_analysis",),
        allowed_tools=("skill", "mcp__pfc_aitest_rc7__runtime_status"),
    )
    return launcher, assignment, truth


def test_skill_bound_worker_proves_real_skill_tool_call_before_handoff(tmp_path, monkeypatch) -> None:
    launcher, assignment, truth = _launcher(tmp_path, monkeypatch, include_skill=True)
    invocation, output = launcher.execute(assignment, "analyze")
    assert output == {"result": "ok"}
    assert invocation.result == "PASS"
    handoff = [row for row in truth.store.iter_raw() if row["event_type"] == "HANDOFF_RETURNED"][-1]
    assert handoff["payload"]["required_skill"] == "pfc-requirement-analysis"
    assert handoff["payload"]["skill_tool_call_proven"] is True


def test_skill_bound_worker_fails_closed_if_model_skips_skill_tool(tmp_path, monkeypatch) -> None:
    launcher, assignment, truth = _launcher(tmp_path, monkeypatch, include_skill=False)
    with pytest.raises(RC7WorkerContractError, match="REQUIRED_WORKER_SKILL_TOOL_CALL_MISSING"):
        launcher.execute(assignment, "analyze")
    names = [row["event_type"] for row in truth.store.iter_raw()]
    assert "ROUTING_INTEGRITY_FAIL" in names
    assert "HANDOFF_RETURNED" not in names


def test_bank_worker_parallelism_defaults_to_one_and_detects_429(monkeypatch) -> None:
    monkeypatch.delenv("PFC_RC7_WORKER_MAX_PARALLEL", raising=False)
    assert worker_parallelism() == 1
    monkeypatch.setenv("PFC_RC7_WORKER_MAX_PARALLEL", "2")
    assert worker_parallelism() == 2
    assert is_provider_backpressure("HTTP 429 QUOTA_EXCEEDED BadRequester") is True
    assert is_provider_backpressure("completed") is False
