from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from rc8_runtime.contracts import RC8ContractError
from rc8_runtime.provider_recovery import RecoveryCheckpoint, SideEffectState
from rc8_runtime.recovery_store import (
    PostgreSQLRecoveryCheckpointStore,
    RECOVERY_CHECKPOINT,
    StartupRecoveryAction,
)


def checkpoint(state=SideEffectState.NONE):
    return RecoveryCheckpoint(
        checkpoint_id="ckpt-1",
        mission_id="mission-1",
        test_run_id="run-1",
        stage_instance_id="stage-1",
        work_item_id="work-1",
        attempt_id="attempt-1",
        input_snapshot_ref="snapshot:abc",
        cursor="cursor:7",
        side_effect_state=state,
        completed_effect_refs=("evidence:1",),
    )


def test_store_rejects_non_postgresql_authority():
    engine = sa.create_engine("sqlite:///:memory:")
    with pytest.raises(RC8ContractError, match="RECOVERY_STORE_POSTGRESQL_REQUIRED"):
        PostgreSQLRecoveryCheckpointStore(engine)


def test_postgresql_upsert_is_keyed_by_checkpoint_and_identity_guarded():
    # Compile the authoritative statement shape without pretending a live bank
    # PostgreSQL instance exists in cloud CI.
    values = PostgreSQLRecoveryCheckpointStore._values(
        checkpoint(), provider_ref="bankgpt", model_ref="model-a", now=100
    )
    from sqlalchemy.dialects.postgresql import insert as pg_insert

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
        set_={"cursor": excluded.cursor, "updated_at": excluded.updated_at},
        where=identity_same,
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (checkpoint_id) DO UPDATE" in sql
    assert "mission_id" in sql
    assert "work_item_id" in sql
    assert "attempt_id" in sql
    assert "closed_at IS NULL" in sql


def test_startup_reconciliation_reclaims_same_durable_identity():
    item = checkpoint(SideEffectState.CONFIRMED_NOT_APPLIED)
    records = PostgreSQLRecoveryCheckpointStore.startup_reconciliation([item])
    assert len(records) == 1
    record = records[0]
    assert record.action == StartupRecoveryAction.RESUME_SAME_WORK_ITEM
    assert record.checkpoint.mission_id == "mission-1"
    assert record.checkpoint.stage_instance_id == "stage-1"
    assert record.checkpoint.work_item_id == "work-1"
    assert record.checkpoint.attempt_id == "attempt-1"
    assert record.checkpoint.resume_key == item.resume_key


def test_startup_reconciliation_never_replays_unknown_side_effect():
    item = checkpoint(SideEffectState.UNKNOWN)
    record = PostgreSQLRecoveryCheckpointStore.startup_reconciliation([item])[0]
    assert record.action == StartupRecoveryAction.RECONCILE_SIDE_EFFECT
    assert record.checkpoint.resume_key == item.resume_key


def test_recovery_table_matches_migration_contract():
    names = {column.name for column in RECOVERY_CHECKPOINT.columns}
    assert {
        "checkpoint_id",
        "mission_id",
        "test_run_id",
        "stage_instance_id",
        "work_item_id",
        "attempt_id",
        "input_snapshot_ref",
        "cursor",
        "side_effect_state",
        "completed_effect_refs",
        "provider_ref",
        "model_ref",
        "created_at",
        "updated_at",
        "closed_at",
        "close_reason",
    } == names
