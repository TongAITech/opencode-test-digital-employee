"""artifact metadata

Revision ID: 0003_artifact_metadata
Revises: 0002_governance_projection_semantics
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_artifact_metadata"
down_revision = "0002_governance_projection_semantics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rc8_artifact_metadata",
        sa.Column("artifact_id", sa.String(length=200), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("work_item_id", sa.String(length=200), nullable=False),
        sa.Column("node_id", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column("producer_kind", sa.String(length=64), nullable=False),
        sa.Column("producer_ref", sa.String(length=240), nullable=False),
        sa.Column("file_name", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("availability", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=200), nullable=True),
        sa.Column("attempt_id", sa.String(length=200), nullable=True),
        sa.Column("step_id", sa.String(length=200), nullable=True),
        sa.Column("refs", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_rc8_artifact_metadata_test_run_id", "rc8_artifact_metadata", ["test_run_id"])
    op.create_index("ix_rc8_artifact_metadata_work_item_id", "rc8_artifact_metadata", ["work_item_id"])


def downgrade() -> None:
    op.drop_index("ix_rc8_artifact_metadata_work_item_id", table_name="rc8_artifact_metadata")
    op.drop_index("ix_rc8_artifact_metadata_test_run_id", table_name="rc8_artifact_metadata")
    op.drop_table("rc8_artifact_metadata")
