from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rc6_runtime.automation import ProcessStepResult, ScriptArtifact, ScriptValidation
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.case_fanout_conformance import (
    AcceptedCaseInventoryReader,
    persist_contract,
    record_script_ready,
)
from rc7_runtime.case_runtime import CasePreparationService
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.execution_fanout_conformance import check_execution_barrier
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence, Mission, Task, TaskStatus
from rc7_runtime.runtime_execution import RuntimeExecutionError, VerifiedScriptExecutionBundle
from rc7_runtime.runtime_execution_control import ClosedLoopRuntimeExecutionService
from rc7_runtime.script_contract import AcceptedTestDesignScriptContractCompiler
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-RC7-1-FANOUT-PRODUCTION"
RELEASE = "RC7.1-FANOUT-PRODUCTION"
DESIGN_ARTIFACT = "ART-RC7-1-FANOUT-DESIGN"
DESIGN_TASK = "TASK-RC7-1-FANOUT-DESIGN"
SCRIPT_TASK = "TASK-RC7-1-FANOUT-SCRIPT"
EXECUTION_TASK = "TASK-RC7-1-FANOUT-EXECUTION"
TARGET = "TARGET-RC7-1-FANOUT"


def _case(tc_id: str) -> dict:
    return {
        "tc_id": tc_id,
        "case_version": 1,
        "requirement_id": "REQ-RC7-1-FANOUT",
        "sst_id": "SST-RC7-1-FANOUT",
        "layer": "L3",
        "preconditions": [],
        "test_data": {
            "initial_state": [],
            "input_data": [],
            "cleanup_policy": {"mode": "NONE", "required": False},
        },
        "cleanup_policy": {"mode": "NONE", "required": False},
        "steps": [{"order": 1, "action": "GET", "target": "/loan/%s" % tc_id}],
        "expected": "business_code=OK",
        "oracle": {"checks": [{"type": "BUSINESS_RULE", "expected": "OK"}]},
        "evidence_requirements": ["api-response", "oracle"],
        "target_requirements": ["REQ-RC7-1-FANOUT"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://fanout/business-code-ok"],
        "runner_type": "PYTEST",
        "coverage_links": [],
    }


def _candidate_bytes(cases: list[dict]) -> bytes:
    envelope = {
        "task_id": DESIGN_TASK,
        "artifact": {
            "artifact_id": DESIGN_ARTIFACT,
            "artifact_type": "TEST_DESIGN_MODEL",
            "content_ref": "runtime://accepted-test-design",
            "parent_refs": [],
            "evidence_refs": ["EVD-RC7-1-FANOUT-DESIGN-SOURCE"],
        },
        "semantic_payload": {
            "cases": cases,
            "obligations": [{"obligation_id": "OB-RC7-1-FANOUT"}],
        },
        "evidence": [],
    }
    return (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _setup(tmp_path: Path):
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    truth = TruthRuntime(r1)
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="prove real per-Case execution fanout and restart-safe receipt aggregation",
        ),
    )
    control.register_task(
        Task(
            task_id=DESIGN_TASK,
            mission_id=MISSION,
            node="TEST_DESIGN",
            task_type="PRODUCE",
            objective="freeze accepted two-Case denominator",
            required_capabilities=["test_design"],
        )
    )
    control.register_task(
        Task(
            task_id=SCRIPT_TASK,
            mission_id=MISSION,
            node="SCRIPT_READINESS",
            task_type="PRODUCE",
            objective="prove every accepted Case has an executable script",
            required_capabilities=["script_generation"],
        )
    )
    control.register_task(
        Task(
            task_id=EXECUTION_TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute every accepted Case",
            required_capabilities=["test_execution"],
        )
    )

    source = Evidence(
        evidence_id="EVD-RC7-1-FANOUT-DESIGN-SOURCE",
        mission_id=MISSION,
        kind="TEST_DESIGN_SOURCE",
        source_ref="runtime://test-design-worker",
        content_ref="evidence://accepted-two-case-design",
        subject_refs=[DESIGN_TASK],
    )
    append_entity(truth, source, release_id=RELEASE, artifact_version=1)
    raw = _candidate_bytes([_case("TC-A"), _case("TC-B")])
    path = tmp_path / "accepted-test-design.json"
    path.write_bytes(raw)
    artifact = Artifact(
        artifact_id=DESIGN_ARTIFACT,
        mission_id=MISSION,
        artifact_type="TEST_DESIGN_MODEL",
        producer_task_id=DESIGN_TASK,
        content_ref="file://" + str(path.resolve()),
        evidence_refs=[source.evidence_id],
        content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
    )
    append_entity(truth, artifact, release_id=RELEASE, artifact_version=1)
    evaluation = Evaluation(
        evaluation_id="EVAL-RC7-1-FANOUT-DESIGN-PASS",
        mission_id=MISSION,
        node="TEST_DESIGN",
        artifact_refs=[DESIGN_ARTIFACT],
        result=EvaluationResult.PASS,
        evaluator_ref="independent-test-design-reviewer",
        dimensions={"semantic_coverage": "PASS"},
        evidence_refs=[source.evidence_id],
    )
    append_entity(truth, evaluation, release_id=RELEASE, artifact_version=1)
    design_row = truth.query("rc7_task", task_id=DESIGN_TASK)[0]
    design_task = control.scheduler.task(DESIGN_TASK)
    design_task.state = TaskStatus.PASS
    design_task.output_artifact_refs = [DESIGN_ARTIFACT]
    design_task.evaluation_id = evaluation.evaluation_id
    append_entity(
        truth,
        design_task,
        release_id=RELEASE,
        artifact_version=int(design_row["artifact_version"]) + 1,
    )
    persist_contract(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        script_task_id=SCRIPT_TASK,
        execution_task_id=EXECUTION_TASK,
    )
    return r1, truth, control


def _source(tc_id: str, symbol: str) -> str:
    return '''import json
import os
from pathlib import Path


def _emit(row):
    with open(os.environ["RC6_EXECUTION_MANIFEST"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\\n")


def %s():
    log = Path(os.environ["RC7_FANOUT_INVOCATION_LOG"])
    with log.open("a", encoding="utf-8") as handle:
        handle.write(%r + "\\n")
    _emit({"type":"tool_call","tool_id":"api-runtime","call_ref":"api-call://%s","evidence_ref":"api-evidence://%s"})
    _emit({"type":"actual_result","value":{"business_code":"OK","case_id":%r,"origin":"subprocess"}})
    assert True
''' % (symbol, tc_id, tc_id, tc_id, tc_id)


def _bundle(tmp_path: Path, truth: TruthRuntime, tc_id: str) -> VerifiedScriptExecutionBundle:
    contract = AcceptedTestDesignScriptContractCompiler().compile(
        truth,
        mission_id=MISSION,
        design_artifact_id=DESIGN_ARTIFACT,
        tc_id=tc_id,
    )
    symbol = "test_" + tc_id.lower().replace("-", "_")
    source_path = tmp_path / ("test_fanout_%s.py" % tc_id.lower())
    source_path.write_text(_source(tc_id, symbol), encoding="utf-8")
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()

    validation_evidence = Evidence(
        evidence_id="EVD-VALIDATION-" + tc_id,
        mission_id=MISSION,
        kind="SCRIPT_READINESS_VALIDATION_PROOF",
        source_ref="runtime://script-validator",
        content_ref="validation://" + tc_id,
        subject_refs=[tc_id, contract.spec.spec_id],
    )
    append_entity(truth, validation_evidence, release_id=RELEASE, artifact_version=1)
    step = ProcessStepResult(
        name="pytest_collect",
        command=("pytest", "--collect-only", str(source_path)),
        exit_code=0,
        stdout_ref="stdout://validation/" + tc_id,
        stderr_ref="stderr://validation/" + tc_id,
        duration_ms=1,
        passed=True,
    )
    script = ScriptArtifact(
        script_id="SCRIPT-" + tc_id,
        spec_id=contract.spec.spec_id,
        tc_id=tc_id,
        case_version=1,
        layer=contract.spec.layer,
        runner_type=contract.spec.runner_type,
        source_ref="file://" + str(source_path.resolve()),
        test_symbol=symbol,
        case_fingerprint=contract.spec.case_fingerprint,
        oracle_fingerprint=contract.spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=(validation_evidence.evidence_id,),
        revision=1,
    )
    validation = ScriptValidation(
        validation_id="VALIDATION-" + tc_id,
        script_id=script.script_id,
        runner_type=script.runner_type,
        test_symbol=script.test_symbol,
        steps=(step,),
        evidence_refs=(validation_evidence.evidence_id,),
        status="SCRIPT_READY",
    )
    record_script_ready(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        task_id=SCRIPT_TASK,
        artifact_id="ART-SCRIPT-" + tc_id,
        contract=contract,
        script=script,
        validation=validation,
        evidence_root=str(tmp_path / "execution-evidence"),
    )
    return VerifiedScriptExecutionBundle(
        upstream_mission_id=MISSION,
        upstream_task_id=SCRIPT_TASK,
        upstream_evaluation_id="EVAL-SCRIPT-" + tc_id,
        upstream_result_ref="runtime://script-result/" + tc_id,
        spec_ref="runtime://spec/" + tc_id,
        frozen_case=contract.frozen_case,
        spec=contract.spec,
        script=script,
        validation=validation,
        source_sha256=source_sha,
    )


def _broker() -> ToolCapabilityBroker:
    broker = ToolCapabilityBroker()
    broker.discover("api-runtime", "qualification://api-runtime")
    broker.mark_executable("api-runtime", "executable://api-runtime")
    broker.register("api-runtime", "registration://api-runtime")
    broker.record_probe(
        "api-runtime",
        success=True,
        tool_call_ref="probe://api-runtime",
        evidence_ref="probe-evidence://api-runtime",
    )
    broker.mark_target_ready("api-runtime", TARGET, "target-ready://api-runtime")
    return broker


def _oracle(_oracle_snapshot, actual, _context):
    tc_id = actual.get("case_id")
    return {
        "passed": actual.get("business_code") == "OK",
        "assertion_ref": "assertion://%s/business-code-ok" % tc_id,
        "evidence_refs": ["oracle-evidence://%s/business-code-ok" % tc_id],
        "details": {"expected": "OK", "actual": actual.get("business_code")},
    }


def _prepared(raw: dict) -> PreparedAttempt:
    return PreparedAttempt(
        status=str(raw["status"]),
        attempt_id=str(raw["attempt_id"]),
        tc_id=str(raw["tc_id"]),
        case_version=int(raw["case_version"]),
        target_id=str(raw["target_id"]),
        precondition_evidence=tuple(raw.get("precondition_evidence") or ()),
        initial_state_bindings=dict(raw.get("initial_state_bindings") or {}),
        input_data_bindings=dict(raw.get("input_data_bindings") or {}),
        binding_evidence=tuple(raw.get("binding_evidence") or ()),
        cleanup_policy=dict(raw.get("cleanup_policy") or {}),
        oracle_snapshot=dict(raw.get("oracle_snapshot") or {}),
    )


def _activate_prepare_execute(
    *,
    tmp_path: Path,
    truth: TruthRuntime,
    control: ClosedLoopControlPlane,
    service: ClosedLoopRuntimeExecutionService,
    task_id: str,
    bundle: VerifiedScriptExecutionBundle,
    attempt_id: str,
    invocation_log: Path,
):
    authority = RC7AuthorityRuntime(b"rc7-1-fanout-production-signing-key")
    broker = _broker()
    active = service.activate_task(
        control,
        task_id,
        bundle=bundle,
        target_id=TARGET,
        authority=authority,
        tool_broker=broker,
    )
    preparation = CasePreparationService(truth, tmp_path / "case-state")
    first = preparation.prepare(
        mission_id=MISSION,
        task_id=task_id,
        worker_id=active.runtime_worker_id,
        case=bundle.frozen_case,
        attempt_id=attempt_id,
        target_id=TARGET,
    )
    assert first["status"] == "PREPARED"
    assert first["replayed"] is False
    replay = CasePreparationService(truth, tmp_path / "case-state").prepare(
        mission_id=MISSION,
        task_id=task_id,
        worker_id=active.runtime_worker_id,
        case=bundle.frozen_case,
        attempt_id=attempt_id,
        target_id=TARGET,
    )
    assert replay["status"] == "PREPARED"
    assert replay["replayed"] is True
    assert replay["evidence_id"] == first["evidence_id"]

    return service.execute_active_task(
        control,
        task_id,
        bundle=bundle,
        prepared=_prepared(first["prepared_attempt"]),
        active=active,
        authority=authority,
        tool_broker=broker,
        oracle_evaluator=_oracle,
        cwd=str(tmp_path),
        env={
            "RC7_FANOUT_INVOCATION_LOG": str(invocation_log),
            "RC7_FANOUT_TC_ID": bundle.spec.tc_id,
        },
    )


def _pending_repair_for(truth: TruthRuntime, tc_id: str) -> str:
    for row in truth.query("rc7_task", mission_id=MISSION):
        if row.get("node") != "EXECUTION" or row.get("task_type") != "REPAIR":
            continue
        for gap_id in list(row.get("gap_refs") or []):
            gaps = truth.query("rc7_gap", gap_id=str(gap_id))
            if gaps and gaps[0].get("category") == "EXECUTION_CASE_PENDING" and tc_id in list(gaps[0].get("subject_refs") or []):
                return str(row["task_id"])
    raise AssertionError("missing EXECUTION repair task for %s" % tc_id)


def test_real_two_case_fanout_survives_restart_and_never_replays_parent_runner(tmp_path: Path) -> None:
    r1, truth, control = _setup(tmp_path)
    bundle_a = _bundle(tmp_path, truth, "TC-A")
    bundle_b = _bundle(tmp_path, truth, "TC-B")
    inventory = AcceptedCaseInventoryReader().load(truth, MISSION)
    assert inventory.tc_ids == ("TC-A", "TC-B")

    service = ClosedLoopRuntimeExecutionService(
        evidence_root=str(tmp_path / "execution-evidence"),
        state_root=str(tmp_path / "case-state"),
        timeout_seconds=20,
    )
    invocation_log = tmp_path / "business-invocations.log"

    first = _activate_prepare_execute(
        tmp_path=tmp_path,
        truth=truth,
        control=control,
        service=service,
        task_id=EXECUTION_TASK,
        bundle=bundle_a,
        attempt_id="ATT-FANOUT-A",
        invocation_log=invocation_log,
    )
    assert first.execution_record.status == "PASS"
    assert first.task_state == "REPAIR_REQUIRED"
    assert first.loop_result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert first.loop_result.evaluation.dimensions["case_execution_fanout"] == "INCOMPLETE"
    assert first.loop_result.evaluation.dimensions["missing_tc_ids"] == ["TC-B"]
    assert first.fanout_finalize_status == "NOT_READY"
    barrier = check_execution_barrier(truth, MISSION)
    assert barrier.status == "INCOMPLETE"
    assert barrier.pass_ready_tc_ids == ("TC-A",)
    assert barrier.missing_tc_ids == ("TC-B",)
    assert invocation_log.read_text(encoding="utf-8").splitlines() == ["TC-A"]

    # Simulate a fresh process/session using only durable R1 + evidence/state.
    restarted_truth = TruthRuntime(r1)
    restarted_control = ClosedLoopControlPlane(restarted_truth, RELEASE, MISSION)
    restarted_service = ClosedLoopRuntimeExecutionService(
        evidence_root=str(tmp_path / "execution-evidence"),
        state_root=str(tmp_path / "case-state"),
        timeout_seconds=20,
    )
    recovered_barrier = check_execution_barrier(restarted_truth, MISSION)
    assert recovered_barrier.pass_ready_tc_ids == ("TC-A",)
    repair_b = _pending_repair_for(restarted_truth, "TC-B")
    assert restarted_control.scheduler.task(repair_b).state == TaskStatus.READY

    second = _activate_prepare_execute(
        tmp_path=tmp_path,
        truth=restarted_truth,
        control=restarted_control,
        service=restarted_service,
        task_id=repair_b,
        bundle=bundle_b,
        attempt_id="ATT-FANOUT-B",
        invocation_log=invocation_log,
    )
    assert second.execution_record.status == "PASS"
    assert second.task_state == "PASS"
    assert second.loop_result.evaluation.result == EvaluationResult.PASS
    assert second.loop_result.evaluation.dimensions["case_execution_fanout"] == "CASE_TERMINAL"
    assert second.fanout_finalize_status == "FINALIZED"

    complete = check_execution_barrier(restarted_truth, MISSION)
    assert complete.status == "PASS"
    assert complete.required_tc_ids == ("TC-A", "TC-B")
    assert complete.pass_ready_tc_ids == ("TC-A", "TC-B")
    assert len(complete.receipt_ids) == 2
    assert restarted_control.scheduler.task(EXECUTION_TASK).state == TaskStatus.PASS

    # Exactly the two accepted Cases executed. Parent aggregation itself never
    # launched a third subprocess/business action.
    assert invocation_log.read_text(encoding="utf-8").splitlines() == ["TC-A", "TC-B"]
    aggregate = [
        row for row in restarted_truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == "CASE_EXECUTION_AGGREGATE"
    ]
    assert len(aggregate) == 1
    aggregate_payload = json.loads(
        Path(str(aggregate[0]["content_ref"])[len("file://"):]).read_text(encoding="utf-8")
    )
    assert aggregate_payload["terminal_receipt_ids"] == list(complete.receipt_ids)
    assert aggregate_payload["receipt_only_aggregate"] is True
    assert aggregate_payload["runner_reexecuted"] is False
    assert aggregate_payload["business_side_effect_replayed"] is False

    again = restarted_service.finalize_case_fanout(restarted_control)
    assert again.status == "ALREADY_FINALIZED"
    assert invocation_log.read_text(encoding="utf-8").splitlines() == ["TC-A", "TC-B"]

    # A restart must not turn canonical EXECUTION READY again and replay TC-A.
    with pytest.raises(RuntimeExecutionError, match="CASE_FANOUT_CANONICAL_EXECUTION_ALREADY_COMPLETE"):
        restarted_service.activate_task(
            restarted_control,
            EXECUTION_TASK,
            bundle=bundle_a,
            target_id=TARGET,
            authority=RC7AuthorityRuntime(b"rc7-1-fanout-production-signing-key"),
            tool_broker=_broker(),
        )
    assert invocation_log.read_text(encoding="utf-8").splitlines() == ["TC-A", "TC-B"]

    # Canonical R1 alone reconstructs Case receipts and aggregate Evidence.
    final_truth = TruthRuntime(r1)
    final_barrier = check_execution_barrier(final_truth, MISSION)
    assert final_barrier.status == "PASS"
    assert final_barrier.pass_ready_tc_ids == ("TC-A", "TC-B")
    assert len([
        row for row in final_truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == "CASE_EXECUTION_TERMINAL"
    ]) == 2
    assert len([
        row for row in final_truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == "CASE_EXECUTION_AGGREGATE"
    ]) == 1
