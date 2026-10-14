from __future__ import annotations

import pytest

from rc6_runtime.truth import EventValidationError, TruthRuntime
from rc7_runtime import Evaluation, EvaluationResult, Gap, GapSeverity
from rc7_runtime.defect_loop import (
    DefectClosedLoop,
    DefectContractError,
    DefectQualificationInput,
    DefectStatus,
    RootCauseHypothesis,
)
from rc7_runtime.truth_overlay import append_entity


def _product_gap(suffix: str = "1") -> Gap:
    return Gap(
        gap_id="GAP-PRODUCT-" + suffix,
        mission_id="MISSION-1",
        source_node="EXECUTION",
        category="PRODUCT_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="DEFECT",
        description="trusted product behavior mismatch",
        subject_refs=["ATT-" + suffix, "TC-1"],
        evidence_refs=["EVD-EXEC-" + suffix],
    )


def _qualified_input() -> DefectQualificationInput:
    return DefectQualificationInput(
        execution_trusted=True,
        oracle_valid=True,
        evidence_complete=True,
        script_issue_excluded=True,
        data_issue_excluded=True,
        environment_issue_excluded=True,
        reproducible=True,
    )


def _candidate(loop: DefectClosedLoop, suffix: str = "1"):
    return loop.create_candidate(
        mission_id="MISSION-1",
        product_gap=_product_gap(suffix),
        requirement_refs=["REQ-1"],
        test_case_id="TC-1",
        execution_attempt_id="ATT-" + suffix,
        expected={"business_code": "REJECTED", "db": "UNCHANGED"},
        actual={"business_code": "REJECTED", "db": "CHANGED"},
        evidence_refs=["EVD-DB-" + suffix],
        severity="HIGH",
    )


def _hypothesis(suffix: str = "1") -> RootCauseHypothesis:
    return RootCauseHypothesis(
        hypothesis_id="RCA-" + suffix,
        statement="validation rejected the request but persistence still executed",
        suspected_symbols=("RateService.adjustRate", "RateRepository.updateRate"),
        evidence_refs=("EVD-RCA-" + suffix,),
        confidence=0.88,
    )


def test_defect_cannot_qualify_from_boolean_reproducible_without_reproduction_evidence() -> None:
    loop = DefectClosedLoop()
    defect = _candidate(loop)
    loop.transition(defect, DefectStatus.QUALIFYING)

    result = loop.evaluate_qualification(defect, _qualified_input())
    assert result.qualified is False
    assert result.evaluation.result.value == "REPAIR_REQUIRED"
    assert "REPRODUCTION_EVIDENCE_MISSING" in result.gaps[0].description
    assert defect.state == DefectStatus.QUALIFYING


def test_defect_requires_rca_before_review_and_closure_requires_fix_plus_regression(tmp_path) -> None:
    loop = DefectClosedLoop()
    defect = _candidate(loop)
    loop.transition(defect, DefectStatus.QUALIFYING)
    loop.record_reproduction(
        defect,
        attempt_id="ATT-REPRO-1",
        reproduced=True,
        evidence_refs=["EVD-REPRO-1"],
    )

    result = loop.evaluate_qualification(defect, _qualified_input())
    assert result.qualified is True
    assert defect.state == DefectStatus.EVIDENCE_READY

    with pytest.raises(DefectContractError, match="DEFECT_REVIEW_REQUIRES_RCA_HYPOTHESIS"):
        loop.transition(defect, DefectStatus.READY_FOR_REVIEW)

    loop.attach_root_cause_hypothesis(defect, _hypothesis())
    loop.transition(defect, DefectStatus.READY_FOR_REVIEW)
    loop.transition(defect, DefectStatus.CONFIRMED, evaluation_id="EVAL-CONFIRM-1")
    loop.transition(defect, DefectStatus.FIX_PENDING)
    loop.transition(defect, DefectStatus.FIX_DETECTED, fix_revision="fix-sha-123")
    loop.transition(defect, DefectStatus.VERIFYING)

    with pytest.raises(DefectContractError, match="DEFECT_FIX_VERIFICATION_EVIDENCE_REQUIRED"):
        loop.transition(defect, DefectStatus.FIXED)

    loop.transition(defect, DefectStatus.FIXED, verification_refs=["EXEC-VERIFY-1"])
    loop.transition(defect, DefectStatus.REGRESSION_TESTING)

    with pytest.raises(DefectContractError, match="DEFECT_CLOSE_REQUIRES_REGRESSION_EVIDENCE"):
        loop.transition(defect, DefectStatus.CLOSED, evaluation_id="EVAL-CLOSE-1")

    loop.transition(
        defect,
        DefectStatus.CLOSED,
        evaluation_id="EVAL-CLOSE-1",
        regression_refs=["EXEC-REGRESSION-1", "EXEC-REGRESSION-2"],
    )
    assert defect.state == DefectStatus.CLOSED
    assert defect.fix_revision == "fix-sha-123"
    assert defect.verification_refs == ["EXEC-VERIFY-1"]
    assert defect.regression_refs == ["EXEC-REGRESSION-1", "EXEC-REGRESSION-2"]

    truth = TruthRuntime(tmp_path / "r1.jsonl")

    # A terminal object carrying a plausible-looking evaluation id is still
    # rejected until that exact independent DEFECT/PASS Evaluation exists in R1.
    with pytest.raises(EventValidationError, match="DURABLE_PASS_REQUIRES_EXISTING_EVALUATION"):
        loop.persist(truth, release_id="RC7", defect=defect, artifact_version=7)

    close_evaluation = Evaluation(
        evaluation_id="EVAL-CLOSE-1",
        mission_id="MISSION-1",
        node="DEFECT",
        artifact_refs=[defect.defect_id],
        result=EvaluationResult.PASS,
        evaluator_ref="evaluator-defect-independent",
        dimensions={
            "defect_id": defect.defect_id,
            "defect_state": "CLOSED",
            "fix_revision": defect.fix_revision,
            "fix_verified": True,
            "impact_regression_passed": True,
        },
        evidence_refs=["EXEC-VERIFY-1", "EXEC-REGRESSION-1", "EXEC-REGRESSION-2"],
    )
    append_entity(truth, close_evaluation, release_id="RC7")

    receipt = loop.persist(truth, release_id="RC7", defect=defect, artifact_version=7)
    assert receipt.status == "PERSISTENCE_VERIFIED"
    projected = truth.query("rc7_defect", defect_id=defect.defect_id)[0]
    assert projected["state"] == "CLOSED"
    assert projected["fix_revision"] == "fix-sha-123"
    assert projected["verification_refs"] == ["EXEC-VERIFY-1"]
    assert projected["regression_refs"] == ["EXEC-REGRESSION-1", "EXEC-REGRESSION-2"]

    replayed = TruthRuntime(tmp_path / "r1.jsonl")
    assert replayed.query("rc7_defect", defect_id=defect.defect_id)[0]["state"] == "CLOSED"


def test_same_root_cause_and_same_symptom_is_duplicate_but_related_symptom_is_not() -> None:
    loop = DefectClosedLoop()
    existing = _candidate(loop, "A")
    candidate = _candidate(loop, "B")
    related = loop.create_candidate(
        mission_id="MISSION-1",
        product_gap=_product_gap("C"),
        requirement_refs=["REQ-1"],
        test_case_id="TC-RELATED",
        execution_attempt_id="ATT-C",
        expected={"business_code": "REJECTED"},
        actual={"business_code": "TIMEOUT"},
        evidence_refs=["EVD-RELATED"],
    )

    loop.attach_root_cause_hypothesis(existing, _hypothesis("A"))
    loop.attach_root_cause_hypothesis(candidate, _hypothesis("B"))
    loop.attach_root_cause_hypothesis(related, _hypothesis("C"))

    assert loop.duplicate_of(candidate, [existing]) == existing.defect_id
    assert loop.duplicate_of(related, [existing]) is None
