from __future__ import annotations

import threading
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from sqlalchemy import create_engine

from rc8_center.control_plane import CenterControlError, WorkItemRecord, WorkItemState
from rc8_center.formal_control import FormalCenterControlPlane
from rc8_center.infrastructure import (
    Base,
    PostgresArtifactRepository,
    PostgresCenterRepository,
    PostgresCoverageRepository,
    PostgresGovernanceRepository,
    PostgresStore,
)
from rc8_center.runtime_mutation_producer import RuntimeMutationAwareFormalCenterControlPlane
from rc8_center.scope_aware_governance_projector import ScopeAwareGovernanceEventProjector
from rc8_runtime import (
    ArtifactAvailability,
    CentralR1RuntimeLedger,
    NodeIdentity,
    RuntimeProducerKind,
    WorkItemIdentity,
    runtime_event,
)
from rc8_runtime.artifacts import ArtifactManifest
from rc8_runtime.governance import AttemptStatus, StageInstance, StageState


class FakeCoordination:
    def __init__(self) -> None:
        self._leases = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(kind: str, resource_id: str):
        return kind, resource_id

    def lease_info(self, kind: str, resource_id: str):
        with self._lock:
            value = self._leases.get(self._key(kind, resource_id))
            return dict(value) if value is not None else None

    def acquire_lease(self, kind: str, resource_id: str, owner_id: str, ttl_seconds: int, *, lease_id: str):
        with self._lock:
            key = self._key(kind, resource_id)
            if key in self._leases:
                return False
            self._leases[key] = {"owner_id": owner_id, "lease_id": lease_id, "ttl_seconds": ttl_seconds}
            return True

    def renew_lease(self, kind: str, resource_id: str, owner_id: str, ttl_seconds: int, *, lease_id: str):
        with self._lock:
            value = self._leases.get(self._key(kind, resource_id))
            if value is None or value["owner_id"] != owner_id or value["lease_id"] != lease_id:
                return False
            value["ttl_seconds"] = ttl_seconds
            return True

    def release_lease(self, kind: str, resource_id: str, owner_id: str, *, lease_id: str):
        with self._lock:
            key = self._key(kind, resource_id)
            value = self._leases.get(key)
            if value is None or value["owner_id"] != owner_id or value["lease_id"] != lease_id:
                return False
            del self._leases[key]
            return True


class NoopMutationProducer:
    def process_runtime_event(self, _event):
        return None


def _fixture():
    tmp = TemporaryDirectory()
    engine = create_engine("sqlite+pysqlite:///%s/attempt-authority.db" % tmp.name, future=True)
    Base.metadata.create_all(engine)
    store = PostgresStore(engine)
    control_repository = PostgresCenterRepository(store)
    governance_repository = PostgresGovernanceRepository(store)
    coverage_repository = PostgresCoverageRepository(store)
    artifact_repository = PostgresArtifactRepository(store)
    coordination = FakeCoordination()
    ledger = CentralR1RuntimeLedger(str(Path(tmp.name) / "event-stream.jsonl"))
    projector = ScopeAwareGovernanceEventProjector(
        ledger,
        governance_repository,
        coverage_repository,
        artifact_repository,
    )
    core = FormalCenterControlPlane(
        control_repository,
        coordination,
        ledger,
        projector,
        now_fn=lambda: 1000,
    )
    control = RuntimeMutationAwareFormalCenterControlPlane(core, NoopMutationProducer())

    governance_repository.upsert_stage(
        StageInstance(
            stage_instance_id="stage-1",
            test_run_id="run-1",
            stage_type="COVERAGE_DRIVEN_EXECUTION_CLOSURE",
            scope_version="delivery-scope:S1",
            attempt_no=1,
            state=StageState.READY,
        )
    )
    control_repository.upsert_work_item(
        WorkItemRecord(
            identity=WorkItemIdentity(
                work_item_id="work-1",
                test_run_id="run-1",
                stage="COVERAGE_DRIVEN_EXECUTION_CLOSURE",
                scope_refs=("delivery-scope:S1", "stage-instance:stage-1"),
                required_capabilities=(),
            ),
            state=WorkItemState.READY,
        )
    )
    control_repository.link_work_item_to_stage(
        work_item_id="work-1",
        stage_instance_id="stage-1",
        test_run_id="run-1",
        created_at=1,
    )
    control.register_node(
        NodeIdentity(
            node_id="node-1",
            operator_ref="attempt-authority-test",
            os_family="linux",
            architecture="x86_64",
            shell="bash",
            registered_at=1,
        )
    )
    lease = control.lease_work_item("work-1", "node-1", ttl_seconds=120)
    assert lease.lease_id
    return tmp, control, ledger, governance_repository, artifact_repository, lease


def test_center_start_creates_canonical_attempt_from_active_lease() -> None:
    tmp, control, ledger, governance, _artifacts, lease = _fixture()
    try:
        started = control.start_work_item("work-1", "node-1", lease.lease_id)
        assert started.state == WorkItemState.RUNNING
        events = ledger.runtime_events(test_run_id="run-1", work_item_id="work-1")
        assert len(events) == 1
        event = events[0]
        assert event["event_type"] == "ATTEMPT_STARTED"
        assert event["attempt_id"] == lease.lease_id
        assert event["producer_ref"] == "rc8-center-attempt-authority"
        assert event["data"]["stage_instance_id"] == "stage-1"
        assert event["data"]["input_snapshot_ref"] == "delivery-scope:S1"
        attempt = governance.get_attempt(lease.lease_id)
        assert attempt.status == AttemptStatus.STARTED
        assert attempt.producer_ref == "rc8-center-attempt-authority"
        control.start_work_item("work-1", "node-1", lease.lease_id)
        assert len(ledger.runtime_events(test_run_id="run-1", work_item_id="work-1")) == 1
    finally:
        tmp.cleanup()


def test_worker_cannot_create_or_rename_mission_attempt() -> None:
    tmp, control, ledger, _governance, _artifacts, lease = _fixture()
    try:
        control.start_work_item("work-1", "node-1", lease.lease_id)
        next_sequence = ledger.latest_node_sequence(test_run_id="run-1", node_id="node-1") + 1
        worker_start = runtime_event(
            event_id="worker-start",
            test_run_id="run-1",
            work_item_id="work-1",
            node_id="node-1",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="worker:l7",
            event_type="ATTEMPT_STARTED",
            sequence=next_sequence,
            attempt_id=lease.lease_id,
            data={"stage_instance_id": "stage-1", "input_snapshot_ref": "delivery-scope:S1"},
            occurred_at=1001,
        )
        with pytest.raises(CenterControlError, match="CENTER_OWNS_ATTEMPT_START"):
            control.append_runtime_event(worker_start, lease_id=lease.lease_id)
        wrong_terminal = runtime_event(
            event_id="wrong-terminal",
            test_run_id="run-1",
            work_item_id="work-1",
            node_id="node-1",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="worker:l7",
            event_type="ATTEMPT_COMPLETED",
            sequence=next_sequence,
            attempt_id="attempt-chosen-by-worker",
            data={},
            occurred_at=1002,
        )
        with pytest.raises(CenterControlError, match="ATTEMPT_ID_MUST_MATCH_ACTIVE_LEASE"):
            control.append_runtime_event(wrong_terminal, lease_id=lease.lease_id)
        assert len(ledger.runtime_events(test_run_id="run-1", work_item_id="work-1")) == 1
    finally:
        tmp.cleanup()


def test_worker_terminal_fact_keeps_r1_provenance_without_rewriting_attempt_authority() -> None:
    tmp, control, ledger, governance, artifacts, lease = _fixture()
    try:
        control.start_work_item("work-1", "node-1", lease.lease_id)
        artifacts.upsert(
            ArtifactManifest(
                artifact_id="ART-JUNIT",
                test_run_id="run-1",
                work_item_id="work-1",
                node_id="node-1",
                kind="JUNIT_XML",
                producer_kind=RuntimeProducerKind.WORKER,
                producer_ref="worker:l7",
                file_name="TEST.xml",
                sha256="0" * 64,
                size_bytes=1,
                availability=ArtifactAvailability.AVAILABLE,
                attempt_id=lease.lease_id,
                created_at=1001,
            )
        )
        terminal = runtime_event(
            event_id="terminal-1",
            test_run_id="run-1",
            work_item_id="work-1",
            node_id="node-1",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="worker:l7",
            event_type="ATTEMPT_COMPLETED",
            sequence=ledger.latest_node_sequence(test_run_id="run-1", node_id="node-1") + 1,
            attempt_id=lease.lease_id,
            refs=["ART-JUNIT"],
            data={
                "finished_at": 1002,
                "evidence_refs": ["ART-JUNIT"],
                "action_refs": ["action:execute-case"],
                "assertion_refs": ["assertion:expected-vs-actual"],
            },
            occurred_at=1002,
        )
        result = control.append_runtime_event(terminal, lease_id=lease.lease_id)
        assert result["projection"]["projection"]["status"] == "PROJECTED"
        r1_terminal = ledger.runtime_events(test_run_id="run-1", work_item_id="work-1")[-1]
        assert r1_terminal["producer_ref"] == "worker:l7"
        attempt = governance.get_attempt(lease.lease_id)
        assert attempt.status == AttemptStatus.COMPLETED
        assert attempt.producer_ref == "rc8-center-attempt-authority"
        assert attempt.input_snapshot_ref == "delivery-scope:S1"
        assert attempt.evidence_refs == ("ART-JUNIT",)
    finally:
        tmp.cleanup()
