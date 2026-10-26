"""Regression guard for the RC8 N5 -> N6 mission dependency.

N6 executable readiness must never be planned before N5 has prepared the
attempt-specific auth/data/route prerequisites.
"""
from rc8_center.mission_planner import plan_test_round_mission
from rc8_runtime.mission_graph import MissionStageType


def test_n5_precondition_data_prep_is_direct_predecessor_of_n6_executable_spec():
    plan = plan_test_round_mission(
        test_run_id="run-n5-n6-order",
        test_round_id="round-n5-n6-order",
        scope_refs=["sst:STB-N5-N6"],
    )
    by_type = {stage.stage_type: stage for stage in plan.stages}

    n5 = by_type[MissionStageType.PRECONDITION_DATA_PREP.value]
    n6 = by_type[MissionStageType.EXECUTABLE_SPEC.value]

    assert n6.predecessor_ids == (n5.stage_instance_id,)
    assert n5.stage_instance_id in n6.predecessor_ids
    assert n6.stage_instance_id in n5.successor_ids


def test_n7_execution_cannot_bypass_n5_or_n6_in_planned_chain():
    plan = plan_test_round_mission(
        test_run_id="run-n5-n6-n7-order",
        test_round_id="round-n5-n6-n7-order",
        scope_refs=["sst:STB-N5-N6-N7"],
    )
    by_type = {stage.stage_type: stage for stage in plan.stages}

    n5 = by_type[MissionStageType.PRECONDITION_DATA_PREP.value]
    n6 = by_type[MissionStageType.EXECUTABLE_SPEC.value]
    n7 = by_type[MissionStageType.APPLICABLE_LAYER_EXECUTION.value]

    assert n6.predecessor_ids == (n5.stage_instance_id,)
    assert n7.predecessor_ids == (n6.stage_instance_id,)
