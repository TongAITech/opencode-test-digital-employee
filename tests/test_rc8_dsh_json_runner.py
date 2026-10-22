from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rc8_node.dsh_json_runner import DshJsonRunner, DshJsonRunnerError


def _event_stream(session_id: str = "session-1", *, with_tool: bool = True, with_output: bool = True) -> str:
    events = [{"type": "session", "session_id": session_id}]
    if with_tool:
        events.append({"type": "tool_call", "tool_name": "read", "path": "requirements/REQ.md"})
    if with_output:
        events.append({"type": "final", "text": json.dumps({"atomic_statements": ["A"], "evidence_refs": ["source:1"]})})
    return "\n".join(json.dumps(item) for item in events) + "\n"


def _runner(tmp_path: Path, command_runner):
    dsh = tmp_path / "dsh"
    dsh.write_text("stub", encoding="utf-8")
    patch = tmp_path / "patch.json"
    patch.write_text("{}", encoding="utf-8")
    return DshJsonRunner(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        timeout_seconds=30,
        command_runner=command_runner,
    )


def test_runner_uses_exact_headless_json_protocol_and_returns_validated_result(tmp_path: Path) -> None:
    captured = {}

    def command_runner(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=_event_stream(), stderr="")

    runner = _runner(tmp_path, command_runner)
    result = runner.run("analyze requirement")
    assert captured["command"] == [
        str(tmp_path / "dsh"),
        "--profile", "headless",
        "--patch", str(tmp_path / "patch.json"),
        "--json",
        "analyze requirement",
    ]
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["check"] is False
    assert result.session_id == "session-1"
    assert result.tool_calls[0]["tool_name"] == "read"
    assert result.output["atomic_statements"] == ["A"]
    assert result.exit_code == 0


def test_runner_rejects_reused_session(tmp_path: Path) -> None:
    def command_runner(_command, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=_event_stream("session-same"), stderr="")

    runner = _runner(tmp_path, command_runner)
    runner.run("first")
    with pytest.raises(DshJsonRunnerError, match="WORKER_SESSION_NOT_INDEPENDENT"):
        runner.run("second")


def test_runner_requires_real_tool_call(tmp_path: Path) -> None:
    def command_runner(_command, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=_event_stream(with_tool=False), stderr="")

    with pytest.raises(DshJsonRunnerError, match="REAL_TOOL_CALL_MISSING"):
        _runner(tmp_path, command_runner).run("analyze")


def test_runner_requires_strict_final_json(tmp_path: Path) -> None:
    def command_runner(_command, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=_event_stream(with_output=False), stderr="")

    with pytest.raises(DshJsonRunnerError, match="STRICT_JSON_OUTPUT_MISSING"):
        _runner(tmp_path, command_runner).run("analyze")


def test_runner_rejects_nonzero_process_even_with_structured_output(tmp_path: Path) -> None:
    def command_runner(_command, **_kwargs):
        return SimpleNamespace(returncode=9, stdout=_event_stream(), stderr="boom")

    with pytest.raises(DshJsonRunnerError, match="WORKER_PROCESS_FAILED") as captured:
        _runner(tmp_path, command_runner).run("analyze")
    assert captured.value.exit_code == 9
    assert captured.value.stderr == "boom"


def test_runner_is_truth_neutral() -> None:
    source = Path(__file__).resolve().parents[1] / "rc8_node" / "dsh_json_runner.py"
    text = source.read_text(encoding="utf-8")
    assert "CentralR1RuntimeLedger" not in text
    assert "rc7_runtime" not in text
    assert "truth.append" not in text
