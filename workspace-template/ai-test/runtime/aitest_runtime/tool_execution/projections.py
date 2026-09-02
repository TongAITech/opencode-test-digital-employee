from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, RuntimeError, canonical_json, canonical_sha256

from .contracts import EXTENSION_ID, ToolExecutionRecord, ToolExecutionState


PROJECTION_TABLES = frozenset({"tool_execution_projection"})
MIGRATION_SQL = (
    """
    CREATE TABLE tool_execution_projection (
        mission_id TEXT NOT NULL,
        tool_execution_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        side_effect_policy TEXT NOT NULL,
        side_effect_state TEXT NOT NULL,
        status TEXT NOT NULL,
        intent_digest TEXT NOT NULL,
        command_id TEXT NOT NULL,
        created_seq INTEGER NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, tool_execution_id)
    )
    """,
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class ToolExecutionMigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),
    )


class ToolExecutionProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        if mission_id is None:
            conn.execute("DELETE FROM tool_execution_projection")
        else:
            conn.execute("DELETE FROM tool_execution_projection WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, ToolExecutionState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Tool Execution projection input")
        self.clear(conn, composed.mission_id)
        conn.executemany(
            """
            INSERT INTO tool_execution_projection(
                mission_id,tool_execution_id,attempt_id,task_id,side_effect_policy,side_effect_state,status,
                intent_digest,command_id,created_seq,state_json,projection_seq
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    composed.mission_id,
                    item.tool_execution_id,
                    item.intent.attempt_id,
                    item.intent.task_id,
                    item.intent.side_effect_policy.value,
                    item.side_effect_state.value,
                    item.status.value,
                    item.intent.intent_digest,
                    item.intent.command_id,
                    item.intent.created_seq,
                    canonical_json(item.to_dict()),
                    composed.seq,
                )
                for item in state.executions
            ],
        )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> ToolExecutionState:
        rows = conn.execute(
            "SELECT state_json FROM tool_execution_projection WHERE mission_id=? ORDER BY created_seq, tool_execution_id",
            (mission_id,),
        ).fetchall()
        return ToolExecutionState(
            mission_id=mission_id,
            executions=tuple(ToolExecutionRecord.from_dict(json.loads(row["state_json"])) for row in rows),
        )

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        values = {
            int(row["projection_seq"])
            for row in conn.execute(
                "SELECT DISTINCT projection_seq FROM tool_execution_projection WHERE mission_id=?", (mission_id,)
            ).fetchall()
        }
        if not values:
            return None
        if len(values) != 1:
            return -1
        return next(iter(values))

    def verify(self, replayed_state: ToolExecutionState, projected_state: ToolExecutionState | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}


ToolExecutionProjection = ToolExecutionProjectionContribution
ToolExecutionMigration = ToolExecutionMigrationContribution


__all__ = [
    "MIGRATION_SQL", "PROJECTION_TABLES", "ToolExecutionMigration", "ToolExecutionMigrationContribution",
    "ToolExecutionProjection", "ToolExecutionProjectionContribution",
]
