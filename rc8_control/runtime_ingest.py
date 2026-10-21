"""Storage-agnostic ingestion rules for central RC8 runtime facts and artifacts."""

from __future__ import annotations

from dataclasses import asdict
from typing import Dict

from .runtime_contracts import ArtifactAvailability, ArtifactManifest, RuntimeEventEnvelope


class RuntimeIngestError(RuntimeError):
    pass


class RuntimeIngestStore:
    """Deterministic W0/W1 ingest core.

    Real PostgreSQL/object-storage adapters will sit behind the same rules.  The
    service proves idempotency and artifact verification semantics before any
    transport/storage implementation is allowed to claim success.
    """

    def __init__(self) -> None:
        self._events_by_key: Dict[str, RuntimeEventEnvelope] = {}
        self._artifacts: Dict[str, ArtifactManifest] = {}

    def ingest_event(self, envelope: RuntimeEventEnvelope) -> RuntimeEventEnvelope:
        previous = self._events_by_key.get(envelope.idempotency_key)
        if previous is not None:
            if previous != envelope:
                raise RuntimeIngestError("IDEMPOTENCY_KEY_CONFLICT:%s" % envelope.idempotency_key)
            return previous
        self._events_by_key[envelope.idempotency_key] = envelope
        return envelope

    def event_count(self) -> int:
        return len(self._events_by_key)

    def declare_artifact(self, manifest: ArtifactManifest) -> ArtifactManifest:
        previous = self._artifacts.get(manifest.artifact_id)
        if previous is not None:
            if asdict(previous) != asdict(manifest):
                raise RuntimeIngestError("ARTIFACT_ID_CONFLICT:%s" % manifest.artifact_id)
            return previous
        if manifest.availability != ArtifactAvailability.DECLARED:
            raise RuntimeIngestError("NEW_ARTIFACT_MUST_START_DECLARED")
        self._artifacts[manifest.artifact_id] = manifest
        return manifest

    def begin_upload(self, artifact_id: str) -> ArtifactManifest:
        artifact = self._artifact(artifact_id)
        if artifact.availability not in (ArtifactAvailability.DECLARED, ArtifactAvailability.FAILED):
            raise RuntimeIngestError("ARTIFACT_UPLOAD_START_FORBIDDEN:%s" % artifact.availability.value)
        artifact.availability = ArtifactAvailability.UPLOADING
        return artifact

    def mark_upload_failed(self, artifact_id: str) -> ArtifactManifest:
        artifact = self._artifact(artifact_id)
        if artifact.availability not in (ArtifactAvailability.DECLARED, ArtifactAvailability.UPLOADING):
            raise RuntimeIngestError("ARTIFACT_UPLOAD_FAILURE_FORBIDDEN:%s" % artifact.availability.value)
        artifact.availability = ArtifactAvailability.FAILED
        return artifact

    def mark_available(self, artifact_id: str, verified_size_bytes: int, verified_sha256: str) -> ArtifactManifest:
        artifact = self._artifact(artifact_id)
        if artifact.availability != ArtifactAvailability.UPLOADING:
            raise RuntimeIngestError("ARTIFACT_NOT_UPLOADING:%s" % artifact.availability.value)
        if verified_size_bytes != artifact.size_bytes:
            raise RuntimeIngestError("ARTIFACT_SIZE_MISMATCH:%s" % artifact_id)
        if verified_sha256.lower() != artifact.sha256.lower():
            raise RuntimeIngestError("ARTIFACT_HASH_MISMATCH:%s" % artifact_id)
        artifact.availability = ArtifactAvailability.AVAILABLE
        return artifact

    def supersede(self, artifact_id: str) -> ArtifactManifest:
        artifact = self._artifact(artifact_id)
        if artifact.availability != ArtifactAvailability.AVAILABLE:
            raise RuntimeIngestError("ONLY_AVAILABLE_ARTIFACT_CAN_BE_SUPERSEDED")
        artifact.availability = ArtifactAvailability.SUPERSEDED
        return artifact

    def get_artifact(self, artifact_id: str) -> ArtifactManifest:
        return self._artifact(artifact_id)

    def _artifact(self, artifact_id: str) -> ArtifactManifest:
        try:
            return self._artifacts[artifact_id]
        except KeyError:
            raise RuntimeIngestError("ARTIFACT_NOT_FOUND:%s" % artifact_id)
