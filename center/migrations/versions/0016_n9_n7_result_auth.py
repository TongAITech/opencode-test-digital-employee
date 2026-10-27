"""Bind N9 verification/regression to authoritative N7 WorkItems.

Revision ID: 0016_n9_n7_result_auth
Revises: 0015_n8_n9_persistence
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_n9_n7_result_auth"
down_revision = "0015_n8_n9_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rc8_defect_case",
        sa.Column("fix_verification_work_item_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "rc8_defect_case",
        sa.Column("fix_verification_attempt_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "rc8_defect_case",
        sa.Column("impact_regression_work_item_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "rc8_defect_case",
        sa.Column("impact_regression_case_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "rc8_defect_case",
        sa.Column("impact_regression_attempt_id", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rc8_defect_case", "impact_regression_attempt_id")
    op.drop_column("rc8_defect_case", "impact_regression_case_id")
    op.drop_column("rc8_defect_case", "impact_regression_work_item_id")
    op.drop_column("rc8_defect_case", "fix_verification_attempt_id")
    op.drop_column("rc8_defect_case", "fix_verification_work_item_id")
