from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rc6_runtime.automation import ProcessStepResult, ScriptArtifact, ScriptValidation
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.execution import ExecutionRecord
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.defect_qualification_control import DefectQualificationControl
from rc7_runtime.defect_reproduction import DefectReproductionResult
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Gap,
    GapSeverity,
    Mission,
    Task,
    TaskStatus,
)
from rc7_runtime.runtime_execution import VerifiedScriptExecutionBundle
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-DEFECT-QUAL"
ORIGINAL_TASK = "TASK-EXEC-DEFECT-QUAL"
PRODUCT_GAP = "GAP-PRODUCT-DEFECT-QUAL"


def _case():
    return {
        "tc_id": "TC-DEFECT-QUAL",
        "case_version": 1,
        "status": "FROZEN",
        "release_id": "RC7-DEFECT-QUAL",
        "requirement_id": "REQ-DEFECT-QUAL",
        "sst_id": "SST-DEFECT-QUAL",
        "layer": "L2",
        "preconditions": [],
        "steps": [{"order": 1, "action": "execute defect-qualifying behavior"}],
        "expected": {"business_code": "OK"},
        "oracle": {
            "checks": [
                {
                    "id": "CHK-1",
                    "type": "BUSINESS_RULE",
                    "actual_path": "business_code",
                    "operator": "EQ",
                    "expected": "OK",
                }
            ]
        },
        "evidence_requirements": ["database-call", "oracle"],
        "target_requirements": ["REQ-DEFECT-QUAL"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://defect-qual"],
        "cleanup_policy": {"mode": "NONE"},
        "runner_type": "PYTEST",
    }


def _bundle(tmp_path: Path):
    case = _case()
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-DEFECT-QUAL",),
        test_data_refs=(),
        oracle_refs=("oracle://defect-qual",),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    script = ScriptArtifact(
        script_id="SCRIPT-DEFECT-QUAL",
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(tmp_path / "unused.py"),
        test_symbol="test_unused",
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=("evidence://builder",),
        revision=1,
    )
    validation = ScriptValidation(
        validation_id="VAL-DEFECT-QUAL",
        script_id=script.script_id,
        runner_type="PYTEST",
        test_symbol=script.test_symbol,
        steps=(
            ProcessStepResult(
                name="fixture",
                command=("python",),
                exit_code=0,
                stdout_ref="stdout://fixture",
                stderr_ref="stderr://fixture",
                duration_ms=1,
                passed=True,
            ),
        ),
        evidence_refs=("evidence://validation",),
        status="SCRIPT_READY",
    )
    return VerifiedScriptExecutionBundle(
        upstream_mission_id="MISSION-SCRIPT",
        upstream_task_id="TASK-SCRIPT",
        upstream_evaluation_id="EVAL-SCRIPT",
        upstream_result_ref="file://script-result.json",
        spec_ref="file://spec.json",
        frozen_case=case,
        spec=spec,
        script=script,
        validation=validation,
        source_sha256="fixture",
    )


def _write_json(path: Path, payload):
    encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7-DEFECT-QUAL",
            goal="qualify product defect from durable evidence",
        ),
    )
    control.register_task(
        Task(
            task_id=ORIGINAL_TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="original trusted product fail",
            required_capabilities=["test_execution"],
        )
    )
    leased = control.lease_next(worker_ref="execution-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == ORIGINAL_TASK
    control.start(ORIGINAL_TASK, worker_ref="execution-worker")

    record_payload = {
        "record": {
            "attempt_id": "ATT-ORIGINAL",
            "tc_id": "TC-DEFECT-QUAL",
            "case_version": 1,
            "target_id": "TARGET-1",
            "layer": "L2",
            "worker_id": "execution-worker",
            "lease_id": "lease-original",
            "status": "FAIL",
            "integrity_passed": True,
            "actual_result": {"business_code": "BAD"},
            "tool_call_refs": ["database-call://original"],
            "evidence_refs": ["EVD-RUNTIME-RAW"],
            "assertion_ref": "assertion://business",
            "assertion_passed": False,
            "reason": "ORACLE_ASSERTION_FAILED",
        }
    }
    record_path = tmp_path / "original-record.json"
    record_digest = _write_json(record_path, record_payload)
    record_evidence = Evidence(
        evidence_id="EVD-ORIGINAL-RECORD",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://execution",
        content_ref="file://" + str(record_path),
        subject_refs=[ORIGINAL_TASK, "ATT-ORIGINAL", "TC-DEFECT-QUAL"],
        content_hash="sha256:" + record_digest,
    )

    context = {
        "preparation_verified": True,
        "real_action_executed": True,
        "assertion_failed": True,
        "case_oracle_verified": True,
        "executable_spec_verified": True,
        "script_validated": True,
        "data_verified": True,
        "auth_verified": True,
        "route_verified": True,
        "tool_verified": True,
        "environment_verified": True,
        "dependency_verified": True,
    }
    diagnosis_path = tmp_path / "diagnosis.json"
    diagnosis_digest = _write_json(
        diagnosis_path,
        {"context": context, "diagnosis": {"failure_class": "PRODUCT"}},
    )
    diagnosis_evidence = Evidence(
        evidence_id="EVD-PRODUCT-DIAGNOSIS",
        mission_id=MISSION,
        kind="RUNTIME_FAILURE_DIAGNOSIS",
        source_ref="runtime://execution-diagnosis",
        content_ref="file://" + str(diagnosis_path),
        subject_refs=[ORIGINAL_TASK, "ATT-ORIGINAL", "TC-DEFECT-QUAL"],
        content_hash="sha256:" + diagnosis_digest,
    )
    artifact = Artifact(
        artifact_id="ART-ORIGINAL-EXECUTION",
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=ORIGINAL_TASK,
        content_ref="file://" + str(record_path),
        evidence_refs=[record_evidence.evidence_id, diagnosis_evidence.evidence_id],
        content_hash="sha256:" + record_digest,
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=ORIGINAL_TASK,
            worker_ref="execution-worker",
            artifacts=(artifact,),
            evidence=(record_evidence, diagnosis_evidence),
        )
    )
    gap = Gap(
        gap_id=PRODUCT_GAP,
        mission_id=MISSION,
        source_node="EXECUTION",
        category="PRODUCT_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="DEFECT",
        description="trusted business mismatch",
        subject_refs=["ATT-ORIGINAL", "TC-DEFECT-QUAL"],
        evidence_refs=[record_evidence.evidence_id, diagnosis_evidence.evidence_id],
        acceptance_criteria=["complete evidence-backed defect lifecycle"],
    )
    control.accept_evaluation(
        ORIGINAL_TASK,
        evaluation=Evaluation(
            evaluation_id="EVAL-ORIGINAL-PRODUCT",
            mission_id=MISSION,
            node="EXECUTION",
            artifact_refs=[artifact.artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="runtime-execution-gate",
            dimensions={"test_result": "FAIL", "failure_class": "PRODUCT"},
            gap_refs=[gap.gap_id],
            evidence_refs=[record_evidence.evidence_id, diagnosis_evidence.evidence_id],
        ),
        gaps=(gap,),
    )
    defect_tasks = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "DEFECT" and row.get("task_type") == "QUALIFY_DEFECT"
    ]
    assert len(defect_tasks) == 1
    assert defect_tasks[0]["state"] == "READY"
    return truth, control, str(defect_tasks[0]["task_id"])


def _reproduction(truth, *, reproduced: bool):
    attempt = "ATT-REPRO-YES" if reproduced else "ATT-REPRO-NO"
    evidence = Evidence(
        evidence_id="EVD-REPRO-YES" if reproduced else "EVD-REPRO-NO",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://defect-reproduction",
        content_ref="evidence://reproduction/%s" % attempt,
        subject_refs=[attempt, "TC-DEFECT-QUAL"],
    )
    append_entity(truth, evidence, release_id="RC7-DEFECT-QUAL")
    artifact = Artifact(
        artifact_id="ART-REPRO-YES" if reproduced else "ART-REPRO-NO",
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id="TASK-REPRO-FIXTURE",
        content_ref="artifact://reproduction/%s" % attempt,
        evidence_refs=[evidence.evidence_id],
    )
    append_entity(truth, artifact, release_id="RC7-DEFECT-QUAL")
    record = ExecutionRecord(
        attempt_id=attempt,
        tc_id="TC-DEFECT-QUAL",
        case_version=1,
        target_id="TARGET-1",
        layer="L2",
        worker_id="repro-worker",
        lease_id="repro-lease",
        status="FAIL" if reproduced else "PASS",
        integrity_passed=True,
        actual_result={"business_code": "BAD" if reproduced else "OK"},
        tool_call_refs=("database-call://reproduction",),
        evidence_refs=(evidence.evidence_id,),
        assertion_ref="assertion://business",
        assertion_passed=False if reproduced else True,
        reason="ORACLE_ASSERTION_FAILED" if reproduced else None,
    )
    return DefectReproductionResult(
        execution_record=record,
        record_artifact_id=artifact.artifact_id,
        evidence_ids=(evidence.evidence_id,),
        evaluation_id="EVAL-REPRO-FIXTURE",
        task_state="PASS",
        reproduced=reproduced,
        conclusive=True,
        runtime_worker_id="repro-worker",
        runtime_lease_id="repro-lease",
    )


def test_reproduced_product_failure_enters_evidence_ready_without_resolving_product_gap(tmp_path: Path):
    truth, control, defect_task_id = _control(tmp_path)
    result = DefectQualificationControl(evidence_root=str(tmp_path / "defect-evidence")).qualify(
        control,
        defect_task_id,
        product_gap_id=PRODUCT_GAP,
        bundle=_bundle(tmp_path),
        reproduction=_reproduction(truth, reproduced=True),
    )

    assert result.qualified is True
    assert result.defect_state == "EVIDENCE_READY"
    assert result.defect_task_state == "OUTPUT_PRODUCED"
    assert result.qualification_gap_ids == ()
    assert result.qualification_repair_task_ids == ()
    defect = truth.query("rc7_defect", defect_id=result.defect_id)[0]
    assert defect["state"] == "EVIDENCE_READY"
    assert defect["reproduction_attempts"] == 1
    assert defect["reproduction_passes"] == 1
    product_gap = truth.query("rc7_gap", gap_id=PRODUCT_GAP)[0]
    assert product_gap["state"] == "REPAIRING"
    assert product_gap["resolution_evaluation_id"] is None


def test_non_reproduction_stays_qualifying_and_schedules_runnable_defect_repair(tmp_path: Path):
    truth, control, defect_task_id = _control(tmp_path)
    result = DefectQualificationControl(evidence_root=str(tmp_path / "defect-evidence")).qualify(
        control,
        defect_task_id,
        product_gap_id=PRODUCT_GAP,
        bundle=_bundle(tmp_path),
        reproduction=_reproduction(truth, reproduced=False),
    )

    assert result.qualified is False
    assert result.defect_state == "QUALIFYING"
    assert len(result.qualification_gap_ids) == 1
    assert len(result.qualification_repair_task_ids) == 1
    gap = truth.query("rc7_gap", gap_id=result.qualification_gap_ids[0])[0]
    assert gap["category"] == "DEFECT_QUALIFICATION_INCOMPLETE"
    assert gap["state"] == "PLANNED"
    repair = control.scheduler.task(result.qualification_repair_task_ids[0])
    assert repair.node == "DEFECT"
    assert repair.state == TaskStatus.READY
    defect = truth.query("rc7_defect", defect_id=result.defect_id)[0]
    assert defect["state"] == "QUALIFYING"
    assert defect["reproduction_attempts"] == 1
    assert defect["reproduction_passes"] == 0
