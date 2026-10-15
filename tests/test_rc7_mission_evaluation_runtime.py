from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.mission_evaluation_runtime import MissionEvaluationRuntime
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence, Mission, Task, TaskStatus
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-EVAL-RUNTIME"
RELEASE = "RC7-MISSION-EVAL-RUNTIME"
DESIGN_TASK = "TASK-DESIGN-EVAL-RUNTIME"
DESIGN_ARTIFACT = "ART-DESIGN-EVAL-RUNTIME"
EXEC_TASK = "TASK-EXEC-EVAL-RUNTIME"
EXEC_ARTIFACT = "ART-EXEC-EVAL-RUNTIME"
TC_ID = "TC-MISSION-EVAL-RUNTIME"


def _write(path: Path, payload):
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
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
            goal="converge only from R1-derived mission evidence",
        ),
        release_id=RELEASE,
    )

    design_path = tmp_path / "design.json"
    design_payload = {
        "artifact": {"artifact_id": DESIGN_ARTIFACT, "artifact_type": "TEST_DESIGN_MODEL"},
        "semantic_payload": {
            "obligations": [
                {
                    "obligation_id": "OBL-RULE-EVAL-RUNTIME",
                    "kind": "BUSINESS_RULE",
                    "layer": "L3",
                    "risk": "HIGH",
                    "required": True,
                },
                {
                    "obligation_id": "OBL-CODE-EVAL-RUNTIME",
                    "kind": "CODE_IMPACT",
                    "layer": "L3",
                    "risk": "CRITICAL",
                    "required": True,
                },
            ],
            "cases": [
                {
                    "tc_id": TC_ID,
                    "risk": "HIGH",
                    "coverage_links": [
                        {"subject_id": "OBL-RULE-EVAL-RUNTIME", "evidence_ref": "evidence://rule"},
                        {"subject_id": "OBL-CODE-EVAL-RUNTIME", "evidence_ref": "evidence://code"},
                    ],
                }
            ],
        },
    }
    design_hash = _write(design_path, design_payload)
    design_evidence = Evidence(
        evidence_id="EVD-DESIGN-EVAL-RUNTIME",
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
        evaluation_id="EVAL-DESIGN-EVAL-RUNTIME",
        mission_id=MISSION,
        node="TEST_DESIGN",
        artifact_refs=[DESIGN_ARTIFACT],
        result=EvaluationResult.PASS,
        evaluator_ref="independent-test-design-gate",
        dimensions={"gate_status": "SUFFICIENT"},
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
            objective="accepted design truth",
            state=TaskStatus.PASS,
            output_artifact_refs=[DESIGN_ARTIFACT],
            evaluation_id=design_eval.evaluation_id,
        ),
        release_id=RELEASE,
    )

    execution_path = tmp_path / "execution.json"
    execution_record = {
        "attempt_id": "ATT-MISSION-EVAL-RUNTIME",
        "tc_id": TC_ID,
        "case_version": 1,
        "target_id": "TARGET-MISSION-EVAL-RUNTIME",
        "layer": "L3",
        "worker_id": "runtime-execution",
        "lease_id": "LEASE-MISSION-EVAL-RUNTIME",
        "status": "PASS",
        "integrity_passed": True,
        "actual_result": {"business_code": "OK"},
        "tool_call_refs": ["api-call://mission-eval-runtime"],
        "evidence_refs": ["EVD-EXEC-EVAL-RUNTIME"],
        "assertion_ref": "oracle-assertion://mission-eval-runtime",
        "assertion_passed": True,
        "reason": "ORACLE_PASS",
    }
    execution_hash = _write(execution_path, {"record": execution_record})
    execution_evidence = Evidence(
        evidence_id="EVD-EXEC-EVAL-RUNTIME",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://formal-execution",
        content_ref="file://" + str(execution_path),
        subject_refs=[EXEC_TASK, execution_record["attempt_id"], TC_ID],
        content_hash=execution_hash,
    )
    append_entity(truth, execution_evidence, release_id=RELEASE)
    append_entity(
        truth,
        Artifact(
            artifact_id=EXEC_ARTIFACT,
            mission_id=MISSION,
            artifact_type="EXECUTION_CONCLUSION",
            producer_task_id=EXEC_TASK,
            content_ref="file://" + str(execution_path),
            evidence_refs=[execution_evidence.evidence_id],
            content_hash=execution_hash,
        ),
        release_id=RELEASE,
    )
    execution_eval = Evaluation(
        evaluation_id="EVAL-EXEC-EVAL-RUNTIME",
        mission_id=MISSION,
        node="EXECUTION",
        artifact_refs=[EXEC_ARTIFACT],
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
            "attempt_id": execution_record["attempt_id"],
        },
        evidence_refs=[execution_evidence.evidence_id],
    )
    append_entity(truth, execution_eval, release_id=RELEASE)
    append_entity(
        truth,
        Task(
            task_id=EXEC_TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="trusted conclusive execution",
            state=TaskStatus.PASS,
            output_artifact_refs=[EXEC_ARTIFACT],
            evaluation_id=execution_eval.evaluation_id,
        ),
        release_id=RELEASE,
    )
    return truth


def test_mission_evaluation_runtime_builds_snapshot_and_converges_without_caller_counters(tmp_path: Path):
    truth = _truth(tmp_path)
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)

    result = MissionEvaluationRuntime(
        evidence_root=str(tmp_path / "evidence")
    ).run(control)

    assert result.evaluation_result == "PASS"
    assert result.sufficiency_state == "SUFFICIENT"
    assert result.release_recommendation == "RECOMMENDED"
    assert result.task_state == "PASS"
    assert result.mission_state == "CONVERGED"
    assert result.gap_ids == ()

    task = control.scheduler.task(result.task_id)
    assert task.node == "MISSION_EVALUATION"
    assert task.state == TaskStatus.PASS
    assert task.output_artifact_refs == [result.snapshot_artifact_id]
    snapshot_rows = truth.query("rc7_artifact", artifact_id=result.snapshot_artifact_id)
    assert len(snapshot_rows) == 1
    assert snapshot_rows[0]["artifact_type_name"] == "MISSION_EVIDENCE_SNAPSHOT"
    evidence_rows = truth.query("rc7_evidence", evidence_id=result.snapshot_evidence_id)
    assert len(evidence_rows) == 1
    assert evidence_rows[0]["kind"] == "MISSION_EVIDENCE_SNAPSHOT"

    mission = truth.query("rc7_mission", mission_id=MISSION)[0]
    assert mission["state"] == "CONVERGED"
    assert mission["sufficiency_state"] == "SUFFICIENT"
    assert mission["latest_evaluation_id"] == result.evaluation_id

    evaluations = truth.query("rc7_evaluation", evaluation_id=result.evaluation_id)
    assert len(evaluations) == 1
    assert evaluations[0]["artifact_refs"] == [result.snapshot_artifact_id]
