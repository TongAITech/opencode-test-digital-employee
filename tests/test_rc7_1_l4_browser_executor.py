from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from rc7_release.browser_executor import BrowserExecutorError, execute_browser_action


def _helper(tmp_path: Path, *, exit_code: int = 0) -> Path:
    path = tmp_path / "browser_helper.py"
    path.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "print(json.dumps({'argv': sys.argv[1:], 'request': request}, sort_keys=True))\n"
        "raise SystemExit(%d)\n" % exit_code,
        encoding="utf-8",
    )
    return path


def _configure(monkeypatch, tmp_path: Path, helper: Path, *, target: str = "TARGET-L4", kind: str = "playwright") -> None:
    monkeypatch.setenv("PFC_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("PFC_BROWSER_CLIENT_BIN", sys.executable)
    monkeypatch.setenv("PFC_BROWSER_CLIENT_ARGS_JSON", json.dumps([str(helper), "--fixed-capability-arg"]))
    monkeypatch.setenv("PFC_BROWSER_TARGET_ID", target)
    monkeypatch.setenv("PFC_BROWSER_TOOL_KIND", kind)


def test_real_browser_process_is_target_bound_and_uses_stdin_json(monkeypatch, tmp_path: Path) -> None:
    helper = _helper(tmp_path)
    _configure(monkeypatch, tmp_path, helper)
    request = {"action": "navigate-and-assert", "url": "https://example.invalid/app", "assert": {"text": "ready"}}

    result = execute_browser_action(request=request, target_id="TARGET-L4")

    assert result["tool"] == "browser-skill"
    assert result["implementation"] == "playwright"
    assert result["target_id"] == "TARGET-L4"
    assert result["shell"] is False
    assert result["request_transport"] == "STDIN_JSON"
    assert result["client_args_persisted"] is False
    assert result["invocation_ref"].startswith("playwright://TARGET-L4/")
    observed = json.loads(result["stdout"]["text"])
    assert observed["argv"] == ["--fixed-capability-arg"]
    assert observed["request"] == request
    assert "navigate-and-assert" not in observed["argv"]


def test_browser_target_mismatch_fails_before_process(monkeypatch, tmp_path: Path) -> None:
    helper = _helper(tmp_path)
    _configure(monkeypatch, tmp_path, helper, target="TARGET-A")
    with pytest.raises(BrowserExecutorError, match="BROWSER_TARGET_MISMATCH"):
        execute_browser_action(request={"action": "navigate"}, target_id="TARGET-B")


def test_unadmitted_browser_implementation_fails_closed(monkeypatch, tmp_path: Path) -> None:
    helper = _helper(tmp_path)
    _configure(monkeypatch, tmp_path, helper, kind="generic-shell")
    with pytest.raises(BrowserExecutorError, match="BROWSER_TOOL_KIND_NOT_ADMITTED"):
        execute_browser_action(request={"action": "navigate"}, target_id="TARGET-L4")


def test_browser_nonzero_exit_never_returns_receipt(monkeypatch, tmp_path: Path) -> None:
    helper = _helper(tmp_path, exit_code=9)
    _configure(monkeypatch, tmp_path, helper, kind="browser-skill")
    with pytest.raises(BrowserExecutorError, match="BROWSER_CLIENT_EXIT_NONZERO"):
        execute_browser_action(request={"action": "navigate"}, target_id="TARGET-L4")
