from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rc7_runtime.rc72_context_economy import (
    ContextAffinity,
    ExecutionMode,
    SemanticWorkDescriptor,
)
from rc7_runtime.rc72_economy_scheduler import (
    EconomyAwareReadySelector,
    EconomySchedulingError,
)
from rc7_runtime.rc72_model_economy import MissionCriticality, SemanticCostClass


DAYTIME = datetime(2026, 10, 29, 2, 0, tzinfo=timezone.utc)   # 10:00 Asia/Shanghai
EVENING = datetime(2026, 10, 29, 11, 0, tzinfo=timezone.utc)  # 19:00 Asia/Shanghai
NIGHT = datetime(2026, 10, 29, 14, 0, tzinfo=timezone.utc)    # 22:00 Asia/Shanghai


def _item(
    workitem_id,
    *,
    mode=ExecutionMode.SEMANTIC,
    criticality=MissionCriticality.NON_BLOCKING,
    cost=SemanticCostClass.HIGH,
):
    return SemanticWorkDescriptor(
        workitem_id=workitem_id,
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        stage="DESIGN",
        execution_mode=mode,
        mission_criticality=criticality,
        semantic_cost_class=cost,
        affinity=ContextAffinity(requirement_id="REQ-1", sst_id="SST-1"),
        input_refs=("ART-REQ",),
    )


def test_daytime_prefers_deterministic_progress_and_defers_nonblocking_high_cost_semantic():
    plan = EconomyAwareReadySelector().plan(
        [
            _item("WI-DB", mode=ExecutionMode.DETERMINISTIC),
            _item("WI-SEM"),
        ],
        when=DAYTIME,
    )
    assert plan.run_now_workitem_ids == ("WI-DB",)
    assert plan.deferred_workitem_ids == ("WI-SEM",)
    assert plan.reasons["WI-DB"] == "DETERMINISTIC_PROGRESS_NOW"
    assert plan.reasons["WI-SEM"] == "DAYTIME_HIGH_COST_NON_BLOCKING_DEFER_RECOMMENDED"


def test_blocking_semantic_critical_path_runs_now_even_at_full_rate():
    plan = EconomyAwareReadySelector().plan(
        [
            _item(
                "WI-BLOCK",
                criticality=MissionCriticality.BLOCKING,
                cost=SemanticCostClass.HIGH,
            )
        ],
        when=DAYTIME,
    )
    assert plan.run_now_workitem_ids == ("WI-BLOCK",)
    assert plan.deferred_workitem_ids == ()
    assert plan.reasons["WI-BLOCK"] == "MISSION_CRITICAL_PATH_NOW"


def test_daytime_only_high_cost_nonblocking_work_promotes_one_so_mission_never_idles():
    plan = EconomyAwareReadySelector().plan(
        [_item("WI-1"), _item("WI-2"), _item("WI-3")],
        when=DAYTIME,
    )
    assert plan.run_now_workitem_ids == ("WI-1",)
    assert plan.deferred_workitem_ids == ("WI-2", "WI-3")
    assert plan.reasons["WI-1"] == "MISSION_PROGRESS_OVERRIDE_DEFER"
    assert plan.makes_progress is True


def test_evening_ten_to_one_runs_nonblocking_high_cost_semantic_now():
    plan = EconomyAwareReadySelector().plan([_item("WI-SEM")], when=EVENING)
    assert plan.cost_window.name == "BANK_18_21_TEN_TO_ONE"
    assert plan.cost_window.quota_cost_factor == 0.1
    assert plan.run_now_workitem_ids == ("WI-SEM",)
    assert plan.deferred_workitem_ids == ()
    assert plan.reasons["WI-SEM"] == "CHEAP_OR_UNLIMITED_WINDOW_NOW"


def test_after_21_runs_all_ready_work_without_economy_deferral():
    plan = EconomyAwareReadySelector().plan(
        [_item("WI-1"), _item("WI-2")],
        when=NIGHT,
    )
    assert plan.cost_window.name == "BANK_AFTER_21_UNLIMITED"
    assert plan.cost_window.quota_limited is False
    assert plan.run_now_workitem_ids == ("WI-1", "WI-2")
    assert plan.deferred_workitem_ids == ()


def test_low_or_medium_cost_nonblocking_semantic_can_progress_during_daytime():
    plan = EconomyAwareReadySelector().plan(
        [
            _item("WI-LOW", cost=SemanticCostClass.LOW),
            _item("WI-MED", cost=SemanticCostClass.MEDIUM),
            _item("WI-HIGH", cost=SemanticCostClass.HIGH),
        ],
        when=DAYTIME,
    )
    assert plan.run_now_workitem_ids == ("WI-LOW", "WI-MED")
    assert plan.deferred_workitem_ids == ("WI-HIGH",)


def test_cross_mission_selection_is_rejected_instead_of_merging_truth():
    first = _item("WI-1")
    second = SemanticWorkDescriptor(
        workitem_id="WI-2",
        mission_id="MISSION-2",
        node="TEST_DESIGN",
        stage="DESIGN",
        execution_mode=ExecutionMode.SEMANTIC,
        mission_criticality=MissionCriticality.NON_BLOCKING,
        semantic_cost_class=SemanticCostClass.HIGH,
        affinity=ContextAffinity(requirement_id="REQ-2", sst_id="SST-2"),
        input_refs=("ART-REQ-2",),
    )
    with pytest.raises(EconomySchedulingError, match="CROSS_MISSION"):
        EconomyAwareReadySelector().plan([first, second], when=DAYTIME)
