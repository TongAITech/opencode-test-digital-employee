from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.mission_evidence_builder import MissionEvidenceBuildError
from rc7_runtime.mission_formal_evidence_builder import R1FormalMissionEvidenceSnapshotBuilder
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence, Mission, Task, TaskStatus
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-FORMAL-SNAPSHOT"
RELEASE = "RC7-FORMAL-SNAPSHOT"
TC_ID = "TC-FORMAL-SNAPSHOT"
DESIGN_TASK = "TASK-DESIGN-FORMAL-SNAPSHOT"
DESIGN_ARTIFACT = "ART-DESIGN-FORMAL-SNAPSHOT"


def _write(path: Path, payload):
    encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _truth(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    append_entity(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="only latest ordinary formal PASS may verify mission coverage",
        ),
        release_id=RELEASE,
    )
    design_path = tmp_path / "design.json"
    design_payload = {
        "semantic_payload": {
            "obligations": [
                {
                    "obligation_id": "OBL-RULE-FORMAL",
                    "kind": "BUSINESS_RULE",
                    "risk": "HIGH",
                    "required": True,
                },
                {
                    "obligation_id": "OBL-CODE-FORMAL",
                    "kind": "CODE_IMPACT",
                    "risk": "CRITICAL",
                    "required": True,
                },
            ],
            "cases": [
                {
                    "tc_id": TC_ID,
                    "risk": "HIGH",
                    "coverage_links": [
                        {"subject_id": "OBL-RULE-FORMAL"},
                        {"subject_id": "OBL-CODE-FORMAL"},
                    ],
                }
            ],
        }
    }
    digest = _write(design_path, design_payload)
    evidence = Evidence(
        evidence_id="EVD-DESIGN-FORMAL",
        mission_id=MISSION,
        kind="TEST_DESIGN_PROOF",
        source_ref="runtime://test-design",
        content_ref="file://" + str(design_path),
        subject_refs=[DESIGN_TASK, DESIGN_ARTIFACT],
        content_hash=digest,
    )
    append_entity(truth, evidence, release_id=RELEASE)
    append_entity(
        truth,
        Artifact(
            artifact_id=DESIGN_ARTIFACT,
            mission_id=MISSION,
            artifact_type="TEST_DESIGN_MODEL",
            producer_task_id=DESIGN_TASK,
            content_ref="file://" + str(design_path),
            evidence_refs=[evidence.evidence_id],
            content_hash=digest,
        ),
        release_id=RELEASE,
    )
    design_eval = Evaluation(
        evaluation_id="EVAL-DESIGN-FORMAL",
        mission_id=MISSION,
        node="TEST_DESIGN",
        artifact_refs=[DESIGN_ARTIFACT],
        result=EvaluationResult.PASS,
        evaluator_ref="independent-test-design-gate",
        evidence_refs=[evidence.evidence_id],
    )
    append_entity(truth, design_eval, release_id=RELEASE)
    append_entity(
        truth,
        Task(
            task_id=DESIGN_TASK,
            mission_id=MISSION,
            node="TEST_DESIGN",
            task_type="ANALYZE",
            objective="accepted design truth",
            state=TaskStatus.PASS,
            output_artifact_refs=[DESIGN_ARTIFACT],
            evaluation_id=design_eval.evaluation_id,
        ),
        release_id=RELEASE,
    )
    return truth


def _execution(
    tmp_path: Path,
    truth: TruthRuntime,
    *,
    suffix: str,
    passed: bool,
    purpose=None,
    formal_overrides=None,
):
    task_id = "TASK-EXEC-%s" % suffix
    artifact_id = "ART-EXEC-%s" % suffix
    evidence_id = "EVD-EXEC-%s" % suffix
    evaluation_id = "EVAL-EXEC-%s" % suffix
    attempt_id = "ATT-%s" % suffix
    conclusion_path = tmp_path / ("execution-conclusion-%s.json" % suffix.lower())
    formal_path = tmp_path / ("execution-formal-%s.json" % suffix.lower())
    record = {
        "attempt_id": attempt_id,
        "tc_id": TC_ID,
        "case_version": 1,
        "target_id": "TARGET-FORMAL",
        "layer": "L3",
        "worker_id": "runtime-execution",
        "lease_id": "LEASE-%s" % suffix,
        "status": "PASS" if passed else "FAIL",
        "integrity_passed": True,
        "actual_result": {"business_code": "OK" if passed else "BAD"},
        "tool_call_refs": ["api-call://%s" % suffix],
        "evidence_refs": [evidence_id],
        "assertion_ref": "oracle://%s" % suffix,
        "assertion_passed": passed,
        "reason": "ORACLE_PASS" if passed else "ORACLE_ASSERTION_FAILED",
    }
    formal_record = json.loads(json.dumps(record))
    if formal_overrides:
        formal_record.update(formal_overrides)
    artifact_digest = _write(conclusion_path, {"record": record})
    formal_digest = _write(formal_path, {"record": formal_record})
    evidence = Evidence(
        evidence_id=evidence_id,
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://formal-execution",
        content_ref="file://" + str(formal_path),
        subject_refs=[task_id, attempt_id, TC_ID],
        content_hash=formal_digest,
    )
    artifact = Artifact(
        artifact_id=artifact_id,
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=task_id,
        content_ref="file://" + str(conclusion_path),
        evidence_refs=[evidence_id],
        content_hash=artifact_digest,
    )
    dimensions = {
        "test_result": "PASS" if passed else "FAIL",
        "execution_status": record["status"],
        "integrity_passed": True,
        "assertion_passed": passed,
        "conclusive": True,
        "attempt_id": attempt_id,
    }
    if purpose is not None:
        dimensions["purpose"] = purpose
        dimensions["source_product_gap_id"] = "GAP-PRODUCT-FORMAL"
        dimensions["reproduced"] = not passed
    evaluation = Evaluation(
        evaluation_id=evaluation_id,
        mission_id=MISSION,
        node="EXECUTION",
        artifact_refs=[artifact_id],
        result=EvaluationResult.PASS,
        evaluator_ref="runtime-execution-gate",
        dimensions=dimensions,
        evidence_refs=[evidence_id],
    )
    append_entity(truth, evidence, release_id=RELEASE)
    append_entity(truth, artifact, release_id=RELEASE)
    append_entity(truth, evaluation, release_id=RELEASE)
    append_entity(
        truth,
        Task(
            task_id=task_id,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="DEFECT_REPRODUCTION" if purpose == "DEFECT_REPRODUCTION" else "EXECUTE",
            objective="formal execution %s" % suffix,
            state=TaskStatus.PASS,
            output_artifact_refs=[artifact_id],
            evaluation_id=evaluation_id,
        ),
        release_id=RELEASE,
    )
    return formal_path


def _build(tmp_path: Path, truth: TruthRuntime):
    return R1FormalMissionEvidenceSnapshotBuilder(
        evidence_root=str(tmp_path / "mission-evidence")
    ).build(
        truth,
        mission_id=MISSION,
        producer_task_id="TASK-MISSION-EVALUATION",
    ).snapshot


def test_latest_ordinary_formal_fail_revokes_previous_verified_case(tmp_path: Path):
    truth = _truth(tmp_path)
    _execution(tmp_path, truth, suffix="01-PASS", passed=True)
    _execution(tmp_path, truth, suffix="02-FAIL", passed=False)

    snapshot = _build(tmp_path, truth)

    assert snapshot.critical_requirements_verified == 0
    assert snapshot.critical_obligations_verified == 0
    assert snapshot.critical_branches_verified == 0
    assert snapshot.critical_executions_conclusive == 0
    assert snapshot.inconclusive_execution_refs == (TC_ID,)


def test_defect_reproduction_alone_never_verifies_mission_case(tmp_path: Path):
    truth = _truth(tmp_path)
    _execution(
        tmp_path,
        truth,
        suffix="01-REPRO-NONFAIL",
        passed=True,
        purpose="DEFECT_REPRODUCTION",
    )

    snapshot = _build(tmp_path, truth)

    assert snapshot.critical_requirements_verified == 0
    assert snapshot.critical_obligations_verified == 0
    assert snapshot.critical_branches_verified == 0
    assert snapshot.critical_executions_conclusive == 0


def test_defect_reproduction_does_not_override_latest_ordinary_pass(tmp_path: Path):
    truth = _truth(tmp_path)
    _execution(tmp_path, truth, suffix="01-PASS", passed=True)
    _execution(
        tmp_path,
        truth,
        suffix="02-REPRO-FAIL",
        passed=False,
        purpose="DEFECT_REPRODUCTION",
    )

    snapshot = _build(tmp_path, truth)

    assert snapshot.critical_requirements_verified == 1
    assert snapshot.critical_obligations_verified == 2
    assert snapshot.critical_branches_verified == 1
    assert snapshot.critical_executions_conclusive == 1
    assert not snapshot.inconclusive_execution_refs


def test_formal_execution_hash_tamper_cannot_contribute_to_mission_coverage(tmp_path: Path):
    truth = _truth(tmp_path)
    formal_path = _execution(tmp_path, truth, suffix="01-PASS", passed=True)
    payload = json.loads(formal_path.read_text(encoding="utf-8"))
    payload["record"]["actual_result"] = {"business_code": "TAMPERED"}
    formal_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(
        MissionEvidenceBuildError,
        match="MISSION_FORMAL_RUNTIME_EXECUTION_HASH_MISMATCH",
    ):
        _build(tmp_path, truth)


def test_matching_subject_labels_cannot_splice_different_execution_record(tmp_path: Path):
    truth = _truth(tmp_path)
    _execution(
        tmp_path,
        truth,
        suffix="01-PASS",
        passed=True,
        formal_overrides={
            "status": "FAIL",
            "actual_result": {"business_code": "SPLICED"},
            "assertion_ref": "oracle://different-execution",
            "assertion_passed": False,
        },
    )

    with pytest.raises(
        MissionEvidenceBuildError,
        match="MISSION_FORMAL_RUNTIME_EXECUTION_RECORD_MISMATCH:.*status.*actual_result.*assertion_ref.*assertion_passed",
    ):
        _build(tmp_path, truth)
