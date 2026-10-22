import pytest

from rc8_runtime.contracts import RC8ContractError
from rc8_runtime.governance import StageInstance, StageState
from rc8_runtime.mission_graph import MissionGraphRuntime, MissionStageType


def _stage(stage_id, stage_type, scope, attempt_no=1, predecessors=(), state=StageState.PENDING, outputs=()):
    return StageInstance(
        stage_instance_id=stage_id,
        test_run_id="run-1",
        stage_type=stage_type.value,
        scope_version=scope,
        attempt_no=attempt_no,
        predecessor_ids=tuple(predecessors),
        state=state,
        output_refs=tuple(outputs),
    )


def test_same_stage_type_can_run_attempt_one_for_different_delivery_scopes():
    graph = MissionGraphRuntime("run-1")
    graph.add_stage(_stage("scope-a", MissionStageType.SCOPE_INTAKE, "scope:SST-A@v1"))
    graph.add_stage(_stage("scope-b", MissionStageType.SCOPE_INTAKE, "scope:SST-B@v1"))
    graph.add_stage(
        _stage(
            "req-a",
            MissionStageType.REQUIREMENT_ANALYSIS,
            "scope:SST-A@v1",
            predecessors=("scope-a",),
        )
    )
    graph.add_stage(
        _stage(
            "req-b",
            MissionStageType.REQUIREMENT_ANALYSIS,
            "scope:SST-B@v1",
            predecessors=("scope-b",),
        )
    )
    assert graph.latest_stage(MissionStageType.REQUIREMENT_ANALYSIS, "scope:SST-A@v1").stage_instance_id == "req-a"
    assert graph.latest_stage(MissionStageType.REQUIREMENT_ANALYSIS, "scope:SST-B@v1").stage_instance_id == "req-b"


def test_same_scope_rework_requires_higher_attempt_number():
    graph = MissionGraphRuntime("run-1")
    graph.add_stage(_stage("scope-a", MissionStageType.SCOPE_INTAKE, "scope:SST-A@v1"))
    graph.add_stage(
        _stage(
            "req-a-1",
            MissionStageType.REQUIREMENT_ANALYSIS,
            "scope:SST-A@v1",
            attempt_no=1,
            predecessors=("scope-a",),
        )
    )
    with pytest.raises(RC8ContractError, match="MISSION_STAGE_REWORK_REQUIRES_NEW_ATTEMPT_NO"):
        graph.add_stage(
            _stage(
                "req-a-duplicate",
                MissionStageType.REQUIREMENT_ANALYSIS,
                "scope:SST-A@v1",
                attempt_no=1,
                predecessors=("scope-a",),
            )
        )
    graph.add_stage(
        _stage(
            "req-a-2",
            MissionStageType.REQUIREMENT_ANALYSIS,
            "scope:SST-A@v1",
            attempt_no=2,
            predecessors=("scope-a",),
        )
    )
    assert graph.latest_stage(MissionStageType.REQUIREMENT_ANALYSIS, "scope:SST-A@v1").attempt_no == 2


def test_activity_completion_requires_evidence_and_never_claims_sufficiency():
    graph = MissionGraphRuntime("run-1")
    graph.add_stage(
        _stage(
            "scope-a",
            MissionStageType.SCOPE_INTAKE,
            "scope:SST-A@v1",
            state=StageState.EVIDENCE_PENDING,
        )
    )
    with pytest.raises(RC8ContractError, match="ACTIVITY_COMPLETION_REQUIRES_OUTPUT_EVIDENCE"):
        graph.record_activity_completion("scope-a", ())

    completed = graph.record_activity_completion("scope-a", ("artifact:scope-intake",))
    assert completed.state == StageState.COMPLETED
    assert completed.output_refs == ("artifact:scope-intake",)
    assert completed.evaluator_id is None


def test_sufficiency_stage_cannot_use_activity_completion_shortcut():
    graph = MissionGraphRuntime("run-1")
    graph.add_stage(_stage("scope-a", MissionStageType.SCOPE_INTAKE, "scope:SST-A@v1", state=StageState.COMPLETED))
    graph.add_stage(
        _stage(
            "req-a",
            MissionStageType.REQUIREMENT_ANALYSIS,
            "scope:SST-A@v1",
            predecessors=("scope-a",),
            state=StageState.COMPLETED,
        )
    )
    graph.add_stage(
        _stage(
            "req-suff-a",
            MissionStageType.REQUIREMENT_SUFFICIENCY,
            "scope:SST-A@v1",
            predecessors=("req-a",),
            state=StageState.EVIDENCE_PENDING,
        )
    )
    with pytest.raises(RC8ContractError, match="SUFFICIENCY_STAGE_REQUIRES_EVALUATION"):
        graph.record_activity_completion("req-suff-a", ("artifact:fake-green",))
