"""PostgreSQL persistence for RC8 model/provider recovery checkpoints."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import BigInteger, JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column

from rc8_runtime.provider_recovery import RecoveryCheckpoint, SideEffectState

from .postgres import Base, PostgresStore


class ProviderRecoveryCheckpointRow(Base):
    __tablename__ = "rc8_provider_recovery_checkpoint"

    checkpoint_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    stage_instance_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    work_item_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    input_snapshot_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    cursor: Mapped[str] = mapped_column(String(1000), nullable=False)
    side_effect_state: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_effect_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    provider_ref: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    model_ref: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    closed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    close_reason: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)


@dataclass(frozen=True)
class StoredRecoveryCheckpoint:
    checkpoint: RecoveryCheckpoint
    provider_ref: Optional[str]
    model_ref: Optional[str]
    created_at: int
    updated_at: int
    closed_at: Optional[int]
    close_reason: Optional[str]

    @property
    def is_open(self) -> bool:
        return self.closed_at is None


class PostgresProviderRecoveryCheckpointRepository:
    """Durable checkpoint repository; Redis is coordination only, never truth."""

    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    def save(self, checkpoint: RecoveryCheckpoint, *, provider_ref: Optional[str] = None, model_ref: Optional[str] = None, now: Optional[int] = None) -> StoredRecoveryCheckpoint:
        if not isinstance(checkpoint, RecoveryCheckpoint):
            raise ValueError("PROVIDER_RECOVERY_CHECKPOINT_REQUIRED")
        timestamp = int(now if now is not None else time.time())
        if timestamp <= 0:
            raise ValueError("PROVIDER_RECOVERY_CHECKPOINT_TIME_INVALID")
        with self.store.session() as session:
            existing = session.get(ProviderRecoveryCheckpointRow, checkpoint.checkpoint_id)
            if existing is not None:
                current = self._value(existing)
                if current.checkpoint != checkpoint:
                    raise ValueError("PROVIDER_RECOVERY_CHECKPOINT_IDENTITY_CONFLICT")
                if current.provider_ref != provider_ref or current.model_ref != model_ref:
                    raise ValueError("PROVIDER_RECOVERY_CHECKPOINT_ORIGIN_IMMUTABLE")
                return current
            open_rows = list(session.scalars(select(ProviderRecoveryCheckpointRow).where(ProviderRecoveryCheckpointRow.work_item_id == checkpoint.work_item_id, ProviderRecoveryCheckpointRow.closed_at.is_(None))))
            for row in open_rows:
                if row.mission_id != checkpoint.mission_id or row.test_run_id != checkpoint.test_run_id or row.stage_instance_id != checkpoint.stage_instance_id:
                    raise ValueError("PROVIDER_RECOVERY_WORK_ITEM_IDENTITY_CONFLICT")
                row.closed_at = timestamp
                row.close_reason = "SUPERSEDED_BY_NEWER_CHECKPOINT"
                row.updated_at = timestamp
            row = ProviderRecoveryCheckpointRow(
                checkpoint_id=checkpoint.checkpoint_id,
                mission_id=checkpoint.mission_id,
                test_run_id=checkpoint.test_run_id,
                stage_instance_id=checkpoint.stage_instance_id,
                work_item_id=checkpoint.work_item_id,
                attempt_id=checkpoint.attempt_id,
                input_snapshot_ref=checkpoint.input_snapshot_ref,
                cursor=checkpoint.cursor,
                side_effect_state=checkpoint.side_effect_state.value,
                completed_effect_refs=list(checkpoint.completed_effect_refs),
                provider_ref=provider_ref,
                model_ref=model_ref,
                created_at=timestamp,
                updated_at=timestamp,
                closed_at=None,
                close_reason=None,
            )
            session.add(row)
            return self._value(row)

    def get(self, checkpoint_id: str) -> Optional[StoredRecoveryCheckpoint]:
        with self.store.session() as session:
            row = session.get(ProviderRecoveryCheckpointRow, checkpoint_id)
            return self._value(row) if row is not None else None

    def latest_open_for_work_item(self, work_item_id: str) -> Optional[StoredRecoveryCheckpoint]:
        with self.store.session() as session:
            row = session.scalar(select(ProviderRecoveryCheckpointRow).where(ProviderRecoveryCheckpointRow.work_item_id == work_item_id, ProviderRecoveryCheckpointRow.closed_at.is_(None)).order_by(ProviderRecoveryCheckpointRow.updated_at.desc(), ProviderRecoveryCheckpointRow.checkpoint_id.desc()).limit(1))
            return self._value(row) if row is not None else None

    def list_open(self, *, test_run_id: Optional[str] = None) -> List[StoredRecoveryCheckpoint]:
        with self.store.session() as session:
            statement = select(ProviderRecoveryCheckpointRow).where(ProviderRecoveryCheckpointRow.closed_at.is_(None))
            if test_run_id is not None:
                statement = statement.where(ProviderRecoveryCheckpointRow.test_run_id == test_run_id)
            statement = statement.order_by(ProviderRecoveryCheckpointRow.updated_at, ProviderRecoveryCheckpointRow.checkpoint_id)
            return [self._value(row) for row in session.scalars(statement)]

    def close(self, checkpoint_id: str, *, reason: str = "WORK_ITEM_COMPLETED", now: Optional[int] = None) -> StoredRecoveryCheckpoint:
        if not str(reason or "").strip():
            raise ValueError("PROVIDER_RECOVERY_CLOSE_REASON_REQUIRED")
        timestamp = int(now if now is not None else time.time())
        with self.store.session() as session:
            row = session.get(ProviderRecoveryCheckpointRow, checkpoint_id)
            if row is None:
                raise ValueError("PROVIDER_RECOVERY_CHECKPOINT_NOT_FOUND")
            if row.closed_at is None:
                row.closed_at = timestamp
                row.updated_at = timestamp
                row.close_reason = str(reason).strip()
            elif row.close_reason != str(reason).strip():
                raise ValueError("PROVIDER_RECOVERY_CHECKPOINT_CLOSE_IMMUTABLE")
            return self._value(row)

    @staticmethod
    def _value(row: ProviderRecoveryCheckpointRow) -> StoredRecoveryCheckpoint:
        checkpoint = RecoveryCheckpoint(
            checkpoint_id=row.checkpoint_id,
            mission_id=row.mission_id,
            test_run_id=row.test_run_id,
            stage_instance_id=row.stage_instance_id,
            work_item_id=row.work_item_id,
            attempt_id=row.attempt_id,
            input_snapshot_ref=row.input_snapshot_ref,
            cursor=row.cursor,
            side_effect_state=SideEffectState(row.side_effect_state),
            completed_effect_refs=tuple(row.completed_effect_refs or ()),
        )
        return StoredRecoveryCheckpoint(checkpoint=checkpoint, provider_ref=row.provider_ref, model_ref=row.model_ref, created_at=int(row.created_at), updated_at=int(row.updated_at), closed_at=int(row.closed_at) if row.closed_at is not None else None, close_reason=row.close_reason)
