from pathlib import Path

import pytest

from rc6_runtime.automation import ProcessStepResult, ScriptArtifact, ScriptValidation
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.case_runtime import CasePreparationService, PREPARED_ATTEMPT_KIND
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.runtime_execution import VerifiedScriptExecutionBundle
from rc7_runtime.runtime_execution_control import ClosedLoopRuntimeExecutionService


MISSION = "MISSION-ACTIVE-PREP"
TASK = "TASK-ACTIVE-PREP"
TARGET = "PFC-SIT-ACTIVE"


def _case():
    return {
        "status": "FROZEN",
        "tc_id": "TC-ACTIVE-PREP",
        "case_version": 1,
        "release_id": "REL-ACTIVE-PREP",
        "requirement_id": "REQ-ACTIVE-PREP",
        "sst_id": "SST-ACTIVE-PREP",
        "layer": "L2",
        "preconditions": [],
        "test_data": {
            "initial_state": [],
            "input_data": [],
            "cleanup_policy": {"mode": "NONE"},
        },
        "cleanup_policy": {"mode": "NONE"},
        "steps": [{"order": 1, "action": "execute"}],
        "expected": "OK",
        "oracle": {"checks": [{"type": "BUSINESS_RULE", "expected": "OK"}]},
        "evidence_requirements": ["runner-output"],
        "target_requirements": ["REQ-ACTIVE-PREP"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://active-prep"],
        "runner_type": "PYTEST",
    }


def _bundle():
    case = _case()
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-ACTIVE-PREP",),
        test_data_refs=(),
        oracle_refs=("oracle://active-prep",),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    script = ScriptArtifact(
        script_id="SCRIPT-ACTIVE-PREP",
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://unused.py",
        test_symbol="test_active_prep",
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=("EVD-BUILDER",),
        revision=1,
    )
    step = ProcessStepResult(
        name="pytest_collect",
        command=("pytest", "--collect-only"),
        exit_code=0,
        stdout_ref="stdout://active-prep",
        stderr_ref="stderr://active-prep",
        duration_ms=1,
        passed=True,
    )
    validation = ScriptValidation(
        validation_id="VAL-ACTIVE-PREP",
        script_id=script.script_id,
        runner_type=script.runner_type,
        test_symbol=script.test_symbol,
        steps=(step,),
        evidence_refs=("EVD-VALIDATION",),
        status="SCRIPT_READY",
    )
    return VerifiedScriptExecutionBundle(
        upstream_mission_id=MISSION,
        upstream_task_id="TASK-SCRIPT",
        upstream_evaluation_id="EVAL-SCRIPT",
        upstream_result_ref="file://script-receipt.json",
        spec_ref="file://spec.json",
        frozen_case=case,
        spec=spec,
        script=script,
        validation=validation,
        source_sha256="source-sha",
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


def test_field_preparation_uses_same_active_execution_lease(tmp_path: Path):
    state = tmp_path / "state"
    truth = TruthRuntime(state / "r1" / "event-stream.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id="REL-ACTIVE-PREP", goal="prepare under exact execution lease"),
    )
    control.register_task(
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="prepare then execute",
            required_capabilities=["test_execution"],
        )
    )
    service = ClosedLoopRuntimeExecutionService(
        evidence_root=str(tmp_path / "execution-evidence"),
        state_root=str(state),
        timeout_seconds=30,
    )
    active = service.activate_task(
        control,
        TASK,
        bundle=_bundle(),
        target_id=TARGET,
        authority=RC7AuthorityRuntime(b"active-prep-signing-key"),
        tool_broker=_broker(),
    )

    leased = control.scheduler.task(TASK)
    assert leased.state == TaskStatus.LEASED
    assert leased.lease_owner == active.runtime_worker_id

    preparation = CasePreparationService(truth, state)
    planned = preparation.plan(
        mission_id=MISSION,
        task_id=TASK,
        worker_id=active.runtime_worker_id,
        case=_case(),
        attempt_id="ATT-ACTIVE-PREP",
        target_id=TARGET,
    )
    assert planned["status"] == "PASS"
    assert planned["field_required_capabilities"] == []

    prepared = preparation.prepare(
        mission_id=MISSION,
        task_id=TASK,
        worker_id=active.runtime_worker_id,
        case=_case(),
        attempt_id="ATT-ACTIVE-PREP",
        target_id=TARGET,
    )
    assert prepared["status"] == "PREPARED"
    assert prepared["prepared_attempt"]["status"] == "PREPARED"
    rows = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == PREPARED_ATTEMPT_KIND
    ]
    assert len(rows) == 1
    assert TASK in rows[0]["subject_refs"]
    assert active.runtime_worker_id in rows[0]["subject_refs"]
    assert "ATT-ACTIVE-PREP" in rows[0]["subject_refs"]

    with pytest.raises(Exception, match="WORKER_NOT_TASK_OWNER"):
        preparation.plan(
            mission_id=MISSION,
            task_id=TASK,
            worker_id="OTHER-WORKER",
            case=_case(),
            attempt_id="ATT-OTHER",
            target_id=TARGET,
        )
