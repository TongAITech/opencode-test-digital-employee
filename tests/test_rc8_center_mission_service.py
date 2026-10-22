import pytest

from rc8_center.governance_repository import JsonFileGovernanceRepository
from rc8_center.mission_service import CenterMissionService
from rc8_runtime.contracts import RC8ContractError
from rc8_runtime.governance import StageState, StatusScope, SufficiencyEvaluation, SufficiencyResult
from rc8_runtime.mission_graph import MissionStageType


def _service(tmp_path):
    repo = JsonFileGovernanceRepository(str(tmp_path / "governance.json"))
    return repo, CenterMissionService(repo)


def _finish_activity(service, run_id, stage_id, artifact):
    service.mark_ready(run_id, stage_id)
    service.mark_leased(run_id, stage_id)
    service.mark_executing(run_id, stage_id)
    service.mark_evidence_pending(run_id, stage_id)
    return service.complete_activity(run_id, stage_id, (artifact,))


def _prepare_sufficiency(service, run_id, stage_id, artifact):
    service.mark_ready(run_id, stage_id)
    service.mark_leased(run_id, stage_id)
    service.mark_executing(run_id, stage_id)
    service.mark_evidence_pending(run_id, stage_id)
    return service.begin_sufficiency_evaluation(run_id, stage_id, (artifact,))


def test_center_mission_service_runs_two_delivery_scopes_independently(tmp_path):
    repo, service = _service(tmp_path)
    for scope, suffix in (("scope:SST-A@v1", "a"), ("scope:SST-B@v1", "b")):
        service.register_stage(
            test_run_id="run-1",
            stage_instance_id="scope-" + suffix,
            stage_type=MissionStageType.SCOPE_INTAKE,
            scope_version=scope,
            attempt_no=1,
        )
        _finish_activity(service, "run-1", "scope-" + suffix, "artifact:scope-" + suffix)
        service.register_stage(
            test_run_id="run-1",
            stage_instance_id="req-" + suffix,
            stage_type=MissionStageType.REQUIREMENT_ANALYSIS,
            scope_version=scope,
            attempt_no=1,
            predecessor_ids=("scope-" + suffix,),
        )

    assert set(service.ready_stage_ids("run-1")) == {"req-a", "req-b"}
    assert repo.get_stage("req-a").scope_version == "scope:SST-A@v1"
    assert repo.get_stage("req-b").scope_version == "scope:SST-B@v1"


def test_insufficient_gate_blocks_code_analysis_until_new_rework_stage(tmp_path):
    repo, service = _service(tmp_path)
    service.register_stage(
        test_run_id="run-1",
        stage_instance_id="scope-a",
        stage_type=MissionStageType.SCOPE_INTAKE,
        scope_version="scope:SST-A@v1",
        attempt_no=1,
    )
    _finish_activity(service, "run-1", "scope-a", "artifact:scope")
    service.register_stage(
        test_run_id="run-1",
        stage_instance_id="req-a-1",
        stage_type=MissionStageType.REQUIREMENT_ANALYSIS,
        scope_version="scope:SST-A@v1",
        attempt_no=1,
        predecessor_ids=("scope-a",),
    )
    _finish_activity(service, "run-1", "req-a-1", "artifact:req-analysis")
    service.register_stage(
        test_run_id="run-1",
        stage_instance_id="req-suff-a-1",
        stage_type=MissionStageType.REQUIREMENT_SUFFICIENCY,
        scope_version="scope:SST-A@v1",
        attempt_no=1,
        predecessor_ids=("req-a-1",),
    )
    _prepare_sufficiency(service, "run-1", "req-suff-a-1", "artifact:req-eval-input")
    repo.append_evaluation(
        SufficiencyEvaluation(
            evaluation_id="eval-req-a-1",
            test_run_id="run-1",
            scope=StatusScope.STAGE,
            subject_id="req-suff-a-1",
            evaluator_id="requirement-sufficiency-worker",
            policy_version="policy-v1",
            result=SufficiencyResult.INSUFFICIENT,
            dimension_refs=("coverage:business-rules",),
            evidence_refs=("artifact:req-eval",),
            unsatisfied_requirement_refs=("br:17",),
            unresolved_gap_ids=("gap:req:17",),
            explanation="business rule 17 is unresolved",
        )
    )
    state = service.reconcile_sufficiency("run-1", "req-suff-a-1")
    assert state.state == StageState.INSUFFICIENT
    service.complete_sufficiency("run-1", "req-suff-a-1")

    service.register_stage(
        test_run_id="run-1",
        stage_instance_id="code-a-1",
        stage_type=MissionStageType.CODE_ANALYSIS,
        scope_version="scope:SST-A@v1",
        attempt_no=1,
        predecessor_ids=("req-suff-a-1",),
    )
    assert "code-a-1" not in service.ready_stage_ids("run-1")
    with pytest.raises(RC8ContractError, match="MISSION_STAGE_DEPENDENCIES_NOT_SATISFIED"):
        service.mark_ready("run-1", "code-a-1")

    # The correct response is a new analysis/sufficiency attempt, not forcing the
    # old insufficient gate green.
    service.register_stage(
        test_run_id="run-1",
        stage_instance_id="req-a-2",
        stage_type=MissionStageType.REQUIREMENT_ANALYSIS,
        scope_version="scope:SST-A@v1",
        attempt_no=2,
        predecessor_ids=("req-suff-a-1",),
    )
    assert repo.get_stage("req-a-1").state == StageState.COMPLETED
    assert repo.get_stage("req-a-2").attempt_no == 2


def test_persisted_sufficient_gate_survives_service_restart_and_unlocks_downstream(tmp_path):
    repo, service = _service(tmp_path)
    service.register_stage(
        test_run_id="run-1",
        stage_instance_id="scope-a",
        stage_type=MissionStageType.SCOPE_INTAKE,
        scope_version="scope:SST-A@v1",
        attempt_no=1,
    )
    _finish_activity(service, "run-1", "scope-a", "artifact:scope")
    service.register_stage(
        test_run_id="run-1",
        stage_instance_id="req-a",
        stage_type=MissionStageType.REQUIREMENT_ANALYSIS,
        scope_version="scope:SST-A@v1",
        attempt_no=1,
        predecessor_ids=("scope-a",),
    )
    _finish_activity(service, "run-1", "req-a", "artifact:req")
    service.register_stage(
        test_run_id="run-1",
        stage_instance_id="req-suff-a",
        stage_type=MissionStageType.REQUIREMENT_SUFFICIENCY,
        scope_version="scope:SST-A@v1",
        attempt_no=1,
        predecessor_ids=("req-a",),
    )
    _prepare_sufficiency(service, "run-1", "req-suff-a", "artifact:req-eval-input")
    repo.append_evaluation(
        SufficiencyEvaluation(
            evaluation_id="eval-req-a",
            test_run_id="run-1",
            scope=StatusScope.STAGE,
            subject_id="req-suff-a",
            evaluator_id="requirement-sufficiency-worker",
            policy_version="policy-v1",
            result=SufficiencyResult.SUFFICIENT,
            dimension_refs=("coverage:business-rules",),
            evidence_refs=("artifact:req-eval",),
            explanation="all required rules resolved",
        )
    )
    service.reconcile_sufficiency("run-1", "req-suff-a")
    service.complete_sufficiency("run-1", "req-suff-a")

    # Reconstruct service as if Center restarted.
    service2 = CenterMissionService(JsonFileGovernanceRepository(str(tmp_path / "governance.json")))
    service2.register_stage(
        test_run_id="run-1",
        stage_instance_id="code-a",
        stage_type=MissionStageType.CODE_ANALYSIS,
        scope_version="scope:SST-A@v1",
        attempt_no=1,
        predecessor_ids=("req-suff-a",),
    )
    assert "code-a" in service2.ready_stage_ids("run-1")
    assert service2.mark_ready("run-1", "code-a").state == StageState.READY


def test_invalidation_keeps_old_stage_visible_and_blocks_old_green(tmp_path):
    repo, service = _service(tmp_path)
    service.register_stage(
        test_run_id="run-1",
        stage_instance_id="scope-a",
        stage_type=MissionStageType.SCOPE_INTAKE,
        scope_version="scope:SST-A@v1",
        attempt_no=1,
    )
    _finish_activity(service, "run-1", "scope-a", "artifact:scope")
    service.register_stage(
        test_run_id="run-1",
        stage_instance_id="req-a",
        stage_type=MissionStageType.REQUIREMENT_ANALYSIS,
        scope_version="scope:SST-A@v1",
        attempt_no=1,
        predecessor_ids=("scope-a",),
    )
    _finish_activity(service, "run-1", "req-a", "artifact:req-v1")

    record = service.invalidate(
        test_run_id="run-1",
        source_ref="requirement:v2",
        stage_instance_ids=("req-a",),
        reason="requirement changed after analysis",
        evidence_refs=("artifact:req-v2",),
        invalidation_id="inv-1",
    )
    assert record.target_refs == ("req-a",)
    assert repo.get_stage("req-a").state == StageState.INVALIDATED
    assert repo.get_stage("scope-a").state == StageState.COMPLETED
    assert len(repo.list_invalidations("run-1")) == 1
