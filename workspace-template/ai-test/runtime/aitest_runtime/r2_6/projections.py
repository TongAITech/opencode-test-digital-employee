from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import EXTENSION_ID, HumanGateState, R26Error


PROJECTION_TABLES = frozenset({"r26_human_gates"})
MIGRATION_SQL = (
    """
    CREATE TABLE r26_human_gates (
        mission_id TEXT NOT NULL,
        gate_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        gate_revision INTEGER NOT NULL,
        continuation_revision INTEGER NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, gate_id)
    )
    """,
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class R26MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),
    )


class R26ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        if mission_id is None:
            conn.execute("DELETE FROM r26_human_gates")
        else:
            conn.execute("DELETE FROM r26_human_gates WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, HumanGateState):
            raise R26Error("EXTENSION_SCHEMA_MISMATCH", "invalid R2.6 projection input")
        self.clear(conn, composed.mission_id)
        conn.executemany(
            "INSERT INTO r26_human_gates(mission_id,gate_id,state_json,gate_revision,continuation_revision,projection_seq) VALUES(?,?,?,?,?,?)",
            [
                (
                    composed.mission_id,
                    gate.gate_id,
                    canonical_json(gate.to_dict()),
                    gate.gate_revision,
                    gate.continuation_revision,
                    composed.seq,
                )
                for gate in sorted(state.gates, key=lambda value: value.gate_id)
            ],
        )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> HumanGateState:
        rows = conn.execute("SELECT state_json FROM r26_human_gates WHERE mission_id=? ORDER BY gate_id", (mission_id,)).fetchall()
        gates = {}
        for row in rows:
            raw = json.loads(row["state_json"])
            gates[raw["gate_id"]] = raw
        return HumanGateState.from_dict({"mission_id": mission_id, "gates": gates})

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        rows = conn.execute("SELECT DISTINCT projection_seq FROM r26_human_gates WHERE mission_id=?", (mission_id,)).fetchall()
        if not rows:
            return None
        values = {int(row[0]) for row in rows}
        return next(iter(values)) if len(values) == 1 else -1

    def verify(self, replayed_state: HumanGateState, projected_state: HumanGateState | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}
