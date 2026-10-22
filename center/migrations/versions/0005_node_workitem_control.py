"""node capability work-item control

Revision ID: 0005_node_workitem
Revises: 0004_legacy_scope_ref
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_node_workitem"
down_revision = "0004_legacy_scope_ref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rc8_node",
        sa.Column("node_id", sa.String(length=200), primary_key=True),
        sa.Column("operator_ref", sa.String(length=240), nullable=False),
        sa.Column("os_family", sa.String(length=32), nullable=False),
        sa.Column("architecture", sa.String(length=64), nullable=False),
        sa.Column("shell", sa.String(length=64), nullable=False),
        sa.Column("registered_at", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("first_registered_at", sa.BigInteger(), nullable=False),
        sa.Column("last_heartbeat_at", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "rc8_node_capability",
        sa.Column("node_id", sa.String(length=200), primary_key=True),
        sa.Column("capability_id", sa.String(length=200), primary_key=True),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("probe_ref", sa.String(length=400), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("verified_at", sa.BigInteger(), nullable=True),
    )
    op.create_table(
        "rc8_work_item",
        sa.Column("work_item_id", sa.String(length=200), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("stage", sa.String(length=100), nullable=False),
        sa.Column("scope_refs", sa.JSON(), nullable=False),
        sa.Column("required_capabilities", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("lease_id", sa.String(length=200), nullable=True),
        sa.Column("lease_owner_node_id", sa.String(length=200), nullable=True),
        sa.Column("lease_expires_at", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_rc8_work_item_test_run_id", "rc8_work_item", ["test_run_id"])


def downgrade() -> None:
    op.drop_index("ix_rc8_work_item_test_run_id", table_name="rc8_work_item")
    op.drop_table("rc8_work_item")
    op.drop_table("rc8_node_capability")
    op.drop_table("rc8_node")
