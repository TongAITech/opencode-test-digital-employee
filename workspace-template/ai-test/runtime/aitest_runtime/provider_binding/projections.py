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

from .contracts import EXTENSION_ID, ProviderBindingRecord, ProviderBindingState


PROJECTION_TABLES = frozenset({"provider_binding_projection"})

MIGRATION_SQL = (
    """
    CREATE TABLE provider_binding_projection (
        mission_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        runtime_session_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        configuration_identity TEXT NOT NULL,
        configuration_version_json TEXT NOT NULL,
        configuration_digest TEXT NOT NULL,
        configuration_scope_json TEXT NOT NULL,
        configuration_provenance_json TEXT NOT NULL,
        command_id TEXT NOT NULL,
        created_seq INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        created_by_type TEXT NOT NULL,
        created_by_id TEXT NOT NULL,
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
class ProviderBindingMigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),
    )


class ProviderBindingProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        if mission_id is None:
            conn.execute("DELETE FROM provider_binding_projection")
        else:
            conn.execute("DELETE FROM provider_binding_projection WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, ProviderBindingState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Provider Binding projection input")
        self.clear(conn, composed.mission_id)
        conn.executemany(
            """
            INSERT INTO provider_binding_projection(
                mission_id,attempt_id,runtime_session_id,provider,model,
                configuration_identity,configuration_version_json,configuration_digest,
                configuration_scope_json,configuration_provenance_json,command_id,
                created_seq,created_at,created_by_type,created_by_id,state_json,projection_seq
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    composed.mission_id,
                    item.attempt_id,
                    item.runtime_session_id,
                    item.provider,
                    item.model,
                    item.configuration.identity,
                    canonical_json(item.configuration.version),
                    item.configuration.digest,
                    canonical_json(item.configuration.scope),
                    canonical_json(item.configuration.provenance),
                    item.command_id,
                    item.created_seq,
                    item.created_at,
                    item.created_by["type"],
                    item.created_by["id"],
                    canonical_json(item.to_dict()),
                    composed.seq,
                )
                for item in state.bindings
            ],
        )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> ProviderBindingState:
        rows = conn.execute(
            "SELECT state_json FROM provider_binding_projection WHERE mission_id=? ORDER BY created_seq, attempt_id",
            (mission_id,),
        ).fetchall()
        return ProviderBindingState(
            mission_id=mission_id,
            bindings=tuple(ProviderBindingRecord.from_dict(json.loads(row["state_json"])) for row in rows),
        )

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        values = {
            int(row["projection_seq"])
            for row in conn.execute(
                "SELECT DISTINCT projection_seq FROM provider_binding_projection WHERE mission_id=?",
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
        replayed_state: ProviderBindingState,
        projected_state: ProviderBindingState | None,
    ) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}


__all__ = [
    "MIGRATION_SQL",
    "PROJECTION_TABLES",
    "ProviderBindingMigrationContribution",
    "ProviderBindingProjectionContribution",
]
