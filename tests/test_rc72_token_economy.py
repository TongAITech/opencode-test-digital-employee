from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_model_economy import (
    DshTokenUsage,
    MissionCriticality,
    ModelCallClass,
    SemanticCostClass,
    TokenEconomyError,
    TokenEconomyService,
    TokenMeteredDshLauncher,
    UsageStatus,
    classify_bank_cost_window,
    extract_dsh_token_usage,
)


DAYTIME = datetime(2026, 10, 29, 2, 0, tzinfo=timezone.utc)   # 10:00 Asia/Shanghai
EVENING = datetime(2026, 10, 29, 11, 0, tzinfo=timezone.utc)  # 19:00 Asia/Shanghai
NIGHT = datetime(2026, 10, 29, 14, 0, tzinfo=timezone.utc)    # 22:00 Asia/Shanghai


def _service(
    tmp_path: Path,
    *,
    measured: bool = True,
    lineage: bool = True,
    same: int = 2,
    when: datetime = DAYTIME,
):
    truth = TruthRuntime(tmp_path / "r1" / "event-stream.jsonl")
    service = TokenEconomyService(
        truth,
        release_id="REL-RC72-TOKEN",
        clock=lambda: when,
    )
    service.configure_budget(
        mission_id="MISSION-1",
        max_total_tokens=1_000,
        max_model_calls=5,
        max_single_call_tokens=400,
        max_retry_tokens=400,
        max_retry_calls=1,
        max_same_context_calls=same,
        require_measured_usage=measured,
        require_complete_lineage=lineage,
    )
    return truth, service


def _admit(
    service: TokenEconomyService,
    *,
    prompt: str = "do work",
    retry: bool = False,
    criticality: MissionCriticality = MissionCriticality.UNKNOWN,
    cost: SemanticCostClass = SemanticCostClass.UNKNOWN,
):
    return service.admit_call(
        mission_id="MISSION-1",
        node="N3",
        stage="TEST_DESIGN",
        workitem_id="WI-1",
        attempt_id="ATT-1",
        agent_id="test-design",
        call_class=ModelCallClass.LLM_REQUIRED,
        retry=retry,
        prompt=prompt,
        mission_criticality=criticality,
        semantic_cost_class=cost,
    )


def test_extract_single_final_usage_is_measured():
    text = json.dumps({
        "type": "response.completed",
        "usage": {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
    })
    usage = extract_dsh_token_usage(text)
    assert usage.status == UsageStatus.MEASURED
    assert usage.input_tokens == 120
    assert usage.output_tokens == 30
    assert usage.total_tokens == 150
    assert usage.source == "DSH_FINAL_USAGE"


def test_extract_ambiguous_usage_fails_closed():
    text = "\n".join([
        json.dumps({"type": "message", "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}}),
        json.dumps({"type": "message", "usage": {"input_tokens": 200, "output_tokens": 20, "total_tokens": 220}}),
    ])
    usage = extract_dsh_token_usage(text)
    assert usage.status == UsageStatus.UNKNOWN
    assert usage.total_tokens == 0
    assert usage.source == "DSH_USAGE_AMBIGUOUS_MULTIPLE_SNAPSHOTS"


def test_bank_cost_window_is_explicit_and_not_host_timezone_dependent():
    daytime = classify_bank_cost_window(DAYTIME)
    assert daytime.name == "BANK_DAYTIME_FULL_RATE"
    assert daytime.timezone_name == "Asia/Shanghai"
    assert daytime.quota_limited is True
    assert daytime.quota_cost_factor == 1.0

    evening = classify_bank_cost_window(EVENING)
    assert evening.name == "BANK_18_21_TEN_TO_ONE"
    assert evening.quota_limited is True
    assert evening.quota_cost_factor == 0.1

    night = classify_bank_cost_window(NIGHT)
    assert night.name == "BANK_AFTER_21_UNLIMITED"
    assert night.quota_limited is False
    assert night.quota_cost_factor == 0.0

    with pytest.raises(TokenEconomyError, match="AWARE_DATETIME"):
        classify_bank_cost_window(datetime(2026, 10, 29, 19, 0))


def test_measured_usage_persists_to_r1_and_economy_qualification_passes(tmp_path: Path):
    truth, service = _service(tmp_path)
    admission = _admit(service)
    assert admission.admitted
    service.complete_call(
        admission.call_id,
        DshTokenUsage(UsageStatus.MEASURED, 250, 50, 300, "TEST_PROVIDER_USAGE"),
    )

    summary = service.summary("MISSION-1")
    assert summary["model_calls"] == 1
    assert summary["measured_calls"] == 1
    assert summary["measured_total_tokens"] == 300
    assert summary["measured_quota_equivalent_tokens"] == 300
    assert summary["unknown_usage_calls"] == 0
    assert service.qualification("MISSION-1").status == "PASS"

    rows = truth.query("rc72_token_call", mission_id="MISSION-1")
    assert len(rows) == 1
    assert rows[0]["state"] == "COMPLETED"
    assert rows[0]["usage_status"] == "MEASURED"
    assert rows[0]["cost_window"] == "BANK_DAYTIME_FULL_RATE"


def test_unknown_usage_holds_economy_but_does_not_cancel_following_mandatory_work(tmp_path: Path):
    _, service = _service(tmp_path)
    admission = _admit(service)
    service.complete_call(admission.call_id, DshTokenUsage.unknown("DSH_USAGE_NOT_EMITTED"))

    qualification = service.qualification("MISSION-1")
    assert qualification.status == "HOLD"
    assert qualification.reason == "TOKEN_USAGE_UNKNOWN"

    following = _admit(service, prompt="different mandatory work")
    assert following.admitted
    assert "PRIOR_TOKEN_USAGE_UNKNOWN" in following.warnings
    assert following.reserved_tokens == 400


def test_budget_pressure_warns_but_does_not_kill_mandatory_work(tmp_path: Path):
    _, service = _service(tmp_path)
    first = _admit(service, prompt="first")
    service.complete_call(
        first.call_id,
        DshTokenUsage(UsageStatus.MEASURED, 500, 150, 650, "TEST_PROVIDER_USAGE"),
    )
    second = _admit(
        service,
        prompt="second required test",
        criticality=MissionCriticality.BLOCKING,
        cost=SemanticCostClass.HIGH,
    )
    assert second.admitted
    assert "MISSION_QUOTA_EQUIVALENT_TARGET_EXCEEDED" in second.warnings
    assert second.schedule_recommendation == "RUN_NOW"


def test_nonblocking_high_cost_work_recommends_cheaper_window_without_dropping_work(tmp_path: Path):
    _, service = _service(tmp_path, when=DAYTIME)
    admission = _admit(
        service,
        prompt="batch semantic review",
        criticality=MissionCriticality.NON_BLOCKING,
        cost=SemanticCostClass.HIGH,
    )
    assert admission.admitted
    assert admission.schedule_recommendation == "DEFER_RECOMMENDED"
    assert "CHEAPER_WINDOW_AVAILABLE" in admission.warnings


def test_blocking_high_cost_work_runs_now_even_in_full_rate_window(tmp_path: Path):
    _, service = _service(tmp_path, when=DAYTIME)
    admission = _admit(
        service,
        prompt="critical semantic dependency",
        criticality=MissionCriticality.BLOCKING,
        cost=SemanticCostClass.HIGH,
    )
    assert admission.admitted
    assert admission.schedule_recommendation == "RUN_NOW"
    assert "CHEAPER_WINDOW_AVAILABLE" not in admission.warnings


def test_evening_ten_to_one_is_reflected_in_quota_equivalent_usage(tmp_path: Path):
    _, service = _service(tmp_path, when=EVENING)
    admission = _admit(service, prompt="evening work")
    assert admission.quota_cost_factor == 0.1
    service.complete_call(
        admission.call_id,
        DshTokenUsage(UsageStatus.MEASURED, 80, 20, 100, "TEST_PROVIDER_USAGE"),
    )
    summary = service.summary("MISSION-1")
    assert summary["measured_total_tokens"] == 100
    assert summary["measured_quota_equivalent_tokens"] == 10


def test_after_21_usage_is_measured_but_not_charged_to_limited_quota(tmp_path: Path):
    _, service = _service(tmp_path, when=NIGHT)
    admission = _admit(service, prompt="night work")
    assert admission.quota_limited is False
    assert admission.quota_cost_factor == 0.0
    service.complete_call(
        admission.call_id,
        DshTokenUsage(UsageStatus.MEASURED, 80, 20, 100, "TEST_PROVIDER_USAGE"),
    )
    summary = service.summary("MISSION-1")
    assert summary["measured_total_tokens"] == 100
    assert summary["measured_quota_equivalent_tokens"] == 0


def test_deterministic_work_is_not_allowed_to_consume_llm_budget(tmp_path: Path):
    _, service = _service(tmp_path)
    blocked = service.admit_call(
        mission_id="MISSION-1",
        node="N1",
        stage="STATE_SYNC",
        workitem_id="WI-DET",
        attempt_id="ATT-DET",
        agent_id="state-sync",
        call_class=ModelCallClass.DETERMINISTIC_NO_LLM,
        retry=False,
        prompt="serialize json",
    )
    assert not blocked.admitted
    assert blocked.reason == "DETERMINISTIC_STEP_MUST_NOT_USE_LLM"


def test_same_exact_context_no_progress_guard_remains_hard(tmp_path: Path):
    _, service = _service(tmp_path, same=1)
    first = _admit(service, prompt="same prompt")
    service.complete_call(
        first.call_id,
        DshTokenUsage(UsageStatus.MEASURED, 100, 20, 120, "TEST_PROVIDER_USAGE"),
    )
    blocked = _admit(service, prompt="same prompt")
    assert not blocked.admitted
    assert blocked.reason == "SAME_CONTEXT_NO_PROGRESS_GUARD"


def test_incomplete_lineage_cannot_pass_strict_economy_qualification(tmp_path: Path):
    _, service = _service(tmp_path)
    admission = service.admit_call(
        mission_id="MISSION-1",
        node="UNKNOWN",
        stage="UNKNOWN",
        workitem_id="UNKNOWN",
        attempt_id="ATT-1",
        agent_id="agent",
        call_class=ModelCallClass.LLM_REQUIRED,
        retry=False,
        prompt="work",
    )
    service.complete_call(
        admission.call_id,
        DshTokenUsage(UsageStatus.MEASURED, 100, 10, 110, "TEST_PROVIDER_USAGE"),
    )
    qualification = service.qualification("MISSION-1")
    assert qualification.status == "HOLD"
    assert qualification.reason == "TOKEN_CALL_LINEAGE_INCOMPLETE"


class _FakeDelegate:
    def __init__(self, raw_path: Path):
        self.raw_path = raw_path
        self.calls = 0

    def execute(self, assignment, prompt):
        self.calls += 1
        self.raw_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_path.write_text(
            json.dumps({
                "type": "response.completed",
                "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100},
            }) + "\n",
            encoding="utf-8",
        )
        invocation = SimpleNamespace(evidence_refs=["file://" + self.raw_path.as_posix()])
        return invocation, {"ok": True}


def test_metered_launcher_wraps_existing_launcher_without_changing_result(tmp_path: Path):
    _, service = _service(tmp_path)
    raw_path = tmp_path / "worker-evidence" / "call.jsonl"
    delegate = _FakeDelegate(raw_path)
    wrapper = TokenMeteredDshLauncher(
        delegate,
        service,
        metadata_resolver=lambda assignment: {
            "node": "N3",
            "stage": "TEST_DESIGN",
            "workitem_id": "WI-1",
            "call_class": "LLM_REQUIRED",
            "retry": False,
            "mission_criticality": "BLOCKING",
            "semantic_cost_class": "HIGH",
        },
    )
    assignment = SimpleNamespace(
        mission_id="MISSION-1",
        attempt_id="ATT-1",
        agent_id="test-design",
    )
    invocation, output = wrapper.execute(assignment, "one compact prompt")
    assert delegate.calls == 1
    assert output == {"ok": True}
    assert invocation.evidence_refs
    summary = service.summary("MISSION-1")
    assert summary["measured_total_tokens"] == 100
    assert service.qualification("MISSION-1").status == "PASS"


def test_metered_launcher_never_calls_delegate_for_hard_waste_guard(tmp_path: Path):
    _, service = _service(tmp_path)
    raw_path = tmp_path / "worker-evidence" / "call.jsonl"
    delegate = _FakeDelegate(raw_path)
    wrapper = TokenMeteredDshLauncher(
        delegate,
        service,
        metadata_resolver=lambda assignment: {
            "node": "N1",
            "stage": "STATE_SYNC",
            "workitem_id": "WI-DET",
            "call_class": "DETERMINISTIC_NO_LLM",
        },
    )
    assignment = SimpleNamespace(mission_id="MISSION-1", attempt_id="ATT-1", agent_id="state-sync")
    with pytest.raises(TokenEconomyError, match="TOKEN_CALL_BLOCKED"):
        wrapper.execute(assignment, "do deterministic work")
    assert delegate.calls == 0
