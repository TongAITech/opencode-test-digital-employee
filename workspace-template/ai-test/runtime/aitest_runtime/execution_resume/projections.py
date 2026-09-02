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

from .contracts import EXTENSION_ID, ExecutionAttemptRecord, ExecutionResumeState


PROJECTION_TABLES = frozenset({"execution_attempt_projection"})

MIGRATION_SQL = (
    """
    CREATE TABLE execution_attempt_projection (
        mission_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        plan_revision_id TEXT NOT NULL,
        attempt_kind TEXT NOT NULL,
        predecessor_attempt_id TEXT,
        root_attempt_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        context_cursor_seq INTEGER NOT NULL,
        context_semantic_digest TEXT NOT NULL,
        context_schema_version INTEGER NOT NULL,
        context_builder_version INTEGER NOT NULL,
        context_canonicalization_version INTEGER NOT NULL,
        policy_id TEXT NOT NULL,
        policy_version INTEGER NOT NULL,
        knowledge_set_digest TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, attempt_id)
    )
    """,
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class ExecutionResumeMigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),
    )


class ExecutionResumeProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        if mission_id is None:
            conn.execute("DELETE FROM execution_attempt_projection")
        else:
            conn.execute(
                "DELETE FROM execution_attempt_projection WHERE mission_id=?",
                (mission_id,),
            )

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, ExecutionResumeState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Execution Resume projection input")
        self.clear(conn, composed.mission_id)
        conn.executemany(
            """
            INSERT INTO execution_attempt_projection(
                mission_id,attempt_id,task_id,plan_id,plan_revision_id,attempt_kind,
                predecessor_attempt_id,root_attempt_id,ordinal,context_cursor_seq,
                context_semantic_digest,context_schema_version,context_builder_version,
                context_canonicalization_version,policy_id,policy_version,
                knowledge_set_digest,state_json,projection_seq
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    composed.mission_id,
                    item.attempt_id,
                    item.task_id,
                    item.plan_id,
                    item.plan_revision_id,
                    item.attempt_kind,
                    item.predecessor_attempt_id,
                    item.root_attempt_id,
                    item.ordinal,
                    item.context_cursor.through_seq,
                    item.context_semantic_digest,
                    item.context_schema_version,
                    item.context_builder_version,
                    item.context_canonicalization_version,
                    item.policy_id,
                    item.policy_version,
                    item.knowledge_set_digest,
                    canonical_json(item.to_dict()),
                    composed.seq,
                )
                for item in state.attempts
            ],
        )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> ExecutionResumeState:
        rows = conn.execute(
            "SELECT state_json FROM execution_attempt_projection WHERE mission_id=? ORDER BY context_cursor_seq, attempt_id",
            (mission_id,),
        ).fetchall()
        return ExecutionResumeState(
            mission_id=mission_id,
            attempts=tuple(
                ExecutionAttemptRecord.from_dict(json.loads(row["state_json"]))
                for row in rows
            ),
        )

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        values = {
            int(row["projection_seq"])
            for row in conn.execute(
                "SELECT DISTINCT projection_seq FROM execution_attempt_projection WHERE mission_id=?",
                (mission_id,),
            ).fetchall()
        }
        if not values:
            return None
        if len(values) != 1:
            return -1
        return next(iter(values))

    def verify(
        self,
        replayed_state: ExecutionResumeState,
        projected_state: ExecutionResumeState | None,
    ) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {
            "ok": replay_hash == projection_hash,
            "replay_hash": replay_hash,
            "projection_hash": projection_hash,
        }
