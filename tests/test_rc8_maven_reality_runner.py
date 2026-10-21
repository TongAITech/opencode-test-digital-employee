from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from rc8_center import CenterControlPlane, MemoryCenterRepository
from rc8_center.artifacts import FileArtifactStore, MemoryArtifactRepository
from rc8_center.http_server import CenterHttpApplication, create_server
from rc8_node.reality_maven import MavenRealityError, run_maven_reality
from rc8_runtime import CentralR1RuntimeLedger


def _fake_maven(tmp_path: Path) -> str:
    if os.name == "nt":
        path = tmp_path / "mvn.cmd"
        path.write_text("@echo off\r\necho Apache Maven RC8-reality-contract\r\nexit /b 0\r\n", encoding="utf-8")
    else:
        path = tmp_path / "mvn"
        path.write_text("#!/usr/bin/env bash\necho 'Apache Maven RC8-reality-contract'\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    return str(path)


def _project(tmp_path: Path, failures: int = 0) -> Path:
    project = tmp_path / "project"
    reports = project / "target" / "surefire-reports"
    reports.mkdir(parents=True)
    (project / "pom.xml").write_text("<project></project>", encoding="utf-8")
    (reports / "TEST-reality.xml").write_text(
        '<testsuite name="reality" tests="2" failures="%s" errors="0" skipped="0"></testsuite>' % failures,
        encoding="utf-8",
    )
    return project


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


def test_reality_runner_proves_complete_center_node_maven_chain_in_contract_environment(tmp_path: Path) -> None:
    server, thread, repo, ledger, artifacts, center_url = _center(tmp_path)
    try:
        project = _project(tmp_path)
        code, summary = run_maven_reality(
            center_url=center_url,
            node_id="NODE-REALITY-1",
            operator_ref="tester",
            state_dir=str(tmp_path / "node-state"),
            project_dir=str(project),
            maven_command=_fake_maven(tmp_path),
            run_id="REALITY-CONTRACT-1",
            allow_online=False,
            require_pass=True,
        )
        assert code == 0
        assert summary["reality_status"] == "EXECUTION_CHAIN_VERIFIED"
        assert summary["offline"] is True
        assert summary["actual"]["passed"] is True
        assert summary["goals"][0] == "-o"
        assert len(summary["artifact_ids"]) == 4
        assert summary["r1_receipt"]["status"] == "PERSISTENCE_VERIFIED"
        assert repo.get_capability("NODE-REALITY-1", "maven-junit").state.value == "VERIFIED"
        assert repo.get_work_item("REALITY-CONTRACT-1-execution").state.value == "COMPLETED"
        assert len(ledger.runtime_events(test_run_id="REALITY-CONTRACT-1")) == 1
        assert all(artifacts.get(artifact_id).availability.value == "AVAILABLE" for artifact_id in summary["artifact_ids"])
        result_path = tmp_path / "node-state" / "reality" / "REALITY-CONTRACT-1" / "reality-result.json"
        preflight_path = tmp_path / "node-state" / "reality" / "REALITY-CONTRACT-1" / "preflight.json"
        assert result_path.is_file()
        assert preflight_path.is_file()
        preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
        assert preflight["status"] == "PREFLIGHT_PASS"
        assert preflight["pom_exists"] is True
        assert preflight["maven_command_resolved"] is True
        assert preflight["truth_note"].startswith("PREFLIGHT_PASS proves prerequisites")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_reality_runner_distinguishes_verified_chain_from_failed_junit_actual(tmp_path: Path) -> None:
    server, thread, _, ledger, _, center_url = _center(tmp_path)
    try:
        project = _project(tmp_path, failures=1)
        code, summary = run_maven_reality(
            center_url=center_url,
            node_id="NODE-REALITY-2",
            operator_ref="tester",
            state_dir=str(tmp_path / "node-state-2"),
            project_dir=str(project),
            maven_command=_fake_maven(tmp_path),
            run_id="REALITY-CONTRACT-2",
            allow_online=False,
            require_pass=True,
        )
        assert code == 30
        assert summary["reality_status"] == "EXECUTION_CHAIN_VERIFIED_TEST_FAILED"
        assert summary["actual"]["passed"] is False
        events = ledger.runtime_events(test_run_id="REALITY-CONTRACT-2")
        assert len(events) == 1
        assert events[0]["data"]["passed"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_strict_portability_rejects_implicit_default_maven_repository(tmp_path: Path) -> None:
    server, thread, _, _, _, center_url = _center(tmp_path)
    try:
        with pytest.raises(MavenRealityError, match="STRICT_PORTABILITY_REQUIRES_EXPLICIT_MAVEN_REPO"):
            run_maven_reality(
                center_url=center_url,
                node_id="NODE-STRICT-1",
                operator_ref="tester",
                state_dir=str(tmp_path / "strict-state"),
                project_dir=str(_project(tmp_path)),
                maven_command=_fake_maven(tmp_path),
                run_id="REALITY-STRICT-1",
                allow_online=False,
                strict_portability=True,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_strict_portability_uses_explicit_offline_repository_and_records_preflight(tmp_path: Path) -> None:
    server, thread, _, _, _, center_url = _center(tmp_path)
    try:
        repo_dir = tmp_path / "offline-m2"
        repo_dir.mkdir()
        code, summary = run_maven_reality(
            center_url=center_url,
            node_id="NODE-STRICT-2",
            operator_ref="tester",
            state_dir=str(tmp_path / "strict-state-2"),
            project_dir=str(_project(tmp_path)),
            maven_command=_fake_maven(tmp_path),
            run_id="REALITY-STRICT-2",
            maven_repo=str(repo_dir),
            allow_online=False,
            strict_portability=True,
        )
        assert code == 0
        assert summary["strict_portability"] is True
        assert summary["goals"][0] == "-o"
        assert summary["goals"][1] == "-Dmaven.repo.local=%s" % repo_dir.resolve()
        preflight = json.loads(Path(summary["preflight_path"]).read_text(encoding="utf-8"))
        assert preflight["explicit_maven_repository"] is True
        assert preflight["strict_portability"] is True
        assert preflight["maven_local_repository"] == str(repo_dir.resolve())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_unsafe_run_id_is_rejected_before_center_or_artifact_mutation(tmp_path: Path) -> None:
    with pytest.raises(MavenRealityError, match="REALITY_RUN_ID_UNSAFE"):
        run_maven_reality(
            center_url="http://127.0.0.1:1",
            node_id="NODE-UNSAFE",
            operator_ref="tester",
            state_dir=str(tmp_path / "unsafe-state"),
            project_dir=str(_project(tmp_path)),
            maven_command=_fake_maven(tmp_path),
            run_id="bad/run:id",
        )
