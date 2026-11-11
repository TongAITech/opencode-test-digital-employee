from types import MethodType, SimpleNamespace

import pytest

from rc6_runtime.truth import TruthRuntime
import rc7_runtime.closed_loop_control as closed_loop_module
from rc7_runtime.closed_loop_control import ClosedLoopControlError, ClosedLoopControlPlane
from rc7_runtime.models import Evaluation, EvaluationResult, Mission, Task, TaskStatus


def _script_task(*, task_type="PRODUCE"):
    return Task(
        task_id="TASK-SCRIPT-FANOUT-GATE",
        mission_id="MISSION-FANOUT-GATE",
        node="SCRIPT_READINESS",
        task_type=task_type,
        objective="prove every accepted case has a ready script",
        state=TaskStatus.OUTPUT_PRODUCED,
        lease_owner="script-worker",
    )


def _evaluation(*, evidence_refs=()):
    return Evaluation(
        evaluation_id="EVAL-SCRIPT-FANOUT-GATE",
        mission_id="MISSION-FANOUT-GATE",
        node="SCRIPT_READINESS",
        artifact_refs=[],
        result=EvaluationResult.PASS,
        evaluator_ref="independent-script-gate",
        evidence_refs=list(evidence_refs),
    )


def _control():
    control = object.__new__(ClosedLoopControlPlane)
    control.truth = object()
    control.mission_id = "MISSION-FANOUT-GATE"
    control.release_id = "REL-FANOUT-GATE"
    return control


def test_control_boundary_rejects_incomplete_script_fanout(monkeypatch):
    control = _control()
    task = _script_task()
    monkeypatch.setattr(closed_loop_module, "case_fanout_contract_enabled", lambda truth, mission_id: True)
    monkeypatch.setattr(
        closed_loop_module,
        "check_script_barrier",
        lambda truth, mission_id: SimpleNamespace(
            status="INCOMPLETE",
            missing_tc_ids=("TC-2", "TC-3"),
            receipt_ids=("EVD-TC-1",),
        ),
    )

    with pytest.raises(ClosedLoopControlError, match="SCRIPT_FANOUT_BARRIER_INCOMPLETE:TC-2,TC-3"):
        control._require_script_fanout_pass_ready(task, _evaluation(evidence_refs=("EVD-TC-1",)))


def test_control_boundary_requires_final_evaluation_to_bind_all_case_receipts(monkeypatch):
    control = _control()
    task = _script_task()
    monkeypatch.setattr(closed_loop_module, "case_fanout_contract_enabled", lambda truth, mission_id: True)
    monkeypatch.setattr(
        closed_loop_module,
        "check_script_barrier",
        lambda truth, mission_id: SimpleNamespace(
            status="PASS",
            missing_tc_ids=(),
            receipt_ids=("EVD-TC-1", "EVD-TC-2"),
        ),
    )

    with pytest.raises(ClosedLoopControlError, match="SCRIPT_FANOUT_RECEIPT_BINDING_MISSING:EVD-TC-2"):
        control._require_script_fanout_pass_ready(task, _evaluation(evidence_refs=("EVD-TC-1",)))

    control._require_script_fanout_pass_ready(
        task,
        _evaluation(evidence_refs=("EVD-TC-1", "EVD-TC-2")),
    )


def test_repair_task_does_not_claim_top_level_fanout_completion(monkeypatch):
    control = _control()
    task = _script_task(task_type="REPAIR")

    def unexpected(*_args, **_kwargs):
        raise AssertionError("repair task must not evaluate the top-level fanout barrier")

    monkeypatch.setattr(closed_loop_module, "case_fanout_contract_enabled", unexpected)
    control._require_script_fanout_pass_ready(task, _evaluation())


def test_accept_evaluation_invokes_script_fanout_gate_before_persisting_pass(tmp_path):
    event_path = tmp_path / 'fanout-gate-r1.jsonl'
    truth = TruthRuntime(event_path)
    control = ClosedLoopControlPlane.bootstrap(truth, Mission(
        mission_id='MISSION-FANOUT-GATE', release_id='REL-FANOUT-GATE',
        goal='prove the script gate precedes PASS persistence',
    ))
    task = _script_task()
    control.register_task(task)
    before = event_path.read_bytes()

    def block(self, passed_task, passed_evaluation):
        assert passed_task.task_id == task.task_id
        assert passed_task.state == TaskStatus.OUTPUT_PRODUCED
        assert passed_evaluation.result == EvaluationResult.PASS
        raise ClosedLoopControlError("SCRIPT_FANOUT_SENTINEL")

    control._require_script_fanout_pass_ready = MethodType(block, control)

    with pytest.raises(ClosedLoopControlError, match="SCRIPT_FANOUT_SENTINEL"):
        control.accept_evaluation(task.task_id, evaluation=_evaluation())
    assert event_path.read_bytes() == before
    assert truth.query('rc7_evaluation', evaluation_id='EVAL-SCRIPT-FANOUT-GATE') == []
    assert control.scheduler.task(task.task_id).state == TaskStatus.OUTPUT_PRODUCED
