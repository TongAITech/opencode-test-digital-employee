from pathlib import Path

import pytest

from rc7_runtime.rc72_n4_completion import N4DeliveryGateService
from rc7_runtime.rc72_n5_data_inventory import (
    N5DataInventoryError,
    N5DataRequirementInventoryService,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION
from test_rc72_n4_completion import _reviewed_batch


def _n5_ready(tmp_path: Path, monkeypatch):
    truth, scopes = _reviewed_batch(tmp_path, monkeypatch)
    completed = N4DeliveryGateService(
        truth, source_commit=COMMIT
    ).complete(release_batch_id=BATCH)
    assert completed["gate"]["decision"] == "PASS"
    assert completed["gate"]["n5_state"] == "READY"
    return truth, scopes, completed


def test_n5_materializes_case_data_requirements_without_guessing_data_refs(
    tmp_path: Path, monkeypatch
):
    truth, scopes, completed = _n5_ready(tmp_path, monkeypatch)
    result = N5DataRequirementInventoryService(
        truth, source_commit=COMMIT
    ).materialize(release_batch_id=BATCH)

    assert result["status"] == "MATERIALIZED"
    assert result["node_state"] == "RUNNING"
    assert result["n6_state"] == "NOT_STARTED"
    assert result["case_count"] == len(scopes)
    assert result["data_requirement_count"] == len(scopes)
    assert len(result["data_requirement_ids"]) == len(scopes)

    rows = truth.query("rc72_n5_data_requirement", release_batch_id=BATCH)
    assert len(rows) == len(scopes)
    assert {row["status"] for row in rows} == {"UNRESOLVED"}
    assert {(row["requirement_id"], row["sst_id"]) for row in rows} == {
        (scope["requirement_id"], scope["sst_id"]) for scope in scopes
    }
    for row in rows:
        assert row["requirement_text"] == "valid scoped request data"
        assert row["normalized_requirement"] == "valid scoped request data"
        assert row["source_case_sha256"].startswith("sha256:")
        assert row["source_n4_delivery_id"] == completed["delivery"]["delivery_id"]
        assert row["source_n4_gate_id"] == completed["gate"]["gate_id"]
        assert row["source_n3_artifact_refs"]
        assert row["case_preconditions"]
        assert row["case_code_trace"]
        assert row["case_evidence_requirements"]
        assert "data_ref" not in row
        assert "verified" not in row
        assert "lease_id" not in row

    snapshots = truth.query("rc72_n5_data_inventory_snapshot", release_batch_id=BATCH)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot["snapshot_id"] == result["snapshot_id"]
    assert snapshot["data_requirement_ids"] == result["data_requirement_ids"]
    assert snapshot["case_count"] == len(scopes)
    assert snapshot["data_requirement_count"] == len(scopes)
    assert "data_refs" not in snapshot
    assert "n5_pass" not in snapshot

    # N5 inventory is not discovery/construction/verification/reservation.
    assert truth.query("rc72_data_resource") == []
    assert truth.query("rc72_data_lease") == []
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []
    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    n6 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]
    assert n5["state"] == "RUNNING"
    assert n6["state"] == "NOT_STARTED"


def test_n5_inventory_replay_is_idempotent_and_does_not_release_n6(
    tmp_path: Path, monkeypatch
):
    truth, _scopes, _completed = _n5_ready(tmp_path, monkeypatch)
    service = N5DataRequirementInventoryService(truth, source_commit=COMMIT)
    first = service.materialize(release_batch_id=BATCH)
    second = service.materialize(release_batch_id=BATCH)

    assert first["status"] == "MATERIALIZED"
    assert second["status"] == "RESUMED"
    assert second["snapshot_id"] == first["snapshot_id"]
    assert second["data_requirement_ids"] == first["data_requirement_ids"]
    assert second["n6_state"] == "NOT_STARTED"
    assert len(
        truth.query("rc72_n5_data_requirement", release_batch_id=BATCH)
    ) == first["data_requirement_count"]
    assert len(
        truth.query("rc72_n5_data_inventory_snapshot", release_batch_id=BATCH)
    ) == 1
    assert truth.query("rc72_data_resource") == []
    assert truth.query("rc72_data_lease") == []
    assert truth.query(
        "rc72_node_transition",
        mission_id=MISSION,
        from_node_type="N5_TEST_DATA",
        to_node_type="N6_EXECUTABLE_READINESS",
    ) == []


def test_n5_inventory_is_forbidden_when_n4_aggregate_needs_revision(
    tmp_path: Path, monkeypatch
):
    truth, _scopes = _reviewed_batch(tmp_path, monkeypatch, gap_index=0)
    completed = N4DeliveryGateService(
        truth, source_commit=COMMIT
    ).complete(release_batch_id=BATCH)
    assert completed["gate"]["decision"] == "NEEDS_REVISION"
    assert completed["gate"]["n5_state"] == "NOT_STARTED"

    with pytest.raises(
        N5DataInventoryError,
        match="N5_NOT_ADMITTED",
    ):
        N5DataRequirementInventoryService(
            truth, source_commit=COMMIT
        ).materialize(release_batch_id=BATCH)

    assert truth.query("rc72_n5_data_requirement", release_batch_id=BATCH) == []
    assert truth.query(
        "rc72_n5_data_inventory_snapshot", release_batch_id=BATCH
    ) == []
    assert truth.query("rc72_data_resource") == []


def test_n5_inventory_replays_n4_candidate_hash_and_rejects_tampering(
    tmp_path: Path, monkeypatch
):
    truth, _scopes, completed = _n5_ready(tmp_path, monkeypatch)
    delivery = truth.query(
        "rc72_node_delivery", delivery_id=completed["delivery"]["delivery_id"]
    )[0]
    artifact_id = delivery["artifact_refs"][0]
    artifact = truth.query("rc7_artifact", artifact_id=artifact_id)[0]
    content_ref = artifact["content_ref"]
    assert content_ref.startswith("file://")
    path = Path(content_ref[len("file://"):])
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(
        N5DataInventoryError,
        match="N4_PAYLOAD_INVALID",
    ):
        N5DataRequirementInventoryService(
            truth, source_commit=COMMIT
        ).materialize(release_batch_id=BATCH)

    assert truth.query("rc72_n5_data_requirement", release_batch_id=BATCH) == []
    assert truth.query(
        "rc72_n5_data_inventory_snapshot", release_batch_id=BATCH
    ) == []
    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    n6 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]
    assert n5["state"] == "READY"
    assert n6["state"] == "NOT_STARTED"
