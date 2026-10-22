"""Formal RC8 Artifact upload service.

The byte store is local/volume-backed for the first formal Center deployment,
while metadata is durable in PostgreSQL. Every mutating upload operation is
re-authorized against PostgreSQL WorkItem identity/state plus the active Redis
owner+lease token. Artifact availability is not trusted until FileArtifactStore
verifies exact size and SHA-256 and atomically publishes the final file.

Completing an Artifact immediately replays the R1 governance projector so any
terminal Attempt that was correctly held PENDING on unavailable evidence can
advance only after that evidence is AVAILABLE.
"""
from __future__ import annotations

from typing import Dict, Optional

from rc8_runtime.artifacts import ArtifactManifest

from .artifacts import ArtifactSyncError, FileArtifactStore
from .control_plane import CenterControlError
from .formal_control import FormalCenterControlPlane
from .governance_event_projector import GovernanceEventProjector


class FormalArtifactError(RuntimeError):
    pass


class FormalArtifactService:
    def __init__(
        self,
        store: FileArtifactStore,
        control: FormalCenterControlPlane,
        projector: GovernanceEventProjector,
    ) -> None:
        self.store = store
        self.control = control
        self.projector = projector

    def begin(self, manifest: ArtifactManifest, *, lease_id: str) -> Dict[str, object]:
        self._authorize_manifest(manifest, lease_id=lease_id)
        try:
            stored = self.store.begin(manifest)
            offset = self.store.current_offset(manifest.artifact_id)
        except (ArtifactSyncError, ValueError) as exc:
            raise FormalArtifactError(str(exc)) from exc
        return {
            "manifest": stored,
            "offset": offset,
            "truth_note": "LEASE_AUTHORIZED_UPLOAD_PENDING_HASH_VERIFICATION",
        }

    def status(self, artifact_id: str, *, node_id: str, lease_id: str) -> Dict[str, object]:
        manifest = self._require_manifest(artifact_id)
        self._require_same_node(manifest, node_id)
        self._authorize_manifest(manifest, lease_id=lease_id)
        try:
            offset = self.store.current_offset(artifact_id)
        except (ArtifactSyncError, ValueError) as exc:
            raise FormalArtifactError(str(exc)) from exc
        return {"manifest": manifest, "offset": offset}

    def upload_chunk(
        self,
        artifact_id: str,
        *,
        node_id: str,
        lease_id: str,
        offset: int,
        data: bytes,
    ) -> Dict[str, object]:
        manifest = self._require_manifest(artifact_id)
        self._require_same_node(manifest, node_id)
        self._authorize_manifest(manifest, lease_id=lease_id)
        try:
            next_offset = self.store.upload_chunk(artifact_id, offset=offset, data=data)
            current = self._require_manifest(artifact_id)
        except (ArtifactSyncError, ValueError) as exc:
            raise FormalArtifactError(str(exc)) from exc
        return {
            "artifact_id": artifact_id,
            "offset": next_offset,
            "availability": current.availability.value,
        }

    def complete(self, artifact_id: str, *, node_id: str, lease_id: str) -> Dict[str, object]:
        manifest = self._require_manifest(artifact_id)
        self._require_same_node(manifest, node_id)
        self._authorize_manifest(manifest, lease_id=lease_id)
        try:
            available = self.store.complete(artifact_id)
        except (ArtifactSyncError, ValueError) as exc:
            raise FormalArtifactError(str(exc)) from exc

        # Evidence-dependent runtime facts stay PENDING until this point. Replay
        # after atomic publication so projection never observes an unverified file.
        projection = self.projector.replay()
        return {
            "manifest": available,
            "projection": projection,
            "truth_note": "ARTIFACT_AVAILABLE_AFTER_SIZE_SHA256_VERIFICATION",
        }

    def _authorize_manifest(self, manifest: ArtifactManifest, *, lease_id: str) -> None:
        try:
            self.control.authorize_work_item_write(
                test_run_id=manifest.test_run_id,
                work_item_id=manifest.work_item_id,
                node_id=manifest.node_id,
                lease_id=lease_id,
            )
        except (CenterControlError, ValueError) as exc:
            raise FormalArtifactError(str(exc)) from exc

    def _require_manifest(self, artifact_id: str) -> ArtifactManifest:
        manifest: Optional[ArtifactManifest] = self.store.repository.get(artifact_id)
        if manifest is None:
            raise FormalArtifactError("ARTIFACT_NOT_FOUND")
        return manifest

    @staticmethod
    def _require_same_node(manifest: ArtifactManifest, node_id: str) -> None:
        if manifest.node_id != str(node_id).strip():
            raise FormalArtifactError("ARTIFACT_NODE_MISMATCH")
