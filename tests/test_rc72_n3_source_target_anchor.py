from pathlib import Path
import hashlib
import json

import pytest

from rc7_runtime.rc72_n3_source_target_anchor import (
    N3SourceTargetEvidenceAnchorError,
    N3SourceTargetEvidenceAnchorService,
    validate_rc72_n3_dsh_evidence_anchor,
)
from rc7_runtime.rc72_n3_source_target_handoff import N3SourceTargetDshHandoffService

from rc72_n2_test_support import BATCH, COMMIT, MISSION
from test_rc72_n3_source_target_handoff import (
    APPLICATION,
    TOOL,
    _launcher,
    _ready,
)


def _attempt(tmp_path: Path):
    truth, _assigned = _ready(tmp_path)
    result = N3SourceTargetDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth),
        allowed_tools=[TOOL],
    ).handoff(release_batch_id=BATCH, application_id=APPLICATION)
    attempt = truth.query(
        "rc72_n3_source_target_attempt", attempt_id=result["attempt_id"]
    )[0]
    return truth, attempt


def _raw_path(attempt):
    refs = [
        ref for ref in attempt["runtime_evidence_refs"]
        if ref.startswith("file://")
    ]
    assert len(refs) == 1
    return Path(refs[0][len("file://"):])


def _service(tmp_path: Path, truth):
    return N3SourceTargetEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state-n3-source"),
    )


def test_n3_raw_dsh_attempt_is_sha256_anchored_without_promoting_source_truth(tmp_path: Path):
    truth, attempt = _attempt(tmp_path)
    raw_path = _raw_path(attempt)
    expected_hash = "sha256:" + hashlib.sha256(raw_path.read_bytes()).hexdigest()

    anchor = _service(tmp_path, truth).anchor(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )

    assert anchor["attempt_id"] == attempt["attempt_id"]
    assert anchor["dsh_session_id"] == attempt["dsh_session_id"]
    assert anchor["raw_output_sha256"] == expected_hash
    assert anchor["raw_output_ref"] == "file://" + str(raw_path.resolve())
    assert anchor["candidate_schema"] == "RC72_N3_SOURCE_TARGET_CANDIDATE_V1"
    for forbidden in (
        "targets", "repository_ref", "source_revision", "target_id",
        "source_mapping", "source_mapping_accepted", "changed_files",
        "changed_symbols", "codegraph_result",
    ):
        assert forbidden not in anchor
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []
    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    assert n4["state"] == "NOT_STARTED"


def test_n3_raw_anchor_replay_is_idempotent(tmp_path: Path):
    truth, _attempt_row = _attempt(tmp_path)
    service = _service(tmp_path, truth)

    first = service.anchor(release_batch_id=BATCH, application_id=APPLICATION)
    second = service.anchor(release_batch_id=BATCH, application_id=APPLICATION)

    assert first["anchor_id"] == second["anchor_id"]
    assert first["raw_output_sha256"] == second["raw_output_sha256"]
    assert len(truth.query("rc72_n3_dsh_evidence_anchor", release_batch_id=BATCH)) == 1


def test_n3_raw_anchor_detects_bytes_changed_after_anchor(tmp_path: Path):
    truth, attempt = _attempt(tmp_path)
    service = _service(tmp_path, truth)
    first = service.anchor(release_batch_id=BATCH, application_id=APPLICATION)
    raw_path = _raw_path(attempt)

    raw_path.write_bytes(raw_path.read_bytes() + b"\n")

    with pytest.raises(
        N3SourceTargetEvidenceAnchorError,
        match="ANCHOR_CONFLICT:raw_output_sha256",
    ):
        service.anchor(release_batch_id=BATCH, application_id=APPLICATION)

    stored = truth.query(
        "rc72_n3_dsh_evidence_anchor", anchor_id=first["anchor_id"]
    )[0]
    assert stored["raw_output_sha256"] == first["raw_output_sha256"]


def test_n3_raw_anchor_rejects_session_mismatch_before_first_anchor(tmp_path: Path):
    truth, attempt = _attempt(tmp_path)
    raw_path = _raw_path(attempt)
    lines = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for item in lines:
        if item.get("type") == "session":
            item["session_id"] = "session-tampered"
    raw_path.write_text(
        "\n".join(json.dumps(item) for item in lines) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        N3SourceTargetEvidenceAnchorError,
        match="DSH_SESSION_MISMATCH",
    ):
        _service(tmp_path, truth).anchor(
            release_batch_id=BATCH,
            application_id=APPLICATION,
        )

    assert truth.query("rc72_n3_dsh_evidence_anchor", release_batch_id=BATCH) == []


def test_n3_raw_anchor_rejects_tool_call_mismatch_before_first_anchor(tmp_path: Path):
    truth, attempt = _attempt(tmp_path)
    raw_path = _raw_path(attempt)
    lines = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for item in lines:
        if item.get("type") == "tool_call":
            item["tool_name"] = "different-source-probe"
    raw_path.write_text(
        "\n".join(json.dumps(item) for item in lines) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        N3SourceTargetEvidenceAnchorError,
        match="TOOL_CALL_EVIDENCE_MISMATCH",
    ):
        _service(tmp_path, truth).anchor(
            release_batch_id=BATCH,
            application_id=APPLICATION,
        )

    assert truth.query("rc72_n3_dsh_evidence_anchor", release_batch_id=BATCH) == []


def test_n3_anchor_contract_rejects_repository_truth_smuggling(tmp_path: Path):
    truth, _attempt_row = _attempt(tmp_path)
    anchor = dict(
        _service(tmp_path, truth).anchor(
            release_batch_id=BATCH,
            application_id=APPLICATION,
        )
    )
    anchor["repository_ref"] = "git://repo/BLOAN"

    with pytest.raises(Exception, match="SOURCE_TRUTH_CLAIM_FORBIDDEN:repository_ref"):
        validate_rc72_n3_dsh_evidence_anchor(anchor)
