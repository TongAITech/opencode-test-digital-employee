from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.mission_evidence_builder import R1MissionEvidenceSnapshotBuilder
from rc7_runtime.mission_sufficiency import MissionSufficiencyClosedLoop
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Mission,
    Task,
    TaskStatus,
)
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-R1-SNAPSHOT"
RELEASE = "RC7-R1-SNAPSHOT"
DESIGN_TASK = "TASK-DESIGN-R1-SNAPSHOT"
DESIGN_ARTIFACT = "ART-DESIGN-R1-SNAPSHOT"
MISSION_TASK = "TASK-MISSION-EVAL-R1-SNAPSHOT"


def _json_file(path: Path, payload):
    encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _base_truth(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    append_entity(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="derive mission sufficiency only from durable R1 truth",
        ),
        release_id=RELEASE,
    )

    design_path = tmp_path / "design.json"
    design_payload = {
        "artifact": {"artifact_id": DESIGN_ARTIFACT, "artifact_type": "TEST_DESIGN_MODEL"},
        "semantic_payload": {
            "obligations": [
                {
                    "obligation_id": "OBL-BUSINESS-RULE",
                    "kind": "BUSINESS_RULE",
                    "layer": "L3",
                    "risk": "HIGH",
                    "required": True,
                    "evidence_refs": ["evidence://requirement"],
                },
                {
                    "obligation_id": "OBL-CODE-IMPACT",
                    "kind": "CODE_IMPACT",
                    "layer": "L3",
                    "risk": "CRITICAL",
                    "required": True,
                    "evidence_refs": ["evidence://code"],
                },
                {
                    "obligation_id": "OBL-LOW-OPTIONAL",
                    "kind": "REGRESSION",
                    "layer": "L3",
                    "risk": "LOW",
                    "required": True,
                    "evidence_refs": ["evidence://low"],
                },
            ],
            "cases": [
                {
                    "tc_id": "TC-CRITICAL-R1",
                    "risk": "HIGH",
                    "coverage_links": [
                        {"subject_id": "OBL-BUSINESS-RULE", "evidence_ref": "evidence://coverage-req"},
                        {"subject_id": "OBL-CODE-IMPACT", "evidence_ref": "evidence://coverage-code"},
                    ],
                },
                {
                    "tc_id": "TC-LOW-R1",
                    "risk": "LOW",
                    "coverage_links": [
                        {"subject_id": "OBL-LOW-OPTIONAL", "evidence_ref": "evidence://coverage-low"}
                    ],
                },
            ],
        },
    }
    design_hash = _json_file(design_path, design_payload)
    design_evidence = Evidence(
        evidence_id="EVD-DESIGN-R1-SNAPSHOT",
        mission_id=MISSION,
        kind="TEST_DESIGN_PROOF",
        source_ref="runtime://test-design",
        content_ref="file://" + str(design_path),
        subject_refs=[DESIGN_TASK, DESIGN_ARTIFACT],
        content_hash=design_hash,
    )
    append_entity(truth, design_evidence, release_id=RELEASE)
    append_entity(
        truth,
        Artifact(
            artifact_id=DESIGN_ARTIFACT,
            mission_id=MISSION,
            artifact_type="TEST_DESIGN_MODEL",
            producer_task_id=DESIGN_TASK,
            content_ref="file://" + str(design_path),
            evidence_refs=[design_evidence.evidence_id],
            content_hash=design_hash,
        ),
        release_id=RELEASE,
    )
    design_eval = Evaluation(
        evaluation_id="EVAL-DESIGN-R1-SNAPSHOT",
        mission_id=MISSION,
        node="TEST_DESIGN",
        artifact_refs=[DESIGN_ARTIFACT],
        result=EvaluationResult.PASS,
        evaluator_ref="independent-test-design-gate",
        dimensions={
            "gate_status": "SUFFICIENT",
            "metrics": {
                "required_subject_count": 3,
                "covered_subject_count": 3,
                "semantic_coverage": 1.0,
            },
        },
        evidence_refs=[design_evidence.evidence_id],
    )
    append_entity(truth, design_eval, release_id=RELEASE)
    append_entity(
        truth,
        Task(
            task_id=DESIGN_TASK,
            mission_id=MISSION,
            node="TEST_DESIGN",
            task_type="ANALYZE",
            objective="produce accepted test obligations and cases",
            state=TaskStatus.PASS,
            output_artifact_refs=[DESIGN_ARTIFACT],
            evaluation_id=design_eval.evaluation_id,
        ),
        release_id=RELEASE,
    )
    append_entity(
        truth,
        Task(
            task_id=MISSION_TASK,
            mission_id=MISSION,
            node="MISSION_EVALUATION",
            task_type="EVALUATE",
            objective="derive R1 mission evidence snapshot",
            state=TaskStatus.RUNNING,
            lease_owner="rc7-runtime-mission-evidence-builder",
        ),
        release_id=RELEASE,
    )
    return truth


def _append_execution(tmp_path: Path, truth: TruthRuntime):
    artifact_id = "ART-EXEC-R1-SNAPSHOT"
    evidence_id = "EVD-EXEC-R1-SNAPSHOT"
    path = tmp_path / "execution.json"
    record = {
        "attempt_id": "ATT-R1-SNAPSHOT",
        "tc_id": "TC-CRITICAL-R1",
        "case_version": 1,
        "target_id": "TARGET-R1-SNAPSHOT",
        "layer": "L3",
        "worker_id": "runtime-execution",
        "lease_id": "LEASE-R1-SNAPSHOT",
        "status": "PASS",
        "integrity_passed": True,
        "actual_result": {"business_code": "OK"},
        "tool_call_refs": ["api-call://r1-snapshot"],
        "evidence_refs": [evidence_id],
        "assertion_ref": "oracle-assertion://r1-snapshot",
        "assertion_passed": True,
        "reason": "ORACLE_PASS",
    }
    digest = _json_file(path, {"record": record})
    evidence = Evidence(
        evidence_id=evidence_id,
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://formal-execution",
        content_ref="file://" + str(path),
        subject_refs=[record["attempt_id"], record["tc_id"]],
        content_hash=digest,
    )
    append_entity(truth, evidence, release_id=RELEASE)
    append_entity(
        truth,
        Artifact(
            artifact_id=artifact_id,
            mission_id=MISSION,
            artifact_type="EXECUTION_CONCLUSION",
            producer_task_id="TASK-EXEC-R1-SNAPSHOT",
            content_ref="file://" + str(path),
            evidence_refs=[evidence_id],
            content_hash=digest,
        ),
        release_id=RELEASE,
    )
    append_entity(
        truth,
        Evaluation(
            evaluation_id="EVAL-EXEC-R1-SNAPSHOT",
            mission_id=MISSION,
            node="EXECUTION",
            artifact_refs=[artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="runtime-execution-gate",
            dimensions={
                "test_result": "PASS",
                "execution_status": "PASS",
                "integrity_passed": True,
                "assertion_passed": True,
                "failure_class": None,
                "recovery_action": None,
                "conclusive": True,
                "attempt_id": record["attempt_id"],
            },
            evidence_refs=[evidence_id],
        ),
        release_id=RELEASE,
    )


def test_design_coverage_cannot_self_report_runtime_verification(tmp_path: Path):
    truth = _base_truth(tmp_path)
    built = R1MissionEvidenceSnapshotBuilder(
        evidence_root=str(tmp_path / "evidence")
    ).build(
        truth,
        mission_id=MISSION,
        producer_task_id=MISSION_TASK,
    )

    snapshot = built.snapshot
    assert snapshot.critical_requirements_total == 1
    assert snapshot.critical_requirements_verified == 0
    assert snapshot.unverified_requirement_refs == ("OBL-BUSINESS-RULE",)
    assert snapshot.critical_obligations_total == 2
    assert snapshot.critical_obligations_verified == 0
    assert set(snapshot.unverified_obligation_refs) == {"OBL-BUSINESS-RULE", "OBL-CODE-IMPACT"}
    assert snapshot.critical_branches_total == 1
    assert snapshot.critical_branches_verified == 0
    assert snapshot.unverified_branch_refs == ("OBL-CODE-IMPACT",)
    assert snapshot.critical_executions_total == 1
    assert snapshot.critical_executions_conclusive == 0
    assert snapshot.inconclusive_execution_refs == ("TC-CRITICAL-R1",)

    result = MissionSufficiencyClosedLoop().evaluate(snapshot)
    assert result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert result.sufficiency_state == "NOT_SUFFICIENT"
    categories = {gap.category for gap in result.gaps}
    assert "CRITICAL_REQUIREMENT_NOT_VERIFIED" in categories
    assert "CRITICAL_OBLIGATION_NOT_VERIFIED" in categories
    assert "CRITICAL_BRANCH_UNVERIFIED" in categories
    assert "INCONCLUSIVE_RESULT_GAP" in categories


def test_conclusive_execution_drives_verified_numerators_and_snapshot_is_durable(tmp_path: Path):
    truth = _base_truth(tmp_path)
    _append_execution(tmp_path, truth)
    built = R1MissionEvidenceSnapshotBuilder(
        evidence_root=str(tmp_path / "evidence")
    ).build(
        truth,
        mission_id=MISSION,
        producer_task_id=MISSION_TASK,
    )

    snapshot = built.snapshot
    assert snapshot.critical_requirements_total == 1
    assert snapshot.critical_requirements_verified == 1
    assert snapshot.critical_obligations_total == 2
    assert snapshot.critical_obligations_verified == 2
    assert snapshot.critical_branches_total == 1
    assert snapshot.critical_branches_verified == 1
    assert snapshot.critical_executions_total == 1
    assert snapshot.critical_executions_conclusive == 1
    assert not snapshot.unverified_requirement_refs
    assert not snapshot.unverified_obligation_refs
    assert not snapshot.unverified_branch_refs
    assert not snapshot.inconclusive_execution_refs

    evidence_rows = truth.query("rc7_evidence", evidence_id=built.evidence.evidence_id)
    artifact_rows = truth.query("rc7_artifact", artifact_id=built.artifact.artifact_id)
    assert len(evidence_rows) == 1
    assert len(artifact_rows) == 1
    snapshot_path = Path(built.artifact.content_ref[len("file://"):])
    raw = snapshot_path.read_bytes()
    assert built.artifact.content_hash == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert snapshot.snapshot_ref == built.artifact.artifact_id
    assert snapshot.evidence_refs == (built.evidence.evidence_id,)

    result = MissionSufficiencyClosedLoop().evaluate(snapshot)
    assert result.evaluation.result == EvaluationResult.PASS
    assert result.sufficiency_state == "SUFFICIENT"
