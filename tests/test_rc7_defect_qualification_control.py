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
            objective="produce a trustworthy product failure",
            required_capabilities=["test_execution"],
        )
    )
    execution_artifact = Artifact(
        artifact_id="ART-EXEC-DEFECT-QUAL",
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=ORIGINAL_TASK,
        content_ref="file://execution.json",
        evidence_refs=["EVD-EXEC-DEFECT-QUAL"],
        content_hash="sha256:execution",
    )
    execution_evidence = Evidence(
        evidence_id="EVD-EXEC-DEFECT-QUAL",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://formal-execution",
        content_ref="file://execution.json",
        subject_refs=[ORIGINAL_TASK, "ATT-DEFECT-QUAL", "TC-DEFECT-QUAL"],
        content_hash="sha256:execution",
    )
    leased = control.lease_next(worker_ref="runtime-execution-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == ORIGINAL_TASK
    control.start(ORIGINAL_TASK, worker_ref="runtime-execution-worker")
    control.submit_worker_output(
        WorkerOutput(
            task_id=ORIGINAL_TASK,
            worker_ref="runtime-execution-worker",
            artifacts=(execution_artifact,),
            evidence=(execution_evidence,),
        )
    )
    product_gap = Gap(
        gap_id=PRODUCT_GAP,
        mission_id=MISSION,
        source_node="EXECUTION",
        category="PRODUCT_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="DEFECT",
        subject_refs=[ORIGINAL_TASK, "ATT-DEFECT-QUAL", "TC-DEFECT-QUAL"],
        evidence_refs=["EVD-EXEC-DEFECT-QUAL"],
        acceptance_criteria=["trusted product failure is qualified as a defect"],
    )
    execution_evaluation = Evaluation(
        evaluation_id="EVAL-EXEC-DEFECT-QUAL",
        mission_id=MISSION,
        node="EXECUTION",
        evaluator_ref="runtime-execution-gate",
        artifact_refs=[execution_artifact.artifact_id],
        result=EvaluationResult.PASS,
        evidence_refs=[execution_evidence.evidence_id],
        gap_refs=[product_gap.gap_id],
        dimensions={"test_result": "FAIL", "failure_class": "PRODUCT"},
    )
    accepted = control.accept_evaluation(
        ORIGINAL_TASK,
        evaluation=execution_evaluation,
        gaps=(product_gap,),
    )
    assert accepted.state == TaskStatus.PASS
    defect_tasks = [
        row
        for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "DEFECT" and PRODUCT_GAP in row.get("gap_refs", [])
    ]
    assert len(defect_tasks) == 1
    return truth, control, defect_tasks[0]["task_id"]


def _persist_source_execution(truth: TruthRuntime, tmp_path: Path):
    execution_payload = {
        "attempt_id": "ATT-DEFECT-QUAL",
        "tc_id": "TC-DEFECT-QUAL",
        "case_version": 1,
        "target_id": "TARGET-DEFECT-QUAL",
        "layer": "L2",
        "worker_id": "runtime-execution-worker",
        "lease_id": "LEASE-DEFECT-QUAL",
        "status": "FAIL",
        "integrity_passed": True,
        "actual_result": {"business_code": "ERR"},
        "tool_call_refs": ["database-call://source"],
        "evidence_refs": ["EVD-EXEC-DEFECT-QUAL"],
        "assertion_ref": "oracle-assertion://defect-qual",
        "assertion_passed": False,
        "reason": "ORACLE_ASSERTION_FAILED",
    }
    execution_path = tmp_path / "source-execution.json"
    digest = _write_json(execution_path, {"record": execution_payload})
    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-SOURCE-EXEC-DEFECT-QUAL",
            mission_id=MISSION,
            kind="RUNTIME_EXECUTION_RECORD",
            source_ref="runtime://formal-execution",
            content_ref="file://" + str(execution_path),
            subject_refs=[ORIGINAL_TASK, "ATT-DEFECT-QUAL", "TC-DEFECT-QUAL"],
            content_hash="sha256:" + digest,
        ),
        release_id="RC7-DEFECT-QUAL",
        artifact_version=1,
    )
    append_entity(
        truth,
        Artifact(
            artifact_id="ART-SOURCE-EXEC-DEFECT-QUAL",
            mission_id=MISSION,
            artifact_type="EXECUTION_CONCLUSION",
            producer_task_id=ORIGINAL_TASK,
            content_ref="file://" + str(execution_path),
            evidence_refs=["EVD-SOURCE-EXEC-DEFECT-QUAL"],
            content_hash="sha256:" + digest,
        ),
        release_id="RC7-DEFECT-QUAL",
        artifact_version=1,
    )
    return ExecutionRecord(**execution_payload)


def _reproduction(truth: TruthRuntime, *, reproduced: bool):
    result = DefectReproductionResult(
        reproduced=reproduced,
        attempt_ids=("ATT-DEFECT-QUAL", "ATT-DEFECT-QUAL-R1") if reproduced else ("ATT-DEFECT-QUAL",),
        evidence_refs=("EVD-EXEC-DEFECT-QUAL",),
        failure_signature_id="FSIG-DEFECT-QUAL",
        stop_reason="SIGNATURE_REPRODUCED" if reproduced else "REPRODUCTION_NOT_CONFIRMED",
    )
    return result


def _qualify(control: ClosedLoopControlPlane, task_id: str, worker_ref: str = "defect-qualifier"):
    leased = control.lease_next(worker_ref=worker_ref, capabilities=("defect_qualification",))
    assert leased is not None and leased.task_id == task_id
    control.start(task_id, worker_ref=worker_ref)
    return leased


def test_reproduced_product_failure_enters_evidence_ready_without_resolving_product_gap(tmp_path: Path):
    truth, control, defect_task_id = _control(tmp_path)
    _persist_source_execution(truth, tmp_path)
    _qualify(control, defect_task_id)
    result = DefectQualificationControl(evidence_root=str(tmp_path / "defect-evidence")).qualify(
        control,
        defect_task_id,
        product_gap_id=PRODUCT_GAP,
        bundle=_bundle(tmp_path),
        reproduction=_reproduction(truth, reproduced=True),
    )
    assert result.defect.state.value == "EVIDENCE_READY"
    assert result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert control.scheduler.task(defect_task_id).state == TaskStatus.REPAIR_REQUIRED
    assert truth.query("rc7_gap", gap_id=PRODUCT_GAP)[0]["state"] == "PLANNED"


def test_non_reproduction_stays_qualifying_and_schedules_runnable_defect_repair(tmp_path: Path):
    truth, control, defect_task_id = _control(tmp_path)
    _persist_source_execution(truth, tmp_path)
    _qualify(control, defect_task_id)
    result = DefectQualificationControl(evidence_root=str(tmp_path / "defect-evidence")).qualify(
        control,
        defect_task_id,
        product_gap_id=PRODUCT_GAP,
        bundle=_bundle(tmp_path),
        reproduction=_reproduction(truth, reproduced=False),
    )
    assert result.defect.state.value == "QUALIFYING"
    assert result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert control.scheduler.task(defect_task_id).state == TaskStatus.REPAIR_REQUIRED
    repair_tasks = [
        row
        for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "REPAIR" and PRODUCT_GAP in row.get("gap_refs", [])
    ]
    assert repair_tasks
    assert any(row.get("state") == "READY" for row in repair_tasks)
