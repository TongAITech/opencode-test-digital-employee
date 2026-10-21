"""RC8 Center artifact-sync service.

The service supports resumable offset-based writes and only marks an artifact
AVAILABLE after size and SHA-256 verification. Metadata persistence is injected;
the memory repository is unit-test only.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path
from typing import Dict, Optional, Protocol

from rc8_runtime import ArtifactAvailability
from rc8_runtime.artifacts import ArtifactManifest


class ArtifactSyncError(ValueError):
    pass


class ArtifactRepository(Protocol):
    def get(self, artifact_id: str) -> Optional[ArtifactManifest]: ...
    def upsert(self, manifest: ArtifactManifest) -> None: ...


class MemoryArtifactRepository:
    def __init__(self) -> None:
        self._items: Dict[str, ArtifactManifest] = {}

    def get(self, artifact_id: str) -> Optional[ArtifactManifest]:
        return self._items.get(artifact_id)

    def upsert(self, manifest: ArtifactManifest) -> None:
        self._items[manifest.artifact_id] = manifest


class FileArtifactStore:
    def __init__(self, root: str, repository: ArtifactRepository) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.repository = repository

    def begin(self, manifest: ArtifactManifest) -> ArtifactManifest:
        if not isinstance(manifest, ArtifactManifest):
            raise ArtifactSyncError("ARTIFACT_MANIFEST_REQUIRED")
        current = self.repository.get(manifest.artifact_id)
        if current is not None:
            if self._identity_tuple(current) != self._identity_tuple(manifest):
                raise ArtifactSyncError("ARTIFACT_ID_CONFLICT")
            if current.availability != ArtifactAvailability.AVAILABLE:
                part = self._part_path(manifest.artifact_id)
                part.parent.mkdir(parents=True, exist_ok=True)
                part.touch(exist_ok=True)
            return current
        pending = replace(manifest, availability=ArtifactAvailability.PENDING_UPLOAD)
        self.repository.upsert(pending)
        part = self._part_path(manifest.artifact_id)
        part.parent.mkdir(parents=True, exist_ok=True)
        # Always materialize the pending file, including size==0 artifacts such
        # as an empty stderr.log from a successful Maven execution. Otherwise
        # complete() would have no byte stream to hash/atomically publish.
        part.touch(exist_ok=True)
        return pending

    def current_offset(self, artifact_id: str) -> int:
        self._require_manifest(artifact_id)
        part = self._part_path(artifact_id)
        return part.stat().st_size if part.exists() else 0

    def upload_chunk(self, artifact_id: str, *, offset: int, data: bytes) -> int:
        manifest = self._require_manifest(artifact_id)
        if manifest.availability == ArtifactAvailability.AVAILABLE:
            return manifest.size_bytes
        if not isinstance(offset, int) or offset < 0:
            raise ArtifactSyncError("ARTIFACT_OFFSET_INVALID")
        if not isinstance(data, (bytes, bytearray)):
            raise ArtifactSyncError("ARTIFACT_CHUNK_BYTES_REQUIRED")
        current = self.current_offset(artifact_id)
        if current != offset:
            raise ArtifactSyncError("ARTIFACT_OFFSET_MISMATCH:%s" % current)
        if current + len(data) > manifest.size_bytes:
            raise ArtifactSyncError("ARTIFACT_SIZE_OVERFLOW")
        path = self._part_path(artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as fh:
            fh.write(bytes(data))
            fh.flush()
            os.fsync(fh.fileno())
        updated = replace(manifest, availability=ArtifactAvailability.UPLOADING)
        self.repository.upsert(updated)
        return current + len(data)

    def complete(self, artifact_id: str) -> ArtifactManifest:
        manifest = self._require_manifest(artifact_id)
        if manifest.availability == ArtifactAvailability.AVAILABLE:
            return manifest
        part = self._part_path(artifact_id)
        if not part.exists():
            if manifest.size_bytes == 0:
                part.parent.mkdir(parents=True, exist_ok=True)
                part.touch()
            else:
                raise ArtifactSyncError("ARTIFACT_PART_MISSING")
        actual_size = part.stat().st_size
        if actual_size != manifest.size_bytes:
            raise ArtifactSyncError("ARTIFACT_SIZE_MISMATCH:%s:%s" % (actual_size, manifest.size_bytes))
        digest = hashlib.sha256()
        with part.open("rb") as fh:
            while True:
                block = fh.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
        actual_hash = digest.hexdigest().lower()
        if actual_hash != manifest.sha256.lower():
            failed = replace(manifest, availability=ArtifactAvailability.UPLOAD_FAILED)
            self.repository.upsert(failed)
            raise ArtifactSyncError("ARTIFACT_HASH_MISMATCH")
        final_path = self._final_path(artifact_id, manifest.file_name)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(part), str(final_path))
        available = replace(manifest, availability=ArtifactAvailability.AVAILABLE)
        self.repository.upsert(available)
        return available

    def content_path(self, artifact_id: str) -> Path:
        manifest = self._require_manifest(artifact_id)
        if manifest.availability != ArtifactAvailability.AVAILABLE:
            raise ArtifactSyncError("ARTIFACT_NOT_AVAILABLE")
        return self._final_path(artifact_id, manifest.file_name)

    def _require_manifest(self, artifact_id: str) -> ArtifactManifest:
        manifest = self.repository.get(artifact_id)
        if manifest is None:
            raise ArtifactSyncError("ARTIFACT_NOT_FOUND")
        return manifest

    def _part_path(self, artifact_id: str) -> Path:
        return self.root / "pending" / (artifact_id + ".part")

    def _final_path(self, artifact_id: str, file_name: str) -> Path:
        safe_name = Path(file_name).name
        return self.root / "available" / artifact_id / safe_name

    @staticmethod
    def _identity_tuple(manifest: ArtifactManifest):
        return (
            manifest.artifact_id,
            manifest.test_run_id,
            manifest.work_item_id,
            manifest.node_id,
            manifest.kind,
            manifest.sha256.lower(),
            manifest.size_bytes,
            manifest.file_name,
        )
