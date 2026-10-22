from rc8_runtime.governance import StageInstance, StageState, StatusScope, SufficiencyEvaluation, SufficiencyResult
from rc8_runtime.mission_graph import MissionGraphRuntime, MissionStageType


def _stage(stage_id, stage_type, attempt_no=1, predecessors=(), state=StageState.PENDING):
    return StageInstance(
        stage_instance_id=stage_id,
        test_run_id="run-1",
        stage_type=stage_type.value,
        scope_version="scope:SST-A@v1",
        attempt_no=attempt_no,
        predecessor_ids=tuple(predecessors),
        state=state,
        evaluator_id="requirement-evaluator" if state == StageState.SUFFICIENT else None,
    )


def _evaluation(result):
    return SufficiencyEvaluation(
        evaluation_id="eval-1",
        test_run_id="run-1",
        scope=StatusScope.STAGE,
        subject_id="req-suff-1",
        evaluator_id="requirement-evaluator",
        policy_version="v1",
        result=result,
        dimension_refs=("coverage:requirement",),
        evidence_refs=("artifact:eval",),
        explanation="deterministic gate result",
    )


def _graph(result):
    graph = MissionGraphRuntime("run-1")
    graph.add_stage(_stage("scope-1", MissionStageType.SCOPE_INTAKE, state=StageState.COMPLETED))
    graph.add_stage(
        _stage(
            "req-1",
            MissionStageType.REQUIREMENT_ANALYSIS,
            predecessors=("scope-1",),
            state=StageState.COMPLETED,
        )
    )
    gate_state = StageState.INSUFFICIENT if result == SufficiencyResult.INSUFFICIENT else StageState.SUFFICIENT
    graph.add_stage(
        _stage(
            "req-suff-1",
            MissionStageType.REQUIREMENT_SUFFICIENCY,
            predecessors=("req-1",),
            state=gate_state,
        )
    )
    graph.restore_evaluation(_evaluation(result))
    graph.add_stage(
        _stage(
            "req-2",
            MissionStageType.REQUIREMENT_ANALYSIS,
            attempt_no=2,
            predecessors=("req-suff-1",),
        )
    )
    graph.add_stage(
        _stage(
            "code-1",
            MissionStageType.CODE_ANALYSIS,
            predecessors=("req-suff-1",),
        )
    )
    return graph


def test_insufficient_gate_unlocks_rework_and_blocks_forward_progression():
    graph = _graph(SufficiencyResult.INSUFFICIENT)
    assert graph.can_mark_ready("req-2") is True
    assert graph.can_mark_ready("code-1") is False


def test_sufficient_gate_unlocks_forward_progression_and_does_not_schedule_rework():
    graph = _graph(SufficiencyResult.SUFFICIENT)
    assert graph.can_mark_ready("req-2") is False
    assert graph.can_mark_ready("code-1") is True
