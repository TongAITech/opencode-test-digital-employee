from __future__ import annotations

from rc8_center.mission_service import CenterMissionService
from rc8_runtime.governance import StageInstance, StageState, StatusScope, SufficiencyEvaluation, SufficiencyResult
from rc8_runtime.mission_graph import MissionStageType


REQUIRED = (
    "dimension:requirement-source-assertions",
    "dimension:requirement-atomic-statements",
    "dimension:requirement-traceability",
    "dimension:requirement-evidence",
    "dimension:requirement-normal-path",
    "dimension:requirement-open-question",
)


class FakeGovernanceRepository:
    def __init__(self, stages, evaluations=()):
        self.stages = {item.stage_instance_id: item for item in stages}
        self.evaluations = list(evaluations)

    def list_stages(self, test_run_id):
        return [item for item in self.stages.values() if item.test_run_id == test_run_id]

    def list_evaluations(self, test_run_id):
        return [item for item in self.evaluations if item.test_run_id == test_run_id]

    def get_stage(self, stage_instance_id):
        return self.stages.get(stage_instance_id)

    def upsert_stage(self, stage):
        self.stages[stage.stage_instance_id] = stage

    def append_evaluation(self, evaluation):
        if not any(item.evaluation_id == evaluation.evaluation_id for item in self.evaluations):
            self.evaluations.append(evaluation)


def _stages(*, suff_state=StageState.EVALUATING, with_code=False):
    scope = StageInstance(stage_instance_id="scope", test_run_id="run", stage_type=MissionStageType.SCOPE_INTAKE.value, scope_version="delivery-scope:S1", attempt_no=1, state=StageState.COMPLETED)
    analysis = StageInstance(stage_instance_id="analysis", test_run_id="run", stage_type=MissionStageType.REQUIREMENT_ANALYSIS.value, scope_version="delivery-scope:S1", attempt_no=1, state=StageState.COMPLETED, predecessor_ids=("scope",))
    suff = StageInstance(stage_instance_id="suff", test_run_id="run", stage_type=MissionStageType.REQUIREMENT_SUFFICIENCY.value, scope_version="delivery-scope:S1", attempt_no=1, state=suff_state, predecessor_ids=("analysis",), input_refs=("test-round:R1", "delivery-scope:S1"), output_refs=("artifact:req-suff",))
    values = [scope, analysis, suff]
    if with_code:
        values.append(StageInstance(stage_instance_id="code", test_run_id="run", stage_type=MissionStageType.CODE_ANALYSIS.value, scope_version="delivery-scope:S1", attempt_no=1, state=StageState.PENDING, predecessor_ids=("suff",)))
    return values


def _worker_green(dimensions):
    return SufficiencyEvaluation(
        evaluation_id="worker-eval",
        test_run_id="run",
        scope=StatusScope.STAGE,
        subject_id="suff",
        evaluator_id="RC8_REQUIREMENT_SUFFICIENCY_POLICY",
        policy_version="rc8.requirement-sufficiency.v1",
        result=SufficiencyResult.SUFFICIENT,
        dimension_refs=tuple(dimensions),
        evidence_refs=("artifact:req-suff",),
        satisfied_requirement_refs=tuple(dimensions),
        unsatisfied_requirement_refs=(),
        unresolved_gap_ids=(),
        explanation="worker candidate says sufficient",
        evaluated_at=10,
    )


def test_worker_three_of_six_green_is_downgraded_by_center_frozen_denominator():
    repo = FakeGovernanceRepository(_stages(), [_worker_green(REQUIRED[:3])])
    stage = CenterMissionService(repo).reconcile_sufficiency("run", "suff")
    assert stage.state == StageState.INSUFFICIENT
    center = repo.evaluations[-1]
    assert center.evaluation_id == "center-worker-eval"
    assert center.result == SufficiencyResult.INSUFFICIENT
    assert center.policy_version.startswith("center-ledger:")
    assert len(center.dimension_refs) == 6
    assert len(center.unsatisfied_requirement_refs) == 3
    assert any(ref.startswith("ledger:") for ref in center.evidence_refs)


def test_worker_six_of_six_green_becomes_center_authoritative_sufficient():
    repo = FakeGovernanceRepository(_stages(), [_worker_green(REQUIRED)])
    stage = CenterMissionService(repo).reconcile_sufficiency("run", "suff")
    assert stage.state == StageState.SUFFICIENT
    center = repo.evaluations[-1]
    assert center.result == SufficiencyResult.SUFFICIENT
    assert center.evaluator_id == "RC8_CENTER_SUFFICIENCY_LEDGER"
    assert center.policy_version.startswith("center-ledger:")
    assert set(center.satisfied_requirement_refs) == set(REQUIRED)


def test_persisted_worker_green_alone_cannot_unlock_downstream_after_restart():
    stages = _stages(suff_state=StageState.COMPLETED, with_code=True)
    repo = FakeGovernanceRepository(stages, [_worker_green(REQUIRED)])
    assert CenterMissionService(repo).ready_stage_ids("run") == ()
