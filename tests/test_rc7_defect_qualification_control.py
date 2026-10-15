from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rc6_runtime.automation import ProcessStepResult, ScriptArtifact, ScriptValidation
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.execution import ExecutionRecord
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.defect_qualification_control import (
    DefectQualificationControl,
    DefectQualificationControlError,
)
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
        "expected": "business_code equals OK",
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
    reproduction_tasks = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "EXECUTION" and row.get("task_type") == "DEFECT_REPRODUCTION"
    ]
    defect_tasks = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "DEFECT" and row.get("task_type") == "QUALIFY_DEFECT"
    ]
    assert len(reproduction_tasks) == 1
    assert len(defect_tasks) == 1
    assert reproduction_tasks[0]["state"] == "READY"
    assert reproduction_tasks[0]["dependency_task_ids"] == [ORIGINAL_TASK]
    assert reproduction_tasks[0]["input_artifact_refs"] == [artifact.artifact_id]
    assert defect_tasks[0]["state"] == "REGISTERED"
    assert defect_tasks[0]["dependency_task_ids"] == [reproduction_tasks[0]["task_id"]]
    return (
        truth,
        control,
        str(defect_tasks[0]["task_id"]),
        str(reproduction_tasks[0]["task_id"]),
    )


def _durable_reproduction(
    control: ClosedLoopControlPlane,
    tmp_path: Path,
    reproduction_task_id: str,
    *,
    reproduced: bool,
):
    suffix = "YES" if reproduced else "NO"
    attempt = "ATT-REPRO-%s" % suffix
    evidence_id = "EVD-REPRO-%s" % suffix
    artifact_id = "ART-REPRO-%s" % suffix
    evaluation_id = "EVAL-REPRO-%s" % suffix

    leased = control.lease_next(
        worker_ref="repro-worker",
        capabilities=("test_execution",),
    )
    assert leased is not None and leased.task_id == reproduction_task_id
    control.start(reproduction_task_id, worker_ref="repro-worker")

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
        evidence_refs=(evidence_id,),
        assertion_ref="assertion://business",
        assertion_passed=False if reproduced else True,
        reason="ORACLE_ASSERTION_FAILED" if reproduced else None,
    )
    record_path = tmp_path / ("reproduction-%s.json" % suffix.lower())
    digest = _write_json(
        record_path,
        {
            "record": {
                "attempt_id": record.attempt_id,
                "tc_id": record.tc_id,
                "case_version": record.case_version,
                "target_id": record.target_id,
                "layer": record.layer,
                "worker_id": record.worker_id,
                "lease_id": record.lease_id,
                "status": record.status,
                "integrity_passed": record.integrity_passed,
                "actual_result": record.actual_result,
                "tool_call_refs": list(record.tool_call_refs),
                "evidence_refs": list(record.evidence_refs),
                "assertion_ref": record.assertion_ref,
                "assertion_passed": record.assertion_passed,
                "reason": record.reason,
            }
        },
    )
    evidence = Evidence(
        evidence_id=evidence_id,
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://formal-execution",
        content_ref="file://" + str(record_path),
        subject_refs=[reproduction_task_id, attempt, "TC-DEFECT-QUAL"],
        content_hash="sha256:" + digest,
    )
    artifact = Artifact(
        artifact_id=artifact_id,
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=reproduction_task_id,
        content_ref="file://" + str(record_path),
        evidence_refs=[evidence_id],
        content_hash="sha256:" + digest,
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=reproduction_task_id,
            worker_ref="repro-worker",
            artifacts=(artifact,),
            evidence=(evidence,),
        )
    )
    evaluation = Evaluation(
        evaluation_id=evaluation_id,
        mission_id=MISSION,
        node="EXECUTION",
        artifact_refs=[artifact_id],
        result=EvaluationResult.PASS,
        evaluator_ref="rc7-defect-reproduction-runtime-gate",
        dimensions={
            "purpose": "DEFECT_REPRODUCTION",
            "source_product_gap_id": PRODUCT_GAP,
            "attempt_id": attempt,
            "execution_status": record.status,
            "integrity_passed": True,
            "assertion_passed": record.assertion_passed,
            "reproduced": reproduced,
            "conclusive": True,
        },
        evidence_refs=[evidence_id],
    )
    accepted = control.accept_evaluation(
        reproduction_task_id,
        evaluation=evaluation,
    )
    assert accepted.state == TaskStatus.PASS
    return DefectReproductionResult(
        execution_record=record,
        record_artifact_id=artifact_id,
        evidence_ids=(evidence_id,),
        evaluation_id=evaluation_id,
        task_state="PASS",
        reproduced=reproduced,
        conclusive=True,
        runtime_worker_id="repro-worker",
        runtime_lease_id="repro-lease",
    )


def _forged_reproduction():
    record = ExecutionRecord(
        attempt_id="ATT-FORGED",
        tc_id="TC-DEFECT-QUAL",
        case_version=1,
        target_id="TARGET-1",
        layer="L2",
        worker_id="forged-worker",
        lease_id="forged-lease",
        status="FAIL",
        integrity_passed=True,
        actual_result={"business_code": "BAD"},
        tool_call_refs=("database-call://forged",),
        evidence_refs=("EVD-FORGED",),
        assertion_ref="assertion://business",
        assertion_passed=False,
        reason="ORACLE_ASSERTION_FAILED",
    )
    return DefectReproductionResult(
        execution_record=record,
        record_artifact_id="ART-FORGED",
        evidence_ids=("EVD-FORGED",),
        evaluation_id="EVAL-FORGED",
        task_state="PASS",
        reproduced=True,
        conclusive=True,
        runtime_worker_id="forged-worker",
        runtime_lease_id="forged-lease",
    )


def test_reproduced_product_failure_enters_evidence_ready_without_resolving_product_gap(tmp_path: Path):
    truth, control, defect_task_id, reproduction_task_id = _control(tmp_path)
    reproduction = _durable_reproduction(
        control,
        tmp_path,
        reproduction_task_id,
        reproduced=True,
    )
    assert control.scheduler.task(defect_task_id).state == TaskStatus.READY
    result = DefectQualificationControl(evidence_root=str(tmp_path / "defect-evidence")).qualify(
        control,
        defect_task_id,
        product_gap_id=PRODUCT_GAP,
        bundle=_bundle(tmp_path),
        reproduction=reproduction,
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
    truth, control, defect_task_id, reproduction_task_id = _control(tmp_path)
    reproduction = _durable_reproduction(
        control,
        tmp_path,
        reproduction_task_id,
        reproduced=False,
    )
    assert control.scheduler.task(defect_task_id).state == TaskStatus.READY
    result = DefectQualificationControl(evidence_root=str(tmp_path / "defect-evidence")).qualify(
        control,
        defect_task_id,
        product_gap_id=PRODUCT_GAP,
        bundle=_bundle(tmp_path),
        reproduction=reproduction,
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


def test_forged_in_memory_reproduction_cannot_qualify_product_defect(tmp_path: Path):
    _, control, defect_task_id, reproduction_task_id = _control(tmp_path)
    _durable_reproduction(
        control,
        tmp_path,
        reproduction_task_id,
        reproduced=True,
    )
    assert control.scheduler.task(defect_task_id).state == TaskStatus.READY
    with pytest.raises(
        DefectQualificationControlError,
        match="REPRODUCTION_EVALUATION_NOT_DURABLE",
    ):
        DefectQualificationControl(evidence_root=str(tmp_path / "defect-evidence")).qualify(
            control,
            defect_task_id,
            product_gap_id=PRODUCT_GAP,
            bundle=_bundle(tmp_path),
            reproduction=_forged_reproduction(),
        )
