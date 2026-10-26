"""Add durable N5 PreparedAttempt and N6 executable readiness state.

Revision ID: 0014_n5_n6_execution_state
Revises: 0013_provider_recovery_ckpt
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0014_n5_n6_execution_state"
down_revision = "0013_provider_recovery_ckpt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rc8_prepared_attempt",
        sa.Column("prepared_attempt_id", sa.String(length=240), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("mission_node_id", sa.String(length=300), nullable=False),
        sa.Column("case_id", sa.String(length=200), nullable=False),
        sa.Column("attempt_id", sa.String(length=200), nullable=False),
        sa.Column("reality_snapshot_id", sa.String(length=300), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("data_refs", sa.JSON(), nullable=False),
        sa.Column("verification_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("reservation_ref", sa.String(length=300), nullable=True),
        sa.Column("reservation_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("data_freshness_ref", sa.String(length=300), nullable=True),
        sa.Column("auth_session_ref", sa.String(length=300), nullable=True),
        sa.Column("auth_binding_mode", sa.String(length=64), nullable=True),
        sa.Column("auth_acquired_at", sa.BigInteger(), nullable=True),
        sa.Column("auth_expires_at", sa.BigInteger(), nullable=True),
        sa.Column("freshness_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("environment_ref", sa.String(length=300), nullable=True),
        sa.Column("route_ref", sa.String(length=500), nullable=True),
        sa.Column("binding_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("released_at", sa.BigInteger(), nullable=True),
        sa.Column("release_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("quarantine_reason", sa.String(length=500), nullable=True),
    )
    op.create_index("ix_rc8_prepared_attempt_test_run", "rc8_prepared_attempt", ["test_run_id"])
    op.create_index("ix_rc8_prepared_attempt_mission_node", "rc8_prepared_attempt", ["mission_node_id"])
    op.create_index("ix_rc8_prepared_attempt_case", "rc8_prepared_attempt", ["case_id"])
    op.create_index("ix_rc8_prepared_attempt_attempt", "rc8_prepared_attempt", ["attempt_id"])
    op.create_index("ix_rc8_prepared_attempt_state", "rc8_prepared_attempt", ["state"])

    op.create_table(
        "rc8_executable_spec",
        sa.Column("executable_spec_id", sa.String(length=240), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("mission_node_id", sa.String(length=300), nullable=False),
        sa.Column("case_id", sa.String(length=200), nullable=False),
        sa.Column("attempt_id", sa.String(length=200), nullable=False),
        sa.Column("prepared_attempt_id", sa.String(length=240), nullable=False),
        sa.Column("frozen_case_ref", sa.String(length=300), nullable=False),
        sa.Column("driver_ref", sa.String(length=300), nullable=False),
        sa.Column("script_artifact_ref", sa.String(length=300), nullable=False),
        sa.Column("fixture_binding_refs", sa.JSON(), nullable=False),
        sa.Column("assertion_refs", sa.JSON(), nullable=False),
        sa.Column("evidence_collector_refs", sa.JSON(), nullable=False),
        sa.Column("build_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("semantic_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("invalidation_reason", sa.String(length=500), nullable=True),
        sa.Column("invalidation_evidence_refs", sa.JSON(), nullable=False),
    )
    op.create_index("ix_rc8_executable_spec_test_run", "rc8_executable_spec", ["test_run_id"])
    op.create_index("ix_rc8_executable_spec_mission_node", "rc8_executable_spec", ["mission_node_id"])
    op.create_index("ix_rc8_executable_spec_case", "rc8_executable_spec", ["case_id"])
    op.create_index("ix_rc8_executable_spec_attempt", "rc8_executable_spec", ["attempt_id"])
    op.create_index("ix_rc8_executable_spec_prepared", "rc8_executable_spec", ["prepared_attempt_id"])
    op.create_index("ix_rc8_executable_spec_state", "rc8_executable_spec", ["state"])


def downgrade() -> None:
    op.drop_index("ix_rc8_executable_spec_state", table_name="rc8_executable_spec")
    op.drop_index("ix_rc8_executable_spec_prepared", table_name="rc8_executable_spec")
    op.drop_index("ix_rc8_executable_spec_attempt", table_name="rc8_executable_spec")
    op.drop_index("ix_rc8_executable_spec_case", table_name="rc8_executable_spec")
    op.drop_index("ix_rc8_executable_spec_mission_node", table_name="rc8_executable_spec")
    op.drop_index("ix_rc8_executable_spec_test_run", table_name="rc8_executable_spec")
    op.drop_table("rc8_executable_spec")

    op.drop_index("ix_rc8_prepared_attempt_state", table_name="rc8_prepared_attempt")
    op.drop_index("ix_rc8_prepared_attempt_attempt", table_name="rc8_prepared_attempt")
    op.drop_index("ix_rc8_prepared_attempt_case", table_name="rc8_prepared_attempt")
    op.drop_index("ix_rc8_prepared_attempt_mission_node", table_name="rc8_prepared_attempt")
    op.drop_index("ix_rc8_prepared_attempt_test_run", table_name="rc8_prepared_attempt")
    op.drop_table("rc8_prepared_attempt")
