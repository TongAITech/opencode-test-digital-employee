"""stage work item lineage

Revision ID: 0010_stage_workitem
Revises: 0009_run_round
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0010_stage_workitem"
down_revision = "0009_run_round"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rc8_stage_work_item_link",
        sa.Column("work_item_id", sa.String(length=200), primary_key=True),
        sa.Column("stage_instance_id", sa.String(length=200), nullable=False),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
    )
    op.create_index(
        "ix_rc8_stage_work_item_link_stage_instance_id",
        "rc8_stage_work_item_link",
        ["stage_instance_id"],
    )
    op.create_index(
        "ix_rc8_stage_work_item_link_test_run_id",
        "rc8_stage_work_item_link",
        ["test_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_rc8_stage_work_item_link_test_run_id", table_name="rc8_stage_work_item_link")
    op.drop_index("ix_rc8_stage_work_item_link_stage_instance_id", table_name="rc8_stage_work_item_link")
    op.drop_table("rc8_stage_work_item_link")
