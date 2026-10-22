"""complete governance projection semantics

Revision ID: 0002_governance_projection_semantics
Revises: 0001_formal_center_foundation
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_governance_projection_semantics"
down_revision = "0001_formal_center_foundation"
branch_labels = None
depends_on = None

_EMPTY_JSON = sa.text("'[]'::json")
_EMPTY_OBJECT = sa.text("'{}'::json")


def upgrade() -> None:
    # Mission Stage: scope_version is a durable scope/snapshot reference string,
    # never a numeric counter.  Keep the legacy scope_ref column for reversible
    # compatibility but stop using it as domain truth.
    op.alter_column(
        "rc8_mission_stage",
        "scope_version",
        existing_type=sa.BigInteger(),
        type_=sa.String(length=300),
        postgresql_using="scope_version::text",
        existing_nullable=False,
    )
    op.alter_column("rc8_mission_stage", "stage_type", type_=sa.String(length=100), existing_type=sa.String(length=80))
    op.alter_column("rc8_mission_stage", "evaluator_ref", new_column_name="evaluator_id")
    op.add_column("rc8_mission_stage", sa.Column("attempt_no", sa.BigInteger(), nullable=False, server_default="1"))
    for name in ("input_refs", "output_refs", "gap_refs", "invalidation_refs", "predecessor_ids", "successor_ids"):
        op.add_column("rc8_mission_stage", sa.Column(name, sa.JSON(), nullable=False, server_default=_EMPTY_JSON))
    op.add_column("rc8_mission_stage", sa.Column("assigned_worker", sa.String(length=240), nullable=True))
    op.add_column("rc8_mission_stage", sa.Column("policy_version", sa.String(length=240), nullable=True))
    op.add_column("rc8_mission_stage", sa.Column("started_at", sa.BigInteger(), nullable=True))
    op.add_column("rc8_mission_stage", sa.Column("finished_at", sa.BigInteger(), nullable=True))

    # Attempt: migrate the W-A scaffold names into the canonical AttemptRecord.
    op.alter_column("rc8_attempt", "state", new_column_name="status")
    op.alter_column("rc8_attempt", "ended_at", new_column_name="finished_at")
    op.alter_column("rc8_attempt", "source_snapshot_ref", new_column_name="input_snapshot_ref")
    op.alter_column("rc8_attempt", "input_snapshot_ref", existing_type=sa.String(length=240), type_=sa.String(length=300), existing_nullable=True)
    op.execute("UPDATE rc8_attempt SET input_snapshot_ref='MIGRATED_FORMAL_V1_UNKNOWN' WHERE input_snapshot_ref IS NULL")
    op.alter_column("rc8_attempt", "input_snapshot_ref", existing_type=sa.String(length=300), nullable=False)
    op.add_column("rc8_attempt", sa.Column("work_item_id", sa.String(length=200), nullable=False, server_default="MIGRATED_FORMAL_V1_UNKNOWN"))
    op.add_column("rc8_attempt", sa.Column("producer_node_id", sa.String(length=200), nullable=False, server_default="MIGRATED_FORMAL_V1_UNKNOWN"))
    op.add_column("rc8_attempt", sa.Column("producer_ref", sa.String(length=240), nullable=False, server_default="MIGRATED_FORMAL_V1_UNKNOWN"))
    op.add_column("rc8_attempt", sa.Column("case_id", sa.String(length=200), nullable=True))
    for name in ("action_refs", "assertion_refs", "evidence_refs", "coverage_refs", "gap_refs", "defect_refs"):
        op.add_column("rc8_attempt", sa.Column(name, sa.JSON(), nullable=False, server_default=_EMPTY_JSON))
    op.add_column("rc8_attempt", sa.Column("failure_ownership", sa.String(length=64), nullable=True))

    # Gap: canonical names and evidence/repair semantics.
    op.alter_column("rc8_gap", "state", new_column_name="status")
    op.alter_column("rc8_gap", "created_at", new_column_name="opened_at")
    op.alter_column("rc8_gap", "resolved_at", new_column_name="closed_at")
    op.add_column("rc8_gap", sa.Column("description", sa.Text(), nullable=False, server_default="MIGRATED_FORMAL_V1_GAP"))
    op.add_column("rc8_gap", sa.Column("repair_strategy", sa.Text(), nullable=False, server_default="MIGRATED_FORMAL_V1_REVIEW_REQUIRED"))
    op.add_column("rc8_gap", sa.Column("source_case_id", sa.String(length=200), nullable=True))
    op.add_column("rc8_gap", sa.Column("source_assertion_id", sa.String(length=200), nullable=True))
    for name in ("evidence_refs", "invalidates", "closure_evidence_refs"):
        op.add_column("rc8_gap", sa.Column(name, sa.JSON(), nullable=False, server_default=_EMPTY_JSON))

    # Coverage: preserve exact metric + provenance rather than a naked percent.
    op.alter_column("rc8_coverage_observation", "attempt_id", existing_type=sa.String(length=200), nullable=True)
    op.alter_column("rc8_coverage_observation", "source_snapshot_ref", existing_type=sa.String(length=240), type_=sa.String(length=300), existing_nullable=False)
    op.alter_column("rc8_coverage_observation", "source_tool", existing_type=sa.String(length=100), nullable=True)
    op.add_column("rc8_coverage_observation", sa.Column("case_id", sa.String(length=200), nullable=True))
    op.add_column("rc8_coverage_observation", sa.Column("metric_id", sa.String(length=200), nullable=False, server_default="MIGRATED_FORMAL_V1_METRIC"))
    op.add_column("rc8_coverage_observation", sa.Column("threshold", sa.Float(), nullable=False, server_default="0"))
    op.add_column("rc8_coverage_observation", sa.Column("critical", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("rc8_coverage_observation", sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default=_EMPTY_JSON))
    op.add_column("rc8_coverage_observation", sa.Column("artifact_refs", sa.JSON(), nullable=False, server_default=_EMPTY_JSON))

    op.create_table(
        "rc8_invalidation",
        sa.Column("invalidation_id", sa.String(length=200), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("source_ref", sa.String(length=300), nullable=False),
        sa.Column("target_refs", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_rc8_invalidation_test_run_id", "rc8_invalidation", ["test_run_id"])

    op.create_table(
        "rc8_sufficiency_evaluation",
        sa.Column("evaluation_id", sa.String(length=200), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=240), nullable=False),
        sa.Column("evaluator_id", sa.String(length=240), nullable=False),
        sa.Column("policy_version", sa.String(length=240), nullable=False),
        sa.Column("result", sa.String(length=64), nullable=False),
        sa.Column("dimension_refs", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("satisfied_requirement_refs", sa.JSON(), nullable=False),
        sa.Column("unsatisfied_requirement_refs", sa.JSON(), nullable=False),
        sa.Column("unresolved_gap_ids", sa.JSON(), nullable=False),
        sa.Column("accepted_waiver_ids", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evaluated_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_rc8_sufficiency_evaluation_test_run_id", "rc8_sufficiency_evaluation", ["test_run_id"])
    op.create_index("ix_rc8_sufficiency_evaluation_subject_id", "rc8_sufficiency_evaluation", ["subject_id"])

    op.create_table(
        "rc8_release_decision",
        sa.Column("release_decision_id", sa.String(length=200), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("mission_evaluation_ref", sa.String(length=240), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("blocking_defect_refs", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_rc8_release_decision_test_run_id", "rc8_release_decision", ["test_run_id"])

    op.create_table(
        "rc8_projection_receipt",
        sa.Column("event_id", sa.String(length=200), primary_key=True),
        sa.Column("test_run_id", sa.String(length=160), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("domain_ref", sa.String(length=300), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
    )
    op.create_index("ix_rc8_projection_receipt_test_run_id", "rc8_projection_receipt", ["test_run_id"])


def downgrade() -> None:
    op.drop_index("ix_rc8_projection_receipt_test_run_id", table_name="rc8_projection_receipt")
    op.drop_table("rc8_projection_receipt")
    op.drop_index("ix_rc8_release_decision_test_run_id", table_name="rc8_release_decision")
    op.drop_table("rc8_release_decision")
    op.drop_index("ix_rc8_sufficiency_evaluation_subject_id", table_name="rc8_sufficiency_evaluation")
    op.drop_index("ix_rc8_sufficiency_evaluation_test_run_id", table_name="rc8_sufficiency_evaluation")
    op.drop_table("rc8_sufficiency_evaluation")
    op.drop_index("ix_rc8_invalidation_test_run_id", table_name="rc8_invalidation")
    op.drop_table("rc8_invalidation")

    for name in ("artifact_refs", "evidence_refs", "critical", "threshold", "metric_id", "case_id"):
        op.drop_column("rc8_coverage_observation", name)
    op.alter_column("rc8_coverage_observation", "source_tool", existing_type=sa.String(length=100), nullable=False)
    op.alter_column("rc8_coverage_observation", "source_snapshot_ref", existing_type=sa.String(length=300), type_=sa.String(length=240), existing_nullable=False)
    op.alter_column("rc8_coverage_observation", "attempt_id", existing_type=sa.String(length=200), nullable=False)

    for name in ("closure_evidence_refs", "invalidates", "evidence_refs", "source_assertion_id", "source_case_id", "repair_strategy", "description"):
        op.drop_column("rc8_gap", name)
    op.alter_column("rc8_gap", "closed_at", new_column_name="resolved_at")
    op.alter_column("rc8_gap", "opened_at", new_column_name="created_at")
    op.alter_column("rc8_gap", "status", new_column_name="state")

    for name in ("failure_ownership", "defect_refs", "gap_refs", "coverage_refs", "evidence_refs", "assertion_refs", "action_refs", "case_id", "producer_ref", "producer_node_id", "work_item_id"):
        op.drop_column("rc8_attempt", name)
    op.alter_column("rc8_attempt", "input_snapshot_ref", existing_type=sa.String(length=300), type_=sa.String(length=240), existing_nullable=False)
    op.alter_column("rc8_attempt", "input_snapshot_ref", new_column_name="source_snapshot_ref")
    op.alter_column("rc8_attempt", "finished_at", new_column_name="ended_at")
    op.alter_column("rc8_attempt", "status", new_column_name="state")

    for name in ("finished_at", "started_at", "policy_version", "assigned_worker", "successor_ids", "predecessor_ids", "invalidation_refs", "gap_refs", "output_refs", "input_refs", "attempt_no"):
        op.drop_column("rc8_mission_stage", name)
    op.alter_column("rc8_mission_stage", "evaluator_id", new_column_name="evaluator_ref")
    op.alter_column(
        "rc8_mission_stage",
        "scope_version",
        existing_type=sa.String(length=300),
        type_=sa.BigInteger(),
        postgresql_using="scope_version::bigint",
        existing_nullable=False,
    )
    op.alter_column("rc8_mission_stage", "stage_type", type_=sa.String(length=80), existing_type=sa.String(length=100))
