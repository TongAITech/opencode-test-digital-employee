from __future__ import annotations

from pathlib import Path

from rc6_runtime.automation import ScriptArtifact
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.defect_reproduction import DefectReproductionExecutionService
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
from rc7_runtime.script_validation import EvidenceBackedScriptReadinessValidator


MISSION = "MISSION-DEFECT-REPRO"
ORIGINAL_TASK = "TASK-EXEC-ORIGINAL"
REPRO_TASK = "TASK-EXEC-DEFECT-REPRO"
PRODUCT_GAP = "GAP-PRODUCT-ORIGINAL"
TARGET = "TARGET-DEFECT-REPRO"


def _case():
    return {
        "tc_id": "TC-DEFECT-REPRO",
        "case_version": 1,
        "status": "FROZEN",
        "release_id": "RC7-DEFECT-REPRO",
        "requirement_id": "REQ-DEFECT-REPRO",
        "sst_id": "SST-DEFECT-REPRO",
        "layer": "L2",
        "preconditions": [],
        "steps": [{"order": 1, "action": "reproduce database-backed mismatch"}],
        "expected": "business_code=OK",
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
        "target_requirements": ["REQ-DEFECT-REPRO"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://defect-repro"],
        "cleanup_policy": {"mode": "NONE"},
        "runner_type": "PYTEST",
    }


def _bundle(tmp_path: Path, business_code="BAD"):
    case = _case()
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-DEFECT-REPRO",),
        test_data_refs=(),
        oracle_refs=("oracle://defect-repro",),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    source = tmp_path / ("test_defect_repro_%s.py" % business_code.lower())
    source.write_text(
        '''import json\nimport os\n\ndef _emit(row):\n    with open(os.environ["RC6_EXECUTION_MANIFEST"], "a", encoding="utf-8") as handle:\n        handle.write(json.dumps(row, sort_keys=True) + "\\n")\n\ndef test_defect_reproduction():\n    _emit({"type":"tool_call","tool_id":"database","call_ref":"database-call://defect-repro","evidence_ref":"database-evidence://defect-repro"})\n    _emit({"type":"actual_result","value":{"business_code":"%s","source":"real-reproduction-process"}})\n    assert True\n''' % business_code,
        encoding="utf-8",
    )
    script = ScriptArtifact(
        script_id="SCRIPT-DEFECT-REPRO-%s" % business_code,
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(source),
        test_symbol="test_defect_reproduction",
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=("evidence://builder",),
        revision=1,
    )
    validation = EvidenceBackedScriptReadinessValidator(
        evidence_root=str(tmp_path / "script-readiness"),
        timeout_seconds=20,
    ).validate(spec=spec, script=script, cwd=str(tmp_path))
    assert validation.ready
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


def _prepared(attempt_id):
    return PreparedAttempt(
        status="PREPARED",
        attempt_id=attempt_id,
        tc_id="TC-DEFECT-REPRO",
        case_version=1,
        target_id=TARGET,
        precondition_evidence=(),
        initial_state_bindings={},
        input_data_bindings={},
        binding_evidence=(),
        cleanup_policy={"mode": "NONE"},
        oracle_snapshot=_case()["oracle"],
    )


def _broker():
    broker = ToolCapabilityBroker()
    broker.discover("database", "qualification://database")
    broker.mark_executable("database", "executable://database")
    broker.register("database", "registration://database")
    broker.record_probe(
        "database",
        success=True,
        tool_call_ref="probe://database",
        evidence_ref="probe-evidence://database",
    )
    broker.mark_target_ready("database", TARGET, "target-ready://database")
    return broker


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7-DEFECT-REPRO",
            goal="prove defect reproduction does not duplicate product defect handoff",
        ),
    )
    control.register_task(
        Task(
            task_id=ORIGINAL_TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="original trusted product failure",
            required_capabilities=["test_execution"],
        )
    )
    leased = control.lease_next(worker_ref="original-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == ORIGINAL_TASK
    control.start(ORIGINAL_TASK, worker_ref="original-worker")
    evidence = Evidence(
        evidence_id="EVD-ORIGINAL-PRODUCT",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://original",
        content_ref="evidence://original-product",
        subject_refs=[ORIGINAL_TASK, "ATT-ORIGINAL", "TC-DEFECT-REPRO"],
    )
    artifact = Artifact(
        artifact_id="ART-ORIGINAL-PRODUCT",
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=ORIGINAL_TASK,
        content_ref="artifact://original-product",
        evidence_refs=[evidence.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=ORIGINAL_TASK,
            worker_ref="original-worker",
            artifacts=(artifact,),
            evidence=(evidence,),
        )
    )
    gap = Gap(
        gap_id=PRODUCT_GAP,
        mission_id=MISSION,
        source_node="EXECUTION",
        category="PRODUCT_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="DEFECT",
        description="trusted original product mismatch",
        subject_refs=["ATT-ORIGINAL", "TC-DEFECT-REPRO"],
        evidence_refs=[evidence.evidence_id],
        acceptance_criteria=["defect lifecycle reaches terminal evidence-backed resolution"],
    )
    control.accept_evaluation(
        ORIGINAL_TASK,
        evaluation=Evaluation(
            evaluation_id="EVAL-ORIGINAL-PRODUCT",
            mission_id=MISSION,
            node="EXECUTION",
            artifact_refs=[artifact.artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="original-independent-gate",
            dimensions={"test_result": "FAIL", "failure_class": "PRODUCT"},
            gap_refs=[gap.gap_id],
            evidence_refs=[evidence.evidence_id],
        ),
        gaps=(gap,),
    )
    assert control.scheduler.task(ORIGINAL_TASK).state == TaskStatus.PASS
    assert truth.query("rc7_gap", gap_id=PRODUCT_GAP)[0]["state"] == "PLANNED"
    return truth, control


def _register_reproduction(control):
    control.register_task(
        Task(
            task_id=REPRO_TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="DEFECT_REPRODUCTION",
            objective="independently reproduce the original product mismatch",
            required_capabilities=["test_execution"],
            dependency_task_ids=[ORIGINAL_TASK],
            input_artifact_refs=["ART-ORIGINAL-PRODUCT"],
            priority=10,
        )
    )
    assert control.scheduler.task(REPRO_TASK).state == TaskStatus.READY


def test_real_oracle_fail_reproduction_passes_reproduction_task_without_duplicate_product_gap(tmp_path: Path):
    truth, control = _control(tmp_path)
    _register_reproduction(control)

    result = DefectReproductionExecutionService(
        evidence_root=str(tmp_path / "evidence"),
        timeout_seconds=20,
    ).execute_task(
        control,
        REPRO_TASK,
        source_product_gap_id=PRODUCT_GAP,
        bundle=_bundle(tmp_path, "BAD"),
        prepared=_prepared("ATT-REPRO-1"),
        authority=RC7AuthorityRuntime(b"rc7-defect-repro-signing-key"),
        tool_broker=_broker(),
        cwd=str(tmp_path),
    )

    assert result.conclusive is True
    assert result.reproduced is True
    assert result.execution_record.status == "FAIL"
    assert result.execution_record.integrity_passed is True
    assert result.execution_record.assertion_passed is False
    assert result.task_state == "PASS"
    assert control.scheduler.task(REPRO_TASK).state == TaskStatus.PASS
    assert len(truth.query("rc7_artifact", artifact_id=result.record_artifact_id)) == 1
    product_gaps = [
        row for row in truth.query("rc7_gap", mission_id=MISSION)
        if row.get("category") == "PRODUCT_DEFECT"
    ]
    assert len(product_gaps) == 1
    assert product_gaps[0]["gap_id"] == PRODUCT_GAP


def test_real_business_pass_is_conclusive_non_reproduction_without_new_product_gap(tmp_path: Path):
    truth, control = _control(tmp_path)
    _register_reproduction(control)

    result = DefectReproductionExecutionService(
        evidence_root=str(tmp_path / "evidence"),
        timeout_seconds=20,
    ).execute_task(
        control,
        REPRO_TASK,
        source_product_gap_id=PRODUCT_GAP,
        bundle=_bundle(tmp_path, "OK"),
        prepared=_prepared("ATT-REPRO-2"),
        authority=RC7AuthorityRuntime(b"rc7-defect-repro-signing-key"),
        tool_broker=_broker(),
        cwd=str(tmp_path),
    )

    assert result.conclusive is True
    assert result.reproduced is False
    assert result.execution_record.status == "PASS"
    assert result.task_state == "PASS"
    product_gaps = [
        row for row in truth.query("rc7_gap", mission_id=MISSION)
        if row.get("category") == "PRODUCT_DEFECT"
    ]
    assert len(product_gaps) == 1
