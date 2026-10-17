from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from rc6_runtime.automation import ProcessStepResult, ScriptArtifact, ScriptValidation
from rc6_runtime.execution import ExecutionRecord
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.case_fanout_conformance import (
    check_script_barrier,
    record_script_ready,
)
from rc7_runtime.case_runtime import PREPARED_ATTEMPT_KIND
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.execution_chain_evidence import record_chain_call
from rc7_runtime.execution_fanout_conformance import (
    check_execution_barrier,
    deferred_product_defect_gaps,
    record_execution_terminal,
)
from rc7_runtime.execution_fanout_evaluator import RuntimeCaseFanoutExecutionEvaluator
from rc7_runtime.execution_loop import ExecutionLoopResult
from rc7_runtime.execution_recovery_conformance import ExecutionRecoveryConformanceChecker
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Gap,
    GapSeverity,
    TaskStatus,
)
from rc7_runtime.node_tool_conformance import record_successful_call
from rc7_runtime.script_contract import AcceptedTestDesignScriptContractCompiler
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-THREE-CASE-QUAL"
RELEASE = "REL-THREE-CASE-QUAL"
DESIGN_ARTIFACT = "ART-TD-THREE-CASE-QUAL"
TARGET = "PFC-SIT-THREE-CASE"
WORKER = "RUNTIME-EXECUTION-THREE-CASE"
TC_PASS = "TC-PASS"
TC_RETRY = "TC-RETRY"
TC_DEFECT = "TC-DEFECT"


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _write(path: Path, payload: object) -> str:
    raw = _canonical(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _case(tc_id: str) -> dict:
    return {
        "tc_id": tc_id,
        "case_version": 1,
        "status": "FROZEN",
        "release_id": RELEASE,
        "requirement_id": "REQ-THREE-CASE",
        "sst_id": "SST-THREE-CASE",
        "layer": "L2",
        "preconditions": [],
        "test_data": {
            "strategy": "REUSE_EXISTING",
            "required_capabilities": [],
            "cleanup_policy": {"mode": "NONE", "required": False},
        },
        "cleanup_policy": {"mode": "NONE", "required": False},
        "steps": [{"order": 1, "action": "query deterministic bank fixture"}],
        "expected": "business_code=OK",
        "oracle": {
            "checks": [
                {
                    "id": "CHK-%s" % tc_id,
                    "type": "BUSINESS_RULE",
                    "actual_path": "business_code",
                    "operator": "EQ",
                    "expected": "OK",
                }
            ]
        },
        "evidence_requirements": ["runner-output", "oracle-runtime"],
        "target_requirements": ["REQ-THREE-CASE"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://%s" % tc_id.lower()],
        "runner_type": "PYTEST",
        "coverage_links": [],
    }


def _candidate_bytes(task_id: str) -> bytes:
    envelope = {
        "task_id": task_id,
        "artifact": {
            "artifact_id": DESIGN_ARTIFACT,
            "artifact_type": "TEST_DESIGN_MODEL",
            "content_ref": "runtime://accepted-test-design",
            "parent_refs": [],
            "evidence_refs": ["EVD-TD-THREE-CASE-SOURCE"],
        },
        "semantic_payload": {
            "cases": [_case(TC_PASS), _case(TC_RETRY), _case(TC_DEFECT)],
            "obligations": [{"obligation_id": "OB-THREE-CASE"}],
        },
        "evidence": [],
    }
    return (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _setup_mission(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "7" * 40)
    r1 = tmp_path / "state" / "r1" / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id=MISSION,
        release_id=RELEASE,
        goal="qualify PASS, recovered retry and PRODUCT_DEFECT in one accepted Case denominator",
        graph_version="v2",
    )
    truth = TruthRuntime(r1)
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    design_row = next(
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "TEST_DESIGN" and row.get("task_type") == "PRODUCE"
    )
    design_task_id = str(design_row["task_id"])
    source = Evidence(
        evidence_id="EVD-TD-THREE-CASE-SOURCE",
        mission_id=MISSION,
        kind="TEST_DESIGN_SOURCE",
        source_ref="dsh://test-design-worker",
        content_ref="evidence://three-case-design-source",
        subject_refs=[design_task_id],
    )
    append_entity(truth, source, release_id=RELEASE, artifact_version=1)
    raw = _candidate_bytes(design_task_id)
    design_path = tmp_path / "accepted-three-case-design.json"
    design_path.write_bytes(raw)
    append_entity(
        truth,
        Artifact(
            artifact_id=DESIGN_ARTIFACT,
            mission_id=MISSION,
            artifact_type="TEST_DESIGN_MODEL",
            producer_task_id=design_task_id,
            content_ref="file://" + str(design_path.resolve()),
            evidence_refs=[source.evidence_id],
            content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
        ),
        release_id=RELEASE,
        artifact_version=1,
    )
    evaluation = Evaluation(
        evaluation_id="EVAL-TD-THREE-CASE-PASS",
        mission_id=MISSION,
        node="TEST_DESIGN",
        artifact_refs=[DESIGN_ARTIFACT],
        result=EvaluationResult.PASS,
        evaluator_ref="independent-test-design-reviewer",
        dimensions={"semantic_coverage": "PASS"},
        evidence_refs=[source.evidence_id],
    )
    append_entity(truth, evaluation, release_id=RELEASE, artifact_version=1)
    design_task = control.scheduler.task(design_task_id)
    design_task.state = TaskStatus.PASS
    design_task.output_artifact_refs = [DESIGN_ARTIFACT]
    design_task.evaluation_id = evaluation.evaluation_id
    append_entity(
        truth,
        design_task,
        release_id=RELEASE,
        artifact_version=int(design_row["artifact_version"]) + 1,
    )
    script_task_id = str(next(
        row["task_id"] for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "SCRIPT_READINESS" and row.get("task_type") == "PRODUCE"
    ))
    execution_row = next(
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "EXECUTION" and row.get("task_type") == "PRODUCE"
    )
    execution_task_id = str(execution_row["task_id"])
    return r1, truth, control, script_task_id, execution_task_id, execution_row


def _script_receipt(tmp_path: Path, truth: TruthRuntime, script_task_id: str, tc_id: str) -> str:
    contract = AcceptedTestDesignScriptContractCompiler().compile(
        truth,
        mission_id=MISSION,
        design_artifact_id=DESIGN_ARTIFACT,
        tc_id=tc_id,
    )
    validation_evidence = Evidence(
        evidence_id="EVD-VALIDATION-" + tc_id,
        mission_id=MISSION,
        kind="SCRIPT_READINESS_VALIDATION_PROOF",
        source_ref="runtime://script-validator",
        content_ref="validation://" + tc_id,
        subject_refs=[tc_id],
    )
    append_entity(truth, validation_evidence, release_id=RELEASE, artifact_version=1)
    script_path = tmp_path / ("test_%s.py" % tc_id.lower().replace("-", "_"))
    script_path.write_text("def test_case():\n    assert True\n", encoding="utf-8")
    script = ScriptArtifact(
        script_id="SCRIPT-" + tc_id,
        spec_id=contract.spec.spec_id,
        tc_id=tc_id,
        case_version=1,
        layer=contract.spec.layer,
        runner_type=contract.spec.runner_type,
        source_ref="file://" + str(script_path.resolve()),
        test_symbol="test_case",
        case_fingerprint=contract.spec.case_fingerprint,
        oracle_fingerprint=contract.spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=(validation_evidence.evidence_id,),
        revision=1,
    )
    step = ProcessStepResult(
        name="pytest_collect",
        command=("pytest", "--collect-only"),
        exit_code=0,
        stdout_ref="stdout://" + tc_id,
        stderr_ref="stderr://" + tc_id,
        duration_ms=1,
        passed=True,
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
    return record_script_ready(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        task_id=script_task_id,
        artifact_id="ART-SCRIPT-" + tc_id,
        contract=contract,
        script=script,
        validation=validation,
        evidence_root=str(tmp_path / "evidence"),
    )


def _activate_execution(truth: TruthRuntime, control: ClosedLoopControlPlane, task_id: str, row: dict) -> None:
    task = control.scheduler.task(task_id)
    task.state = TaskStatus.RUNNING
    task.lease_owner = WORKER
    append_entity(
        truth,
        task,
        release_id=RELEASE,
        artifact_version=int(row["artifact_version"]) + 1,
    )


def _prepared(tmp_path: Path, truth: TruthRuntime, task_id: str, attempt_id: str, tc_id: str) -> str:
    payload = {
        "status": "PREPARED",
        "attempt_id": attempt_id,
        "tc_id": tc_id,
        "case_version": 1,
        "target_id": TARGET,
    }
    relative = Path("case-runtime") / MISSION / attempt_id / "prepared-attempt.json"
    digest = _write(tmp_path / "state" / relative, payload)
    evidence = Evidence(
        evidence_id="EVD-PREP-" + attempt_id,
        mission_id=MISSION,
        kind=PREPARED_ATTEMPT_KIND,
        source_ref="runtime://case-runtime/preparation",
        content_ref="state://" + relative.as_posix(),
        subject_refs=[task_id, WORKER, attempt_id, tc_id, TARGET],
        content_hash=digest,
    )
    append_entity(truth, evidence, release_id=RELEASE, artifact_version=1)
    return evidence.evidence_id


def _record_and_artifact(
    tmp_path: Path,
    truth: TruthRuntime,
    task_id: str,
    *,
    attempt_id: str,
    tc_id: str,
    status: str,
    assertion_passed: bool,
):
    record = ExecutionRecord(
        attempt_id=attempt_id,
        tc_id=tc_id,
        case_version=1,
        target_id=TARGET,
        layer="L2",
        worker_id=WORKER,
        lease_id="LEASE-" + attempt_id,
        status=status,
        integrity_passed=True,
        actual_result={"business_code": "OK" if assertion_passed else "BAD"},
        tool_call_refs=("tool://runner/%s" % attempt_id,),
        evidence_refs=("evidence://runner/%s" % attempt_id,),
        assertion_ref="ASSERT-" + attempt_id,
        assertion_passed=assertion_passed,
        reason=None if assertion_passed else "ORACLE_ASSERTION_FAILED",
    )
    record_path = tmp_path / "execution-records" / (attempt_id + ".json")
    digest = _write(record_path, {"record": asdict(record)})
    evidence = Evidence(
        evidence_id="EVD-EXEC-RECORD-" + attempt_id,
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://formal-execution",
        content_ref="file://" + str(record_path.resolve()),
        subject_refs=[task_id, attempt_id, tc_id],
        content_hash="sha256:" + digest,
    )
    append_entity(truth, evidence, release_id=RELEASE, artifact_version=1)
    artifact = Artifact(
        artifact_id="ART-EXEC-" + attempt_id,
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=task_id,
        content_ref="file://" + str(record_path.resolve()),
        evidence_refs=[evidence.evidence_id],
        content_hash="sha256:" + digest,
    )
    append_entity(truth, artifact, release_id=RELEASE, artifact_version=1)
    return record, evidence.evidence_id, artifact.artifact_id


def _loop(record: ExecutionRecord, artifact_id: str, *, product_defect: bool = False) -> ExecutionLoopResult:
    gaps = ()
    recovery = None
    test_result = "PASS"
    if product_defect:
        gap = Gap(
            gap_id="GAP-PRODUCT-" + record.tc_id,
            mission_id=MISSION,
            source_node="EXECUTION",
            category="PRODUCT_DEFECT",
            severity=GapSeverity.HIGH,
            target_node="DEFECT",
            description="trusted deterministic product mismatch for %s" % record.tc_id,
            subject_refs=[record.attempt_id, record.tc_id],
            evidence_refs=["EVD-ORACLE-FAIL-" + record.tc_id],
            acceptance_criteria=["reproduce and independently review %s" % record.tc_id],
        )
        gaps = (gap,)
        recovery = "PRODUCT_DEFECT"
        test_result = "FAIL"
    evaluation = Evaluation(
        evaluation_id="EVAL-EXEC-" + record.attempt_id,
        mission_id=MISSION,
        node="EXECUTION",
        artifact_refs=[artifact_id],
        result=EvaluationResult.PASS,
        evaluator_ref="rc7-runtime-owned-execution-gate",
        dimensions={
            "attempt_id": record.attempt_id,
            "failure_class": "PRODUCT" if product_defect else None,
            "test_result": test_result,
        },
        gap_refs=[gap.gap_id for gap in gaps],
        evidence_refs=["EVD-ORACLE-" + record.attempt_id],
    )
    return ExecutionLoopResult(
        evaluation=evaluation,
        gaps=gaps,
        test_result=test_result,
        conclusive=True,
        recovery_action=recovery,
    )


def _attempt_truth(truth: TruthRuntime, attempt_id: str, tc_id: str, status: str) -> None:
    truth.append_atomic(
        "EXECUTION_ATTEMPT_UPSERTED",
        {
            "attempt_id": attempt_id,
            "release_id": RELEASE,
            "requirement_id": "REQ-THREE-CASE",
            "tc_id": tc_id,
            "case_version": 1,
            "target_id": TARGET,
            "layer": "L2",
            "status": status,
            "actual_result": {"status": status},
            "tool_call_refs": ["tool://runner/%s" % attempt_id],
            "evidence_refs": ["evidence://runner/%s" % attempt_id],
        },
    )


def _convergence(truth: TruthRuntime, attempt_id: str, status: str) -> None:
    truth.append_atomic(
        "EXECUTION_CONVERGENCE_UPSERTED",
        {
            "convergence_id": "CONV-" + attempt_id,
            "release_id": RELEASE,
            "attempt_id": attempt_id,
            "status": status,
            "reason": "three-case qualification",
            "evidence_refs": ["evidence://convergence/%s" % attempt_id],
        },
    )


def _diagnosis(truth: TruthRuntime, attempt_id: str, diagnosis_id: str, failure_class: str) -> None:
    truth.append_atomic(
        "FAILURE_DIAGNOSIS_UPSERTED",
        {
            "diagnosis_id": diagnosis_id,
            "release_id": RELEASE,
            "attempt_id": attempt_id,
            "failure_class": failure_class,
            "evidence_refs": ["evidence://diagnosis/%s" % attempt_id],
            "classifier_ref": "classifier://runtime",
            "rationale": "deterministic qualification diagnosis",
            "failure_signature_id": "SIG-" + attempt_id,
            "root_cause_candidate_id": None,
            "cat_required": False,
            "cat_queried": False,
            "cat_query_evidence_id": None,
        },
    )


def test_three_case_same_mission_pass_retry_and_defect_are_all_required(tmp_path: Path, monkeypatch) -> None:
    r1, truth, control, script_task_id, execution_task_id, execution_row = _setup_mission(tmp_path, monkeypatch)
    script_receipts = {
        tc_id: _script_receipt(tmp_path, truth, script_task_id, tc_id)
        for tc_id in (TC_PASS, TC_RETRY, TC_DEFECT)
    }
    scripts = check_script_barrier(truth, MISSION)
    assert scripts.status == "PASS"
    assert scripts.required_tc_ids == tuple(sorted((TC_PASS, TC_RETRY, TC_DEFECT)))

    _activate_execution(truth, control, execution_task_id, execution_row)
    record_successful_call(
        truth,
        mission_id=MISSION,
        task_id=execution_task_id,
        worker_id=WORKER,
        tool_name="runner_execute",
        result={"status": "PASS", "qualification": "three-case"},
    )
    record_successful_call(
        truth,
        mission_id=MISSION,
        task_id=execution_task_id,
        worker_id=WORKER,
        tool_name="execution_convergence",
        result={"status": "PASS", "qualification": "three-case"},
    )

    # Case A: direct PASS earns one terminal credit, never the entire denominator.
    pass_attempt = "ATT-PASS"
    pass_prepared = _prepared(tmp_path, truth, execution_task_id, pass_attempt, TC_PASS)
    _attempt_truth(truth, pass_attempt, TC_PASS, "PASS")
    _convergence(truth, pass_attempt, "PASS")
    pass_record, pass_record_evidence, pass_artifact = _record_and_artifact(
        tmp_path, truth, execution_task_id,
        attempt_id=pass_attempt, tc_id=TC_PASS, status="PASS", assertion_passed=True,
    )
    pass_receipt = record_execution_terminal(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        task_id=execution_task_id,
        script_receipt_id=script_receipts[TC_PASS],
        prepared_evidence_id=pass_prepared,
        record_evidence_id=pass_record_evidence,
        record=pass_record,
        loop_result=_loop(pass_record, pass_artifact),
        state_root=str(tmp_path / "state"),
        evidence_root=str(tmp_path / "evidence"),
    )
    after_pass = check_execution_barrier(truth, MISSION)
    assert after_pass.status == "INCOMPLETE"
    assert set(after_pass.missing_tc_ids) == {TC_RETRY, TC_DEFECT}

    # Case B: first failed attempt must carry diagnosis/decision/recovery truth;
    # only the successor PASS receives Case terminal credit.
    retry1 = "ATT-RETRY-1"
    retry2 = "ATT-RETRY-2"
    _prepared(tmp_path, truth, execution_task_id, retry1, TC_RETRY)
    _prepared(tmp_path, truth, execution_task_id, retry2, TC_RETRY)
    _attempt_truth(truth, retry1, TC_RETRY, "FAIL")
    _diagnosis(truth, retry1, "DIAG-RETRY", "DATA")
    truth.append_atomic(
        "RECOVERY_DECISION_UPSERTED",
        {
            "decision_id": "RDEC-RETRY",
            "release_id": RELEASE,
            "diagnosis_id": "DIAG-RETRY",
            "attempt_id": retry1,
            "action": "RESEARCH_OR_REBUILD_DATA",
            "terminal": False,
            "next_attempt_id": retry2,
            "retry_allowed": False,
            "reprepare_allowed": True,
            "reason": "rebuild deterministic data then rerun",
        },
    )
    truth.append_atomic(
        "RECOVERY_ACTION_UPSERTED",
        {
            "recovery_action_id": "RACT-RETRY",
            "release_id": RELEASE,
            "action": "RESEARCH_OR_REBUILD_DATA",
            "prior_attempt_id": retry1,
            "next_attempt_id": retry2,
            "status": "PASS",
            "evidence_refs": ["evidence://recovery/retry"],
            "output_refs": ["data://rebuilt/retry"],
            "verified": True,
            "terminal_status": None,
        },
    )
    _convergence(truth, retry1, "RECOVERY_ALLOWED")
    record_chain_call(
        truth,
        mission_id=MISSION,
        task_id=execution_task_id,
        worker_id="WORKER-DIAGNOSTIC",
        tool_name="failure_diagnose",
        attempt_id=retry1,
        result={"status": "PASS", "failure_class": "DATA"},
    )
    record_chain_call(
        truth,
        mission_id=MISSION,
        task_id=execution_task_id,
        worker_id="WORKER-RECOVERY-PLANNER",
        tool_name="recovery_decide",
        attempt_id=retry1,
        result={"status": "PASS", "action": "RESEARCH_OR_REBUILD_DATA"},
    )
    record_chain_call(
        truth,
        mission_id=MISSION,
        task_id=execution_task_id,
        worker_id="WORKER-RECOVERY-EXECUTOR",
        tool_name="recovery_execute",
        attempt_id=retry1,
        result={"status": "PASS", "next_attempt_id": retry2},
    )
    _attempt_truth(truth, retry2, TC_RETRY, "PASS")
    _convergence(truth, retry2, "PASS")
    retry_record, retry_record_evidence, retry_artifact = _record_and_artifact(
        tmp_path, truth, execution_task_id,
        attempt_id=retry2, tc_id=TC_RETRY, status="PASS", assertion_passed=True,
    )
    retry_receipt = record_execution_terminal(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        task_id=execution_task_id,
        script_receipt_id=script_receipts[TC_RETRY],
        prepared_evidence_id="EVD-PREP-" + retry2,
        record_evidence_id=retry_record_evidence,
        record=retry_record,
        loop_result=_loop(retry_record, retry_artifact),
        state_root=str(tmp_path / "state"),
        evidence_root=str(tmp_path / "evidence"),
    )
    after_retry = check_execution_barrier(truth, MISSION)
    assert after_retry.status == "INCOMPLETE"
    assert after_retry.pass_ready_tc_ids == tuple(sorted((TC_PASS, TC_RETRY)))
    assert after_retry.missing_tc_ids == (TC_DEFECT,)

    # Case C: trusted Oracle FAIL + terminal PRODUCT decision creates one deferred
    # product-defect handoff, while still satisfying this Case's execution credit.
    defect_attempt = "ATT-DEFECT"
    defect_prepared = _prepared(tmp_path, truth, execution_task_id, defect_attempt, TC_DEFECT)
    _attempt_truth(truth, defect_attempt, TC_DEFECT, "FAIL")
    _diagnosis(truth, defect_attempt, "DIAG-DEFECT", "PRODUCT")
    truth.append_atomic(
        "RECOVERY_DECISION_UPSERTED",
        {
            "decision_id": "RDEC-DEFECT",
            "release_id": RELEASE,
            "diagnosis_id": "DIAG-DEFECT",
            "attempt_id": defect_attempt,
            "action": "PRODUCT_DEFECT",
            "terminal": True,
            "next_attempt_id": None,
            "retry_allowed": False,
            "reprepare_allowed": False,
            "reason": "trusted deterministic product mismatch",
        },
    )
    _convergence(truth, defect_attempt, "PRODUCT_DEFECT_CONFIRMED")
    record_chain_call(
        truth,
        mission_id=MISSION,
        task_id=execution_task_id,
        worker_id="WORKER-DIAGNOSTIC",
        tool_name="failure_diagnose",
        attempt_id=defect_attempt,
        result={"status": "PASS", "failure_class": "PRODUCT"},
    )
    record_chain_call(
        truth,
        mission_id=MISSION,
        task_id=execution_task_id,
        worker_id="WORKER-RECOVERY-PLANNER",
        tool_name="recovery_decide",
        attempt_id=defect_attempt,
        result={"status": "PASS", "action": "PRODUCT_DEFECT"},
    )
    defect_record, defect_record_evidence, defect_artifact = _record_and_artifact(
        tmp_path, truth, execution_task_id,
        attempt_id=defect_attempt, tc_id=TC_DEFECT, status="FAIL", assertion_passed=False,
    )
    defect_loop = _loop(defect_record, defect_artifact, product_defect=True)
    defect_receipt = record_execution_terminal(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        task_id=execution_task_id,
        script_receipt_id=script_receipts[TC_DEFECT],
        prepared_evidence_id=defect_prepared,
        record_evidence_id=defect_record_evidence,
        record=defect_record,
        loop_result=defect_loop,
        state_root=str(tmp_path / "state"),
        evidence_root=str(tmp_path / "evidence"),
    )

    complete = check_execution_barrier(truth, MISSION)
    assert complete.status == "PASS"
    assert complete.required_tc_ids == tuple(sorted((TC_PASS, TC_RETRY, TC_DEFECT)))
    assert complete.pass_ready_tc_ids == complete.required_tc_ids
    assert set(complete.receipt_ids) == {pass_receipt, retry_receipt, defect_receipt}

    defects = deferred_product_defect_gaps(
        truth,
        mission_id=MISSION,
        receipt_ids=complete.receipt_ids,
    )
    assert len(defects) == 1
    assert defects[0].gap_id == "GAP-PRODUCT-" + TC_DEFECT
    assert defect_receipt in defects[0].evidence_refs

    aggregate = RuntimeCaseFanoutExecutionEvaluator._aggregate_result(defect_loop, complete, defects)
    assert aggregate.evaluation.result == EvaluationResult.PASS
    assert aggregate.test_result == "FAIL"
    assert aggregate.recovery_action == "PRODUCT_DEFECT"
    assert aggregate.evaluation.dimensions["required_case_count"] == 3
    assert aggregate.evaluation.dimensions["pass_ready_case_count"] == 3
    assert aggregate.evaluation.dimensions["product_defect_count"] == 1
    assert set(complete.receipt_ids).issubset(set(aggregate.evaluation.evidence_refs))

    recovery = ExecutionRecoveryConformanceChecker(truth).check_task(MISSION, execution_task_id)
    assert recovery.status == "PASS"
    assert set(recovery.attempt_ids) == {pass_attempt, retry1, retry2, defect_attempt}
    assert "failure_diagnose" in recovery.observed_tools
    assert "recovery_execute" in recovery.observed_tools

    # Session/process recreation must not lose denominator, retry lineage or the
    # deferred defect handoff: R1 alone is sufficient to reconstruct all three.
    resumed_truth = TruthRuntime(r1)
    resumed_barrier = check_execution_barrier(resumed_truth, MISSION)
    resumed_defects = deferred_product_defect_gaps(
        resumed_truth,
        mission_id=MISSION,
        receipt_ids=resumed_barrier.receipt_ids,
    )
    resumed_recovery = ExecutionRecoveryConformanceChecker(resumed_truth).check_task(MISSION, execution_task_id)
    assert resumed_barrier.status == "PASS"
    assert set(resumed_barrier.receipt_ids) == {pass_receipt, retry_receipt, defect_receipt}
    assert [gap.gap_id for gap in resumed_defects] == ["GAP-PRODUCT-" + TC_DEFECT]
    assert resumed_recovery.status == "PASS"
