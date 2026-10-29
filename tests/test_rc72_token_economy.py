from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_model_economy import (
    DshTokenUsage,
    ModelCallClass,
    TokenEconomyError,
    TokenEconomyService,
    TokenMeteredDshLauncher,
    UsageStatus,
    extract_dsh_token_usage,
)


def _service(tmp_path: Path, *, measured: bool = True, lineage: bool = True, same: int = 2):
    truth = TruthRuntime(tmp_path / "r1" / "event-stream.jsonl")
    service = TokenEconomyService(truth, release_id="REL-RC72-TOKEN")
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


def _admit(service: TokenEconomyService, *, prompt: str = "do work", retry: bool = False):
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


def test_measured_usage_persists_to_r1_and_q7_admission_passes(tmp_path: Path):
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
    assert summary["unknown_usage_calls"] == 0
    assert service.qualification("MISSION-1").status == "PASS"

    rows = truth.query("rc72_token_call", mission_id="MISSION-1")
    assert len(rows) == 1
    assert rows[0]["state"] == "COMPLETED"
    assert rows[0]["usage_status"] == "MEASURED"


def test_unknown_usage_holds_q7_and_blocks_following_call_in_strict_mode(tmp_path: Path):
    _, service = _service(tmp_path)
    admission = _admit(service)
    service.complete_call(admission.call_id, DshTokenUsage.unknown("DSH_USAGE_NOT_EMITTED"))

    qualification = service.qualification("MISSION-1")
    assert qualification.status == "HOLD"
    assert qualification.reason == "TOKEN_USAGE_UNKNOWN"

    blocked = _admit(service, prompt="different work")
    assert not blocked.admitted
    assert blocked.reason == "PRIOR_TOKEN_USAGE_UNKNOWN"


def test_budget_reservation_blocks_call_before_quota_overshoot(tmp_path: Path):
    _, service = _service(tmp_path)
    first = _admit(service, prompt="first")
    service.complete_call(
        first.call_id,
        DshTokenUsage(UsageStatus.MEASURED, 500, 150, 650, "TEST_PROVIDER_USAGE"),
    )
    blocked = _admit(service, prompt="second")
    assert not blocked.admitted
    assert blocked.reason == "MISSION_TOKEN_BUDGET_EXHAUSTED"


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


def test_same_exact_context_is_bounded(tmp_path: Path):
    _, service = _service(tmp_path, same=1)
    first = _admit(service, prompt="same prompt")
    service.complete_call(
        first.call_id,
        DshTokenUsage(UsageStatus.MEASURED, 100, 20, 120, "TEST_PROVIDER_USAGE"),
    )
    blocked = _admit(service, prompt="same prompt")
    assert not blocked.admitted
    assert blocked.reason == "SAME_CONTEXT_CALL_BUDGET_EXHAUSTED"


def test_incomplete_lineage_cannot_pass_strict_q7(tmp_path: Path):
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


def test_metered_launcher_never_calls_delegate_when_admission_is_blocked(tmp_path: Path):
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
