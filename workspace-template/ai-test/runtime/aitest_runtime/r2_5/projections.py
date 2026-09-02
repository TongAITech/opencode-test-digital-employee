from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import EXTENSION_ID, R25Error, SessionOrchestrationState


PROJECTION_TABLES = frozenset({"r25_agent_bindings", "r25_delegations"})
MIGRATION_SQL = (
    """
    CREATE TABLE r25_agent_bindings (
        mission_id TEXT NOT NULL,
        binding_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, binding_id)
    )
    """,
    """
    CREATE TABLE r25_delegations (
        mission_id TEXT NOT NULL,
        delegation_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, delegation_id)
    )
    """,
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class R25MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),
    )


class R25ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        if mission_id is None:
            conn.execute("DELETE FROM r25_agent_bindings")
            conn.execute("DELETE FROM r25_delegations")
        else:
            conn.execute("DELETE FROM r25_agent_bindings WHERE mission_id=?", (mission_id,))
            conn.execute("DELETE FROM r25_delegations WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, SessionOrchestrationState):
            raise R25Error("EXTENSION_SCHEMA_MISMATCH", "invalid R2.5 projection input")
        self.clear(conn, composed.mission_id)
        conn.executemany(
            "INSERT INTO r25_agent_bindings(mission_id,binding_id,state_json,projection_seq) VALUES(?,?,?,?)",
            [
                (composed.mission_id, item.binding_id, canonical_json(item.to_dict()), composed.seq)
                for item in sorted(state.bindings, key=lambda value: value.binding_id)
            ],
        )
        conn.executemany(
            "INSERT INTO r25_delegations(mission_id,delegation_id,state_json,projection_seq) VALUES(?,?,?,?)",
            [
                (
                    composed.mission_id,
                    delegation.delegation_id,
                    canonical_json({
                        "delegation": delegation.to_dict(),
                        "child_results": [
                            item.to_dict() for item in state.child_results
                            if item.delegation_id == delegation.delegation_id
                        ],
                        "joins": [
                            item.to_dict() for item in state.joins
                            if item.delegation_id == delegation.delegation_id
                        ],
                    }),
                    composed.seq,
                )
                for delegation in sorted(state.delegations, key=lambda value: value.delegation_id)
            ],
        )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> SessionOrchestrationState:
        bindings = [
            json.loads(row["state_json"])
            for row in conn.execute(
                "SELECT state_json FROM r25_agent_bindings WHERE mission_id=? ORDER BY binding_id",
                (mission_id,),
            )
        ]
        delegations: list[dict] = []
        child_results: list[dict] = []
        joins: list[dict] = []
        for row in conn.execute(
            "SELECT state_json FROM r25_delegations WHERE mission_id=? ORDER BY delegation_id",
            (mission_id,),
        ):
            value = json.loads(row["state_json"])
            delegations.append(value["delegation"])
            child_results.extend(value.get("child_results") or ())
            joins.extend(value.get("joins") or ())
        return SessionOrchestrationState.from_dict({
            "mission_id": mission_id,
            "bindings": bindings,
            "delegations": delegations,
            "child_results": child_results,
            "joins": joins,
        })

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        rows = conn.execute(
            "SELECT DISTINCT projection_seq FROM ("
            "SELECT projection_seq FROM r25_agent_bindings WHERE mission_id=? "
            "UNION ALL SELECT projection_seq FROM r25_delegations WHERE mission_id=?"
            ")",
            (mission_id, mission_id),
        ).fetchall()
        if not rows:
            return None
        values = {int(row[0]) for row in rows}
        return next(iter(values)) if len(values) == 1 else -1

    def verify(self, replayed_state: SessionOrchestrationState, projected_state: SessionOrchestrationState | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}
