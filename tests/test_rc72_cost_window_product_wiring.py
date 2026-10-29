from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import ClosedLoopControlPlane, RC72EconomyClosedLoopControlPlane
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.rc72_context_economy import ExecutionMode
from rc7_runtime.rc72_model_economy import MissionCriticality, SemanticCostClass
from rc7_runtime.rc72_scheduler_integration import EconomyAwareTaskSchedulerAdapter
from rc7_runtime.rc72_schedule_semantics import WorkScheduleSemanticsService


DAYTIME = datetime(2026, 10, 29, 2, 0, tzinfo=timezone.utc)  # 10:00 Asia/Shanghai


def _control(tmp_path: Path) -> ClosedLoopControlPlane:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    return ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id="M-SCHED-1", release_id="REL-1", goal="prove real cost-window wiring"),
    )


def _task(task_id: str, priority: int, objective: str) -> Task:
    return Task(
        task_id=task_id,
        mission_id="M-SCHED-1",
        node="TEST_DESIGN",
        task_type="SEMANTIC_WORK",
        objective=objective,
        priority=priority,
    )


def test_closed_loop_control_plane_is_economy_aware_by_default(tmp_path: Path) -> None:
    control = _control(tmp_path)

    assert isinstance(control, RC72EconomyClosedLoopControlPlane)
    assert isinstance(control.scheduler, EconomyAwareTaskSchedulerAdapter)
    assert control.gap_planner.scheduler is control.scheduler
    assert isinstance(control.schedule_semantics, WorkScheduleSemanticsService)


def test_missing_semantics_never_guesses_from_task_text_and_runs_now(tmp_path: Path) -> None:
    control = _control(tmp_path)
    task = _task(
        "WI-NO-SEMANTICS",
        10,
        "critical blocking extremely expensive work words must not become scheduling truth",
    )
    control.register_task(task)

    descriptor = control.schedule_semantics.resolve(control.scheduler.task(task.task_id))
    assert descriptor.execution_mode == ExecutionMode.SEMANTIC
    assert descriptor.mission_criticality == MissionCriticality.UNKNOWN
    assert descriptor.semantic_cost_class == SemanticCostClass.UNKNOWN

    control.scheduler.clock = lambda: DAYTIME
    ready = control.scheduler.ready_tasks("M-SCHED-1")
    assert tuple(item.task_id for item in ready) == ("WI-NO-SEMANTICS",)
    assert control.scheduler.last_plan is not None
    assert control.scheduler.last_plan.run_now_workitem_ids == ("WI-NO-SEMANTICS",)
    assert control.scheduler.last_plan.deferred_workitem_ids == ()


def test_explicit_high_cost_nonblocking_truth_reorders_real_control_without_scope_loss(tmp_path: Path) -> None:
    control = _control(tmp_path)
    high = _task("WI-HIGH", 10, "explicit high-cost semantic work")
    normal = _task("WI-UNKNOWN", 20, "ordinary work without scheduling semantics")
    control.register_task(high)
    control.register_task(normal)

    control.schedule_semantics.record(
        mission_id="M-SCHED-1",
        workitem_id="WI-HIGH",
        execution_mode=ExecutionMode.SEMANTIC,
        mission_criticality=MissionCriticality.NON_BLOCKING,
        semantic_cost_class=SemanticCostClass.HIGH,
        source_ref="planning://M-SCHED-1/WI-HIGH/semantic-cost-v1",
    )
    control.scheduler.clock = lambda: DAYTIME

    ready = control.scheduler.ready_tasks("M-SCHED-1")
    assert tuple(item.task_id for item in ready) == ("WI-UNKNOWN", "WI-HIGH")
    assert control.scheduler.last_plan is not None
    assert control.scheduler.last_plan.run_now_workitem_ids == ("WI-UNKNOWN",)
    assert control.scheduler.last_plan.deferred_workitem_ids == ("WI-HIGH",)

    # Economy changes only the runtime ordering view. Canonical scope/priority is intact.
    rows = control.truth.query("rc7_task", mission_id="M-SCHED-1")
    assert {row["task_id"] for row in rows} == {"WI-HIGH", "WI-UNKNOWN"}
    assert control.scheduler.task("WI-HIGH").priority == 10
    assert control.scheduler.task("WI-UNKNOWN").priority == 20

    leased = control.lease_next(worker_ref="worker-1", capabilities=())
    assert leased is not None and leased.task_id == "WI-UNKNOWN"
    assert control.scheduler.task("WI-UNKNOWN").state == TaskStatus.LEASED
    assert control.scheduler.task("WI-HIGH").state == TaskStatus.READY


def test_schedule_semantics_survive_r1_replay_and_remain_explicit(tmp_path: Path) -> None:
    path = tmp_path / "r1.jsonl"
    truth = TruthRuntime(path)
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id="M-SCHED-1", release_id="REL-1", goal="replay scheduling truth"),
    )
    control.register_task(_task("WI-HIGH", 10, "work"))
    recorded = control.schedule_semantics.record(
        mission_id="M-SCHED-1",
        workitem_id="WI-HIGH",
        execution_mode=ExecutionMode.SEMANTIC,
        mission_criticality=MissionCriticality.NON_BLOCKING,
        semantic_cost_class=SemanticCostClass.HIGH,
        source_ref="planning://explicit/scheduling/decision",
    )

    replayed = TruthRuntime(path)
    service = WorkScheduleSemanticsService(replayed, release_id="REL-1")
    descriptor = service.resolve(control.scheduler.task("WI-HIGH"))

    assert recorded["source_ref"] == "planning://explicit/scheduling/decision"
    assert descriptor.mission_criticality == MissionCriticality.NON_BLOCKING
    assert descriptor.semantic_cost_class == SemanticCostClass.HIGH
    rows = replayed.query("rc72_work_schedule_semantics", workitem_id="WI-HIGH")
    assert len(rows) == 1
    assert rows[0]["artifact_version"] == 1
