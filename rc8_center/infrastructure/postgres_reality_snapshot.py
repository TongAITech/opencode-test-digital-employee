"""PostgreSQL durable persistence for RC8 N1 RealitySnapshot truth."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, Boolean, JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column

from rc8_center.reality_snapshot import CapabilitySnapshot, RealityBlocker, RealitySnapshot
from rc8_runtime.contracts import CapabilityState
from rc8_runtime.mission_nodes import MissionNodeType

from .postgres import Base, PostgresStore


class RealitySnapshotRow(Base):
    __tablename__ = "rc8_reality_snapshot"

    snapshot_id: Mapped[str] = mapped_column(String(300), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    scope_version: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    snapshot_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_revision: Mapped[str] = mapped_column(String(300), nullable=False)
    environment_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    capabilities: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    blockers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PostgresRealitySnapshotRepository:
    """Durable N1 snapshots. Redis must never replace this truth."""

    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    def get_reality_snapshot(self, snapshot_id: str) -> Optional[RealitySnapshot]:
        with self.store.session() as session:
            row = session.get(RealitySnapshotRow, snapshot_id)
            return self._value(row) if row is not None else None

    def latest_reality_snapshot(self, test_run_id: str, scope_version: str) -> Optional[RealitySnapshot]:
        with self.store.session() as session:
            row = session.scalar(
                select(RealitySnapshotRow)
                .where(
                    RealitySnapshotRow.test_run_id == test_run_id,
                    RealitySnapshotRow.scope_version == scope_version,
                )
                .order_by(RealitySnapshotRow.snapshot_version.desc())
                .limit(1)
            )
            return self._value(row) if row is not None else None

    def save_reality_snapshot(self, snapshot: RealitySnapshot) -> None:
        if not isinstance(snapshot, RealitySnapshot):
            raise ValueError("REALITY_SNAPSHOT_REQUIRED")
        with self.store.session() as session:
            existing = session.get(RealitySnapshotRow, snapshot.snapshot_id)
            if existing is not None:
                if self._value(existing) != snapshot:
                    raise ValueError("REALITY_SNAPSHOT_ID_CONFLICT")
                return
            latest = session.scalar(
                select(RealitySnapshotRow)
                .where(
                    RealitySnapshotRow.test_run_id == snapshot.test_run_id,
                    RealitySnapshotRow.scope_version == snapshot.scope_version,
                )
                .order_by(RealitySnapshotRow.snapshot_version.desc())
                .limit(1)
            )
            expected = 1 if latest is None else int(latest.snapshot_version) + 1
            if snapshot.snapshot_version != expected:
                raise ValueError("REALITY_SNAPSHOT_VERSION_NON_MONOTONIC")
            session.add(
                RealitySnapshotRow(
                    snapshot_id=snapshot.snapshot_id,
                    test_run_id=snapshot.test_run_id,
                    scope_version=snapshot.scope_version,
                    snapshot_version=snapshot.snapshot_version,
                    source_revision=snapshot.source_revision,
                    environment_refs=list(snapshot.environment_refs),
                    capabilities=[self._capability_json(value) for value in snapshot.capabilities],
                    blockers=[self._blocker_json(value) for value in snapshot.blockers],
                    fingerprint=snapshot.fingerprint,
                    ready=snapshot.ready,
                    created_at=snapshot.created_at,
                )
            )

    @staticmethod
    def _capability_json(value: CapabilitySnapshot) -> dict:
        return {
            "requirement_id": value.requirement_id,
            "capability_id": value.capability_id,
            "execution_node_id": value.execution_node_id,
            "state": value.state.value,
            "probe_ref": value.probe_ref,
            "evidence_refs": list(value.evidence_refs),
            "verified_at": value.verified_at,
        }

    @staticmethod
    def _blocker_json(value: RealityBlocker) -> dict:
        return {
            "blocker_id": value.blocker_id,
            "requirement_id": value.requirement_id,
            "capability_id": value.capability_id,
            "reason": value.reason,
            "affected_mission_nodes": [item.value for item in value.affected_mission_nodes],
            "evidence_refs": list(value.evidence_refs),
        }

    @staticmethod
    def _value(row: RealitySnapshotRow) -> RealitySnapshot:
        capabilities = tuple(
            CapabilitySnapshot(
                requirement_id=value["requirement_id"],
                capability_id=value["capability_id"],
                execution_node_id=value["execution_node_id"],
                state=CapabilityState(value["state"]),
                probe_ref=value["probe_ref"],
                evidence_refs=tuple(value.get("evidence_refs") or ()),
                verified_at=int(value["verified_at"]),
            )
            for value in (row.capabilities or [])
        )
        blockers = tuple(
            RealityBlocker(
                blocker_id=value["blocker_id"],
                requirement_id=value["requirement_id"],
                capability_id=value["capability_id"],
                reason=value["reason"],
                affected_mission_nodes=tuple(MissionNodeType(item) for item in value.get("affected_mission_nodes") or ()),
                evidence_refs=tuple(value.get("evidence_refs") or ()),
            )
            for value in (row.blockers or [])
        )
        return RealitySnapshot(
            snapshot_id=row.snapshot_id,
            test_run_id=row.test_run_id,
            scope_version=row.scope_version,
            snapshot_version=int(row.snapshot_version),
            source_revision=row.source_revision,
            environment_refs=tuple(row.environment_refs or ()),
            capabilities=capabilities,
            blockers=blockers,
            fingerprint=row.fingerprint,
            created_at=int(row.created_at),
        )
