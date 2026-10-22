from __future__ import annotations

import pytest

from rc8_center.mission_planner import PLAN_POLICY_VERSION, plan_test_round_mission
from rc8_runtime.governance import StageState
from rc8_runtime.mission_graph import MissionGraphRuntime, MissionStageType


def test_two_scopes_plan_parallel_chains_then_converge_to_mission_sufficiency() -> None:
    plan = plan_test_round_mission(
        test_run_id="TR-1",
        test_round_id="ROUND-1",
        scope_refs=["SCOPE-A", "SCOPE-B"],
    )

    assert plan.policy_version == PLAN_POLICY_VERSION
    assert plan.scope_refs == ("SCOPE-A", "SCOPE-B")
    assert plan.stage_count == 26
    assert len(plan.initial_ready_stage_ids) == 2
    assert len(plan.initial_work_items) == 2

    by_id = {stage.stage_instance_id: stage for stage in plan.stages}
    ready = [by_id[stage_id] for stage_id in plan.initial_ready_stage_ids]
    assert {stage.stage_type for stage in ready} == {MissionStageType.SCOPE_INTAKE.value}
    assert {stage.scope_version for stage in ready} == {
        "delivery-scope:SCOPE-A",
        "delivery-scope:SCOPE-B",
    }

    work_stage_ids = {item.stage_instance_id for item in plan.initial_work_items}
    assert work_stage_ids == set(plan.initial_ready_stage_ids)
    assert len(set(plan.initial_work_item_ids)) == 2
    for item in plan.initial_work_items:
        identity = item.identity
        assert identity.test_run_id == "TR-1"
        assert identity.stage == MissionStageType.SCOPE_INTAKE.value
        assert "stage-instance:%s" % item.stage_instance_id in identity.scope_refs
        assert "test-round:ROUND-1" in identity.scope_refs
        assert identity.required_capabilities == tuple()

    mission = by_id[plan.mission_sufficiency_stage_id]
    assert mission.stage_type == MissionStageType.MISSION_SUFFICIENCY.value
    assert mission.state == StageState.PENDING
    assert len(mission.predecessor_ids) == 2
    assert {
        by_id[value].stage_type for value in mission.predecessor_ids
    } == {MissionStageType.FAILURE_COVERAGE_EVALUATION.value}

    report = by_id[plan.report_release_stage_id]
    assert report.stage_type == MissionStageType.REPORT_RELEASE.value
    assert report.predecessor_ids == (plan.mission_sufficiency_stage_id,)

    graph = MissionGraphRuntime("TR-1")
    for stage in plan.stages:
        graph.add_stage(stage)
    assert set(graph.runtime.stages) == set(by_id)


def test_one_scope_contains_full_initial_analysis_design_execution_chain() -> None:
    plan = plan_test_round_mission(
        test_run_id="TR-1",
        test_round_id="ROUND-1",
        scope_refs=["SCOPE-A"],
    )
    stage_types = [stage.stage_type for stage in plan.stages]
    for required in (
        MissionStageType.SCOPE_INTAKE,
        MissionStageType.REQUIREMENT_ANALYSIS,
        MissionStageType.REQUIREMENT_SUFFICIENCY,
        MissionStageType.CODE_ANALYSIS,
        MissionStageType.CODE_SUFFICIENCY,
        MissionStageType.RISK_TEST_MODEL,
        MissionStageType.TEST_DESIGN,
        MissionStageType.DESIGN_SUFFICIENCY,
        MissionStageType.EXECUTABLE_SPEC,
        MissionStageType.PRECONDITION_DATA_PREP,
        MissionStageType.APPLICABLE_LAYER_EXECUTION,
        MissionStageType.FAILURE_COVERAGE_EVALUATION,
        MissionStageType.MISSION_SUFFICIENCY,
        MissionStageType.REPORT_RELEASE,
    ):
        assert required.value in stage_types

    # Repair/re-execution are gap-driven and must not be fabricated initially.
    assert MissionStageType.DELTA_REPAIR.value not in stage_types
    assert MissionStageType.TARGETED_REEXECUTION.value not in stage_types


def test_plan_is_deterministic_for_same_round_run_and_scope_snapshot() -> None:
    first = plan_test_round_mission(
        test_run_id="TR-1",
        test_round_id="ROUND-1",
        scope_refs=["SCOPE-A", "SCOPE-B"],
    )
    second = plan_test_round_mission(
        test_run_id="TR-1",
        test_round_id="ROUND-1",
        scope_refs=["SCOPE-A", "SCOPE-B"],
    )
    assert first == second


def test_scope_order_does_not_change_stage_or_work_item_identity() -> None:
    first = plan_test_round_mission(
        test_run_id="TR-1",
        test_round_id="ROUND-1",
        scope_refs=["SCOPE-A", "SCOPE-B"],
    )
    second = plan_test_round_mission(
        test_run_id="TR-1",
        test_round_id="ROUND-1",
        scope_refs=["SCOPE-B", "SCOPE-A"],
    )
    first_ids = {stage.stage_instance_id for stage in first.stages}
    second_ids = {stage.stage_instance_id for stage in second.stages}
    assert first_ids == second_ids
    assert set(first.initial_ready_stage_ids) == set(second.initial_ready_stage_ids)
    assert set(first.initial_work_item_ids) == set(second.initial_work_item_ids)


def test_duplicate_or_empty_scope_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="MISSION_PLAN_SCOPE_REQUIRED"):
        plan_test_round_mission(test_run_id="TR", test_round_id="ROUND", scope_refs=[])
    with pytest.raises(ValueError, match="MISSION_PLAN_DUPLICATE_SCOPE_REF"):
        plan_test_round_mission(test_run_id="TR", test_round_id="ROUND", scope_refs=["S1", "S1"])
