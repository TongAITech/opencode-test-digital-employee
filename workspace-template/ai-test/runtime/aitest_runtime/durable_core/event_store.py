from __future__ import annotations

import json
import sqlite3
from typing import Iterable

from .canonical import canonical_json
from .contracts import EventEnvelope, RuntimeError


def _row_to_event(row: sqlite3.Row) -> EventEnvelope:
    return EventEnvelope(
        event_id=row["event_id"],
        mission_id=row["mission_id"],
        session_id=row["session_id"],
        seq=int(row["seq"]),
        event_type=row["event_type"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        command_id=row["command_id"],
        correlation_id=row["correlation_id"],
        initiator_type=row["initiator_type"],
        initiator_id=row["initiator_id"],
        payload=json.loads(row["payload_json"]),
        created_at=row["created_at"],
        schema_version=int(row["schema_version"]),
    )


def get_head_seq(conn: sqlite3.Connection, mission_id: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(seq), 0) AS head FROM events WHERE mission_id=?", (mission_id,)).fetchone()
    return int(row["head"])


def list_events(
    conn: sqlite3.Connection,
    mission_id: str,
    after_seq: int = 0,
    through_seq: int | None = None,
) -> list[EventEnvelope]:
    sql = "SELECT * FROM events WHERE mission_id=? AND seq>?"
    params: list[object] = [mission_id, after_seq]
    if through_seq is not None:
        sql += " AND seq<=?"
        params.append(through_seq)
    sql += " ORDER BY seq ASC"
    return [_row_to_event(row) for row in conn.execute(sql, params).fetchall()]


def _insert_events(conn: sqlite3.Connection, events: Iterable[EventEnvelope]) -> None:
    for event in events:
        expected = get_head_seq(conn, event.mission_id) + 1
        if event.seq != expected:
            raise RuntimeError(
                "EVENT_SEQUENCE_VIOLATION",
                f"expected seq {expected}, received {event.seq}",
            )
        conn.execute(
            """
            INSERT INTO events(
                event_id,mission_id,session_id,seq,event_type,entity_type,entity_id,
                command_id,correlation_id,initiator_type,initiator_id,payload_json,
                created_at,schema_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event.event_id,
                event.mission_id,
                event.session_id,
                event.seq,
                event.event_type,
                event.entity_type,
                event.entity_id,
                event.command_id,
                event.correlation_id,
                event.initiator_type,
                event.initiator_id,
                canonical_json(event.payload),
                event.created_at,
                event.schema_version,
            ),
        )
