from __future__ import annotations

import threading
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine

from rc8_center.control_plane import WorkItemRecord, WorkItemState
from rc8_center.formal_control import FormalCenterControlPlane
from rc8_center.governance_event_projector import GovernanceEventProjector
from rc8_center.infrastructure import (
    Base,
    PostgresCenterRepository,
    PostgresStore,
    StageWorkItemLinkRow,
)
from rc8_center.infrastructure.postgres import MissionStageRow
from rc8_runtime import (
    CapabilityQualification,
    CapabilityState,
    CentralR1RuntimeLedger,
    NodeIdentity,
    WorkItemIdentity,
)


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


def _fixture():
    tmp = TemporaryDirectory()
    engine = create_engine("sqlite+pysqlite:///%s/claim.db" % tmp.name, future=True)
    Base.metadata.create_all(engine)
    store = PostgresStore(engine)
    repository = PostgresCenterRepository(store)
    coordination = FakeCoordination()
    ledger = CentralR1RuntimeLedger(str(Path(tmp.name) / "event-stream.jsonl"))
    projector = GovernanceEventProjector(ledger, None, None, None)  # claim/lease tests do not project runtime events
    control = FormalCenterControlPlane(repository, coordination, ledger, projector, now_fn=lambda: 1000)
    return tmp, store, repository, coordination, control


def _node(control: FormalCenterControlPlane, node_id: str) -> None:
    control.register_node(
        NodeIdentity(
            node_id=node_id,
            operator_ref="tester",
            os_family="windows",
            architecture="x86_64",
            shell="git-bash",
            registered_at=1,
        )
    )


def _verify(control: FormalCenterControlPlane, node_id: str, capability_id: str) -> None:
    control.qualify_capability(
        CapabilityQualification(
            node_id=node_id,
            capability_id=capability_id,
            state=CapabilityState.VERIFIED,
            probe_ref="probe:%s" % capability_id,
            evidence_refs=("evidence:%s" % capability_id,),
            verified_at=10,
        )
    )


def _work(repository: PostgresCenterRepository, work_id: str, *, run: str, stage: str, required=()):
    identity = WorkItemIdentity(
        work_item_id=work_id,
        test_run_id=run,
        stage=stage,
        scope_refs=("scope:1",),
        required_capabilities=tuple(required),
    )
    repository.upsert_work_item(WorkItemRecord(identity=identity, state=WorkItemState.READY))


def test_claim_next_filters_by_verified_capability_and_test_run() -> None:
    tmp, _store, repo, _coord, control = _fixture()
    try:
        _node(control, "node-a")
        _verify(control, "node-a", "CAN_DSH")
        _work(repo, "work-dsh", run="TR-A", stage="A_REQUIREMENT", required=("CAN_DSH",))
        _work(repo, "work-maven", run="TR-A", stage="B_EXECUTION", required=("CAN_MAVEN",))
        _work(repo, "work-other-run", run="TR-B", stage="A_REQUIREMENT", required=("CAN_DSH",))

        claimed = control.claim_next_work_item("node-a", test_run_id="TR-A")
        assert claimed is not None
        assert claimed.identity.work_item_id == "work-dsh"
        assert claimed.state == WorkItemState.LEASED
        assert claimed.lease_owner_node_id == "node-a"
        assert claimed.lease_id

        # Maven-only work is not silently assigned to the DSH-only node.
        assert control.claim_next_work_item("node-a", test_run_id="TR-A") is None
    finally:
        tmp.cleanup()


def test_claim_next_skips_redis_contended_candidate_and_claims_next_ready_item() -> None:
    tmp, _store, repo, coord, control = _fixture()
    try:
        _node(control, "node-a")
        _work(repo, "work-a", run="TR-A", stage="A_STAGE")
        _work(repo, "work-b", run="TR-A", stage="B_STAGE")
        assert coord.acquire_lease("work-item", "work-a", "node-other", 60, lease_id="foreign-lease") is True

        claimed = control.claim_next_work_item("node-a", test_run_id="TR-A")
        assert claimed is not None
        assert claimed.identity.work_item_id == "work-b"
        assert repo.get_work_item("work-a").state == WorkItemState.READY
    finally:
        tmp.cleanup()


def test_claim_next_never_reoffers_terminal_or_recovery_required_work() -> None:
    tmp, _store, repo, _coord, control = _fixture()
    try:
        _node(control, "node-a")
        _work(repo, "work-terminal", run="TR-A", stage="A_STAGE")
        terminal = repo.get_work_item("work-terminal")
        repo.upsert_work_item(WorkItemRecord(identity=terminal.identity, state=WorkItemState.COMPLETED))

        _work(repo, "work-recovery", run="TR-A", stage="B_STAGE")
        recovery = repo.get_work_item("work-recovery")
        repo.upsert_work_item(
            WorkItemRecord(
                identity=recovery.identity,
                state=WorkItemState.LEASED,
                lease_id="lost-redis-lease",
                lease_owner_node_id="node-a",
                lease_expires_at=999,
            )
        )

        assert control.claim_next_work_item("node-a", test_run_id="TR-A") is None
        assert repo.get_work_item("work-terminal").state == WorkItemState.COMPLETED
        assert repo.get_work_item("work-recovery").state == WorkItemState.LEASED
    finally:
        tmp.cleanup()


def test_exact_stage_instance_lineage_is_resolvable_for_claimed_work() -> None:
    tmp, store, repo, _coord, control = _fixture()
    try:
        _node(control, "node-a")
        with store.session() as session:
            session.add(
                MissionStageRow(
                    stage_instance_id="stage-1",
                    test_run_id="TR-A",
                    stage_type="SCOPE_INTAKE",
                    scope_version="delivery-scope:S1",
                    attempt_no=1,
                    state="READY",
                    input_refs=[], output_refs=[], gap_refs=[], invalidation_refs=[],
                    predecessor_ids=[], successor_ids=[],
                    assigned_worker=None, evaluator_id=None, policy_version="p1",
                    started_at=None, finished_at=None, created_at=1, updated_at=1, payload={},
                )
            )
        _work(repo, "work-1", run="TR-A", stage="SCOPE_INTAKE")
        repo.link_work_item_to_stage(
            work_item_id="work-1",
            stage_instance_id="stage-1",
            test_run_id="TR-A",
            created_at=2,
        )

        claimed = control.claim_next_work_item("node-a", test_run_id="TR-A")
        assert claimed is not None
        assert control.stage_instance_id_for_work_item(claimed.identity.work_item_id) == "stage-1"
    finally:
        tmp.cleanup()
