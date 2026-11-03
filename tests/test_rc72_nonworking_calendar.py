"""C10: bank quota is restricted ONLY on actual Shanghai working days.

Calendar fixtures below use synthetic 2026-11-05 as a configured holiday and
2026-11-07 as a configured compensatory workday; they do not claim either is
an official Chinese 2026 statutory calendar date. Field must supply the bank
approved statutory calendar explicitly through the trusted JSON policy.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_model_economy import (
    BankCostWindowConfig,
    DshTokenUsage,
    ModelCallClass,
    TokenEconomyError,
    TokenEconomyService,
    UsageStatus,
    classify_bank_cost_window,
)
from rc7_runtime.rc72_context_economy import (
    ContextAffinity, ExecutionMode, SemanticWorkDescriptor,
)
from rc7_runtime.rc72_economy_scheduler import EconomyAwareReadySelector
from rc7_runtime.rc72_model_economy import MissionCriticality, SemanticCostClass


def _shanghai(day, hour, minute=0):
    # Use aware UTC, never the runner machine's local timezone.
    from datetime import timedelta
    utc = datetime.fromisoformat(day + "T00:00:00+00:00")
    return utc + timedelta(hours=hour - 8, minutes=minute)


def _calendar():
    # A synthetic holiday and a synthetic adjusted weekend workday.
    return BankCostWindowConfig(
        non_working_dates=("2026-11-05",),
        makeup_work_dates=("2026-11-07",),
    )


def _descriptor(workitem_id):
    return SemanticWorkDescriptor(
        workitem_id=workitem_id,
        mission_id="M-CAL",
        node="TEST_DESIGN",
        stage="N4",
        execution_mode=ExecutionMode.SEMANTIC,
        mission_criticality=MissionCriticality.NON_BLOCKING,
        semantic_cost_class=SemanticCostClass.HIGH,
        affinity=ContextAffinity(),
        input_refs=("REQ-SOURCE",),
    )


def test_weekends_are_unlimited_all_day_with_no_calendar_override():
    for day in ("2026-11-07", "2026-11-08"):
        for hour in (0, 9, 17, 18, 20, 21, 23):
            window = classify_bank_cost_window(_shanghai(day, hour))
            assert window.name == "BANK_NON_WORKING_DAY_UNLIMITED"
            assert window.quota_limited is False
            assert window.quota_cost_factor == 0.0
            assert window.timezone_name == "Asia/Shanghai"


def test_explicit_weekday_holiday_and_weekend_makeup_shift_properly():
    policy = _calendar()
    holiday = classify_bank_cost_window(_shanghai("2026-11-05", 10), config=policy)
    assert holiday.name == "BANK_NON_WORKING_DAY_UNLIMITED"
    assert not holiday.quota_limited
    assert holiday.quota_cost_factor == 0
    assert classify_bank_cost_window(_shanghai("2026-11-05", 19), config=policy).quota_limited is False
    assert classify_bank_cost_window(_shanghai("2026-11-05", 23), config=policy).quota_cost_factor == 0.0
    # A compensatory weekend workday is NOT free, including after midnight.
    assert classify_bank_cost_window(_shanghai("2026-11-07", 0, 1), config=policy).quota_cost_factor == 1.0
    assert classify_bank_cost_window(_shanghai("2026-11-07", 17, 59), config=policy).quota_cost_factor == 1.0
    assert classify_bank_cost_window(_shanghai("2026-11-07", 18, 0), config=policy).quota_cost_factor == 0.1
    assert classify_bank_cost_window(_shanghai("2026-11-07", 20, 59), config=policy).quota_cost_factor == 0.1
    assert classify_bank_cost_window(_shanghai("2026-11-07", 21, 0), config=policy).quota_limited is False
    # Ordinary workday, same schedule.
    assert classify_bank_cost_window(_shanghai("2026-11-06", 10), config=policy).quota_cost_factor == 1.0


def test_input_calendar_validation_and_canonical_replay_config():
    original = BankCostWindowConfig.from_mapping({
        "timezone_name": "Asia/Shanghai",
        "makeup_work_dates": ["2026-11-14", "2026-11-07"],
        "non_working_dates": ["2026-11-05", "2026-11-03"],
    })
    assert original.makeup_work_dates == ("2026-11-07", "2026-11-14")
    assert BankCostWindowConfig.from_mapping(original.as_mapping()) == original
    assert original.as_mapping()["non_working_dates"] == ["2026-11-03", "2026-11-05"]


@pytest.mark.parametrize("invalid", [
    {"non_working_dates": ["2026-02-30"]},
    {"non_working_dates": ["11/05/2026"]},
    {"non_working_dates": ["2026-11-05", "2026-11-05"]},
    {"makeup_work_dates": ["2026-11-07"], "non_working_dates": ["2026-11-07"]},
    {"makeup_work_dates": "2026-11-07"},
    {"non_working_dates": [20261105]},
    {"makeup_work_dates": [None]},
])
def test_bad_holiday_calendar_fails_without_guessing(invalid):
    with pytest.raises(TokenEconomyError, match="BANK_COST_WINDOW"):
        BankCostWindowConfig.from_mapping(invalid)


def test_non_workday_real_usage_measured_but_charged_zero_in_R1_and_replay(tmp_path):
    ledger = tmp_path / "r1.jsonl"
    truth = TruthRuntime(ledger)
    economy = TokenEconomyService(
        truth, release_id="RC7.2", cost_window_config=_calendar(),
        clock=lambda: _shanghai("2026-11-05", 10),
    )
    economy.configure_budget(
        mission_id="M-CAL", max_total_tokens=10, max_model_calls=1,
        max_single_call_tokens=100, max_retry_tokens=100,
        max_retry_calls=1,
    )
    admission = economy.admit_call(
        mission_id="M-CAL", node="N4_TEST_DESIGN", stage="N4",
        workitem_id="WI-REQUIRED", attempt_id="ATT-1", agent_id="designer",
        call_class=ModelCallClass.LLM_REQUIRED, retry=False, prompt="required design",
        mission_criticality=MissionCriticality.BLOCKING,
    )
    assert admission.admitted
    assert admission.cost_window == "BANK_NON_WORKING_DAY_UNLIMITED"
    assert admission.quota_limited is False
    economy.complete_call(
        admission.call_id,
        DshTokenUsage(UsageStatus.MEASURED, 110, 20, 130, "REAL_PROVIDER_USAGE"),
    )
    call = truth.query("rc72_token_call", call_id=admission.call_id)[0]
    assert call["total_tokens"] == 130
    assert call["quota_equivalent_tokens"] == 0
    summary = economy.summary("M-CAL")
    assert summary["measured_total_tokens"] == 130
    assert summary["measured_quota_equivalent_tokens"] == 0

    replay = TruthRuntime(ledger)
    assert replay.query("rc72_token_budget", budget_id="M-CAL")[0][
        "bank_cost_window_config"
    ]["non_working_dates"] == ["2026-11-05"]
    assert replay.query("rc72_token_call", call_id=admission.call_id)[0]["total_tokens"] == 130


def test_nonworking_schedule_may_advance_high_cost_work_without_deleting_workitem():
    items = [_descriptor("WI-1"), _descriptor("WI-2")]
    scheduler = EconomyAwareReadySelector(cost_window_config=_calendar())
    holiday = scheduler.plan(items, when=_shanghai("2026-11-05", 10))
    assert set(holiday.run_now_workitem_ids + holiday.deferred_workitem_ids) == {"WI-1", "WI-2"}
    assert holiday.deferred_workitem_ids == ()
    assert holiday.cost_window.quota_limited is False
    normal = scheduler.plan(items, when=_shanghai("2026-11-06", 10))
    assert set(normal.run_now_workitem_ids + normal.deferred_workitem_ids) == {"WI-1", "WI-2"}
    # Mission-first override runs one blocking dependency candidate even in
    # an expensive window: economy cannot stall the entire ReleaseBatch.
    assert len(normal.run_now_workitem_ids) == 1
    assert len(normal.deferred_workitem_ids) == 1
    assert normal.reasons[normal.run_now_workitem_ids[0]] == "MISSION_PROGRESS_OVERRIDE_DEFER"
    # The same policy honors a makeup Saturday as a limited working day.
    makeup = scheduler.plan(items, when=_shanghai("2026-11-07", 10))
    assert set(makeup.run_now_workitem_ids + makeup.deferred_workitem_ids) == {"WI-1", "WI-2"}
    assert len(makeup.run_now_workitem_ids) == 1
    assert len(makeup.deferred_workitem_ids) == 1
