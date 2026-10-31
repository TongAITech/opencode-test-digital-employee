from pathlib import Path

import pytest

from rc7_runtime.rc72_n3_completion import N3DeliveryGateService
from rc7_runtime.rc72_n4_parent_truth import N4ParentTruthError, N4ParentTruthService
from rc7_runtime.test_obligation_inventory import ParentDerivedTestObligationInventory

from rc72_n2_test_support import BATCH, COMMIT, MISSION, REQUIREMENTS
from test_rc72_n3_completion import _review_gate_ready


def test_n4_parent_truth_is_forbidden_before_n3_node_gate_pass(tmp_path: Path, monkeypatch):
    truth, _row, _promoted, _reviewed = _review_gate_ready(tmp_path, monkeypatch)

    with pytest.raises(N4ParentTruthError, match="N4_NOT_ADMITTED"):
        N4ParentTruthService(truth).resolve(release_batch_id=BATCH)

    n3 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    )[0]
    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    assert n3["state"] == "RUNNING"
    assert n4["state"] == "NOT_STARTED"
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    ) == []


def test_n4_parent_truth_uses_only_active_pass_n2_n3_deliveries_and_nonempty_denominator(
    tmp_path: Path, monkeypatch
):
    truth, _row, promoted, reviewed = _review_gate_ready(tmp_path, monkeypatch)
    n3_result = N3DeliveryGateService(truth, source_commit=COMMIT).complete(
        release_batch_id=BATCH
    )
    assert n3_result["gate"]["decision"] == "PASS"
    assert n3_result["gate"]["n4_state"] == "READY"

    snapshot = N4ParentTruthService(truth).resolve(release_batch_id=BATCH)

    assert snapshot["lineage_ready"] is True
    assert snapshot["cases_generated"] is False
    assert snapshot["n4_pass"] is False
    assert snapshot["n4_state"] == "READY"
    assert snapshot["mission_id"] == MISSION
    assert snapshot["release_batch_id"] == BATCH
    assert snapshot["n3_delivery_id"] == n3_result["delivery"]["delivery_id"]
    assert snapshot["n3_gate_id"] == n3_result["gate"]["gate_id"]
    assert promoted["artifact_id"] in snapshot["parent_artifact_refs"]
    assert snapshot["artifact_hashes"][promoted["artifact_id"]].startswith("sha256:")

    assert set(snapshot["requirement_sst_map"]) == set(REQUIREMENTS)
    assert all(snapshot["requirement_sst_map"][requirement_id] for requirement_id in REQUIREMENTS)
    all_ssts = [
        sst_id
        for sst_ids in snapshot["requirement_sst_map"].values()
        for sst_id in sst_ids
    ]
    assert all_ssts
    assert len(all_ssts) == len(set(all_ssts))
    assert set(
        requirement_id
        for values in snapshot["code_requirement_map"].values()
        for requirement_id in values
    ) == set(REQUIREMENTS)

    assert snapshot["obligation_source_total"] > 0
    assert snapshot["requirement_source_total"] > 0
    assert snapshot["code_source_total"] > 0
    kinds = {row["kind"] for row in snapshot["obligation_sources"]}
    assert "CODE_IMPACT" in kinds
    assert "REGRESSION" in kinds
    assert kinds.intersection(
        {
            "REQUIREMENT_ASSERTION",
            "BUSINESS_RULE",
            "PRECONDITION",
            "POSITIVE_PATH",
            "NEGATIVE_PATH",
            "BOUNDARY",
            "STATE_TRANSITION",
            "ROLE_PERMISSION",
            "DATA_CONDITION",
            "DEPENDENCY",
            "SIDE_EFFECT",
        }
    )

    gate = truth.query("rc72_node_gate", gate_id=snapshot["n3_gate_id"])[0]
    assert gate["decision"] == "PASS"
    assert gate["failed"] == []
    assert reviewed["evaluation_id"] in [
        ref[len("evaluation://") :]
        for ref in truth.query(
            "rc72_node_delivery", delivery_id=snapshot["n3_delivery_id"]
        )[0]["input_refs"]
        if ref.startswith("evaluation://")
    ]


def test_inherited_parent_inventory_now_understands_rc72_artifact_types(
    tmp_path: Path, monkeypatch
):
    truth, _row, _promoted, _reviewed = _review_gate_ready(tmp_path, monkeypatch)
    N3DeliveryGateService(truth, source_commit=COMMIT).complete(release_batch_id=BATCH)
    snapshot = N4ParentTruthService(truth).resolve(release_batch_id=BATCH)

    sources = ParentDerivedTestObligationInventory().derive(
        truth,
        mission_id=MISSION,
        parent_artifact_refs=snapshot["parent_artifact_refs"],
    )
    assert sources
    source_rows = {(item.kind, item.source_id, item.parent_artifact_id) for item in sources}
    assert len(source_rows) == len(sources)
    assert any(item.kind == "CODE_IMPACT" for item in sources)
    assert any(item.kind == "REGRESSION" for item in sources)
    assert any(
        item.kind
        in {
            "REQUIREMENT_ASSERTION",
            "BUSINESS_RULE",
            "PRECONDITION",
            "POSITIVE_PATH",
            "NEGATIVE_PATH",
            "BOUNDARY",
            "STATE_TRANSITION",
            "ROLE_PERMISSION",
            "DATA_CONDITION",
            "DEPENDENCY",
            "SIDE_EFFECT",
        }
        for item in sources
    )
