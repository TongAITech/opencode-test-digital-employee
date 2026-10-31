from pathlib import Path

import pytest

from rc7_runtime.rc72_n4_test_design_anchor import N4TestDesignEvidenceAnchorService
from rc7_runtime.rc72_n4_test_design_handoff import N4TestDesignDshHandoffService
from rc7_runtime.rc72_n4_test_design_promotion import (
    N4TestDesignCandidatePromotionService,
    N4TestDesignPromotionError,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n4_test_design_handoff import (
    TOOL_GRAPH,
    TOOL_READ,
    _launcher,
    _ready,
)


def _anchored(tmp_path: Path, monkeypatch, *, gap=False):
    truth, _snapshot, dispatched, _assigned = _ready(tmp_path, monkeypatch)
    scope = dispatched["design_scopes"][0]
    N4TestDesignDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, gap=gap),
        allowed_tools=[TOOL_READ, TOOL_GRAPH],
    ).handoff(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )
    anchor = N4TestDesignEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state-n4-design"),
    ).anchor(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )
    return truth, scope, anchor


def _service(tmp_path: Path, truth):
    return N4TestDesignCandidatePromotionService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state-n4-design"),
    )


def test_n4_promotion_creates_hash_bound_candidate_and_stops_before_review(
    tmp_path: Path, monkeypatch
):
    truth, scope, anchor = _anchored(tmp_path, monkeypatch)
    result = _service(tmp_path, truth).promote(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )

    assert result["status"] == "PROMOTED"
    assert result["task_state"] == "OUTPUT_PRODUCED"
    assert result["obligation_count"] >= 1
    assert result["case_count"] >= 1
    assert result["candidate_unknowns"] == []
    assert result["candidate_gaps"] == []
    assert result["evidence_anchor_id"] == anchor["anchor_id"]

    artifacts = truth.query("rc7_artifact", artifact_id=result["artifact_id"])
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact["artifact_type_name"] == "TEST_DESIGN_CANDIDATE"
    assert artifact["producer_task_id"] == result["task_id"]
    assert artifact["state"] == "VALID"
    assert artifact["content_hash"] == result["content_hash"]
    assert len(artifact["evidence_refs"]) >= 2

    task = truth.query("rc7_task", task_id=result["task_id"])[0]
    assert task["state"] == "OUTPUT_PRODUCED"
    assert task["output_artifact_refs"] == [result["artifact_id"]]
    assert task.get("evaluation_id") in {None, ""}

    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    assert n4["state"] == "RUNNING"
    assert n5["state"] == "NOT_STARTED"
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []


def test_n4_promotion_is_idempotent_for_same_anchored_candidate(
    tmp_path: Path, monkeypatch
):
    truth, scope, _anchor = _anchored(tmp_path, monkeypatch)
    service = _service(tmp_path, truth)
    first = service.promote(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )
    second = service.promote(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )

    assert second["status"] == "RESUMED"
    assert second["artifact_id"] == first["artifact_id"]
    assert second["content_hash"] == first["content_hash"]
    assert len(truth.query("rc7_artifact", artifact_id=first["artifact_id"])) == 1


def test_n4_promotion_rejects_raw_bytes_changed_after_anchor(
    tmp_path: Path, monkeypatch
):
    truth, scope, anchor = _anchored(tmp_path, monkeypatch)
    path = Path(anchor["raw_output_ref"][len("file://"):])
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(
        N4TestDesignPromotionError,
        match="RAW_OUTPUT_HASH_MISMATCH",
    ):
        _service(tmp_path, truth).promote(
            release_batch_id=BATCH,
            requirement_id=scope["requirement_id"],
            sst_id=scope["sst_id"],
        )


def test_n4_explicit_gap_candidate_is_promoted_for_repair_not_pass(
    tmp_path: Path, monkeypatch
):
    truth, scope, _anchor = _anchored(tmp_path, monkeypatch, gap=True)
    result = _service(tmp_path, truth).promote(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )

    assert result["status"] == "PROMOTED"
    assert result["task_state"] == "OUTPUT_PRODUCED"
    assert result["obligation_count"] >= 1
    assert result["case_count"] == 0
    assert result["candidate_gaps"] == [
        {"id": "GAP-DESIGN", "type": "CASE_NOT_YET_PROVEN"}
    ]

    task = truth.query("rc7_task", task_id=result["task_id"])[0]
    assert task["state"] == "OUTPUT_PRODUCED"
    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    assert n4["state"] == "RUNNING"
    assert n5["state"] == "NOT_STARTED"
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []
