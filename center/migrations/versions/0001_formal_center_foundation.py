"""formal Center foundation

Revision ID: 0001_formal_center_foundation
Revises:
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_formal_center_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rc8_test_run",
        sa.Column("test_run_id", sa.String(length=160), primary_key=True),
        sa.Column("production_batch_id", sa.String(length=160), nullable=True),
        sa.Column("status_scope", sa.String(length=32), nullable=False),
        sa.Column("current_state", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "rc8_mission_stage",
        sa.Column("stage_instance_id", sa.String(length=200), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("stage_type", sa.String(length=80), nullable=False),
        sa.Column("scope_ref", sa.String(length=240), nullable=False),
        sa.Column("scope_version", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("evaluator_ref", sa.String(length=240), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_rc8_mission_stage_test_run_id", "rc8_mission_stage", ["test_run_id"])
    op.create_table(
        "rc8_attempt",
        sa.Column("attempt_id", sa.String(length=200), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("stage_instance_id", sa.String(length=200), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.BigInteger(), nullable=False),
        sa.Column("ended_at", sa.BigInteger(), nullable=True),
        sa.Column("source_snapshot_ref", sa.String(length=240), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_rc8_attempt_test_run_id", "rc8_attempt", ["test_run_id"])
    op.create_index("ix_rc8_attempt_stage_instance_id", "rc8_attempt", ["stage_instance_id"])
    op.create_table(
        "rc8_gap",
        sa.Column("gap_id", sa.String(length=200), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("source_stage_instance_id", sa.String(length=200), nullable=False),
        sa.Column("source_attempt_id", sa.String(length=200), nullable=True),
        sa.Column("gap_type", sa.String(length=100), nullable=False),
        sa.Column("owner_stage", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("resolved_at", sa.BigInteger(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_rc8_gap_test_run_id", "rc8_gap", ["test_run_id"])
    op.create_table(
        "rc8_coverage_observation",
        sa.Column("observation_id", sa.String(length=200), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("stage_instance_id", sa.String(length=200), nullable=False),
        sa.Column("attempt_id", sa.String(length=200), nullable=False),
        sa.Column("dimension", sa.String(length=100), nullable=False),
        sa.Column("subject_ref", sa.String(length=300), nullable=False),
        sa.Column("covered", sa.BigInteger(), nullable=False),
        sa.Column("total", sa.BigInteger(), nullable=False),
        sa.Column("source_snapshot_ref", sa.String(length=240), nullable=False),
        sa.Column("source_tool", sa.String(length=100), nullable=False),
        sa.Column("observed_at", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_rc8_coverage_observation_test_run_id", "rc8_coverage_observation", ["test_run_id"])
    op.create_index("ix_rc8_coverage_observation_stage_instance_id", "rc8_coverage_observation", ["stage_instance_id"])
    op.create_index("ix_rc8_coverage_observation_attempt_id", "rc8_coverage_observation", ["attempt_id"])
    op.create_table(
        "rc8_projection_checkpoint",
        sa.Column("projector_id", sa.String(length=160), primary_key=True),
        sa.Column("last_event_id", sa.String(length=200), nullable=True),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("rc8_projection_checkpoint")
    op.drop_index("ix_rc8_coverage_observation_attempt_id", table_name="rc8_coverage_observation")
    op.drop_index("ix_rc8_coverage_observation_stage_instance_id", table_name="rc8_coverage_observation")
    op.drop_index("ix_rc8_coverage_observation_test_run_id", table_name="rc8_coverage_observation")
    op.drop_table("rc8_coverage_observation")
    op.drop_index("ix_rc8_gap_test_run_id", table_name="rc8_gap")
    op.drop_table("rc8_gap")
    op.drop_index("ix_rc8_attempt_stage_instance_id", table_name="rc8_attempt")
    op.drop_index("ix_rc8_attempt_test_run_id", table_name="rc8_attempt")
    op.drop_table("rc8_attempt")
    op.drop_index("ix_rc8_mission_stage_test_run_id", table_name="rc8_mission_stage")
    op.drop_table("rc8_mission_stage")
    op.drop_table("rc8_test_run")
