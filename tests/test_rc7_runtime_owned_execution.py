from __future__ import annotations

import json
from pathlib import Path

from rc6_runtime.automation import ScriptArtifact
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.preparation import PreparedAttempt
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.runtime_execution import VerifiedScriptExecutionBundle
from rc7_runtime.runtime_execution_strict import StrictRuntimeOwnedExecutionCoordinator
from rc7_runtime.script_validation import EvidenceBackedScriptReadinessValidator


TARGET = "QUAL-TARGET-L3"


def _case():
    return {
        "tc_id": "TC-RUNTIME-EXEC-1",
        "case_version": 1,
        "status": "FROZEN",
        "release_id": "RC7-EXEC-TEST",
        "requirement_id": "REQ-EXEC-1",
        "sst_id": "SST-EXEC-1",
        "layer": "L3",
        "preconditions": [],
        "test_data": {
            "initial_state": [],
            "input_data": [],
            "cleanup_policy": {"mode": "NONE"},
        },
        "steps": [{"order": 1, "action": "invoke qualified API path"}],
        "expected": "business_code=OK",
        "oracle": {"checks": [{"type": "BUSINESS_RULE", "expected": "OK"}]},
        "evidence_requirements": ["api-runtime-call", "actual-result", "oracle-assertion"],
        "target_requirements": ["REQ-EXEC-1"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://business-code-ok"],
        "cleanup_policy": {"mode": "NONE"},
        "runner_type": "PYTEST",
    }


def _source(*, fail_after_actual=False, emit_tool=True):
    tool_line = """
    _append({"type":"tool_call","tool_id":"api-runtime","call_ref":"api-call://real-1","evidence_ref":"api-evidence://real-1"})
""" if emit_tool else ""
    terminal = "assert False, 'real runner failure after claimed actual result'" if fail_after_actual else "assert True"
    return f'''import json\nimport os\n\ndef _append(row):\n    path = os.environ["RC6_EXECUTION_MANIFEST"]\n    with open(path, "a", encoding="utf-8") as handle:\n        handle.write(json.dumps(row, sort_keys=True) + "\\n")\n\ndef test_runtime_owned_execution():\n{tool_line}    _append({{"type":"actual_result","value":{{"business_code":"OK","source":"real-process"}}}})\n    {terminal}\n'''


def _bundle(tmp_path: Path, source: str):
    case = _case()
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-EXEC-1",),
        test_data_refs=(),
        oracle_refs=("oracle://business-code-ok",),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    source_path = tmp_path / "test_runtime_owned_execution_fixture.py"
    source_path.write_text(source, encoding="utf-8")
    script = ScriptArtifact(
        script_id="SCRIPT-RUNTIME-EXEC-1",
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(source_path),
        test_symbol="test_runtime_owned_execution",
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=("evidence://builder",),
        revision=1,
    )
    validation = EvidenceBackedScriptReadinessValidator(
        evidence_root=str(tmp_path / "readiness-evidence"),
        timeout_seconds=20,
    ).validate(spec=spec, script=script, cwd=str(tmp_path))
    assert validation.ready
    return VerifiedScriptExecutionBundle(
        upstream_mission_id="UPSTREAM-SCRIPT-MISSION",
        upstream_task_id="UPSTREAM-SCRIPT-TASK",
        upstream_evaluation_id="UPSTREAM-SCRIPT-EVAL",
        upstream_result_ref="file://upstream-result.json",
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
        attempt_id="ATT-RUNTIME-EXEC-1",
        tc_id="TC-RUNTIME-EXEC-1",
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
    broker.discover("api-runtime", "qualification://api-runtime")
    broker.mark_executable("api-runtime", "executable://api-runtime")
    broker.register("api-runtime", "registration://api-runtime")
    broker.record_probe(
        "api-runtime",
        success=True,
        tool_call_ref="probe-call://api-runtime",
        evidence_ref="probe-evidence://api-runtime",
    )
    broker.mark_target_ready("api-runtime", TARGET, "target-ready://api-runtime")
    return broker


def _oracle(oracle, actual, context):
    passed = actual.get("business_code") == "OK"
    return {
        "passed": passed,
        "assertion_ref": "assertion://business-code-ok",
        "evidence_refs": ["oracle-evidence://business-code-ok"],
        "details": {"expected": "OK", "actual": actual.get("business_code")},
    }


def _execute(tmp_path: Path, source: str):
    bundle = _bundle(tmp_path, source)
    coordinator = StrictRuntimeOwnedExecutionCoordinator(
        evidence_root=str(tmp_path / "execution-evidence"),
        timeout_seconds=20,
    )
    return coordinator.execute(
        bundle=bundle,
        prepared=_prepared(),
        authority=RC7AuthorityRuntime(b"rc7-runtime-execution-signing-key"),
        tool_broker=_broker(),
        oracle_evaluator=_oracle,
        cwd=str(tmp_path),
        env=None,
    )


def test_runtime_process_and_real_tool_evidence_are_required_for_pass(tmp_path: Path):
    outcome = _execute(tmp_path, _source())
    record = outcome.record
    assert record.status == "PASS"
    assert record.integrity_passed is True
    assert record.assertion_passed is True
    assert record.actual_result["source"] == "real-process"
    assert any(ref.startswith("api-call://") for ref in record.tool_call_refs)
    file_refs = [ref for ref in record.evidence_refs if ref.startswith("file://")]
    assert file_refs
    assert all(Path(ref[len("file://"):]).is_file() for ref in file_refs)


def test_nonzero_real_runner_exit_cannot_be_hidden_by_claimed_actual_result(tmp_path: Path):
    outcome = _execute(tmp_path, _source(fail_after_actual=True))
    record = outcome.record
    assert record.actual_result["business_code"] == "OK"
    assert record.assertion_passed is True
    assert record.status == "FAIL"
    assert record.integrity_passed is False
    assert record.reason.startswith("RUNNER_PROCESS_FAILED:")


def test_pytest_success_without_required_business_tool_call_never_passes(tmp_path: Path):
    outcome = _execute(tmp_path, _source(emit_tool=False))
    record = outcome.record
    assert record.status == "FAIL"
    assert record.integrity_passed is False
    assert record.reason == "REQUIRED_REAL_TOOL_CALL_MISSING:api-runtime"
