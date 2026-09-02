from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import (
    EXTENSION_ID,
    BusinessJourney,
    JourneyCheckpoint,
    JourneyTransition,
    JourneyVerification,
    PageGraph,
    R35State,
)
from .errors import R35Error


PROJECTION_TABLES = frozenset({"r3_5_entities"})
SCHEMA_SQL = """
CREATE TABLE r3_5_entities (
    mission_id TEXT NOT NULL,
    entity_kind TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_version TEXT NOT NULL,
    state_json TEXT NOT NULL,
    entity_digest TEXT NOT NULL,
    projection_seq INTEGER NOT NULL,
    PRIMARY KEY(mission_id, entity_kind, entity_id, entity_version)
)
"""


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA_SQL)


@dataclass(frozen=True)
class R35MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(SCHEMA_SQL), _apply_schema),
    )


def _rows(state: R35State) -> list[tuple[str, str, str, dict[str, Any], str]]:
    values: list[tuple[str, str, str, dict[str, Any], str]] = []
    values.extend(
        ("PAGE_GRAPH", item.graph_id, str(item.graph_version), item.to_dict(), item.graph_digest)
        for item in state.page_graphs
    )
    values.extend(
        ("BUSINESS_JOURNEY", item.journey_id, str(item.journey_version), item.to_dict(), item.journey_digest)
        for item in state.journeys
    )
    values.extend(
        ("JOURNEY_TRANSITION", item.transition_id, "1", item.to_dict(), item.transition_digest)
        for item in state.transitions
    )
    values.extend(
        ("JOURNEY_CHECKPOINT", item.checkpoint_id, str(item.journey_version), item.to_dict(), item.checkpoint_digest)
        for item in state.checkpoints
    )
    values.extend(
        ("JOURNEY_VERIFICATION", item.verification_id, str(item.journey_version), item.to_dict(), item.verification_digest)
        for item in state.verifications
    )
    return sorted(values, key=lambda value: (value[0], value[1], value[2]))


def _decode_state(rows: list[sqlite3.Row], mission_id: str) -> R35State:
    values: dict[str, list[dict[str, Any]]] = {
        "PAGE_GRAPH": [],
        "BUSINESS_JOURNEY": [],
        "JOURNEY_TRANSITION": [],
        "JOURNEY_CHECKPOINT": [],
        "JOURNEY_VERIFICATION": [],
    }
    for row in rows:
        kind = str(row["entity_kind"])
        if kind not in values:
            raise R35Error("R3_5_PROJECTION_DRIFT", f"unknown R3.5 projection entity kind: {kind}")
        item = json.loads(row["state_json"])
        digest_key = {
            "PAGE_GRAPH": "graph_digest",
            "BUSINESS_JOURNEY": "journey_digest",
            "JOURNEY_TRANSITION": "transition_digest",
            "JOURNEY_CHECKPOINT": "checkpoint_digest",
            "JOURNEY_VERIFICATION": "verification_digest",
        }[kind]
        if item.get(digest_key) != row["entity_digest"]:
            raise R35Error("R3_5_PROJECTION_DRIFT", f"projection digest mismatch for {kind}:{row['entity_id']}")
        values[kind].append(item)
    return R35State(
        mission_id=mission_id,
        page_graphs=tuple(PageGraph.from_dict(item) for item in values["PAGE_GRAPH"]),
        journeys=tuple(BusinessJourney.from_dict(item) for item in values["BUSINESS_JOURNEY"]),
        transitions=tuple(JourneyTransition.from_dict(item) for item in values["JOURNEY_TRANSITION"]),
        checkpoints=tuple(JourneyCheckpoint.from_dict(item) for item in values["JOURNEY_CHECKPOINT"]),
        verifications=tuple(JourneyVerification.from_dict(item) for item in values["JOURNEY_VERIFICATION"]),
    )


class R35ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        if mission_id is None:
            conn.execute("DELETE FROM r3_5_entities")
        else:
            conn.execute("DELETE FROM r3_5_entities WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R35State):
            raise R35Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.5 projection input")
        self.clear(conn, composed.mission_id)
        conn.executemany(
            """
            INSERT INTO r3_5_entities(
                mission_id,entity_kind,entity_id,entity_version,state_json,entity_digest,projection_seq
            ) VALUES(?,?,?,?,?,?,?)
            """,
            [
                (
                    composed.mission_id,
                    entity_kind,
                    entity_id,
                    entity_version,
                    canonical_json(value),
                    digest,
                    composed.seq,
                )
                for entity_kind, entity_id, entity_version, value, digest in _rows(state)
            ],
        )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R35State:
        rows = conn.execute(
            """
            SELECT entity_kind,entity_id,entity_version,state_json,entity_digest,projection_seq
            FROM r3_5_entities
            WHERE mission_id=?
            ORDER BY entity_kind,entity_id,entity_version
            """,
            (mission_id,),
        ).fetchall()
        return _decode_state(rows, mission_id)

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        rows = conn.execute(
            "SELECT DISTINCT projection_seq FROM r3_5_entities WHERE mission_id=?",
            (mission_id,),
        ).fetchall()
        if not rows:
            return None
        values = {int(row[0]) for row in rows}
        if len(values) != 1:
            raise R35Error("R3_5_PROJECTION_DRIFT", "R3.5 projection contains multiple sequence values")
        return values.pop()

    def verify(self, replayed: R35State, projected: R35State | None) -> dict[str, object]:
        replayed_hash = canonical_sha256(replayed.to_dict())
        projected_hash = canonical_sha256(projected.to_dict()) if projected is not None else None
        return {
            "ok": projected is not None and replayed_hash == projected_hash,
            "replayed_hash": replayed_hash,
            "projected_hash": projected_hash,
            "entity_count": sum(
                len(items)
                for items in (
                    replayed.page_graphs,
                    replayed.journeys,
                    replayed.transitions,
                    replayed.checkpoints,
                    replayed.verifications,
                )
            ),
        }
