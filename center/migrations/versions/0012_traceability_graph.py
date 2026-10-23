"""evidence-backed requirement runtime traceability graph

Revision ID: 0012_traceability_graph
Revises: 0011_req_scope_revision
Create Date: 2026-10-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0012_traceability_graph"
down_revision = "0011_req_scope_revision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rc8_code_source_snapshot",
        sa.Column("snapshot_id", sa.String(length=200), primary_key=True),
        sa.Column("identity", sa.String(length=64), nullable=False),
        sa.Column("repository_id", sa.String(length=240), nullable=False),
        sa.Column("repository_url", sa.String(length=1000), nullable=False),
        sa.Column("application_id", sa.String(length=240), nullable=True),
        sa.Column("base_commit_sha", sa.String(length=160), nullable=True),
        sa.Column("commit_sha", sa.String(length=160), nullable=False),
        sa.Column("subpath", sa.String(length=1000), nullable=True),
        sa.Column("test_round_id", sa.String(length=200), nullable=False),
        sa.Column("scope_revision_id", sa.String(length=200), nullable=False),
        sa.Column("system_id", sa.String(length=240), nullable=True),
        sa.Column("system_version", sa.String(length=240), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("identity", name="uq_rc8_code_source_snapshot_identity"),
    )
    op.create_index("ix_rc8_code_source_snapshot_identity", "rc8_code_source_snapshot", ["identity"])
    op.create_index("ix_rc8_code_source_snapshot_test_round_id", "rc8_code_source_snapshot", ["test_round_id"])
    op.create_index("ix_rc8_code_source_snapshot_scope_revision_id", "rc8_code_source_snapshot", ["scope_revision_id"])

    op.create_table(
        "rc8_traceability_graph",
        sa.Column("graph_id", sa.String(length=200), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("test_round_id", sa.String(length=200), nullable=False),
        sa.Column("scope_revision_id", sa.String(length=200), nullable=False),
        sa.Column("code_source_snapshot_id", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "test_run_id",
            "scope_revision_id",
            "code_source_snapshot_id",
            name="uq_rc8_trace_graph_frozen_scope",
        ),
    )
    op.create_index("ix_rc8_traceability_graph_test_run_id", "rc8_traceability_graph", ["test_run_id"])
    op.create_index("ix_rc8_traceability_graph_test_round_id", "rc8_traceability_graph", ["test_round_id"])
    op.create_index("ix_rc8_traceability_graph_scope_revision_id", "rc8_traceability_graph", ["scope_revision_id"])
    op.create_index("ix_rc8_traceability_graph_code_source_snapshot_id", "rc8_traceability_graph", ["code_source_snapshot_id"])

    op.create_table(
        "rc8_trace_node",
        sa.Column("node_id", sa.String(length=240), primary_key=True),
        sa.Column("graph_id", sa.String(length=200), nullable=False),
        sa.Column("node_type", sa.String(length=64), nullable=False),
        sa.Column("business_key", sa.String(length=1000), nullable=False),
        sa.Column("display_name", sa.String(length=1000), nullable=False),
        sa.Column("source_snapshot_id", sa.String(length=200), nullable=True),
        sa.Column("scope_revision_id", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("graph_id", "node_type", "business_key", name="uq_rc8_trace_node_business_key"),
    )
    op.create_index("ix_rc8_trace_node_graph_id", "rc8_trace_node", ["graph_id"])
    op.create_index("ix_rc8_trace_node_node_type", "rc8_trace_node", ["node_type"])

    op.create_table(
        "rc8_trace_edge",
        sa.Column("edge_id", sa.String(length=240), primary_key=True),
        sa.Column("graph_id", sa.String(length=200), nullable=False),
        sa.Column("from_node_id", sa.String(length=240), nullable=False),
        sa.Column("to_node_id", sa.String(length=240), nullable=False),
        sa.Column("relation_type", sa.String(length=80), nullable=False),
        sa.Column("verification_state", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_count", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "graph_id", "from_node_id", "to_node_id", "relation_type",
            name="uq_rc8_trace_edge_relation",
        ),
    )
    op.create_index("ix_rc8_trace_edge_graph_id", "rc8_trace_edge", ["graph_id"])
    op.create_index("ix_rc8_trace_edge_from_node_id", "rc8_trace_edge", ["from_node_id"])
    op.create_index("ix_rc8_trace_edge_to_node_id", "rc8_trace_edge", ["to_node_id"])
    op.create_index("ix_rc8_trace_edge_relation_type", "rc8_trace_edge", ["relation_type"])
    op.create_index("ix_rc8_trace_edge_verification_state", "rc8_trace_edge", ["verification_state"])

    op.create_table(
        "rc8_trace_evidence",
        sa.Column("evidence_id", sa.String(length=240), primary_key=True),
        sa.Column("graph_id", sa.String(length=200), nullable=False),
        sa.Column("edge_id", sa.String(length=240), nullable=False),
        sa.Column("evidence_type", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=1000), nullable=False),
        sa.Column("artifact_id", sa.String(length=240), nullable=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("stage_id", sa.String(length=240), nullable=True),
        sa.Column("work_item_id", sa.String(length=240), nullable=True),
        sa.Column("attempt_id", sa.String(length=240), nullable=True),
        sa.Column("code_source_snapshot_id", sa.String(length=200), nullable=False),
        sa.Column("captured_at", sa.BigInteger(), nullable=False),
        sa.Column("integrity_hash", sa.String(length=256), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_rc8_trace_evidence_graph_id", "rc8_trace_evidence", ["graph_id"])
    op.create_index("ix_rc8_trace_evidence_edge_id", "rc8_trace_evidence", ["edge_id"])
    op.create_index("ix_rc8_trace_evidence_evidence_type", "rc8_trace_evidence", ["evidence_type"])
    op.create_index("ix_rc8_trace_evidence_test_run_id", "rc8_trace_evidence", ["test_run_id"])
    op.create_index("ix_rc8_trace_evidence_code_source_snapshot_id", "rc8_trace_evidence", ["code_source_snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_rc8_trace_evidence_code_source_snapshot_id", table_name="rc8_trace_evidence")
    op.drop_index("ix_rc8_trace_evidence_test_run_id", table_name="rc8_trace_evidence")
    op.drop_index("ix_rc8_trace_evidence_evidence_type", table_name="rc8_trace_evidence")
    op.drop_index("ix_rc8_trace_evidence_edge_id", table_name="rc8_trace_evidence")
    op.drop_index("ix_rc8_trace_evidence_graph_id", table_name="rc8_trace_evidence")
    op.drop_table("rc8_trace_evidence")

    op.drop_index("ix_rc8_trace_edge_verification_state", table_name="rc8_trace_edge")
    op.drop_index("ix_rc8_trace_edge_relation_type", table_name="rc8_trace_edge")
    op.drop_index("ix_rc8_trace_edge_to_node_id", table_name="rc8_trace_edge")
    op.drop_index("ix_rc8_trace_edge_from_node_id", table_name="rc8_trace_edge")
    op.drop_index("ix_rc8_trace_edge_graph_id", table_name="rc8_trace_edge")
    op.drop_table("rc8_trace_edge")

    op.drop_index("ix_rc8_trace_node_node_type", table_name="rc8_trace_node")
    op.drop_index("ix_rc8_trace_node_graph_id", table_name="rc8_trace_node")
    op.drop_table("rc8_trace_node")

    op.drop_index("ix_rc8_traceability_graph_code_source_snapshot_id", table_name="rc8_traceability_graph")
    op.drop_index("ix_rc8_traceability_graph_scope_revision_id", table_name="rc8_traceability_graph")
    op.drop_index("ix_rc8_traceability_graph_test_round_id", table_name="rc8_traceability_graph")
    op.drop_index("ix_rc8_traceability_graph_test_run_id", table_name="rc8_traceability_graph")
    op.drop_table("rc8_traceability_graph")

    op.drop_index("ix_rc8_code_source_snapshot_scope_revision_id", table_name="rc8_code_source_snapshot")
    op.drop_index("ix_rc8_code_source_snapshot_test_round_id", table_name="rc8_code_source_snapshot")
    op.drop_index("ix_rc8_code_source_snapshot_identity", table_name="rc8_code_source_snapshot")
    op.drop_table("rc8_code_source_snapshot")
