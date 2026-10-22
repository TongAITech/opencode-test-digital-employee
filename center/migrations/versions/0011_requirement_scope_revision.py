"""first-class requirement and scope revisions

Revision ID: 0011_req_scope_revision
Revises: 0010_stage_workitem
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011_req_scope_revision"
down_revision = "0010_stage_workitem"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rc8_requirement_revision",
        sa.Column("requirement_revision_id", sa.String(length=240), primary_key=True),
        sa.Column("requirement_id", sa.String(length=200), nullable=False),
        sa.Column("revision_label", sa.String(length=80), nullable=False),
        sa.Column("parent_requirement_revision_id", sa.String(length=240), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("requirement_id", "revision_label", name="uq_rc8_requirement_revision_label"),
    )
    op.create_index(
        "ix_rc8_requirement_revision_requirement_id",
        "rc8_requirement_revision",
        ["requirement_id"],
    )

    op.create_table(
        "rc8_scope_revision",
        sa.Column("scope_revision_id", sa.String(length=240), primary_key=True),
        sa.Column("requirement_revision_id", sa.String(length=240), nullable=False),
        sa.Column("revision_label", sa.String(length=80), nullable=False),
        sa.Column("parent_scope_revision_id", sa.String(length=240), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("requirement_revision_id", "revision_label", name="uq_rc8_scope_revision_label"),
    )
    op.create_index(
        "ix_rc8_scope_revision_requirement_revision_id",
        "rc8_scope_revision",
        ["requirement_revision_id"],
    )

    op.create_table(
        "rc8_delivery_revision_binding",
        sa.Column("delivery_id", sa.String(length=200), primary_key=True),
        sa.Column("requirement_revision_id", sa.String(length=240), nullable=False),
        sa.Column("scope_revision_id", sa.String(length=240), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
    )
    op.create_index(
        "ix_rc8_delivery_revision_binding_requirement_revision_id",
        "rc8_delivery_revision_binding",
        ["requirement_revision_id"],
    )
    op.create_index(
        "ix_rc8_delivery_revision_binding_scope_revision_id",
        "rc8_delivery_revision_binding",
        ["scope_revision_id"],
    )

    # Existing delivery history is not discarded. Materialize an immutable
    # compatibility revision pair per historical Delivery, preserving the
    # continuation chain when one exists. New product writes use the formal
    # revision repository and can provide business labels such as V1/V2/V3.
    op.execute(
        sa.text(
            """
            INSERT INTO rc8_requirement_revision (
                requirement_revision_id, requirement_id, revision_label,
                parent_requirement_revision_id, created_at, payload
            )
            SELECT
                'req-rev-' || md5(d.requirement_id || chr(31) || d.delivery_id),
                d.requirement_id,
                'LEGACY-' || substr(md5(d.delivery_id), 1, 12),
                CASE WHEN d.continuation_of_delivery_id IS NULL THEN NULL
                     ELSE 'req-rev-' || md5(d.requirement_id || chr(31) || d.continuation_of_delivery_id)
                END,
                d.created_at,
                json_build_object('source', '0011_LEGACY_BACKFILL', 'delivery_id', d.delivery_id)
            FROM rc8_requirement_delivery d
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO rc8_scope_revision (
                scope_revision_id, requirement_revision_id, revision_label,
                parent_scope_revision_id, created_at, payload
            )
            SELECT
                'scope-rev-' || md5(('req-rev-' || md5(d.requirement_id || chr(31) || d.delivery_id)) || chr(31) || d.delivery_id),
                'req-rev-' || md5(d.requirement_id || chr(31) || d.delivery_id),
                'LEGACY-' || substr(md5(d.delivery_id), 1, 12),
                CASE WHEN d.continuation_of_delivery_id IS NULL THEN NULL
                     ELSE 'scope-rev-' || md5(('req-rev-' || md5(d.requirement_id || chr(31) || d.continuation_of_delivery_id)) || chr(31) || d.continuation_of_delivery_id)
                END,
                d.created_at,
                json_build_object('source', '0011_LEGACY_BACKFILL', 'delivery_id', d.delivery_id)
            FROM rc8_requirement_delivery d
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO rc8_delivery_revision_binding (
                delivery_id, requirement_revision_id, scope_revision_id, created_at
            )
            SELECT
                d.delivery_id,
                'req-rev-' || md5(d.requirement_id || chr(31) || d.delivery_id),
                'scope-rev-' || md5(('req-rev-' || md5(d.requirement_id || chr(31) || d.delivery_id)) || chr(31) || d.delivery_id),
                d.created_at
            FROM rc8_requirement_delivery d
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_rc8_delivery_revision_binding_scope_revision_id",
        table_name="rc8_delivery_revision_binding",
    )
    op.drop_index(
        "ix_rc8_delivery_revision_binding_requirement_revision_id",
        table_name="rc8_delivery_revision_binding",
    )
    op.drop_table("rc8_delivery_revision_binding")
    op.drop_index(
        "ix_rc8_scope_revision_requirement_revision_id",
        table_name="rc8_scope_revision",
    )
    op.drop_table("rc8_scope_revision")
    op.drop_index(
        "ix_rc8_requirement_revision_requirement_id",
        table_name="rc8_requirement_revision",
    )
    op.drop_table("rc8_requirement_revision")
