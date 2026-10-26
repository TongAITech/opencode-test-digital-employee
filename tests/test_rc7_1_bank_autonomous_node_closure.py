from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_node_adoption import AutonomousNodeAdoptionControl
from rc7_runtime.bank_autonomous_node_closure import (
    BankAutonomousNodeClosureCoordinator,
    BankAutonomousNodeClosureError,
)
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Mission,
    Task,
    TaskStatus,
)
from rc7_runtime.truth_overlay import append_entity


RELEASE = "RC7.1-BANK-NODE-CLOSURE"
MISSION = "MISSION-BANK-NODE-CLOSURE"
RUN = "RUN-BANK-NODE-CLOSURE"


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="prove BANK evaluated tasks become governed autonomous node truth",
        ),
    )
    return truth, control


def _seed_pass(
    truth: TruthRuntime,
    *,
    node_id: str,
    source_node: str,
    suffix: str,
    evaluator_ref: str = "independent-source-reviewer",
):
    task_id = "TASK-%s-%s" % (node_id, suffix)
    artifact_id = "ART-%s-%s" % (node_id, suffix)
    evidence_id = "EVD-%s-%s" % (node_id, suffix)
    evaluation_id = "EVAL-%s-%s" % (node_id, suffix)
    evidence = Evidence(
        evidence_id=evidence_id,
        mission_id=MISSION,
        kind="BANK_NODE_SOURCE_EVIDENCE",
        source_ref="runtime://bank-node-source",
        content_ref="evidence://%s" % evidence_id,
        subject_refs=[task_id, artifact_id],
    )
    artifact = Artifact(
        artifact_id=artifact_id,
        mission_id=MISSION,
        artifact_type="%s_RESULT" % source_node,
        producer_task_id=task_id,
        content_ref="artifact://%s" % artifact_id,
        evidence_refs=[evidence_id],
        content_hash="sha256:%s" % (suffix * 8)[:64],
    )
    evaluation = Evaluation(
        evaluation_id=evaluation_id,
        mission_id=MISSION,
        node=source_node,
        artifact_refs=[artifact_id],
        result=EvaluationResult.PASS,
        evaluator_ref=evaluator_ref,
        dimensions={"sufficiency": "PASS", "source_node": source_node},
        gap_refs=[],
        evidence_refs=[evidence_id],
    )
    task = Task(
        task_id=task_id,
        mission_id=MISSION,
        node=source_node,
        task_type="PRODUCE_AND_EVALUATE",
        objective="produce current evaluated %s result" % source_node,
        state=TaskStatus.PASS,
        lease_owner="worker-%s" % node_id.lower(),
        output_artifact_refs=[artifact_id],
        evaluation_id=evaluation_id,
    )
    for entity in (evidence, artifact, evaluation, task):
        append_entity(truth, entity, release_id=RELEASE)
    return task, evaluation


def _n6_spec():
    case = {
        "status": "FROZEN",
        "tc_id": "TC-N6-BANK-001",
        "case_version": 1,
        "release_id": RELEASE,
        "requirement_id": "REQ-001",
        "sst_id": "SST-001",
        "layer": "L3",
        "preconditions": [{"id": "PRE-AUTH", "description": "fresh auth"}],
        "steps": [
            {"order": 1, "action": "create request"},
            {"order": 2, "action": "submit request"},
        ],
        "expected": "business result saved",
        "oracle": {"type": "API_AND_STATE", "checks": ["code", "state"]},
        "evidence_requirements": ["REQUEST_RESPONSE", "CAT_CORRELATION"],
    }
    return ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-001",),
        test_data_refs=("DATA-LOAN",),
        oracle_refs=("ORACLE-API", "ORACLE-STATE"),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )


def _n6_matrix(spec, *, omit_step: bool = False):
    steps = [
        {"order": 1, "implementation_ref": "fn:test_case/step_1"},
        {"order": 2, "implementation_ref": "fn:test_case/step_2"},
    ]
    if omit_step:
        steps = steps[:1]
    return {
        "steps": steps,
        "oracles": [
            {"oracle_ref": ref, "assertion_ref": "assert:%s" % ref}
            for ref in spec.oracle_refs
        ],
        "runtime_bindings": [
            {"binding_ref": "PRE-AUTH", "injection_ref": "fixture:auth"},
            {"binding_ref": "DATA-LOAN", "injection_ref": "fixture:loan"},
        ],
        "evidence_collectors": [
            {"requirement": ref, "collector_ref": "collector:%s" % ref}
            for ref in spec.evidence_requirements
        ],
    }


def _seed_n6(
    truth: TruthRuntime,
    tmp_path: Path,
    *,
    omit_step: bool = False,
    task_type: str = "AGENT",
    fanout_status: str = "PASS",
):
    spec = _n6_spec()
    task_id = "TASK-N6-BANK"
    artifact_id = "ART-N6-BANK-SCRIPT"
    design_artifact_id = "ART-N6-BANK-DESIGN"
    candidate_evidence_id = "EVD-N6-BANK-CANDIDATE"
    evaluation_id = "EVAL-N6-BANK-READY"

    fanout_contract = Evidence(
        evidence_id="EVD-N6-BANK-FANOUT-CONTRACT",
        mission_id=MISSION,
        kind="CASE_FANOUT_CONTRACT",
        source_ref="runtime://case-fanout-contract/v1",
        content_ref="case-fanout://bank-n6-test",
        subject_refs=[task_id],
    )
    candidate_evidence = Evidence(
        evidence_id=candidate_evidence_id,
        mission_id=MISSION,
        kind="WORKER_CANDIDATE_RECORD",
        source_ref="dsh://worker/script-worker",
        content_ref="runtime://candidate/script",
        subject_refs=[task_id, artifact_id],
    )
    design_artifact = Artifact(
        artifact_id=design_artifact_id,
        mission_id=MISSION,
        artifact_type="TEST_DESIGN_MODEL",
        producer_task_id="TASK-DESIGN-N6-BANK",
        content_ref="artifact://n6-bank-design",
        evidence_refs=[],
        content_hash="sha256:" + "1" * 64,
    )
    semantic_payload = {
        "binding": {
            "spec_id": spec.spec_id,
            "tc_id": spec.tc_id,
            "case_version": spec.case_version,
            "runner_type": spec.runner_type,
            "case_fingerprint": spec.case_fingerprint,
            "oracle_fingerprint": spec.oracle_fingerprint,
            "design_content_hash": "sha256:design",
        },
        "source_text": (
            "def test_case(auth, loan):\n"
            "    response = submit(loan)\n"
            "    assert response is not None\n"
        ),
        "test_symbol": "test_case",
        "implementation_matrix": _n6_matrix(spec, omit_step=omit_step),
    }
    envelope = {
        "task_id": task_id,
        "artifact": {
            "artifact_id": artifact_id,
            "artifact_type": "SCRIPT_CANDIDATE",
        },
        "semantic_payload": semantic_payload,
    }
    candidate_path = tmp_path / "n6-bank-script-candidate.json"
    raw = (
        json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    candidate_path.write_bytes(raw)
    content_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    candidate_artifact = Artifact(
        artifact_id=artifact_id,
        mission_id=MISSION,
        artifact_type="SCRIPT_CANDIDATE",
        producer_task_id=task_id,
        content_ref="file://" + str(candidate_path),
        evidence_refs=[candidate_evidence_id],
        content_hash=content_hash,
    )
    evaluation = Evaluation(
        evaluation_id=evaluation_id,
        mission_id=MISSION,
        node="SCRIPT_READINESS",
        artifact_refs=[artifact_id],
        result=EvaluationResult.PASS,
        evaluator_ref="rc7-runtime-script-readiness-gate",
        dimensions={
            "gate_status": "SCRIPT_READY",
            "business_assertion_executed": False,
            "case_fingerprint": spec.case_fingerprint,
            "oracle_fingerprint": spec.oracle_fingerprint,
            "case_fanout_contract": fanout_status,
        },
        gap_refs=[],
        evidence_refs=[candidate_evidence_id],
    )
    task = Task(
        task_id=task_id,
        mission_id=MISSION,
        node="SCRIPT_READINESS",
        task_type=task_type,
        objective="produce aggregate BANK script readiness",
        state=TaskStatus.PASS,
        lease_owner="script-worker",
        input_artifact_refs=[design_artifact_id],
        output_artifact_refs=[artifact_id],
        evaluation_id=evaluation_id,
    )
    for entity in (
        fanout_contract,
        candidate_evidence,
        design_artifact,
        candidate_artifact,
        evaluation,
        task,
    ):
        append_entity(truth, entity, release_id=RELEASE)
    return task, spec


@pytest.mark.parametrize(
    "node_id,source_node",
    [
        ("N2", "REQUIREMENT_ANALYSIS"),
        ("N3", "CODE_ANALYSIS"),
        ("N4", "TEST_DESIGN"),
    ],
)
def test_bank_passed_task_is_reconciled_to_current_director_accepted_node(
    tmp_path: Path,
    node_id: str,
    source_node: str,
):
    truth, control = _control(tmp_path)
    task, evaluation = _seed_pass(
        truth,
        node_id=node_id,
        source_node=source_node,
        suffix=node_id.lower(),
    )
    coordinator = BankAutonomousNodeClosureCoordinator(
        release_id=RELEASE,
        run_id=RUN,
        evidence_root=str(tmp_path / "evidence"),
    )

    receipt = coordinator.reconcile_passed_task(
        control,
        node_id=node_id,
        source_task_id=task.task_id,
    )

    assert receipt.delivery.node_id == node_id
    assert receipt.source_evaluation_id == evaluation.evaluation_id
    accepted = [
        row
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "DIRECTOR_NODE_ACCEPTED"
        and row.get("data", {}).get("node_id") == node_id
        and row.get("data", {}).get("run_id") == RUN
    ]
    terminal = [
        row
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_TERMINAL"
        and row.get("data", {}).get("node_id") == node_id
        and row.get("data", {}).get("state") == "PASS"
    ]
    assert len(accepted) == 1
    assert len(terminal) == 1
    director_eval_id = accepted[0]["data"]["evaluation_id"]
    director_eval = truth.query(
        "rc7_evaluation", evaluation_id=director_eval_id
    )[0]
    assert director_eval["evaluator_ref"] == coordinator.DEFAULT_DIRECTOR_REF
    assert director_eval["evaluator_ref"] != evaluation.evaluator_ref
    assert director_eval["result"] == "PASS"


def test_reconciliation_is_restart_safe_and_does_not_duplicate_director_truth(
    tmp_path: Path,
):
    truth, control = _control(tmp_path)
    task, _ = _seed_pass(
        truth,
        node_id="N2",
        source_node="REQUIREMENT_ANALYSIS",
        suffix="restart",
    )
    first = BankAutonomousNodeClosureCoordinator(
        release_id=RELEASE,
        run_id=RUN,
        evidence_root=str(tmp_path / "evidence"),
    )
    first.reconcile_passed_task(
        control,
        node_id="N2",
        source_task_id=task.task_id,
    )

    recreated = BankAutonomousNodeClosureCoordinator(
        release_id=RELEASE,
        run_id=RUN,
        evidence_root=str(tmp_path / "evidence"),
    )
    receipt = recreated.reconcile_passed_task(
        control,
        node_id="N2",
        source_task_id=task.task_id,
    )

    assert receipt.recovered is True
    assert receipt.director_decision is None
    accepted = [
        row
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "DIRECTOR_NODE_ACCEPTED"
        and row.get("data", {}).get("node_id") == "N2"
    ]
    terminal = [
        row
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_TERMINAL"
        and row.get("data", {}).get("node_id") == "N2"
    ]
    assert len(accepted) == 1
    assert len(terminal) == 1


def test_existing_iteration_with_different_source_cannot_be_silently_rewritten(
    tmp_path: Path,
):
    truth, control = _control(tmp_path)
    task, _ = _seed_pass(
        truth,
        node_id="N3",
        source_node="CODE_ANALYSIS",
        suffix="drift",
    )
    adoption = AutonomousNodeAdoptionControl(
        truth,
        release_id=RELEASE,
        evidence_root=str(tmp_path / "evidence"),
    )
    adoption.node_control.start_iteration(
        mission_id=MISSION,
        run_id=RUN,
        node_id="N3",
        input_version="stale-input-version",
        delta_hash="sha256:stale-delta-v1",
    )

    with pytest.raises(
        BankAutonomousNodeClosureError,
        match="BANK_NODE_SOURCE_CHANGED_REQUIRES_DURABLE_REPAIR:N3",
    ):
        BankAutonomousNodeClosureCoordinator(
            release_id=RELEASE,
            run_id=RUN,
            evidence_root=str(tmp_path / "evidence"),
        ).reconcile_passed_task(
            control,
            node_id="N3",
            source_task_id=task.task_id,
        )


def test_director_identity_cannot_reuse_source_evaluator_identity(tmp_path: Path):
    truth, control = _control(tmp_path)
    task, _ = _seed_pass(
        truth,
        node_id="N4",
        source_node="TEST_DESIGN",
        suffix="self-review",
        evaluator_ref=BankAutonomousNodeClosureCoordinator.DEFAULT_DIRECTOR_REF,
    )

    with pytest.raises(
        BankAutonomousNodeClosureError,
        match="BANK_NODE_DIRECTOR_CANNOT_REUSE_SOURCE_EVALUATOR:N4",
    ):
        BankAutonomousNodeClosureCoordinator(
            release_id=RELEASE,
            run_id=RUN,
            evidence_root=str(tmp_path / "evidence"),
        ).reconcile_passed_task(
            control,
            node_id="N4",
            source_task_id=task.task_id,
        )


def test_bank_convergence_reconciles_aggregate_script_pass_to_n6_director_accept(
    tmp_path: Path,
    monkeypatch,
):
    truth, control = _control(tmp_path)
    task, spec = _seed_n6(truth, tmp_path)
    coordinator = BankAutonomousNodeClosureCoordinator(
        release_id=RELEASE,
        run_id=RUN,
        evidence_root=str(tmp_path / "evidence"),
    )
    monkeypatch.setattr(
        coordinator.script_compiler,
        "compile",
        lambda *args, **kwargs: SimpleNamespace(spec=spec),
    )

    receipts = coordinator.reconcile_passed_nodes(control)

    n6 = [receipt for receipt in receipts if receipt.node_id == "N6"]
    assert len(n6) == 1
    assert n6[0].source_task_id == task.task_id
    accepted = [
        row
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "DIRECTOR_NODE_ACCEPTED"
        and row.get("data", {}).get("node_id") == "N6"
        and row.get("data", {}).get("run_id") == RUN
    ]
    terminal = [
        row
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_TERMINAL"
        and row.get("data", {}).get("node_id") == "N6"
        and row.get("data", {}).get("state") == "PASS"
    ]
    assert len(accepted) == 1
    assert len(terminal) == 1

    restarted = BankAutonomousNodeClosureCoordinator(
        release_id=RELEASE,
        run_id=RUN,
        evidence_root=str(tmp_path / "evidence"),
    )
    monkeypatch.setattr(
        restarted.script_compiler,
        "compile",
        lambda *args, **kwargs: SimpleNamespace(spec=spec),
    )
    again = restarted.reconcile_passed_nodes(control)
    recovered_n6 = [receipt for receipt in again if receipt.node_id == "N6"]
    assert len(recovered_n6) == 1
    assert recovered_n6[0].recovered is True
    assert recovered_n6[0].director_decision is None
    assert len([
        row for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "DIRECTOR_NODE_ACCEPTED"
        and row.get("data", {}).get("node_id") == "N6"
    ]) == 1
    assert len([
        row for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_TERMINAL"
        and row.get("data", {}).get("node_id") == "N6"
    ]) == 1


def test_bank_n6_incomplete_matrix_fails_closed_before_director(
    tmp_path: Path,
    monkeypatch,
):
    truth, control = _control(tmp_path)
    _task, spec = _seed_n6(truth, tmp_path, omit_step=True)
    coordinator = BankAutonomousNodeClosureCoordinator(
        release_id=RELEASE,
        run_id=RUN,
        evidence_root=str(tmp_path / "evidence"),
    )
    monkeypatch.setattr(
        coordinator.script_compiler,
        "compile",
        lambda *args, **kwargs: SimpleNamespace(spec=spec),
    )

    with pytest.raises(
        BankAutonomousNodeClosureError,
        match="BANK_N6_SEMANTIC_GATE_FAILED:N6_SEMANTIC_IMPLEMENTATION_INCOMPLETE",
    ):
        coordinator.reconcile_passed_nodes(control)

    gaps = [
        row for row in truth.query("rc7_gap", mission_id=MISSION)
        if row.get("category") == "SCRIPT_IMPLEMENTATION_COVERAGE_GAP"
    ]
    assert len(gaps) == 1
    assert "SCRIPT_MATRIX_MISSING:steps:2" in gaps[0]["description"]
    assert not [
        row for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "DIRECTOR_NODE_ACCEPTED"
        and row.get("data", {}).get("node_id") == "N6"
    ]
    assert not [
        row for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_TERMINAL"
        and row.get("data", {}).get("node_id") == "N6"
    ]


def test_bank_n6_repair_task_cannot_close_node(tmp_path: Path):
    truth, control = _control(tmp_path)
    _seed_n6(truth, tmp_path, task_type="REPAIR")
    coordinator = BankAutonomousNodeClosureCoordinator(
        release_id=RELEASE,
        run_id=RUN,
        evidence_root=str(tmp_path / "evidence"),
    )

    receipts = coordinator.reconcile_passed_nodes(control)

    assert not [receipt for receipt in receipts if receipt.node_id == "N6"]
    assert not [
        row for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("data", {}).get("node_id") == "N6"
        and row.get("event_type_name") in {"NODE_READY_FOR_DIRECTOR_REVIEW", "DIRECTOR_NODE_ACCEPTED", "NODE_TERMINAL"}
    ]


def test_bank_n6_requires_aggregate_case_fanout_pass(tmp_path: Path):
    truth, control = _control(tmp_path)
    _seed_n6(truth, tmp_path, fanout_status="INCOMPLETE")
    coordinator = BankAutonomousNodeClosureCoordinator(
        release_id=RELEASE,
        run_id=RUN,
        evidence_root=str(tmp_path / "evidence"),
    )

    with pytest.raises(
        BankAutonomousNodeClosureError,
        match="BANK_N6_CASE_FANOUT_PASS_REQUIRED",
    ):
        coordinator.reconcile_passed_nodes(control)

    assert not [
        row for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("data", {}).get("node_id") == "N6"
        and row.get("event_type_name") in {"NODE_READY_FOR_DIRECTOR_REVIEW", "DIRECTOR_NODE_ACCEPTED", "NODE_TERMINAL"}
    ]
