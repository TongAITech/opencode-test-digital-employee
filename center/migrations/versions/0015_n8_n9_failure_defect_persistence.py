"""Persist formal N8 diagnosis and N9 defect closure state.

Revision ID: 0015_n8_n9_persistence
Revises: 0014_n5_n6_execution_state
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_n8_n9_persistence"
down_revision = "0014_n5_n6_execution_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rc8_failure_observation",
        sa.Column("observation_id", sa.String(length=240), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("source_mission_node_id", sa.String(length=300), nullable=False),
        sa.Column("source_attempt_id", sa.String(length=200), nullable=False),
        sa.Column("source_case_id", sa.String(length=200), nullable=False),
        sa.Column("source_assertion_id", sa.String(length=200), nullable=True),
        sa.Column("summary", sa.String(length=1000), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_rc8_failure_observation_test_run_id", "rc8_failure_observation", ["test_run_id"])
    op.create_index("ix_rc8_failure_observation_source_attempt_id", "rc8_failure_observation", ["source_attempt_id"])

    op.create_table(
        "rc8_diagnostic_evidence",
        sa.Column("diagnostic_id", sa.String(length=240), primary_key=True),
        sa.Column("observation_id", sa.String(length=240), nullable=False),
        sa.Column("classification", sa.String(length=64), nullable=False),
        sa.Column("classifier_ref", sa.String(length=300), nullable=False),
        sa.Column("reason_code", sa.String(length=240), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("diagnosed_at", sa.BigInteger(), nullable=False),
        sa.Column("route_scope", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_rc8_diagnostic_evidence_observation_id", "rc8_diagnostic_evidence", ["observation_id"])

    op.create_table(
        "rc8_gap_route_decision",
        sa.Column("decision_id", sa.String(length=240), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("observation_id", sa.String(length=240), nullable=False),
        sa.Column("diagnostic_id", sa.String(length=240), nullable=False),
        sa.Column("gap_id", sa.String(length=240), nullable=False),
        sa.Column("classification", sa.String(length=64), nullable=False),
        sa.Column("target_mission_node", sa.String(length=100), nullable=False),
        sa.Column("policy_code", sa.String(length=240), nullable=False),
        sa.Column("repairable", sa.Boolean(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("decided_at", sa.BigInteger(), nullable=False),
        sa.Column("authority", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_rc8_gap_route_decision_test_run_id", "rc8_gap_route_decision", ["test_run_id"])
    op.create_index("ix_rc8_gap_route_decision_gap_id", "rc8_gap_route_decision", ["gap_id"])

    op.create_table(
        "rc8_repair_work_order",
        sa.Column("work_order_id", sa.String(length=240), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("route_decision_id", sa.String(length=240), nullable=False),
        sa.Column("gap_id", sa.String(length=240), nullable=False),
        sa.Column("predecessor_attempt_id", sa.String(length=200), nullable=False),
        sa.Column("target_mission_node", sa.String(length=100), nullable=False),
        sa.Column("repair_strategy", sa.String(length=240), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_rc8_repair_work_order_test_run_id", "rc8_repair_work_order", ["test_run_id"])
    op.create_index("ix_rc8_repair_work_order_gap_id", "rc8_repair_work_order", ["gap_id"])

    op.create_table(
        "rc8_repair_receipt",
        sa.Column("receipt_id", sa.String(length=240), primary_key=True),
        sa.Column("work_order_id", sa.String(length=240), nullable=False),
        sa.Column("result", sa.String(length=64), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_rc8_repair_receipt_work_order_id", "rc8_repair_receipt", ["work_order_id"])

    op.create_table(
        "rc8_successor_attempt",
        sa.Column("successor_id", sa.String(length=240), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("work_order_id", sa.String(length=240), nullable=False, unique=True),
        sa.Column("repair_receipt_id", sa.String(length=240), nullable=False),
        sa.Column("predecessor_attempt_id", sa.String(length=200), nullable=False),
        sa.Column("successor_attempt_id", sa.String(length=200), nullable=False),
        sa.Column("authorized_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_rc8_successor_attempt_test_run_id", "rc8_successor_attempt", ["test_run_id"])
    op.create_index("ix_rc8_successor_attempt_work_order_id", "rc8_successor_attempt", ["work_order_id"], unique=True)
    op.create_index("ix_rc8_successor_attempt_successor_attempt_id", "rc8_successor_attempt", ["successor_attempt_id"])

    op.create_table(
        "rc8_defect_case",
        sa.Column("defect_case_id", sa.String(length=240), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("route_decision_id", sa.String(length=240), nullable=False, unique=True),
        sa.Column("source_observation_id", sa.String(length=240), nullable=False),
        sa.Column("source_case_id", sa.String(length=200), nullable=False),
        sa.Column("source_attempt_id", sa.String(length=200), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("candidate_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("reproduction_attempt_id", sa.String(length=200), nullable=True),
        sa.Column("reproducer_ref", sa.String(length=300), nullable=True),
        sa.Column("reproduction_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("qualification_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("rca_summary", sa.String(length=2000), nullable=True),
        sa.Column("rca_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("duplicate_of", sa.String(length=300), nullable=True),
        sa.Column("dedup_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("impact_refs", sa.JSON(), nullable=False),
        sa.Column("impact_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("severity", sa.String(length=64), nullable=True),
        sa.Column("review_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("external_defect_ref", sa.String(length=300), nullable=True),
        sa.Column("filing_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("fix_revision_ref", sa.String(length=300), nullable=True),
        sa.Column("fix_detected_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("fix_verification_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("impact_regression_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("closure_evidence_refs", sa.JSON(), nullable=False),
    )
    op.create_index("ix_rc8_defect_case_test_run_id", "rc8_defect_case", ["test_run_id"])
    op.create_index("ix_rc8_defect_case_route_decision_id", "rc8_defect_case", ["route_decision_id"], unique=True)
    op.create_index("ix_rc8_defect_case_state", "rc8_defect_case", ["state"])


def downgrade() -> None:
    op.drop_index("ix_rc8_defect_case_state", table_name="rc8_defect_case")
    op.drop_index("ix_rc8_defect_case_route_decision_id", table_name="rc8_defect_case")
    op.drop_index("ix_rc8_defect_case_test_run_id", table_name="rc8_defect_case")
    op.drop_table("rc8_defect_case")
    op.drop_index("ix_rc8_successor_attempt_successor_attempt_id", table_name="rc8_successor_attempt")
    op.drop_index("ix_rc8_successor_attempt_work_order_id", table_name="rc8_successor_attempt")
    op.drop_index("ix_rc8_successor_attempt_test_run_id", table_name="rc8_successor_attempt")
    op.drop_table("rc8_successor_attempt")
    op.drop_index("ix_rc8_repair_receipt_work_order_id", table_name="rc8_repair_receipt")
    op.drop_table("rc8_repair_receipt")
    op.drop_index("ix_rc8_repair_work_order_gap_id", table_name="rc8_repair_work_order")
    op.drop_index("ix_rc8_repair_work_order_test_run_id", table_name="rc8_repair_work_order")
    op.drop_table("rc8_repair_work_order")
    op.drop_index("ix_rc8_gap_route_decision_gap_id", table_name="rc8_gap_route_decision")
    op.drop_index("ix_rc8_gap_route_decision_test_run_id", table_name="rc8_gap_route_decision")
    op.drop_table("rc8_gap_route_decision")
    op.drop_index("ix_rc8_diagnostic_evidence_observation_id", table_name="rc8_diagnostic_evidence")
    op.drop_table("rc8_diagnostic_evidence")
    op.drop_index("ix_rc8_failure_observation_source_attempt_id", table_name="rc8_failure_observation")
    op.drop_index("ix_rc8_failure_observation_test_run_id", table_name="rc8_failure_observation")
    op.drop_table("rc8_failure_observation")
