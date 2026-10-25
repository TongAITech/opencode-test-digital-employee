from __future__ import annotations

from pathlib import Path

import pytest

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
