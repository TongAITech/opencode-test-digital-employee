from __future__ import annotations

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.mission_stage_dispatch import MissionStageDispatcher, MissionStageDispatchError
from rc7_runtime.models import Gap, GapSeverity, Task


def _control(tmp_path, monkeypatch, mission_id):
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "9" * 40)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id=mission_id,
        release_id="REL-EXEC-REPAIR-DISPATCH",
        goal="govern dynamic execution repair ownership",
    )
    return ClosedLoopControlPlane(
        TruthRuntime(r1),
        "REL-EXEC-REPAIR-DISPATCH",
        mission_id,
    )


def test_forged_execution_repair_cannot_borrow_canonical_node_owner(monkeypatch, tmp_path):
    control = _control(tmp_path, monkeypatch, "MISSION-FORGED-EXEC-REPAIR")
    control.register_task(
        Task(
            task_id="TASK-FORGED-EXEC-REPAIR",
            mission_id=control.mission_id,
            node="EXECUTION",
            task_type="REPAIR",
            objective="attempt to bypass governed Gap ownership",
            required_capabilities=["test_execution"],
            priority=0,
        )
    )
    dispatcher = MissionStageDispatcher(
        control,
        runtime_handlers={"EXECUTION": lambda task: "RUNTIME"},
        producer_runner=lambda: "PRODUCER",
    )

    with pytest.raises(MissionStageDispatchError, match="DYNAMIC_TASK_GOVERNED_GAP_REQUIRED"):
        dispatcher.next_route()


def test_execution_case_pending_repair_is_runtime_owned_and_never_hits_producer(monkeypatch, tmp_path):
    control = _control(tmp_path, monkeypatch, "MISSION-GOVERNED-EXEC-REPAIR")
    gap = Gap(
        gap_id="GAP-EXEC-CASE-PENDING-TC-2",
        mission_id=control.mission_id,
        source_node="EXECUTION",
        category="EXECUTION_CASE_PENDING",
        severity=GapSeverity.HIGH,
        target_node="EXECUTION",
        description="TC-2 has no terminal execution receipt",
        subject_refs=["ART-DESIGN", "TC-2"],
        acceptance_criteria=["execute TC-2 through governed runtime"],
    )
    repair = control.gap_planner.plan(gap, priority=0)
    assert repair is not None
    control.refresh_ready()

    producer_calls = []
    runtime_calls = []
    dispatcher = MissionStageDispatcher(
        control,
        runtime_handlers={
            "EXECUTION": lambda task: runtime_calls.append(task.task_id) or "RUNTIME_EXECUTION_REPAIR"
        },
        producer_runner=lambda: producer_calls.append("producer") or "PRODUCER",
    )

    route = dispatcher.next_route()
    assert route is not None
    assert route.task_id == repair.task_id
    assert route.node == "EXECUTION"
    assert route.owner == "RUNTIME"
    assert route.action == "RUNTIME_HANDLER"

    assert dispatcher.dispatch_next() == "RUNTIME_EXECUTION_REPAIR"
    assert runtime_calls == [repair.task_id]
    assert producer_calls == []
