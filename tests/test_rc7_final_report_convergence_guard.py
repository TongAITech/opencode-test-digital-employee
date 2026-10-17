from __future__ import annotations

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import final_report as final_report_module
from rc7_runtime.final_report import FinalReportError, RC7FinalReportBuilder
from rc7_runtime.models import Evaluation, EvaluationResult, Mission, MissionStatus
from rc7_runtime.truth_overlay import append_entity, install_rc7_truth_overlay


def test_final_report_rechecks_convergence_authority_before_rendering(tmp_path, monkeypatch):
    install_rc7_truth_overlay()
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    mission_id = "MISSION-REPORT-CONVERGENCE-GUARD"
    release_id = "RC7"
    append_entity(
        truth,
        Mission(mission_id=mission_id, release_id=release_id, goal="guard report"),
        release_id=release_id,
        artifact_version=1,
    )
    evaluation = Evaluation(
        evaluation_id="EVAL-MISSION-REPORT-GUARD",
        mission_id=mission_id,
        node="MISSION_EVALUATION",
        artifact_refs=["ART-MISSION-SNAPSHOT"],
        result=EvaluationResult.PASS,
        evaluator_ref="independent-mission-sufficiency-gate",
        dimensions={"sufficiency_state": "SUFFICIENT"},
    )
    append_entity(truth, evaluation, release_id=release_id)
    append_entity(
        truth,
        Mission(
            mission_id=mission_id,
            release_id=release_id,
            goal="guard report",
            state=MissionStatus.CONVERGED,
            sufficiency_state="SUFFICIENT",
            latest_evaluation_id=evaluation.evaluation_id,
        ),
        release_id=release_id,
        artifact_version=2,
    )

    def reject(_self, _mission_id):
        raise RuntimeError("ORACLE_OR_DEFECT_CONVERGENCE_PROOF_MISSING")

    monkeypatch.setattr(
        final_report_module.MissionConvergenceConformanceChecker,
        "require_pass",
        reject,
    )
    with pytest.raises(
        FinalReportError,
        match="FINAL_REPORT_CONVERGENCE_CONFORMANCE_FAILED:ORACLE_OR_DEFECT_CONVERGENCE_PROOF_MISSING",
    ):
        RC7FinalReportBuilder(truth).snapshot(mission_id)
