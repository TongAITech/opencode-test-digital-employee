from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from rc8_center import CenterControlPlane, MemoryCenterRepository
from rc8_center.artifacts import FileArtifactStore, MemoryArtifactRepository
from rc8_center.http_server import CenterHttpApplication, create_server
from rc8_node import HttpCenterClient, NodeAgent, NodeIdentityStore
from rc8_node.capabilities import CapabilityAdapterError, MavenJUnitCapabilityAdapter
from rc8_runtime import CapabilityState, CentralR1RuntimeLedger


def _fake_maven(tmp_path: Path, *, success: bool) -> str:
    """Create a directly executable fake Maven command on both CI platforms.

    Windows CreateProcess does not execute an extensionless bash script directly,
    so use a .cmd shim there. Linux keeps the executable bash script. This keeps
    the adapter test about a real subprocess rather than mocking subprocess.run.
    """
    if os.name == "nt":
        path = tmp_path / "mvn.cmd"
        if success:
            path.write_text("@echo off\r\necho Apache Maven RC8-test\r\nexit /b 0\r\n", encoding="utf-8")
        else:
            path.write_text("@echo off\r\necho broken maven 1>&2\r\nexit /b 9\r\n", encoding="utf-8")
    else:
        path = tmp_path / "mvn"
        if success:
            path.write_text("#!/usr/bin/env bash\necho 'Apache Maven RC8-test'\nexit 0\n", encoding="utf-8")
        else:
            path.write_text("#!/usr/bin/env bash\necho 'broken maven' >&2\nexit 9\n", encoding="utf-8")
        path.chmod(0o755)
    return str(path)


def test_successful_real_subprocess_probe_stays_probing_until_evidence_bound(tmp_path: Path) -> None:
    adapter = MavenJUnitCapabilityAdapter(str(tmp_path / "evidence"), maven_command=_fake_maven(tmp_path, success=True))
    result = adapter.probe()
    assert result.returncode == 0
    assert result.state == CapabilityState.PROBING
    assert "Apache Maven" in result.stdout
    evidence = Path(result.evidence_path)
    assert evidence.is_file()
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["probe_state"] == "PROBING"
    qualification = adapter.qualification_before_upload("node-1", result)
    assert qualification.state == CapabilityState.PROBING
    assert qualification.evidence_refs == []


def test_verified_requires_successful_probe_and_uploaded_artifact_reference(tmp_path: Path) -> None:
    adapter = MavenJUnitCapabilityAdapter(str(tmp_path / "evidence"), maven_command=_fake_maven(tmp_path, success=True))
    result = adapter.probe()
    verified = adapter.verified_qualification("node-1", result, "artifact-probe-1", verified_at=123)
    assert verified.state == CapabilityState.VERIFIED
    assert verified.evidence_refs == ["artifact-probe-1"]
    assert verified.verified_at == 123


def test_failed_tool_probe_is_degraded_and_cannot_be_verified(tmp_path: Path) -> None:
    adapter = MavenJUnitCapabilityAdapter(str(tmp_path / "evidence"), maven_command=_fake_maven(tmp_path, success=False))
    result = adapter.probe()
    assert result.returncode == 9
    assert result.state == CapabilityState.DEGRADED
    with pytest.raises(CapabilityAdapterError, match="CAPABILITY_PROBE_NOT_SUCCESSFUL"):
        adapter.verified_qualification("node-1", result, "artifact-probe-1")


def test_missing_maven_is_unavailable_not_verified(tmp_path: Path) -> None:
    adapter = MavenJUnitCapabilityAdapter(str(tmp_path / "evidence"), maven_command=str(tmp_path / "missing-mvn"))
    result = adapter.probe()
    assert result.returncode is None
    assert result.state == CapabilityState.UNAVAILABLE
    qualification = adapter.qualification_before_upload("node-1", result)
    assert qualification.state == CapabilityState.UNAVAILABLE


def test_successful_probe_uploads_center_artifact_before_verified(tmp_path: Path) -> None:
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
            node_id="NODE-CAP-1",
            operator_ref="tester",
            os_family="windows",
            architecture="x86_64",
            shell="git-bash",
            now=100,
        )
        agent = NodeAgent(identity, client)
        agent.register()
        agent.heartbeat()
        client.post(
            "/api/v1/work-items/register",
            {
                "work_item_id": "WI-CAP-1",
                "test_run_id": "RUN-CAP-1",
                "stage": "CAPABILITY_QUALIFICATION",
                "scope_refs": ["NODE-CAP-1"],
                "required_capabilities": [],
            },
        )
        agent.lease("WI-CAP-1", ttl_seconds=120)
        agent.start("WI-CAP-1")

        adapter = MavenJUnitCapabilityAdapter(
            str(tmp_path / "probe-evidence"),
            maven_command=_fake_maven(tmp_path, success=True),
        )
        qualification = adapter.qualify_through_center(
            agent,
            test_run_id="RUN-CAP-1",
            work_item_id="WI-CAP-1",
            artifact_id="ART-CAP-MVN-1",
            verified_at=123,
        )

        assert qualification.state == CapabilityState.VERIFIED
        assert qualification.evidence_refs == ["ART-CAP-MVN-1"]
        stored = repo.get_capability("NODE-CAP-1", "maven-junit")
        assert stored is not None and stored.state == CapabilityState.VERIFIED
        artifact = artifact_repo.get("ART-CAP-MVN-1")
        assert artifact is not None and artifact.availability.value == "AVAILABLE"
        assert artifact.sha256 == Path(adapter.evidence_dir / "maven-junit-probe.json").read_bytes() and False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
