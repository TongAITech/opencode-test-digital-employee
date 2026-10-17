from types import SimpleNamespace

import pytest

import rc7_runtime.control_plane as control_plane_module
from rc7_runtime.control_plane import GapRepairPlanner
from rc7_runtime.execution_fanout_evaluator import RuntimeCaseFanoutExecutionEvaluator
from rc7_runtime.execution_loop import ExecutionLoopResult
from rc7_runtime.models import Evaluation, EvaluationResult, Gap, GapSeverity


MISSION = "MISSION-FANOUT-DEFECT"


def _product_gap(gap_id, tc_id):
    return Gap(
        gap_id=gap_id,
        mission_id=MISSION,
        source_node="EXECUTION",
        category="PRODUCT_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="DEFECT",
        description="trusted mismatch for %s" % tc_id,
        subject_refs=["ATT-" + tc_id, tc_id],
        evidence_refs=["EVD-FAIL-" + tc_id],
        acceptance_criteria=["reproduce %s" % tc_id],
    )


def _loop(gaps=(), *, recovery="PRODUCT_DEFECT"):
    evaluation = Evaluation(
        evaluation_id="EVAL-CASE",
        mission_id=MISSION,
        node="EXECUTION",
        artifact_refs=["ART-CURRENT"],
        result=EvaluationResult.PASS,
        evaluator_ref="runtime-execution-gate",
        dimensions={"attempt_id": "ATT-CURRENT", "failure_class": "PRODUCT", "test_result": "FAIL"},
        gap_refs=[gap.gap_id for gap in gaps],
        evidence_refs=["EVD-CURRENT"],
    )
    return ExecutionLoopResult(
        evaluation=evaluation,
        gaps=tuple(gaps),
        test_result="FAIL" if gaps else "PASS",
        conclusive=True,
        recovery_action=recovery if gaps else None,
    )


def test_runtime_repair_defect_is_deferred_in_receipt_not_lost_as_nondurable_gap():
    gap = _product_gap("GAP-PRODUCT-TC1", "TC-1")
    result = RuntimeCaseFanoutExecutionEvaluator._case_terminal_result(
        _loop((gap,)),
        "EVD-CASE-EXEC-TC1",
    )

    assert result.evaluation.result == EvaluationResult.PASS
    assert result.gaps == ()
    assert result.evaluation.gap_refs == []
    assert result.evaluation.dimensions["product_defect_deferred"] is True
    assert result.evaluation.evidence_refs[-1] == "EVD-CASE-EXEC-TC1"


def test_aggregate_replays_every_deferred_product_defect_and_all_case_receipts():
    defects = (
        _product_gap("GAP-PRODUCT-TC1", "TC-1"),
        _product_gap("GAP-PRODUCT-TC2", "TC-2"),
    )
    barrier = SimpleNamespace(
        required_tc_ids=("TC-1", "TC-2", "TC-3"),
        pass_ready_tc_ids=("TC-1", "TC-2", "TC-3"),
        receipt_ids=("EVD-CASE-EXEC-TC1", "EVD-CASE-EXEC-TC2", "EVD-CASE-EXEC-TC3"),
    )

    result = RuntimeCaseFanoutExecutionEvaluator._aggregate_result(_loop(()), barrier, defects)

    assert result.evaluation.result == EvaluationResult.PASS
    assert result.test_result == "FAIL"
    assert result.recovery_action == "PRODUCT_DEFECT"
    assert tuple(gap.gap_id for gap in result.gaps) == ("GAP-PRODUCT-TC1", "GAP-PRODUCT-TC2")
    assert result.evaluation.gap_refs == ["GAP-PRODUCT-TC1", "GAP-PRODUCT-TC2"]
    assert result.evaluation.dimensions["product_defect_count"] == 2
    assert result.evaluation.dimensions["case_execution_fanout"] == "PASS"
    assert set(barrier.receipt_ids).issubset(set(result.evaluation.evidence_refs))


class _Truth:
    def __init__(self, terminal_rows, artifacts):
        self.terminal_rows = terminal_rows
        self.artifacts = artifacts

    def query(self, artifact_type, **filters):
        if artifact_type == "rc7_evidence":
            rows = self.terminal_rows
        elif artifact_type == "rc7_artifact":
            rows = self.artifacts
        else:
            rows = []
        return [
            dict(row) for row in rows
            if all(row.get(key) == value for key, value in filters.items())
        ]


class _Scheduler:
    def __init__(self, tasks):
        self.tasks = tasks

    def _row(self, task_id):
        row = self.tasks.get(task_id)
        return dict(row) if row else None


def test_defect_source_resolver_uses_each_terminal_receipts_exact_case_artifact(monkeypatch):
    terminal_rows = [
        {"evidence_id": "EVD-TERM-TC1", "mission_id": MISSION, "kind": "CASE_EXECUTION_TERMINAL"},
        {"evidence_id": "EVD-TERM-TC2", "mission_id": MISSION, "kind": "CASE_EXECUTION_TERMINAL"},
    ]
    artifacts = [
        {
            "artifact_id": "ART-EXEC-TC1",
            "mission_id": MISSION,
            "artifact_type_name": "EXECUTION_CONCLUSION",
            "producer_task_id": "TASK-EXEC-REPAIR-TC1",
        },
        {
            "artifact_id": "ART-EXEC-TC2",
            "mission_id": MISSION,
            "artifact_type_name": "EXECUTION_CONCLUSION",
            "producer_task_id": "TASK-EXEC-REPAIR-TC2",
        },
    ]
    tasks = {
        "TASK-EXEC-REPAIR-TC1": {"mission_id": MISSION, "node": "EXECUTION", "state": "PASS"},
        "TASK-EXEC-REPAIR-TC2": {"mission_id": MISSION, "node": "EXECUTION", "state": "PASS"},
    }
    truth = _Truth(terminal_rows, artifacts)
    scheduler = _Scheduler(tasks)
    planner = GapRepairPlanner(truth, "RC7", scheduler)

    payloads = {
        "EVD-TERM-TC1": {
            "outcome": "PRODUCT_DEFECT",
            "execution_artifact_id": "ART-EXEC-TC1",
            "execution_task_id": "TASK-EXEC-REPAIR-TC1",
            "product_defect_gap": {"gap_id": "GAP-PRODUCT-TC1"},
        },
        "EVD-TERM-TC2": {
            "outcome": "PRODUCT_DEFECT",
            "execution_artifact_id": "ART-EXEC-TC2",
            "execution_task_id": "TASK-EXEC-REPAIR-TC2",
            "product_defect_gap": {"gap_id": "GAP-PRODUCT-TC2"},
        },
    }
    monkeypatch.setattr(
        control_plane_module,
        "load_execution_terminal_receipt",
        lambda truth, mission_id, receipt_id: payloads[receipt_id],
    )

    gap1 = _product_gap("GAP-PRODUCT-TC1", "TC-1")
    gap1.evidence_refs.append("EVD-TERM-TC1")
    gap2 = _product_gap("GAP-PRODUCT-TC2", "TC-2")
    gap2.evidence_refs.append("EVD-TERM-TC2")

    assert planner._product_defect_source(gap1) == ("TASK-EXEC-REPAIR-TC1", "ART-EXEC-TC1")
    assert planner._product_defect_source(gap2) == ("TASK-EXEC-REPAIR-TC2", "ART-EXEC-TC2")


def test_receipt_source_binding_rejects_wrong_gap(monkeypatch):
    truth = _Truth(
        [{"evidence_id": "EVD-TERM", "mission_id": MISSION, "kind": "CASE_EXECUTION_TERMINAL"}],
        [{
            "artifact_id": "ART-EXEC",
            "mission_id": MISSION,
            "artifact_type_name": "EXECUTION_CONCLUSION",
            "producer_task_id": "TASK-EXEC",
        }],
    )
    planner = GapRepairPlanner(
        truth,
        "RC7",
        _Scheduler({"TASK-EXEC": {"mission_id": MISSION, "node": "EXECUTION", "state": "PASS"}}),
    )
    monkeypatch.setattr(
        control_plane_module,
        "load_execution_terminal_receipt",
        lambda truth, mission_id, receipt_id: {
            "outcome": "PRODUCT_DEFECT",
            "execution_artifact_id": "ART-EXEC",
            "execution_task_id": "TASK-EXEC",
            "product_defect_gap": {"gap_id": "OTHER-GAP"},
        },
    )
    gap = _product_gap("GAP-PRODUCT-TC1", "TC-1")
    gap.evidence_refs.append("EVD-TERM")

    with pytest.raises(control_plane_module.ControlPlaneError, match="GAP_BINDING_MISMATCH"):
        planner._product_defect_source(gap)
