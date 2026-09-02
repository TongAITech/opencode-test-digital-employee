from __future__ import annotations
import json
import sqlite3
from dataclasses import dataclass
from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, RuntimeError, canonical_json, canonical_sha256
from .contracts import EXTENSION_ID, G3Fact, G3State

TABLE = "g3_testing_intelligence_facts"
SQL = """
CREATE TABLE g3_testing_intelligence_facts (
    mission_id TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    fact_kind TEXT NOT NULL,
    digest TEXT NOT NULL,
    state_json TEXT NOT NULL,
    state_hash TEXT NOT NULL,
    projection_seq INTEGER NOT NULL,
    PRIMARY KEY(mission_id, fact_id)
)
"""

def _apply(conn: sqlite3.Connection) -> None:
    conn.execute(SQL)

@dataclass(frozen=True)
class G3MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (MigrationStep(1, canonical_sha256([SQL]), _apply),)

class G3ProjectionContribution:
    projection_tables = frozenset({TABLE})
    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        conn.execute(f"DELETE FROM {TABLE}" + ("" if mission_id is None else " WHERE mission_id=?"), () if mission_id is None else (mission_id,))
    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, G3State):
            raise RuntimeError("G3_PROJECTION_INPUT_INVALID", EXTENSION_ID)
        self.clear(conn, composed.mission_id)
        conn.executemany(
            f"INSERT INTO {TABLE}(mission_id,fact_id,fact_kind,digest,state_json,state_hash,projection_seq) VALUES(?,?,?,?,?,?,?)",
            [(composed.mission_id, f.fact_id, f.fact_kind, f.digest, canonical_json(f.to_dict()), canonical_sha256(f.to_dict()), composed.seq) for f in state.facts],
        )
    def read(self, conn: sqlite3.Connection, mission_id: str) -> G3State:
        # Projection rows are keyed by fact_id for identity, never for temporal order.
        # Rebuild state in canonical R1 Event Stream order so latest() matches replay.
        rows = conn.execute(f"SELECT state_json FROM {TABLE} WHERE mission_id=?", (mission_id,)).fetchall()
        facts = [G3Fact.from_dict(json.loads(row[0])) for row in rows]
        facts.sort(key=lambda fact: fact.created_seq)
        return G3State(mission_id, tuple(facts))
    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        rows = conn.execute(f"SELECT DISTINCT projection_seq FROM {TABLE} WHERE mission_id=?", (mission_id,)).fetchall()
        if not rows: return None
        return int(rows[0][0]) if len(rows) == 1 else -1
    def verify(self, replayed_state: G3State, projected_state: G3State | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}
