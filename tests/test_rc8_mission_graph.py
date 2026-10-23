import pytest

from rc8_runtime.contracts import RC8ContractError
from rc8_runtime.governance import (
    StageInstance,
    StageState,
    StatusScope,
    SufficiencyEvaluation,
    SufficiencyResult,
)
from rc8_runtime.mission_graph import MissionGraphRuntime, MissionStageType, validate_edge


def _stage(stage_id, stage_type, attempt_no=1, predecessors=(), state=StageState.PENDING):
    return StageInstance(
        stage_instance_id=stage_id,
        test_run_id="run-1",
        stage_type=stage_type.value,
        scope_version="scope-v1",
        attempt_no=attempt_no,
        predecessor_ids=tuple(predecessors),
        state=state,
    )


def _advance_to_evaluating(graph, stage_id):
    graph.runtime.transition_stage(stage_id, StageState.LEASED)
    graph.runtime.transition_stage(stage_id, StageState.EXECUTING)
    graph.runtime.transition_stage(stage_id, StageState.EVIDENCE_PENDING)
    graph.runtime.transition_stage(stage_id, StageState.EVALUATING)


def _eval(eval_id, stage_id, result, gaps=(), unsatisfied=(), authoritative=True):
    center_green = result == SufficiencyResult.SUFFICIENT and authoritative
    return SufficiencyEvaluation(
        evaluation_id=eval_id,
        test_run_id="run-1",
        scope=StatusScope.STAGE,
        subject_id=stage_id,
        evaluator_id="RC8_CENTER_SUFFICIENCY_LEDGER" if center_green else "independent-evaluator",
        policy_version="center-ledger:ledger-test" if center_green else "policy-v1",
        result=result,
        dimension_refs=("coverage:req",),
        evidence_refs=("artifact:evaluation", "ledger:ledger-test") if center_green else ("artifact:evaluation",),
        unresolved_gap_ids=tuple(gaps),
        unsatisfied_requirement_refs=tuple(unsatisfied),
        explanation="evidence-backed sufficiency decision",
    )


def test_first_stage_must_be_scope_intake_and_arbitrary_skip_is_forbidden():
    graph = MissionGraphRuntime("run-1")
    with pytest.raises(RC8ContractError, match="MISSION_FIRST_STAGE_MUST_BE_SCOPE_INTAKE"):
        graph.add_stage(_stage("req-1", MissionStageType.REQUIREMENT_ANALYSIS))

    graph.add_stage(_stage("scope-1", MissionStageType.SCOPE_INTAKE))
    with pytest.raises(RC8ContractError, match="MISSION_STAGE_EDGE_FORBIDDEN"):
        graph.add_stage(
            _stage(
                "design-1",
                MissionStageType.TEST_DESIGN,
                predecessors=("scope-1",),
            )
        )

    with pytest.raises(RC8ContractError, match="MISSION_STAGE_EDGE_FORBIDDEN"):
        validate_edge(MissionStageType.SCOPE_INTAKE.value, MissionStageType.CODE_ANALYSIS.value)


def test_completed_activity_can_feed_sufficiency_but_insufficient_gate_blocks_downstream():
    graph = MissionGraphRuntime("run-1")
    graph.add_stage(_stage("scope-1", MissionStageType.SCOPE_INTAKE, state=StageState.COMPLETED))
    graph.add_stage(
        _stage(
            "req-analysis-1",
            MissionStageType.REQUIREMENT_ANALYSIS,
            predecessors=("scope-1",),
            state=StageState.COMPLETED,
        )
    )
    graph.add_stage(
        _stage(
            "req-suff-1",
            MissionStageType.REQUIREMENT_SUFFICIENCY,
            predecessors=("req-analysis-1",),
        )
    )
    assert graph.can_mark_ready("req-suff-1") is True
    graph.mark_ready("req-suff-1")
    _advance_to_evaluating(graph, "req-suff-1")
    graph.record_stage_sufficiency(
        "req-suff-1",
        _eval(
            "eval-req-1",
            "req-suff-1",
            SufficiencyResult.INSUFFICIENT,
            gaps=("gap-business-rule",),
            unsatisfied=("requirement:BR-17",),
        ),
    )
    graph.complete_stage("req-suff-1")

    graph.add_stage(
        _stage(
            "code-analysis-1",
            MissionStageType.CODE_ANALYSIS,
            predecessors=("req-suff-1",),
        )
    )
    assert graph.can_mark_ready("code-analysis-1") is False
    with pytest.raises(RC8ContractError, match="MISSION_STAGE_DEPENDENCIES_NOT_SATISFIED"):
        graph.mark_ready("code-analysis-1")


def test_worker_green_cannot_bypass_center_authority_in_record_path():
    graph = MissionGraphRuntime("run-1")
    graph.add_stage(_stage("scope-1", MissionStageType.SCOPE_INTAKE, state=StageState.COMPLETED))
    graph.add_stage(_stage("req-analysis-1", MissionStageType.REQUIREMENT_ANALYSIS, predecessors=("scope-1",), state=StageState.COMPLETED))
    graph.add_stage(_stage("req-suff-1", MissionStageType.REQUIREMENT_SUFFICIENCY, predecessors=("req-analysis-1",)))
    graph.mark_ready("req-suff-1")
    _advance_to_evaluating(graph, "req-suff-1")
    with pytest.raises(RC8ContractError, match="MISSION_SUFFICIENT_REQUIRES_CENTER_LEDGER_AUTHORITY"):
        graph.record_stage_sufficiency("req-suff-1", _eval("worker-green", "req-suff-1", SufficiencyResult.SUFFICIENT, authoritative=False))
    assert graph.runtime.stages["req-suff-1"].state == StageState.EVALUATING


def test_only_center_authoritative_sufficient_evaluation_unlocks_next_stage():
    graph = MissionGraphRuntime("run-1")
    graph.add_stage(_stage("scope-1", MissionStageType.SCOPE_INTAKE, state=StageState.COMPLETED))
    graph.add_stage(
        _stage(
            "req-analysis-1",
            MissionStageType.REQUIREMENT_ANALYSIS,
            predecessors=("scope-1",),
            state=StageState.COMPLETED,
        )
    )
    graph.add_stage(
        _stage(
            "req-suff-1",
            MissionStageType.REQUIREMENT_SUFFICIENCY,
            predecessors=("req-analysis-1",),
        )
    )
    graph.mark_ready("req-suff-1")
    _advance_to_evaluating(graph, "req-suff-1")
    stage = graph.record_stage_sufficiency(
        "req-suff-1",
        _eval("eval-req-1", "req-suff-1", SufficiencyResult.SUFFICIENT),
    )
    assert stage.state == StageState.SUFFICIENT
    graph.complete_stage("req-suff-1")

    graph.add_stage(
        _stage(
            "code-analysis-1",
            MissionStageType.CODE_ANALYSIS,
            predecessors=("req-suff-1",),
        )
    )
    assert graph.can_mark_ready("code-analysis-1") is True
    assert graph.mark_ready("code-analysis-1").state == StageState.READY


def test_rework_requires_new_stage_instance_and_higher_attempt_number():
    graph = MissionGraphRuntime("run-1")
    graph.add_stage(_stage("scope-1", MissionStageType.SCOPE_INTAKE, state=StageState.COMPLETED))
    graph.add_stage(
        _stage(
            "req-analysis-1",
            MissionStageType.REQUIREMENT_ANALYSIS,
            attempt_no=1,
            predecessors=("scope-1",),
            state=StageState.COMPLETED,
        )
    )
    with pytest.raises(RC8ContractError, match="MISSION_STAGE_REWORK_REQUIRES_NEW_ATTEMPT_NO"):
        graph.add_stage(
            _stage(
                "req-analysis-copy",
                MissionStageType.REQUIREMENT_ANALYSIS,
                attempt_no=1,
                predecessors=("scope-1",),
            )
        )
    graph.add_stage(
        _stage(
            "req-analysis-2",
            MissionStageType.REQUIREMENT_ANALYSIS,
            attempt_no=2,
            predecessors=("scope-1",),
        )
    )
    assert graph.latest_stage(MissionStageType.REQUIREMENT_ANALYSIS).stage_instance_id == "req-analysis-2"


def test_upstream_change_invalidates_old_green_and_all_downstream_proof():
    graph = MissionGraphRuntime("run-1")
    graph.add_stage(_stage("scope-1", MissionStageType.SCOPE_INTAKE, state=StageState.COMPLETED))
    graph.add_stage(
        _stage(
            "req-analysis-1",
            MissionStageType.REQUIREMENT_ANALYSIS,
            predecessors=("scope-1",),
            state=StageState.COMPLETED,
        )
    )
    graph.add_stage(
        _stage(
            "req-suff-1",
            MissionStageType.REQUIREMENT_SUFFICIENCY,
            predecessors=("req-analysis-1",),
            state=StageState.COMPLETED,
        )
    )
    # Hydrate the historical Center-authoritative sufficiency proof.
    graph.runtime.evaluations["eval-old"] = _eval("eval-old", "req-suff-1", SufficiencyResult.SUFFICIENT)
    graph._stage_evaluations["req-suff-1"] = "eval-old"
    graph.add_stage(
        _stage(
            "code-analysis-1",
            MissionStageType.CODE_ANALYSIS,
            predecessors=("req-suff-1",),
            state=StageState.COMPLETED,
        )
    )
    graph.add_stage(
        _stage(
            "code-suff-1",
            MissionStageType.CODE_SUFFICIENCY,
            predecessors=("code-analysis-1",),
            state=StageState.COMPLETED,
        )
    )

    record = graph.invalidate_from(
        "requirement-analysis:v2",
        ("req-suff-1",),
        reason="new business rule changes downstream impact",
        evidence_refs=("artifact:req-analysis-v2",),
        invalidation_id="inv-1",
    )
    assert set(record.target_refs) == {"req-suff-1", "code-analysis-1", "code-suff-1"}
    assert graph.runtime.stages["req-suff-1"].state == StageState.INVALIDATED
    assert graph.runtime.stages["code-analysis-1"].state == StageState.INVALIDATED
    assert graph.runtime.stages["code-suff-1"].state == StageState.INVALIDATED
    assert graph.runtime.stages["req-analysis-1"].state == StageState.COMPLETED
