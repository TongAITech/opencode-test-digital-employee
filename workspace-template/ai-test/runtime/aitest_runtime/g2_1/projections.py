from __future__ import annotations
import json, sqlite3
from dataclasses import dataclass
from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256
from .contracts import EXTENSION_ID, SessionControlState

SQL = """CREATE TABLE g21_session_control_projection (
 mission_id TEXT PRIMARY KEY, state_json TEXT NOT NULL, state_hash TEXT NOT NULL, projection_seq INTEGER NOT NULL
)"""

def _apply(conn: sqlite3.Connection) -> None:
    conn.execute(SQL)

@dataclass(frozen=True)
class G21MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (MigrationStep(1, canonical_sha256(SQL), _apply),)

class G21ProjectionContribution:
    projection_tables = frozenset({"g21_session_control_projection"})
    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        if mission_id is None: conn.execute("DELETE FROM g21_session_control_projection")
        else: conn.execute("DELETE FROM g21_session_control_projection WHERE mission_id=?", (mission_id,))
    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        self.clear(conn, composed.mission_id)
        payload = state.to_dict()
        conn.execute("INSERT INTO g21_session_control_projection(mission_id,state_json,state_hash,projection_seq) VALUES(?,?,?,?)", (composed.mission_id, canonical_json(payload), canonical_sha256(payload), composed.seq))
    def read(self, conn: sqlite3.Connection, mission_id: str) -> SessionControlState:
        row = conn.execute("SELECT state_json FROM g21_session_control_projection WHERE mission_id=?", (mission_id,)).fetchone()
        return SessionControlState.from_dict(json.loads(row[0])) if row else SessionControlState(mission_id)
    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        row = conn.execute("SELECT projection_seq FROM g21_session_control_projection WHERE mission_id=?", (mission_id,)).fetchone()
        return int(row[0]) if row else None
    def verify(self, replayed_state: SessionControlState, projected_state: SessionControlState | None) -> dict[str, object]:
        a=canonical_sha256(replayed_state.to_dict()); b=canonical_sha256(projected_state.to_dict()) if projected_state else None
        return {"ok": a==b, "replay_hash": a, "projection_hash": b}
