from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from aitest_runtime.durable_core import (
    ComposedRuntimeState,
    MigrationStep,
    RuntimeError,
    canonical_json,
    canonical_sha256,
)

from .contracts import EXTENSION_ID, WorkGraphState


PROJECTION_TABLES = frozenset(
    {
        "work_graph_plan_projection",
        "work_graph_revision_projection",
        "work_graph_task_projection",
        "work_graph_dependency_projection",
        "work_graph_snapshot_projection",
    }
)


MIGRATION_SQL = (
    """
    CREATE TABLE work_graph_plan_projection (
        mission_id TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, plan_id)
    )
    """,
    """
    CREATE TABLE work_graph_revision_projection (
        mission_id TEXT NOT NULL,
        revision_id TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, revision_id)
    )
    """,
    """
    CREATE TABLE work_graph_task_projection (
        mission_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        revision_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, task_id)
    )
    """,
    """
    CREATE TABLE work_graph_dependency_projection (
        mission_id TEXT NOT NULL,
        revision_id TEXT NOT NULL,
        predecessor_task_id TEXT NOT NULL,
        successor_task_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, revision_id, predecessor_task_id, successor_task_id)
    )
    """,
    """
    CREATE TABLE work_graph_snapshot_projection (
        mission_id TEXT NOT NULL,
        snapshot_id TEXT NOT NULL,
        scope TEXT NOT NULL,
        plan_id TEXT,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, snapshot_id)
    )
    """,
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class WorkGraphMigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),
    )


class WorkGraphProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        for table in sorted(self.projection_tables):
            if mission_id is None:
                conn.execute(f"DELETE FROM {table}")
            else:
                conn.execute(f"DELETE FROM {table} WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, WorkGraphState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Work Graph projection input")
        self.clear(conn, composed.mission_id)
        conn.executemany(
            "INSERT INTO work_graph_plan_projection(mission_id,plan_id,state_json,projection_seq) VALUES(?,?,?,?)",
            [
                (composed.mission_id, item.plan_id, canonical_json(item.to_dict()), composed.seq)
                for item in state.plans
            ],
        )
        conn.executemany(
            "INSERT INTO work_graph_revision_projection(mission_id,revision_id,plan_id,state_json,projection_seq) VALUES(?,?,?,?,?)",
            [
                (
                    composed.mission_id,
                    item.revision_id,
                    item.plan_id,
                    canonical_json(item.to_dict()),
                    composed.seq,
                )
                for item in state.revisions
            ],
        )
        conn.executemany(
            "INSERT INTO work_graph_task_projection(mission_id,task_id,plan_id,revision_id,state_json,projection_seq) VALUES(?,?,?,?,?,?)",
            [
                (
                    composed.mission_id,
                    item.task_id,
                    item.plan_id,
                    item.plan_revision_id,
                    canonical_json(item.to_dict()),
                    composed.seq,
                )
                for item in state.tasks
            ],
        )
        conn.executemany(
            """
            INSERT INTO work_graph_dependency_projection(
                mission_id,revision_id,predecessor_task_id,successor_task_id,state_json,projection_seq
            ) VALUES(?,?,?,?,?,?)
            """,
            [
                (
                    composed.mission_id,
                    item.revision_id,
                    item.predecessor_task_id,
                    item.successor_task_id,
                    canonical_json(item.to_dict()),
                    composed.seq,
                )
                for item in state.dependencies
            ],
        )
        conn.executemany(
            """
            INSERT INTO work_graph_snapshot_projection(
                mission_id,snapshot_id,scope,plan_id,state_json,projection_seq
            ) VALUES(?,?,?,?,?,?)
            """,
            [
                (
                    composed.mission_id,
                    item.snapshot_id,
                    item.scope,
                    item.plan_id,
                    canonical_json(item.to_dict()),
                    composed.seq,
                )
                for item in state.snapshots
            ],
        )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> WorkGraphState:
        def rows(table: str, order_by: str):
            return conn.execute(
                f"SELECT state_json FROM {table} WHERE mission_id=? ORDER BY {order_by}",
                (mission_id,),
            ).fetchall()

        plans = [json.loads(row["state_json"]) for row in rows("work_graph_plan_projection", "plan_id")]
        revisions = [
            json.loads(row["state_json"])
            for row in rows("work_graph_revision_projection", "revision_id")
        ]
        tasks = [json.loads(row["state_json"]) for row in rows("work_graph_task_projection", "task_id")]
        dependencies = [
            json.loads(row["state_json"])
            for row in rows(
                "work_graph_dependency_projection",
                "revision_id,predecessor_task_id,successor_task_id",
            )
        ]
        snapshots = [
            json.loads(row["state_json"])
            for row in rows("work_graph_snapshot_projection", "snapshot_id")
        ]
        return WorkGraphState.from_dict(
            {
                "mission_id": mission_id,
                "plans": {item["plan_id"]: item for item in plans},
                "revisions": {item["revision_id"]: item for item in revisions},
                "tasks": {item["task_id"]: item for item in tasks},
                "dependencies": dependencies,
                "snapshots": {item["snapshot_id"]: item for item in snapshots},
            }
        )

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        values = set()
        for table in sorted(self.projection_tables):
            values.update(
                int(row["projection_seq"])
                for row in conn.execute(
                    f"SELECT DISTINCT projection_seq FROM {table} WHERE mission_id=?",
                    (mission_id,),
                ).fetchall()
            )
        if not values:
            return None
        if len(values) != 1:
            return -1
        return next(iter(values))

    def verify(self, replayed_state: WorkGraphState, projected_state: WorkGraphState | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {
            "ok": replay_hash == projection_hash,
            "replay_hash": replay_hash,
            "projection_hash": projection_hash,
        }
