from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

from rc8_center import CenterControlPlane, MemoryCenterRepository
from rc8_center.artifacts import FileArtifactStore, MemoryArtifactRepository
from rc8_center.http_server import CenterHttpApplication, create_server
from rc8_node.codegraph import CodeGraphExecutableAdapter
from rc8_node.reality_code_analysis import run_code_analysis_reality
from rc8_runtime import CentralR1RuntimeLedger


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "business-repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "rc8@example.test")
    _git(repo, "config", "user.name", "RC8 Test")
    service = repo / "src" / "main" / "java" / "demo" / "Service.java"
    controller = repo / "src" / "main" / "java" / "demo" / "Controller.java"
    service.parent.mkdir(parents=True)
    service.write_text("package demo; public class Service { String value(){ return \"v1\"; } }\n", encoding="utf-8")
    controller.write_text("package demo; public class Controller { String get(){ return \"v1\"; } }\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    service.write_text("package demo; public class Service { String value(){ return \"v2\"; } }\n", encoding="utf-8")
    controller.write_text("package demo; public class Controller { String get(){ return \"v2\"; } }\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "change")
    return repo


def _center(tmp_path: Path):
    repo = MemoryCenterRepository()
    ledger = CentralR1RuntimeLedger(str(tmp_path / "r1.jsonl"))
    control = CenterControlPlane(repo, ledger)
    artifact_repo = MemoryArtifactRepository()
    artifact_store = FileArtifactStore(str(tmp_path / "artifacts"), artifact_repo)
    server = create_server(CenterHttpApplication(control, artifact_store), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, repo, ledger, artifact_repo, "http://127.0.0.1:%s" % server.server_address[1]


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
                "nodes": [{"name": "demo.Symbol", "kind": "METHOD"}],
                "edges": [{"from": "demo.Controller", "to": "demo.Service"}],
            },
            "parse_error": None,
            "success": True,
        }


def test_code_analysis_reality_stays_probing_when_semantic_analysis_is_missing(monkeypatch, tmp_path: Path) -> None:
    server, thread, repo, ledger, artifacts, center_url = _center(tmp_path)
    monkeypatch.setattr("rc8_node.code_analysis.CodeGraphExecutableAdapter", ContractCodeGraphAdapter)
    try:
        business = _repo(tmp_path)
        code, summary = run_code_analysis_reality(
            center_url=center_url,
            node_id="NODE-CA-1",
            operator_ref="tester",
            state_dir=str(tmp_path / "node-state"),
            project_dir=str(business),
            codegraph_command="contract-codegraph",
            run_id="REALITY-CA-CONTRACT-PENDING",
            base_ref="HEAD~1",
            head_ref="HEAD",
            max_rounds=3,
            initial_points=1,
            points_step=1,
            max_points=4,
        )
        assert code == 30
        assert summary["overall_sufficiency"] == "SEMANTIC_PENDING"
        assert summary["capability_state"] == "PROBING"
        assert summary["classification"] == "CODE_ANALYSIS_STRUCTURAL_EVIDENCE_SUFFICIENT_SEMANTIC_PENDING"
        assert summary["structural_sufficiency"]["state"] == "PASS"
        assert summary["round_count"] == 2
        assert summary["work_item_state"] == "COMPLETED"
        assert summary["r1_receipt"]["status"] == "PERSISTENCE_VERIFIED"
        qualification = repo.get_capability("NODE-CA-1", "code-analysis")
        assert qualification is not None
        assert qualification.state.value == "PROBING"
        events = ledger.runtime_events(test_run_id="REALITY-CA-CONTRACT-PENDING")
        assert len(events) == 1
        assert events[0]["event_type"] == "CODE_ANALYSIS_STRUCTURAL_EVIDENCE_RECORDED"
        assert events[0]["data"]["semantic_analysis_present"] is False
        assert all(artifacts.get(artifact_id).availability.value == "AVAILABLE" for artifact_id in summary["artifact_ids"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_code_analysis_reality_verifies_only_after_evidence_bound_semantic_pass(monkeypatch, tmp_path: Path) -> None:
    server, thread, repo, ledger, artifacts, center_url = _center(tmp_path)
    monkeypatch.setattr("rc8_node.code_analysis.CodeGraphExecutableAdapter", ContractCodeGraphAdapter)
    try:
        business = _repo(tmp_path)
        # The deterministic evidence refs are stable for this repository/snapshot.
        from rc8_node.code_analysis import EvidenceBackedCodeAnalysisEngine

        probe = EvidenceBackedCodeAnalysisEngine(
            str(tmp_path / "probe"),
            codegraph_command="contract-codegraph",
            initial_points=2,
            points_step=1,
            max_points=4,
        ).execute(repo_path=str(business), base_ref="HEAD~1", head_ref="HEAD")
        ref = probe.structured_analysis["evidence_refs"][0]
        semantic_path = tmp_path / "semantic.json"
        semantic_path.write_text(
            json.dumps(
                {
                    "summary": "调用链和变更影响已分析。",
                    "changes": [{"file": "src/main/java/demo/Service.java"}],
                    "impact_chains": [{"from": "Controller", "to": "Service"}],
                    "risks": [{"type": "REGRESSION"}],
                    "test_impacts": [{"type": "TARGETED_REGRESSION"}],
                    "unknowns": [],
                    "sufficiency": {"state": "PASS", "reason": "all required evidence mapped"},
                    "claims": [{"claim": "调用链需要回归", "evidence_refs": [ref]}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        code, summary = run_code_analysis_reality(
            center_url=center_url,
            node_id="NODE-CA-2",
            operator_ref="tester",
            state_dir=str(tmp_path / "node-state-2"),
            project_dir=str(business),
            codegraph_command="contract-codegraph",
            run_id="REALITY-CA-CONTRACT-PASS",
            base_ref="HEAD~1",
            head_ref="HEAD",
            semantic_json=str(semantic_path),
            max_rounds=3,
            initial_points=2,
            points_step=1,
            max_points=4,
        )
        assert code == 0
        assert summary["reality_status"] == "EXECUTION_CHAIN_VERIFIED"
        assert summary["overall_sufficiency"] == "PASS"
        assert summary["capability_state"] == "VERIFIED"
        assert summary["classification"] == "CODE_ANALYSIS_SUFFICIENT"
        assert summary["semantic_analysis_present"] is True
        qualification = repo.get_capability("NODE-CA-2", "code-analysis")
        assert qualification is not None
        assert qualification.state.value == "VERIFIED"
        events = ledger.runtime_events(test_run_id="REALITY-CA-CONTRACT-PASS")
        assert len(events) == 1
        assert events[0]["event_type"] == "CODE_ANALYSIS_SUFFICIENT_RECORDED"
        assert events[0]["data"]["overall_sufficiency"] == "PASS"
        assert all(artifacts.get(artifact_id).availability.value == "AVAILABLE" for artifact_id in summary["artifact_ids"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
