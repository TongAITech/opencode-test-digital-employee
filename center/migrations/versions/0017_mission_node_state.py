"""Persist Center-owned MissionNode current truth.

Revision ID: 0017_mission_node_state
Revises: 0016_n9_n7_result_auth
"""
from alembic import op
import sqlalchemy as sa


revision = "0017_mission_node_state"
down_revision = "0016_n9_n7_result_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rc8_mission_node",
        sa.Column("mission_node_id", sa.String(length=300), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("node_type", sa.String(length=100), nullable=False),
        sa.Column("scope_version", sa.String(length=300), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("stage_instance_ids", sa.JSON(), nullable=False),
        sa.Column("predecessor_node_ids", sa.JSON(), nullable=False),
        sa.Column("output_refs", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint(
            "test_run_id",
            "node_type",
            name="uq_rc8_mission_node_test_run_type",
        ),
    )
    op.create_index(
        "ix_rc8_mission_node_test_run_id",
        "rc8_mission_node",
        ["test_run_id"],
    )
    op.create_index(
        "ix_rc8_mission_node_node_type",
        "rc8_mission_node",
        ["node_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_rc8_mission_node_node_type", table_name="rc8_mission_node")
    op.drop_index("ix_rc8_mission_node_test_run_id", table_name="rc8_mission_node")
    op.drop_table("rc8_mission_node")
