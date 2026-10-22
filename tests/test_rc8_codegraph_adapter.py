from __future__ import annotations

import subprocess
from pathlib import Path

from rc8_node.codegraph import CodeGraphExecutableAdapter


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "rc8@example.test")
    _git(repo, "config", "user.name", "RC8 Test")
    source = repo / "src" / "Demo.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        "package demo;\npublic class Demo { public int value() { return 1; } }\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    source.write_text(
        "package demo;\npublic class Demo { public int value() { return 2; } }\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "change")
    return repo


class FakeCodeGraphAdapter(CodeGraphExecutableAdapter):
    def __init__(self, evidence_dir: str, **_kwargs) -> None:
        self.evidence_dir = Path(evidence_dir)
        self.codegraph_command = "fake-codegraph"
        self.timeout_seconds = 1

    def _call_tool(self, repo: Path, tool: str, args):
        return {
            "tool": tool,
            "arguments": dict(args),
            "returncode": 0,
            "started_at": 1,
            "finished_at": 2,
            "stdout_encoding": "utf-8",
            "stderr_encoding": "empty",
            "stderr": "",
            "payload": {
                "tool": tool,
                "workspace": str(repo),
                "nodes": [{"name": "demo.Demo.value", "kind": "METHOD"}],
                "edges": [],
            },
            "parse_error": None,
            "success": True,
        }


def test_codegraph_executes_real_structural_contract_against_one_git_snapshot(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    adapter = FakeCodeGraphAdapter(str(tmp_path / "evidence"))
    result = adapter.execute(
        repo_path=str(repo),
        base_ref="HEAD~1",
        head_ref="HEAD",
        max_points=1,
    )
    assert result.state == "PASS"
    assert result.classification == "CODEGRAPH_GRAPH_EVIDENCE_VERIFIED"
    assert result.snapshot_before.snapshot_id == result.snapshot_after.snapshot_id
    assert result.changed_java_files == ("src/Demo.java",)
    assert len(result.query_points) == 1
    assert len(result.tool_calls) == 5
    assert [item["tool"] for item in result.tool_calls] == [
        "codegraph_get_ai_context",
        "codegraph_get_callers",
        "codegraph_get_callees",
        "codegraph_get_dependency_graph",
        "codegraph_analyze_impact",
    ]
    evidence = Path(result.evidence_path)
    assert evidence.is_file()
    text = evidence.read_text(encoding="utf-8")
    assert result.graph_digest in text
    assert result.snapshot_before.snapshot_id in text


class MutatingCodeGraphAdapter(FakeCodeGraphAdapter):
    def __init__(self, evidence_dir: str, **kwargs) -> None:
        super().__init__(evidence_dir, **kwargs)
        self._mutated = False

    def _call_tool(self, repo: Path, tool: str, args):
        response = super()._call_tool(repo, tool, args)
        if not self._mutated:
            self._mutated = True
            with (repo / "src" / "Demo.java").open("a", encoding="utf-8") as handle:
                handle.write("// changed during graph query\n")
        return response


def test_codegraph_fails_closed_when_source_snapshot_changes_during_query(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    adapter = MutatingCodeGraphAdapter(str(tmp_path / "evidence"))
    result = adapter.execute(
        repo_path=str(repo),
        base_ref="HEAD~1",
        head_ref="HEAD",
        max_points=1,
    )
    assert result.state == "FAILED"
    assert result.classification == "CODEGRAPH_SNAPSHOT_STALE"
    assert result.snapshot_before.snapshot_id != result.snapshot_after.snapshot_id


class PartialCodeGraphAdapter(FakeCodeGraphAdapter):
    def _call_tool(self, repo: Path, tool: str, args):
        response = super()._call_tool(repo, tool, args)
        if tool == "codegraph_get_callers":
            response["returncode"] = 1
            response["success"] = False
            response["stderr"] = "real query failed"
        return response


def test_codegraph_does_not_verify_when_one_structural_query_fails(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    adapter = PartialCodeGraphAdapter(str(tmp_path / "evidence"))
    result = adapter.execute(
        repo_path=str(repo),
        base_ref="HEAD~1",
        head_ref="HEAD",
        max_points=1,
    )
    assert result.state == "FAILED"
    assert result.classification == "CODEGRAPH_STRUCTURAL_QUERY_FAILED"
