"""PostgreSQL durable persistence for RC8 N5 PreparedAttempt state."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column

from rc8_center.prepared_attempt import AuthBindingMode, PreparedAttempt, PreparedAttemptError, PreparedAttemptState

from .postgres import Base, PostgresStore


class PreparedAttemptRow(Base):
    __tablename__ = "rc8_prepared_attempt"

    prepared_attempt_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    mission_node_id: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    reality_snapshot_id: Mapped[str] = mapped_column(String(300), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    data_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    verification_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reservation_ref: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    reservation_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    data_freshness_ref: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    auth_session_ref: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    auth_binding_mode: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    auth_acquired_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    auth_expires_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    freshness_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    environment_ref: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    route_ref: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    binding_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    released_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    release_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    quarantine_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


_ACTIVE_STATES = tuple(value.value for value in PreparedAttemptState if value not in {PreparedAttemptState.RELEASED, PreparedAttemptState.QUARANTINED})


class PostgresPreparedAttemptRepository:
    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    def get_prepared_attempt(self, prepared_attempt_id: str) -> Optional[PreparedAttempt]:
        with self.store.session() as session:
            row = session.get(PreparedAttemptRow, prepared_attempt_id)
            return self._value(row) if row is not None else None

    def current_for_attempt(self, test_run_id: str, case_id: str, attempt_id: str) -> Optional[PreparedAttempt]:
        with self.store.session() as session:
            rows = list(session.scalars(select(PreparedAttemptRow).where(PreparedAttemptRow.test_run_id == test_run_id, PreparedAttemptRow.case_id == case_id, PreparedAttemptRow.attempt_id == attempt_id, PreparedAttemptRow.state.in_(_ACTIVE_STATES))))
            if len(rows) > 1:
                raise PreparedAttemptError("MULTIPLE_CURRENT_PREPARED_ATTEMPTS")
            return self._value(rows[0]) if rows else None

    def save_prepared_attempt(self, value: PreparedAttempt) -> None:
        if not isinstance(value, PreparedAttempt):
            raise PreparedAttemptError("PREPARED_ATTEMPT_REQUIRED")
        with self.store.session() as session:
            history = list(session.scalars(select(PreparedAttemptRow).where(
                PreparedAttemptRow.test_run_id == value.test_run_id,
                PreparedAttemptRow.case_id == value.case_id,
                PreparedAttemptRow.attempt_id == value.attempt_id,
            )))
            competing = [row for row in history if row.prepared_attempt_id != value.prepared_attempt_id]
            if competing:
                if any(row.state in _ACTIVE_STATES for row in competing) and not value.terminal:
                    raise PreparedAttemptError("CURRENT_PREPARED_ATTEMPT_ALREADY_EXISTS")
                raise PreparedAttemptError("RETRY_REQUIRES_NEW_ATTEMPT_IDENTITY")
            row = session.get(PreparedAttemptRow, value.prepared_attempt_id)
            if row is None:
                row = PreparedAttemptRow(prepared_attempt_id=value.prepared_attempt_id)
                session.add(row)
            self._assign(row, value)

    @staticmethod
    def _assign(row: PreparedAttemptRow, value: PreparedAttempt) -> None:
        row.test_run_id = value.test_run_id
        row.mission_node_id = value.mission_node_id
        row.case_id = value.case_id
        row.attempt_id = value.attempt_id
        row.reality_snapshot_id = value.reality_snapshot_id
        row.state = value.state.value
        row.data_refs = list(value.data_refs)
        row.verification_evidence_refs = list(value.verification_evidence_refs)
        row.reservation_ref = value.reservation_ref
        row.reservation_evidence_refs = list(value.reservation_evidence_refs)
        row.data_freshness_ref = value.data_freshness_ref
        row.auth_session_ref = value.auth_session_ref
        row.auth_binding_mode = value.auth_binding_mode.value if value.auth_binding_mode else None
        row.auth_acquired_at = value.auth_acquired_at
        row.auth_expires_at = value.auth_expires_at
        row.freshness_evidence_refs = list(value.freshness_evidence_refs)
        row.environment_ref = value.environment_ref
        row.route_ref = value.route_ref
        row.binding_evidence_refs = list(value.binding_evidence_refs)
        row.created_at = value.created_at
        row.updated_at = value.updated_at
        row.released_at = value.released_at
        row.release_evidence_refs = list(value.release_evidence_refs)
        row.quarantine_reason = value.quarantine_reason

    @staticmethod
    def _value(row: PreparedAttemptRow) -> PreparedAttempt:
        return PreparedAttempt(prepared_attempt_id=row.prepared_attempt_id, test_run_id=row.test_run_id, mission_node_id=row.mission_node_id, case_id=row.case_id, attempt_id=row.attempt_id, reality_snapshot_id=row.reality_snapshot_id, data_refs=tuple(row.data_refs or ()), state=PreparedAttemptState(row.state), verification_evidence_refs=tuple(row.verification_evidence_refs or ()), reservation_ref=row.reservation_ref, reservation_evidence_refs=tuple(row.reservation_evidence_refs or ()), data_freshness_ref=row.data_freshness_ref, auth_session_ref=row.auth_session_ref, auth_binding_mode=AuthBindingMode(row.auth_binding_mode) if row.auth_binding_mode else None, auth_acquired_at=int(row.auth_acquired_at) if row.auth_acquired_at is not None else None, auth_expires_at=int(row.auth_expires_at) if row.auth_expires_at is not None else None, freshness_evidence_refs=tuple(row.freshness_evidence_refs or ()), environment_ref=row.environment_ref, route_ref=row.route_ref, binding_evidence_refs=tuple(row.binding_evidence_refs or ()), created_at=int(row.created_at), updated_at=int(row.updated_at), released_at=int(row.released_at) if row.released_at is not None else None, release_evidence_refs=tuple(row.release_evidence_refs or ()), quarantine_reason=row.quarantine_reason)
