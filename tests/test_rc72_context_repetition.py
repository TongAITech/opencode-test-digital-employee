from __future__ import annotations

from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_context_repetition import (
    ContextRepetitionDetector,
    ContextRepetitionKind,
)
from rc7_runtime.rc72_model_economy import (
    DshTokenUsage,
    ModelCallClass,
    TokenEconomyService,
    UsageStatus,
)


def _service(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1" / "event-stream.jsonl")
    service = TokenEconomyService(truth, release_id="REL-RC72-REPEAT")
    service.configure_budget(
        mission_id="MISSION-1",
        max_total_tokens=100000,
        max_model_calls=100,
        max_single_call_tokens=10000,
        max_retry_tokens=100000,
        max_retry_calls=100,
        max_same_context_calls=10,
        require_measured_usage=False,
        require_complete_lineage=False,
    )
    return truth, service


def _admit(service, *, workitem_id: str, attempt_id: str, prompt: str):
    return service.admit_call(
        mission_id="MISSION-1",
        node="N4_TEST_DESIGN",
        stage="TEST_DESIGN",
        workitem_id=workitem_id,
        attempt_id=attempt_id,
        agent_id="test-design-agent",
        call_class=ModelCallClass.LLM_REQUIRED,
        retry=False,
        prompt=prompt,
    )


def _complete(service, admission, total=30):
    service.complete_call(
        admission.call_id,
        DshTokenUsage(
            status=UsageStatus.MEASURED,
            input_tokens=total - 5,
            output_tokens=5,
            total_tokens=total,
            source="TEST_PROVIDER_USAGE",
        ),
    )


def test_same_workitem_attempt_exact_repeat_is_detected_as_suspect_not_progress_claim(tmp_path: Path):
    truth, service = _service(tmp_path)
    prompt = "same full semantic context"
    first = _admit(service, workitem_id="WI-1", attempt_id="ATT-1", prompt=prompt)
    second = _admit(service, workitem_id="WI-1", attempt_id="ATT-1", prompt=prompt)
    assert first.admitted and second.admitted
    _complete(service, first)
    _complete(service, second)

    report = ContextRepetitionDetector(truth).report("MISSION-1")
    assert report.executed_call_count == 2
    assert report.repeated_group_count == 1
    assert report.duplicate_call_count == 1
    group = report.groups[0]
    assert group.repetition_kind == ContextRepetitionKind.SAME_WORKITEM_ATTEMPT
    assert group.economy_signal == "POTENTIAL_NO_PROGRESS_REPEAT"
    assert group.progress_proven is False
    assert group.workitem_ids == ("WI-1",)
    assert group.attempt_ids == ("ATT-1",)
    assert group.repeated_context_bytes == len(prompt.encode("utf-8"))


def test_cross_attempt_repeat_is_attributed_without_retry_policy_or_blocking(tmp_path: Path):
    truth, service = _service(tmp_path)
    prompt = "unchanged context carried into another attempt"
    first = _admit(service, workitem_id="WI-1", attempt_id="ATT-1", prompt=prompt)
    second = _admit(service, workitem_id="WI-1", attempt_id="ATT-2", prompt=prompt)
    _complete(service, first)
    _complete(service, second)

    report = ContextRepetitionDetector(truth).report("MISSION-1")
    group = report.groups[0]
    assert group.repetition_kind == ContextRepetitionKind.CROSS_ATTEMPT
    assert group.economy_signal == "RETRY_CONTEXT_AMPLIFICATION_CANDIDATE"
    assert group.attempt_ids == ("ATT-1", "ATT-2")
    assert report.cross_attempt_group_count == 1
    # Step 5 observes only; it does not implement Step 6 retry controls.
    assert service.qualification("MISSION-1").status in {"PASS", "DEGRADED"}


def test_cross_workitem_and_attempt_repeat_keeps_explicit_lineage_and_is_not_called_no_progress(tmp_path: Path):
    truth, service = _service(tmp_path)
    prompt = "shared requirement and code context"
    first = _admit(service, workitem_id="WI-1", attempt_id="ATT-1", prompt=prompt)
    second = _admit(service, workitem_id="WI-2", attempt_id="ATT-2", prompt=prompt)
    _complete(service, first)
    _complete(service, second)

    report = ContextRepetitionDetector(truth).report("MISSION-1")
    group = report.groups[0]
    assert group.repetition_kind == ContextRepetitionKind.MIXED
    assert group.economy_signal == "MIXED_CONTEXT_REUSE_CANDIDATE"
    assert group.workitem_ids == ("WI-1", "WI-2")
    assert group.attempt_ids == ("ATT-1", "ATT-2")
    assert report.mixed_group_count == 1
    assert report.same_attempt_suspect_group_count == 0


def test_pending_call_is_not_counted_as_context_that_already_executed(tmp_path: Path):
    truth, service = _service(tmp_path)
    prompt = "context not yet proven executed twice"
    first = _admit(service, workitem_id="WI-1", attempt_id="ATT-1", prompt=prompt)
    pending = _admit(service, workitem_id="WI-1", attempt_id="ATT-1", prompt=prompt)
    _complete(service, first)

    before = ContextRepetitionDetector(truth).report("MISSION-1")
    assert before.executed_call_count == 1
    assert before.repeated_group_count == 0

    _complete(service, pending)
    after = ContextRepetitionDetector(truth).report("MISSION-1")
    assert after.executed_call_count == 2
    assert after.repeated_group_count == 1


def test_different_contexts_do_not_create_false_repeat(tmp_path: Path):
    truth, service = _service(tmp_path)
    first = _admit(service, workitem_id="WI-1", attempt_id="ATT-1", prompt="context-A")
    second = _admit(service, workitem_id="WI-1", attempt_id="ATT-1", prompt="context-B")
    _complete(service, first)
    _complete(service, second)

    report = ContextRepetitionDetector(truth).report("MISSION-1")
    assert report.executed_call_count == 2
    assert report.unique_context_count == 2
    assert report.repeated_group_count == 0
    assert report.duplicate_call_count == 0
    assert report.repeated_context_bytes == 0
