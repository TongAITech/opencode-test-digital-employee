from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from rc6_runtime.automation import ScriptArtifact
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.execution_profiles import RC7_1_EXECUTION_PROFILES
from rc7_runtime.models import EvaluationResult, Mission, Task, TaskStatus
from rc7_runtime.runtime_execution import VerifiedScriptExecutionBundle
from rc7_runtime.runtime_execution_control import ClosedLoopRuntimeExecutionService
from rc7_runtime.script_validation import EvidenceBackedScriptReadinessValidator


TARGET = "TARGET-RC7-1-LAYER-PRODUCTION"


def _case(layer: str) -> dict:
    return {
        "tc_id": "TC-RC7-1-%s" % layer,
        "case_version": 1,
        "status": "FROZEN",
        "release_id": "RC7.1-LAYER-PRODUCTION",
        "requirement_id": "REQ-RC7-1-LAYER-PRODUCTION",
        "sst_id": "SST-RC7-1-LAYER-PRODUCTION",
        "layer": layer,
        "preconditions": [],
        "steps": [{"order": 1, "action": "execute governed %s runtime" % layer}],
        "expected": "business_code=OK",
        "oracle": {"checks": [{"type": "BUSINESS_RULE", "expected": "OK"}]},
        "evidence_requirements": ["runtime-action", "oracle", "layer-contract"],
        "target_requirements": ["REQ-RC7-1-LAYER-PRODUCTION"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://rc7-1/%s/business-code-ok" % layer.lower()],
        "cleanup_policy": {"mode": "NONE"},
        "runner_type": "PYTEST",
    }


def _source(symbol: str, *, include_layer_evidence: bool = True) -> str:
    layer_payload = '''
    layer_evidence = {
        "layer": layer,
        "case_id": tc_id,
        "target_id": target_id,
        "mission_id": mission_id,
        "attempt_id": attempt_id,
        "worker_id": worker_id,
        "session_id": "SESSION-" + layer,
        "started_at": "2026-10-23T08:00:00Z",
        "finished_at": "2026-10-23T08:00:01Z",
        "status": "PASS",
        "preconditions": [],
        "test_data": {},
        "steps": ["execute governed runtime"],
        "expected_results": ["business_code=OK"],
        "actual_results": ["business_code=OK"],
        "assertions": [{
            "assertion_id": "ASSERT-" + layer,
            "expected": "OK",
            "actual": "OK",
            "result": "PASS",
            "evidence_refs": [raw_ref],
        }],
        "evidence_refs": [raw_ref],
        "execution_receipt": {
            "receipt_id": "LOCAL-RECEIPT-" + layer,
            "case_id": tc_id,
            "attempt_id": attempt_id,
            "target_id": target_id,
            "status": "PASS",
        },
    }
    if layer == "L4":
        layer_evidence["browser"] = {
            "page_open": ["/login", "/cfg/version"],
            "actions": ["fresh 4A login", "query version"],
            "state_reads": ["version row visible"],
            "evidence_types": ["screenshot", "dom", "trace", "network"],
            "evidence_refs": [raw_ref],
        }
        layer_evidence["auth"] = {
            "required_4a": True,
            "method": "foura_auth.py",
            "fresh_login": True,
            "historical_cookie_fallback": False,
            "expiry_relogin_supported": True,
        }
    elif layer == "L5":
        layer_evidence["api_calls"] = [{
            "url": "/api/version/query",
            "method": "POST",
            "request": {"version": "1.2.0"},
            "response": {"code": "0000", "rows": 1},
            "status_code": 200,
            "business_code": "0000",
            "route_source": "browser_network_capture",
            "endpoint_guessed": False,
            "evidence_refs": [raw_ref],
        }]
    elif layer == "L6":
        layer_evidence["capability"] = {
            "status": "AVAILABLE",
            "tool_name": "governed-capability",
            "evidence_refs": [raw_ref],
        }
    elif layer == "L7":
        layer_evidence["real_runtime_execution"] = True
        layer_evidence["E2E_VERIFIED_REQUIRES_REAL_RUNTIME_EXECUTION"] = True
        layer_evidence["e2e_chain"] = {
            "entry": "browser entry",
            "frontend": "page state",
            "api": "captured request/response",
            "service": "service execution",
            "data_or_state": "persisted state",
            "business_result": "business_code=OK",
            "oracle": "business-code assertion",
            "evidence_refs": [raw_ref],
        }
''' if include_layer_evidence else '    layer_evidence = None\n'
    actual = '''{"business_code":"OK","case_id":tc_id,"layer_evidence":layer_evidence}''' if include_layer_evidence else '''{"business_code":"OK","case_id":tc_id}'''
    return '''import json
import os


def _emit(row):
    with open(os.environ["RC6_EXECUTION_MANIFEST"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\\n")


def %s():
    layer = os.environ["RC7_LAYER"]
    tc_id = os.environ["RC7_TC_ID"]
    mission_id = os.environ["RC7_MISSION_ID"]
    attempt_id = os.environ["RC7_ATTEMPT_ID"]
    worker_id = os.environ["RC7_WORKER_ID"]
    target_id = os.environ["RC7_TARGET_ID"]
    tool_id = os.environ["RC7_TOOL_ID"]
    evidence_path = os.path.abspath(os.environ["RC7_EVIDENCE_FILE"])
    with open(evidence_path, "w", encoding="utf-8") as handle:
        json.dump({"layer": layer, "tc_id": tc_id, "attempt_id": attempt_id, "captured": True}, handle, sort_keys=True)
    raw_ref = "file://" + evidence_path
%s
    _emit({"type":"tool_call","tool_id":tool_id,"call_ref":"tool-call://"+layer,"evidence_ref":raw_ref})
    _emit({"type":"actual_result","value":%s})
    assert True
''' % (symbol, layer_payload, actual)


def _bundle(tmp_path: Path, layer: str, *, include_layer_evidence: bool = True) -> VerifiedScriptExecutionBundle:
    case = _case(layer)
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-RC7-1-LAYER-PRODUCTION",),
        test_data_refs=(),
        oracle_refs=("oracle://rc7-1/%s/business-code-ok" % layer.lower(),),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    symbol = "test_rc7_1_%s_production" % layer.lower()
    source_path = tmp_path / ("test_rc7_1_%s_fixture.py" % layer.lower())
    source_path.write_text(_source(symbol, include_layer_evidence=include_layer_evidence), encoding="utf-8")
    script = ScriptArtifact(
        script_id="SCRIPT-RC7-1-" + layer,
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(source_path),
        test_symbol=symbol,
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=("evidence://script-builder/%s" % layer.lower(),),
        revision=1,
    )
    validation = EvidenceBackedScriptReadinessValidator(
        evidence_root=str(tmp_path / "script-validation"),
        timeout_seconds=20,
    ).validate(spec=spec, script=script, cwd=str(tmp_path))
    assert validation.ready
    return VerifiedScriptExecutionBundle(
        upstream_mission_id="MISSION-UPSTREAM-" + layer,
        upstream_task_id="TASK-UPSTREAM-" + layer,
        upstream_evaluation_id="EVAL-UPSTREAM-" + layer,
        upstream_result_ref="runtime://upstream/" + layer,
        spec_ref="runtime://spec/" + layer,
        frozen_case=case,
        spec=spec,
        script=script,
        validation=validation,
        source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
    )


def _prepared(layer: str) -> PreparedAttempt:
    return PreparedAttempt(
        status="PREPARED",
        attempt_id="ATT-RC7-1-" + layer,
        tc_id="TC-RC7-1-" + layer,
        case_version=1,
        target_id=TARGET,
        precondition_evidence=(),
        initial_state_bindings={},
        input_data_bindings={},
        binding_evidence=(),
        cleanup_policy={"mode": "NONE"},
        oracle_snapshot=_case(layer)["oracle"],
    )


def _broker(tool_id: str) -> ToolCapabilityBroker:
    broker = ToolCapabilityBroker()
    broker.discover(tool_id, "qualification://" + tool_id)
    broker.mark_executable(tool_id, "executable://" + tool_id)
    broker.register(tool_id, "registration://" + tool_id)
    broker.record_probe(
        tool_id,
        success=True,
        tool_call_ref="probe://" + tool_id,
        evidence_ref="probe-evidence://" + tool_id,
    )
    broker.mark_target_ready(tool_id, TARGET, "target-ready://" + tool_id)
    return broker


def _oracle(_oracle_snapshot, actual, _context):
    layer_evidence = actual.get("layer_evidence") if isinstance(actual.get("layer_evidence"), dict) else {}
    layer = str(layer_evidence.get("layer") or "UNKNOWN")
    refs = layer_evidence.get("evidence_refs") if isinstance(layer_evidence.get("evidence_refs"), list) else []
    evidence_ref = refs[0] if refs else "runtime-evidence://oracle/no-layer-contract"
    return {
        "passed": actual.get("business_code") == "OK",
        "assertion_ref": "assertion://%s/business-code-ok" % layer.lower(),
        "evidence_refs": [evidence_ref],
        "details": {"expected": "OK", "actual": actual.get("business_code")},
    }


def _control(tmp_path: Path, layer: str):
    mission_id = "MISSION-RC7-1-LAYER-" + layer
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=mission_id,
            release_id="RC7.1-LAYER-PRODUCTION",
            goal="prove %s production evidence contract" % layer,
        ),
    )
    task = Task(
        task_id="TASK-RC7-1-LAYER-" + layer,
        mission_id=mission_id,
        node="EXECUTION",
        task_type="EXECUTE",
        objective="execute governed %s production service" % layer,
        required_capabilities=["test_execution"],
    )
    control.register_task(task)
    assert control.scheduler.task(task.task_id).state == TaskStatus.READY
    return truth, control, task.task_id, mission_id


def _run(tmp_path: Path, layer: str, *, include_layer_evidence: bool = True):
    truth, control, task_id, mission_id = _control(tmp_path, layer)
    bundle = _bundle(tmp_path, layer, include_layer_evidence=include_layer_evidence)
    prepared = _prepared(layer)
    tool_id = RC7_1_EXECUTION_PROFILES[layer].required_tools[0]
    authority = RC7AuthorityRuntime(b"rc7-1-layer-production-signing-key")
    broker = _broker(tool_id)
    service = ClosedLoopRuntimeExecutionService(
        evidence_root=str(tmp_path / "execution-evidence"),
        timeout_seconds=20,
    )
    active = service.activate_task(
        control,
        task_id,
        bundle=bundle,
        target_id=TARGET,
        authority=authority,
        tool_broker=broker,
    )
    proof_file = tmp_path / ("%s-current-run-proof.json" % layer.lower())
    result = service.execute_active_task(
        control,
        task_id,
        bundle=bundle,
        prepared=prepared,
        active=active,
        authority=authority,
        tool_broker=broker,
        oracle_evaluator=_oracle,
        cwd=str(tmp_path),
        env={
            "RC7_LAYER": layer,
            "RC7_TC_ID": bundle.spec.tc_id,
            "RC7_MISSION_ID": mission_id,
            "RC7_ATTEMPT_ID": prepared.attempt_id,
            "RC7_WORKER_ID": active.runtime_worker_id,
            "RC7_TARGET_ID": TARGET,
            "RC7_TOOL_ID": tool_id,
            "RC7_EVIDENCE_FILE": str(proof_file.resolve()),
        },
    )
    return truth, control, result


@pytest.mark.parametrize("layer", ["L4", "L5", "L6", "L7"])
def test_real_production_service_requires_and_accepts_complete_layer_evidence(tmp_path: Path, layer: str) -> None:
    truth, control, result = _run(tmp_path, layer)
    assert result.execution_record.status == "PASS"
    assert result.execution_record.integrity_passed is True
    assert result.execution_record.assertion_passed is True
    assert result.loop_result.evaluation.result == EvaluationResult.PASS
    assert result.loop_result.conclusive is True
    assert result.loop_result.evaluation.dimensions["layer_evidence_contract_required"] is True
    assert result.loop_result.evaluation.dimensions["layer_evidence_contract_passed"] is True
    assert result.task_state == "PASS"
    assert control.scheduler.task("TASK-RC7-1-LAYER-" + layer).state == TaskStatus.PASS

    # Subprocess proof must physically exist and be hashed into canonical R1 Evidence.
    runtime_evidence = [
        row for row in truth.query("rc7_evidence", mission_id="MISSION-RC7-1-LAYER-" + layer)
        if row.get("kind") == "RUNTIME_EXECUTION_EVIDENCE"
        and str(row.get("content_ref", "")).startswith("file://")
    ]
    assert runtime_evidence
    for row in runtime_evidence:
        proof = Path(str(row["content_ref"])[len("file://"):])
        assert proof.is_file()
        assert row.get("content_hash") == "sha256:" + hashlib.sha256(proof.read_bytes()).hexdigest()


def test_real_service_generic_l5_pass_without_layer_contract_cannot_be_executed_pass(tmp_path: Path) -> None:
    _truth, control, result = _run(tmp_path, "L5", include_layer_evidence=False)
    assert result.execution_record.status == "PASS"
    assert result.execution_record.integrity_passed is True
    assert result.loop_result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert result.loop_result.conclusive is False
    assert result.loop_result.test_result == "INCONCLUSIVE"
    assert result.loop_result.evaluation.dimensions["layer_evidence_contract_passed"] is False
    assert "layer_evidence" in result.loop_result.evaluation.dimensions["layer_evidence_contract_missing"]
    assert result.task_state == "REPAIR_REQUIRED"
    assert control.scheduler.task("TASK-RC7-1-LAYER-L5").state == TaskStatus.REPAIR_REQUIRED
