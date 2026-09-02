from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import (
    EXTENSION_ID,
    AutomationMapping,
    CaseBatch,
    R33Error,
    R33ReuseReference,
    R33State,
    StandardTestCase,
    TestPoint,
    TestStrategy,
)


PROJECTION_TABLES = frozenset({
    "r33_strategies",
    "r33_test_points",
    "r33_case_batches",
    "r33_standard_cases",
    "r33_automation_mappings",
    "r33_reuses",
})
MIGRATION_SQL = (
    """
    CREATE TABLE r33_strategies (
        mission_id TEXT NOT NULL,
        strategy_version_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, strategy_version_id)
    )
    """,
    """
    CREATE TABLE r33_test_points (
        mission_id TEXT NOT NULL,
        point_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, point_id)
    )
    """,
    """
    CREATE TABLE r33_case_batches (
        mission_id TEXT NOT NULL,
        batch_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, batch_id)
    )
    """,
    """
    CREATE TABLE r33_standard_cases (
        mission_id TEXT NOT NULL,
        case_version_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, case_version_id)
    )
    """,
    """
    CREATE TABLE r33_automation_mappings (
        mission_id TEXT NOT NULL,
        mapping_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, mapping_id)
    )
    """,
    """
    CREATE TABLE r33_reuses (
        mission_id TEXT NOT NULL,
        reuse_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, reuse_id)
    )
    """,
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class R33MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),
    )


class R33ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        for table in sorted(PROJECTION_TABLES):
            if mission_id is None:
                conn.execute(f"DELETE FROM {table}")
            else:
                conn.execute(f"DELETE FROM {table} WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R33State):
            raise R33Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.3 projection input")
        self.clear(conn, composed.mission_id)
        conn.executemany(
            "INSERT INTO r33_strategies(mission_id,strategy_version_id,state_json,projection_seq) VALUES(?,?,?,?)",
            [(composed.mission_id, item.strategy_version_id, canonical_json(item.to_dict()), composed.seq) for item in state.strategies],
        )
        conn.executemany(
            "INSERT INTO r33_test_points(mission_id,point_id,state_json,projection_seq) VALUES(?,?,?,?)",
            [(composed.mission_id, item.point_id, canonical_json(item.to_dict()), composed.seq) for item in state.test_points],
        )
        conn.executemany(
            "INSERT INTO r33_case_batches(mission_id,batch_id,state_json,projection_seq) VALUES(?,?,?,?)",
            [(composed.mission_id, item.batch_id, canonical_json(item.to_dict()), composed.seq) for item in state.batches],
        )
        conn.executemany(
            "INSERT INTO r33_standard_cases(mission_id,case_version_id,state_json,projection_seq) VALUES(?,?,?,?)",
            [(composed.mission_id, item.case_version_id, canonical_json(item.to_dict()), composed.seq) for item in state.standard_cases],
        )
        conn.executemany(
            "INSERT INTO r33_automation_mappings(mission_id,mapping_id,state_json,projection_seq) VALUES(?,?,?,?)",
            [(composed.mission_id, item.mapping_id, canonical_json(item.to_dict()), composed.seq) for item in state.automation_mappings],
        )
        conn.executemany(
            "INSERT INTO r33_reuses(mission_id,reuse_id,state_json,projection_seq) VALUES(?,?,?,?)",
            [(composed.mission_id, item.reuse_id, canonical_json(item.to_dict()), composed.seq) for item in state.reuses],
        )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R33State:
        def rows(table: str, order: str) -> list[dict]:
            return [json.loads(row["state_json"]) for row in conn.execute(f"SELECT state_json FROM {table} WHERE mission_id=? ORDER BY {order}", (mission_id,))]
        return R33State(
            mission_id=mission_id,
            strategies=tuple(TestStrategy.from_dict(item) for item in rows("r33_strategies", "strategy_version_id")),
            test_points=tuple(TestPoint.from_dict(item) for item in rows("r33_test_points", "point_id")),
            batches=tuple(CaseBatch.from_dict(item) for item in rows("r33_case_batches", "batch_id")),
            standard_cases=tuple(StandardTestCase.from_dict(item) for item in rows("r33_standard_cases", "case_version_id")),
            automation_mappings=tuple(AutomationMapping.from_dict(item) for item in rows("r33_automation_mappings", "mapping_id")),
            reuses=tuple(R33ReuseReference.from_dict(item) for item in rows("r33_reuses", "reuse_id")),
        )

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        values: set[int] = set()
        for table in sorted(PROJECTION_TABLES):
            values.update(int(row[0]) for row in conn.execute(f"SELECT DISTINCT projection_seq FROM {table} WHERE mission_id=?", (mission_id,)))
        if not values:
            return None
        return next(iter(values)) if len(values) == 1 else -1

    def verify(self, replayed_state: R33State, projected_state: R33State | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}

