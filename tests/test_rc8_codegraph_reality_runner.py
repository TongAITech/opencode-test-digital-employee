from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from rc8_center import CenterControlPlane, MemoryCenterRepository
from rc8_center.artifacts import FileArtifactStore, MemoryArtifactRepository
from rc8_center.http_server import CenterHttpApplication, create_server
from rc8_node.codegraph import CodeGraphExecutableAdapter
from rc8_node.reality_codegraph import run_codegraph_reality
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
    source = repo / "src" / "main" / "java" / "demo" / "Service.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        "package demo;\npublic class Service { public String value() { return \"v1\"; } }\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    source.write_text(
        "package demo;\npublic class Service { public String value() { return \"v2\"; } }\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "java change")
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
    """CI contract double. Never represents BANK_REALITY_VERIFIED."""

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
                "nodes": [{"name": "demo.Service.value", "kind": "METHOD"}],
                "edges": [{"from": "demo.Service.value", "to": "demo.Repository.get"}],
            },
            "parse_error": None,
            "success": True,
        }


def test_codegraph_reality_runner_persists_snapshot_bound_graph_evidence(monkeypatch, tmp_path: Path) -> None:
    server, thread, repo, ledger, artifacts, center_url = _center(tmp_path)
    monkeypatch.setattr("rc8_node.reality_codegraph.CodeGraphExecutableAdapter", ContractCodeGraphAdapter)
    try:
        business = _repo(tmp_path)
        code, summary = run_codegraph_reality(
            center_url=center_url,
            node_id="NODE-CG-1",
            operator_ref="tester",
            state_dir=str(tmp_path / "node-state"),
            project_dir=str(business),
            codegraph_command="contract-codegraph",
            run_id="REALITY-CG-CONTRACT-1",
            base_ref="HEAD~1",
            head_ref="HEAD",
            max_points=1,
        )
        assert code == 0
        assert summary["reality_status"] == "EXECUTION_CHAIN_VERIFIED"
        assert summary["capability_state"] == "VERIFIED"
        assert summary["classification"] == "CODEGRAPH_GRAPH_EVIDENCE_VERIFIED"
        assert summary["changed_java_files"] == ["src/main/java/demo/Service.java"]
        assert summary["query_point_count"] == 1
        assert summary["tool_call_count"] == 5
        assert summary["work_item_state"] == "COMPLETED"
        assert summary["r1_receipt"]["status"] == "PERSISTENCE_VERIFIED"
        assert len(summary["artifact_ids"]) == 2

        qualification = repo.get_capability("NODE-CG-1", "codegraph")
        assert qualification is not None
        assert qualification.state.value == "VERIFIED"
        work = repo.get_work_item("REALITY-CG-CONTRACT-1-execution")
        assert work is not None
        assert work.state.value == "COMPLETED"
        events = ledger.runtime_events(test_run_id="REALITY-CG-CONTRACT-1")
        assert len(events) == 1
        event = events[0]
        assert event["event_type"] == "CODEGRAPH_GRAPH_EVIDENCE_RECORDED"
        assert event["data"]["snapshot_id"] == summary["snapshot_id"]
        assert event["data"]["graph_digest"] == summary["graph_digest"]
        assert event["data"]["tool_call_count"] == 5
        assert event["data"]["tool_names"] == [
            "codegraph_get_ai_context",
            "codegraph_get_callers",
            "codegraph_get_callees",
            "codegraph_get_dependency_graph",
            "codegraph_analyze_impact",
        ]
        assert all(artifacts.get(artifact_id).availability.value == "AVAILABLE" for artifact_id in summary["artifact_ids"])
        graph_path = Path(summary["graph_evidence_path"])
        assert graph_path.is_file()
        assert summary["snapshot_id"] in graph_path.read_text(encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
