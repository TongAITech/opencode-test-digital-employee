from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_model_economy import (
    DshTokenUsage,
    ModelCallClass,
    TokenEconomyService,
    UsageStatus,
)


DAYTIME = datetime(2026, 10, 29, 2, 0, tzinfo=timezone.utc)
MISSION_ID = "MISSION-QUAL"
RESERVED_TOKENS = 400


def _service(tmp_path: Path, **overrides):
    truth = TruthRuntime(tmp_path / "r1" / "event-stream.jsonl")
    service = TokenEconomyService(
        truth,
        release_id="REL-RC72-QUAL",
        clock=lambda: DAYTIME,
    )
    limits = {
        "max_total_tokens": 10_000,
        "max_model_calls": 10,
        "max_single_call_tokens": RESERVED_TOKENS,
        "max_retry_tokens": 10_000,
        "max_retry_calls": 10,
        "max_same_context_calls": 1,
        "require_measured_usage": True,
        "require_complete_lineage": True,
    }
    limits.update(overrides)
    service.configure_budget(mission_id=MISSION_ID, **limits)
    return truth, service


def _admit(
    service: TokenEconomyService,
    *,
    suffix: str,
    retry: bool = False,
    prompt: Optional[str] = None,
):
    return service.admit_call(
        mission_id=MISSION_ID,
        node="N7",
        stage="EXECUTION",
        workitem_id="WI-%s" % suffix,
        attempt_id="ATT-%s" % suffix,
        agent_id="executor",
        call_class=ModelCallClass.LLM_REQUIRED,
        retry=retry,
        prompt=prompt or "semantic work %s" % suffix,
    )


def _complete(
    service: TokenEconomyService,
    *,
    suffix: str,
    total_tokens: int = 10,
    retry: bool = False,
    prompt: Optional[str] = None,
):
    admission = _admit(service, suffix=suffix, retry=retry, prompt=prompt)
    assert admission.admitted
    service.complete_call(
        admission.call_id,
        DshTokenUsage(
            UsageStatus.MEASURED,
            max(total_tokens - 1, 0),
            1,
            total_tokens,
            "TEST_PROVIDER_USAGE",
        ),
    )
    return admission


def test_total_token_target_overrun_degrades_economy_without_holding_mission(tmp_path: Path):
    _, service = _service(tmp_path, max_total_tokens=100)
    _complete(service, suffix="TOTAL", total_tokens=101)

    qualification = service.qualification(MISSION_ID)
    assert qualification.status == "DEGRADED"
    assert qualification.reason == "MODEL_ECONOMY_QUOTA_TARGET_EXCEEDED"
    assert qualification.status != "HOLD"


def test_model_call_target_overrun_degrades_economy_without_holding_mission(tmp_path: Path):
    _, service = _service(tmp_path, max_model_calls=1)
    _complete(service, suffix="CALL-1")
    _complete(service, suffix="CALL-2")

    qualification = service.qualification(MISSION_ID)
    assert qualification.status == "DEGRADED"
    assert qualification.reason == "MODEL_ECONOMY_CALL_TARGET_EXCEEDED"
    assert qualification.status != "HOLD"


def test_retry_token_target_overrun_degrades_economy_without_holding_mission(tmp_path: Path):
    _, service = _service(tmp_path, max_retry_tokens=50, max_retry_calls=10)
    _complete(service, suffix="RETRY-TOKEN", total_tokens=60, retry=True)

    qualification = service.qualification(MISSION_ID)
    assert qualification.status == "DEGRADED"
    assert qualification.reason == "MODEL_ECONOMY_RETRY_TOKEN_TARGET_EXCEEDED"
    assert qualification.status != "HOLD"


def test_retry_count_target_overrun_degrades_economy_without_holding_mission(tmp_path: Path):
    _, service = _service(tmp_path, max_retry_calls=0, max_retry_tokens=10_000)
    _complete(service, suffix="RETRY-COUNT", retry=True)

    qualification = service.qualification(MISSION_ID)
    assert qualification.status == "DEGRADED"
    assert qualification.reason == "MODEL_ECONOMY_RETRY_CALL_TARGET_EXCEEDED"
    assert qualification.status != "HOLD"


def test_unknown_usage_is_not_measured_zero_and_does_not_cancel_mandatory_execution(tmp_path: Path):
    truth, service = _service(tmp_path)
    first = _admit(service, suffix="UNKNOWN")
    assert first.admitted
    service.complete_call(
        first.call_id,
        DshTokenUsage.unknown("DSH_USAGE_NOT_EMITTED"),
    )

    row = truth.query("rc72_token_call", call_id=first.call_id)[0]
    summary = service.summary(MISSION_ID)
    assert row["usage_status"] == "UNKNOWN"
    assert summary["unknown_usage_calls"] == 1
    assert summary["measured_calls"] == 0
    assert summary["unknown_reserved_tokens"] == RESERVED_TOKENS

    economy_qualification = service.qualification(MISSION_ID)
    assert economy_qualification.status == "HOLD"
    assert economy_qualification.reason == "TOKEN_USAGE_UNKNOWN"

    following = _admit(service, suffix="MANDATORY-AFTER-UNKNOWN")
    assert following.admitted
    assert "PRIOR_TOKEN_USAGE_UNKNOWN" in following.warnings


def test_pathological_same_context_runaway_remains_hard_guard(tmp_path: Path):
    _, service = _service(tmp_path, max_same_context_calls=1)
    _complete(service, suffix="RUNAWAY-1", prompt="same no-progress context")

    blocked = _admit(
        service,
        suffix="RUNAWAY-2",
        prompt="same no-progress context",
    )
    assert not blocked.admitted
    assert blocked.reason == "SAME_CONTEXT_NO_PROGRESS_GUARD"

    qualification = service.qualification(MISSION_ID)
    assert qualification.status == "HOLD"
    assert qualification.reason == "MODEL_ECONOMY_WASTE_GUARD_TRIGGERED"
