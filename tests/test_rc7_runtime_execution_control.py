from __future__ import annotations

import json
from pathlib import Path

from rc6_runtime.automation import ScriptArtifact
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.runtime_execution import VerifiedScriptExecutionBundle
from rc7_runtime.runtime_execution_control import ClosedLoopRuntimeExecutionService
from rc7_runtime.script_validation import EvidenceBackedScriptReadinessValidator


TARGET = "TARGET-R1-EXEC"


def _case():
    return {
        "tc_id": "TC-R1-EXEC-1",
        "case_version": 1,
        "status": "FROZEN",
        "release_id": "RC7-R1-EXEC",
        "requirement_id": "REQ-R1-EXEC",
        "sst_id": "SST-R1-EXEC",
        "layer": "L2",
        "preconditions": [],
        "steps": [{"order": 1, "action": "execute runtime-owned component test"}],
        "expected": "business_code=OK",
        "oracle": {"checks": [{"type": "BUSINESS_RULE", "expected": "OK"}]},
        "evidence_requirements": ["process", "database-call", "oracle"],
        "target_requirements": ["REQ-R1-EXEC"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://r1-exec-ok"],
        "cleanup_policy": {"mode": "NONE"},
        "runner_type": "PYTEST",
    }


def _source(*, process_fail=False):
    tail = "assert False, 'real process failed'" if process_fail else "assert True"
    return f'''import json\nimport os\n\ndef _emit(row):\n    with open(os.environ["RC6_EXECUTION_MANIFEST"], "a", encoding="utf-8") as handle:\n        handle.write(json.dumps(row, sort_keys=True) + "\\n")\n\ndef test_r1_formal_execution():\n    _emit({{"type":"tool_call","tool_id":"database","call_ref":"database-call://r1","evidence_ref":"database-evidence://r1"}})\n    _emit({{"type":"actual_result","value":{{"business_code":"OK","origin":"subprocess"}}}})\n    {tail}\n'''


def _bundle(tmp_path: Path, *, process_fail=False):
    case = _case()
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-R1-EXEC",),
        test_data_refs=(),
        oracle_refs=("oracle://r1-exec-ok",),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    source_path = tmp_path / "test_r1_execution_fixture.py"
    source_path.write_text(_source(process_fail=process_fail), encoding="utf-8")
    script = ScriptArtifact(
        script_id="SCRIPT-R1-EXEC-1",
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(source_path),
        test_symbol="test_r1_formal_execution",
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=("evidence://script-builder",),
        revision=1,
    )
    validation = EvidenceBackedScriptReadinessValidator(
        evidence_root=str(tmp_path / "script-revalidation"),
        timeout_seconds=20,
    ).validate(spec=spec, script=script, cwd=str(tmp_path))
    assert validation.ready
    return VerifiedScriptExecutionBundle(
        upstream_mission_id="MISSION-UPSTREAM-SCRIPT",
        upstream_task_id="TASK-UPSTREAM-SCRIPT",
        upstream_evaluation_id="EVAL-UPSTREAM-SCRIPT",
        upstream_result_ref="file://upstream-script-result.json",
        spec_ref="file://upstream-spec.json",
        frozen_case=case,
        spec=spec,
        script=script,
        validation=validation,
        source_sha256="fixture",
    )


def _prepared():
    return PreparedAttempt(
        status="PREPARED",
        attempt_id="ATT-R1-EXEC-1",
        tc_id="TC-R1-EXEC-1",
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


def _oracle(_oracle_snapshot, actual, _context):
    return {
        "passed": actual.get("business_code") == "OK",
        "assertion_ref": "assertion://r1-exec-ok",
        "evidence_refs": ["oracle-evidence://r1-exec-ok"],
        "details": {"actual": actual.get("business_code")},
    }


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id="MISSION-R1-EXEC",
            release_id="RC7-R1-EXEC",
            goal="prove runtime-owned execution reaches durable R1 control truth",
        ),
    )
    task = Task(
        task_id="TASK-R1-EXEC",
        mission_id="MISSION-R1-EXEC",
        node="EXECUTION",
        task_type="EXECUTE",
        objective="execute one approved prepared script",
        required_capabilities=["test_execution"],
    )
    control.register_task(task)
    assert control.scheduler.task(task.task_id).state == TaskStatus.READY
    return truth, control, task.task_id


def _run(tmp_path: Path, *, process_fail=False):
    truth, control, task_id = _control(tmp_path)
    result = ClosedLoopRuntimeExecutionService(
        evidence_root=str(tmp_path / "execution-evidence"),
        timeout_seconds=20,
    ).execute_task(
        control,
        task_id,
        bundle=_bundle(tmp_path, process_fail=process_fail),
        prepared=_prepared(),
        authority=RC7AuthorityRuntime(b"rc7-r1-execution-signing-key"),
        tool_broker=_broker(),
        oracle_evaluator=_oracle,
        cwd=str(tmp_path),
    )
    return truth, control, result


def test_real_execution_pass_is_durable_r1_task_pass(tmp_path: Path):
    truth, control, result = _run(tmp_path)
    assert result.execution_record.status == "PASS"
    assert result.execution_record.integrity_passed is True
    assert result.task_state == "PASS"

    task = control.scheduler.task("TASK-R1-EXEC")
    assert task.state == TaskStatus.PASS
    assert task.output_artifact_refs == [result.record_artifact_id]
    evaluations = truth.query("rc7_evaluation", evaluation_id=task.evaluation_id)
    assert len(evaluations) == 1
    assert evaluations[0]["dimensions"]["test_result"] == "PASS"
    artifacts = truth.query("rc7_artifact", artifact_id=result.record_artifact_id)
    assert len(artifacts) == 1
    record_path = Path(artifacts[0]["content_ref"][len("file://"):])
    assert record_path.is_file()
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    assert payload["record"]["actual_result"]["origin"] == "subprocess"
    assert payload["record"]["worker_id"] == result.runtime_worker_id


def test_real_runner_failure_is_classified_as_script_repair_not_product_or_unknown(tmp_path: Path):
    truth, control, result = _run(tmp_path, process_fail=True)
    assert result.execution_record.actual_result["business_code"] == "OK"
    assert result.execution_record.status == "FAIL"
    assert result.execution_record.integrity_passed is False
    assert result.execution_record.reason.startswith("RUNNER_PROCESS_FAILED:")
    assert result.task_state == "REPAIR_REQUIRED"

    task = control.scheduler.task("TASK-R1-EXEC")
    assert task.state == TaskStatus.REPAIR_REQUIRED
    evaluation = truth.query("rc7_evaluation", evaluation_id=task.evaluation_id)[0]
    assert evaluation["result"] == "REPAIR_REQUIRED"
    assert evaluation["dimensions"]["test_result"] == "INCONCLUSIVE"
    assert evaluation["dimensions"]["failure_class"] == "SCRIPT"
    assert evaluation["dimensions"]["recovery_action"] == "REPAIR_SCRIPT"
    gaps = truth.query("rc7_gap", mission_id="MISSION-R1-EXEC")
    script_gaps = [gap for gap in gaps if gap["category"] == "SCRIPT_DEFECT"]
    assert len(script_gaps) == 1
    assert script_gaps[0]["target_node"] == "SCRIPT_READINESS"
    assert not any(gap["category"] in {"PRODUCT_DEFECT", "UNKNOWN_FAILURE"} for gap in gaps)
