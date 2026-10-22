from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from rc8_node.code_analysis import CodeAnalysisError, EvidenceBackedCodeAnalysisEngine, validate_semantic_analysis
from rc8_node.codegraph import CodeGraphExecutableAdapter


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "business-repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "rc8@example.test")
    _git(repo, "config", "user.name", "RC8 Test")
    service = repo / "src" / "main" / "java" / "demo" / "OrderService.java"
    controller = repo / "src" / "main" / "java" / "demo" / "OrderController.java"
    service.parent.mkdir(parents=True)
    service.write_text("package demo; public class OrderService { String value(){ return \"v1\"; } }\n", encoding="utf-8")
    controller.write_text("package demo; public class OrderController { String get(){ return \"v1\"; } }\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    service.write_text("package demo; public class OrderService { String value(){ return \"v2\"; } }\n", encoding="utf-8")
    controller.write_text("package demo; public class OrderController { String get(){ return \"v2\"; } }\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "two java changes")
    return repo


class ContractCodeGraphAdapter(CodeGraphExecutableAdapter):
    def __init__(self, evidence_dir: str, **_kwargs) -> None:
        self.evidence_dir = Path(evidence_dir)
        self.codegraph_command = "contract-codegraph"
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
                "server": "CI_CONTRACT_DOUBLE_NOT_BANK_REALITY",
                "nodes": [{"name": Path(str(args.get("uri") or "")).name, "kind": "METHOD"}],
                "edges": [{"from": "demo.Controller", "to": "demo.Service"}],
            },
            "parse_error": None,
            "success": True,
        }


def test_code_analysis_expands_queries_until_changed_files_are_covered(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("rc8_node.code_analysis.CodeGraphExecutableAdapter", ContractCodeGraphAdapter)
    repo = _repo(tmp_path)
    engine = EvidenceBackedCodeAnalysisEngine(
        str(tmp_path / "evidence"),
        codegraph_command="contract-codegraph",
        max_rounds=3,
        initial_points=1,
        points_step=1,
        max_points=4,
    )
    result = engine.execute(repo_path=str(repo), base_ref="HEAD~1", head_ref="HEAD")

    assert result.state == "PARTIAL"
    assert result.classification == "CODE_ANALYSIS_STRUCTURAL_EVIDENCE_SUFFICIENT_SEMANTIC_PENDING"
    assert result.overall_sufficiency == "SEMANTIC_PENDING"
    assert result.structural_sufficiency.state == "PASS"
    assert result.structural_sufficiency.changed_file_count == 2
    assert result.structural_sufficiency.covered_file_count == 2
    assert len(result.rounds) == 2
    assert result.rounds[0]["sufficiency"]["state"] == "INSUFFICIENT"
    assert result.rounds[1]["sufficiency"]["state"] == "PASS"
    assert result.rounds[0]["point_limit"] == 1
    assert result.rounds[1]["point_limit"] == 2
    assert result.structured_analysis["analysis_mode"] == "EVIDENCE_STRUCTURED_NOT_LLM"
    assert len(result.structured_analysis["risk_hypotheses"]) >= 2
    assert Path(result.analysis_path).is_file()


def test_semantic_analysis_must_bind_every_claim_to_known_evidence() -> None:
    payload = {
        "summary": "demo",
        "changes": [],
        "impact_chains": [],
        "risks": [],
        "test_impacts": [],
        "unknowns": [],
        "sufficiency": {"state": "PASS"},
        "claims": [{"claim": "risk", "evidence_refs": ["unknown-ref"]}],
    }
    with pytest.raises(CodeAnalysisError, match="SEMANTIC_ANALYSIS_UNKNOWN_EVIDENCE_REF"):
        validate_semantic_analysis(payload, ["known-ref"])


def test_semantic_analysis_can_promote_structural_evidence_to_full_pass(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("rc8_node.code_analysis.CodeGraphExecutableAdapter", ContractCodeGraphAdapter)
    repo = _repo(tmp_path)
    first = EvidenceBackedCodeAnalysisEngine(
        str(tmp_path / "first"),
        codegraph_command="contract-codegraph",
        initial_points=2,
        points_step=1,
        max_points=4,
    ).execute(repo_path=str(repo), base_ref="HEAD~1", head_ref="HEAD")
    ref = first.structured_analysis["evidence_refs"][0]
    semantic = {
        "summary": "两个 Java 文件发生变更，需要回归上下游调用链。",
        "changes": [{"file": "src/main/java/demo/OrderService.java"}],
        "impact_chains": [{"from": "OrderController", "to": "OrderService"}],
        "risks": [{"type": "REGRESSION"}],
        "test_impacts": [{"type": "TARGETED_REGRESSION"}],
        "unknowns": [],
        "sufficiency": {"state": "PASS", "reason": "evidence covered"},
        "claims": [{"claim": "调用链需要回归", "evidence_refs": [ref]}],
    }
    second = EvidenceBackedCodeAnalysisEngine(
        str(tmp_path / "second"),
        codegraph_command="contract-codegraph",
        initial_points=2,
        points_step=1,
        max_points=4,
    ).execute(repo_path=str(repo), base_ref="HEAD~1", head_ref="HEAD", semantic_analysis=semantic)

    assert second.state == "PASS"
    assert second.classification == "CODE_ANALYSIS_SUFFICIENT"
    assert second.overall_sufficiency == "PASS"
    assert second.semantic_analysis is not None
    assert second.semantic_analysis["validation"]["state"] == "PASS"
    payload = json.loads(Path(second.analysis_path).read_text(encoding="utf-8"))
    assert payload["overall_sufficiency"] == "PASS"
