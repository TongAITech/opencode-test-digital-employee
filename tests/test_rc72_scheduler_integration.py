from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.control_plane import TaskScheduler
from rc7_runtime.models import Task, TaskStatus
from rc7_runtime.rc72_context_economy import (
    ContextAffinity,
    ExecutionMode,
    SemanticWorkDescriptor,
)
from rc7_runtime.rc72_model_economy import MissionCriticality, SemanticCostClass
from rc7_runtime.rc72_scheduler_integration import (
    EconomyAwareTaskSchedulerAdapter,
    EconomySchedulerIntegrationError,
    attach_economy_scheduler,
)
from rc7_runtime.truth_overlay import install_rc7_truth_overlay


DAYTIME = datetime(2026, 10, 29, 2, 0, tzinfo=timezone.utc)   # 10:00 Asia/Shanghai
EVENING = datetime(2026, 10, 29, 11, 0, tzinfo=timezone.utc)  # 19:00 Asia/Shanghai


def _task(task_id, priority):
    return Task(
        task_id=task_id,
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        task_type="REPAIR",
        objective="governed work %s" % task_id,
        priority=priority,
    )


def _base_scheduler(tmp_path):
    install_rc7_truth_overlay()
    truth = TruthRuntime(tmp_path / "r1" / "event-stream.jsonl")
    scheduler = TaskScheduler(truth, "REL-1")
    scheduler.register(_task("WI-HIGH", 10))
    scheduler.register(_task("WI-DET", 20))
    scheduler.refresh_ready("MISSION-1")
    return scheduler


def _resolver(task):
    mode = ExecutionMode.DETERMINISTIC if task.task_id == "WI-DET" else ExecutionMode.SEMANTIC
    return SemanticWorkDescriptor.from_task(
        task,
        stage="DESIGN",
        execution_mode=mode,
        mission_criticality=MissionCriticality.NON_BLOCKING,
        semantic_cost_class=SemanticCostClass.HIGH,
        affinity=ContextAffinity(requirement_id="REQ-1", sst_id="SST-1"),
    )


def test_daytime_ready_order_is_shared_economy_order_not_persisted_priority_order(tmp_path):
    base = _base_scheduler(tmp_path)
    assert tuple(task.task_id for task in base.ready_tasks("MISSION-1")) == (
        "WI-HIGH",
        "WI-DET",
    )

    adapter = EconomyAwareTaskSchedulerAdapter(
        base,
        descriptor_resolver=_resolver,
        clock=lambda: DAYTIME,
    )
    assert tuple(task.task_id for task in adapter.ready_tasks("MISSION-1")) == (
        "WI-DET",
        "WI-HIGH",
    )
    # Economy ordering is a runtime view; canonical task priority is untouched.
    assert base.task("WI-HIGH").priority == 10
    assert base.task("WI-DET").priority == 20


def test_lease_next_uses_exact_same_daytime_order_as_ready_view(tmp_path):
    base = _base_scheduler(tmp_path)
    adapter = EconomyAwareTaskSchedulerAdapter(
        base,
        descriptor_resolver=_resolver,
        clock=lambda: DAYTIME,
    )
    ready = adapter.ready_tasks("MISSION-1")
    leased = adapter.lease_next("MISSION-1", worker_ref="worker-1", capabilities=())
    assert leased is not None
    assert leased.task_id == ready[0].task_id == "WI-DET"
    assert base.task("WI-DET").state == TaskStatus.LEASED
    assert base.task("WI-HIGH").state == TaskStatus.READY


def test_after_cheaper_work_is_leased_only_high_cost_work_is_promoted_not_stalled(tmp_path):
    base = _base_scheduler(tmp_path)
    adapter = EconomyAwareTaskSchedulerAdapter(
        base,
        descriptor_resolver=_resolver,
        clock=lambda: DAYTIME,
    )
    first = adapter.lease_next("MISSION-1", worker_ref="worker-1", capabilities=())
    assert first is not None and first.task_id == "WI-DET"

    remaining = adapter.ready_tasks("MISSION-1")
    assert tuple(task.task_id for task in remaining) == ("WI-HIGH",)
    assert adapter.last_plan is not None
    assert adapter.last_plan.reasons["WI-HIGH"] == "MISSION_PROGRESS_OVERRIDE_DEFER"


def test_evening_ten_to_one_preserves_canonical_priority_order_for_semantic_work(tmp_path):
    base = _base_scheduler(tmp_path)
    adapter = EconomyAwareTaskSchedulerAdapter(
        base,
        descriptor_resolver=_resolver,
        clock=lambda: EVENING,
    )
    ready = adapter.ready_tasks("MISSION-1")
    assert tuple(task.task_id for task in ready) == ("WI-HIGH", "WI-DET")
    assert adapter.last_plan is not None
    assert adapter.last_plan.cost_window.quota_cost_factor == 0.1


def test_attach_updates_control_and_gap_planner_to_one_scheduler_object(tmp_path):
    base = _base_scheduler(tmp_path)
    gap_planner = SimpleNamespace(scheduler=base)
    control = SimpleNamespace(scheduler=base, gap_planner=gap_planner)
    adapter = attach_economy_scheduler(
        control,
        descriptor_resolver=_resolver,
        clock=lambda: DAYTIME,
    )
    assert control.scheduler is adapter
    assert gap_planner.scheduler is adapter
    with pytest.raises(EconomySchedulerIntegrationError, match="ALREADY_ATTACHED"):
        attach_economy_scheduler(
            control,
            descriptor_resolver=_resolver,
            clock=lambda: DAYTIME,
        )


def test_descriptor_identity_mismatch_fails_closed(tmp_path):
    base = _base_scheduler(tmp_path)

    def bad_resolver(task):
        descriptor = _resolver(task)
        return SemanticWorkDescriptor(
            workitem_id="OTHER",
            mission_id=descriptor.mission_id,
            node=descriptor.node,
            stage=descriptor.stage,
            execution_mode=descriptor.execution_mode,
            mission_criticality=descriptor.mission_criticality,
            semantic_cost_class=descriptor.semantic_cost_class,
            affinity=descriptor.affinity,
            input_refs=descriptor.input_refs,
            gap_refs=descriptor.gap_refs,
        )

    adapter = EconomyAwareTaskSchedulerAdapter(
        base,
        descriptor_resolver=bad_resolver,
        clock=lambda: DAYTIME,
    )
    with pytest.raises(EconomySchedulerIntegrationError, match="WORKITEM_MISMATCH"):
        adapter.ready_tasks("MISSION-1")
