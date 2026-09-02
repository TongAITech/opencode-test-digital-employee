from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import (
    EXTENSION_ID,
    CampaignSelectionRevision,
    QualityVersion,
    R41State,
    TestCampaign,
)
from .errors import R41Error


PROJECTION_TABLES = frozenset(
    {
        "r41_quality_versions",
        "r41_test_campaigns",
        "r41_campaign_selection_revisions",
    }
)

MIGRATION_SQL = (
    """
    CREATE TABLE r41_quality_versions (
        mission_id TEXT NOT NULL,
        object_id TEXT NOT NULL,
        object_version TEXT NOT NULL,
        quality_version_id TEXT NOT NULL,
        version_digest TEXT NOT NULL,
        state_json TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )
    """,
    """
    CREATE TABLE r41_test_campaigns (
        mission_id TEXT NOT NULL,
        object_id TEXT NOT NULL,
        object_version TEXT NOT NULL,
        campaign_id TEXT NOT NULL,
        campaign_digest TEXT NOT NULL,
        state_json TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )
    """,
    """
    CREATE TABLE r41_campaign_selection_revisions (
        mission_id TEXT NOT NULL,
        object_id TEXT NOT NULL,
        object_version TEXT NOT NULL,
        selection_revision_id TEXT NOT NULL,
        supersedes_revision_id TEXT,
        revision_digest TEXT NOT NULL,
        state_json TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )
    """,
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class R41MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),
    )


class R41ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        for table in (
            "r41_quality_versions",
            "r41_test_campaigns",
            "r41_campaign_selection_revisions",
        ):
            if mission_id is None:
                conn.execute(f"DELETE FROM {table}")
            else:
                conn.execute(f"DELETE FROM {table} WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R41State):
            raise R41Error("R4_1_PROJECTION_INPUT_INVALID", "invalid R4.1 projection input")
        self.clear(conn, composed.mission_id)
        conn.executemany(
            """
            INSERT INTO r41_quality_versions(
                mission_id,object_id,object_version,quality_version_id,version_digest,state_json,state_hash,projection_seq
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            [
                (
                    composed.mission_id, item.quality_version_id, "1", item.quality_version_id,
                    item.version_digest, canonical_json(item.to_dict()), canonical_sha256(item.to_dict()), composed.seq,
                )
                for item in sorted(state.quality_versions, key=lambda value: value.quality_version_id)
            ],
        )
        conn.executemany(
            """
            INSERT INTO r41_test_campaigns(
                mission_id,object_id,object_version,campaign_id,campaign_digest,state_json,state_hash,projection_seq
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            [
                (
                    composed.mission_id, item.campaign_id, "1", item.campaign_id,
                    item.campaign_digest, canonical_json(item.to_dict()), canonical_sha256(item.to_dict()), composed.seq,
                )
                for item in sorted(state.test_campaigns, key=lambda value: value.campaign_id)
            ],
        )
        conn.executemany(
            """
            INSERT INTO r41_campaign_selection_revisions(
                mission_id,object_id,object_version,selection_revision_id,supersedes_revision_id,
                revision_digest,state_json,state_hash,projection_seq
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    composed.mission_id, item.selection_revision_id, "1", item.selection_revision_id,
                    item.supersedes_revision_ref.object_id if item.supersedes_revision_ref else None,
                    item.revision_digest, canonical_json(item.to_dict()), canonical_sha256(item.to_dict()), composed.seq,
                )
                for item in sorted(state.selection_revisions, key=lambda value: value.selection_revision_id)
            ],
        )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R41State:
        quality_versions = tuple(
            QualityVersion.from_dict(json.loads(row["state_json"]))
            for row in conn.execute(
                "SELECT state_json FROM r41_quality_versions WHERE mission_id=? ORDER BY object_id", (mission_id,)
            ).fetchall()
        )
        campaigns = tuple(
            TestCampaign.from_dict(json.loads(row["state_json"]))
            for row in conn.execute(
                "SELECT state_json FROM r41_test_campaigns WHERE mission_id=? ORDER BY object_id", (mission_id,)
            ).fetchall()
        )
        selections = tuple(
            CampaignSelectionRevision.from_dict(json.loads(row["state_json"]))
            for row in conn.execute(
                "SELECT state_json FROM r41_campaign_selection_revisions WHERE mission_id=? ORDER BY object_id", (mission_id,)
            ).fetchall()
        )
        return R41State(mission_id, quality_versions, campaigns, selections)

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        rows = conn.execute(
            "SELECT projection_seq FROM r41_quality_versions WHERE mission_id=? "
            "UNION ALL SELECT projection_seq FROM r41_test_campaigns WHERE mission_id=? "
            "UNION ALL SELECT projection_seq FROM r41_campaign_selection_revisions WHERE mission_id=?",
            (mission_id, mission_id, mission_id),
        ).fetchall()
        if not rows:
            return None
        values = {int(row[0]) for row in rows}
        return next(iter(values)) if len(values) == 1 else -1

    def verify(self, replayed_state: R41State, projected_state: R41State | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}

