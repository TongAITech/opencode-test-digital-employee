from __future__ import annotations

from dataclasses import replace

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from rc8_center.control_plane import WorkItemRecord, WorkItemState
from rc8_center.delivery import (
    ProductionBatch,
    Requirement,
    RequirementDelivery,
    RequirementDeliveryScope,
)
from rc8_center.fanout_progression import FanoutSafeRequirementLoopProgressor
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
from rc8_runtime import (
    ArtifactAvailability,
    AttemptRecord,
    AttemptStatus,
    RuntimeProducerKind,
    WorkItemIdentity,
)
from rc8_runtime.artifacts import ArtifactManifest
from rc8_runtime.governance import StageState
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
    progressor = FanoutSafeRequirementLoopProgressor(
        store=store,
        mission_service=mission,
        governance_repository=governance,
        control_repository=control,
        artifact_repository=artifacts,
    )

    delivery.create_batch(
        ProductionBatch(
            production_batch_id="PB-FANOUT",
            production_date="2026-11-16",
            name="fanout",
            created_at=100,
        )
    )
    delivery.create_requirement(
        Requirement(requirement_id="REQ-FANOUT", title="fanout requirement", created_at=100)
    )
    delivery.create_delivery(
        RequirementDelivery(
            delivery_id="DEL-FANOUT",
            production_batch_id="PB-FANOUT",
            requirement_id="REQ-FANOUT",
            created_at=100,
            updated_at=100,
        )
    )
    delivery.create_scope(
        RequirementDeliveryScope(
            scope_id="SCOPE-FANOUT",
            delivery_id="DEL-FANOUT",
            system_id="PFC",
            system_version="V1",
            application_id="cfg-center",
            sst_id="SST-FANOUT",
            created_at=100,
        )
    )
    rounds.create_next_round(
        "PB-FANOUT",
        ["DEL-FANOUT"],
        requested_test_round_id="ROUND-FANOUT",
        now=100,
    )
    _round, run = rounds.start_runtime_mission(
        "ROUND-FANOUT",
        "TR-FANOUT",
        now=101,
    )
    work_id = run.payload["mission_initial_work_item_ids"][0]
    stage_id = run.payload["mission_initial_ready_stage_ids"][0]
    first = control.get_work_item(work_id)
    assert first is not None

    second_id = work_id + "-case-2"
    control.upsert_work_item(
        WorkItemRecord(
            identity=WorkItemIdentity(
                work_item_id=second_id,
                test_run_id=first.identity.test_run_id,
                stage=first.identity.stage,
                scope_refs=list(first.identity.scope_refs) + ["case:CASE-2"],
                required_capabilities=list(first.identity.required_capabilities),
            ),
            state=WorkItemState.READY,
        )
    )
    control.link_work_item_to_stage(
        work_item_id=second_id,
        stage_instance_id=stage_id,
        test_run_id="TR-FANOUT",
        created_at=102,
    )
    return governance, control, artifacts, progressor, work_id, second_id, stage_id


def _complete(
    governance,
    control,
    artifacts,
    *,
    work_id: str,
    stage_id: str,
    attempt_id: str,
    artifact_id: str,
):
    artifacts.upsert(
        ArtifactManifest(
            artifact_id=artifact_id,
            test_run_id="TR-FANOUT",
            work_item_id=work_id,
            node_id="NODE-1",
            kind="STAGE_EVIDENCE",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="worker:fanout",
            file_name=artifact_id + ".json",
            sha256=("a" if artifact_id.endswith("1") else "b") * 64,
            size_bytes=10,
            availability=ArtifactAvailability.AVAILABLE,
            attempt_id=attempt_id,
            refs=["stage:%s" % stage_id],
            created_at=103,
        )
    )
    governance.upsert_attempt(
        AttemptRecord(
            attempt_id=attempt_id,
            test_run_id="TR-FANOUT",
            stage_instance_id=stage_id,
            work_item_id=work_id,
            producer_node_id="NODE-1",
            producer_ref="worker:fanout",
            input_snapshot_ref="snapshot:fanout",
            status=AttemptStatus.COMPLETED,
            evidence_refs=("artifact:%s" % artifact_id,),
            started_at=103,
            finished_at=104,
        )
    )
    work = control.get_work_item(work_id)
    assert work is not None
    control.upsert_work_item(replace(work, state=WorkItemState.COMPLETED))


def test_first_completed_fanout_work_item_cannot_complete_stage():
    governance, control, artifacts, progressor, first_id, second_id, stage_id = _fixture()
    progressor.on_work_item_leased(first_id)
    progressor.on_work_item_started(first_id)
    _complete(
        governance,
        control,
        artifacts,
        work_id=first_id,
        stage_id=stage_id,
        attempt_id="ATT-CASE-1",
        artifact_id="EV-CASE-1",
    )

    outcome = progressor.reconcile_completed_work_item(first_id)

    stage = governance.get_stage(stage_id)
    assert stage is not None
    assert stage.state == StageState.EXECUTING
    assert stage.output_refs == tuple()
    assert outcome.newly_ready_stage_ids == tuple()
    assert outcome.materialized_work_item_ids == tuple()
    assert second_id in outcome.truth_note

    downstream = [
        item
        for item in governance.list_stages("TR-FANOUT")
        if item.stage_type == MissionStageType.REQUIREMENT_ANALYSIS.value
    ]
    assert len(downstream) == 1
    assert downstream[0].state == StageState.PENDING


def test_last_completed_fanout_work_item_aggregates_all_evidence_before_unlock():
    governance, control, artifacts, progressor, first_id, second_id, stage_id = _fixture()
    progressor.on_work_item_leased(first_id)
    progressor.on_work_item_started(first_id)
    _complete(
        governance,
        control,
        artifacts,
        work_id=first_id,
        stage_id=stage_id,
        attempt_id="ATT-CASE-1",
        artifact_id="EV-CASE-1",
    )
    progressor.reconcile_completed_work_item(first_id)

    _complete(
        governance,
        control,
        artifacts,
        work_id=second_id,
        stage_id=stage_id,
        attempt_id="ATT-CASE-2",
        artifact_id="EV-CASE-2",
    )
    outcome = progressor.reconcile_completed_work_item(second_id)

    stage = governance.get_stage(stage_id)
    assert stage is not None
    assert stage.state == StageState.COMPLETED
    assert set(stage.output_refs) == {"artifact:EV-CASE-1", "artifact:EV-CASE-2"}
    assert len(outcome.newly_ready_stage_ids) == 1
    assert len(outcome.materialized_work_item_ids) == 1
    assert outcome.truth_note == "ALL_LINKED_WORK_ITEMS_COMPLETED_WITH_AVAILABLE_EVIDENCE"
