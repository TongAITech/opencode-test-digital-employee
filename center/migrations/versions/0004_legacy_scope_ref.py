"""relax legacy mission-stage scope_ref

Revision ID: 0004_legacy_scope_ref
Revises: 0003_artifact_metadata
Create Date: 2026-10-22

`scope_ref` belonged to the first formal-Center scaffold. The canonical RC8
StageInstance identity uses `scope_version` as the durable scope/snapshot ref.
Keep the legacy column for reversible migration compatibility, but it must not
remain a NOT NULL dependency of the formal domain model.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_legacy_scope_ref"
down_revision = "0003_artifact_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "rc8_mission_stage",
        "scope_ref",
        existing_type=sa.String(length=240),
        nullable=True,
    )


def downgrade() -> None:
    # Old schema requires a value. Populate compatibility data from the canonical
    # scope_version before restoring NOT NULL; this does not change formal truth.
    op.execute(
        "UPDATE rc8_mission_stage "
        "SET scope_ref = LEFT(scope_version, 240) "
        "WHERE scope_ref IS NULL"
    )
    op.alter_column(
        "rc8_mission_stage",
        "scope_ref",
        existing_type=sa.String(length=240),
        nullable=False,
    )
