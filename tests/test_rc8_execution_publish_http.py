from __future__ import annotations

import threading
from pathlib import Path

from rc8_center import CenterControlPlane, MemoryCenterRepository
from rc8_center.artifacts import FileArtifactStore, MemoryArtifactRepository
from rc8_center.http_server import CenterHttpApplication, create_server
from rc8_node import HttpCenterClient, NodeAgent, NodeIdentityStore
from rc8_node.execution import JUnitActual, MavenExecutionResult
from rc8_node.execution_publish import publish_maven_junit_execution
from rc8_runtime import CentralR1RuntimeLedger


def _result(tmp_path: Path) -> MavenExecutionResult:
    actual_path = tmp_path / "actual.json"
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    xml_path = tmp_path / "TEST-real-http.xml"
    actual_path.write_text('{"actual":true}', encoding="utf-8")
    stdout_path.write_text("maven output", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    xml_path.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0"/>', encoding="utf-8")
    actual = JUnitActual(tests=1, failures=0, errors=0, skipped=0, xml_files=[str(xml_path)])
    return MavenExecutionResult(["mvn", "test"], 0, 1, 2, actual, str(actual_path), "0" * 64, str(stdout_path), str(stderr_path))


def test_real_center_http_artifact_response_is_accepted_before_r1(tmp_path: Path) -> None:
    repo = MemoryCenterRepository()
    ledger = CentralR1RuntimeLedger(str(tmp_path / "r1.jsonl"))
    control = CenterControlPlane(repo, ledger)
    artifact_repo = MemoryArtifactRepository()
    artifact_store = FileArtifactStore(str(tmp_path / "artifacts"), artifact_repo)
    server = create_server(CenterHttpApplication(control, artifact_store), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = HttpCenterClient("http://127.0.0.1:%s" % server.server_address[1])
        identity = NodeIdentityStore(str(tmp_path / "node.json")).load_or_create(
            node_id="NODE-EXEC-HTTP",
            operator_ref="tester",
            os_family="linux",
            architecture="x86_64",
            shell="bash",
            now=100,
        )
        agent = NodeAgent(identity, client)
        agent.register()
        agent.heartbeat()
        client.post(
            "/api/v1/work-items/register",
            {
                "work_item_id": "WI-EXEC-HTTP",
                "test_run_id": "RUN-EXEC-HTTP",
                "stage": "EXECUTION",
                "scope_refs": ["SCOPE-HTTP"],
                "required_capabilities": [],
            },
        )
        agent.lease("WI-EXEC-HTTP", ttl_seconds=120)
        agent.start("WI-EXEC-HTTP")

        published = publish_maven_junit_execution(
            agent,
            test_run_id="RUN-EXEC-HTTP",
            work_item_id="WI-EXEC-HTTP",
            result=_result(tmp_path),
            event_id="EV-EXEC-HTTP",
            sequence=1,
        )

        assert published["actual_passed"] is True
        assert len(published["artifact_ids"]) == 4
        assert all(artifact_repo.get(artifact_id).availability.value == "AVAILABLE" for artifact_id in published["artifact_ids"])
        events = ledger.runtime_events(test_run_id="RUN-EXEC-HTTP")
        assert len(events) == 1
        assert events[0]["event_id"] == "EV-EXEC-HTTP"
        assert events[0]["refs"] == published["artifact_ids"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
