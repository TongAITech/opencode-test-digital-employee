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

from .contracts import EXTENSION_ID, OpenCodeBridgeState, TransportObservationRecord


PROJECTION_TABLES = frozenset({"opencode_bridge_projection"})

MIGRATION_SQL = (
    """
    CREATE TABLE opencode_bridge_projection (
        mission_id TEXT NOT NULL,
        bridge_request_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        runtime_session_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        status TEXT NOT NULL,
        context_cursor_json TEXT NOT NULL,
        context_semantic_digest TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        provider_request_id TEXT NOT NULL,
        external_transport_handle TEXT,
        command_id TEXT NOT NULL,
        created_seq INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        created_by_type TEXT NOT NULL,
        created_by_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, bridge_request_id)
    )
    """,
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class OpenCodeBridgeMigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),
    )


class OpenCodeBridgeProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        if mission_id is None:
            conn.execute("DELETE FROM opencode_bridge_projection")
        else:
            conn.execute("DELETE FROM opencode_bridge_projection WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, OpenCodeBridgeState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid OpenCode Bridge projection input")
        self.clear(conn, composed.mission_id)
        conn.executemany(
            """
            INSERT INTO opencode_bridge_projection(
                mission_id,bridge_request_id,attempt_id,runtime_session_id,operation,status,
                context_cursor_json,context_semantic_digest,correlation_id,provider_request_id,
                external_transport_handle,command_id,created_seq,created_at,created_by_type,
                created_by_id,state_json,projection_seq
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    composed.mission_id,
                    item.bridge_request_id,
                    item.attempt_id,
                    item.runtime_session_id,
                    item.operation.value,
                    item.status,
                    canonical_json(item.context_cursor.to_dict()),
                    item.context_semantic_digest,
                    item.correlation_id,
                    item.provider_request_id,
                    item.external_transport_handle,
                    item.command_id,
                    item.created_seq,
                    item.created_at,
                    item.created_by["type"],
                    item.created_by["id"],
                    canonical_json(item.to_dict()),
                    composed.seq,
                )
                for item in state.observations
            ],
        )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> OpenCodeBridgeState:
        rows = conn.execute(
            "SELECT state_json FROM opencode_bridge_projection WHERE mission_id=? ORDER BY created_seq, bridge_request_id",
            (mission_id,),
        ).fetchall()
        return OpenCodeBridgeState(
            mission_id=mission_id,
            observations=tuple(TransportObservationRecord.from_dict(json.loads(row["state_json"])) for row in rows),
        )

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        values = {
            int(row["projection_seq"])
            for row in conn.execute(
                "SELECT DISTINCT projection_seq FROM opencode_bridge_projection WHERE mission_id=?",
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
        replayed_state: OpenCodeBridgeState,
        projected_state: OpenCodeBridgeState | None,
    ) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}


OpenCodeTransportMigrationContribution = OpenCodeBridgeMigrationContribution
OpenCodeTransportProjectionContribution = OpenCodeBridgeProjectionContribution


__all__ = [
    "MIGRATION_SQL",
    "OpenCodeBridgeMigrationContribution",
    "OpenCodeBridgeProjectionContribution",
    "OpenCodeTransportMigrationContribution",
    "OpenCodeTransportProjectionContribution",
    "PROJECTION_TABLES",
]
