from __future__ import annotations

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.mission_autonomous_driver import MissionAutonomousDriver
from rc7_runtime.mission_stage_dispatch import MissionStageDispatcher
from rc7_runtime.models import Gap, GapSeverity, TaskStatus


@pytest.mark.parametrize(
    "node,category,capabilities",
    [
        ("REQUIREMENT_ANALYSIS", "MISSING_BOUNDARY", ["requirement_reasoning"]),
        ("CODE_ANALYSIS", "CODEGRAPH_INCOMPLETE", ["code_reasoning", "code_reality"]),
        ("TEST_DESIGN", "TEST_CASE_DENSITY_INSUFFICIENT", ["test_design"]),
        ("SCRIPT_READINESS", "SCRIPT_DEFECT", ["test_automation"]),
    ],
)
def test_governed_producer_repair_tasks_are_dispatchable(
    monkeypatch, tmp_path, node, category, capabilities
) -> None:
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "7" * 40)
    mission_id = "MISSION-RC71-REPAIR-%s" % node
    r1 = tmp_path / node / "runtime-state" / "r1" / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id=mission_id,
        release_id="RC7.1",
        goal="prove governed producer repair routing",
    )
    control = ClosedLoopControlPlane(TruthRuntime(r1), "RC7.1", mission_id)
    gap = Gap(
        gap_id="GAP-RC71-%s" % node,
        mission_id=mission_id,
        source_node=node,
        category=category,
        severity=GapSeverity.HIGH,
        target_node=node,
        description="RC7.1 governed repair for %s" % category,
        acceptance_criteria=["repair is independently reevaluated"],
    )
    repair = control.gap_planner.plan(gap, priority=0)
    assert repair is not None
    control.refresh_ready()

    dispatcher = MissionStageDispatcher(control, producer_runner=lambda: "WORKER_DISPATCHED")
    route = dispatcher.next_route()

    assert route is not None
    assert route.task_id == repair.task_id
    assert route.node == node
    assert route.owner == "PRODUCER_WORKER"
    assert route.action == "PRODUCER_WORKER"
    persisted = control.scheduler.task(repair.task_id)
    assert persisted.state == TaskStatus.READY
    assert persisted.required_capabilities == capabilities
    assert persisted.gap_refs == [gap.gap_id]


def test_mission_autonomous_driver_starts_test_design_repair_without_human_dispatch(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "8" * 40)
    mission_id = "MISSION-RC71-AUTO-DESIGN-REPAIR"
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id=mission_id,
        release_id="RC7.1",
        goal="auto-dispatch test design sufficiency repair",
    )
    control = ClosedLoopControlPlane(TruthRuntime(r1), "RC7.1", mission_id)
    gap = Gap(
        gap_id="GAP-RC71-DENSITY",
        mission_id=mission_id,
        source_node="TEST_DESIGN",
        category="TEST_CASE_DENSITY_INSUFFICIENT",
        severity=GapSeverity.HIGH,
        target_node="TEST_DESIGN",
        description="100 obligations require more than 20 shallow cases",
        subject_refs=["ART-DESIGN", "OBL-001", "OBL-100"],
        acceptance_criteria=["case density and diversity sufficiency-v2 gate passes"],
    )
    repair = control.gap_planner.plan(gap, priority=0)
    assert repair is not None
    control.refresh_ready()

    worker_ref = "worker-rc71-delta-designer"

    def run_producer():
        leased = control.lease_next(
            worker_ref=worker_ref,
            capabilities=["test_design"],
        )
        assert leased is not None
        assert leased.task_id == repair.task_id
        control.start(repair.task_id, worker_ref=worker_ref)
        return "STARTED"

    dispatcher = MissionStageDispatcher(control, producer_runner=run_producer)
    driver = MissionAutonomousDriver(control, dispatcher)

    boundary = driver.step()

    assert boundary.status == "PROGRESSED"
    assert boundary.task_id == repair.task_id
    assert boundary.node == "TEST_DESIGN"
    assert boundary.action == "PRODUCER_WORKER"
    persisted = control.scheduler.task(repair.task_id)
    assert persisted.state == TaskStatus.RUNNING
    assert persisted.lease_owner == worker_ref
