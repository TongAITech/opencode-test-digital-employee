from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from rc7_release.code_qualification import (
    CODEGRAPH_QUERY_TOOL,
    GIT_DIFF_TOOL,
    _code_objective,
    _parse_query_args,
    _reviewer_guidance,
    run_real_code_qualification,
)


def test_code_qualification_without_dsh_is_not_proven(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.delenv("PFC_DSH_BIN", raising=False)
    monkeypatch.setenv("PATH", "")

    result = run_real_code_qualification(
        state_root=str(tmp_path / "state"),
        workspace=str(workspace),
        repo_path=".",
        base_ref="base",
        head_ref="head",
        target_id="cfg-data",
        codegraph_args=["search", "RateService", "--json"],
        dsh_bin=None,
        timeout_seconds=1,
    )

    assert result.status == "NOT_PROVEN"
    assert result.reason == "DSH_NOT_AVAILABLE"
    payload = json.loads(
        (tmp_path / "state" / "qualification" / "rc7-dsh-code-result.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "NOT_PROVEN"


def test_code_qualification_requires_explicit_query_and_target_contract(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    missing_query = run_real_code_qualification(
        state_root=str(tmp_path / "state-query"),
        workspace=str(workspace),
        repo_path=".",
        base_ref="base",
        head_ref="head",
        target_id="cfg-data",
        codegraph_args=None,
        dsh_bin="dsh",
    )
    assert missing_query.status == "NOT_PROVEN"
    assert missing_query.reason == "CODEGRAPH_QUERY_ARGS_REQUIRED"

    missing_target = run_real_code_qualification(
        state_root=str(tmp_path / "state-target"),
        workspace=str(workspace),
        repo_path=".",
        base_ref="",
        head_ref="head",
        target_id="cfg-data",
        codegraph_args=["search", "RateService"],
        dsh_bin="dsh",
    )
    assert missing_target.status == "NOT_PROVEN"
    assert missing_target.reason == "CODE_TARGET_AND_REVISIONS_REQUIRED"


def test_code_qualification_missing_workspace_is_not_proven(tmp_path) -> None:
    result = run_real_code_qualification(
        state_root=str(tmp_path / "state"),
        workspace=str(tmp_path / "does-not-exist"),
        repo_path="cfg-data",
        base_ref="base",
        head_ref="head",
        target_id="cfg-data",
        codegraph_args=["search", "RateService"],
        dsh_bin="dsh",
    )
    assert result.status == "NOT_PROVEN"
    assert result.reason == "WORKSPACE_NOT_FOUND"


def _make_git_repo(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("git is not available")
    workspace = tmp_path / "workspace"
    repo = workspace / "cfg-data"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "rc7@example.invalid"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "RC7 Test"], cwd=str(repo), check=True)
    path = repo / "RateService.java"
    path.write_text("class RateService { int x = 1; }\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=str(repo), check=True, capture_output=True, text=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, capture_output=True, text=True).stdout.strip()
    path.write_text("class RateService { int x = 2; }\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "head"], cwd=str(repo), check=True, capture_output=True, text=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, capture_output=True, text=True).stdout.strip()
    monkeypatch.setenv("PFC_WORKSPACE", str(workspace))
    return workspace, base, head


def test_code_qualification_missing_codegraph_binary_is_not_proven(tmp_path, monkeypatch) -> None:
    workspace, base, head = _make_git_repo(tmp_path, monkeypatch)
    monkeypatch.delenv("PFC_CODEGRAPH_BIN", raising=False)
    result = run_real_code_qualification(
        state_root=str(tmp_path / "state"),
        workspace=str(workspace),
        repo_path="cfg-data",
        base_ref=base,
        head_ref=head,
        target_id="cfg-data",
        codegraph_args=["search", "RateService", "--json"],
        dsh_bin=str(Path(__file__).resolve()),
        timeout_seconds=1,
    )
    assert result.status == "NOT_PROVEN"
    assert result.reason.startswith("PROFESSIONAL_TOOL_PREREQUISITE_NOT_PROVEN:PFC_CODEGRAPH_BIN_NOT_CONFIGURED")


def test_code_qualification_prompts_require_real_rc7_professional_tools() -> None:
    args = ["callers", "RateService.adjustRate", "--depth", "2", "--json"]
    objective = _code_objective(
        repo_path="cfg-data",
        base_ref="origin/master",
        head_ref="HEAD",
        target_id="cfg-data",
        codegraph_args=args,
    )
    assert GIT_DIFF_TOOL in objective
    assert CODEGRAPH_QUERY_TOOL in objective
    assert "capability_record_call" in objective
    assert "Do not replace" in objective

    guidance = json.loads(
        _reviewer_guidance(
            repo_path="cfg-data",
            base_ref="origin/master",
            head_ref="HEAD",
            codegraph_args=args,
        )
    )
    assert [item["tool"] for item in guidance["must_call"]] == [GIT_DIFF_TOOL, CODEGRAPH_QUERY_TOOL]
    assert guidance["must_call"][1]["arguments"]["args"] == args


def test_codegraph_query_args_cli_contract_is_strict_json_string_array() -> None:
    assert _parse_query_args('["search","RateService","--json"]') == ["search", "RateService", "--json"]
    assert _parse_query_args(None) is None
    with pytest.raises(ValueError, match="STRING_ARRAY"):
        _parse_query_args('{"query":"RateService"}')
    with pytest.raises(ValueError, match="STRING_ARRAY"):
        _parse_query_args('["search", 1]')
