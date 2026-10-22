"""test rounds within one production date

Revision ID: 0008_test_rounds
Revises: 0007_req_delivery
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0008_test_rounds"
down_revision = "0007_req_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rc8_test_round",
        sa.Column("test_round_id", sa.String(length=200), primary_key=True),
        sa.Column("production_batch_id", sa.String(length=160), nullable=False),
        sa.Column("round_no", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.BigInteger(), nullable=True),
        sa.Column("completed_at", sa.BigInteger(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("production_batch_id", "round_no", name="uq_rc8_test_round_batch_no"),
    )
    op.create_index("ix_rc8_test_round_production_batch_id", "rc8_test_round", ["production_batch_id"])

    op.create_table(
        "rc8_test_round_delivery",
        sa.Column("round_delivery_id", sa.String(length=220), primary_key=True),
        sa.Column("test_round_id", sa.String(length=200), nullable=False),
        sa.Column("delivery_id", sa.String(length=200), nullable=False),
        sa.Column("included_at", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("test_round_id", "delivery_id", name="uq_rc8_test_round_delivery_pair"),
    )
    op.create_index("ix_rc8_test_round_delivery_test_round_id", "rc8_test_round_delivery", ["test_round_id"])
    op.create_index("ix_rc8_test_round_delivery_delivery_id", "rc8_test_round_delivery", ["delivery_id"])


def downgrade() -> None:
    op.drop_index("ix_rc8_test_round_delivery_delivery_id", table_name="rc8_test_round_delivery")
    op.drop_index("ix_rc8_test_round_delivery_test_round_id", table_name="rc8_test_round_delivery")
    op.drop_table("rc8_test_round_delivery")
    op.drop_index("ix_rc8_test_round_production_batch_id", table_name="rc8_test_round")
    op.drop_table("rc8_test_round")
