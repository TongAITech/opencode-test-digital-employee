from pathlib import Path

import pytest

from rc7_runtime.rc72_n5_data_discovery_anchor import (
    N5DataDiscoveryEvidenceAnchorError,
    N5DataDiscoveryEvidenceAnchorService,
    validate_rc72_n5_data_discovery_evidence_anchor,
)
from rc7_runtime.rc72_n5_data_discovery_handoff import N5DataDiscoveryDshHandoffService

from rc72_n2_test_support import BATCH, COMMIT, MISSION
from test_rc72_n5_data_discovery_handoff import (
    TOOL_DATA,
    _first_assignment,
    _launcher,
    _ready,
)


def _handed_off(tmp_path: Path, monkeypatch):
    truth, _inventory, _dispatched, _assigned = _ready(tmp_path, monkeypatch)
    receipt = _first_assignment(truth)
    calls = {"count": 0}
    state_root = tmp_path / ("state-n5-data-%s" % id(calls))
    handoff = N5DataDiscoveryDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, calls=calls),
        allowed_tools=[TOOL_DATA],
    ).handoff(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    return truth, receipt, handoff, state_root


def test_n5_anchor_binds_exact_raw_jsonl_hash_session_and_lineage(
    tmp_path: Path, monkeypatch
):
    truth, receipt, handoff, state_root = _handed_off(tmp_path, monkeypatch)
    anchor = N5DataDiscoveryEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(state_root),
    ).anchor(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )

    assert anchor["attempt_id"] == handoff["attempt_id"]
    assert anchor["data_requirement_id"] == receipt["data_requirement_id"]
    assert anchor["resolution_plan_id"] == receipt["resolution_plan_id"]
    assert anchor["source_case_sha256"] == receipt["source_case_sha256"]
    assert anchor["requirement_id"] == receipt["requirement_id"]
    assert anchor["sst_id"] == receipt["sst_id"]
    assert anchor["obligation_id"] == receipt["obligation_id"]
    assert anchor["case_id"] == receipt["case_id"]
    assert anchor["assignment_id"] == receipt["assignment_id"]
    assert anchor["workitem_id"] == receipt["workitem_id"]
    assert anchor["worker_instance_id"] == receipt["worker_instance_id"]
    assert anchor["dsh_session_id"] == handoff["dsh_session_id"]
    assert anchor["candidate_output_ref"] == handoff["candidate_output_ref"]
    assert anchor["candidate_schema"] == "RC72_N5_DATA_DISCOVERY_CANDIDATE_V1"
    assert anchor["raw_output_ref"].startswith("file://")
    assert anchor["raw_output_sha256"].startswith("sha256:")
    assert len(anchor["raw_output_sha256"]) == 71
    for forbidden in (
        "strategy", "observations", "verification_plan", "data_ref", "binding_id",
        "verification", "verified", "data_lease_id", "node_gate", "node_pass",
        "n5_pass", "n6_ready", "field_verified", "bank_final",
    ):
        assert forbidden not in anchor

    assert truth.query(
        "rc72_n5_data_binding", data_requirement_id=receipt["data_requirement_id"]
    ) == []
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


def test_n5_anchor_is_idempotent_for_unchanged_raw_bytes(tmp_path: Path, monkeypatch):
    truth, receipt, _handoff, state_root = _handed_off(tmp_path, monkeypatch)
    service = N5DataDiscoveryEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(state_root),
    )
    first = service.anchor(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    second = service.anchor(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    assert second["anchor_id"] == first["anchor_id"]
    assert second["raw_output_sha256"] == first["raw_output_sha256"]
    assert len(
        truth.query(
            "rc72_n5_data_discovery_evidence_anchor",
            anchor_id=first["anchor_id"],
        )
    ) == 1


def test_n5_anchor_detects_raw_jsonl_tampering_after_anchor(tmp_path: Path, monkeypatch):
    truth, receipt, _handoff, state_root = _handed_off(tmp_path, monkeypatch)
    service = N5DataDiscoveryEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(state_root),
    )
    first = service.anchor(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    path = Path(first["raw_output_ref"][len("file://"):])
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(
        N5DataDiscoveryEvidenceAnchorError,
        match="CONFLICT:raw_output_sha256",
    ):
        service.anchor(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )


def test_n5_anchor_rejects_raw_session_tampering_before_first_anchor(
    tmp_path: Path, monkeypatch
):
    truth, receipt, handoff, state_root = _handed_off(tmp_path, monkeypatch)
    attempt = truth.query(
        "rc72_n5_data_discovery_attempt", attempt_id=handoff["attempt_id"]
    )[0]
    raw_ref = next(
        ref for ref in attempt["runtime_evidence_refs"] if ref.startswith("file://")
    )
    path = Path(raw_ref[len("file://"):])
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(handoff["dsh_session_id"], "session-tampered-n5-data", 1),
        encoding="utf-8",
    )

    with pytest.raises(
        N5DataDiscoveryEvidenceAnchorError,
        match="DSH_SESSION_MISMATCH",
    ):
        N5DataDiscoveryEvidenceAnchorService(
            truth,
            source_commit=COMMIT,
            state_root=str(state_root),
        ).anchor(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
    assert truth.query("rc72_n5_data_discovery_evidence_anchor") == []


def test_n5_anchor_contract_rejects_candidate_and_data_truth_smuggling(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _handoff, state_root = _handed_off(tmp_path, monkeypatch)
    anchor = dict(
        N5DataDiscoveryEvidenceAnchorService(
            truth,
            source_commit=COMMIT,
            state_root=str(state_root),
        ).anchor(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
    )
    for field, value in (
        ("observations", [{"kind": "SMUGGLED", "summary": "not anchor truth"}]),
        ("data_ref", "db://fake"),
        ("binding_id", "BIND-FAKE"),
        ("data_lease_id", "LEASE-FAKE"),
        ("node_pass", True),
        ("n6_ready", True),
        ("field_verified", True),
        ("bank_final", True),
    ):
        tampered = dict(anchor)
        tampered[field] = value
        with pytest.raises(Exception, match="DATA_TRUTH_CLAIM_FORBIDDEN"):
            validate_rc72_n5_data_discovery_evidence_anchor(tampered)


def test_n5_anchor_requires_exact_source_commit(tmp_path: Path, monkeypatch):
    truth, receipt, _handoff, state_root = _handed_off(tmp_path, monkeypatch)
    with pytest.raises(
        N5DataDiscoveryEvidenceAnchorError,
        match="EXACT_ATTEMPT_REQUIRED",
    ):
        N5DataDiscoveryEvidenceAnchorService(
            truth,
            source_commit="stale-source-commit",
            state_root=str(state_root),
        ).anchor(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
