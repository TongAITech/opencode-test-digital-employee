import pytest

from rc8_runtime.contracts import RC8ContractError
from rc8_runtime.coverage import CoverageObservation
from rc8_runtime.governance import CoverageDimension, CoverageMetric, SufficiencyResult
from rc8_runtime.sufficiency import (
    DimensionAssessment,
    DimensionState,
    FrozenSufficiencyLedger,
    RequiredDimension,
    evaluate_frozen_ledger,
)


def _required(count=20):
    return tuple(
        RequiredDimension(
            dimension_id="req-%02d" % index,
            dimension=CoverageDimension.REQUIREMENT,
            source_ref="scope:scope-v1#req-%02d" % index,
        )
        for index in range(1, count + 1)
    )


def _ledger(count=20):
    return FrozenSufficiencyLedger(
        ledger_id="ledger-1",
        test_run_id="run-1",
        subject_id="requirement-sufficiency-1",
        policy_version="anti-shrink-v1",
        source_refs=("scope:scope-v1", "requirement-revision:r3"),
        required_dimensions=_required(count),
    )


def _sat(dimension_id):
    return DimensionAssessment(
        dimension_id=dimension_id,
        state=DimensionState.SATISFIED,
        evidence_refs=("evidence:%s" % dimension_id,),
    )


def test_empty_frozen_denominator_is_forbidden():
    with pytest.raises(RC8ContractError, match="EMPTY_DENOMINATOR"):
        FrozenSufficiencyLedger(
            ledger_id="ledger-empty",
            test_run_id="run-1",
            subject_id="stage-1",
            policy_version="v1",
            source_refs=("scope:v1",),
            required_dimensions=(),
        )


def test_rc7_style_three_of_twenty_cannot_become_three_of_three():
    decision = evaluate_frozen_ledger(
        _ledger(20),
        [_sat("req-01"), _sat("req-02"), _sat("req-03")],
        evaluator_id="center",
        worker_claimed_sufficient=True,
    )
    assert decision.result == SufficiencyResult.INSUFFICIENT
    assert decision.required_total == 20
    assert decision.satisfied_total == 3
    assert decision.unknown_total == 17
    assert decision.effective_ratio == pytest.approx(0.15)
    assert decision.worker_claimed_sufficient is True


def test_worker_claim_is_audit_only_and_cannot_override_gap():
    decision = evaluate_frozen_ledger(
        _ledger(1),
        [_sat("req-01")],
        evaluator_id="center",
        active_gap_ids=("gap-P0",),
        worker_claimed_sufficient=True,
    )
    assert decision.result == SufficiencyResult.INSUFFICIENT
    assert decision.active_gap_ids == ("gap-P0",)


def test_not_applicable_requires_reason_and_evidence():
    with pytest.raises(RC8ContractError, match="NOT_APPLICABLE_REQUIRES_REASON_AND_EVIDENCE"):
        DimensionAssessment(
            dimension_id="req-01",
            state=DimensionState.NOT_APPLICABLE,
            reason="not used in this scope",
        )


def test_satisfied_requires_evidence():
    with pytest.raises(RC8ContractError, match="SATISFIED_DIMENSION_REQUIRES_EVIDENCE"):
        DimensionAssessment(dimension_id="req-01", state=DimensionState.SATISFIED)


def test_extra_dimension_cannot_expand_or_replace_frozen_denominator():
    with pytest.raises(RC8ContractError, match="ASSESSMENT_OUTSIDE_FROZEN_LEDGER"):
        evaluate_frozen_ledger(
            _ledger(1),
            [_sat("req-01"), _sat("invented-99")],
            evaluator_id="center",
        )


def test_duplicate_dimension_assessment_is_rejected():
    with pytest.raises(RC8ContractError, match="DUPLICATE_DIMENSION_ASSESSMENT"):
        evaluate_frozen_ledger(
            _ledger(1),
            [_sat("req-01"), _sat("req-01")],
            evaluator_id="center",
        )


def test_all_frozen_dimensions_need_evidence_before_sufficient():
    decision = evaluate_frozen_ledger(
        _ledger(2),
        [_sat("req-01"), _sat("req-02")],
        evaluator_id="center",
        worker_claimed_sufficient=False,
    )
    assert decision.result == SufficiencyResult.SUFFICIENT
    assert decision.required_total == 2
    assert decision.effective_ratio == 1.0
    evaluation = decision.to_evaluation("eval-1")
    assert evaluation.result == SufficiencyResult.SUFFICIENT
    assert evaluation.policy_version == "center-ledger:anti-shrink-v1"
    assert evaluation.unsatisfied_requirement_refs == ()


def test_zero_denominator_coverage_observation_is_fail_closed():
    metric = CoverageMetric(
        metric_id="legacy-zero",
        dimension=CoverageDimension.API,
        covered=0,
        total=0,
        threshold=1.0,
        evidence_refs=(),
    )
    # Legacy metric still exposes its historical ratio, but runtime observation
    # is now the fail-closed boundary: zero denominator cannot enter evidence.
    with pytest.raises(RC8ContractError, match="ZERO_DENOMINATOR_FORBIDDEN"):
        CoverageObservation(
            observation_id="obs-1",
            test_run_id="run-1",
            stage_instance_id="code-sufficiency-1",
            subject_ref="api-scope",
            source_snapshot_ref="code-snapshot-1",
            metric=metric,
            artifact_refs=("artifact-1",),
        )
