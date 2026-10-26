from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_autonomous_preparation_closure import (
    BankAutonomousPreparationClosureCoordinator,
    BankAutonomousPreparationClosureError,
)
from rc7_runtime.bank_execution_autopilot import BankExecutionAutopilot
from rc7_runtime.case_runtime import CasePreparationService
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.truth_overlay import append_entity


RELEASE = "RC7.1-BANK-N5"
MISSION = "MISSION-RC7-1-BANK-N5"
RUN = "RUN-RC7-1-BANK-N5"
TARGET = "BANK-PFC-UAT"


def _case(tc_id: str):
    return {
        "status": "FROZEN",
        "tc_id": tc_id,
        "case_version": 1,
        "layer": "L3",
        "preconditions": [],
        "test_data": {
            "initial_state": [],
            "input_data": [],
            "cleanup_policy": {"mode": "NONE"},
        },
        "oracle": {"type": "API", "expected": "OK"},
    }


def _setup(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    append_entity(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="prove BANK N5 production preparation adoption",
        ),
        release_id=RELEASE,
    )
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    return truth, control


def _task(truth, task_id: str, worker_id: str):
    append_entity(
        truth,
        Task(
            task_id=task_id,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="RUNTIME",
            objective="execute accepted case",
            state=TaskStatus.LEASED,
            lease_owner=worker_id,
        ),
        release_id=RELEASE,
    )


def _prepare(
    truth,
    state_root: Path,
    *,
    task_id: str,
    worker_id: str,
    tc_id: str,
    target_id: str,
):
    case = _case(tc_id)
    result = CasePreparationService(truth, state_root).prepare(
        mission_id=MISSION,
        task_id=task_id,
        worker_id=worker_id,
        case=case,
        attempt_id="ATT-%s" % tc_id,
        target_id=target_id,
    )
    assert result["status"] == "PREPARED"
    return case, result


def test_bank_n5_closes_once_only_after_full_case_denominator_is_prepared(
    tmp_path: Path,
) -> None:
    truth, control = _setup(tmp_path)
    state = tmp_path / "state"
    evidence = tmp_path / "evidence"
    cases = (_case("TC-A"), _case("TC-B"))

    _task(truth, "EXEC-A", "worker-a")
    case_a, result_a = _prepare(
        truth,
        state,
        task_id="EXEC-A",
        worker_id="worker-a",
        tc_id="TC-A",
        target_id=TARGET,
    )
    coordinator = BankAutonomousPreparationClosureCoordinator(
        state_root=str(state),
        evidence_root=str(evidence),
        target_id=TARGET,
        max_freshness_seconds=300,
    )
    gate_a = coordinator.adopt_case_and_gate(
        control,
        run_id=RUN,
        execution_task_id="EXEC-A",
        case=case_a,
        prepared_result=result_a,
        accepted_cases=cases,
    )
    assert gate_a.node_closed is False
    prepared_rows = truth.query(
        "rc7_artifact", artifact_id=gate_a.prepared_artifact_id
    )
    assert len(prepared_rows) == 1
    assert prepared_rows[0]["artifact_type_name"] == "PREPARED_ATTEMPT"
    assert not [
        row
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_TERMINAL"
        and row.get("data", {}).get("node_id") == "N5"
    ]

    _task(truth, "EXEC-B", "worker-b")
    case_b, result_b = _prepare(
        truth,
        state,
        task_id="EXEC-B",
        worker_id="worker-b",
        tc_id="TC-B",
        target_id=TARGET,
    )
    gate_b = coordinator.adopt_case_and_gate(
        control,
        run_id=RUN,
        execution_task_id="EXEC-B",
        case=case_b,
        prepared_result=result_b,
        accepted_cases=cases,
    )
    assert gate_b.node_closed is True
    terminal = [
        row
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_TERMINAL"
        and row.get("data", {}).get("node_id") == "N5"
    ]
    assert len(terminal) == 1
    director = truth.query(
        "rc7_evaluation", evaluation_id=gate_b.director_evaluation_id
    )
    assert len(director) == 1
    assert director[0]["evaluator_ref"] == "rc7-bank-autonomous-node-director-gate"
    assert director[0]["evaluator_ref"] != "rc7-runtime-preparation-aggregate-authority"
    aggregate = [
        row
        for row in truth.query("rc7_artifact", mission_id=MISSION)
        if row.get("artifact_type_name") == "PREPARATION_BATCH_FINALIZATION"
    ]
    assert len(aggregate) == 1


def test_bank_n5_stale_case_runtime_preparation_never_reaches_finalization_or_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    truth, control = _setup(tmp_path)
    state = tmp_path / "state"
    _task(truth, "EXEC-A", "worker-a")
    case, result = _prepare(
        truth,
        state,
        task_id="EXEC-A",
        worker_id="worker-a",
        tc_id="TC-A",
        target_id=TARGET,
    )
    source = truth.query("rc7_evidence", evidence_id=result["evidence_id"])[0]
    source_created = int(source["created_at"])

    import rc7_runtime.bank_autonomous_preparation_closure as bridge

    monkeypatch.setattr(bridge.time, "time", lambda: source_created + 120)
    coordinator = BankAutonomousPreparationClosureCoordinator(
        state_root=str(state),
        evidence_root=str(tmp_path / "evidence"),
        target_id=TARGET,
        max_freshness_seconds=30,
    )
    with pytest.raises(
        BankAutonomousPreparationClosureError,
        match="BANK_N5_SOURCE_PREPARED_EVIDENCE_STALE",
    ):
        coordinator.adopt_case_and_gate(
            control,
            run_id=RUN,
            execution_task_id="EXEC-A",
            case=case,
            prepared_result=result,
            accepted_cases=(case,),
        )
    assert not [
        row
        for row in truth.query("rc7_artifact", mission_id=MISSION)
        if row.get("artifact_type_name") == "CASE_PREPARATION_FINALIZATION"
    ]
    assert not [
        row
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_TERMINAL"
        and row.get("data", {}).get("node_id") == "N5"
    ]


def test_bank_n5_target_mismatch_fails_closed_before_node_delivery(
    tmp_path: Path,
) -> None:
    truth, control = _setup(tmp_path)
    state = tmp_path / "state"
    _task(truth, "EXEC-A", "worker-a")
    case, result = _prepare(
        truth,
        state,
        task_id="EXEC-A",
        worker_id="worker-a",
        tc_id="TC-A",
        target_id="OTHER-TARGET",
    )
    coordinator = BankAutonomousPreparationClosureCoordinator(
        state_root=str(state),
        evidence_root=str(tmp_path / "evidence"),
        target_id=TARGET,
    )
    with pytest.raises(
        BankAutonomousPreparationClosureError,
        match="BANK_N5_PREPARED_TARGET_MISMATCH",
    ):
        coordinator.adopt_case_and_gate(
            control,
            run_id=RUN,
            execution_task_id="EXEC-A",
            case=case,
            prepared_result=result,
            accepted_cases=(case,),
        )
    assert not [
        row
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_READY_FOR_DIRECTOR_REVIEW"
        and row.get("data", {}).get("node_id") == "N5"
    ]


def test_bank_execution_main_link_gates_business_runner_through_n5() -> None:
    source = inspect.getsource(BankExecutionAutopilot.run)
    assert source.index("adopt_case_and_gate") < source.index("execute_active_task")
    assert "EXECUTION_N5_FAIL_CLOSED" in source
    assert "BLOCKED_PREPARATION" in source
