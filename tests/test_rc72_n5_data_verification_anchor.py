from pathlib import Path
import json

import pytest

from rc7_runtime.rc72_n5_data_verification_anchor import (
    N5DataVerificationEvidenceAnchorError,
    N5DataVerificationEvidenceAnchorService,
    validate_rc72_n5_data_verification_evidence_anchor,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION
from test_rc72_n5_data_verification_handoff import (
    _prepare_promoted,
    _service,
)


def _verified(tmp_path: Path, monkeypatch, **launcher_kwargs):
    truth, receipt, promoted = _prepare_promoted(tmp_path, monkeypatch)
    service = _service(tmp_path, truth, receipt, **launcher_kwargs)
    result = service.verify(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    attempts = truth.query(
        "rc72_n5_data_verification_attempt",
        verification_attempt_id=result["verification_attempt_id"],
    )
    assert len(attempts) == 1
    return truth, receipt, promoted, service, result, attempts[0]


def _anchor_service(truth, service):
    return N5DataVerificationEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(service.launcher.state_root),
    )


def _raw_path(attempt):
    refs = [
        ref for ref in attempt["runtime_evidence_refs"]
        if isinstance(ref, str) and ref.startswith("file://")
    ]
    assert len(refs) == 1
    return Path(refs[0][len("file://"):])


def _rewrite_events(attempt, mutator):
    path = _raw_path(attempt)
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    mutator(events)
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )


def test_n5_verifier_raw_output_is_hash_anchored_without_admitting_data_truth(
    tmp_path: Path, monkeypatch
):
    truth, receipt, promoted, service, result, attempt = _verified(tmp_path, monkeypatch)
    anchor = _anchor_service(truth, service).anchor(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )

    assert anchor["verification_attempt_id"] == result["verification_attempt_id"]
    assert anchor["candidate_artifact_id"] == promoted["artifact_id"]
    assert anchor["candidate_content_hash"] == promoted["content_hash"]
    assert anchor["verifier_worker_id"] == attempt["verifier_worker_id"]
    assert anchor["verifier_dsh_session_id"] == attempt["verifier_dsh_session_id"]
    assert anchor["producer_worker_id"] != anchor["verifier_worker_id"]
    assert anchor["producer_dsh_session_id"] != anchor["verifier_dsh_session_id"]
    assert anchor["raw_output_ref"].startswith("file://")
    assert anchor["raw_output_sha256"].startswith("sha256:")
    assert len(anchor["raw_output_sha256"]) == 71
    for forbidden in (
        "status", "decision", "candidate_ref", "data_ref", "binding_id",
        "data_lease_id", "node_delivery_id", "node_gate_id", "n5_pass", "n6_ready",
    ):
        assert forbidden not in anchor

    assert truth.query("rc72_n5_data_binding", data_requirement_id=receipt["data_requirement_id"]) == []
    assert truth.query("rc72_data_lease") == []
    n5 = truth.query("rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA")[0]
    n6 = truth.query("rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS")[0]
    assert n5["state"] == "RUNNING"
    assert n6["state"] == "NOT_STARTED"


def test_n5_verifier_anchor_replay_is_idempotent_and_detects_post_anchor_tamper(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _promoted, service, _result, attempt = _verified(tmp_path, monkeypatch)
    anchor_service = _anchor_service(truth, service)
    first = anchor_service.anchor(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    replay = anchor_service.anchor(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    assert replay["anchor_id"] == first["anchor_id"]
    assert replay["raw_output_sha256"] == first["raw_output_sha256"]

    def mutate(events):
        final = [event for event in events if event.get("type") == "final"][0]
        value = json.loads(final["text"])
        value["candidate_ref"] = "candidate://tdsql/account/fixture-tampered"
        final["text"] = json.dumps(value, ensure_ascii=False)

    _rewrite_events(attempt, mutate)
    with pytest.raises(N5DataVerificationEvidenceAnchorError, match="CONFLICT:raw_output_sha256"):
        anchor_service.anchor(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )


def test_n5_verifier_anchor_rejects_session_lineage_tamper(tmp_path: Path, monkeypatch):
    truth, receipt, _promoted, service, _result, attempt = _verified(tmp_path, monkeypatch)

    def mutate(events):
        session = [event for event in events if event.get("type") == "session"][0]
        session["session_id"] = "session-forged-verifier"

    _rewrite_events(attempt, mutate)
    with pytest.raises(N5DataVerificationEvidenceAnchorError, match="DSH_SESSION_MISMATCH"):
        _anchor_service(truth, service).anchor(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
    assert truth.query("rc72_n5_data_verification_evidence_anchor") == []


def test_n5_verifier_anchor_rejects_tool_call_tamper(tmp_path: Path, monkeypatch):
    truth, receipt, _promoted, service, _result, attempt = _verified(tmp_path, monkeypatch)

    def mutate(events):
        tool = [event for event in events if event.get("type") == "tool_call"][0]
        tool["tool_name"] = "unleased-forged-tool"

    _rewrite_events(attempt, mutate)
    with pytest.raises(N5DataVerificationEvidenceAnchorError, match="TOOL_CALL_EVIDENCE_MISMATCH"):
        _anchor_service(truth, service).anchor(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
    assert truth.query("rc72_n5_data_verification_evidence_anchor") == []


def test_n5_verifier_anchor_rejects_canonical_truth_smuggling_in_raw_json(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _promoted, service, _result, attempt = _verified(tmp_path, monkeypatch)

    def mutate(events):
        final = [event for event in events if event.get("type") == "final"][0]
        value = json.loads(final["text"])
        value["data_ref"] = "data://premature/verified"
        final["text"] = json.dumps(value, ensure_ascii=False)

    _rewrite_events(attempt, mutate)
    with pytest.raises(N5DataVerificationEvidenceAnchorError, match="V2_TOP_LEVEL_CONTRACT_INVALID"):
        _anchor_service(truth, service).anchor(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
    assert truth.query("rc72_n5_data_binding") == []
    assert truth.query("rc72_data_lease") == []


def test_n5_repair_required_verifier_output_can_be_anchored_but_cannot_become_data_truth(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _promoted, service, _result, _attempt = _verified(
        tmp_path, monkeypatch, repair=True
    )
    anchor = _anchor_service(truth, service).anchor(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    assert anchor["raw_output_sha256"].startswith("sha256:")
    assert "decision" not in anchor
    assert "status" not in anchor
    assert truth.query("rc72_n5_data_binding", data_requirement_id=receipt["data_requirement_id"]) == []
    assert truth.query("rc72_data_lease") == []


def test_n5_verifier_anchor_validator_rejects_premature_data_ref(tmp_path: Path, monkeypatch):
    truth, receipt, _promoted, service, _result, _attempt = _verified(tmp_path, monkeypatch)
    anchor = _anchor_service(truth, service).anchor(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    forged = dict(anchor)
    forged["data_ref"] = "data://premature/verified"
    with pytest.raises(Exception, match="DATA_TRUTH_CLAIM_FORBIDDEN:data_ref"):
        validate_rc72_n5_data_verification_evidence_anchor(forged)
