from types import SimpleNamespace

import pytest

import rc7_runtime.bank_mission_autopilot as autopilot_module
from rc7_runtime.bank_mission_autopilot import (
    BankMissionAutopilot,
    BankMissionAutopilotError,
)
from rc7_runtime.bank_mission_director import (
    BankMissionDirectorGate,
    BankMissionDirectorGateError,
)


class _FakeTruth:
    def __init__(self, evaluation):
        self.evaluation = evaluation

    def query(self, entity_type, **filters):
        if entity_type == "rc7_evaluation" and filters.get("evaluation_id") == self.evaluation["evaluation_id"]:
            return [self.evaluation]
        return []


class _FakeNodeControl:
    def __init__(self, iteration, delivery):
        self.iteration = iteration
        self.delivery = delivery

    def latest_iteration(self, **kwargs):
        return self.iteration

    def latest_delivery(self, **kwargs):
        return self.delivery


class _FakeAdoption:
    def __init__(self, iteration, delivery, *, accepted=True):
        self.node_control = _FakeNodeControl(iteration, delivery)
        self.accepted = accepted
        self.calls = []

    def director_accept(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(accepted=self.accepted, evaluation_id="EVAL-DIRECTOR")


def _prepared():
    delivery = SimpleNamespace(
        iteration_count=3,
        package_artifact_id="ART-N10-DELIVERY",
    )
    return SimpleNamespace(
        run_id="RUN-BANK-N10",
        evaluation_id="EVAL-N10",
        manifest_artifact_id="ART-N10-MANIFEST",
        sufficiency_state="SUFFICIENT",
        quality_state="CONVERGED_CLEAN",
        release_recommendation="RECOMMENDED",
        delivery=delivery,
    )


def _evaluation(**overrides):
    row = {
        "evaluation_id": "EVAL-N10",
        "mission_id": "M-BANK-N10",
        "node": "MISSION_EVALUATION",
        "result": "PASS",
        "artifact_refs": ["ART-N10-MANIFEST"],
        "gap_refs": [],
        "evaluator_ref": "rc7-independent-mission-convergence-authority",
        "dimensions": {
            "sufficiency_state": "SUFFICIENT",
            "quality_state": "CONVERGED_CLEAN",
            "release_recommendation": "RECOMMENDED",
            "coverage_state": "CLOSED",
            "business_release_decision": "NOT_DECIDED_BY_TEST_SYSTEM",
        },
    }
    row.update(overrides)
    return row


def test_bank_director_gate_accepts_only_current_separate_n10_truth():
    prepared = _prepared()
    truth = _FakeTruth(_evaluation())
    control = SimpleNamespace(
        truth=truth,
        release_id="R-BANK-N10",
        mission_id="M-BANK-N10",
    )
    gate = object.__new__(BankMissionDirectorGate)
    gate.truth = truth
    gate.release_id = "R-BANK-N10"
    gate.director_ref = "rc7-bank-mission-director-gate"
    gate.adoption = _FakeAdoption(
        SimpleNamespace(iteration_count=3),
        prepared.delivery,
    )

    decision = gate.review_and_accept(control, prepared)

    assert decision.accepted is True
    assert gate.adoption.calls == [
        {
            "mission_id": "M-BANK-N10",
            "run_id": "RUN-BANK-N10",
            "node_id": "N10",
            "director_ref": "rc7-bank-mission-director-gate",
        }
    ]


def test_bank_director_gate_rejects_release_authority_bypass():
    prepared = _prepared()
    evaluation = _evaluation()
    evaluation["dimensions"] = dict(evaluation["dimensions"])
    evaluation["dimensions"]["business_release_decision"] = "GO"
    truth = _FakeTruth(evaluation)
    control = SimpleNamespace(
        truth=truth,
        release_id="R-BANK-N10",
        mission_id="M-BANK-N10",
    )
    gate = object.__new__(BankMissionDirectorGate)
    gate.truth = truth
    gate.release_id = "R-BANK-N10"
    gate.director_ref = "rc7-bank-mission-director-gate"
    gate.adoption = _FakeAdoption(
        SimpleNamespace(iteration_count=3),
        prepared.delivery,
    )

    with pytest.raises(
        BankMissionDirectorGateError,
        match="DIRECTOR_N10_BUSINESS_RELEASE_AUTHORITY_VIOLATION",
    ):
        gate.review_and_accept(control, prepared)
    assert gate.adoption.calls == []


def test_bank_autopilot_convergence_orders_governed_n10_director_then_mission_convergence():
    calls = []
    prepared = SimpleNamespace(run_id="RUN-1")

    class _N10:
        def prepare_ready(self, control, *, run_id):
            calls.append(("prepare", control, run_id))
            return prepared

        def converge_after_director_accept(self, control, *, run_id):
            calls.append(("converge", control, run_id))
            return SimpleNamespace()

    class _Director:
        def review_and_accept(self, control, value):
            calls.append(("director", control, value))
            return SimpleNamespace(accepted=True)

    autopilot = object.__new__(BankMissionAutopilot)
    autopilot.config = SimpleNamespace(run_id="RUN-1")
    autopilot.control = object()
    autopilot.n10 = _N10()
    autopilot.director_gate = _Director()

    autopilot._convergence()

    assert [item[0] for item in calls] == ["prepare", "director", "converge"]
    assert calls[0][2] == "RUN-1"
    assert calls[1][2] is prepared
    assert calls[2][2] == "RUN-1"


def test_bank_autopilot_never_converges_when_director_gate_rejects():
    calls = []

    class _N10:
        def prepare_ready(self, control, *, run_id):
            calls.append("prepare")
            return SimpleNamespace(run_id=run_id)

        def converge_after_director_accept(self, control, *, run_id):
            calls.append("converge")

    class _Director:
        def review_and_accept(self, control, value):
            calls.append("director")
            raise BankMissionDirectorGateError("DIRECTOR_REJECTED")

    autopilot = object.__new__(BankMissionAutopilot)
    autopilot.config = SimpleNamespace(run_id="RUN-1")
    autopilot.control = object()
    autopilot.n10 = _N10()
    autopilot.director_gate = _Director()

    with pytest.raises(
        BankMissionAutopilotError,
        match="AUTOPILOT_GOVERNED_N10_CONVERGENCE_FAILED:DIRECTOR_REJECTED",
    ):
        autopilot._convergence()

    assert calls == ["prepare", "director"]


def test_bank_autopilot_drive_wires_convergence_and_post_convergence_report(monkeypatch):
    captured = {}

    class _Dispatcher:
        def __init__(self, control, **kwargs):
            self.control = control

    class _Driver:
        def __init__(
            self,
            control,
            dispatcher,
            *,
            output_evaluators,
            active_task_handler,
            convergence_handler,
            final_report_handler,
        ):
            captured["control"] = control
            captured["convergence_handler"] = convergence_handler
            captured["final_report_handler"] = final_report_handler

        def drive(self, *, max_steps):
            captured["max_steps"] = max_steps
            return "DRIVEN"

    monkeypatch.setattr(autopilot_module, "MissionStageDispatcher", _Dispatcher)
    monkeypatch.setattr(autopilot_module, "MissionAutonomousDriver", _Driver)

    autopilot = object.__new__(BankMissionAutopilot)
    autopilot.control = object()
    autopilot.bridge = SimpleNamespace(run_next=lambda: None)
    autopilot.supervisor = SimpleNamespace(handle=lambda task: None)
    autopilot.config = SimpleNamespace(max_steps=17)
    autopilot._runtime_handler = lambda task: None
    autopilot._requirement_eval = lambda task: None
    autopilot._code_eval = lambda task: None
    autopilot._test_design_eval = lambda task: None
    autopilot._script_eval = lambda task: None

    assert autopilot.drive() == "DRIVEN"
    assert captured["convergence_handler"].__self__ is autopilot
    assert captured["final_report_handler"].__self__ is autopilot
    assert captured["max_steps"] == 17


def test_bank_autopilot_final_report_uses_same_run_id():
    calls = []

    class _N10:
        def generate_final_report(self, control, *, run_id):
            calls.append((control, run_id))
            return "REPORT"

    autopilot = object.__new__(BankMissionAutopilot)
    autopilot.config = SimpleNamespace(run_id="RUN-FINAL")
    autopilot.control = object()
    autopilot.n10 = _N10()

    assert autopilot._final_report() == "REPORT"
    assert calls == [(autopilot.control, "RUN-FINAL")]
