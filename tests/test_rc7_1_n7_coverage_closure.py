from __future__ import annotations

import json

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_coverage_closure import (
    AutonomousCoverageClosureError,
    AutonomousCoverageClosureService,
)
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Evidence, Mission
from rc7_runtime.truth_overlay import append_entity


RELEASE = "RC7.1-WAVE-D-N7"
MISSION = "MISSION-RC7-1-N7-COVERAGE"
RUN = "RUN-RC7-1-N7-COVERAGE"
TARGET = "PFC-CHANGE-SET"


def _setup(tmp_path):
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    append_entity(truth, Mission(mission_id=MISSION, release_id=RELEASE, goal="N7 coverage closure"), release_id=RELEASE)
    evidence = Evidence(
        evidence_id="EVD-N7-SCOPE",
        mission_id=MISSION,
        kind="COVERAGE_SCOPE_PROOF",
        source_ref="runtime://coverage/scope",
        content_ref="runtime://coverage/scope/change-set",
        subject_refs=[RUN, TARGET],
    )
    append_entity(truth, evidence, release_id=RELEASE)
    return truth, ClosedLoopControlPlane(truth, RELEASE, MISSION), evidence.evidence_id


def _execution_evidence(truth, *, evidence_id, content_ref, subject):
    evidence = Evidence(
        evidence_id=evidence_id,
        mission_id=MISSION,
        kind="REAL_EXECUTION_COVERAGE",
        source_ref="runtime://execution/coverage",
        content_ref=content_ref,
        subject_refs=[subject],
    )
    append_entity(truth, evidence, release_id=RELEASE)
    return evidence_id


def _payload(truth, artifact_id):
    row = truth.query("rc7_artifact", artifact_id=artifact_id)[0]
    with open(row["content_ref"][len("file://"):], "r", encoding="utf-8") as handle:
        return json.load(handle)


def test_covered_fail_closes_coverage_without_claiming_quality_pass(tmp_path) -> None:
    truth, control, scope_evidence = _setup(tmp_path)
    service = AutonomousCoverageClosureService(evidence_root=str(tmp_path / "evidence"))
    denominator = service.freeze_denominator(
        control,
        run_id=RUN,
        layer="L1",
        source_revision="commit:abc123",
        target_id=TARGET,
        obligation_ids=["LINE:LoanService:10", "LOGIC:LoanService:approved:true"],
        evidence_refs=[scope_evidence],
    )
    pass_evidence = _execution_evidence(
        truth,
        evidence_id="EVD-N7-PASS",
        content_ref="runtime://jacoco/line-10",
        subject="LINE:LoanService:10",
    )
    fail_evidence = _execution_evidence(
        truth,
        evidence_id="EVD-N7-PRODUCT-FAIL",
        content_ref="runtime://junit/business-assertion-fail",
        subject="LOGIC:LoanService:approved:true",
    )
    receipt = service.reconcile_layer(
        control,
        run_id=RUN,
        denominator=denominator,
        updates={
            "LINE:LoanService:10": {"state": "COVERED_PASS", "evidence_refs": [pass_evidence]},
            "LOGIC:LoanService:approved:true": {
                "state": "COVERED_FAIL",
                "cause": "PRODUCT",
                "evidence_refs": [fail_evidence],
            },
        },
        metrics={"line_coverage": 1.0, "logic_coverage": 1.0},
    )
    assert receipt.receipt.status == "READY"
    assert receipt.receipt.covered == receipt.receipt.total == 2
    assert receipt.receipt.covered_fail == 1
    payload = _payload(truth, receipt.artifact_id)
    assert payload["quality_pass_required"] is False
    assert payload["receipt"]["covered_fail"] == 1


def test_denominator_cannot_shrink_and_expansion_reopens_layer(tmp_path) -> None:
    truth, control, scope_evidence = _setup(tmp_path)
    service = AutonomousCoverageClosureService(evidence_root=str(tmp_path / "evidence"))
    v1 = service.freeze_denominator(
        control,
        run_id=RUN,
        layer="L3",
        source_revision="commit:abc123",
        target_id=TARGET,
        obligation_ids=["API:POST:/loan", "API:GET:/loan/{id}"],
        evidence_refs=[scope_evidence],
    )
    with pytest.raises(AutonomousCoverageClosureError, match="COVERAGE_DENOMINATOR_SHRINK_FORBIDDEN"):
        service.freeze_denominator(
            control,
            run_id=RUN,
            layer="L3",
            source_revision="commit:abc123",
            target_id=TARGET,
            obligation_ids=["API:POST:/loan"],
            evidence_refs=[scope_evidence],
        )
    v2 = service.freeze_denominator(
        control,
        run_id=RUN,
        layer="L3",
        source_revision="commit:abc123",
        target_id=TARGET,
        obligation_ids=["API:POST:/loan", "API:GET:/loan/{id}", "API:DELETE:/loan/{id}"],
        evidence_refs=[scope_evidence],
        discovered_from_layer="L5",
    )
    assert v1.snapshot.denominator_version == "v0001"
    assert v2.snapshot.denominator_version == "v0002"
    assert v1.snapshot.denominator_hash != v2.snapshot.denominator_hash
    reopened = [
        row for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "LAYER_REOPENED"
        and row.get("data", {}).get("layer") == "L3"
    ]
    assert len(reopened) == 1
    assert reopened[0]["data"]["current_version"] == "v0002"


def test_uncovered_obligation_routes_exact_delta_to_real_owner(tmp_path) -> None:
    truth, control, scope_evidence = _setup(tmp_path)
    service = AutonomousCoverageClosureService(evidence_root=str(tmp_path / "evidence"))
    denominator = service.freeze_denominator(
        control,
        run_id=RUN,
        layer="L4",
        source_revision="commit:abc123",
        target_id=TARGET,
        obligation_ids=["UI:submit:valid", "UI:submit:insufficient-data"],
        evidence_refs=[scope_evidence],
    )
    pass_evidence = _execution_evidence(
        truth,
        evidence_id="EVD-N7-UI-PASS",
        content_ref="runtime://browser/network/submit-valid",
        subject="UI:submit:valid",
    )
    receipt = service.reconcile_layer(
        control,
        run_id=RUN,
        denominator=denominator,
        updates={
            "UI:submit:valid": {"state": "COVERED_PASS", "evidence_refs": [pass_evidence]},
            "UI:submit:insufficient-data": {
                "state": "UNEXECUTED",
                "cause": "DATA",
                "evidence_refs": [scope_evidence],
            },
        },
        metrics={"mandatory_ui_obligation_coverage": 1.0},
    )
    assert receipt.receipt.status == "IN_PROGRESS"
    assert receipt.delta_plan_artifact_id
    gaps = [
        row for row in truth.query("rc7_gap", mission_id=MISSION)
        if row.get("category") == "COVERAGE_GAP_DATA"
    ]
    assert len(gaps) == 1
    assert gaps[0]["target_node"] == "TEST_DATA_PREPARATION"
    delta = _payload(truth, receipt.delta_plan_artifact_id)
    assert delta["delta_only"] is True
    assert delta["closed_obligations_must_not_rerun"] is True
    assert [row["obligation_id"] for row in delta["open_obligations"]] == ["UI:submit:insufficient-data"]
    assert delta["open_obligations"][0]["target_nodes"] == ["TEST_DATA_PREPARATION"]


def test_l1_metrics_must_reach_100_percent_even_if_cases_closed(tmp_path) -> None:
    truth, control, scope_evidence = _setup(tmp_path)
    service = AutonomousCoverageClosureService(evidence_root=str(tmp_path / "evidence"))
    denominator = service.freeze_denominator(
        control,
        run_id=RUN,
        layer="L1",
        source_revision="commit:abc123",
        target_id=TARGET,
        obligation_ids=["LINE:1", "LOGIC:1:T"],
        evidence_refs=[scope_evidence],
    )
    execution_evidence = _execution_evidence(
        truth,
        evidence_id="EVD-N7-L1-MEASURE",
        content_ref="runtime://jacoco/report",
        subject="L1",
    )
    receipt = service.reconcile_layer(
        control,
        run_id=RUN,
        denominator=denominator,
        updates={
            "LINE:1": {"state": "COVERED_PASS", "evidence_refs": [execution_evidence]},
            "LOGIC:1:T": {"state": "COVERED_PASS", "evidence_refs": [execution_evidence]},
        },
        metrics={"line_coverage": 1.0, "logic_coverage": 0.9},
    )
    assert receipt.receipt.covered == receipt.receipt.total == 2
    assert receipt.receipt.status == "IN_PROGRESS"
    metric_gaps = [
        row for row in truth.query("rc7_gap", mission_id=MISSION)
        if "METRIC:logic_coverage" in set(str(x) for x in row.get("subject_refs") or [])
    ]
    assert len(metric_gaps) == 1
    assert metric_gaps[0]["target_node"] == "EXECUTION"
