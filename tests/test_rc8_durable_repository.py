from __future__ import annotations

import hashlib
from pathlib import Path

from rc8_center import CenterControlPlane
from rc8_center.artifacts import FileArtifactStore
from rc8_center.json_repository import JsonFileArtifactRepository, JsonFileCenterRepository
from rc8_runtime import (
    ArtifactAvailability,
    CapabilityQualification,
    CapabilityState,
    CentralR1RuntimeLedger,
    NodeIdentity,
    RuntimeProducerKind,
    WorkItemIdentity,
    runtime_event,
)
from rc8_runtime.artifacts import ArtifactManifest


class Clock:
    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def test_center_node_work_and_capability_survive_repository_restart(tmp_path: Path) -> None:
    state_path = tmp_path / "center-state.json"
    r1_path = tmp_path / "r1.jsonl"
    clock = Clock(100)

    repo1 = JsonFileCenterRepository(str(state_path))
    center1 = CenterControlPlane(repo1, CentralR1RuntimeLedger(str(r1_path)), now_fn=clock)
    identity = NodeIdentity(
        node_id="NODE-1",
        operator_ref="tester",
        os_family="windows",
        architecture="x86_64",
        shell="git-bash",
        registered_at=50,
    )
    center1.register_node(identity)
    center1.qualify_capability(
        CapabilityQualification(
            node_id="NODE-1",
            capability_id="CAN_CODEGRAPH",
            state=CapabilityState.VERIFIED,
            probe_ref="probe://cg/1",
            evidence_refs=["ART-PROBE"],
            verified_at=100,
        )
    )
    center1.register_work_item(
        WorkItemIdentity(
            work_item_id="WI-1",
            test_run_id="RUN-1",
            stage="EXECUTION",
            scope_refs=["SCOPE-1"],
            required_capabilities=["CAN_CODEGRAPH"],
        )
    )
    leased = center1.lease_work_item("WI-1", "NODE-1", ttl_seconds=60)
    assert leased.lease_owner_node_id == "NODE-1"

    # Simulate Center process restart while the lease is still valid.
    repo2 = JsonFileCenterRepository(str(state_path))
    center2 = CenterControlPlane(repo2, CentralR1RuntimeLedger(str(r1_path)), now_fn=Clock(110))
    assert repo2.get_node("NODE-1").identity == identity
    assert repo2.get_capability("NODE-1", "CAN_CODEGRAPH").state == CapabilityState.VERIFIED
    restored_work = repo2.get_work_item("WI-1")
    assert restored_work.lease_owner_node_id == "NODE-1"
    assert restored_work.lease_expires_at == 160

    receipt = center2.append_runtime_event(
        runtime_event(
            event_id="EV-AFTER-RESTART",
            test_run_id="RUN-1",
            work_item_id="WI-1",
            node_id="NODE-1",
            producer_kind=RuntimeProducerKind.TOOL,
            producer_ref="codegraph",
            event_type="TOOL_EXECUTED",
            sequence=1,
        )
    )
    assert receipt["status"] == "PERSISTENCE_VERIFIED"


def test_completed_work_item_stays_completed_after_restart(tmp_path: Path) -> None:
    state_path = tmp_path / "center-state.json"
    r1_path = tmp_path / "r1.jsonl"
    center1 = CenterControlPlane(
        JsonFileCenterRepository(str(state_path)),
        CentralR1RuntimeLedger(str(r1_path)),
        now_fn=Clock(100),
    )
    center1.register_node(
        NodeIdentity("NODE-1", "tester", "windows", "x86_64", "git-bash", registered_at=1)
    )
    center1.register_work_item(
        WorkItemIdentity("WI-1", "RUN-1", "EXECUTION", ["SCOPE-1"], [])
    )
    center1.lease_work_item("WI-1", "NODE-1", ttl_seconds=60)
    center1.start_work_item("WI-1", "NODE-1")
    center1.complete_work_item("WI-1", "NODE-1")

    repo2 = JsonFileCenterRepository(str(state_path))
    restored = repo2.get_work_item("WI-1")
    assert restored.state.value == "COMPLETED"
    assert restored.lease_owner_node_id is None
    assert restored.lease_expires_at is None


def test_available_artifact_metadata_and_content_survive_restart(tmp_path: Path) -> None:
    metadata_path = tmp_path / "artifact-metadata.json"
    storage_root = tmp_path / "artifact-bytes"
    content = "截图/日志/脚本等资产".encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()

    repo1 = JsonFileArtifactRepository(str(metadata_path))
    store1 = FileArtifactStore(str(storage_root), repo1)
    manifest = ArtifactManifest(
        artifact_id="ART-1",
        test_run_id="RUN-1",
        work_item_id="WI-1",
        node_id="NODE-1",
        kind="LOG",
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="runner",
        file_name="执行日志.txt",
        sha256=digest,
        size_bytes=len(content),
        refs=["EV-1", "AST-1"],
    )
    store1.begin(manifest)
    store1.upload_chunk("ART-1", offset=0, data=content)
    assert store1.complete("ART-1").availability == ArtifactAvailability.AVAILABLE

    repo2 = JsonFileArtifactRepository(str(metadata_path))
    store2 = FileArtifactStore(str(storage_root), repo2)
    restored = repo2.get("ART-1")
    assert restored.availability == ArtifactAvailability.AVAILABLE
    assert store2.content_path("ART-1").read_bytes() == content
