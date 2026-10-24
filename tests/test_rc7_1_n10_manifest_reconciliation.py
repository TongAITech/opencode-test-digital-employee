from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_contract import (
    CANONICAL_COVERAGE_TARGETS,
    CANONICAL_LAYER_IDS,
    CanonicalLayer,
    NodeDeliveryPackage,
    NodeLoopState,
)
from rc7_runtime.autonomous_coverage_closure import AutonomousCoverageClosureService
from rc7_runtime.autonomous_events import AutonomousEvent
from rc7_runtime.autonomous_mission_manifest import (
    AutonomousMissionEvidenceManifestBuilder,
    MissionEvidenceManifestError,
)
from rc7_runtime.autonomous_node_control import AutonomousNodeControl
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    EventRecord,
    Evidence,
    Mission,
)
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-N10-RECONCILE"
RELEASE = "RC7.1-N10"
RUN = "RUN-N10"


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="reconcile current N1-N9 and L1-L7 truth",
        ),
    )
    return truth, control


def _source_truth(control: ClosedLoopControlPlane, node_id: str):
    evidence = Evidence(
        evidence_id="EVD-SOURCE-" + node_id,
        mission_id=MISSION,
        kind="NODE_SOURCE_EVIDENCE",
        source_ref="runtime://n10-test",
        content_ref="evidence://node/" + node_id,
        subject_refs=[node_id],
    )
    artifact = Artifact(
        artifact_id="ART-SOURCE-" + node_id,
        mission_id=MISSION,
        artifact_type="NODE_SOURCE_OUTPUT",
        producer_task_id="TASK-SOURCE-" + node_id,
        content_ref="artifact://node/" + node_id,
        evidence_refs=[evidence.evidence_id],
    )
    append_entity(control.truth, evidence, release_id=RELEASE)
    append_entity(control.truth, artifact, release_id=RELEASE)
    return artifact.artifact_id, evidence.evidence_id


def _coverage_truth(tmp_path: Path, control: ClosedLoopControlPlane):
    service = AutonomousCoverageClosureService(evidence_root=str(tmp_path / "coverage"))
    summaries = {}
    receipts = {}
    for layer in CANONICAL_LAYER_IDS:
        source_evidence = Evidence(
            evidence_id="EVD-DENOM-" + layer,
            mission_id=MISSION,
            kind="COVERAGE_SCOPE_EVIDENCE",
            source_ref="runtime://coverage-scope",
            content_ref="evidence://coverage/" + layer,
            subject_refs=[RUN, layer],
        )
        result_evidence = Evidence(
            evidence_id="EVD-COVERAGE-" + layer,
            mission_id=MISSION,
            kind="COVERAGE_MEASUREMENT",
            source_ref="runtime://coverage-measurement",
            content_ref="evidence://coverage-result/" + layer,
            subject_refs=[RUN, layer],
        )
        append_entity(control.truth, source_evidence, release_id=RELEASE)
        append_entity(control.truth, result_evidence, release_id=RELEASE)
        obligation_id = "OBL-%s-1" % layer
        denominator = service.freeze_denominator(
            control,
            run_id=RUN,
            layer=layer,
            source_revision="git:abc123",
            target_id="TARGET-" + layer,
            obligation_ids=[obligation_id],
            evidence_refs=[source_evidence.evidence_id],
        )
        state = "COVERED_FAIL" if layer == "L3" else "COVERED_PASS"
        metrics = {
            name: float(target)
            for name, target in CANONICAL_COVERAGE_TARGETS[CanonicalLayer(layer)].items()
        }
        receipt = service.reconcile_layer(
            control,
            run_id=RUN,
            denominator=denominator,
            updates={
                obligation_id: {
                    "state": state,
                    "evidence_refs": [result_evidence.evidence_id],
                }
            },
            metrics=metrics,
        )
        assert receipt.receipt.status == "READY"
        receipts[layer] = (service, denominator, receipt)
        summaries[layer] = {
            "target_id": receipt.receipt.target_id,
            "denominator_version": receipt.receipt.denominator_version,
            "denominator_hash": receipt.receipt.denominator_hash,
            "covered": receipt.receipt.covered,
            "total": receipt.receipt.total,
            "covered_pass": receipt.receipt.covered_pass,
            "covered_fail": receipt.receipt.covered_fail,
            "excluded_with_evidence": receipt.receipt.excluded_with_evidence,
            "metrics": dict(receipt.metrics),
        }
    return summaries, receipts


def _director_accept_current(
    control: ClosedLoopControlPlane,
    node_control: AutonomousNodeControl,
    *,
    node_id: str,
    coverage_summary=None,
):
    source_artifact, source_evidence = _source_truth(control, node_id)
    iteration = node_control.start_iteration(
        mission_id=MISSION,
        run_id=RUN,
        node_id=node_id,
        input_version="input-" + node_id,
        delta_hash="sha256:delta-" + node_id,
    )
    package = NodeDeliveryPackage(
        mission_id=MISSION,
        run_id=RUN,
        node_id=node_id,
        input_version=iteration.input_version,
        iteration_count=iteration.iteration_count,
        artifact_refs=(source_artifact,),
        evidence_refs=(source_evidence,),
        unresolved_gap_ids=(),
        blocked_item_ids=(),
        terminal_status=NodeLoopState.READY_FOR_DIRECTOR_REVIEW.value,
        r1_refs=(iteration.start_event_id,),
        coverage_summary=coverage_summary or {},
        reviewer_result={"result": "PASS"},
        sufficiency_result={"result": "PASS"},
    )
    delivery = node_control.ready_for_director_review(
        iteration,
        package,
        producer_task_id="TASK-SOURCE-" + node_id,
    )
    evaluation_id = "EVAL-DIRECTOR-" + node_id
    append_entity(
        control.truth,
        Evaluation(
            evaluation_id=evaluation_id,
            mission_id=MISSION,
            node="AUTONOMOUS_NODE_GATE",
            artifact_refs=[delivery.package_artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="director-n10",
            dimensions={
                "node_id": node_id,
                "iteration_count": iteration.iteration_count,
                "decision": "ACCEPT",
            },
            evidence_refs=[delivery.package_evidence_id],
        ),
        release_id=RELEASE,
        artifact_version=iteration.iteration_count,
    )
    accept_id = "EVT-DIRECTOR-ACCEPT-" + node_id
    append_entity(
        control.truth,
        EventRecord(
            event_id=accept_id,
            mission_id=MISSION,
            event_type=AutonomousEvent.DIRECTOR_NODE_ACCEPTED.value,
            subject_type=AutonomousNodeControl.SUBJECT_TYPE,
            subject_id=AutonomousNodeControl._subject_id(RUN, node_id),
            refs=[delivery.ready_event_id, delivery.package_artifact_id, evaluation_id],
            data={
                "run_id": RUN,
                "node_id": node_id,
                "iteration_count": iteration.iteration_count,
                "director_ref": "director-n10",
                "evaluation_id": evaluation_id,
                "state": "PASS",
            },
        ),
        release_id=RELEASE,
        artifact_version=iteration.iteration_count,
    )
    append_entity(
        control.truth,
        EventRecord(
            event_id="EVT-NODE-TERMINAL-" + node_id,
            mission_id=MISSION,
            event_type=AutonomousEvent.NODE_TERMINAL.value,
            subject_type=AutonomousNodeControl.SUBJECT_TYPE,
            subject_id=AutonomousNodeControl._subject_id(RUN, node_id),
            refs=[accept_id, evaluation_id],
            data={
                "run_id": RUN,
                "node_id": node_id,
                "iteration_count": iteration.iteration_count,
                "state": "PASS",
                "evaluation_id": evaluation_id,
            },
        ),
        release_id=RELEASE,
        artifact_version=iteration.iteration_count,
    )
    return iteration, delivery


def _seed_all(tmp_path: Path, control: ClosedLoopControlPlane):
    summaries, receipts = _coverage_truth(tmp_path, control)
    node_control = AutonomousNodeControl(
        control.truth,
        release_id=RELEASE,
        evidence_root=str(tmp_path / "node-delivery"),
    )
    seeded = {}
    for number in range(1, 10):
        node_id = "N%d" % number
        seeded[node_id] = _director_accept_current(
            control,
            node_control,
            node_id=node_id,
            coverage_summary=summaries if node_id == "N7" else None,
        )
    return node_control, seeded, summaries, receipts


def test_n10_reconciles_only_current_director_accepted_n1_n9(tmp_path: Path):
    _, control = _control(tmp_path)
    _, _, _, _ = _seed_all(tmp_path, control)
    builder = AutonomousMissionEvidenceManifestBuilder(evidence_root=str(tmp_path / "manifest"))
    nodes = builder.reconcile_node_deliveries(control, run_id=RUN)
    assert tuple(sorted(nodes)) == tuple("N%d" % number for number in range(1, 10))
    assert all(nodes[node]["package"]["terminal_status"] == "READY_FOR_DIRECTOR_REVIEW" for node in nodes)
    assert all(nodes[node]["director_evaluation_id"].startswith("EVAL-DIRECTOR-") for node in nodes)


def test_newer_iteration_invalidates_previous_director_accept(tmp_path: Path):
    _, control = _control(tmp_path)
    node_control, seeded, _, _ = _seed_all(tmp_path, control)
    prior, _ = seeded["N3"]
    node_control.record_repair_completed(
        prior,
        repair_refs=["repair://n3/new-input"],
        delta_hash="sha256:n3-new-delta",
    )
    node_control.start_iteration(
        mission_id=MISSION,
        run_id=RUN,
        node_id="N3",
        input_version="input-N3-v2",
        delta_hash="sha256:n3-v2",
    )
    with pytest.raises(MissionEvidenceManifestError, match="N10_STALE_NODE_DELIVERY:N3"):
        AutonomousMissionEvidenceManifestBuilder(
            evidence_root=str(tmp_path / "manifest")
        ).reconcile_node_deliveries(control, run_id=RUN)


def test_n10_layer_reconciliation_preserves_covered_fail_as_closed_coverage(tmp_path: Path):
    _, control = _control(tmp_path)
    _, _, _, _ = _seed_all(tmp_path, control)
    builder = AutonomousMissionEvidenceManifestBuilder(evidence_root=str(tmp_path / "manifest"))
    nodes = builder.reconcile_node_deliveries(control, run_id=RUN)
    layers = builder.reconcile_layer_coverage(
        control,
        run_id=RUN,
        n7_package=nodes["N7"]["package"],
    )
    assert set(layers) == set(CANONICAL_LAYER_IDS)
    assert layers["L3"]["covered_fail"] == 1
    assert layers["L3"]["covered"] == layers["L3"]["total"] == 1
    assert all(layers[layer]["status"] == "READY" for layer in layers)


def test_denominator_expansion_makes_old_n7_summary_stale(tmp_path: Path):
    _, control = _control(tmp_path)
    _, _, _, receipts = _seed_all(tmp_path, control)
    builder = AutonomousMissionEvidenceManifestBuilder(evidence_root=str(tmp_path / "manifest"))
    nodes = builder.reconcile_node_deliveries(control, run_id=RUN)

    service, old_denominator, _ = receipts["L5"]
    new_scope = Evidence(
        evidence_id="EVD-DENOM-L5-EXPANDED",
        mission_id=MISSION,
        kind="COVERAGE_SCOPE_EVIDENCE",
        source_ref="runtime://coverage-scope",
        content_ref="evidence://coverage/L5/expanded",
        subject_refs=[RUN, "L5"],
    )
    append_entity(control.truth, new_scope, release_id=RELEASE)
    expanded = service.freeze_denominator(
        control,
        run_id=RUN,
        layer="L5",
        source_revision=old_denominator.snapshot.source_revision,
        target_id=old_denominator.snapshot.target_id,
        obligation_ids=list(old_denominator.snapshot.obligation_ids) + ["OBL-L5-NEW"],
        evidence_refs=[new_scope.evidence_id],
        discovered_from_layer="L7",
    )
    assert expanded.snapshot.denominator_version != old_denominator.snapshot.denominator_version

    with pytest.raises(MissionEvidenceManifestError, match="N10_STALE_N7_LAYER_SUMMARY:L5"):
        builder.reconcile_layer_coverage(
            control,
            run_id=RUN,
            n7_package=nodes["N7"]["package"],
        )
