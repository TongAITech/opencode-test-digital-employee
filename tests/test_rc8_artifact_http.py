from __future__ import annotations

import hashlib
import threading
from dataclasses import asdict
from pathlib import Path

import pytest

from rc8_center import CenterControlPlane, MemoryCenterRepository
from rc8_center.artifacts import FileArtifactStore, MemoryArtifactRepository
from rc8_center.http_server import CenterHttpApplication, create_server
from rc8_node import HttpCenterClient, NodeAgent, NodeAgentError, NodeIdentityStore
from rc8_runtime import CentralR1RuntimeLedger, RuntimeProducerKind
from rc8_runtime.artifacts import ArtifactManifest


def _stack(tmp_path: Path):
    repo = MemoryCenterRepository()
    ledger = CentralR1RuntimeLedger(str(tmp_path / "r1.jsonl"))
    control = CenterControlPlane(repo, ledger)
    artifact_repo = MemoryArtifactRepository()
    artifact_store = FileArtifactStore(str(tmp_path / "artifacts"), artifact_repo)
    server = create_server(CenterHttpApplication(control, artifact_store), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HttpCenterClient("http://127.0.0.1:%s" % server.server_address[1])
    return server, thread, control, artifact_repo, artifact_store, client


def _agent(client: HttpCenterClient, tmp_path: Path, node_id: str) -> NodeAgent:
    identity = NodeIdentityStore(str(tmp_path / (node_id + ".json"))).load_or_create(
        node_id=node_id,
        operator_ref="tester",
        os_family="windows",
        architecture="x86_64",
        shell="git-bash",
        now=100,
    )
    agent = NodeAgent(identity, client)
    agent.register()
    agent.heartbeat()
    return agent


def _register_and_lease(client: HttpCenterClient, agent: NodeAgent, work_id: str = "WI-ART") -> None:
    client.post(
        "/api/v1/work-items/register",
        {
            "work_item_id": work_id,
            "test_run_id": "RUN-ART",
            "stage": "EXECUTION",
            "scope_refs": ["SCOPE-1"],
            "required_capabilities": [],
        },
    )
    agent.lease(work_id, ttl_seconds=120)
    agent.start(work_id)


def _manifest(content: bytes, *, node_id="NODE-1", artifact_id="ART-HTTP-1") -> ArtifactManifest:
    return ArtifactManifest(
        artifact_id=artifact_id,
        test_run_id="RUN-ART",
        work_item_id="WI-ART",
        node_id=node_id,
        kind="SCREENSHOT",
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="browser-skill",
        file_name="执行步骤截图.png",
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        case_id="TC-1",
        attempt_id="ATT-1",
        step_id="STEP-1",
        refs=["EV-1", "AST-1"],
    )


def _manifest_payload(manifest: ArtifactManifest):
    payload = asdict(manifest)
    payload["availability"] = manifest.availability.value
    payload["producer_kind"] = manifest.producer_kind.value
    return payload


def test_node_agent_resumes_partial_artifact_and_center_marks_available(tmp_path: Path) -> None:
    server, thread, _, artifact_repo, artifact_store, client = _stack(tmp_path)
    try:
        agent = _agent(client, tmp_path, "NODE-1")
        _register_and_lease(client, agent)
        content = "RC8截图证据".encode("utf-8") * 20
        source = tmp_path / "source.png"
        source.write_bytes(content)
        manifest = _manifest(content)

        client.post("/api/v1/artifacts/begin", _manifest_payload(manifest))
        client.put_bytes("/api/v1/artifacts/ART-HTTP-1/content?offset=0", content[:7])
        assert client.get("/api/v1/artifacts/ART-HTTP-1/offset")["offset"] == 7

        completed = agent.upload_artifact_file(manifest, str(source), chunk_size=11)
        assert completed["artifact"]["availability"] == "AVAILABLE"
        assert artifact_repo.get("ART-HTTP-1").availability.value == "AVAILABLE"
        assert artifact_store.content_path("ART-HTTP-1").read_bytes() == content
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_artifact_upload_requires_active_lease_owned_by_same_node(tmp_path: Path) -> None:
    server, thread, _, _, _, client = _stack(tmp_path)
    try:
        owner = _agent(client, tmp_path, "NODE-1")
        intruder = _agent(client, tmp_path, "NODE-2")
        _register_and_lease(client, owner)
        content = b"not-authorized"
        source = tmp_path / "intruder.log"
        source.write_bytes(content)
        manifest = _manifest(content, node_id="NODE-2", artifact_id="ART-INTRUDER")

        with pytest.raises(NodeAgentError, match="ACTIVE_WORK_ITEM_LEASE_REQUIRED"):
            intruder.upload_artifact_file(manifest, str(source), chunk_size=4)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_artifact_cannot_be_completed_after_work_item_completion(tmp_path: Path) -> None:
    server, thread, _, _, _, client = _stack(tmp_path)
    try:
        agent = _agent(client, tmp_path, "NODE-1")
        _register_and_lease(client, agent)
        content = b"pending-before-complete"
        manifest = _manifest(content)
        client.post("/api/v1/artifacts/begin", _manifest_payload(manifest))
        client.put_bytes("/api/v1/artifacts/ART-HTTP-1/content?offset=0", content)
        agent.complete("WI-ART")

        with pytest.raises(NodeAgentError, match="ACTIVE_WORK_ITEM_LEASE_REQUIRED"):
            client.post("/api/v1/artifacts/ART-HTTP-1/complete", {})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
