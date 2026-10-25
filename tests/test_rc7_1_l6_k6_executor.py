from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from rc7_release.k6_executor import K6ExecutorError, execute_k6_scenario


TARGET = "target-bank-l6"


def _write_k6_helper(tmp_path: Path) -> Path:
    helper = tmp_path / "k6_helper.py"
    helper.write_text(
        "import json, pathlib, sys\n"
        "mode = sys.argv[1]\n"
        "args = sys.argv[2:]\n"
        "if 'run' not in args or '--summary-export' not in args:\n"
        "    print('bad command', file=sys.stderr); sys.exit(11)\n"
        "idx = args.index('--summary-export')\n"
        "summary_path = pathlib.Path(args[idx + 1])\n"
        "script_path = pathlib.Path(args[idx + 2])\n"
        "if not script_path.is_file():\n"
        "    print('script missing', file=sys.stderr); sys.exit(12)\n"
        "count = 0 if mode == 'no-iterations' else 3\n"
        "thresholds = {} if mode == 'no-thresholds' else {'p(95)<500': {'ok': mode != 'threshold-fail'}}\n"
        "summary = {'metrics': {\n"
        "  'iterations': {'type': 'counter', 'contains': 'default', 'values': {'count': count, 'rate': 1.0}},\n"
        "  'http_reqs': {'type': 'counter', 'contains': 'default', 'values': {'count': count, 'rate': 1.0}},\n"
        "  'http_req_duration': {'type': 'trend', 'contains': 'time', 'values': {'avg': 120.0, 'p(95)': 200.0}, 'thresholds': thresholds}\n"
        "}}\n"
        "summary_path.parent.mkdir(parents=True, exist_ok=True)\n"
        "summary_path.write_text(json.dumps(summary), encoding='utf-8')\n"
        "print('k6 helper completed')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    return helper


def _write_script(tmp_path: Path) -> Path:
    script = tmp_path / "perf.js"
    script.write_text("export default function () { /* controlled test */ }\n", encoding="utf-8")
    return script


def _configure(monkeypatch, tmp_path: Path, helper: Path, mode: str = "success", target: str = TARGET) -> None:
    monkeypatch.setenv("PFC_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(tmp_path / "runtime-state"))
    monkeypatch.setenv("PFC_K6_TARGET_ID", target)
    monkeypatch.setenv("PFC_K6_BIN", sys.executable)
    monkeypatch.setenv("PFC_K6_ARGS_JSON", json.dumps([str(helper), mode]))


def test_l6_executes_k6_cli_shape_and_requires_threshold_pass(tmp_path: Path, monkeypatch) -> None:
    helper = _write_k6_helper(tmp_path)
    script = _write_script(tmp_path)
    _configure(monkeypatch, tmp_path, helper)

    result = execute_k6_scenario(
        script_path=str(script),
        scenario_id="publish-load",
        target_id=TARGET,
        timeout_seconds=10,
    )

    assert result["tool"] == "k6"
    assert result["implementation"] == "k6-cli"
    assert result["target_id"] == TARGET
    assert result["scenario_id"] == "publish-load"
    assert result["summary_exported"] is True
    assert result["summary"]["iteration_count"] == 3
    assert result["summary"]["threshold_count"] == 1
    assert result["summary"]["thresholds"][0]["ok"] is True
    assert result["shell"] is False
    assert result["invocation_ref"].startswith("k6://%s/publish-load/" % TARGET)


def test_l6_rejects_zero_iterations_even_when_process_exits_zero(tmp_path: Path, monkeypatch) -> None:
    helper = _write_k6_helper(tmp_path)
    script = _write_script(tmp_path)
    _configure(monkeypatch, tmp_path, helper, mode="no-iterations")

    with pytest.raises(K6ExecutorError, match="K6_NO_ITERATIONS_EXECUTED"):
        execute_k6_scenario(script_path=str(script), scenario_id="publish-load", target_id=TARGET, timeout_seconds=10)


def test_l6_rejects_missing_threshold_evaluation(tmp_path: Path, monkeypatch) -> None:
    helper = _write_k6_helper(tmp_path)
    script = _write_script(tmp_path)
    _configure(monkeypatch, tmp_path, helper, mode="no-thresholds")

    with pytest.raises(K6ExecutorError, match="K6_THRESHOLD_EVALUATION_REQUIRED"):
        execute_k6_scenario(script_path=str(script), scenario_id="publish-load", target_id=TARGET, timeout_seconds=10)


def test_l6_rejects_failed_threshold_even_when_process_exits_zero(tmp_path: Path, monkeypatch) -> None:
    helper = _write_k6_helper(tmp_path)
    script = _write_script(tmp_path)
    _configure(monkeypatch, tmp_path, helper, mode="threshold-fail")

    with pytest.raises(K6ExecutorError, match="K6_THRESHOLD_NOT_PASS"):
        execute_k6_scenario(script_path=str(script), scenario_id="publish-load", target_id=TARGET, timeout_seconds=10)


def test_l6_rejects_target_mismatch_before_execution(tmp_path: Path, monkeypatch) -> None:
    helper = _write_k6_helper(tmp_path)
    script = _write_script(tmp_path)
    _configure(monkeypatch, tmp_path, helper, target="different-target")

    with pytest.raises(K6ExecutorError, match="K6_TARGET_MISMATCH"):
        execute_k6_scenario(script_path=str(script), scenario_id="publish-load", target_id=TARGET, timeout_seconds=10)


def test_l6_rejects_script_outside_workspace(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    helper = _write_k6_helper(workspace)
    outside = tmp_path / "outside.js"
    outside.write_text("export default function () {}\n", encoding="utf-8")
    _configure(monkeypatch, workspace, helper)

    with pytest.raises(K6ExecutorError, match="K6_SCRIPT_PATH_ESCAPE"):
        execute_k6_scenario(script_path=str(outside), scenario_id="publish-load", target_id=TARGET, timeout_seconds=10)
