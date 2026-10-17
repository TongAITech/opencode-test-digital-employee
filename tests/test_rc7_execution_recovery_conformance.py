from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.attempt_cat import ATTEMPT_CAT_QUERY_KIND
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.case_runtime import PREPARED_ATTEMPT_KIND
from rc7_runtime.closed_loop_control import ClosedLoopControlError, ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.execution_chain_evidence import record_chain_call
from rc7_runtime.execution_recovery_conformance import (
    ExecutionRecoveryConformanceChecker,
    contract_enabled as recovery_contract_enabled,
    persist_contract as persist_recovery_contract,
)
from rc7_runtime.models import Evidence, Evaluation, EvaluationResult, Mission, Task
from rc7_runtime.node_tool_conformance import persist_contract as persist_node_tool_contract, record_successful_call
from rc7_runtime.truth_overlay import append_entity


RELEASE = "REL-EXEC-RECOVERY"
MISSION = "MISSION-EXEC-RECOVERY"
TASK = "TASK-EXECUTION"
WORKER = "WORKER-EXECUTION-001"


def _active_execution(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id=RELEASE, goal="prove real execution recovery"),
    )
    control.register_task(
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="PRODUCE",
            objective="Execute real test attempts",
            required_capabilities=["test_execution"],
        )
    )
    leased = control.lease_next(worker_ref=WORKER, capabilities=["test_execution"])
    assert leased is not None and leased.task_id == TASK
    control.start(TASK, worker_ref=WORKER)
    persist_node_tool_contract(truth, mission_id=MISSION, release_id=RELEASE, task_ids=[TASK])
    persist_recovery_contract(truth, mission_id=MISSION, release_id=RELEASE, execution_task_id=TASK)
    return truth, control


def _prepare(truth: TruthRuntime, attempt_id: str, tc_id: str = "TC-1") -> None:
    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-PREP-" + attempt_id,
            mission_id=MISSION,
            kind=PREPARED_ATTEMPT_KIND,
            source_ref="runtime://case-runtime/preparation",
            content_ref="state://case-runtime/%s/prepared-attempt.json" % attempt_id,
            subject_refs=[TASK, WORKER, attempt_id, tc_id, "TARGET-1"],
            content_hash="a" * 64,
        ),
        release_id=RELEASE,
        artifact_version=1,
    )


def _attempt(truth: TruthRuntime, attempt_id: str, status: str, tc_id: str = "TC-1", layer: str = "L2") -> None:
    truth.append_atomic(
        "EXECUTION_ATTEMPT_UPSERTED",
        {
            "attempt_id": attempt_id,
            "release_id": RELEASE,
            "requirement_id": "REQ-1",
            "tc_id": tc_id,
            "case_version": 1,
            "target_id": "TARGET-1",
            "layer": layer,
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
            "reason": "test convergence",
            "evidence_refs": ["evidence://conv/%s" % attempt_id],
        },
    )


def _tool(truth: TruthRuntime, name: str, marker: str) -> None:
    record_successful_call(
        truth,
        mission_id=MISSION,
        task_id=TASK,
        worker_id=WORKER,
        tool_name=name,
        result={"tool": name, "marker": marker, "status": "PASS"},
    )


def _chain(truth: TruthRuntime, attempt_id: str, name: str, worker: str) -> None:
    record_chain_call(
        truth,
        mission_id=MISSION,
        task_id=TASK,
        worker_id=worker,
        tool_name=name,
        attempt_id=attempt_id,
        result={"tool": name, "attempt_id": attempt_id, "status": "PASS"},
    )


def test_new_bank_v2_mission_persists_execution_recovery_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "d" * 40)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    result = start_or_resume(
        r1_path=str(r1),
        mission_id="BANK-EXEC-RECOVERY",
        release_id="REL-BANK",
        goal="bank execution recovery",
    )
    assert result["graph_version"] == "v2"
    assert result["execution_recovery_contract_enabled"] is True
    assert recovery_contract_enabled(TruthRuntime(r1), "BANK-EXEC-RECOVERY") is True


def test_pass_attempt_requires_durable_preparation_runner_and_convergence(tmp_path: Path) -> None:
    truth, _ = _active_execution(tmp_path)
    _prepare(truth, "ATTEMPT-PASS")
    _attempt(truth, "ATTEMPT-PASS", "PASS")
    _convergence(truth, "ATTEMPT-PASS", "PASS")
    _tool(truth, "runner_execute", "pass")
    _tool(truth, "execution_convergence", "pass")

    result = ExecutionRecoveryConformanceChecker(truth).check_task(MISSION, TASK)
    assert result.status == "PASS"
    assert result.terminal_statuses == ("PASS",)


def test_failed_attempt_cannot_fake_pass_without_diagnosis_and_decision(tmp_path: Path) -> None:
    truth, control = _active_execution(tmp_path)
    _prepare(truth, "ATTEMPT-FAIL")
    _attempt(truth, "ATTEMPT-FAIL", "FAIL")
    _convergence(truth, "ATTEMPT-FAIL", "PASS")
    _tool(truth, "runner_execute", "fail")
    _tool(truth, "execution_convergence", "fake-pass")

    result = ExecutionRecoveryConformanceChecker(truth).check_task(MISSION, TASK)
    assert result.status == "FAIL"
    assert any(item.startswith("FAILURE_DIAGNOSIS_NOT_UNIQUE:ATTEMPT-FAIL") for item in result.violations)
    assert any(item.startswith("RECOVERY_DECISION_NOT_UNIQUE:ATTEMPT-FAIL") for item in result.violations)
    assert "FAILURE_DIAGNOSE_CHAIN_CALL_REQUIRED:ATTEMPT-FAIL" in result.violations

    control.submit_worker_output(WorkerOutput(task_id=TASK, worker_ref=WORKER))
    with pytest.raises(ClosedLoopControlError, match="EXECUTION_RECOVERY_CONFORMANCE_FAILED"):
        control.accept_evaluation(
            TASK,
            evaluation=Evaluation(
                evaluation_id="EVAL-FAKE-PASS",
                mission_id=MISSION,
                node="EXECUTION",
                artifact_refs=[],
                result=EvaluationResult.PASS,
                evaluator_ref="AUTHORITY-EXECUTION",
            ),
        )


def test_nonterminal_failure_uses_separate_diagnostic_recovery_roles(tmp_path: Path) -> None:
    truth, control = _active_execution(tmp_path)
    first = "ATTEMPT-1"
    second = "ATTEMPT-2"
    _prepare(truth, first)
    _prepare(truth, second)
    _attempt(truth, first, "FAIL")
    truth.append_atomic(
        "FAILURE_DIAGNOSIS_UPSERTED",
        {
            "diagnosis_id": "DIAG-1",
            "release_id": RELEASE,
            "attempt_id": first,
            "failure_class": "DATA",
            "evidence_refs": ["evidence://diag/1"],
            "classifier_ref": "classifier://runtime",
            "rationale": "test data stale",
            "failure_signature_id": "SIG-1",
            "root_cause_candidate_id": None,
            "cat_required": False,
            "cat_queried": False,
            "cat_query_evidence_id": None,
        },
    )
    truth.append_atomic(
        "RECOVERY_DECISION_UPSERTED",
        {
            "decision_id": "RDEC-1",
            "release_id": RELEASE,
            "diagnosis_id": "DIAG-1",
            "attempt_id": first,
            "action": "RESEARCH_OR_REBUILD_DATA",
            "terminal": False,
            "next_attempt_id": second,
            "retry_allowed": False,
            "reprepare_allowed": True,
            "reason": "data can be rebuilt",
        },
    )
    truth.append_atomic(
        "RECOVERY_ACTION_UPSERTED",
        {
            "recovery_action_id": "RACT-1",
            "release_id": RELEASE,
            "action": "RESEARCH_OR_REBUILD_DATA",
            "prior_attempt_id": first,
            "next_attempt_id": second,
            "status": "PASS",
            "evidence_refs": ["evidence://recovery/1"],
            "output_refs": ["data://rebuilt/1"],
            "verified": True,
            "terminal_status": None,
        },
    )
    _convergence(truth, first, "RECOVERY_ALLOWED")
    _attempt(truth, second, "PASS")
    _convergence(truth, second, "PASS")
    _tool(truth, "runner_execute", "real-runner")
    _tool(truth, "execution_convergence", "runtime-convergence")
    _chain(truth, first, "failure_diagnose", "WORKER-DIAGNOSTIC")
    _chain(truth, first, "recovery_decide", "WORKER-RECOVERY-PLANNER")
    _chain(truth, first, "recovery_execute", "WORKER-RECOVERY-EXECUTOR")

    result = ExecutionRecoveryConformanceChecker(truth).check_task(MISSION, TASK)
    assert result.status == "PASS"
    assert "PASS" in result.terminal_statuses
    assert "failure_diagnose" in result.observed_tools
    assert "recovery_execute" in result.observed_tools

    control.submit_worker_output(WorkerOutput(task_id=TASK, worker_ref=WORKER))
    passed = control.accept_evaluation(
        TASK,
        evaluation=Evaluation(
            evaluation_id="EVAL-EXEC-PASS",
            mission_id=MISSION,
            node="EXECUTION",
            artifact_refs=[],
            result=EvaluationResult.PASS,
            evaluator_ref="AUTHORITY-EXECUTION",
        ),
    )
    assert passed.state.value == "PASS"


def test_cat_required_failure_cannot_pass_without_attempt_scoped_cat_evidence(tmp_path: Path) -> None:
    truth, _ = _active_execution(tmp_path)
    attempt_id = "ATTEMPT-CAT"
    _prepare(truth, attempt_id)
    _attempt(truth, attempt_id, "FAIL", layer="L3")
    truth.append_atomic(
        "FAILURE_DIAGNOSIS_UPSERTED",
        {
            "diagnosis_id": "DIAG-CAT",
            "release_id": RELEASE,
            "attempt_id": attempt_id,
            "failure_class": "PRODUCT",
            "evidence_refs": ["evidence://diag/cat"],
            "classifier_ref": "classifier://runtime",
            "rationale": "downstream product failure",
            "failure_signature_id": "SIG-CAT",
            "root_cause_candidate_id": None,
            "cat_required": True,
            "cat_queried": True,
            "cat_query_evidence_id": "EVD-CAT-MISSING",
        },
    )
    truth.append_atomic(
        "RECOVERY_DECISION_UPSERTED",
        {
            "decision_id": "RDEC-CAT",
            "release_id": RELEASE,
            "diagnosis_id": "DIAG-CAT",
            "attempt_id": attempt_id,
            "action": "PRODUCT_DEFECT",
            "terminal": True,
            "next_attempt_id": None,
            "retry_allowed": False,
            "reprepare_allowed": False,
            "reason": "trusted product failure",
        },
    )
    _convergence(truth, attempt_id, "PRODUCT_DEFECT_CONFIRMED")
    _tool(truth, "runner_execute", "cat-run")
    _tool(truth, "execution_convergence", "cat-convergence")
    _chain(truth, attempt_id, "failure_diagnose", "WORKER-DIAGNOSTIC")
    _chain(truth, attempt_id, "recovery_decide", "WORKER-RECOVERY-PLANNER")

    failed = ExecutionRecoveryConformanceChecker(truth).check_task(MISSION, TASK)
    assert failed.status == "FAIL"
    assert "ATTEMPT_CAT_QUERY_EVIDENCE_NOT_UNIQUE:%s" % attempt_id in failed.violations

    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-CAT-REAL",
            mission_id=MISSION,
            kind=ATTEMPT_CAT_QUERY_KIND,
            source_ref="provider://bank-cat/BANK_CAT_QUERY",
            content_ref="state://attempt-cat/query.json",
            subject_refs=[TASK, "WORKER-DIAGNOSTIC", attempt_id, "TARGET-1", "CATQ-1"],
            content_hash="c" * 64,
        ),
        release_id=RELEASE,
    )
    row = truth.query("failure_diagnosis", diagnosis_id="DIAG-CAT")[0]
    updated = dict(row)
    updated["artifact_version"] = int(row["artifact_version"]) + 1
    updated["cat_query_evidence_id"] = "EVD-CAT-REAL"
    truth.append_atomic("FAILURE_DIAGNOSIS_UPSERTED", updated)

    passed = ExecutionRecoveryConformanceChecker(truth).check_task(MISSION, TASK)
    assert passed.status == "PASS"
