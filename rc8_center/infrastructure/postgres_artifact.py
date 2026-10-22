"""PostgreSQL Artifact metadata repository.

Artifact bytes remain behind Artifact Store; metadata/availability used by R1
projection are durable in PostgreSQL so governance evidence gates do not depend
on the W1 JSON fallback.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from rc8_runtime import ArtifactAvailability, RuntimeProducerKind
from rc8_runtime.artifacts import ArtifactManifest

from .postgres import Base, PostgresStore


class ArtifactMetadataRow(Base):
    __tablename__ = "rc8_artifact_metadata"

    artifact_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    work_item_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    producer_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    producer_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    availability: Mapped[str] = mapped_column(String(64), nullable=False)
    case_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    attempt_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    step_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PostgresArtifactRepository:
    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    def get(self, artifact_id: str) -> Optional[ArtifactManifest]:
        with self.store.session() as session:
            row = session.get(ArtifactMetadataRow, artifact_id)
            return self._from_row(row) if row is not None else None

    def upsert(self, manifest: ArtifactManifest) -> None:
        with self.store.session() as session:
            row = session.get(ArtifactMetadataRow, manifest.artifact_id)
            if row is None:
                session.add(self._to_row(manifest))
                return
            existing = self._from_row(row)
            immutable = (
                "test_run_id", "work_item_id", "node_id", "kind", "producer_kind", "producer_ref",
                "file_name", "sha256", "size_bytes", "case_id", "attempt_id", "step_id", "created_at",
            )
            for name in immutable:
                if getattr(existing, name) != getattr(manifest, name):
                    raise ValueError("ARTIFACT_IDENTITY_IMMUTABLE:%s" % name)
            if not set(existing.refs).issubset(set(manifest.refs)):
                raise ValueError("ARTIFACT_REFS_CANNOT_SHRINK")
            if existing.metadata != manifest.metadata and existing.availability == ArtifactAvailability.AVAILABLE:
                raise ValueError("AVAILABLE_ARTIFACT_METADATA_IMMUTABLE")
            if existing.availability == ArtifactAvailability.AVAILABLE and manifest.availability != ArtifactAvailability.AVAILABLE:
                raise ValueError("AVAILABLE_ARTIFACT_CANNOT_REGRESS")
            row.availability = manifest.availability.value
            row.refs = list(manifest.refs)
            row.metadata_json = dict(manifest.metadata)

    @staticmethod
    def _to_row(value: ArtifactManifest) -> ArtifactMetadataRow:
        return ArtifactMetadataRow(
            artifact_id=value.artifact_id,
            test_run_id=value.test_run_id,
            work_item_id=value.work_item_id,
            node_id=value.node_id,
            kind=value.kind,
            producer_kind=value.producer_kind.value,
            producer_ref=value.producer_ref,
            file_name=value.file_name,
            sha256=value.sha256,
            size_bytes=value.size_bytes,
            availability=value.availability.value,
            case_id=value.case_id,
            attempt_id=value.attempt_id,
            step_id=value.step_id,
            refs=list(value.refs),
            metadata_json=dict(value.metadata),
            created_at=value.created_at,
        )

    @staticmethod
    def _from_row(row: ArtifactMetadataRow) -> ArtifactManifest:
        return ArtifactManifest(
            artifact_id=row.artifact_id,
            test_run_id=row.test_run_id,
            work_item_id=row.work_item_id,
            node_id=row.node_id,
            kind=row.kind,
            producer_kind=RuntimeProducerKind(row.producer_kind),
            producer_ref=row.producer_ref,
            file_name=row.file_name,
            sha256=row.sha256,
            size_bytes=int(row.size_bytes),
            availability=ArtifactAvailability(row.availability),
            case_id=row.case_id,
            attempt_id=row.attempt_id,
            step_id=row.step_id,
            refs=list(row.refs or []),
            metadata=dict(row.metadata_json or {}),
            created_at=int(row.created_at),
        )
