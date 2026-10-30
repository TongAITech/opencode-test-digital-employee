from pathlib import Path
import json

import pytest

from rc7_runtime.candidate_payload import CandidatePayloadReader
from rc7_runtime.rc72_n3_source_target_anchor import N3SourceTargetEvidenceAnchorService
from rc7_runtime.rc72_n3_source_target_promotion import (
    N3SourceTargetCandidatePromotionService,
    N3SourceTargetPromotionError,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n3_source_target_anchor import _attempt, _raw_path
from test_rc72_n3_source_target_handoff import APPLICATION


def _anchor(tmp_path: Path, truth):
    return N3SourceTargetEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state-n3-source"),
    ).anchor(release_batch_id=BATCH, application_id=APPLICATION)


def _promotion(tmp_path: Path, truth):
    return N3SourceTargetCandidatePromotionService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state-n3-source"),
    )


def _assert_downstream_locked(truth):
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []
    n3 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    )[0]
    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    assert n3["state"] == "RUNNING"
    assert n4["state"] == "NOT_STARTED"
    assert truth.query("rc72_node_delivery", mission_id=MISSION, node_type="N3_CODE_ANALYSIS") == []
    assert truth.query("rc72_node_gate", mission_id=MISSION, node_type="N3_CODE_ANALYSIS") == []


def _rewrite_final_candidate(raw_path: Path, mutate):
    events = [
        json.loads(line)
        for line in raw_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    found = False
    for event in events:
        if event.get("type") != "final":
            continue
        candidate = json.loads(event["text"])
        mutate(candidate)
        event["text"] = json.dumps(candidate, ensure_ascii=False)
        found = True
    assert found
    raw_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
        encoding="utf-8",
    )


def test_hash_bound_n3_source_candidate_promotes_only_to_output_produced(tmp_path: Path):
    truth, _attempt_row = _attempt(tmp_path)
    anchor = _anchor(tmp_path, truth)

    result = _promotion(tmp_path, truth).promote(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )

    assert result["status"] == "PROMOTED"
    assert result["task_state"] == "OUTPUT_PRODUCED"
    assert result["evidence_anchor_id"] == anchor["anchor_id"]
    assert len(result["targets"]) == 1
    target = result["targets"][0]
    assert target["target_id"] == "SRC-TARGET-BLOAN"
    assert target["repository_ref"] == "git://repo/BLOAN"
    assert target["source_revision"] == "a" * 40
    assert target["source_evidence_refs"] == ["tool://source-target-probe/BLOAN"]
    assert target["canonical_evidence_ids"]

    task = truth.query("rc7_task", task_id=result["task_id"])[0]
    assert task["state"] == "OUTPUT_PRODUCED"
    assert task["output_artifact_refs"] == [result["artifact_id"]]
    artifact = truth.query("rc7_artifact", artifact_id=result["artifact_id"])[0]
    assert artifact["artifact_type_name"] == "SOURCE_TARGET_MAPPING_CANDIDATE"
    assert artifact["state"] == "VALID"

    durable = CandidatePayloadReader().load(
        truth,
        result["artifact_id"],
        expected_mission_id=MISSION,
        expected_task_id=result["task_id"],
    )
    assert durable.semantic_payload["candidate_kind"] == "SOURCE_TARGET_MAPPING_CANDIDATE"
    assert durable.semantic_payload["application_id"] == APPLICATION
    assert durable.semantic_payload["candidate_unknowns"] == []
    assert durable.semantic_payload["candidate_gaps"] == []
    assert durable.semantic_payload["targets"] == result["targets"]
    assert "mapping_accepted" not in durable.semantic_payload
    assert "evaluation" not in durable.semantic_payload

    evidence = [
        truth.query("rc7_evidence", evidence_id=evidence_id)[0]
        for evidence_id in result["evidence_ids"]
    ]
    kinds = {row["kind"] for row in evidence}
    assert "N3_SOURCE_TARGET_DSH_RAW_PROOF" in kinds
    assert "N3_SOURCE_TARGET_PROOF" in kinds
    _assert_downstream_locked(truth)


def test_n3_source_candidate_promotion_replay_is_idempotent(tmp_path: Path):
    truth, _attempt_row = _attempt(tmp_path)
    _anchor(tmp_path, truth)
    service = _promotion(tmp_path, truth)

    first = service.promote(release_batch_id=BATCH, application_id=APPLICATION)
    second = service.promote(release_batch_id=BATCH, application_id=APPLICATION)

    assert first["status"] == "PROMOTED"
    assert second["status"] == "RESUMED"
    assert first["artifact_id"] == second["artifact_id"]
    assert first["content_hash"] == second["content_hash"]
    assert first["targets"] == second["targets"]
    assert len(truth.query("rc7_artifact", artifact_id=first["artifact_id"])) == 1
    _assert_downstream_locked(truth)


def test_n3_source_candidate_promotion_rejects_raw_bytes_changed_after_anchor(tmp_path: Path):
    truth, attempt = _attempt(tmp_path)
    _anchor(tmp_path, truth)
    raw_path = _raw_path(attempt)
    raw_path.write_bytes(raw_path.read_bytes() + b"\n")

    with pytest.raises(
        N3SourceTargetPromotionError,
        match="RAW_OUTPUT_HASH_MISMATCH",
    ):
        _promotion(tmp_path, truth).promote(
            release_batch_id=BATCH,
            application_id=APPLICATION,
        )

    task = truth.query("rc7_task", task_id=attempt["workitem_id"])[0]
    assert task["state"] == "LEASED"
    assert task["output_artifact_refs"] == []
    assert truth.query("rc7_artifact", mission_id=MISSION, artifact_type_name="SOURCE_TARGET_MAPPING_CANDIDATE") == []
    _assert_downstream_locked(truth)


def test_n3_source_candidate_with_explicit_gap_is_anchorable_but_not_promotable(tmp_path: Path):
    truth, attempt = _attempt(tmp_path)
    raw_path = _raw_path(attempt)

    def add_gap(candidate):
        candidate["targets"] = []
        candidate["gaps"] = [
            {"id": "GAP-SOURCE-MAP", "type": "SOURCE_TARGET_NOT_PROVEN"}
        ]

    _rewrite_final_candidate(raw_path, add_gap)
    anchor = _anchor(tmp_path, truth)
    assert anchor["raw_output_sha256"].startswith("sha256:")

    with pytest.raises(
        N3SourceTargetPromotionError,
        match="UNRESOLVED_DISCOVERY_GAPS",
    ):
        _promotion(tmp_path, truth).promote(
            release_batch_id=BATCH,
            application_id=APPLICATION,
        )

    task = truth.query("rc7_task", task_id=attempt["workitem_id"])[0]
    assert task["state"] == "LEASED"
    assert task["output_artifact_refs"] == []
    _assert_downstream_locked(truth)


def test_n3_source_candidate_with_unknown_is_anchorable_but_not_promotable(tmp_path: Path):
    truth, attempt = _attempt(tmp_path)
    raw_path = _raw_path(attempt)

    def add_unknown(candidate):
        candidate["unknowns"] = [
            {"id": "UNK-REVISION", "description": "source revision owner not proven"}
        ]

    _rewrite_final_candidate(raw_path, add_unknown)
    _anchor(tmp_path, truth)

    with pytest.raises(
        N3SourceTargetPromotionError,
        match="UNRESOLVED_DISCOVERY_UNKNOWNS",
    ):
        _promotion(tmp_path, truth).promote(
            release_batch_id=BATCH,
            application_id=APPLICATION,
        )

    task = truth.query("rc7_task", task_id=attempt["workitem_id"])[0]
    assert task["state"] == "LEASED"
    assert task["output_artifact_refs"] == []
    _assert_downstream_locked(truth)


def test_n3_promoted_candidate_envelope_tampering_is_rejected_on_resume(tmp_path: Path):
    truth, _attempt_row = _attempt(tmp_path)
    _anchor(tmp_path, truth)
    service = _promotion(tmp_path, truth)
    first = service.promote(release_batch_id=BATCH, application_id=APPLICATION)
    artifact = truth.query("rc7_artifact", artifact_id=first["artifact_id"])[0]
    content_ref = artifact["content_ref"]
    assert content_ref.startswith("file://")
    path = Path(content_ref[len("file://"):])
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["semantic_payload"]["targets"][0]["source_revision"] = "b" * 40
    path.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")

    with pytest.raises(Exception, match="CANDIDATE_CONTENT_HASH_MISMATCH"):
        service.promote(release_batch_id=BATCH, application_id=APPLICATION)

    _assert_downstream_locked(truth)
