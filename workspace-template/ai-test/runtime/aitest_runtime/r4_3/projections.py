from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import (
    EXTENSION_ID,
    ConfirmedDefectLifecycle,
    FixDetectionAssessment,
    FixLink,
    R43State,
)
from .errors import R43Error


PROJECTION_TABLES = frozenset(
    {
        "r43_confirmed_defect_lifecycles",
        "r43_fix_links",
        "r43_fix_detection_assessments",
    }
)

MIGRATION_SQL = (
    """
    CREATE TABLE r43_confirmed_defect_lifecycles (
        mission_id TEXT NOT NULL,
        object_id TEXT NOT NULL,
        object_version TEXT NOT NULL,
        r3_assessment_id TEXT NOT NULL,
        quality_version_id TEXT NOT NULL,
        campaign_ids TEXT NOT NULL,
        state_json TEXT NOT NULL,
        entity_digest TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )
    """,
    """
    CREATE TABLE r43_fix_links (
        mission_id TEXT NOT NULL,
        object_id TEXT NOT NULL,
        object_version TEXT NOT NULL,
        lifecycle_id TEXT NOT NULL,
        fix_candidate_ids TEXT NOT NULL,
        build_key TEXT,
        deployment_key TEXT,
        environment_key TEXT,
        state_json TEXT NOT NULL,
        entity_digest TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )
    """,
    """
    CREATE TABLE r43_fix_detection_assessments (
        mission_id TEXT NOT NULL,
        object_id TEXT NOT NULL,
        object_version TEXT NOT NULL,
        lifecycle_id TEXT NOT NULL,
        fix_link_id TEXT NOT NULL,
        quality_version_id TEXT NOT NULL,
        campaign_id TEXT NOT NULL,
        detection_scope TEXT NOT NULL,
        outcome TEXT NOT NULL,
        build_keys TEXT NOT NULL,
        deployment_keys TEXT NOT NULL,
        environment_keys TEXT NOT NULL,
        state_json TEXT NOT NULL,
        entity_digest TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )
    """,
    "CREATE INDEX r43_lifecycle_by_assessment ON r43_confirmed_defect_lifecycles(mission_id, r3_assessment_id)",
    "CREATE INDEX r43_lifecycle_by_quality_version ON r43_confirmed_defect_lifecycles(mission_id, quality_version_id)",
    "CREATE INDEX r43_link_by_lifecycle ON r43_fix_links(mission_id, lifecycle_id)",
    "CREATE INDEX r43_link_by_candidate ON r43_fix_links(mission_id, fix_candidate_ids)",
    "CREATE INDEX r43_link_by_build ON r43_fix_links(mission_id, build_key)",
    "CREATE INDEX r43_link_by_deployment ON r43_fix_links(mission_id, deployment_key)",
    "CREATE INDEX r43_link_by_environment ON r43_fix_links(mission_id, environment_key)",
    "CREATE INDEX r43_detection_by_lifecycle ON r43_fix_detection_assessments(mission_id, lifecycle_id)",
    "CREATE INDEX r43_detection_by_fix_link ON r43_fix_detection_assessments(mission_id, fix_link_id)",
    "CREATE INDEX r43_detection_by_quality_version ON r43_fix_detection_assessments(mission_id, quality_version_id)",
    "CREATE INDEX r43_detection_by_build ON r43_fix_detection_assessments(mission_id, build_keys)",
    "CREATE INDEX r43_detection_by_deployment ON r43_fix_detection_assessments(mission_id, deployment_keys)",
    "CREATE INDEX r43_detection_by_environment ON r43_fix_detection_assessments(mission_id, environment_keys)",
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class R43MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),
    )


def _keys(values: Any) -> str:
    return canonical_json(sorted({item.object_id for item in values}))


def _row_value(item: Any) -> tuple[str, str, str]:
    payload = item.to_dict()
    return canonical_json(payload), canonical_sha256(payload), canonical_sha256(payload)


def _read_object(row: sqlite3.Row, cls: type[Any]) -> Any:
    raw = json.loads(row["state_json"])
    digest = canonical_sha256(raw)
    if row["entity_digest"] != digest or row["state_hash"] != digest:
        raise R43Error("R4_3_PROJECTION_TAMPERED", f"projection digest mismatch for {row['object_id']}")
    return cls.from_dict(raw)


class R43ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        for table in sorted(PROJECTION_TABLES):
            if mission_id is None:
                conn.execute(f"DELETE FROM {table}")
            else:
                conn.execute(f"DELETE FROM {table} WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R43State):
            raise R43Error("R4_3_PROJECTION_INPUT_INVALID", "invalid R4.3 projection input")
        self.clear(conn, composed.mission_id)
        lifecycle_rows = []
        for item in sorted(state.confirmed_defect_lifecycles, key=lambda value: value.lifecycle_id):
            raw, digest, state_hash = _row_value(item)
            lifecycle_rows.append((
                composed.mission_id, item.lifecycle_id, "1", item.r3_6_defect_assessment_ref.object_id,
                item.quality_version_ref.object_id, _keys(item.campaign_refs), raw, digest, state_hash, composed.seq,
            ))
        conn.executemany(
            """INSERT INTO r43_confirmed_defect_lifecycles(
                mission_id,object_id,object_version,r3_assessment_id,quality_version_id,campaign_ids,
                state_json,entity_digest,state_hash,projection_seq
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            lifecycle_rows,
        )
        link_rows = []
        for item in sorted(state.fix_links, key=lambda value: value.fix_link_id):
            raw, digest, state_hash = _row_value(item)
            link_rows.append((
                composed.mission_id, item.fix_link_id, "1", item.confirmed_defect_lifecycle_ref.object_id,
                _keys(item.fix_candidate_refs), item.build_ref.object_id if item.build_ref else None,
                item.deployment_ref.object_id if item.deployment_ref else None,
                item.environment_ref.object_id if item.environment_ref else None,
                raw, digest, state_hash, composed.seq,
            ))
        conn.executemany(
            """INSERT INTO r43_fix_links(
                mission_id,object_id,object_version,lifecycle_id,fix_candidate_ids,build_key,deployment_key,environment_key,
                state_json,entity_digest,state_hash,projection_seq
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            link_rows,
        )
        detection_rows = []
        for item in sorted(state.fix_detection_assessments, key=lambda value: value.fix_detection_id):
            raw, digest, state_hash = _row_value(item)
            detection_rows.append((
                composed.mission_id, item.fix_detection_id, "1", item.confirmed_defect_lifecycle_ref.object_id,
                item.fix_link_ref.object_id, item.quality_version_ref.object_id, item.campaign_ref.object_id,
                item.detection_scope.value, item.outcome.value, _keys(item.build_refs), _keys(item.deployment_refs),
                _keys(item.environment_refs), raw, digest, state_hash, composed.seq,
            ))
        conn.executemany(
            """INSERT INTO r43_fix_detection_assessments(
                mission_id,object_id,object_version,lifecycle_id,fix_link_id,quality_version_id,campaign_id,
                detection_scope,outcome,build_keys,deployment_keys,environment_keys,state_json,entity_digest,state_hash,projection_seq
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            detection_rows,
        )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R43State:
        lifecycles = tuple(
            _read_object(row, ConfirmedDefectLifecycle)
            for row in conn.execute(
                "SELECT * FROM r43_confirmed_defect_lifecycles WHERE mission_id=? ORDER BY object_id", (mission_id,)
            ).fetchall()
        )
        links = tuple(
            _read_object(row, FixLink)
            for row in conn.execute("SELECT * FROM r43_fix_links WHERE mission_id=? ORDER BY object_id", (mission_id,)).fetchall()
        )
        detections = tuple(
            _read_object(row, FixDetectionAssessment)
            for row in conn.execute(
                "SELECT * FROM r43_fix_detection_assessments WHERE mission_id=? ORDER BY object_id", (mission_id,)
            ).fetchall()
        )
        return R43State(mission_id, lifecycles, links, (), detections)

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        rows = conn.execute(
            "SELECT projection_seq FROM r43_confirmed_defect_lifecycles WHERE mission_id=? "
            "UNION ALL SELECT projection_seq FROM r43_fix_links WHERE mission_id=? "
            "UNION ALL SELECT projection_seq FROM r43_fix_detection_assessments WHERE mission_id=?",
            (mission_id, mission_id, mission_id),
        ).fetchall()
        if not rows:
            return None
        values = {int(row[0]) for row in rows}
        return next(iter(values)) if len(values) == 1 else -1

    def verify(self, replayed_state: R43State, projected_state: R43State | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {
            "ok": projected_state is not None and replay_hash == projection_hash,
            "replay_hash": replay_hash,
            "projection_hash": projection_hash,
            "lifecycle_count": len(replayed_state.confirmed_defect_lifecycles),
            "fix_link_count": len(replayed_state.fix_links),
            "detection_count": len(replayed_state.fix_detection_assessments),
        }


def rebuild_r43_projection(conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
    """Rebuild only the three derived R4.3 tables from a replayed composed state."""
    R43ProjectionContribution().apply(conn, composed)


__all__ = ["PROJECTION_TABLES", "MIGRATION_SQL", "R43MigrationContribution", "R43ProjectionContribution", "rebuild_r43_projection"]
