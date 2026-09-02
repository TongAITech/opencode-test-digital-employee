from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import EXTENSION_ID, CoverageSnapshot, DerivationVersion, R31Error, R31State, ReuseReference


PROJECTION_TABLES = frozenset({"r31_derivations", "r31_snapshots", "r31_reuses"})
MIGRATION_SQL = (
    """
    CREATE TABLE r31_derivations (
        mission_id TEXT NOT NULL,
        derivation_version_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, derivation_version_id)
    )
    """,
    """
    CREATE TABLE r31_snapshots (
        mission_id TEXT NOT NULL,
        snapshot_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, snapshot_id)
    )
    """,
    """
    CREATE TABLE r31_reuses (
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
class R31MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),
    )


class R31ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        if mission_id is None:
            conn.execute("DELETE FROM r31_derivations")
            conn.execute("DELETE FROM r31_snapshots")
            conn.execute("DELETE FROM r31_reuses")
        else:
            conn.execute("DELETE FROM r31_derivations WHERE mission_id=?", (mission_id,))
            conn.execute("DELETE FROM r31_snapshots WHERE mission_id=?", (mission_id,))
            conn.execute("DELETE FROM r31_reuses WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R31State):
            raise R31Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.1 projection input")
        self.clear(conn, composed.mission_id)
        conn.executemany(
            "INSERT INTO r31_derivations(mission_id,derivation_version_id,state_json,projection_seq) VALUES(?,?,?,?)",
            [
                (composed.mission_id, item.derivation_version_id, canonical_json(item.to_dict()), composed.seq)
                for item in sorted(state.derivations, key=lambda value: value.derivation_version_id)
            ],
        )
        conn.executemany(
            "INSERT INTO r31_snapshots(mission_id,snapshot_id,state_json,projection_seq) VALUES(?,?,?,?)",
            [
                (composed.mission_id, item.snapshot_id, canonical_json(item.to_dict()), composed.seq)
                for item in sorted(state.snapshots, key=lambda value: value.snapshot_id)
            ],
        )
        conn.executemany(
            "INSERT INTO r31_reuses(mission_id,reuse_id,state_json,projection_seq) VALUES(?,?,?,?)",
            [
                (composed.mission_id, item.reuse_id, canonical_json(item.to_dict()), composed.seq)
                for item in sorted(state.reuses, key=lambda value: value.reuse_id)
            ],
        )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R31State:
        derivations = [
            DerivationVersion.from_dict(json.loads(row["state_json"]))
            for row in conn.execute(
                "SELECT state_json FROM r31_derivations WHERE mission_id=? ORDER BY derivation_version_id",
                (mission_id,),
            )
        ]
        snapshots = [
            CoverageSnapshot.from_dict(json.loads(row["state_json"]))
            for row in conn.execute(
                "SELECT state_json FROM r31_snapshots WHERE mission_id=? ORDER BY snapshot_id",
                (mission_id,),
            )
        ]
        reuses = [
            ReuseReference.from_dict(json.loads(row["state_json"]))
            for row in conn.execute(
                "SELECT state_json FROM r31_reuses WHERE mission_id=? ORDER BY reuse_id",
                (mission_id,),
            )
        ]
        return R31State(
            mission_id=mission_id,
            derivations=tuple(derivations), snapshots=tuple(snapshots), reuses=tuple(reuses),
        )

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        rows = conn.execute(
            "SELECT DISTINCT projection_seq FROM ("
            "SELECT projection_seq FROM r31_derivations WHERE mission_id=? "
            "UNION ALL SELECT projection_seq FROM r31_snapshots WHERE mission_id=? "
            "UNION ALL SELECT projection_seq FROM r31_reuses WHERE mission_id=?"
            ")",
            (mission_id, mission_id, mission_id),
        ).fetchall()
        if not rows:
            return None
        values = {int(row[0]) for row in rows}
        return next(iter(values)) if len(values) == 1 else -1

    def verify(self, replayed_state: R31State, projected_state: R31State | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}
