from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import Artifact, CandidatePayloadError, CandidatePayloadReader
from rc7_runtime.truth_overlay import append_entity


def _persist_candidate(tmp_path, *, content_ref_override=None):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    artifact_id = "ART-CANDIDATE-1"
    task_id = "TASK-CANDIDATE-1"
    envelope = {
        "task_id": task_id,
        "artifact": {
            "artifact_id": artifact_id,
            "artifact_type": "REQUIREMENT_MODEL",
            "content_ref": "source://worker-declared",
            "parent_refs": ["file:///requirements/sst.md"],
            "evidence_refs": ["EVD-SOURCE-1"],
        },
        "semantic_payload": {
            "source_assertions": [{"id": "S1", "text": "rule"}],
            "boundaries": [{"id": "B1", "rule": "inclusive upper bound"}],
        },
        "evidence": [{"kind": "SOURCE", "source_ref": "file:///requirements/sst.md", "content_ref": "EVD-SOURCE-1"}],
    }
    raw = (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": ")) + "\n").encode("utf-8")
    path = tmp_path / "candidate.json"
    path.write_bytes(raw)
    ref = content_ref_override or ("file://" + str(path.resolve()))
    artifact = Artifact(
        artifact_id=artifact_id,
        mission_id="MISSION-CANDIDATE",
        artifact_type="REQUIREMENT_MODEL",
        producer_task_id=task_id,
        content_ref=ref,
        parent_refs=["file:///requirements/sst.md"],
        evidence_refs=["EVD-SOURCE-1"],
        content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
    )
    append_entity(truth, artifact, release_id="RC7")
    return truth, path, artifact


def test_candidate_reader_returns_verified_semantic_payload(tmp_path) -> None:
    truth, _path, artifact = _persist_candidate(tmp_path)
    loaded = CandidatePayloadReader().load(
        truth,
        artifact.artifact_id,
        expected_mission_id="MISSION-CANDIDATE",
        expected_task_id="TASK-CANDIDATE-1",
    )
    assert loaded.artifact_type == "REQUIREMENT_MODEL"
    assert loaded.semantic_payload["boundaries"][0]["id"] == "B1"
    assert loaded.content_hash == artifact.content_hash


def test_candidate_reader_rejects_file_tampering_after_r1_persist(tmp_path) -> None:
    truth, path, artifact = _persist_candidate(tmp_path)
    path.write_text('{"tampered": true}\n', encoding="utf-8")

    with pytest.raises(CandidatePayloadError, match="CANDIDATE_CONTENT_HASH_MISMATCH"):
        CandidatePayloadReader().load(truth, artifact.artifact_id)


def test_candidate_reader_rejects_non_runtime_content_reference(tmp_path) -> None:
    truth, _path, artifact = _persist_candidate(
        tmp_path,
        content_ref_override="artifact://worker-controlled-location",
    )
    with pytest.raises(CandidatePayloadError, match="CANDIDATE_CONTENT_MUST_BE_RUNTIME_FILE"):
        CandidatePayloadReader().load(truth, artifact.artifact_id)


def test_candidate_reader_rejects_wrong_expected_identity(tmp_path) -> None:
    truth, _path, artifact = _persist_candidate(tmp_path)
    reader = CandidatePayloadReader()
    with pytest.raises(CandidatePayloadError, match="CANDIDATE_MISSION_MISMATCH"):
        reader.load(truth, artifact.artifact_id, expected_mission_id="MISSION-OTHER")
    with pytest.raises(CandidatePayloadError, match="CANDIDATE_PRODUCER_TASK_MISMATCH"):
        reader.load(truth, artifact.artifact_id, expected_task_id="TASK-OTHER")
