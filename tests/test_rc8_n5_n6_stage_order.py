from rc8_center.mission_planner import plan_test_round_mission
from rc8_runtime.mission_graph import MissionStageType


def test_n5_prepared_attempt_precedes_n6_executable_readiness():
    plan = plan_test_round_mission(
        test_run_id="run-n5-n6-order",
        test_round_id="round-1",
        scope_refs=("sst-1",),
    )
    by_type = {stage.stage_type: stage for stage in plan.stages}

    n5 = by_type[MissionStageType.PRECONDITION_DATA_PREP.value]
    n6 = by_type[MissionStageType.EXECUTABLE_SPEC.value]

    assert n5.predecessor_ids
    assert n6.predecessor_ids == (n5.stage_instance_id,)
    assert n6.stage_instance_id in n5.successor_ids
    assert n5.stage_instance_id not in n6.successor_ids
