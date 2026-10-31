from pathlib import Path
import hashlib
import json

import pytest

from rc7_runtime.rc72_n3_code_analysis_anchor import (
    N3CodeAnalysisEvidenceAnchorError,
    N3CodeAnalysisEvidenceAnchorService,
    validate_rc72_n3_code_analysis_evidence_anchor,
)
from rc7_runtime.rc72_n3_code_analysis_handoff import N3CodeAnalysisDshHandoffService

from rc72_n2_test_support import BATCH, COMMIT, MISSION
from test_rc72_n3_code_analysis_handoff import _launcher, _ready


def _attempt(tmp_path: Path):
    truth, _dispatched, assigned = _ready(tmp_path)
    row = assigned["assignments"][0]
    result = N3CodeAnalysisDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, [row]),
    ).handoff(release_batch_id=BATCH, target_id=row["target_id"])
    attempt = truth.query(
        "rc72_n3_code_analysis_attempt", attempt_id=result["attempt_id"]
    )[0]
    return truth, row, attempt


def _raw_path(attempt):
    refs = [
        ref for ref in attempt["runtime_evidence_refs"]
        if ref.startswith("file://")
    ]
    assert len(refs) == 1
    return Path(refs[0][len("file://"):])


def _service(tmp_path: Path, truth):
    return N3CodeAnalysisEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state-n3-code"),
    )


def test_code_analysis_raw_attempt_is_sha256_anchored_without_promoting_analysis_truth(
    tmp_path: Path,
):
    truth, assignment, attempt = _attempt(tmp_path)
    raw_path = _raw_path(attempt)
    expected_hash = "sha256:" + hashlib.sha256(raw_path.read_bytes()).hexdigest()

    anchor = _service(tmp_path, truth).anchor(
        release_batch_id=BATCH,
        target_id=assignment["target_id"],
    )

    assert anchor["attempt_id"] == attempt["attempt_id"]
    assert anchor["assignment_id"] == assignment["assignment_id"]
    assert anchor["target_id"] == assignment["target_id"]
    assert anchor["dsh_session_id"] == attempt["dsh_session_id"]
    assert anchor["raw_output_sha256"] == expected_hash
    assert anchor["raw_output_ref"].startswith("file://")
    assert Path(anchor["raw_output_ref"][len("file://"):]).resolve() == raw_path.resolve()
    assert anchor["candidate_schema"] == "RC72_N3_CODE_ANALYSIS_CANDIDATE_V1"
    for forbidden in (
        "semantic_payload", "analysis_id", "changed_files", "changed_symbols",
        "symbol_explanations", "reverse_requirement_mappings", "graph_evidence",
        "code_analysis_pass", "node_gate", "node_pass", "n4_started",
    ):
        assert forbidden not in anchor
    task = truth.query("rc7_task", task_id=attempt["workitem_id"])[0]
    assert task["state"] == "LEASED"
    assert task["output_artifact_refs"] == []
    assert task["evaluation_id"] is None
    assert truth.query(
        "rc72_node_delivery",
        mission_id=MISSION,
        node_type="N3_CODE_ANALYSIS",
    ) == []
    n4 = truth.query(
        "rc72_mission_node",
        mission_id=MISSION,
        node_type="N4_TEST_DESIGN",
    )[0]
    assert n4["state"] == "NOT_STARTED"


def test_code_analysis_raw_anchor_replay_is_idempotent(tmp_path: Path):
    truth, assignment, _attempt_row = _attempt(tmp_path)
    service = _service(tmp_path, truth)

    first = service.anchor(
        release_batch_id=BATCH,
        target_id=assignment["target_id"],
    )
    second = service.anchor(
        release_batch_id=BATCH,
        target_id=assignment["target_id"],
    )

    assert first["anchor_id"] == second["anchor_id"]
    assert first["raw_output_sha256"] == second["raw_output_sha256"]
    assert len(
        truth.query("rc72_n3_code_analysis_evidence_anchor", release_batch_id=BATCH)
    ) == 1


def test_code_analysis_raw_anchor_detects_bytes_changed_after_anchor(tmp_path: Path):
    truth, assignment, attempt = _attempt(tmp_path)
    service = _service(tmp_path, truth)
    first = service.anchor(
        release_batch_id=BATCH,
        target_id=assignment["target_id"],
    )
    raw_path = _raw_path(attempt)

    raw_path.write_bytes(raw_path.read_bytes() + b"\n")

    with pytest.raises(
        N3CodeAnalysisEvidenceAnchorError,
        match="CODE_ANCHOR_CONFLICT:raw_output_sha256",
    ):
        service.anchor(
            release_batch_id=BATCH,
            target_id=assignment["target_id"],
        )

    stored = truth.query(
        "rc72_n3_code_analysis_evidence_anchor", anchor_id=first["anchor_id"]
    )[0]
    assert stored["raw_output_sha256"] == first["raw_output_sha256"]


def test_code_analysis_raw_anchor_rejects_session_mismatch_before_first_anchor(
    tmp_path: Path,
):
    truth, assignment, attempt = _attempt(tmp_path)
    raw_path = _raw_path(attempt)
    lines = [
        json.loads(line)
        for line in raw_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for item in lines:
        if item.get("type") == "session":
            item["session_id"] = "session-tampered"
    raw_path.write_text(
        "\n".join(json.dumps(item) for item in lines) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        N3CodeAnalysisEvidenceAnchorError,
        match="CODE_ANCHOR_DSH_SESSION_MISMATCH",
    ):
        _service(tmp_path, truth).anchor(
            release_batch_id=BATCH,
            target_id=assignment["target_id"],
        )

    assert truth.query(
        "rc72_n3_code_analysis_evidence_anchor", release_batch_id=BATCH
    ) == []


def test_code_analysis_raw_anchor_rejects_tool_call_mismatch_before_first_anchor(
    tmp_path: Path,
):
    truth, assignment, attempt = _attempt(tmp_path)
    raw_path = _raw_path(attempt)
    lines = [
        json.loads(line)
        for line in raw_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for item in lines:
        if item.get("type") == "tool_call" and item.get("tool_name") == "codegraph":
            item["tool_name"] = "different-code-probe"
    raw_path.write_text(
        "\n".join(json.dumps(item) for item in lines) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        N3CodeAnalysisEvidenceAnchorError,
        match="CODE_ANCHOR_TOOL_CALL_EVIDENCE_MISMATCH",
    ):
        _service(tmp_path, truth).anchor(
            release_batch_id=BATCH,
            target_id=assignment["target_id"],
        )

    assert truth.query(
        "rc72_n3_code_analysis_evidence_anchor", release_batch_id=BATCH
    ) == []


def test_code_analysis_anchor_contract_rejects_analysis_truth_smuggling(
    tmp_path: Path,
):
    truth, assignment, _attempt_row = _attempt(tmp_path)
    anchor = dict(
        _service(tmp_path, truth).anchor(
            release_batch_id=BATCH,
            target_id=assignment["target_id"],
        )
    )
    anchor["changed_files"] = ["src/main/java/example/ChangedService.java"]

    with pytest.raises(
        Exception,
        match="ANALYSIS_TRUTH_CLAIM_FORBIDDEN:changed_files",
    ):
        validate_rc72_n3_code_analysis_evidence_anchor(anchor)
