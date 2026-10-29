from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.diagnosis import AttemptHistoryEntry, RecoveryDecision
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.attempt_lineage import LineageAwareAttemptHistory
from rc7_runtime.models import Task
from rc7_runtime.rc72_context_economy import (
    ContextAffinity,
    ExecutionMode,
    SemanticWorkDescriptor,
    build_retry_delta,
)
from rc7_runtime.rc72_model_economy import (
    DshTokenUsage,
    MissionCriticality,
    ModelCallClass,
    SemanticCostClass,
    TokenEconomyService,
    UsageStatus,
)
from rc7_runtime.rc72_retry_amplification import (
    RetryAmplificationAuditService,
    RetryAmplificationProofStatus,
)
from rc7_runtime.rc72_retry_context import RetryContextAuditService


def _history() -> LineageAwareAttemptHistory:
    history = LineageAwareAttemptHistory()
    history.append(
        AttemptHistoryEntry(
            attempt_id="ATT-1",
            parent_attempt_id=None,
            tc_id="TC-1",
            case_version=1,
            target_id="FAT1",
            layer="L3",
            status="FAILED",
            evidence_refs=("EVD-FAIL-1",),
            recorded_at=1,
            failure_signature_id="FSIG-1",
        )
    )
    history.reserve_successor(
        RecoveryDecision(
            diagnosis_id="DIAG-1",
            attempt_id="ATT-1",
            action="RETRY_SAME_STEP",
            retry_allowed=True,
            reprepare_allowed=False,
            terminal=False,
            next_attempt_id="ATT-2",
            reason="repair explicit assertion gap",
        )
    )
    return history


def _task() -> Task:
    return Task(
        task_id="WI-1",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        task_type="REPAIR",
        objective="repair the failed assertion with bounded retry context",
        input_artifact_refs=["ART-REQ-1", "ART-CODE-1"],
        gap_refs=["GAP-1"],
        acceptance_criteria=["retry produces evidence"],
        required_capabilities=["filesystem"],
    )


def _descriptor(task: Task, *, retry_delta=None) -> SemanticWorkDescriptor:
    return SemanticWorkDescriptor.from_task(
        task,
        stage="DESIGN",
        execution_mode=ExecutionMode.SEMANTIC,
        mission_criticality=MissionCriticality.BLOCKING,
        semantic_cost_class=SemanticCostClass.HIGH,
        affinity=ContextAffinity(requirement_id="REQ-1", sst_id="SST-1"),
        retry_delta=retry_delta,
    )


def _services(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1" / "event-stream.jsonl")
    economy = TokenEconomyService(truth, release_id="REL-1")
    economy.configure_budget(
        mission_id="MISSION-1",
        max_total_tokens=100000,
        max_model_calls=100,
        max_single_call_tokens=10000,
        max_retry_tokens=100000,
        max_retry_calls=100,
        max_same_context_calls=10,
        require_measured_usage=False,
        require_complete_lineage=True,
    )
    retry_context = RetryContextAuditService(
        truth,
        release_id="REL-1",
        attempt_history=_history(),
    )
    return truth, economy, retry_context


def _call(economy, *, attempt_id: str, retry: bool, prompt: str, tokens=None, unknown=False):
    admission = economy.admit_call(
        mission_id="MISSION-1",
        node="N4_TEST_DESIGN",
        stage="TEST_DESIGN",
        workitem_id="WI-1",
        attempt_id=attempt_id,
        agent_id="test-design-agent",
        call_class=ModelCallClass.LLM_REQUIRED,
        retry=retry,
        prompt=prompt,
        mission_criticality=MissionCriticality.BLOCKING,
        semantic_cost_class=SemanticCostClass.HIGH,
    )
    assert admission.admitted
    if tokens is not None:
        economy.complete_call(
            admission.call_id,
            DshTokenUsage(
                status=UsageStatus.MEASURED,
                input_tokens=max(0, tokens - 5),
                output_tokens=min(5, tokens),
                total_tokens=tokens,
                source="TEST_PROVIDER_USAGE",
            ),
        )
    elif unknown:
        economy.complete_call(
            admission.call_id,
            DshTokenUsage.unknown("TEST_PROVIDER_USAGE_UNKNOWN"),
        )
    return admission


def _observe_delta(retry_context, task, *, full_context_reason=None):
    retry_delta = build_retry_delta(
        previous_attempt_summary_ref="attempt-summary://ATT-1",
        explicit_gap_refs=("GAP-1",),
        delta_evidence_refs=("evidence://delta/db-assertion",),
        changed_dependency_refs=("data://fixture/v2",),
        full_context_reason=full_context_reason,
    )
    return retry_context.observe(
        task=task,
        attempt_id="ATT-2",
        assignment_id="ASN-2",
        descriptor=_descriptor(task, retry_delta=retry_delta),
    )


def test_delta_retry_measures_tokens_against_real_parent_attempt_without_faking_unknown(tmp_path: Path):
    truth, economy, retry_context = _services(tmp_path)
    task = _task()
    _call(economy, attempt_id="ATT-1", retry=False, prompt="parent full context", tokens=100)
    _observe_delta(retry_context, task)
    _call(economy, attempt_id="ATT-2", retry=True, prompt="gap plus delta evidence", tokens=40)

    report = RetryAmplificationAuditService(truth).report("MISSION-1")
    assert report.retry_attempt_count == 1
    assert report.retry_tokens == 40
    assert report.measured_retry_tokens == 40
    assert report.qualification.status == "PASS"
    assert report.qualification.mission_progress_allowed is True

    attempt = report.attempts[0]
    assert attempt.parent_attempt_id == "ATT-1"
    assert attempt.context_mode == "RETRY_DELTA"
    assert attempt.proof_status == RetryAmplificationProofStatus.MEASURED
    assert attempt.retry_tokens == 40
    assert attempt.parent_tokens == 100
    assert attempt.token_amplification_factor == pytest.approx(0.4)
    assert attempt.exact_parent_context_replay_call_count == 0
    assert "RETRY_TOKEN_USAGE_UNKNOWN" not in attempt.signals


def test_exact_parent_prompt_replay_on_delta_retry_is_advisory_not_no_progress_claim(tmp_path: Path):
    truth, economy, retry_context = _services(tmp_path)
    task = _task()
    prompt = "identical semantic prompt"
    _call(economy, attempt_id="ATT-1", retry=False, prompt=prompt, tokens=80)
    _observe_delta(retry_context, task)
    _call(economy, attempt_id="ATT-2", retry=True, prompt=prompt, tokens=60)

    report = RetryAmplificationAuditService(truth).report("MISSION-1")
    attempt = report.attempts[0]
    assert attempt.exact_parent_context_replay_call_count == 1
    assert "DELTA_RETRY_EXACT_PARENT_CONTEXT_REPLAY" in attempt.signals
    assert report.qualification.status == "DEGRADED"
    assert report.qualification.reason == "RETRY_AMPLIFICATION_ECONOMY_SIGNAL"
    assert report.qualification.mission_progress_allowed is True


def test_unknown_retry_context_and_unknown_usage_remain_unknown_not_zero(tmp_path: Path):
    truth, economy, retry_context = _services(tmp_path)
    task = _task()
    _call(economy, attempt_id="ATT-1", retry=False, prompt="parent context", tokens=50)
    row = retry_context.observe(
        task=task,
        attempt_id="ATT-2",
        assignment_id="ASN-2",
        descriptor=_descriptor(task),
    )
    assert row["context_mode"] == "RETRY_DELTA_UNKNOWN"
    _call(economy, attempt_id="ATT-2", retry=True, prompt="retry context unresolved", unknown=True)

    report = RetryAmplificationAuditService(truth).report("MISSION-1")
    attempt = report.attempts[0]
    assert attempt.proof_status == RetryAmplificationProofStatus.UNKNOWN
    assert attempt.retry_tokens is None
    assert report.retry_tokens is None
    assert report.measured_retry_tokens == 0
    assert "RETRY_CONTEXT_UNKNOWN" in attempt.signals
    assert "RETRY_TOKEN_USAGE_UNKNOWN" in attempt.signals
    assert report.qualification.status == "UNKNOWN"
    assert report.qualification.mission_progress_allowed is True


def test_justified_full_context_retry_is_visible_without_becoming_mission_kill_switch(tmp_path: Path):
    truth, economy, retry_context = _services(tmp_path)
    task = _task()
    prompt = "full context is intentionally reconstructed"
    _call(economy, attempt_id="ATT-1", retry=False, prompt=prompt, tokens=70)
    row = _observe_delta(
        retry_context,
        task,
        full_context_reason="upstream contract changed and invalidated the previous summary",
    )
    assert row["context_mode"] == "FULL_CONTEXT_RETRY"
    _call(economy, attempt_id="ATT-2", retry=True, prompt=prompt, tokens=75)

    report = RetryAmplificationAuditService(truth).report("MISSION-1")
    attempt = report.attempts[0]
    assert report.full_context_retry_count == 1
    assert "FULL_CONTEXT_RETRY_JUSTIFIED" in attempt.signals
    assert "FULL_CONTEXT_PARENT_REPLAY_OBSERVED" in attempt.signals
    assert attempt.token_amplification_factor == pytest.approx(75.0 / 70.0)
    # Full-context retry is explicit and reasoned; visibility alone must not block testing.
    assert report.qualification.status == "PASS"
    assert report.qualification.mission_progress_allowed is True


def test_retry_model_call_without_canonical_retry_context_is_orphan_unknown_not_guessed(tmp_path: Path):
    truth, economy, _ = _services(tmp_path)
    _call(economy, attempt_id="ATT-ORPHAN", retry=True, prompt="orphan retry model call", tokens=25)

    report = RetryAmplificationAuditService(truth).report("MISSION-1")
    assert report.retry_attempt_count == 0
    assert len(report.orphan_retry_call_ids) == 1
    assert report.retry_tokens is None
    assert report.qualification.status == "UNKNOWN"
    assert report.qualification.reason == "RETRY_AMPLIFICATION_PROOF_INCOMPLETE"
    assert report.qualification.mission_progress_allowed is True
