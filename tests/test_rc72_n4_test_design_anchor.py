from pathlib import Path

import pytest

from rc7_runtime.rc72_n4_test_design_anchor import (
    N4TestDesignEvidenceAnchorError,
    N4TestDesignEvidenceAnchorService,
    validate_rc72_n4_test_design_evidence_anchor,
)
from rc7_runtime.rc72_n4_test_design_handoff import N4TestDesignDshHandoffService

from rc72_n2_test_support import BATCH, COMMIT, MISSION
from test_rc72_n4_test_design_handoff import (
    TOOL_GRAPH,
    TOOL_READ,
    _launcher,
    _ready,
)


def _handed_off(tmp_path: Path, monkeypatch):
    truth, _snapshot, dispatched, _assigned = _ready(tmp_path, monkeypatch)
    scope = dispatched["design_scopes"][0]
    handoff = N4TestDesignDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth),
        allowed_tools=[TOOL_READ, TOOL_GRAPH],
    ).handoff(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )
    return truth, scope, handoff


def test_n4_anchor_binds_exact_raw_jsonl_sha_session_and_attempt_lineage(
    tmp_path: Path, monkeypatch
):
    truth, scope, handoff = _handed_off(tmp_path, monkeypatch)
    anchor = N4TestDesignEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state-n4-design"),
    ).anchor(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )

    assert anchor["attempt_id"] == handoff["attempt_id"]
    assert anchor["requirement_id"] == scope["requirement_id"]
    assert anchor["sst_id"] == scope["sst_id"]
    assert anchor["dsh_session_id"] == handoff["dsh_session_id"]
    assert anchor["candidate_output_ref"] == handoff["candidate_output_ref"]
    assert anchor["candidate_schema"] == "RC72_N4_TEST_DESIGN_CANDIDATE_V1"
    assert anchor["raw_output_ref"].startswith("file://")
    assert anchor["raw_output_sha256"].startswith("sha256:")
    assert len(anchor["raw_output_sha256"]) == 71
    assert "cases" not in anchor
    assert "obligations" not in anchor
    assert "evaluation" not in anchor
    assert "node_gate" not in anchor

    attempt = truth.query(
        "rc72_n4_test_design_attempt", attempt_id=handoff["attempt_id"]
    )[0]
    assignment = truth.query(
        "rc72_n4_test_design_assignment", assignment_id=attempt["assignment_id"]
    )[0]
    assert anchor["assignment_id"] == assignment["assignment_id"]
    assert anchor["worker_instance_id"] == assignment["worker_instance_id"]
    assert anchor["workitem_id"] == assignment["workitem_id"]

    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    assert n4["state"] == "RUNNING"
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []


def test_n4_anchor_is_idempotent_for_unchanged_raw_bytes(tmp_path: Path, monkeypatch):
    truth, scope, _handoff = _handed_off(tmp_path, monkeypatch)
    service = N4TestDesignEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state-n4-design"),
    )
    first = service.anchor(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )
    second = service.anchor(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )
    assert second["anchor_id"] == first["anchor_id"]
    assert second["raw_output_sha256"] == first["raw_output_sha256"]
    assert len(truth.query("rc72_n4_test_design_evidence_anchor", anchor_id=first["anchor_id"])) == 1


def test_n4_anchor_detects_raw_jsonl_tampering_after_anchor(tmp_path: Path, monkeypatch):
    truth, scope, _handoff = _handed_off(tmp_path, monkeypatch)
    service = N4TestDesignEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state-n4-design"),
    )
    first = service.anchor(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )
    path = Path(first["raw_output_ref"][len("file://"):])
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(
        N4TestDesignEvidenceAnchorError,
        match="CONFLICT:raw_output_sha256",
    ):
        service.anchor(
            release_batch_id=BATCH,
            requirement_id=scope["requirement_id"],
            sst_id=scope["sst_id"],
        )


def test_n4_anchor_contract_rejects_business_truth_smuggling(tmp_path: Path, monkeypatch):
    truth, scope, _handoff = _handed_off(tmp_path, monkeypatch)
    anchor = dict(
        N4TestDesignEvidenceAnchorService(
            truth,
            source_commit=COMMIT,
            state_root=str(tmp_path / "state-n4-design"),
        ).anchor(
            release_batch_id=BATCH,
            requirement_id=scope["requirement_id"],
            sst_id=scope["sst_id"],
        )
    )
    anchor["cases"] = [{"tc_id": "smuggled"}]
    with pytest.raises(
        Exception,
        match="BUSINESS_TRUTH_CLAIM_FORBIDDEN:cases",
    ):
        validate_rc72_n4_test_design_evidence_anchor(anchor)
