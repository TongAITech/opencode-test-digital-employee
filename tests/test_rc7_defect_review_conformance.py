from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.defect_loop import DefectRecord, DefectStatus, RootCauseHypothesis
from rc7_runtime.defect_review_conformance import (
    CLOSE_EVALUATOR,
    CONFIRM_EVALUATOR,
    FIX_VERIFICATION_TASK,
    IMPACT_REGRESSION_TASK,
    QUALIFICATION_EVALUATOR,
    DefectReviewConformanceChecker,
)
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Gap,
    GapSeverity,
    GapStatus,
    Mission,
    Task,
    TaskStatus,
)
from rc7_runtime.truth_overlay import append_entity, install_rc7_truth_overlay


MISSION = "MISSION-DEFECT-CONFORMANCE"
RELEASE = "REL-DEFECT-CONFORMANCE"
GAP = "GAP-PRODUCT-1"
DEFECT = "DEFECT-1"
OWNER = "TASK-DEFECT-OWNER"
QUAL = "EVAL-DEFECT-QUAL"
CONFIRM = "EVAL-DEFECT-CONFIRM"
CLOSE = "EVAL-DEFECT-CLOSE"
FIX = "fix-revision-1"
ORIGINAL_TC = "TC-ORIGINAL"
REGRESSION_TC = "TC-REGRESSION"


def _append_execution(
    tmp_path: Path,
    truth: TruthRuntime,
    *,
    artifact_id: str,
    task_id: str,
    task_type: str,
    attempt_id: str,
    tc_id: str,
    dependency_task_ids=(),
):
    evidence_id = "EVD-%s" % task_id
    payload = {
        "record": {
            "attempt_id": attempt_id,
            "tc_id": tc_id,
            "case_version": 1,
            "target_id": "TARGET-1",
            "layer": "L3",
            "worker_id": "runtime-worker",
            "lease_id": "LEASE-%s" % task_id,
            "status": "PASS",
            "integrity_passed": True,
            "actual_result": {"business_code": "OK"},
            "tool_call_refs": ["tool://%s" % task_id],
            "evidence_refs": [evidence_id],
            "assertion_ref": "assertion://%s" % attempt_id,
            "assertion_passed": True,
            "reason": None,
        }
    }
    path = tmp_path / (artifact_id + ".json")
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    append_entity(
        truth,
        Evidence(
            evidence_id=evidence_id,
            mission_id=MISSION,
            kind="RUNTIME_EXECUTION_RECORD",
            source_ref="runtime://formal-execution",
            content_ref="file://" + str(path),
            subject_refs=[task_id, attempt_id, tc_id],
            content_hash=digest,
        ),
        release_id=RELEASE,
    )
    append_entity(
        truth,
        Artifact(
            artifact_id=artifact_id,
            mission_id=MISSION,
            artifact_type="EXECUTION_CONCLUSION",
            producer_task_id=task_id,
            content_ref="file://" + str(path),
            evidence_refs=[evidence_id],
            content_hash=digest,
        ),
        release_id=RELEASE,
    )
    evaluation_id = "EVAL-%s" % task_id
    append_entity(
        truth,
        Evaluation(
            evaluation_id=evaluation_id,
            mission_id=MISSION,
            node="EXECUTION",
            artifact_refs=[artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="runtime-execution-gate",
            dimensions={"test_result": "PASS", "conclusive": True, "attempt_id": attempt_id},
            evidence_refs=[evidence_id],
        ),
        release_id=RELEASE,
    )
    append_entity(
        truth,
        Task(
            task_id=task_id,
            mission_id=MISSION,
            node="EXECUTION",
            task_type=task_type,
            objective="defect validation execution",
            state=TaskStatus.PASS,
            dependency_task_ids=list(dependency_task_ids),
            gap_refs=[GAP],
            output_artifact_refs=[artifact_id],
            evaluation_id=evaluation_id,
        ),
        release_id=RELEASE,
    )
    return artifact_id, task_id, attempt_id, tc_id


def _seed_closed_defect(tmp_path: Path) -> TruthRuntime:
    install_rc7_truth_overlay()
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    append_entity(truth, Mission(mission_id=MISSION, release_id=RELEASE, goal="prove defect review conformance"), release_id=RELEASE)

    append_entity(
        truth,
        Evaluation(
            evaluation_id=QUAL,
            mission_id=MISSION,
            node="DEFECT",
            artifact_refs=["ART-CANDIDATE"],
            result=EvaluationResult.PASS,
            evaluator_ref=QUALIFICATION_EVALUATOR,
            dimensions={
                "qualification": {
                    "execution_trusted": True,
                    "oracle_valid": True,
                    "evidence_complete": True,
                    "script_issue_excluded": True,
                    "data_issue_excluded": True,
                    "environment_issue_excluded": True,
                    "reproducible": True,
                },
                "reproduction_attempts": 1,
                "reproduction_passes": 1,
                "state": "QUALIFYING",
            },
        ),
        release_id=RELEASE,
    )
    append_entity(
        truth,
        Evaluation(
            evaluation_id="EVAL-REPRODUCTION",
            mission_id=MISSION,
            node="EXECUTION",
            artifact_refs=["ART-REPRODUCTION"],
            result=EvaluationResult.PASS,
            evaluator_ref="runtime-reproduction-gate",
            dimensions={
                "purpose": "DEFECT_REPRODUCTION",
                "source_product_gap_id": GAP,
                "attempt_id": "ATT-REPRODUCTION",
                "conclusive": True,
                "reproduced": True,
            },
        ),
        release_id=RELEASE,
    )
    append_entity(
        truth,
        Task(
            task_id="TASK-REPRODUCTION",
            mission_id=MISSION,
            node="EXECUTION",
            task_type="DEFECT_REPRODUCTION",
            objective="reproduce product defect",
            state=TaskStatus.PASS,
            gap_refs=[GAP],
            evaluation_id="EVAL-REPRODUCTION",
        ),
        release_id=RELEASE,
    )

    rca = Evidence(
        evidence_id="EVD-RCA",
        mission_id=MISSION,
        kind="ROOT_CAUSE_EVIDENCE",
        source_ref="runtime://rca",
        content_ref="evidence://rca",
        subject_refs=[DEFECT, "RateDecisionService.apply"],
    )
    fix = Evidence(
        evidence_id="EVD-FIX",
        mission_id=MISSION,
        kind="FIX_REVISION_EVIDENCE",
        source_ref="runtime://fix",
        content_ref="evidence://fix",
        subject_refs=[DEFECT, FIX, "RateDecisionService.apply"],
    )
    append_entity(truth, rca, release_id=RELEASE)
    append_entity(truth, fix, release_id=RELEASE)

    append_entity(
        truth,
        Evaluation(
            evaluation_id=CONFIRM,
            mission_id=MISSION,
            node="DEFECT",
            artifact_refs=["ART-CANDIDATE"],
            result=EvaluationResult.PASS,
            evaluator_ref=CONFIRM_EVALUATOR,
            dimensions={
                "defect_id": DEFECT,
                "defect_state": "CONFIRMED",
                "root_cause_hypothesis_id": "RCA-1",
                "root_cause_confidence": 0.95,
            },
            evidence_refs=[rca.evidence_id],
        ),
        release_id=RELEASE,
    )

    verification = _append_execution(
        tmp_path,
        truth,
        artifact_id="ART-FIX-VERIFICATION",
        task_id="TASK-FIX-VERIFICATION",
        task_type=FIX_VERIFICATION_TASK,
        attempt_id="ATT-FIX-VERIFICATION",
        tc_id=ORIGINAL_TC,
    )
    regression = _append_execution(
        tmp_path,
        truth,
        artifact_id="ART-IMPACT-REGRESSION",
        task_id="TASK-IMPACT-REGRESSION",
        task_type=IMPACT_REGRESSION_TASK,
        attempt_id="ATT-IMPACT-REGRESSION",
        tc_id=REGRESSION_TC,
        dependency_task_ids=[verification[1]],
    )

    append_entity(
        truth,
        Evaluation(
            evaluation_id=CLOSE,
            mission_id=MISSION,
            node="DEFECT",
            artifact_refs=["ART-CANDIDATE"],
            result=EvaluationResult.PASS,
            evaluator_ref=CLOSE_EVALUATOR,
            dimensions={
                "defect_id": DEFECT,
                "defect_state": "CLOSED",
                "fix_revision": FIX,
                "fix_verified": True,
                "verification_attempt_id": verification[2],
                "impact_regression_passed": True,
                "regression_case_ids": [regression[3]],
            },
            evidence_refs=[rca.evidence_id, fix.evidence_id],
        ),
        release_id=RELEASE,
    )
    append_entity(
        truth,
        Task(
            task_id=OWNER,
            mission_id=MISSION,
            node="DEFECT",
            task_type="QUALIFY_DEFECT",
            objective="own product defect lifecycle",
            state=TaskStatus.PASS,
            lease_owner="runtime-defect-owner",
            gap_refs=[GAP],
            output_artifact_refs=["ART-CANDIDATE"],
            evaluation_id=CLOSE,
        ),
        release_id=RELEASE,
    )

    gap = Gap(
        gap_id=GAP,
        mission_id=MISSION,
        source_node="EXECUTION",
        category="PRODUCT_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="DEFECT",
        description="trusted product behavior mismatch",
        state=GapStatus.REPAIRING,
        subject_refs=[ORIGINAL_TC],
        evidence_refs=["EVD-RCA"],
    )
    append_entity(truth, gap, release_id=RELEASE, artifact_version=1)

    hypothesis = RootCauseHypothesis(
        hypothesis_id="RCA-1",
        statement="RateDecisionService returned the wrong decision",
        suspected_symbols=("RateDecisionService.apply",),
        evidence_refs=(rca.evidence_id,),
        confidence=0.95,
    )
    qualified = DefectRecord(
        defect_id=DEFECT,
        mission_id=MISSION,
        source_gap_id=GAP,
        requirement_refs=["REQ-1"],
        test_case_ids=[ORIGINAL_TC],
        execution_attempt_ids=["ATT-ORIGINAL", "ATT-REPRODUCTION"],
        expected={"business_code": "OK"},
        actual={"business_code": "BAD"},
        evidence_refs=[rca.evidence_id],
        state=DefectStatus.EVIDENCE_READY,
        reproduction_attempts=1,
        reproduction_passes=1,
        latest_evaluation_id=QUAL,
    )
    append_entity(truth, qualified, release_id=RELEASE, artifact_version=1)
    confirmed = DefectRecord(
        defect_id=DEFECT,
        mission_id=MISSION,
        source_gap_id=GAP,
        requirement_refs=["REQ-1"],
        test_case_ids=[ORIGINAL_TC],
        execution_attempt_ids=["ATT-ORIGINAL", "ATT-REPRODUCTION"],
        expected={"business_code": "OK"},
        actual={"business_code": "BAD"},
        evidence_refs=[rca.evidence_id, fix.evidence_id],
        state=DefectStatus.FIX_PENDING,
        reproduction_attempts=1,
        reproduction_passes=1,
        root_cause_hypothesis=hypothesis,
        latest_evaluation_id=CONFIRM,
    )
    append_entity(truth, confirmed, release_id=RELEASE, artifact_version=2)
    closed = DefectRecord(
        defect_id=DEFECT,
        mission_id=MISSION,
        source_gap_id=GAP,
        requirement_refs=["REQ-1"],
        test_case_ids=[ORIGINAL_TC],
        execution_attempt_ids=["ATT-ORIGINAL", "ATT-REPRODUCTION"],
        expected={"business_code": "OK"},
        actual={"business_code": "BAD"},
        evidence_refs=[rca.evidence_id, fix.evidence_id],
        state=DefectStatus.CLOSED,
        reproduction_attempts=1,
        reproduction_passes=1,
        root_cause_hypothesis=hypothesis,
        fix_revision=FIX,
        verification_refs=[verification[0]],
        regression_refs=[regression[0]],
        latest_evaluation_id=CLOSE,
    )
    append_entity(truth, closed, release_id=RELEASE, artifact_version=3)

    gap.state = GapStatus.EVIDENCE_PENDING
    append_entity(truth, gap, release_id=RELEASE, artifact_version=2)
    gap.state = GapStatus.RESOLVED
    gap.resolution_evaluation_id = CLOSE
    append_entity(truth, gap, release_id=RELEASE, artifact_version=3)
    return truth


def test_defect_review_conformance_passes_full_closed_lifecycle(tmp_path: Path):
    truth = _seed_closed_defect(tmp_path)
    result = DefectReviewConformanceChecker(truth).check_mission(MISSION)
    assert result.status == "PASS"
    assert result.triggered is True
    assert result.product_gap_ids == (GAP,)
    assert result.closed_defect_ids == (DEFECT,)
    assert result.violations == ()


def test_defect_review_conformance_is_not_triggered_without_product_failure(tmp_path: Path):
    install_rc7_truth_overlay()
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    append_entity(truth, Mission(mission_id="MISSION-NO-DEFECT", release_id=RELEASE, goal="clean mission"), release_id=RELEASE)
    result = DefectReviewConformanceChecker(truth).check_mission("MISSION-NO-DEFECT")
    assert result.status == "PASS"
    assert result.triggered is False


def test_defect_review_conformance_rejects_terminal_label_without_runtime_lineage(tmp_path: Path):
    truth = _seed_closed_defect(tmp_path)
    gap_id = "GAP-FAKE-CLOSED"
    defect_id = "DEFECT-FAKE-CLOSED"
    eval_id = "EVAL-FAKE-CLOSED"
    append_entity(
        truth,
        Evaluation(
            evaluation_id=eval_id,
            mission_id=MISSION,
            node="DEFECT",
            artifact_refs=[],
            result=EvaluationResult.PASS,
            evaluator_ref="independent-looking-reviewer",
            dimensions={"defect_id": defect_id, "defect_state": "CLOSED"},
        ),
        release_id=RELEASE,
    )
    fake_gap = Gap(
        gap_id=gap_id,
        mission_id=MISSION,
        source_node="EXECUTION",
        category="PRODUCT_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="DEFECT",
        description="fake resolved label",
        state=GapStatus.REPAIRING,
    )
    append_entity(truth, fake_gap, release_id=RELEASE, artifact_version=1)
    append_entity(
        truth,
        DefectRecord(
            defect_id=defect_id,
            mission_id=MISSION,
            source_gap_id=gap_id,
            requirement_refs=["REQ-FAKE"],
            test_case_ids=["TC-FAKE"],
            execution_attempt_ids=["ATT-FAKE"],
            expected="OK",
            actual="BAD",
            evidence_refs=["EVD-FAKE"],
            state=DefectStatus.CLOSED,
            fix_revision="fake-fix",
            verification_refs=["ART-FAKE-VERIFY"],
            regression_refs=["ART-FAKE-REGRESSION"],
            latest_evaluation_id=eval_id,
        ),
        release_id=RELEASE,
    )
    fake_gap.state = GapStatus.EVIDENCE_PENDING
    append_entity(truth, fake_gap, release_id=RELEASE, artifact_version=2)
    fake_gap.state = GapStatus.RESOLVED
    fake_gap.resolution_evaluation_id = eval_id
    append_entity(truth, fake_gap, release_id=RELEASE, artifact_version=3)

    result = DefectReviewConformanceChecker(truth).check_mission(MISSION)
    assert result.status == "FAIL"
    assert any(reason.startswith("DEFECT_QUALIFICATION_HISTORY_MISSING:%s" % defect_id) for reason in result.violations)
    assert any(reason.startswith("DEFECT_REPRODUCTION_PROOF_REQUIRED:%s" % defect_id) for reason in result.violations)
    assert any(reason.startswith("DEFECT_FIX_REVISION_EVIDENCE_REQUIRED:%s" % defect_id) for reason in result.violations)
