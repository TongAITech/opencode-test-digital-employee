from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from rc8_center.autonomous_progression import AutonomousMissionProgressor, AutonomousProgressionError
from rc8_center.control_plane import WorkItemState
from rc8_center.delivery import ProductionBatch, Requirement, RequirementDelivery, RequirementDeliveryScope
from rc8_center.infrastructure import (
    Base,
    PostgresArtifactRepository,
    PostgresCenterRepository,
    PostgresGovernanceRepository,
    PostgresRequirementDeliveryRepository,
    PostgresStore,
    PostgresTestRoundRepository,
)
from rc8_center.mission_service import CenterMissionService
from rc8_runtime import ArtifactAvailability, AttemptRecord, AttemptStatus, RuntimeProducerKind
from rc8_runtime.artifacts import ArtifactManifest
from rc8_runtime.governance import FailureOwnership, StageState
from rc8_runtime.mission_graph import MissionStageType


def _fixture():
    engine = create_engine(
        "sqlite+pysqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    store = PostgresStore(engine)
    delivery = PostgresRequirementDeliveryRepository(store)
    rounds = PostgresTestRoundRepository(store)
    governance = PostgresGovernanceRepository(store)
    control = PostgresCenterRepository(store)
    artifacts = PostgresArtifactRepository(store)
    mission = CenterMissionService(governance)
    progressor = AutonomousMissionProgressor(
        store=store,
        mission_service=mission,
        governance_repository=governance,
        control_repository=control,
        artifact_repository=artifacts,
    )

    delivery.create_batch(
        ProductionBatch(
            production_batch_id="PB-1",
            production_date="2026-11-15",
            name="11月15日投产",
            created_at=100,
        )
    )
    delivery.create_requirement(Requirement(requirement_id="REQ-1", title="需求一", created_at=100))
    delivery.create_delivery(
        RequirementDelivery(
            delivery_id="DEL-1",
            production_batch_id="PB-1",
            requirement_id="REQ-1",
            created_at=100,
            updated_at=100,
        )
    )
    delivery.create_scope(
        RequirementDeliveryScope(
            scope_id="SCOPE-1",
            delivery_id="DEL-1",
            system_id="PFC",
            system_version="V1",
            application_id="cfg-center",
            sst_id="SST-1",
            created_at=100,
        )
    )
    rounds.create_next_round("PB-1", ["DEL-1"], requested_test_round_id="ROUND-1", now=100)
    _round, run = rounds.start_runtime_mission("ROUND-1", "TR-1", now=101)
    work_id = run.payload["mission_initial_work_item_ids"][0]
    stage_id = run.payload["mission_initial_ready_stage_ids"][0]
    return store, governance, control, artifacts, progressor, work_id, stage_id


def _complete_attempt(governance, artifacts, control, work_id: str, stage_id: str, *, artifact_id: str = "EV-1"):
    manifest = ArtifactManifest(
        artifact_id=artifact_id,
        test_run_id="TR-1",
        work_item_id=work_id,
        node_id="NODE-1",
        kind="STAGE_EVIDENCE",
        producer_kind=RuntimeProducerKind.WORKER,
        producer_ref="worker:test",
        file_name="evidence.json",
        sha256="a" * 64,
        size_bytes=10,
        availability=ArtifactAvailability.AVAILABLE,
        attempt_id="ATT-1",
        refs=["stage:%s" % stage_id],
        created_at=102,
    )
    artifacts.upsert(manifest)
    governance.upsert_attempt(
        AttemptRecord(
            attempt_id="ATT-1",
            test_run_id="TR-1",
            stage_instance_id=stage_id,
            work_item_id=work_id,
            producer_node_id="NODE-1",
            producer_ref="worker:test",
            input_snapshot_ref="snapshot:1",
            status=AttemptStatus.COMPLETED,
            evidence_refs=("artifact:%s" % artifact_id,),
            started_at=102,
            finished_at=103,
        )
    )
    work = control.get_work_item(work_id)
    assert work is not None
    control.upsert_work_item(replace(work, state=WorkItemState.COMPLETED))


def _failure_attempt(
    governance,
    artifacts,
    control,
    work_id: str,
    stage_id: str,
    *,
    status: AttemptStatus,
    artifact_id: str,
):
    attempt_id = "ATT-%s" % status.value
    artifacts.upsert(
        ArtifactManifest(
            artifact_id=artifact_id,
            test_run_id="TR-1",
            work_item_id=work_id,
            node_id="NODE-1",
            kind="FAILURE_EVIDENCE",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="worker:test",
            file_name="failure.json",
            sha256="c" * 64,
            size_bytes=10,
            availability=ArtifactAvailability.AVAILABLE,
            attempt_id=attempt_id,
            refs=["stage:%s" % stage_id],
            created_at=104,
        )
    )
    governance.upsert_attempt(
        AttemptRecord(
            attempt_id=attempt_id,
            test_run_id="TR-1",
            stage_instance_id=stage_id,
            work_item_id=work_id,
            producer_node_id="NODE-1",
            producer_ref="worker:test",
            input_snapshot_ref="snapshot:1",
            status=status,
            evidence_refs=("artifact:%s" % artifact_id,),
            failure_ownership=(FailureOwnership.MODEL if status == AttemptStatus.FAILED_RUNTIME else FailureOwnership.DEPENDENCY),
            started_at=102,
            finished_at=105,
        )
    )
    work = control.get_work_item(work_id)
    assert work is not None
    terminal = WorkItemState.BLOCKED if status == AttemptStatus.BLOCKED else WorkItemState.FAILED
    control.upsert_work_item(replace(work, state=terminal))


def test_completed_evidence_backed_work_unlocks_next_stage_and_materializes_work() -> None:
    _store, governance, control, artifacts, progressor, work_id, stage_id = _fixture()

    leased = progressor.on_work_item_leased(work_id)
    assert leased is not None and leased.state == StageState.LEASED
    executing = progressor.on_work_item_started(work_id)
    assert executing is not None and executing.state == StageState.EXECUTING
    _complete_attempt(governance, artifacts, control, work_id, stage_id)

    outcome = progressor.reconcile_completed_work_item(work_id)
    assert outcome.source_stage_state == StageState.COMPLETED.value
    assert len(outcome.newly_ready_stage_ids) == 1
    assert len(outcome.materialized_work_item_ids) == 1

    source = governance.get_stage(stage_id)
    assert source is not None and source.state == StageState.COMPLETED
    next_stage = governance.get_stage(outcome.newly_ready_stage_ids[0])
    assert next_stage is not None
    assert next_stage.stage_type == MissionStageType.REQUIREMENT_ANALYSIS.value
    assert next_stage.state == StageState.READY

    next_work = control.get_work_item(outcome.materialized_work_item_ids[0])
    assert next_work is not None
    assert next_work.state == WorkItemState.READY
    assert next_work.identity.stage == MissionStageType.REQUIREMENT_ANALYSIS.value
    link = control.get_stage_link_for_work_item(next_work.identity.work_item_id)
    assert link is not None and link.stage_instance_id == next_stage.stage_instance_id


def test_mission_work_item_cannot_complete_without_projected_completed_attempt() -> None:
    _store, _governance, _control, _artifacts, progressor, work_id, _stage_id = _fixture()
    progressor.on_work_item_leased(work_id)
    progressor.on_work_item_started(work_id)
    with pytest.raises(
        AutonomousProgressionError,
        match="MISSION_WORK_ITEM_COMPLETION_REQUIRES_PROJECTED_COMPLETED_ATTEMPT",
    ):
        progressor.assert_work_item_completable(work_id)


def test_mission_work_item_cannot_complete_when_evidence_artifact_is_not_available() -> None:
    _store, governance, control, artifacts, progressor, work_id, stage_id = _fixture()
    progressor.on_work_item_leased(work_id)
    progressor.on_work_item_started(work_id)
    artifacts.upsert(
        ArtifactManifest(
            artifact_id="EV-PENDING",
            test_run_id="TR-1",
            work_item_id=work_id,
            node_id="NODE-1",
            kind="STAGE_EVIDENCE",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="worker:test",
            file_name="pending.json",
            sha256="b" * 64,
            size_bytes=10,
            availability=ArtifactAvailability.PENDING_UPLOAD,
            attempt_id="ATT-PENDING",
            refs=["stage:%s" % stage_id],
            created_at=102,
        )
    )
    governance.upsert_attempt(
        AttemptRecord(
            attempt_id="ATT-PENDING",
            test_run_id="TR-1",
            stage_instance_id=stage_id,
            work_item_id=work_id,
            producer_node_id="NODE-1",
            producer_ref="worker:test",
            input_snapshot_ref="snapshot:1",
            status=AttemptStatus.COMPLETED,
            evidence_refs=("artifact:EV-PENDING",),
            started_at=102,
            finished_at=103,
        )
    )
    work = control.get_work_item(work_id)
    assert work is not None
    control.upsert_work_item(replace(work, state=WorkItemState.COMPLETED))
    with pytest.raises(AutonomousProgressionError, match="MISSION_COMPLETION_EVIDENCE_NOT_AVAILABLE"):
        progressor.reconcile_completed_work_item(work_id)


def test_failure_requires_projected_terminal_attempt() -> None:
    _store, _governance, _control, _artifacts, progressor, work_id, _stage_id = _fixture()
    progressor.on_work_item_leased(work_id)
    progressor.on_work_item_started(work_id)
    with pytest.raises(
        AutonomousProgressionError,
        match="MISSION_WORK_ITEM_FAILURE_REQUIRES_PROJECTED_TERMINAL_ATTEMPT",
    ):
        progressor.assert_work_item_failable(work_id)


@pytest.mark.parametrize(
    ("attempt_status", "work_state", "stage_state", "artifact_id"),
    [
        (AttemptStatus.FAILED_RUNTIME, WorkItemState.FAILED, StageState.FAILED_RUNTIME, "EV-FAIL"),
        (AttemptStatus.BLOCKED, WorkItemState.BLOCKED, StageState.BLOCKED, "EV-BLOCK"),
    ],
)
def test_evidenced_failure_terminalizes_stage_without_downstream_unlock(
    attempt_status: AttemptStatus,
    work_state: WorkItemState,
    stage_state: StageState,
    artifact_id: str,
) -> None:
    _store, governance, control, artifacts, progressor, work_id, stage_id = _fixture()
    progressor.on_work_item_leased(work_id)
    progressor.on_work_item_started(work_id)
    _failure_attempt(
        governance,
        artifacts,
        control,
        work_id,
        stage_id,
        status=attempt_status,
        artifact_id=artifact_id,
    )
    gate = progressor.assert_work_item_failable(work_id)
    assert gate.work_item_state == work_state
    assert gate.stage_state == stage_state

    outcome = progressor.reconcile_failed_work_item(work_id)
    assert outcome.source_stage_state == stage_state.value
    assert outcome.newly_ready_stage_ids == tuple()
    assert outcome.materialized_work_item_ids == tuple()
    source = governance.get_stage(stage_id)
    assert source is not None and source.state == stage_state
    requirement_analysis = [
        item for item in governance.list_stages("TR-1")
        if item.stage_type == MissionStageType.REQUIREMENT_ANALYSIS.value
    ]
    assert len(requirement_analysis) == 1
    assert requirement_analysis[0].state == StageState.PENDING


def test_reconciliation_is_idempotent_after_stage_completion() -> None:
    _store, governance, control, artifacts, progressor, work_id, stage_id = _fixture()
    progressor.on_work_item_leased(work_id)
    progressor.on_work_item_started(work_id)
    _complete_attempt(governance, artifacts, control, work_id, stage_id)
    first = progressor.reconcile_completed_work_item(work_id)
    second = progressor.reconcile_completed_work_item(work_id)
    assert first.source_stage_state == second.source_stage_state == StageState.COMPLETED.value
    assert second.newly_ready_stage_ids == tuple()
    assert second.materialized_work_item_ids == tuple()
