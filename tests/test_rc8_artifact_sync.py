from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from rc8_center.artifacts import ArtifactSyncError, FileArtifactStore, MemoryArtifactRepository
from rc8_runtime import ArtifactAvailability, RuntimeProducerKind
from rc8_runtime.artifacts import ArtifactManifest


def _manifest(content: bytes, *, artifact_id="ART-1", sha=None):
    return ArtifactManifest(
        artifact_id=artifact_id,
        test_run_id="RUN-1",
        work_item_id="WI-1",
        node_id="NODE-1",
        kind="SCREENSHOT",
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="browser-skill",
        file_name="step-1.png",
        sha256=sha or hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        case_id="TC-1",
        attempt_id="ATT-1",
        step_id="STEP-1",
        refs=["EV-1", "AST-1"],
    )


def test_artifact_is_not_available_until_size_and_hash_verify(tmp_path: Path) -> None:
    content = b"fake-png-binary"
    repo = MemoryArtifactRepository()
    store = FileArtifactStore(str(tmp_path / "assets"), repo)
    started = store.begin(_manifest(content))
    assert started.availability == ArtifactAvailability.PENDING_UPLOAD
    assert store.current_offset("ART-1") == 0

    next_offset = store.upload_chunk("ART-1", offset=0, data=content[:5])
    assert next_offset == 5
    assert repo.get("ART-1").availability == ArtifactAvailability.UPLOADING

    with pytest.raises(ArtifactSyncError, match="ARTIFACT_SIZE_MISMATCH"):
        store.complete("ART-1")

    store.upload_chunk("ART-1", offset=5, data=content[5:])
    completed = store.complete("ART-1")
    assert completed.availability == ArtifactAvailability.AVAILABLE
    assert store.content_path("ART-1").read_bytes() == content


def test_zero_byte_artifact_can_be_hash_verified_and_published(tmp_path: Path) -> None:
    content = b""
    repo = MemoryArtifactRepository()
    store = FileArtifactStore(str(tmp_path / "assets"), repo)
    started = store.begin(_manifest(content, artifact_id="ART-ZERO"))
    assert started.availability == ArtifactAvailability.PENDING_UPLOAD
    assert store.current_offset("ART-ZERO") == 0

    completed = store.complete("ART-ZERO")
    assert completed.availability == ArtifactAvailability.AVAILABLE
    assert store.content_path("ART-ZERO").is_file()
    assert store.content_path("ART-ZERO").read_bytes() == b""
    assert completed.sha256 == hashlib.sha256(b"").hexdigest()


def test_artifact_resume_uses_existing_offset(tmp_path: Path) -> None:
    content = b"resume-me"
    repo = MemoryArtifactRepository()
    first = FileArtifactStore(str(tmp_path / "assets"), repo)
    first.begin(_manifest(content))
    first.upload_chunk("ART-1", offset=0, data=content[:4])

    resumed = FileArtifactStore(str(tmp_path / "assets"), repo)
    assert resumed.current_offset("ART-1") == 4
    resumed.upload_chunk("ART-1", offset=4, data=content[4:])
    assert resumed.complete("ART-1").availability == ArtifactAvailability.AVAILABLE


def test_artifact_offset_mismatch_fails_closed(tmp_path: Path) -> None:
    content = b"abcdef"
    repo = MemoryArtifactRepository()
    store = FileArtifactStore(str(tmp_path / "assets"), repo)
    store.begin(_manifest(content))
    store.upload_chunk("ART-1", offset=0, data=b"abc")
    with pytest.raises(ArtifactSyncError, match="ARTIFACT_OFFSET_MISMATCH:3"):
        store.upload_chunk("ART-1", offset=0, data=b"def")


def test_artifact_hash_mismatch_marks_upload_failed(tmp_path: Path) -> None:
    content = b"real"
    repo = MemoryArtifactRepository()
    store = FileArtifactStore(str(tmp_path / "assets"), repo)
    store.begin(_manifest(content, sha="0" * 64))
    store.upload_chunk("ART-1", offset=0, data=content)
    with pytest.raises(ArtifactSyncError, match="ARTIFACT_HASH_MISMATCH"):
        store.complete("ART-1")
    assert repo.get("ART-1").availability == ArtifactAvailability.UPLOAD_FAILED


def test_artifact_id_conflict_is_rejected(tmp_path: Path) -> None:
    repo = MemoryArtifactRepository()
    store = FileArtifactStore(str(tmp_path / "assets"), repo)
    store.begin(_manifest(b"first"))
    with pytest.raises(ArtifactSyncError, match="ARTIFACT_ID_CONFLICT"):
        store.begin(_manifest(b"other"))
