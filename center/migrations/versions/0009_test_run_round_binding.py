"""bind test runs to test rounds

Revision ID: 0009_run_round
Revises: 0008_test_rounds
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009_run_round"
down_revision = "0008_test_rounds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rc8_test_run", sa.Column("test_round_id", sa.String(length=200), nullable=True))
    op.create_index(
        "ux_rc8_test_run_test_round_id",
        "rc8_test_run",
        ["test_round_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_rc8_test_run_test_round_id", table_name="rc8_test_run")
    op.drop_column("rc8_test_run", "test_round_id")
