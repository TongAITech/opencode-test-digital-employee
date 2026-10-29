from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import ClosedLoopControlPlane
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.rc72_context_economy import ExecutionMode
from rc7_runtime.rc72_model_economy import MissionCriticality, SemanticCostClass
from rc7_runtime.state_machine import transition_task
from rc7_runtime.truth_overlay import append_entity


DAYTIME = datetime(2026, 10, 29, 2, 0, tzinfo=timezone.utc)  # 10:00 Asia/Shanghai


def _control(tmp_path: Path) -> ClosedLoopControlPlane:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id="M-CP-1",
            release_id="REL-1",
            goal="prove canonical critical path no-delay",
        ),
    )
    control.scheduler.clock = lambda: DAYTIME
    return control


def _task(task_id: str, priority: int, dependencies=()) -> Task:
    return Task(
        task_id=task_id,
        mission_id="M-CP-1",
        node="TEST_DESIGN",
        task_type="SEMANTIC_WORK",
        objective="work %s" % task_id,
        priority=priority,
        dependency_task_ids=list(dependencies),
    )


def _high_nonblocking(control: ClosedLoopControlPlane, task_id: str) -> None:
    control.schedule_semantics.record(
        mission_id="M-CP-1",
        workitem_id=task_id,
        execution_mode=ExecutionMode.SEMANTIC,
        mission_criticality=MissionCriticality.NON_BLOCKING,
        semantic_cost_class=SemanticCostClass.HIGH,
        source_ref="planning://M-CP-1/%s/high-nonblocking" % task_id,
    )


def test_transitive_dependency_forces_high_cost_work_now_before_independent_sibling(tmp_path: Path) -> None:
    control = _control(tmp_path)
    control.register_task(_task("WI-UP", 20))
    control.register_task(_task("WI-INDEPENDENT", 10))
    control.register_task(_task("WI-MID", 30, ("WI-UP",)))
    control.register_task(_task("WI-DOWN", 40, ("WI-MID",)))
    _high_nonblocking(control, "WI-UP")
    _high_nonblocking(control, "WI-INDEPENDENT")

    ready = control.scheduler.ready_tasks("M-CP-1")

    assert tuple(task.task_id for task in ready) == ("WI-UP", "WI-INDEPENDENT")
    assert control.scheduler.last_plan is not None
    assert control.scheduler.last_plan.run_now_workitem_ids == ("WI-UP",)
    assert control.scheduler.last_plan.deferred_workitem_ids == ("WI-INDEPENDENT",)
    assert control.scheduler.last_plan.reasons["WI-UP"] == "MISSION_CRITICAL_PATH_NOW"
    assessment = control.critical_path.assessment("WI-UP")
    assert assessment is not None
    assert assessment.graph_status == "VERIFIED"
    assert assessment.forced_blocking is True
    assert assessment.downstream_workitem_ids == ("WI-DOWN", "WI-MID")

    leased = control.lease_next(worker_ref="worker-1", capabilities=())
    assert leased is not None and leased.task_id == "WI-UP"
    assert control.scheduler.task("WI-UP").state == TaskStatus.LEASED
    assert control.scheduler.task("WI-INDEPENDENT").state == TaskStatus.READY


def test_cancelled_downstream_no_longer_makes_upstream_critical(tmp_path: Path) -> None:
    control = _control(tmp_path)
    control.register_task(_task("WI-UP", 20))
    control.register_task(_task("WI-NORMAL", 10))
    control.register_task(_task("WI-DOWN", 30, ("WI-UP",)))
    _high_nonblocking(control, "WI-UP")

    base = control.scheduler.delegate
    row = base._required_row("WI-DOWN")
    downstream = base.task("WI-DOWN")
    transition_task(downstream, TaskStatus.CANCELLED)
    base._persist_task(downstream, int(row["artifact_version"]) + 1)

    ready = control.scheduler.ready_tasks("M-CP-1")

    assert tuple(task.task_id for task in ready) == ("WI-NORMAL", "WI-UP")
    assert control.scheduler.last_plan is not None
    assert control.scheduler.last_plan.run_now_workitem_ids == ("WI-NORMAL",)
    assert control.scheduler.last_plan.deferred_workitem_ids == ("WI-UP",)
    assessment = control.critical_path.assessment("WI-UP")
    assert assessment is not None
    assert assessment.graph_status == "VERIFIED"
    assert assessment.forced_blocking is False
    assert assessment.reason == "NO_UNFINISHED_DOWNSTREAM_DEPENDENCY"


def test_incomplete_dependency_graph_fails_safe_to_run_now_never_economy_defer(tmp_path: Path) -> None:
    control = _control(tmp_path)
    control.register_task(_task("WI-HIGH", 20))
    control.register_task(_task("WI-NORMAL", 10))
    _high_nonblocking(control, "WI-HIGH")

    # Bypass scheduler registration deliberately to simulate replayed/corrupted
    # dependency truth. Economy logic must not guess around this uncertainty.
    append_entity(
        control.truth,
        _task("WI-BROKEN", 30, ("WI-MISSING",)),
        release_id="REL-1",
        artifact_version=1,
    )

    ready = control.scheduler.ready_tasks("M-CP-1")

    assert {task.task_id for task in ready} == {"WI-HIGH", "WI-NORMAL"}
    assert control.scheduler.last_plan is not None
    assert "WI-HIGH" in control.scheduler.last_plan.run_now_workitem_ids
    assert "WI-HIGH" not in control.scheduler.last_plan.deferred_workitem_ids
    assert control.scheduler.last_plan.reasons["WI-HIGH"] == "MISSION_CRITICAL_PATH_NOW"
    assessment = control.critical_path.assessment("WI-HIGH")
    assert assessment is not None
    assert assessment.graph_status == "UNSAFE"
    assert assessment.forced_blocking is True
    assert assessment.reason.startswith("DEPENDENCY_GRAPH_UNSAFE_RUN_NOW:")
    assert "DEPENDENCY_NOT_IN_MISSION_GRAPH" in assessment.reason


def test_priority_and_objective_words_cannot_create_critical_path_without_dependency(tmp_path: Path) -> None:
    control = _control(tmp_path)
    control.register_task(
        Task(
            task_id="WI-WORDS",
            mission_id="M-CP-1",
            node="CRITICAL_PATH_BLOCKING",
            task_type="URGENT_EXPENSIVE",
            objective="blocking critical must-run immediate high cost",
            priority=0,
        )
    )
    descriptor = control.critical_path.resolve(control.scheduler.task("WI-WORDS"))
    assessment = control.critical_path.assessment("WI-WORDS")

    assert descriptor.mission_criticality == MissionCriticality.UNKNOWN
    assert assessment is not None
    assert assessment.graph_status == "VERIFIED"
    assert assessment.effective_criticality == MissionCriticality.UNKNOWN
    assert assessment.reason == "NO_UNFINISHED_DOWNSTREAM_DEPENDENCY"
