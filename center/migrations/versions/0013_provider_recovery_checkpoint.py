"""provider/model durable recovery checkpoint

Revision ID: 0013_provider_recovery_ckpt
Revises: 0012_traceability_graph
Create Date: 2026-10-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0013_provider_recovery_ckpt"
down_revision = "0012_traceability_graph"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rc8_provider_recovery_checkpoint",
        sa.Column("checkpoint_id", sa.String(length=240), primary_key=True),
        sa.Column("mission_id", sa.String(length=200), nullable=False),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("stage_instance_id", sa.String(length=200), nullable=False),
        sa.Column("work_item_id", sa.String(length=200), nullable=False),
        sa.Column("attempt_id", sa.String(length=200), nullable=False),
        sa.Column("input_snapshot_ref", sa.String(length=300), nullable=False),
        sa.Column("cursor", sa.String(length=1000), nullable=False),
        sa.Column("side_effect_state", sa.String(length=64), nullable=False),
        sa.Column("completed_effect_refs", sa.JSON(), nullable=False),
        sa.Column("provider_ref", sa.String(length=240), nullable=True),
        sa.Column("model_ref", sa.String(length=240), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("closed_at", sa.BigInteger(), nullable=True),
        sa.Column("close_reason", sa.String(length=120), nullable=True),
    )
    op.create_index("ix_rc8_provider_ckpt_mission", "rc8_provider_recovery_checkpoint", ["mission_id"])
    op.create_index("ix_rc8_provider_ckpt_test_run", "rc8_provider_recovery_checkpoint", ["test_run_id"])
    op.create_index("ix_rc8_provider_ckpt_stage", "rc8_provider_recovery_checkpoint", ["stage_instance_id"])
    op.create_index("ix_rc8_provider_ckpt_work_item", "rc8_provider_recovery_checkpoint", ["work_item_id"])
    op.create_index("ix_rc8_provider_ckpt_attempt", "rc8_provider_recovery_checkpoint", ["attempt_id"])


def downgrade() -> None:
    op.drop_index("ix_rc8_provider_ckpt_attempt", table_name="rc8_provider_recovery_checkpoint")
    op.drop_index("ix_rc8_provider_ckpt_work_item", table_name="rc8_provider_recovery_checkpoint")
    op.drop_index("ix_rc8_provider_ckpt_stage", table_name="rc8_provider_recovery_checkpoint")
    op.drop_index("ix_rc8_provider_ckpt_test_run", table_name="rc8_provider_recovery_checkpoint")
    op.drop_index("ix_rc8_provider_ckpt_mission", table_name="rc8_provider_recovery_checkpoint")
    op.drop_table("rc8_provider_recovery_checkpoint")
