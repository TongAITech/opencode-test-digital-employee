from __future__ import annotations

import json

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import (
    Evaluation,
    EvaluationResult,
    FinalReportError,
    Gap,
    GapSeverity,
    GapStatus,
    Mission,
    MissionStatus,
    RC7FinalReportBuilder,
)
from rc7_runtime.defect_loop import DefectRecord, DefectStatus
from rc7_runtime.truth_overlay import append_entity


def test_final_report_requires_convergence_and_preserves_historical_product_fail(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    mission_id = "MISSION-REPORT-1"
    append_entity(
        truth,
        Mission(
            mission_id=mission_id,
            release_id="RC7",
            goal="report truthful closed-loop outcome",
        ),
        release_id="RC7",
        artifact_version=1,
    )

    builder = RC7FinalReportBuilder(truth)
    with pytest.raises(FinalReportError, match="FINAL_REPORT_REQUIRES_CONVERGED_MISSION"):
        builder.snapshot(mission_id)

    # Preserve the trustworthy historical product FAIL. Fixing the defect later
    # must not rewrite this execution conclusion into PASS.
    execution_evaluation = Evaluation(
        evaluation_id="EVAL-EXEC-REPORT-FAIL",
        mission_id=mission_id,
        node="EXECUTION",
        artifact_refs=["ART-EXEC-REPORT"],
        result=EvaluationResult.PASS,
        evaluator_ref="execution-integrity-gate",
        dimensions={
            "test_result": "FAIL",
            "execution_status": "FAIL",
            "integrity_passed": True,
            "failure_class": "PRODUCT",
            "conclusive": True,
        },
        evidence_refs=["EVD-EXEC-REPORT"],
    )
    append_entity(truth, execution_evaluation, release_id="RC7")

    defect_evaluation = Evaluation(
        evaluation_id="EVAL-DEFECT-REPORT-CLOSED",
        mission_id=mission_id,
        node="DEFECT",
        artifact_refs=["ART-DEFECT-REPORT"],
        result=EvaluationResult.PASS,
        evaluator_ref="evaluator-defect-independent",
        dimensions={
            "defect_id": "DEFECT-REPORT-1",
            "defect_state": "CLOSED",
            "fix_verified": True,
            "impact_regression_passed": True,
        },
        evidence_refs=["EXEC-VERIFY-REPORT", "EXEC-REGRESSION-REPORT"],
    )
    append_entity(truth, defect_evaluation, release_id="RC7")

    defect = DefectRecord(
        defect_id="DEFECT-REPORT-1",
        mission_id=mission_id,
        source_gap_id="GAP-PRODUCT-REPORT-1",
        requirement_refs=["REQ-REPORT-1"],
        test_case_ids=["TC-REPORT-1"],
        execution_attempt_ids=["ATT-REPORT-1", "ATT-REPORT-REPRO"],
        expected={"business_code": "EXPECTED"},
        actual={"business_code": "WRONG"},
        evidence_refs=["EVD-EXEC-REPORT", "EVD-RCA-REPORT"],
        severity="HIGH",
        state=DefectStatus.CLOSED,
        reproduction_attempts=1,
        reproduction_passes=1,
        fix_revision="fix-sha-report",
        verification_refs=["EXEC-VERIFY-REPORT"],
        regression_refs=["EXEC-REGRESSION-REPORT"],
        latest_evaluation_id=defect_evaluation.evaluation_id,
    )
    append_entity(truth, defect, release_id="RC7")

    product_gap = Gap(
        gap_id="GAP-PRODUCT-REPORT-1",
        mission_id=mission_id,
        source_node="EXECUTION",
        category="PRODUCT_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="DEFECT",
        description="historical product mismatch fixed and verified",
        state=GapStatus.RESOLVED,
        subject_refs=["ATT-REPORT-1", "TC-REPORT-1"],
        evidence_refs=["EVD-EXEC-REPORT"],
        resolution_evaluation_id=defect_evaluation.evaluation_id,
    )
    append_entity(truth, product_gap, release_id="RC7")

    mission_evaluation = Evaluation(
        evaluation_id="EVAL-MISSION-REPORT-1",
        mission_id=mission_id,
        node="MISSION_EVALUATION",
        artifact_refs=["SNAPSHOT-REPORT-1"],
        result=EvaluationResult.PASS,
        evaluator_ref="mission-sufficiency-gate",
        dimensions={"sufficiency_state": "SUFFICIENT"},
        evidence_refs=["EVD-MISSION-REPORT"],
    )
    append_entity(truth, mission_evaluation, release_id="RC7")
    append_entity(
        truth,
        Mission(
            mission_id=mission_id,
            release_id="RC7",
            goal="report truthful closed-loop outcome",
            state=MissionStatus.CONVERGED,
            sufficiency_state="SUFFICIENT",
            latest_evaluation_id=mission_evaluation.evaluation_id,
        ),
        release_id="RC7",
        artifact_version=2,
    )

    output = tmp_path / "final-report"
    manifest = builder.build(mission_id, str(output))
    assert manifest["source"] == "R1_EVENT_STREAM_PROJECTION"
    assert manifest["mission_state"] == "CONVERGED"
    assert manifest["sufficiency_state"] == "SUFFICIENT"
    assert manifest["defect_status"] == {"CLOSED": 1}
    assert manifest["gap_status"] == {"RESOLVED": 1}
    assert manifest["execution_results"] == [
        {
            "evaluation_id": execution_evaluation.evaluation_id,
            "test_result": "FAIL",
            "execution_status": "FAIL",
            "failure_class": "PRODUCT",
            "conclusive": True,
            "evidence_refs": ["EVD-EXEC-REPORT"],
        }
    ]
    assert len(manifest["truth_digest"]) == 64
    assert (output / "manifest.json").exists()
    assert (output / "index.html").exists()
    on_disk = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk["truth_digest"] == manifest["truth_digest"]
    assert builder.reconcile(manifest)["status"] == "PASS"

    tampered = dict(manifest)
    tampered["defect_status"] = {"CLOSED": 0}
    reconciliation = builder.reconcile(tampered)
    assert reconciliation["status"] == "FAIL"
    assert "defect_status" in reconciliation["mismatches"]
