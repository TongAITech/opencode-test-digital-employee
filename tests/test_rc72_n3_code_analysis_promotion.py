from pathlib import Path
import json

import pytest

from rc7_runtime.candidate_payload import CandidatePayloadReader
from rc7_runtime.rc72_n3_code_analysis_anchor import N3CodeAnalysisEvidenceAnchorService
from rc7_runtime.rc72_n3_code_analysis_promotion import (
    N3CodeAnalysisCandidatePromotionService,
    N3CodeAnalysisPromotionError,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n3_code_analysis_anchor import _attempt, _raw_path


def _anchor(tmp_path: Path, truth, assignment):
    return N3CodeAnalysisEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state-n3-code"),
    ).anchor(
        release_batch_id=BATCH,
        target_id=assignment["target_id"],
    )


def _promotion(tmp_path: Path, truth):
    return N3CodeAnalysisCandidatePromotionService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state-n3-code"),
    )


def _assert_downstream_locked(truth):
    n3 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    )[0]
    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    assert n3["state"] == "RUNNING"
    assert n4["state"] == "NOT_STARTED"
    assert truth.query(
        "rc72_node_delivery",
        mission_id=MISSION,
        node_type="N3_CODE_ANALYSIS",
    ) == []
    assert truth.query(
        "rc72_node_gate",
        mission_id=MISSION,
        node_type="N3_CODE_ANALYSIS",
    ) == []


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


def test_hash_bound_code_analysis_candidate_promotes_only_to_output_produced(
    tmp_path: Path,
):
    truth, assignment, _attempt_row = _attempt(tmp_path)
    anchor = _anchor(tmp_path, truth, assignment)

    result = _promotion(tmp_path, truth).promote(
        release_batch_id=BATCH,
        target_id=assignment["target_id"],
    )

    assert result["status"] == "PROMOTED"
    assert result["task_state"] == "OUTPUT_PRODUCED"
    assert result["evidence_anchor_id"] == anchor["anchor_id"]
    assert result["target_id"] == assignment["target_id"]
    assert result["changed_files"] == ["src/main/java/example/ChangedService.java"]
    assert result["changed_symbols"] == ["example.ChangedService#execute"]

    task = truth.query("rc7_task", task_id=result["task_id"])[0]
    assert task["state"] == "OUTPUT_PRODUCED"
    assert task["output_artifact_refs"] == [result["artifact_id"]]
    assert task["evaluation_id"] is None
    artifact = truth.query("rc7_artifact", artifact_id=result["artifact_id"])[0]
    assert artifact["artifact_type_name"] == "CODE_ANALYSIS_CANDIDATE"
    assert artifact["state"] == "VALID"

    durable = CandidatePayloadReader().load(
        truth,
        result["artifact_id"],
        expected_mission_id=MISSION,
        expected_task_id=result["task_id"],
    )
    semantic = durable.semantic_payload
    assert semantic["candidate_kind"] == "CODE_ANALYSIS_CANDIDATE"
    assert semantic["application_id"] == assignment["application_id"]
    assert semantic["target_id"] == assignment["target_id"]
    assert semantic["repository_ref"] == assignment["repository_ref"]
    assert semantic["source_revision"] == assignment["source_revision"]
    assert semantic["candidate_unknowns"] == []
    assert semantic["candidate_gaps"] == []
    assert semantic["codegraph_required"] is True
    assert "code_analysis_pass" not in semantic
    assert "evaluation" not in semantic

    evidence = [
        truth.query("rc7_evidence", evidence_id=evidence_id)[0]
        for evidence_id in result["evidence_ids"]
    ]
    kinds = {row["kind"] for row in evidence}
    assert "N3_CODE_ANALYSIS_DSH_RAW_PROOF" in kinds
    assert "N3_CODE_ANALYSIS_PROOF" in kinds
    _assert_downstream_locked(truth)


def test_code_analysis_candidate_promotion_replay_is_idempotent(tmp_path: Path):
    truth, assignment, _attempt_row = _attempt(tmp_path)
    _anchor(tmp_path, truth, assignment)
    service = _promotion(tmp_path, truth)

    first = service.promote(
        release_batch_id=BATCH,
        target_id=assignment["target_id"],
    )
    second = service.promote(
        release_batch_id=BATCH,
        target_id=assignment["target_id"],
    )

    assert first["status"] == "PROMOTED"
    assert second["status"] == "RESUMED"
    assert first["artifact_id"] == second["artifact_id"]
    assert first["content_hash"] == second["content_hash"]
    assert first["changed_files"] == second["changed_files"]
    assert len(truth.query("rc7_artifact", artifact_id=first["artifact_id"])) == 1
    _assert_downstream_locked(truth)


def test_code_analysis_candidate_promotion_rejects_raw_bytes_changed_after_anchor(
    tmp_path: Path,
):
    truth, assignment, attempt = _attempt(tmp_path)
    _anchor(tmp_path, truth, assignment)
    raw_path = _raw_path(attempt)
    raw_path.write_bytes(raw_path.read_bytes() + b"\n")

    with pytest.raises(
        N3CodeAnalysisPromotionError,
        match="RAW_OUTPUT_HASH_MISMATCH",
    ):
        _promotion(tmp_path, truth).promote(
            release_batch_id=BATCH,
            target_id=assignment["target_id"],
        )

    task = truth.query("rc7_task", task_id=attempt["workitem_id"])[0]
    assert task["state"] == "LEASED"
    assert task["output_artifact_refs"] == []
    assert truth.query(
        "rc7_artifact",
        mission_id=MISSION,
        artifact_type_name="CODE_ANALYSIS_CANDIDATE",
    ) == []
    _assert_downstream_locked(truth)


def test_code_analysis_candidate_with_explicit_gap_is_anchorable_but_not_promotable(
    tmp_path: Path,
):
    truth, assignment, attempt = _attempt(tmp_path)
    raw_path = _raw_path(attempt)

    def add_gap(candidate):
        candidate["gaps"] = [
            {"id": "GAP-CODE", "type": "CODEGRAPH_IMPACT_NOT_PROVEN"}
        ]

    _rewrite_final_candidate(raw_path, add_gap)
    anchor = _anchor(tmp_path, truth, assignment)
    assert anchor["raw_output_sha256"].startswith("sha256:")

    with pytest.raises(
        N3CodeAnalysisPromotionError,
        match="UNRESOLVED_ANALYSIS_GAPS",
    ):
        _promotion(tmp_path, truth).promote(
            release_batch_id=BATCH,
            target_id=assignment["target_id"],
        )

    task = truth.query("rc7_task", task_id=attempt["workitem_id"])[0]
    assert task["state"] == "LEASED"
    assert task["output_artifact_refs"] == []
    _assert_downstream_locked(truth)


def test_code_analysis_candidate_rejects_noncanonical_symbol_evidence(tmp_path: Path):
    truth, assignment, attempt = _attempt(tmp_path)
    raw_path = _raw_path(attempt)

    def change_symbol_evidence(candidate):
        candidate["symbol_explanations"][0]["evidence_refs"] = [
            "tool://codegraph/not-in-top-level-evidence"
        ]

    _rewrite_final_candidate(raw_path, change_symbol_evidence)
    _anchor(tmp_path, truth, assignment)

    with pytest.raises(
        N3CodeAnalysisPromotionError,
        match="SYMBOL_EVIDENCE_NOT_CANONICAL",
    ):
        _promotion(tmp_path, truth).promote(
            release_batch_id=BATCH,
            target_id=assignment["target_id"],
        )

    task = truth.query("rc7_task", task_id=attempt["workitem_id"])[0]
    assert task["state"] == "LEASED"
    assert task["output_artifact_refs"] == []
    _assert_downstream_locked(truth)


def test_promoted_code_analysis_candidate_envelope_tampering_is_rejected_on_resume(
    tmp_path: Path,
):
    truth, assignment, _attempt_row = _attempt(tmp_path)
    _anchor(tmp_path, truth, assignment)
    service = _promotion(tmp_path, truth)
    first = service.promote(
        release_batch_id=BATCH,
        target_id=assignment["target_id"],
    )
    artifact = truth.query("rc7_artifact", artifact_id=first["artifact_id"])[0]
    content_ref = artifact["content_ref"]
    assert content_ref.startswith("file://")
    path = Path(content_ref[len("file://"):])
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["semantic_payload"]["changed_symbols"] = ["tampered.Symbol#x"]
    path.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")

    with pytest.raises(Exception, match="CANDIDATE_CONTENT_HASH_MISMATCH"):
        service.promote(
            release_batch_id=BATCH,
            target_id=assignment["target_id"],
        )

    _assert_downstream_locked(truth)
