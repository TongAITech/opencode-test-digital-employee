"""C10 bank-local configurable schedule: no host timezone and no quota kill-switch."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_context_economy import ContextAffinity, ExecutionMode, SemanticWorkDescriptor
from rc7_runtime.rc72_economy_scheduler import EconomyAwareReadySelector
from rc7_runtime.rc72_model_economy import (
    BankCostWindowConfig,
    DshTokenUsage,
    MissionCriticality,
    ModelCallClass,
    SemanticCostClass,
    TokenEconomyError,
    TokenEconomyService,
    UsageStatus,
    classify_bank_cost_window,
)


def _utc(hour, minute=0):
    return datetime(2026, 10, 29, hour, minute, tzinfo=timezone.utc)


def _policy():
    return BankCostWindowConfig.from_mapping({
        "timezone_name": "Asia/Shanghai",
        "normal_end_hour": 17,
        "discount_end_hour": 20,
        "normal_factor_millis": 1000,
        "discount_factor_millis": 250,
        "unlimited_after_discount": True,
        "post_discount_factor_millis": 0,
    })


def test_default_schedule_stays_18_21_at_ten_to_one_and_after_21_unlimited():
    assert classify_bank_cost_window(_utc(9, 30)).quota_cost_factor == 1.0
    assert classify_bank_cost_window(_utc(10)).quota_cost_factor == 0.1
    assert classify_bank_cost_window(_utc(13)).quota_limited is False
    assert classify_bank_cost_window(_utc(13)).timezone_name == "Asia/Shanghai"


def test_policy_changes_discount_and_unlimited_boundaries_without_host_timezone():
    policy = _policy()
    assert classify_bank_cost_window(_utc(8, 59), config=policy).quota_cost_factor == 1.0
    assert classify_bank_cost_window(_utc(9, 0), config=policy).quota_cost_factor == 0.25
    assert classify_bank_cost_window(_utc(11, 59), config=policy).quota_cost_factor == 0.25
    window = classify_bank_cost_window(_utc(12, 0), config=policy)
    assert window.quota_limited is False
    assert window.quota_cost_factor == 0.0
    assert window.timezone_name == "Asia/Shanghai"


def test_invalid_policy_fails_closed_instead_of_guessing_host_time():
    with pytest.raises(TokenEconomyError, match="TIMEZONE"):
        BankCostWindowConfig(timezone_name="America/Los_Angeles")
    with pytest.raises(TokenEconomyError, match="HOURS"):
        BankCostWindowConfig(normal_end_hour=22, discount_end_hour=21)
    with pytest.raises(TokenEconomyError, match="UNLIMITED_FACTOR"):
        BankCostWindowConfig(post_discount_factor_millis=100)
    with pytest.raises(TokenEconomyError, match="UNKNOWN_CONFIGURATION_KEYS"):
        BankCostWindowConfig.from_mapping({"weekend_unlimited": True})
    with pytest.raises(TokenEconomyError, match="AWARE_DATETIME"):
        classify_bank_cost_window(datetime(2026, 10, 29, 19), config=_policy())


def test_explicit_post_discount_limited_mode_is_honored():
    policy = BankCostWindowConfig(
        unlimited_after_discount=False, post_discount_factor_millis=500,
    )
    night = classify_bank_cost_window(_utc(13), config=policy)
    assert night.quota_limited is True
    assert night.quota_cost_factor == 0.5
    assert night.name == "BANK_AFTER_DISCOUNT_LIMITED"


def test_model_ledger_persists_actual_tokens_separately_from_configured_quota_equivalence(tmp_path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    economy = TokenEconomyService(
        truth, release_id="REL-1", clock=lambda: _utc(12),
        cost_window_config=_policy(),
    )
    economy.configure_budget(
        mission_id="M-1", max_total_tokens=10, max_model_calls=1,
        max_single_call_tokens=100, max_retry_tokens=10, max_retry_calls=1,
    )
    result = economy.admit_call(
        mission_id="M-1", node="N3", stage="N3", workitem_id="WI-1",
        attempt_id="ATT-1", agent_id="AGENT-1",
        call_class=ModelCallClass.LLM_REQUIRED, retry=False, prompt="semantic prompt",
        mission_criticality=MissionCriticality.BLOCKING,
    )
    assert result.admitted
    assert result.cost_window == "BANK_AFTER_DISCOUNT_UNLIMITED"
    assert result.quota_limited is False
    economy.complete_call(
        result.call_id, DshTokenUsage(UsageStatus.MEASURED, 100, 20, 120, "DSH_REAL_USAGE"),
    )
    row = truth.query("rc72_token_call", call_id=result.call_id)[0]
    assert row["total_tokens"] == 120
    assert row["quota_equivalent_tokens"] == 0
    assert row["usage_status"] == "MEASURED"
    assert economy.summary("M-1")["measured_total_tokens"] == 120


def _workitem(workitem_id, *, deterministic=False):
    return SemanticWorkDescriptor(
        workitem_id=workitem_id, mission_id="M-1", node="N4", stage="N4",
        execution_mode=ExecutionMode.DETERMINISTIC if deterministic else ExecutionMode.SEMANTIC,
        mission_criticality=MissionCriticality.NON_BLOCKING,
        semantic_cost_class=SemanticCostClass.LOW if deterministic else SemanticCostClass.HIGH,
        affinity=ContextAffinity(), input_refs=("REF-1",),
    )


def test_scheduler_changes_only_ready_order_not_business_workitem_denominator():
    items = [_workitem("WI-HIGH"), _workitem("WI-DETERMINISTIC", deterministic=True)]
    default = EconomyAwareReadySelector().plan(items, when=_utc(9, 30))
    custom = EconomyAwareReadySelector(cost_window_config=_policy()).plan(items, when=_utc(9, 30))
    assert default.run_now_workitem_ids == ("WI-DETERMINISTIC",)
    assert default.deferred_workitem_ids == ("WI-HIGH",)
    assert set(default.run_now_workitem_ids + default.deferred_workitem_ids) == {"WI-HIGH", "WI-DETERMINISTIC"}
    assert custom.run_now_workitem_ids == ("WI-HIGH", "WI-DETERMINISTIC")
    assert custom.deferred_workitem_ids == ()



def test_real_control_plane_and_cold_resume_share_canonical_bank_window(tmp_path):
    from rc7_runtime import ClosedLoopControlPlane
    from rc7_runtime.models import Mission, Task

    path = tmp_path / "r1.jsonl"
    truth = TruthRuntime(path)
    control = ClosedLoopControlPlane.bootstrap(
        truth, Mission(mission_id="M-LIVE-WINDOW", release_id="REL-C10", goal="window from R1"),
    )
    control.register_task(Task(
        task_id="WI-EXPENSIVE", mission_id="M-LIVE-WINDOW",
        node="TEST_DESIGN", task_type="SEMANTIC", objective="mandatory semantic review",
    ))
    control.register_task(Task(
        task_id="WI-TOOL", mission_id="M-LIVE-WINDOW",
        node="TEST_DATA", task_type="DETERMINISTIC", objective="real DB query",
    ))
    control.schedule_semantics.record(
        mission_id="M-LIVE-WINDOW", workitem_id="WI-EXPENSIVE",
        execution_mode=ExecutionMode.SEMANTIC,
        mission_criticality=MissionCriticality.NON_BLOCKING,
        semantic_cost_class=SemanticCostClass.HIGH,
        source_ref="plan://explicit/expensive",
    )
    control.schedule_semantics.record(
        mission_id="M-LIVE-WINDOW", workitem_id="WI-TOOL",
        execution_mode=ExecutionMode.DETERMINISTIC,
        mission_criticality=MissionCriticality.BLOCKING,
        semantic_cost_class=SemanticCostClass.LOW,
        source_ref="plan://explicit/tool",
    )

    economy = TokenEconomyService(
        truth, release_id="REL-C10", cost_window_config=_policy(),
    )
    economy.configure_budget(
        mission_id="M-LIVE-WINDOW", max_total_tokens=1000,
        max_model_calls=10, max_single_call_tokens=100,
        max_retry_tokens=500, max_retry_calls=10,
    )
    # 17:30 China => 09:30 UTC: configurable policy is discount but fixed
    # default would still classify daytime and defer WI-EXPENSIVE.
    for current_truth in (truth, TruthRuntime(path)):
        resumed = ClosedLoopControlPlane(current_truth, "REL-C10", "M-LIVE-WINDOW")
        resumed.scheduler.clock = lambda: _utc(9, 30)
        plan = resumed.scheduler.ready_tasks("M-LIVE-WINDOW")
        assert {task.task_id for task in plan} == {"WI-EXPENSIVE", "WI-TOOL"}
        assert resumed.economy_scheduler.last_plan is not None
        assert resumed.economy_scheduler.last_plan.deferred_workitem_ids == ()
        assert resumed.economy_scheduler.last_plan.cost_window.quota_cost_factor == 0.25
        assert resumed.economy_scheduler.selector.cost_window_config == _policy()
