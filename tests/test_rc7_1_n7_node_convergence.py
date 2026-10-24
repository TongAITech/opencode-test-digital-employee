from __future__ import annotations

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_contract import CANONICAL_COVERAGE_TARGETS, CanonicalLayer
from rc7_runtime.autonomous_n7_node import AutonomousN7NodeError, AutonomousN7NodeService, WaveDNodeAdoptionControl
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Evidence, Mission
from rc7_runtime.truth_overlay import append_entity


RELEASE = "RC7.1-WAVE-D-N7-NODE"
MISSION = "MISSION-RC7-1-N7-NODE"
RUN = "RUN-RC7-1-N7-NODE"


def _setup(tmp_path):
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    append_entity(truth, Mission(mission_id=MISSION, release_id=RELEASE, goal="N7 all-layer convergence"), release_id=RELEASE)
    scope = Evidence(
        evidence_id="EVD-N7-NODE-SCOPE",
        mission_id=MISSION,
        kind="COVERAGE_SCOPE_PROOF",
        source_ref="runtime://coverage/scope",
        content_ref="runtime://coverage/current-change-set",
        subject_refs=[RUN],
    )
    append_entity(truth, scope, release_id=RELEASE)
    return truth, ClosedLoopControlPlane(truth, RELEASE, MISSION), scope.evidence_id


def _exec_evidence(truth, layer, suffix="1"):
    evidence_id = "EVD-%s-EXEC-%s" % (layer, suffix)
    if not truth.query("rc7_evidence", evidence_id=evidence_id):
        append_entity(
            truth,
            Evidence(
                evidence_id=evidence_id,
                mission_id=MISSION,
                kind="REAL_EXECUTION_COVERAGE",
                source_ref="runtime://execution/%s" % layer.lower(),
                content_ref="runtime://coverage/%s/%s" % (layer.lower(), suffix),
                subject_refs=[layer, suffix],
            ),
            release_id=RELEASE,
        )
    return evidence_id


def _ready_all(service, truth, control, scope):
    denominators = {}
    receipts = {}
    for layer_enum in CanonicalLayer:
        layer = layer_enum.value
        denominator = service.freeze_denominator(
            control,
            run_id=RUN,
            layer=layer,
            source_revision="commit:abc123",
            target_id="TARGET-%s" % layer,
            obligation_ids=["%s:OBLIGATION:1" % layer],
            evidence_refs=[scope],
        )
        evidence_id = _exec_evidence(truth, layer)
        state = "COVERED_FAIL" if layer == "L6" else "COVERED_PASS"
        receipt = service.reconcile_layer(
            control,
            run_id=RUN,
            denominator=denominator,
            updates={
                "%s:OBLIGATION:1" % layer: {
                    "state": state,
                    "evidence_refs": [evidence_id],
                },
            },
            metrics=dict(CANONICAL_COVERAGE_TARGETS[layer_enum]),
        )
        denominators[layer] = denominator
        receipts[layer] = receipt
    return denominators, receipts


def test_n7_requires_all_current_layers_then_director_gate(tmp_path) -> None:
    truth, control, scope = _setup(tmp_path)
    service = AutonomousN7NodeService(evidence_root=str(tmp_path / "evidence"))
    _denominators, receipts = _ready_all(service, truth, control, scope)

    delivery = service.publish_ready(control, run_id=RUN, receipts=list(receipts.values()))
    assert delivery.node_id == "N7"
    assert delivery.iteration_count == 1
    assert not [
        row for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_TERMINAL" and row.get("data", {}).get("node_id") == "N7"
    ]

    decision = WaveDNodeAdoptionControl(
        truth,
        release_id=RELEASE,
        evidence_root=str(tmp_path / "evidence"),
    ).director_accept(
        mission_id=MISSION,
        run_id=RUN,
        node_id="N7",
        director_ref="director-runtime-authority",
    )
    assert decision.accepted is True

    task_rows = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "EXECUTION" and row.get("objective") == "close current L1-L7 coverage denominators"
    ]
    assert len(task_rows) == 1
    evaluation = truth.query("rc7_evaluation", evaluation_id=task_rows[0]["evaluation_id"])[0]
    assert evaluation["dimensions"]["covered_fail_total"] == 1
    assert evaluation["dimensions"]["product_quality_pass_required"] is False


def test_n7_rejects_missing_layer_receipt(tmp_path) -> None:
    truth, control, scope = _setup(tmp_path)
    service = AutonomousN7NodeService(evidence_root=str(tmp_path / "evidence"))
    _denominators, receipts = _ready_all(service, truth, control, scope)
    receipts.pop("L7")
    with pytest.raises(AutonomousN7NodeError, match="N7_ALL_CANONICAL_LAYER_RECEIPTS_REQUIRED"):
        service.publish_ready(control, run_id=RUN, receipts=list(receipts.values()))


def test_denominator_expansion_invalidates_old_receipt_and_opens_new_n7_iteration(tmp_path) -> None:
    truth, control, scope = _setup(tmp_path)
    service = AutonomousN7NodeService(evidence_root=str(tmp_path / "evidence"))
    denominators, receipts = _ready_all(service, truth, control, scope)
    first = service.publish_ready(control, run_id=RUN, receipts=list(receipts.values()))
    WaveDNodeAdoptionControl(
        truth,
        release_id=RELEASE,
        evidence_root=str(tmp_path / "evidence"),
    ).director_accept(
        mission_id=MISSION,
        run_id=RUN,
        node_id="N7",
        director_ref="director-runtime-authority",
    )
    assert first.iteration_count == 1

    expanded = service.freeze_denominator(
        control,
        run_id=RUN,
        layer="L3",
        source_revision="commit:abc123",
        target_id="TARGET-L3",
        obligation_ids=["L3:OBLIGATION:1", "L3:OBLIGATION:2"],
        evidence_refs=[scope],
        discovered_from_layer="L5",
    )
    assert expanded.snapshot.denominator_version == "v0002"
    n7_tasks = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("objective") == "close current L1-L7 coverage denominators"
    ]
    assert len(n7_tasks) == 1
    assert n7_tasks[0]["state"] == "READY"

    with pytest.raises(AutonomousN7NodeError, match="N7_STALE_LAYER_RECEIPT:L3"):
        service.publish_ready(control, run_id=RUN, receipts=list(receipts.values()))

    e1 = _exec_evidence(truth, "L3", "v2-existing")
    e2 = _exec_evidence(truth, "L3", "v2-new")
    receipts["L3"] = service.reconcile_layer(
        control,
        run_id=RUN,
        denominator=expanded,
        updates={
            "L3:OBLIGATION:1": {"state": "COVERED_PASS", "evidence_refs": [e1]},
            "L3:OBLIGATION:2": {"state": "COVERED_PASS", "evidence_refs": [e2]},
        },
        metrics={"mandatory_api_obligation_coverage": 1.0},
    )
    second = service.publish_ready(control, run_id=RUN, receipts=list(receipts.values()))
    assert second.iteration_count == 2
    gap_events = [
        row for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_GAP_DETECTED"
        and row.get("data", {}).get("node_id") == "N7"
    ]
    assert any("GAP-N7-DENOM-EXPANDED" in str(gap_id) for row in gap_events for gap_id in row["data"]["gap_ids"])
