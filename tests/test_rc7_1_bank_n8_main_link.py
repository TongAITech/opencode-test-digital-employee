from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

import rc7_runtime.bank_execution_autopilot as bank_execution_autopilot_module
from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_execution_autopilot import BankExecutionAutopilot, BankExecutionAutopilotError
from rc7_runtime.bank_n8_recovery import BankN8RecoveryCoordinator
from rc7_runtime.bank_n8_successor import BankN8SuccessorCoordinator
from rc7_runtime.case_runtime import PREPARED_ATTEMPT_KIND, _state_ref, _write_immutable_json
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.execution_recovery import RecoveryWorkPlan
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
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-RC7-1-BANK-N8"
SOURCE = "TASK-EXEC-N8-BANK"


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7.1-N8-BANK",
            goal="prove bank N8 production retry gate",
        ),
    )
    control.register_task(
        Task(
            task_id=SOURCE,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute one governed case",
            required_capabilities=["test_execution"],
        )
    )
    return truth, control


def _make_source_repair_required(control: ClosedLoopControlPlane):
    leased = control.lease_next(worker_ref="execution-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE
    control.start(SOURCE, worker_ref="execution-worker")
    evidence = Evidence(
        evidence_id="EVD-EXEC-N8-BANK",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://execution",
        content_ref="evidence://attempt/ATT-1",
        subject_refs=[SOURCE, "ATT-1", "TC-1"],
    )
    artifact = Artifact(
        artifact_id="ART-EXEC-N8-BANK",
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=SOURCE,
        content_ref="artifact://attempt/ATT-1",
        evidence_refs=[evidence.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=SOURCE,
            worker_ref="execution-worker",
            artifacts=(artifact,),
            evidence=(evidence,),
        )
    )
    gap = Gap(
        gap_id="GAP-TRANSIENT-N8-BANK",
        mission_id=MISSION,
        source_node="EXECUTION",
        category="TRANSIENT_FAILURE",
        severity=GapSeverity.MEDIUM,
        target_node="EXECUTION",
        description="transient failure requires controlled successor attempt",
        subject_refs=["ATT-1", "TC-1"],
        evidence_refs=[evidence.evidence_id],
        acceptance_criteria=["authorize a fresh successor attempt without executing business work in the repair task"],
    )
    evaluation = Evaluation(
        evaluation_id="EVAL-EXEC-N8-BANK",
        mission_id=MISSION,
        node="EXECUTION",
        artifact_refs=[artifact.artifact_id],
        result=EvaluationResult.REPAIR_REQUIRED,
        evaluator_ref="runtime-execution-gate",
        dimensions={"attempt_id": "ATT-1", "recovery_action": "RETRY_SAME_STEP"},
        gap_refs=[gap.gap_id],
        evidence_refs=[evidence.evidence_id],
    )
    control.accept_evaluation(SOURCE, evaluation=evaluation, gaps=(gap,))
    repair_rows = [
        row for row in control.truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "REPAIR"
        and row.get("node") == "EXECUTION"
        and row.get("gap_refs") == [gap.gap_id]
    ]
    assert len(repair_rows) == 1
    return gap, control.scheduler.task(repair_rows[0]["task_id"])


def _persist_source_prepared(truth, state_root: Path):
    prepared = PreparedAttempt(
        status="PREPARED",
        attempt_id="ATT-1",
        tc_id="TC-1",
        case_version=1,
        target_id="BANK-TARGET",
        precondition_evidence=("EVD-PRE-1",),
        initial_state_bindings={"loan_id": "L-1"},
        input_data_bindings={"amount": 100},
        binding_evidence=("EVD-DATA-1",),
        cleanup_policy={"mode": "RELEASE"},
        oracle_snapshot={"checks": [{"id": "CHK-1", "type": "BUSINESS_RULE", "actual_path": "code", "operator": "EQ", "expected": "OK"}]},
    )
    target, digest = _write_immutable_json(
        state_root,
        Path(MISSION) / "ATT-1" / "prepared-attempt.json",
        asdict(prepared),
    )
    evidence = Evidence(
        evidence_id="EVD-PREPARED-ATT-1",
        mission_id=MISSION,
        kind=PREPARED_ATTEMPT_KIND,
        source_ref="runtime://case-runtime/preparation",
        content_ref=_state_ref(state_root, target),
        subject_refs=[SOURCE, "execution-worker", "ATT-1", "TC-1", "BANK-TARGET"],
        content_hash=digest,
    )
    append_entity(truth, evidence, release_id="RC7.1-N8-BANK", artifact_version=1)
    return prepared, target


def _direct_order_and_repair(control, gap, repair_task, evidence_root: Path):
    coordinator = BankN8RecoveryCoordinator(evidence_root=str(evidence_root))
    plan = RecoveryWorkPlan(
        diagnosis_id="DIAG-ATT-1",
        source_attempt_id="ATT-1",
        action="RETRY_SAME_STEP",
        mode="DIRECT_RETRY",
        target_node="EXECUTION",
        retry_allowed=True,
        reprepare_required=False,
        terminal=False,
        successor_attempt_id="ATT-2",
        reason="runtime-classified transient failure",
    )
    order = coordinator._create_direct_retry_order(
        control,
        source_task_id=SOURCE,
        gap_id=gap.gap_id,
        plan=plan,
        diagnosis_evidence_id="EVD-DIAG-ATT-1",
        failure_signature_id="FSIG-ATT-1",
    )
    successor = coordinator.handle_execution_repair(control, repair_task)
    return coordinator, order, successor


def test_bank_execution_repair_is_n8_authorization_not_business_execution():
    calls = []

    class _N8:
        def handle_execution_repair(self, control, task):
            calls.append((control, task.task_id))
            return "ATT-2"

    autopilot = object.__new__(BankExecutionAutopilot)
    autopilot.n8_recovery = _N8()
    control = object()
    task = SimpleNamespace(task_id="TASK-REPAIR", node="EXECUTION", task_type="REPAIR")

    autopilot.run(control, task)

    assert calls == [(control, "TASK-REPAIR")]


def test_direct_retry_repair_produces_authorization_receipt_without_business_action(tmp_path: Path):
    truth, control = _control(tmp_path)
    gap, repair_task = _make_source_repair_required(control)
    coordinator, order, successor = _direct_order_and_repair(control, gap, repair_task, tmp_path / "evidence")

    assert successor == "ATT-2"
    assert control.scheduler.task(repair_task.task_id).state == TaskStatus.PASS
    assert control.scheduler.task(SOURCE).state == TaskStatus.READY
    assert truth.query("rc7_gap", gap_id=gap.gap_id)[0]["state"] == "EVIDENCE_PENDING"

    receipts = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == coordinator.DIRECT_RECEIPT_TYPE
        and order.order_id in set(row.get("subject_refs") or [])
    ]
    assert len(receipts) == 1
    ref = receipts[0]["content_ref"]
    assert ref.startswith("file://")
    payload = json.loads(Path(ref[len("file://"):]).read_text(encoding="utf-8"))
    assert payload["source_attempt_id"] == "ATT-1"
    assert payload["successor_attempt_id"] == "ATT-2"
    assert payload["business_action_executed"] is False


def test_direct_retry_materializes_fresh_successor_prepared_once_without_mutating_source(tmp_path: Path):
    truth, control = _control(tmp_path)
    state_root = tmp_path / "state"
    original, original_path = _persist_source_prepared(truth, state_root)
    original_bytes = original_path.read_bytes()
    gap, repair_task = _make_source_repair_required(control)
    _coordinator, _order, successor = _direct_order_and_repair(control, gap, repair_task, tmp_path / "evidence")
    assert successor == "ATT-2"

    leased = control.lease_next(worker_ref="retry-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE
    successor_service = BankN8SuccessorCoordinator(state_root=state_root)
    prepared_result = successor_service.materialize_direct_successor(
        control,
        source_task_id=SOURCE,
        worker_id="retry-worker",
        tc_id="TC-1",
        target_id="BANK-TARGET",
    )

    assert prepared_result is not None
    assert prepared_result["n8_successor"] is True
    assert prepared_result["source_attempt_id"] == "ATT-1"
    assert prepared_result["prepared_attempt"]["attempt_id"] == "ATT-2"
    assert prepared_result["prepared_attempt"]["input_data_bindings"] == original.input_data_bindings
    assert prepared_result["prepared_attempt"]["oracle_snapshot"] == original.oracle_snapshot
    assert original_path.read_bytes() == original_bytes

    prepared_rows = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == PREPARED_ATTEMPT_KIND
    ]
    assert len(prepared_rows) == 2
    att1 = [row for row in prepared_rows if "ATT-1" in set(row.get("subject_refs") or [])]
    att2 = [row for row in prepared_rows if "ATT-2" in set(row.get("subject_refs") or [])]
    assert len(att1) == 1
    assert len(att2) == 1
    assert att2[0]["source_ref"] == "runtime://bank-n8/direct-retry-successor"
    assert prepared_result["authorization_evidence_id"] in set(att2[0]["subject_refs"])

    assert successor_service.materialize_direct_successor(
        control,
        source_task_id=SOURCE,
        worker_id="retry-worker",
        tc_id="TC-1",
        target_id="BANK-TARGET",
    ) is None


def test_execution_repair_targets_only_case_bound_to_gap_without_sibling_fallback(monkeypatch):
    class _Truth:
        @staticmethod
        def query(artifact_type, **filters):
            assert artifact_type == "rc7_gap"
            assert filters == {"gap_id": "GAP-TC-B"}
            return [{"gap_id": "GAP-TC-B", "subject_refs": ["ATT-TC-B", "TC-B"]}]

    autopilot = object.__new__(BankExecutionAutopilot)
    autopilot.inventory = SimpleNamespace(
        load=lambda truth, mission_id: SimpleNamespace(tc_ids=("TC-A", "TC-B"))
    )
    control = SimpleNamespace(truth=_Truth(), mission_id=MISSION)
    task = SimpleNamespace(task_type="REPAIR", gap_refs=["GAP-TC-B"])

    def _barrier_must_not_run(*args, **kwargs):
        raise AssertionError("repair with a unique Case binding must not fall back to sibling fanout")

    monkeypatch.setattr(
        bank_execution_autopilot_module,
        "check_execution_barrier",
        _barrier_must_not_run,
    )

    assert autopilot._case_for_task(control, task) == "TC-B"


def test_normal_execution_only_selects_missing_case_and_rejects_after_all_siblings_terminal(monkeypatch):
    autopilot = object.__new__(BankExecutionAutopilot)
    autopilot.inventory = SimpleNamespace(
        load=lambda truth, mission_id: SimpleNamespace(tc_ids=("TC-A", "TC-B"))
    )
    control = SimpleNamespace(truth=object(), mission_id=MISSION)
    task = SimpleNamespace(task_type="EXECUTE", gap_refs=[])

    # TC-A is already terminal and therefore absent from the missing denominator.
    # Production scheduling must choose only TC-B and never replay TC-A.
    monkeypatch.setattr(
        bank_execution_autopilot_module,
        "check_execution_barrier",
        lambda truth, mission_id: SimpleNamespace(
            missing_tc_ids=("TC-B",),
            pass_ready_tc_ids=("TC-A",),
        ),
    )
    assert autopilot._case_for_task(control, task) == "TC-B"

    # Once both siblings are terminal, an extra execution dispatch is a hard error,
    # not permission to recycle an already-terminal Case.
    monkeypatch.setattr(
        bank_execution_autopilot_module,
        "check_execution_barrier",
        lambda truth, mission_id: SimpleNamespace(
            missing_tc_ids=(),
            pass_ready_tc_ids=("TC-A", "TC-B"),
        ),
    )
    with pytest.raises(BankExecutionAutopilotError, match="EXECUTION_FANOUT_ALREADY_COMPLETE"):
        autopilot._case_for_task(control, task)
