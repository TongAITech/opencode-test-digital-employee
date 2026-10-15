from __future__ import annotations

from pathlib import Path

from rc6_runtime.automation import ScriptArtifact
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.autonomous_execution_service import AutonomousClosedLoopExecutionService
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.runtime_execution import VerifiedScriptExecutionBundle
from rc7_runtime.script_validation import EvidenceBackedScriptReadinessValidator


MISSION = "MISSION-PREP-EXEC-E2E"
TASK = "TASK-PREP-EXEC-E2E"
TARGET = "TARGET-PREP-EXEC-E2E"
ATTEMPT = "ATT-PREP-EXEC-E2E-1"


def _case():
    return {
        "tc_id": "TC-PREP-EXEC-E2E",
        "case_version": 1,
        "status": "FROZEN",
        "release_id": "RC7-PREP-EXEC-E2E",
        "requirement_id": "REQ-PREP-EXEC-E2E",
        "sst_id": "SST-PREP-EXEC-E2E",
        "layer": "L2",
        "preconditions": [
            {"id": "PRE-DB", "type": "ENVIRONMENT", "requirement": "database target reachable"},
        ],
        "test_data": {
            "initial_state": [
                {
                    "id": "STATE-LOAN",
                    "selectors": {"status": "DRAFT"},
                    "allowed_strategies": ["REUSE_EXISTING"],
                }
            ],
            "input_data": [
                {
                    "id": "INPUT-AMOUNT",
                    "selectors": {"amount": 1000},
                    "allowed_strategies": ["DERIVE"],
                }
            ],
            "cleanup_policy": {"mode": "NONE"},
        },
        "steps": [{"order": 1, "action": "execute component rule with prepared bindings"}],
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
        "evidence_requirements": ["preparation", "database-call", "oracle"],
        "target_requirements": ["REQ-PREP-EXEC-E2E"],
        "test_data_refs": ["STATE-LOAN", "INPUT-AMOUNT"],
        "oracle_refs": ["oracle://prep-exec-ok"],
        "cleanup_policy": {"mode": "NONE"},
        "runner_type": "PYTEST",
    }


def _bundle(tmp_path: Path):
    case = _case()
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-PREP-EXEC-E2E",),
        test_data_refs=("STATE-LOAN", "INPUT-AMOUNT"),
        oracle_refs=("oracle://prep-exec-ok",),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    source_path = tmp_path / "test_prepared_execution_fixture.py"
    source_path.write_text(
        '''import json\nimport os\n\ndef _emit(row):\n    with open(os.environ["RC6_EXECUTION_MANIFEST"], "a", encoding="utf-8") as handle:\n        handle.write(json.dumps(row, sort_keys=True) + "\\n")\n\ndef test_prepared_execution():\n    assert os.environ["RC7_EXECUTION_ATTEMPT_ID"] == "ATT-PREP-EXEC-E2E-1"\n    _emit({"type":"tool_call","tool_id":"database","call_ref":"database-call://prepared-e2e","evidence_ref":"database-evidence://prepared-e2e"})\n    _emit({"type":"actual_result","value":{"business_code":"OK","loan_id":"L-100","amount":1000}})\n''',
        encoding="utf-8",
    )
    script = ScriptArtifact(
        script_id="SCRIPT-PREP-EXEC-E2E",
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(source_path),
        test_symbol="test_prepared_execution",
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=("evidence://script-builder/prep-e2e",),
        revision=1,
    )
    validation = EvidenceBackedScriptReadinessValidator(
        evidence_root=str(tmp_path / "script-readiness"),
        timeout_seconds=20,
    ).validate(spec=spec, script=script, cwd=str(tmp_path))
    assert validation.ready
    return VerifiedScriptExecutionBundle(
        upstream_mission_id="MISSION-SCRIPT-UPSTREAM",
        upstream_task_id="TASK-SCRIPT-UPSTREAM",
        upstream_evaluation_id="EVAL-SCRIPT-UPSTREAM",
        upstream_result_ref="file://script-upstream.json",
        spec_ref="file://spec-upstream.json",
        frozen_case=case,
        spec=spec,
        script=script,
        validation=validation,
        source_sha256="fixture",
    )


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7-PREP-EXEC-E2E",
            goal="prepare from frozen case and execute without caller-built PreparedAttempt",
        ),
    )
    control.register_task(
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="runtime owns preparation and execution",
            required_capabilities=["test_execution"],
        )
    )
    assert control.scheduler.task(TASK).state == TaskStatus.READY
    return truth, control


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


def _precondition(spec, context):
    return {
        "success": True,
        "evidence_ref": "evidence://precondition/%s/%s" % (spec["id"], context["attempt_id"]),
    }


def _reuse(requirement, context):
    return {
        "success": True,
        "binding": {"loan_id": "L-100", "status": "DRAFT"},
        "tool_call_ref": "toolcall://database/search/L-100",
        "evidence_ref": "evidence://database/search/L-100",
    }


def _derive(requirement, context):
    return {
        "success": True,
        "binding": {"amount": 1000},
        "tool_call_ref": "toolcall://derive/amount/1000",
        "evidence_ref": "evidence://derive/amount/1000",
    }


def _verify(requirement, binding, context):
    return {"success": True, "evidence_ref": "evidence://verify/%s" % requirement["id"]}


def _oracle(_snapshot, actual, _context):
    return {
        "passed": actual.get("business_code") == "OK",
        "assertion_ref": "assertion://prep-exec-ok",
        "evidence_refs": ["oracle-evidence://prep-exec-ok"],
        "details": {"business_code": actual.get("business_code")},
    }


def test_frozen_case_is_prepared_persisted_then_real_subprocess_executes_to_pass(tmp_path: Path):
    truth, control = _control(tmp_path)
    result = AutonomousClosedLoopExecutionService(
        evidence_root=str(tmp_path / "runtime-evidence"),
        timeout_seconds=20,
    ).prepare_and_execute_generic(
        control,
        TASK,
        bundle=_bundle(tmp_path),
        attempt_id=ATTEMPT,
        target_id=TARGET,
        precondition_resolvers={"ENVIRONMENT": _precondition},
        data_strategies={"REUSE_EXISTING": _reuse, "DERIVE": _derive},
        data_verifier=_verify,
        authority=RC7AuthorityRuntime(b"rc7-prep-exec-e2e-signing-key"),
        tool_broker=_broker(),
        oracle_evaluator=_oracle,
        cwd=str(tmp_path),
    )

    assert result.preparation.prepared.attempt_id == ATTEMPT
    assert result.preparation.prepared.initial_state_bindings["STATE-LOAN"]["loan_id"] == "L-100"
    assert result.preparation.prepared.input_data_bindings["INPUT-AMOUNT"]["amount"] == 1000
    assert len(truth.query("rc7_artifact", artifact_id=result.preparation.artifact_id)) == 1
    prep_evidence = [
        truth.query("rc7_evidence", evidence_id=evidence_id)[0]
        for evidence_id in result.preparation.evidence_ids
    ]
    assert {row["kind"] for row in prep_evidence} >= {
        "PRECONDITION_EVIDENCE",
        "PREPARATION_BINDING_EVIDENCE",
        "RUNTIME_PREPARATION_RECORD",
    }

    assert result.execution.converged is True
    assert result.execution.final_task_state == "PASS"
    assert len(result.execution.attempts) == 1
    attempt = result.execution.attempts[0]
    assert attempt.execution_record.attempt_id == ATTEMPT
    assert attempt.execution_record.status == "PASS"
    assert attempt.execution_record.actual_result["loan_id"] == "L-100"
    assert control.scheduler.task(TASK).state == TaskStatus.PASS
