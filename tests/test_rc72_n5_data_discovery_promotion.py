from pathlib import Path

import pytest

from rc7_runtime.rc72_n5_data_discovery_anchor import N5DataDiscoveryEvidenceAnchorService
from rc7_runtime.rc72_n5_data_discovery_handoff import N5DataDiscoveryDshHandoffService
from rc7_runtime.rc72_n5_data_discovery_promotion import (
    N5DataDiscoveryCandidatePromotionService,
    N5DataDiscoveryPromotionError,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n5_data_discovery_handoff import (
    TOOL_DATA,
    _first_assignment,
    _launcher,
    _ready,
)


def _anchored(tmp_path: Path, monkeypatch):
    truth, _inventory, _dispatched, _assigned = _ready(tmp_path, monkeypatch)
    receipt = _first_assignment(truth)
    calls = {"count": 0}
    state_root = tmp_path / ("state-n5-data-%s" % id(calls))
    N5DataDiscoveryDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, calls=calls),
        allowed_tools=[TOOL_DATA],
    ).handoff(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    anchor = N5DataDiscoveryEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(state_root),
    ).anchor(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    return truth, receipt, anchor, state_root


def _service(truth, state_root: Path):
    return N5DataDiscoveryCandidatePromotionService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        state_root=str(state_root),
    )


def test_n5_promotion_creates_hash_bound_candidate_and_stops_before_data_verification(
    tmp_path: Path, monkeypatch
):
    truth, receipt, anchor, state_root = _anchored(tmp_path, monkeypatch)
    resources_before = list(truth.query("rc72_data_resource"))

    result = _service(truth, state_root).promote(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )

    assert result["status"] == "PROMOTED"
    assert result["task_state"] == "OUTPUT_PRODUCED"
    assert result["data_requirement_id"] == receipt["data_requirement_id"]
    assert result["resolution_plan_id"] == receipt["resolution_plan_id"]
    assert result["case_id"] == receipt["case_id"]
    assert result["strategy"] == "DISCOVER_EXISTING"
    assert result["observation_count"] >= 1
    assert result["verification_plan"]
    assert result["candidate_unknowns"] == []
    assert result["candidate_gaps"] == []
    assert result["evidence_anchor_id"] == anchor["anchor_id"]

    artifacts = truth.query("rc7_artifact", artifact_id=result["artifact_id"])
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact["artifact_type_name"] == "DATA_DISCOVERY_CANDIDATE"
    assert artifact["producer_task_id"] == result["task_id"]
    assert artifact["state"] == "VALID"
    assert artifact["content_hash"] == result["content_hash"]
    assert len(artifact["evidence_refs"]) == 1

    evidence = truth.query("rc7_evidence", evidence_id=artifact["evidence_refs"][0])
    assert len(evidence) == 1
    assert evidence[0]["kind"] == "N5_DATA_DISCOVERY_DSH_RAW_PROOF"
    assert evidence[0]["content_hash"] == anchor["raw_output_sha256"]

    task = truth.query("rc7_task", task_id=result["task_id"])[0]
    assert task["state"] == "OUTPUT_PRODUCED"
    assert task["output_artifact_refs"] == [result["artifact_id"]]
    assert task.get("evaluation_id") in {None, ""}

    # Promotion is candidate truth only. It must not turn observations into a
    # verified DataRef/binding/lease or alter unrelated reusable resources.
    assert list(truth.query("rc72_data_resource")) == resources_before
    assert truth.query(
        "rc72_n5_data_binding", data_requirement_id=receipt["data_requirement_id"]
    ) == []
    assert truth.query("rc72_data_lease") == []
    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    n6 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]
    assert n5["state"] == "RUNNING"
    assert n6["state"] == "NOT_STARTED"
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []


def test_n5_promotion_is_idempotent_for_same_anchored_candidate(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _anchor, state_root = _anchored(tmp_path, monkeypatch)
    service = _service(truth, state_root)
    first = service.promote(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    second = service.promote(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )

    assert second["status"] == "RESUMED"
    assert second["artifact_id"] == first["artifact_id"]
    assert second["content_hash"] == first["content_hash"]
    assert len(truth.query("rc7_artifact", artifact_id=first["artifact_id"])) == 1
    assert truth.query(
        "rc72_n5_data_binding", data_requirement_id=receipt["data_requirement_id"]
    ) == []


def test_n5_promotion_rejects_raw_bytes_changed_after_anchor(
    tmp_path: Path, monkeypatch
):
    truth, receipt, anchor, state_root = _anchored(tmp_path, monkeypatch)
    path = Path(anchor["raw_output_ref"][len("file://"):])
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(
        N5DataDiscoveryPromotionError,
        match="RAW_OUTPUT_HASH_MISMATCH",
    ):
        _service(truth, state_root).promote(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
    assert truth.query(
        "rc72_n5_data_binding", data_requirement_id=receipt["data_requirement_id"]
    ) == []
    assert truth.query("rc72_data_lease") == []


def test_n5_promotion_requires_anchor_and_exact_source_commit(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _anchor, state_root = _anchored(tmp_path, monkeypatch)
    with pytest.raises(
        N5DataDiscoveryPromotionError,
        match="EXACT_EVIDENCE_ANCHOR_REQUIRED",
    ):
        N5DataDiscoveryCandidatePromotionService(
            truth,
            release_id=RELEASE,
            mission_id=MISSION,
            source_commit="stale-source-commit",
            state_root=str(state_root),
        ).promote(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )


def test_n5_candidate_observation_does_not_satisfy_verified_binding_contract(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _anchor, state_root = _anchored(tmp_path, monkeypatch)
    result = _service(truth, state_root).promote(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    artifact = truth.query("rc7_artifact", artifact_id=result["artifact_id"])[0]
    assert artifact["artifact_type_name"] == "DATA_DISCOVERY_CANDIDATE"
    assert truth.query(
        "rc72_n5_data_binding", data_requirement_id=receipt["data_requirement_id"]
    ) == []
    plan = truth.query(
        "rc72_n5_data_resolution_plan",
        plan_id=receipt["resolution_plan_id"],
    )[0]
    assert plan["status"] == "DISCOVERY_REQUIRED"
    assert plan["binding_id"] is None
    assert plan["data_ref"] is None
