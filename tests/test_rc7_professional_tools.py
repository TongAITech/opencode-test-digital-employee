from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from rc7_release.dsh import write_patch
from rc7_release.mcp_server import handle
from rc7_release.professional_tools import (
    ProfessionalToolError,
    codegraph_probe,
    codegraph_query,
    git_diff,
    git_show_revision,
)


def _run(command, cwd):
    subprocess.run(command, cwd=str(cwd), check=True, capture_output=True, text=True)


def _git_repo(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("git is not available")
    workspace = tmp_path / "workspace"
    repo = workspace / "cfg-data"
    repo.mkdir(parents=True)
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "rc7@example.invalid"], repo)
    _run(["git", "config", "user.name", "RC7 Test"], repo)
    target = repo / "RateService.java"
    target.write_text("class RateService { int limit = 1; }\n", encoding="utf-8")
    _run(["git", "add", "RateService.java"], repo)
    _run(["git", "commit", "-m", "base"], repo)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, capture_output=True, text=True).stdout.strip()
    target.write_text("class RateService { int limit = 2; }\n", encoding="utf-8")
    _run(["git", "add", "RateService.java"], repo)
    _run(["git", "commit", "-m", "head"], repo)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, capture_output=True, text=True).stdout.strip()
    monkeypatch.setenv("PFC_WORKSPACE", str(workspace))
    monkeypatch.delenv("PFC_GIT_BIN", raising=False)
    return workspace, repo, base, head


def test_git_professional_tools_execute_real_read_only_git(tmp_path, monkeypatch) -> None:
    _workspace, _repo, base, head = _git_repo(tmp_path, monkeypatch)

    revision = git_show_revision(repo_path="cfg-data", ref="HEAD")
    assert revision["revision"] == head
    assert revision["subject"] == "head"

    result = git_diff(
        repo_path="cfg-data",
        base_ref=base,
        head_ref=head,
        paths=["RateService.java"],
    )
    assert result["base_revision"] == base
    assert result["head_revision"] == head
    assert result["changed_files"] == ["RateService.java"]
    assert "limit = 1" in result["diff"]["text"]
    assert "limit = 2" in result["diff"]["text"]
    assert result["diff"]["sha256"]


def test_git_adapter_rejects_workspace_escape_and_option_injection(tmp_path, monkeypatch) -> None:
    _workspace, _repo, base, head = _git_repo(tmp_path, monkeypatch)
    with pytest.raises(ProfessionalToolError, match="REPO_PATH_ESCAPES_WORKSPACE"):
        git_diff(repo_path="../outside", base_ref=base, head_ref=head)
    with pytest.raises(ProfessionalToolError, match="BASE_REF_INVALID"):
        git_diff(repo_path="cfg-data", base_ref="--output=/tmp/x", head_ref=head)
    with pytest.raises(ProfessionalToolError, match="GIT_PATH_ESCAPES_REPOSITORY"):
        git_diff(repo_path="cfg-data", base_ref=base, head_ref=head, paths=["../secret"])


def _fake_codegraph(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    body = (
        "import json, sys\n"
        "if sys.argv[1:] == ['--help']:\n"
        "    print('fake codegraph: query search symbol callers callees references impact')\n"
        "    raise SystemExit(0)\n"
        "print(json.dumps({'args': sys.argv[1:], 'kind': 'query-result'}, sort_keys=True))\n"
    )
    if os.name == "nt":
        helper = tmp_path / "fake-codegraph.py"
        helper.write_text(body, encoding="utf-8")
        script = tmp_path / "fake-codegraph.cmd"
        script.write_text(
            '@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, helper),
            encoding="utf-8",
        )
    else:
        script = tmp_path / "fake-codegraph"
        script.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
        script.chmod(0o755)
    monkeypatch.setenv("PFC_WORKSPACE", str(workspace))
    monkeypatch.setenv("PFC_CODEGRAPH_BIN", str(script))
    return workspace, script


def test_codegraph_adapter_probes_and_executes_allowlisted_query(tmp_path, monkeypatch) -> None:
    _workspace, script = _fake_codegraph(tmp_path, monkeypatch)
    probe = codegraph_probe()
    assert probe["binary"] == str(script.resolve())
    assert "fake codegraph" in probe["help"]["text"]

    result = codegraph_query(args=["callers", "RateService.adjustRate", "--depth", "2", "--json"])
    payload = json.loads(result["result"]["text"])
    assert payload["kind"] == "query-result"
    assert payload["args"][0] == "callers"
    assert "RateService.adjustRate" in payload["args"]


def test_codegraph_adapter_rejects_mutating_or_unknown_operations(tmp_path, monkeypatch) -> None:
    _fake_codegraph(tmp_path, monkeypatch)
    with pytest.raises(ProfessionalToolError, match="CODEGRAPH_MUTATING_OPERATION_FORBIDDEN"):
        codegraph_query(args=["index", "."])
    with pytest.raises(ProfessionalToolError, match="CODEGRAPH_MUTATING_OPERATION_FORBIDDEN"):
        codegraph_query(args=["query", "RateService", "--output", "index"])
    with pytest.raises(ProfessionalToolError, match="CODEGRAPH_QUERY_VERB_NOT_ALLOWED"):
        codegraph_query(args=["doctor"])
    with pytest.raises(ProfessionalToolError, match="CODEGRAPH_OPTION_NOT_ALLOWED"):
        codegraph_query(args=["query", "RateService", "--write-cache"])


def test_rc7_mcp_adds_professional_tools_without_losing_rc6_tools(tmp_path, monkeypatch) -> None:
    _workspace, _repo, base, head = _git_repo(tmp_path, monkeypatch)
    listing = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    names = {tool["name"] for tool in listing["result"]["tools"]}
    assert "runtime_status" in names
    assert {"git_show_revision", "git_diff", "codegraph_probe", "codegraph_query"}.issubset(names)

    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "git_diff",
                "arguments": {
                    "repo_path": "cfg-data",
                    "base_ref": base,
                    "head_ref": head,
                    "paths": ["RateService.java"],
                },
            },
        }
    )
    assert not response["result"].get("isError", False)
    result = json.loads(response["result"]["content"][0]["text"])
    assert result["changed_files"] == ["RateService.java"]


def test_rc7_patch_uses_additive_rc7_mcp_server_and_passes_tool_env(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    codegraph = tmp_path / "codegraph-bin"
    codegraph.write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("PFC_CODEGRAPH_BIN", str(codegraph))
    monkeypatch.delenv("PFC_WORKSPACE", raising=False)

    patch = write_patch(tmp_path / "rc7.cordis.yml", home, sys.executable)
    text = patch.read_text(encoding="utf-8")
    assert "serverName: pfc_aitest_rc7" in text
    assert "args: ['-m', 'rc7_release.mcp_server_authorized']" in text
    assert "args: ['-m', 'rc7_release.mcp_server_field']" not in text
    assert "PFC_WORKSPACE:" in text
    assert "PFC_CODEGRAPH_BIN:" in text
    assert "rc6_release.mcp_server" not in text
