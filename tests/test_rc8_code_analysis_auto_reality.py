from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

from rc8_center import CenterControlPlane, MemoryCenterRepository
from rc8_center.artifacts import FileArtifactStore, MemoryArtifactRepository
from rc8_center.http_server import CenterHttpApplication, create_server
from rc8_node.codegraph import CodeGraphExecutableAdapter
from rc8_node.dsh_semantic_worker import DshSemanticResult
from rc8_node.reality_code_analysis_auto import run_auto_code_analysis_reality
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


class ContractDshSemanticWorker:
    def __init__(self, evidence_dir: str, **_kwargs) -> None:
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def execute(self, *, request_path: str, env=None):
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        evidence_ref = request["allowed_evidence_refs"][0]
        raw = self.evidence_dir / "dsh-semantic.jsonl"
        provenance = self.evidence_dir / "dsh-semantic-provenance.json"
        raw.write_text('{"type":"ci-contract-double"}\n', encoding="utf-8")
        provenance.write_text(json.dumps({"state": "PASS", "source": "CI_CONTRACT_DOUBLE_NOT_BANK_REALITY"}), encoding="utf-8")
        semantic = {
            "summary": "evidence-backed semantic summary",
            "changes": [{"file": request["source_change"]["changed_java_files"][0]}],
            "impact_chains": [{"from": "Controller", "to": "Service"}],
            "risks": [{"type": "REGRESSION", "severity": "MEDIUM"}],
            "test_impacts": [{"layer": "L1", "target": "changed chain"}],
            "unknowns": [],
            "claims": [{"claim": "changed code needs targeted regression", "evidence_refs": [evidence_ref]}],
            "sufficiency": {"state": "PASS", "reason": "CI contract evidence covered"},
        }
        return DshSemanticResult(
            state="PASS",
            classification="DSH_SEMANTIC_WORKER_VERIFIED",
            session_id="session-ci-auto-1",
            exit_code=0,
            semantic_analysis=semantic,
            tool_calls=({"tool_name": "mcp__pfc_aitest_rc7__read_text", "call_id": "call-1"},),
            tool_results=({"call_id": "call-1", "kind": "tool_result"},),
            stdout_encoding="utf-8",
            stderr_encoding="empty",
            raw_jsonl_path=str(raw),
            provenance_path=str(provenance),
        )


def test_auto_code_analysis_promotes_only_after_structural_and_dsh_semantic_pass(monkeypatch, tmp_path: Path) -> None:
    server, thread, repo, ledger, artifacts, center_url = _center(tmp_path)
    monkeypatch.setattr("rc8_node.code_analysis.CodeGraphExecutableAdapter", ContractCodeGraphAdapter)
    monkeypatch.setattr("rc8_node.reality_code_analysis_auto.DshSemanticWorker", ContractDshSemanticWorker)
    try:
        business = _repo(tmp_path)
        code, summary = run_auto_code_analysis_reality(
            center_url=center_url,
            node_id="NODE-CA-AUTO-1",
            operator_ref="tester",
            state_dir=str(tmp_path / "node-state"),
            project_dir=str(business),
            codegraph_command="contract-codegraph",
            dsh_command="contract-dsh",
            run_id="REALITY-CA-AUTO-CONTRACT",
            base_ref="HEAD~1",
            head_ref="HEAD",
            max_rounds=3,
            initial_points=1,
            points_step=1,
            max_points=4,
        )
        assert code == 0
        assert summary["reality_status"] == "EXECUTION_CHAIN_VERIFIED"
        assert summary["classification"] == "CODE_ANALYSIS_SUFFICIENT"
        assert summary["overall_sufficiency"] == "PASS"
        assert summary["capability_state"] == "VERIFIED"
        assert summary["structural_sufficiency"]["state"] == "PASS"
        assert summary["round_count"] == 2
        assert summary["semantic_source"] == "DSH_HEADLESS_WORKER"
        assert summary["semantic_sufficiency"]["state"] == "PASS"
        assert summary["dsh_session_id"] == "session-ci-auto-1"
        assert summary["dsh_tool_call_count"] == 1
        assert summary["dsh_tool_result_count"] == 1
        assert summary["work_item_state"] == "COMPLETED"
        assert summary["r1_receipt"]["status"] == "PERSISTENCE_VERIFIED"
        qualification = repo.get_capability("NODE-CA-AUTO-1", "code-analysis")
        assert qualification is not None
        assert qualification.state.value == "VERIFIED"
        events = ledger.runtime_events(test_run_id="REALITY-CA-AUTO-CONTRACT")
        assert len(events) == 1
        assert events[0]["event_type"] == "CODE_ANALYSIS_SUFFICIENT_RECORDED"
        assert events[0]["data"]["semantic_source"] == "DSH_HEADLESS_WORKER"
        assert events[0]["data"]["dsh_session_id"] == "session-ci-auto-1"
        assert all(artifacts.get(artifact_id).availability.value == "AVAILABLE" for artifact_id in summary["artifact_ids"])
        assert Path(summary["final_analysis_path"]).is_file()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
