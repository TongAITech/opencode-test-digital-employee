"""production batch requirement delivery

Revision ID: 0007_req_delivery
Revises: 0006_lease_recovery
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_req_delivery"
down_revision = "0006_lease_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rc8_production_batch",
        sa.Column("production_batch_id", sa.String(length=160), primary_key=True),
        sa.Column("production_date", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_rc8_production_batch_production_date", "rc8_production_batch", ["production_date"])

    op.create_table(
        "rc8_requirement",
        sa.Column("requirement_id", sa.String(length=200), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )

    op.create_table(
        "rc8_requirement_delivery",
        sa.Column("delivery_id", sa.String(length=200), primary_key=True),
        sa.Column("production_batch_id", sa.String(length=160), nullable=False),
        sa.Column("requirement_id", sa.String(length=200), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("continuation_of_delivery_id", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("production_batch_id", "requirement_id", name="uq_rc8_requirement_delivery_batch_requirement"),
    )
    op.create_index("ix_rc8_requirement_delivery_production_batch_id", "rc8_requirement_delivery", ["production_batch_id"])
    op.create_index("ix_rc8_requirement_delivery_requirement_id", "rc8_requirement_delivery", ["requirement_id"])

    op.create_table(
        "rc8_requirement_delivery_scope",
        sa.Column("scope_id", sa.String(length=220), primary_key=True),
        sa.Column("delivery_id", sa.String(length=200), nullable=False),
        sa.Column("scope_identity", sa.String(length=64), nullable=False),
        sa.Column("system_id", sa.String(length=240), nullable=False),
        sa.Column("system_version", sa.String(length=240), nullable=False),
        sa.Column("application_id", sa.String(length=240), nullable=True),
        sa.Column("sst_id", sa.String(length=240), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("scope_identity", name="uq_rc8_requirement_delivery_scope_identity"),
    )
    op.create_index("ix_rc8_requirement_delivery_scope_delivery_id", "rc8_requirement_delivery_scope", ["delivery_id"])


def downgrade() -> None:
    op.drop_index("ix_rc8_requirement_delivery_scope_delivery_id", table_name="rc8_requirement_delivery_scope")
    op.drop_table("rc8_requirement_delivery_scope")
    op.drop_index("ix_rc8_requirement_delivery_requirement_id", table_name="rc8_requirement_delivery")
    op.drop_index("ix_rc8_requirement_delivery_production_batch_id", table_name="rc8_requirement_delivery")
    op.drop_table("rc8_requirement_delivery")
    op.drop_table("rc8_requirement")
    op.drop_index("ix_rc8_production_batch_production_date", table_name="rc8_production_batch")
    op.drop_table("rc8_production_batch")
