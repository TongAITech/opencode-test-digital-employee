"""PostgreSQL authority for RC8 durable provider recovery checkpoints.

The store is deliberately non-LLM.  It persists the exact Mission/Stage/WorkItem/
Attempt identity before provider calls and exposes deterministic startup
reconciliation after process restart.  Redis is not an authority for these rows.

Python 3.8 compatible.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .contracts import RC8ContractError
from .provider_recovery import RecoveryCheckpoint, SideEffectState


_METADATA = sa.MetaData()
RECOVERY_CHECKPOINT = sa.Table(
    "rc8_provider_recovery_checkpoint",
    _METADATA,
    sa.Column("checkpoint_id", sa.String(240), primary_key=True),
    sa.Column("mission_id", sa.String(200), nullable=False),
    sa.Column("test_run_id", sa.String(160), nullable=False),
    sa.Column("stage_instance_id", sa.String(200), nullable=False),
    sa.Column("work_item_id", sa.String(200), nullable=False),
    sa.Column("attempt_id", sa.String(200), nullable=False),
    sa.Column("input_snapshot_ref", sa.String(300), nullable=False),
    sa.Column("cursor", sa.String(1000), nullable=False),
    sa.Column("side_effect_state", sa.String(64), nullable=False),
    sa.Column("completed_effect_refs", sa.JSON(), nullable=False),
    sa.Column("provider_ref", sa.String(240), nullable=True),
    sa.Column("model_ref", sa.String(240), nullable=True),
    sa.Column("created_at", sa.BigInteger(), nullable=False),
    sa.Column("updated_at", sa.BigInteger(), nullable=False),
    sa.Column("closed_at", sa.BigInteger(), nullable=True),
    sa.Column("close_reason", sa.String(120), nullable=True),
)


class StartupRecoveryAction(str, Enum):
    RESUME_SAME_WORK_ITEM = "RESUME_SAME_WORK_ITEM"
    RECONCILE_SIDE_EFFECT = "RECONCILE_SIDE_EFFECT"


@dataclass(frozen=True)
class StartupRecoveryRecord:
    checkpoint: RecoveryCheckpoint
    action: StartupRecoveryAction
    reason: str


class PostgreSQLRecoveryCheckpointStore:
    """Transactional PostgreSQL repository for RecoveryCheckpoint.

    ``save_before_provider_call`` is an idempotent UPSERT keyed by checkpoint_id.
    Durable identity columns are immutable across retries: a conflicting write
    that attempts to reuse a checkpoint for another Mission/Stage/WorkItem/
    Attempt fails closed instead of silently forking execution identity.
    """

    def __init__(self, engine: sa.engine.Engine) -> None:
        if engine is None:
            raise RC8ContractError("RECOVERY_STORE_ENGINE_REQUIRED")
        if engine.dialect.name != "postgresql":
            raise RC8ContractError("RECOVERY_STORE_POSTGRESQL_REQUIRED")
        self.engine = engine

    def save_before_provider_call(
        self,
        checkpoint: RecoveryCheckpoint,
        *,
        provider_ref: Optional[str],
        model_ref: Optional[str],
        now: int,
    ) -> None:
        if not isinstance(checkpoint, RecoveryCheckpoint):
            raise RC8ContractError("RECOVERY_CHECKPOINT_REQUIRED")
        if not isinstance(now, int) or now < 0:
            raise RC8ContractError("RECOVERY_STORE_NOW_INVALID")

        values = self._values(checkpoint, provider_ref=provider_ref, model_ref=model_ref, now=now)
        statement = pg_insert(RECOVERY_CHECKPOINT).values(**values)
        excluded = statement.excluded
        identity_same = sa.and_(
            RECOVERY_CHECKPOINT.c.mission_id == excluded.mission_id,
            RECOVERY_CHECKPOINT.c.test_run_id == excluded.test_run_id,
            RECOVERY_CHECKPOINT.c.stage_instance_id == excluded.stage_instance_id,
            RECOVERY_CHECKPOINT.c.work_item_id == excluded.work_item_id,
            RECOVERY_CHECKPOINT.c.attempt_id == excluded.attempt_id,
            RECOVERY_CHECKPOINT.c.input_snapshot_ref == excluded.input_snapshot_ref,
            RECOVERY_CHECKPOINT.c.closed_at.is_(None),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[RECOVERY_CHECKPOINT.c.checkpoint_id],
            set_={
                "cursor": excluded.cursor,
                "side_effect_state": excluded.side_effect_state,
                "completed_effect_refs": excluded.completed_effect_refs,
                "provider_ref": excluded.provider_ref,
                "model_ref": excluded.model_ref,
                "updated_at": excluded.updated_at,
            },
            where=identity_same,
        )
        with self.engine.begin() as connection:
            result = connection.execute(statement)
            if result.rowcount != 1:
                raise RC8ContractError("RECOVERY_CHECKPOINT_IDENTITY_CONFLICT")

    def load_open(self) -> List[RecoveryCheckpoint]:
        statement = (
            sa.select(RECOVERY_CHECKPOINT)
            .where(RECOVERY_CHECKPOINT.c.closed_at.is_(None))
            .order_by(RECOVERY_CHECKPOINT.c.updated_at.asc(), RECOVERY_CHECKPOINT.c.checkpoint_id.asc())
        )
        with self.engine.begin() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._checkpoint(row) for row in rows]

    def mark_side_effect_reconciled(
        self,
        checkpoint_id: str,
        *,
        applied: bool,
        completed_effect_refs: Iterable[str],
        now: int,
    ) -> None:
        refs = tuple(str(item).strip() for item in completed_effect_refs if str(item).strip())
        state = SideEffectState.CONFIRMED_APPLIED if applied else SideEffectState.CONFIRMED_NOT_APPLIED
        statement = (
            sa.update(RECOVERY_CHECKPOINT)
            .where(
                RECOVERY_CHECKPOINT.c.checkpoint_id == checkpoint_id,
                RECOVERY_CHECKPOINT.c.closed_at.is_(None),
                RECOVERY_CHECKPOINT.c.side_effect_state == SideEffectState.UNKNOWN.value,
            )
            .values(
                side_effect_state=state.value,
                completed_effect_refs=list(refs),
                updated_at=now,
            )
        )
        with self.engine.begin() as connection:
            result = connection.execute(statement)
            if result.rowcount != 1:
                raise RC8ContractError("SIDE_EFFECT_RECONCILIATION_PRECONDITION_FAILED")

    def close(self, checkpoint_id: str, *, reason: str, now: int) -> None:
        if not reason or not reason.strip():
            raise RC8ContractError("RECOVERY_CLOSE_REASON_REQUIRED")
        statement = (
            sa.update(RECOVERY_CHECKPOINT)
            .where(
                RECOVERY_CHECKPOINT.c.checkpoint_id == checkpoint_id,
                RECOVERY_CHECKPOINT.c.closed_at.is_(None),
            )
            .values(closed_at=now, close_reason=reason.strip(), updated_at=now)
        )
        with self.engine.begin() as connection:
            result = connection.execute(statement)
            if result.rowcount != 1:
                raise RC8ContractError("RECOVERY_CHECKPOINT_NOT_OPEN")

    @staticmethod
    def startup_reconciliation(checkpoints: Iterable[RecoveryCheckpoint]) -> List[StartupRecoveryRecord]:
        """Build deterministic restart work without consulting an LLM."""
        records = []
        for checkpoint in checkpoints:
            if checkpoint.side_effect_state == SideEffectState.UNKNOWN:
                records.append(
                    StartupRecoveryRecord(
                        checkpoint=checkpoint,
                        action=StartupRecoveryAction.RECONCILE_SIDE_EFFECT,
                        reason="unknown external side effect must be reconciled before replay",
                    )
                )
            else:
                records.append(
                    StartupRecoveryRecord(
                        checkpoint=checkpoint,
                        action=StartupRecoveryAction.RESUME_SAME_WORK_ITEM,
                        reason="durable checkpoint is safe to reclaim with original identity",
                    )
                )
        return records

    @staticmethod
    def _values(checkpoint, *, provider_ref, model_ref, now):
        return {
            "checkpoint_id": checkpoint.checkpoint_id,
            "mission_id": checkpoint.mission_id,
            "test_run_id": checkpoint.test_run_id,
            "stage_instance_id": checkpoint.stage_instance_id,
            "work_item_id": checkpoint.work_item_id,
            "attempt_id": checkpoint.attempt_id,
            "input_snapshot_ref": checkpoint.input_snapshot_ref,
            "cursor": checkpoint.cursor,
            "side_effect_state": checkpoint.side_effect_state.value,
            "completed_effect_refs": list(checkpoint.completed_effect_refs),
            "provider_ref": provider_ref,
            "model_ref": model_ref,
            "created_at": now,
            "updated_at": now,
            "closed_at": None,
            "close_reason": None,
        }

    @staticmethod
    def _checkpoint(row) -> RecoveryCheckpoint:
        return RecoveryCheckpoint(
            checkpoint_id=row["checkpoint_id"],
            mission_id=row["mission_id"],
            test_run_id=row["test_run_id"],
            stage_instance_id=row["stage_instance_id"],
            work_item_id=row["work_item_id"],
            attempt_id=row["attempt_id"],
            input_snapshot_ref=row["input_snapshot_ref"],
            cursor=row["cursor"],
            side_effect_state=SideEffectState(row["side_effect_state"]),
            completed_effect_refs=tuple(row["completed_effect_refs"] or ()),
        )
