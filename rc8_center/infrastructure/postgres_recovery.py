"""PostgreSQL persistence for RC8 lease recovery incidents."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import BigInteger, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from rc8_center.recovery import (
    RecoveryIncident,
    RecoveryIncidentState,
    RecoveryReason,
    RecoveryResolution,
)

from .postgres import Base, PostgresStore


class RecoveryIncidentRow(Base):
    __tablename__ = "rc8_recovery_incident"

    incident_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    work_item_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    node_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    lease_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    work_item_state: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    runtime_event_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    opened_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    resolution: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    decision_ref: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    evidence_ref: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


class PostgresRecoveryRepository:
    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    def upsert_open(self, value: RecoveryIncident) -> RecoveryIncident:
        with self.store.session() as session:
            row = session.get(RecoveryIncidentRow, value.incident_id)
            if row is None:
                session.add(self._row(value))
                return value
            current = self._value(row)
            identity = (
                "work_item_id", "test_run_id", "node_id", "lease_id", "reason", "opened_at",
            )
            for name in identity:
                if getattr(current, name) != getattr(value, name):
                    raise ValueError("RECOVERY_INCIDENT_IDENTITY_CONFLICT:%s" % name)
            if current.state == RecoveryIncidentState.RESOLVED:
                return current
            row.work_item_state = value.work_item_state
            row.runtime_event_count = value.runtime_event_count
            return self._value(row)

    def resolve(self, value: RecoveryIncident) -> RecoveryIncident:
        if value.state != RecoveryIncidentState.RESOLVED:
            raise ValueError("RECOVERY_RESOLUTION_REQUIRES_RESOLVED_STATE")
        if value.resolution is None or value.resolved_at is None:
            raise ValueError("RECOVERY_RESOLUTION_DETAILS_REQUIRED")
        with self.store.session() as session:
            row = session.get(RecoveryIncidentRow, value.incident_id)
            if row is None:
                raise ValueError("RECOVERY_INCIDENT_NOT_FOUND")
            current = self._value(row)
            if current.state == RecoveryIncidentState.RESOLVED:
                if current != value:
                    raise ValueError("RECOVERY_RESOLUTION_IMMUTABLE")
                return current
            row.state = value.state.value
            row.resolution = value.resolution.value
            row.decision_ref = value.decision_ref
            row.evidence_ref = value.evidence_ref
            row.explanation = value.explanation
            row.resolved_at = value.resolved_at
            row.work_item_state = value.work_item_state
            row.runtime_event_count = value.runtime_event_count
            return self._value(row)

    def get(self, incident_id: str) -> Optional[RecoveryIncident]:
        with self.store.session() as session:
            row = session.get(RecoveryIncidentRow, incident_id)
            return self._value(row) if row is not None else None

    def list_open(self) -> List[RecoveryIncident]:
        with self.store.session() as session:
            rows = session.scalars(
                select(RecoveryIncidentRow)
                .where(RecoveryIncidentRow.state == RecoveryIncidentState.OPEN.value)
                .order_by(RecoveryIncidentRow.opened_at, RecoveryIncidentRow.incident_id)
            )
            return [self._value(row) for row in rows]

    def list_for_test_run(self, test_run_id: str) -> List[RecoveryIncident]:
        with self.store.session() as session:
            rows = session.scalars(
                select(RecoveryIncidentRow)
                .where(RecoveryIncidentRow.test_run_id == test_run_id)
                .order_by(RecoveryIncidentRow.opened_at, RecoveryIncidentRow.incident_id)
            )
            return [self._value(row) for row in rows]

    @staticmethod
    def _row(v: RecoveryIncident) -> RecoveryIncidentRow:
        return RecoveryIncidentRow(
            incident_id=v.incident_id,
            work_item_id=v.work_item_id,
            test_run_id=v.test_run_id,
            node_id=v.node_id,
            lease_id=v.lease_id,
            work_item_state=v.work_item_state,
            reason=v.reason.value,
            runtime_event_count=v.runtime_event_count,
            state=v.state.value,
            opened_at=v.opened_at,
            resolution=v.resolution.value if v.resolution else None,
            decision_ref=v.decision_ref,
            evidence_ref=v.evidence_ref,
            explanation=v.explanation,
            resolved_at=v.resolved_at,
        )

    @staticmethod
    def _value(row: RecoveryIncidentRow) -> RecoveryIncident:
        return RecoveryIncident(
            incident_id=row.incident_id,
            work_item_id=row.work_item_id,
            test_run_id=row.test_run_id,
            node_id=row.node_id,
            lease_id=row.lease_id,
            work_item_state=row.work_item_state,
            reason=RecoveryReason(row.reason),
            runtime_event_count=int(row.runtime_event_count),
            state=RecoveryIncidentState(row.state),
            opened_at=int(row.opened_at),
            resolution=RecoveryResolution(row.resolution) if row.resolution else None,
            decision_ref=row.decision_ref,
            evidence_ref=row.evidence_ref,
            explanation=row.explanation,
            resolved_at=row.resolved_at,
        )
