from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.defect_loop import DefectClosedLoop, DefectRecord, DefectStatus, RootCauseHypothesis
from rc7_runtime.defect_resolution_control import (
    DefectResolutionControl,
    DefectResolutionControlError,
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
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-DEFECT-RESOLUTION"
RELEASE = "RC7-DEFECT-RESOLUTION"
GAP_ID = "GAP-PRODUCT-RESOLUTION"
TASK_ID = "TASK-DEFECT-OWNER"
ARTIFACT_ID = "ART-DEFECT-CANDIDATE-OWNER"
DEFECT_ID = "DEFECT-RESOLUTION-1"
ORIGINAL_TC = "TC-ORIGINAL-DEFECT"


def _setup(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="close a trusted product defect only after fix verification and impact regression",
        ),
    )
    qualification_eval = Evaluation(
        evaluation_id="EVAL-DEFECT-QUALIFIED",
        mission_id=MISSION,
        node="DEFECT",
        artifact_refs=[ARTIFACT_ID],
        result=EvaluationResult.PASS,
        evaluator_ref="rc7-defect-qualification-gate",
        dimensions={"qualification": "PASS"},
        evidence_refs=["EVD-DEFECT-CANDIDATE"],
    )
    append_entity(truth, qualification_eval, release_id=RELEASE)
    candidate_evidence = Evidence(
        evidence_id="EVD-DEFECT-CANDIDATE",
        mission_id=MISSION,
        kind="DEFECT_CANDIDATE_RECORD",
        source_ref="runtime://defect-qualification",
        content_ref="evidence://defect-candidate",
        subject_refs=[TASK_ID, DEFECT_ID, GAP_ID],
    )
    append_entity(truth, candidate_evidence, release_id=RELEASE)
    candidate_artifact = Artifact(
        artifact_id=ARTIFACT_ID,
        mission_id=MISSION,
        artifact_type="DEFECT_CANDIDATE",
        producer_task_id=TASK_ID,
        content_ref="artifact://defect-candidate",
        evidence_refs=[candidate_evidence.evidence_id],
    )
    append_entity(truth, candidate_artifact, release_id=RELEASE)
    append_entity(
        truth,
        Task(
            task_id=TASK_ID,
            mission_id=MISSION,
            node="DEFECT",
            task_type="QUALIFY_DEFECT",
            objective="own the product defect lifecycle",
            required_capabilities=["defect_analysis"],
            state=TaskStatus.OUTPUT_PRODUCED,
            lease_owner="rc7-runtime-defect-qualifier",
            gap_refs=[GAP_ID],
            output_artifact_refs=[ARTIFACT_ID],
        ),
        release_id=RELEASE,
    )
    append_entity(
        truth,
        Gap(
            gap_id=GAP_ID,
            mission_id=MISSION,
            source_node="EXECUTION",
            category="PRODUCT_DEFECT",
            severity=GapSeverity.HIGH,
            target_node="DEFECT",
            description="trusted product mismatch",
            state=GapStatus.REPAIRING,
            subject_refs=[ORIGINAL_TC, "ATT-ORIGINAL"],
            evidence_refs=[candidate_evidence.evidence_id],
            acceptance_criteria=["fix verified and impact regression passed"],
        ),
        release_id=RELEASE,
    )
    defect = DefectRecord(
        defect_id=DEFECT_ID,
        mission_id=MISSION,
        source_gap_id=GAP_ID,
        requirement_refs=["REQ-1"],
        test_case_ids=[ORIGINAL_TC],
        execution_attempt_ids=["ATT-ORIGINAL", "ATT-REPRO"],
        expected="business_code equals OK",
        actual={"business_code": "BAD"},
        evidence_refs=[candidate_evidence.evidence_id],
        severity="HIGH",
        state=DefectStatus.EVIDENCE_READY,
        reproduction_attempts=1,
        reproduction_passes=1,
        latest_evaluation_id=qualification_eval.evaluation_id,
    )
    DefectClosedLoop.persist(truth, release_id=RELEASE, defect=defect, artifact_version=1)
    return truth, control


def _evidence(truth, evidence_id: str, kind: str, subjects):
    item = Evidence(
        evidence_id=evidence_id,
        mission_id=MISSION,
        kind=kind,
        source_ref="runtime://test/%s" % kind.lower(),
        content_ref="evidence://%s" % evidence_id,
        subject_refs=list(subjects),
    )
    append_entity(truth, item, release_id=RELEASE)
    return item


def _execution(tmp_path: Path, truth, *, artifact_id: str, attempt_id: str, tc_id: str, passed: bool):
    evidence_id = "EVD-" + artifact_id
    evidence = _evidence(truth, evidence_id, "RUNTIME_EXECUTION_RECORD", [attempt_id, tc_id])
    record = {
        "attempt_id": attempt_id,
        "tc_id": tc_id,
        "case_version": 1,
        "target_id": "TARGET-1",
        "layer": "L2",
        "worker_id": "runtime-execution",
        "lease_id": "LEASE-" + attempt_id,
        "status": "PASS" if passed else "FAIL",
        "integrity_passed": True,
        "actual_result": {"business_code": "OK" if passed else "BAD"},
        "tool_call_refs": ["database-call://%s" % attempt_id],
        "evidence_refs": [evidence_id],
        "assertion_ref": "oracle-assertion://%s" % attempt_id,
        "assertion_passed": bool(passed),
        "reason": None if passed else "ORACLE_ASSERTION_FAILED",
    }
    path = tmp_path / (artifact_id + ".json")
    encoded = (json.dumps({"record": record}, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    artifact = Artifact(
        artifact_id=artifact_id,
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id="TASK-EXEC-%s" % attempt_id,
        content_ref="file://" + str(path),
        evidence_refs=[evidence_id],
        content_hash="sha256:" + digest,
    )
    append_entity(truth, artifact, release_id=RELEASE)
    return artifact


def _confirm_and_detect_fix(tmp_path: Path, truth, control):
    rca = _evidence(truth, "EVD-RCA-1", "ROOT_CAUSE_EVIDENCE", [DEFECT_ID, "RateService.fix"])
    resolution = DefectResolutionControl()
    confirmed = resolution.confirm_root_cause(
        control,
        DEFECT_ID,
        hypothesis=RootCauseHypothesis(
            hypothesis_id="RCA-1",
            statement="RateService persisted state after a rejected validation",
            suspected_symbols=("RateService.fix",),
            evidence_refs=(rca.evidence_id,),
            confidence=0.93,
        ),
    )
    assert confirmed.state == DefectStatus.FIX_PENDING
    fix_revision = "fix-sha-abc123"
    fix_evidence = _evidence(
        truth,
        "EVD-FIX-REVISION",
        "FIX_REVISION_EVIDENCE",
        [DEFECT_ID, fix_revision, "RateService.fix"],
    )
    detected = resolution.detect_fix(
        control,
        DEFECT_ID,
        fix_revision=fix_revision,
        fix_evidence_id=fix_evidence.evidence_id,
    )
    assert detected.state == DefectStatus.FIX_DETECTED
    return resolution, fix_revision


def test_defect_closes_only_after_original_case_verification_and_distinct_regression(tmp_path: Path):
    truth, control = _setup(tmp_path)
    resolution, fix_revision = _confirm_and_detect_fix(tmp_path, truth, control)
    verification = _execution(
        tmp_path,
        truth,
        artifact_id="ART-VERIFY-1",
        attempt_id="ATT-VERIFY-1",
        tc_id=ORIGINAL_TC,
        passed=True,
    )
    regression = _execution(
        tmp_path,
        truth,
        artifact_id="ART-REGRESSION-1",
        attempt_id="ATT-REGRESSION-1",
        tc_id="TC-IMPACT-REGRESSION",
        passed=True,
    )

    result = resolution.close_after_verification(
        control,
        DEFECT_ID,
        verification_artifact_id=verification.artifact_id,
        regression_artifact_ids=[regression.artifact_id],
    )

    assert result.defect_state == "CLOSED"
    assert result.fix_revision == fix_revision
    assert result.defect_task_state == "PASS"
    assert result.product_gap_state == "RESOLVED"
    defect = truth.query("rc7_defect", defect_id=DEFECT_ID)[0]
    assert defect["state"] == "CLOSED"
    assert defect["verification_refs"] == [verification.artifact_id]
    assert defect["regression_refs"] == [regression.artifact_id]
    evaluation = truth.query("rc7_evaluation", evaluation_id=result.evaluation_id)[0]
    assert evaluation["dimensions"]["fix_verified"] is True
    assert evaluation["dimensions"]["impact_regression_passed"] is True
    assert control.scheduler.task(TASK_ID).state == TaskStatus.PASS


def test_fix_revision_cannot_be_self_reported_without_matching_r1_evidence(tmp_path: Path):
    truth, control = _setup(tmp_path)
    rca = _evidence(truth, "EVD-RCA-2", "ROOT_CAUSE_EVIDENCE", [DEFECT_ID])
    resolution = DefectResolutionControl()
    resolution.confirm_root_cause(
        control,
        DEFECT_ID,
        hypothesis=RootCauseHypothesis(
            hypothesis_id="RCA-2",
            statement="evidence-backed RCA",
            suspected_symbols=("RateService.fix",),
            evidence_refs=(rca.evidence_id,),
            confidence=0.8,
        ),
    )
    with pytest.raises(DefectResolutionControlError, match="DEFECT_RESOLUTION_EVIDENCE_NOT_DURABLE"):
        resolution.detect_fix(
            control,
            DEFECT_ID,
            fix_revision="fake-sha",
            fix_evidence_id="EVD-NOT-IN-R1",
        )


def test_failed_original_case_fix_verification_reopens_defect_and_keeps_product_gap_open(tmp_path: Path):
    truth, control = _setup(tmp_path)
    resolution, _ = _confirm_and_detect_fix(tmp_path, truth, control)
    failed = _execution(
        tmp_path,
        truth,
        artifact_id="ART-VERIFY-FAIL",
        attempt_id="ATT-VERIFY-FAIL",
        tc_id=ORIGINAL_TC,
        passed=False,
    )

    defect = resolution.reopen_after_failed_verification(
        control,
        DEFECT_ID,
        failed_execution_artifact_id=failed.artifact_id,
    )
    assert defect.state == DefectStatus.REOPENED
    assert truth.query("rc7_gap", gap_id=GAP_ID)[0]["state"] == "REPAIRING"
    assert control.scheduler.task(TASK_ID).state == TaskStatus.OUTPUT_PRODUCED
    durable = truth.query("rc7_defect", defect_id=DEFECT_ID)[0]
    assert durable["state"] == "REOPENED"
