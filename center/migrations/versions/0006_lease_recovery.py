"""lease recovery incidents

Revision ID: 0006_lease_recovery
Revises: 0005_node_workitem
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_lease_recovery"
down_revision = "0005_node_workitem"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rc8_recovery_incident",
        sa.Column("incident_id", sa.String(length=240), primary_key=True),
        sa.Column("work_item_id", sa.String(length=200), nullable=False),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("node_id", sa.String(length=200), nullable=True),
        sa.Column("lease_id", sa.String(length=200), nullable=True),
        sa.Column("work_item_state", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("runtime_event_count", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("opened_at", sa.BigInteger(), nullable=False),
        sa.Column("resolution", sa.String(length=80), nullable=True),
        sa.Column("decision_ref", sa.String(length=300), nullable=True),
        sa.Column("evidence_ref", sa.String(length=300), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_rc8_recovery_incident_work_item_id", "rc8_recovery_incident", ["work_item_id"])
    op.create_index("ix_rc8_recovery_incident_test_run_id", "rc8_recovery_incident", ["test_run_id"])


def downgrade() -> None:
    op.drop_index("ix_rc8_recovery_incident_test_run_id", table_name="rc8_recovery_incident")
    op.drop_index("ix_rc8_recovery_incident_work_item_id", table_name="rc8_recovery_incident")
    op.drop_table("rc8_recovery_incident")
