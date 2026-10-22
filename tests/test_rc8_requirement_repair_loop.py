from __future__ import annotations

from dataclasses import replace

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

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
from rc8_center.requirement_loop_progression import RequirementLoopProgressor
from rc8_runtime import ArtifactAvailability, AttemptRecord, AttemptStatus, RuntimeProducerKind
from rc8_runtime.artifacts import ArtifactManifest
from rc8_runtime.governance import (
    GapRecord,
    GapSeverity,
    GapStatus,
    GapType,
    StageState,
    StatusScope,
    SufficiencyEvaluation,
    SufficiencyResult,
)
from rc8_runtime.mission_graph import MissionStageType


def _fixture(max_attempts: int = 3):
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
    progressor = RequirementLoopProgressor(
        store=store,
        mission_service=mission,
        governance_repository=governance,
        control_repository=control,
        artifact_repository=artifacts,
        max_requirement_analysis_attempts=max_attempts,
    )
    delivery.create_batch(ProductionBatch("PB", "2026-11-15", "投产", created_at=1))
    delivery.create_requirement(Requirement("REQ", "需求", created_at=1))
    delivery.create_delivery(RequirementDelivery("DEL", "PB", "REQ", created_at=1, updated_at=1))
    delivery.create_scope(
        RequirementDeliveryScope(
            "SCOPE",
            "DEL",
            "PFC",
            "SYS-V1",
            "SST-1",
            application_id="cfg-center",
            created_at=1,
        )
    )
    rounds.create_next_round("PB", ["DEL"], requested_test_round_id="ROUND", now=1)
    _round, run = rounds.start_runtime_mission("ROUND", "TR", now=2)
    return governance, control, artifacts, progressor, run


def _artifact(artifacts, *, artifact_id: str, work_id: str, stage_id: str, attempt_id: str) -> str:
    artifacts.upsert(
        ArtifactManifest(
            artifact_id=artifact_id,
            test_run_id="TR",
            work_item_id=work_id,
            node_id="NODE",
            kind="TEST_EVIDENCE",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="worker:test",
            file_name="evidence.json",
            sha256="a" * 64,
            size_bytes=10,
            availability=ArtifactAvailability.AVAILABLE,
            attempt_id=attempt_id,
            refs=["stage:%s" % stage_id],
            created_at=10,
        )
    )
    return "artifact:%s" % artifact_id


def _complete_activity(governance, control, artifacts, progressor, work_id: str, stage_id: str, suffix: str):
    progressor.on_work_item_leased(work_id)
    progressor.on_work_item_started(work_id)
    attempt_id = "ATT-%s" % suffix
    evidence_ref = _artifact(
        artifacts,
        artifact_id="EV-%s" % suffix,
        work_id=work_id,
        stage_id=stage_id,
        attempt_id=attempt_id,
    )
    governance.upsert_attempt(
        AttemptRecord(
            attempt_id=attempt_id,
            test_run_id="TR",
            stage_instance_id=stage_id,
            work_item_id=work_id,
            producer_node_id="NODE",
            producer_ref="worker:test",
            input_snapshot_ref="snapshot:%s" % suffix,
            status=AttemptStatus.COMPLETED,
            evidence_refs=(evidence_ref,),
            started_at=10,
            finished_at=11,
        )
    )
    work = control.get_work_item(work_id)
    assert work is not None
    control.upsert_work_item(replace(work, state=WorkItemState.COMPLETED))
    return progressor.reconcile_completed_work_item(work_id), evidence_ref


def _single_work_for_stage(control, stage_id: str):
    links = control.list_work_item_links_for_stage(stage_id)
    assert len(links) == 1
    work = control.get_work_item(links[0].work_item_id)
    assert work is not None
    return work


def _stage(governance, stage_type: MissionStageType, attempt_no: int):
    values = [
        value
        for value in governance.list_stages("TR")
        if value.stage_type == stage_type.value and value.attempt_no == attempt_no
    ]
    assert len(values) == 1
    return values[0]


def _reach_requirement_sufficiency(governance, control, artifacts, progressor, run):
    intake_id = run.payload["mission_initial_ready_stage_ids"][0]
    intake_work = run.payload["mission_initial_work_item_ids"][0]
    intake_outcome, _ = _complete_activity(
        governance, control, artifacts, progressor, intake_work, intake_id, "INTAKE"
    )
    assert len(intake_outcome.newly_ready_stage_ids) == 1
    req_stage = _stage(governance, MissionStageType.REQUIREMENT_ANALYSIS, 1)
    req_work = _single_work_for_stage(control, req_stage.stage_instance_id)
    req_outcome, _ = _complete_activity(
        governance,
        control,
        artifacts,
        progressor,
        req_work.identity.work_item_id,
        req_stage.stage_instance_id,
        "REQ1",
    )
    assert len(req_outcome.newly_ready_stage_ids) == 1
    suff_stage = _stage(governance, MissionStageType.REQUIREMENT_SUFFICIENCY, 1)
    suff_work = _single_work_for_stage(control, suff_stage.stage_instance_id)
    return suff_stage, suff_work


def _complete_sufficiency(
    governance,
    control,
    artifacts,
    progressor,
    *,
    stage,
    work,
    suffix: str,
    result: SufficiencyResult,
    unresolved_gap_ids=(),
):
    progressor.on_work_item_leased(work.identity.work_item_id)
    progressor.on_work_item_started(work.identity.work_item_id)
    attempt_id = "ATT-SUFF-%s" % suffix
    evidence_ref = _artifact(
        artifacts,
        artifact_id="EV-SUFF-%s" % suffix,
        work_id=work.identity.work_item_id,
        stage_id=stage.stage_instance_id,
        attempt_id=attempt_id,
    )
    governance.upsert_attempt(
        AttemptRecord(
            attempt_id=attempt_id,
            test_run_id="TR",
            stage_instance_id=stage.stage_instance_id,
            work_item_id=work.identity.work_item_id,
            producer_node_id="NODE",
            producer_ref="worker:sufficiency",
            input_snapshot_ref="snapshot:suff:%s" % suffix,
            status=AttemptStatus.COMPLETED,
            evidence_refs=(evidence_ref,),
            gap_refs=tuple(unresolved_gap_ids),
            started_at=20,
            finished_at=21,
        )
    )
    evaluation = SufficiencyEvaluation(
        evaluation_id="EVAL-%s" % suffix,
        test_run_id="TR",
        scope=StatusScope.STAGE,
        subject_id=stage.stage_instance_id,
        evaluator_id="requirement-sufficiency-policy",
        policy_version="rc8.requirement-sufficiency.v1",
        result=result,
        dimension_refs=("traceability", "normal-path"),
        evidence_refs=(evidence_ref,),
        satisfied_requirement_refs=("requirement:REQ",) if result == SufficiencyResult.SUFFICIENT else tuple(),
        unsatisfied_requirement_refs=("requirement:REQ",) if result == SufficiencyResult.INSUFFICIENT else tuple(),
        unresolved_gap_ids=tuple(unresolved_gap_ids),
        explanation="充分" if result == SufficiencyResult.SUFFICIENT else "需求分析仍有未解决缺口",
        evaluated_at=22,
    )
    governance.append_evaluation(evaluation)
    work_record = control.get_work_item(work.identity.work_item_id)
    assert work_record is not None
    control.upsert_work_item(replace(work_record, state=WorkItemState.COMPLETED))
    return progressor.reconcile_completed_work_item(work.identity.work_item_id), evidence_ref


def test_insufficient_requirement_appends_attempt2_and_keeps_code_blocked() -> None:
    governance, control, artifacts, progressor, run = _fixture()
    suff1, work1 = _reach_requirement_sufficiency(governance, control, artifacts, progressor, run)

    gap_ref = _artifact(
        artifacts,
        artifact_id="EV-GAP-1",
        work_id=work1.identity.work_item_id,
        stage_id=suff1.stage_instance_id,
        attempt_id="ATT-SUFF-1",
    )
    governance.upsert_gap(
        GapRecord(
            gap_id="GAP-1",
            test_run_id="TR",
            source_stage_instance_id=suff1.stage_instance_id,
            gap_type=GapType.REQUIREMENT_UNCLEAR,
            severity=GapSeverity.P1,
            description="验收条件存在歧义",
            owner_stage=MissionStageType.REQUIREMENT_ANALYSIS.value,
            repair_strategy="补充需求分析并重新评估充分度",
            evidence_refs=(gap_ref,),
            opened_at=22,
        )
    )
    outcome, _ = _complete_sufficiency(
        governance,
        control,
        artifacts,
        progressor,
        stage=suff1,
        work=work1,
        suffix="1",
        result=SufficiencyResult.INSUFFICIENT,
        unresolved_gap_ids=("GAP-1",),
    )

    assert outcome.truth_note == "REQUIREMENT_INSUFFICIENT_APPENDED_REPAIR_ATTEMPT"
    req2 = _stage(governance, MissionStageType.REQUIREMENT_ANALYSIS, 2)
    suff2 = _stage(governance, MissionStageType.REQUIREMENT_SUFFICIENCY, 2)
    code = _stage(governance, MissionStageType.CODE_ANALYSIS, 1)
    suff1_persisted = governance.get_stage(suff1.stage_instance_id)
    assert suff1_persisted is not None
    assert req2.state == StageState.READY
    assert req2.predecessor_ids == (suff1.stage_instance_id,)
    assert req2.successor_ids == (suff2.stage_instance_id,)
    assert suff2.state == StageState.PENDING
    assert suff2.predecessor_ids == (req2.stage_instance_id,)
    assert suff2.successor_ids == (code.stage_instance_id,)
    assert code.state == StageState.PENDING
    assert code.predecessor_ids == (suff2.stage_instance_id,)
    assert req2.stage_instance_id in suff1_persisted.successor_ids
    assert code.stage_instance_id not in suff1_persisted.successor_ids
    req2_work = _single_work_for_stage(control, req2.stage_instance_id)
    assert "gap:GAP-1" in req2_work.identity.scope_refs
    assert governance.get_gap("GAP-1") is not None
    assert len(governance.list_evaluations("TR")) == 1

    # Crash/reconcile retries must not create another attempt-2 graph or edges.
    second = progressor.reconcile_completed_work_item(work1.identity.work_item_id)
    assert second.truth_note == "REQUIREMENT_INSUFFICIENT_APPENDED_REPAIR_ATTEMPT"
    assert len([
        value for value in governance.list_stages("TR")
        if value.stage_type == MissionStageType.REQUIREMENT_ANALYSIS.value and value.attempt_no == 2
    ]) == 1
    assert len([
        value for value in governance.list_stages("TR")
        if value.stage_type == MissionStageType.REQUIREMENT_SUFFICIENCY.value and value.attempt_no == 2
    ]) == 1
    assert governance.get_stage(suff1.stage_instance_id).successor_ids == (req2.stage_instance_id,)
    assert governance.get_stage(req2.stage_instance_id).successor_ids == (suff2.stage_instance_id,)
    assert governance.get_stage(suff2.stage_instance_id).successor_ids == (code.stage_instance_id,)


def test_repaired_requirement_becomes_sufficient_then_unlocks_code_analysis() -> None:
    governance, control, artifacts, progressor, run = _fixture()
    suff1, work1 = _reach_requirement_sufficiency(governance, control, artifacts, progressor, run)
    gap_ref = _artifact(
        artifacts,
        artifact_id="EV-GAP",
        work_id=work1.identity.work_item_id,
        stage_id=suff1.stage_instance_id,
        attempt_id="ATT-SUFF-1",
    )
    governance.upsert_gap(
        GapRecord(
            gap_id="GAP",
            test_run_id="TR",
            source_stage_instance_id=suff1.stage_instance_id,
            gap_type=GapType.REQUIREMENT_UNCLEAR,
            severity=GapSeverity.P1,
            description="缺少明确验收路径",
            owner_stage=MissionStageType.REQUIREMENT_ANALYSIS.value,
            repair_strategy="补充分析",
            evidence_refs=(gap_ref,),
            opened_at=22,
        )
    )
    _complete_sufficiency(
        governance,
        control,
        artifacts,
        progressor,
        stage=suff1,
        work=work1,
        suffix="1",
        result=SufficiencyResult.INSUFFICIENT,
        unresolved_gap_ids=("GAP",),
    )

    req2 = _stage(governance, MissionStageType.REQUIREMENT_ANALYSIS, 2)
    req2_work = _single_work_for_stage(control, req2.stage_instance_id)
    _complete_activity(
        governance,
        control,
        artifacts,
        progressor,
        req2_work.identity.work_item_id,
        req2.stage_instance_id,
        "REQ2",
    )
    suff2 = _stage(governance, MissionStageType.REQUIREMENT_SUFFICIENCY, 2)
    suff2_work = _single_work_for_stage(control, suff2.stage_instance_id)

    closure_ref = _artifact(
        artifacts,
        artifact_id="EV-CLOSE-GAP",
        work_id=suff2_work.identity.work_item_id,
        stage_id=suff2.stage_instance_id,
        attempt_id="ATT-SUFF-2",
    )
    gap = governance.get_gap("GAP")
    assert gap is not None
    governance.upsert_gap(
        replace(
            gap,
            status=GapStatus.CLOSED,
            closure_evidence_refs=(closure_ref,),
            closed_at=30,
        )
    )
    outcome, _ = _complete_sufficiency(
        governance,
        control,
        artifacts,
        progressor,
        stage=suff2,
        work=suff2_work,
        suffix="2",
        result=SufficiencyResult.SUFFICIENT,
    )
    code = _stage(governance, MissionStageType.CODE_ANALYSIS, 1)
    assert code.state == StageState.READY
    assert code.predecessor_ids == (suff2.stage_instance_id,)
    assert governance.get_stage(suff2.stage_instance_id).successor_ids == (code.stage_instance_id,)
    code_work = _single_work_for_stage(control, code.stage_instance_id)
    assert code_work.identity.stage == MissionStageType.CODE_ANALYSIS.value
    assert outcome.truth_note == "EVIDENCE_GATED_STAGE_PROGRESSION"
    assert [value.result for value in governance.list_evaluations("TR")] == [
        SufficiencyResult.INSUFFICIENT,
        SufficiencyResult.SUFFICIENT,
    ]
    assert governance.get_gap("GAP").status == GapStatus.CLOSED


def test_requirement_repair_attempt_cap_never_unlocks_code_analysis() -> None:
    governance, control, artifacts, progressor, run = _fixture(max_attempts=1)
    suff1, work1 = _reach_requirement_sufficiency(governance, control, artifacts, progressor, run)
    outcome, _ = _complete_sufficiency(
        governance,
        control,
        artifacts,
        progressor,
        stage=suff1,
        work=work1,
        suffix="CAP",
        result=SufficiencyResult.INSUFFICIENT,
        unresolved_gap_ids=("GAP-CAP",),
    )
    code = _stage(governance, MissionStageType.CODE_ANALYSIS, 1)
    assert outcome.truth_note == "REQUIREMENT_INSUFFICIENT_REPAIR_LIMIT_REACHED_CODE_ANALYSIS_BLOCKED"
    assert code.state == StageState.PENDING
    assert not [
        value for value in governance.list_stages("TR")
        if value.stage_type == MissionStageType.REQUIREMENT_ANALYSIS.value and value.attempt_no > 1
    ]
