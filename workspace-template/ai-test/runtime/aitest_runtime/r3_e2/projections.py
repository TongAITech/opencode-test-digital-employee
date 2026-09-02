from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import EXTENSION_ID, R3E2Error, R3E2State, SUTAuthContext, SUTAuthContextScope


PROJECTION_TABLES = frozenset({
    "r3e2_auth_contexts",
    "r3e2_origin_records",
    "r3e2_lifecycle_events",
})

MIGRATION_SQL = (
    """
    CREATE TABLE r3e2_auth_contexts (
        scope_key TEXT NOT NULL,
        project_id TEXT NOT NULL,
        environment_id TEXT NOT NULL,
        system_id TEXT NOT NULL,
        version_scope TEXT NOT NULL,
        tenant_scope_ref TEXT NOT NULL,
        permission_scope_digest TEXT NOT NULL,
        context_key TEXT NOT NULL,
        context_id TEXT NOT NULL,
        context_epoch INTEGER NOT NULL,
        status TEXT NOT NULL,
        validation_status TEXT NOT NULL,
        state_json TEXT NOT NULL,
        origin_missions_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(scope_key, context_key)
    )
    """,
    """
    CREATE TABLE r3e2_origin_records (
        mission_id TEXT NOT NULL,
        context_key TEXT NOT NULL,
        event_seq INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        state_json TEXT NOT NULL,
        origin_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, context_key, event_seq)
    )
    """,
    """
    CREATE TABLE r3e2_lifecycle_events (
        scope_key TEXT NOT NULL,
        context_key TEXT NOT NULL,
        event_seq INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        status TEXT NOT NULL,
        validation_status TEXT NOT NULL,
        state_json TEXT NOT NULL,
        origin_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(scope_key, context_key, event_seq)
    )
    """,
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class R3E2MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),
    )


def _decode(value: str) -> dict[str, Any]:
    return json.loads(value)


def _scope_fields(scope: SUTAuthContextScope) -> tuple[str, str, str, str, str, str, str]:
    return (
        scope.key,
        scope.project_id,
        scope.environment_id,
        scope.system_id,
        scope.version_scope,
        scope.tenant_scope_ref,
        scope.permission_scope_digest,
    )


def _origins(value: str | None, mission_id: str) -> list[str]:
    existing = list(json.loads(value) if value else [])
    if mission_id not in existing:
        existing.append(mission_id)
    return sorted(set(existing))


def _immutable_context(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "identity": value["identity"],
        "scope": value["scope"],
        "auth_profile_ref": value.get("auth_profile_ref"),
        "auth_method": value["auth_method"],
    }


def _upsert_context(
    conn: sqlite3.Connection,
    context: SUTAuthContext,
    mission_id: str,
    projection_seq: int,
) -> None:
    scope = context.scope
    fields = _scope_fields(scope)
    row = conn.execute(
        "SELECT state_json, origin_missions_json FROM r3e2_auth_contexts WHERE scope_key=? AND context_key=?",
        (scope.key, context.identity.key),
    ).fetchone()
    state = context.to_dict()
    if row is None:
        conn.execute(
            """
            INSERT INTO r3e2_auth_contexts(
                scope_key,project_id,environment_id,system_id,version_scope,tenant_scope_ref,
                permission_scope_digest,context_key,context_id,context_epoch,status,validation_status,
                state_json,origin_missions_json,projection_seq
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            fields + (
                context.identity.key,
                context.identity.sut_auth_context_id,
                context.identity.context_epoch,
                context.status,
                context.validation_status,
                canonical_json(state),
                canonical_json([mission_id]),
                projection_seq,
            ),
        )
        return
    existing = _decode(row["state_json"])
    if canonical_sha256(_immutable_context(existing)) != canonical_sha256(_immutable_context(state)):
        raise R3E2Error("R3_E2_CONTEXT_ID_CONFLICT", f"canonical context conflicts across origins: {context.identity.key}")
    origins = _origins(row["origin_missions_json"], mission_id)
    conn.execute(
        """
        UPDATE r3e2_auth_contexts
        SET status=?,validation_status=?,state_json=?,origin_missions_json=?,projection_seq=?
        WHERE scope_key=? AND context_key=?
        """,
        (context.status, context.validation_status, canonical_json(state), canonical_json(origins), projection_seq, scope.key, context.identity.key),
    )


class R3E2ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        if mission_id is None:
            for table in sorted(PROJECTION_TABLES):
                conn.execute(f"DELETE FROM {table}")
            return
        conn.execute("DELETE FROM r3e2_origin_records WHERE mission_id=?", (mission_id,))
        rows = conn.execute("SELECT scope_key,context_key,origin_missions_json FROM r3e2_auth_contexts").fetchall()
        for row in rows:
            origins = [item for item in json.loads(row["origin_missions_json"]) if item != mission_id]
            if origins:
                conn.execute(
                    "UPDATE r3e2_auth_contexts SET origin_missions_json=? WHERE scope_key=? AND context_key=?",
                    (canonical_json(sorted(origins)), row["scope_key"], row["context_key"]),
                )
            else:
                conn.execute("DELETE FROM r3e2_auth_contexts WHERE scope_key=? AND context_key=?", (row["scope_key"], row["context_key"]))
        conn.execute("DELETE FROM r3e2_lifecycle_events WHERE origin_json LIKE ?", (f'%"mission_id":"{mission_id}"%',))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R3E2State):
            raise R3E2Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.E2 projection input")
        self.clear(conn, composed.mission_id)
        for history in state.transition_history:
            context = SUTAuthContext.from_dict(history["context"])
            event_seq = int(history["event_seq"])
            origin = dict(history["origin_lineage"])
            conn.execute(
                """
                INSERT OR REPLACE INTO r3e2_origin_records(
                    mission_id,context_key,event_seq,event_type,state_json,origin_json,projection_seq
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (composed.mission_id, context.identity.key, event_seq, history["event_type"], canonical_json(context.to_dict()), canonical_json(origin), composed.seq),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO r3e2_lifecycle_events(
                    scope_key,context_key,event_seq,event_type,status,validation_status,state_json,origin_json,projection_seq
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (context.scope.key, context.identity.key, event_seq, history["event_type"], context.status, context.validation_status, canonical_json(context.to_dict()), canonical_json(origin), composed.seq),
            )
        for context in sorted(state.contexts, key=lambda value: value.identity.key):
            _upsert_context(conn, context, composed.mission_id, composed.seq)

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R3E2State:
        rows = conn.execute(
            "SELECT context_key,event_seq,event_type,state_json,origin_json FROM r3e2_origin_records WHERE mission_id=? ORDER BY event_seq",
            (mission_id,),
        ).fetchall()
        latest: dict[str, dict[str, Any]] = {}
        history: list[dict[str, Any]] = []
        for row in rows:
            snapshot = _decode(row["state_json"])
            latest[row["context_key"]] = snapshot
            history.append({
                "event_type": row["event_type"],
                "context_key": row["context_key"],
                "event_seq": int(row["event_seq"]),
                "origin_lineage": _decode(row["origin_json"]),
                "context": snapshot,
                "status": snapshot["status"],
                "validation_status": snapshot["validation_status"],
                "record_digest": snapshot["record_digest"],
            })
        return R3E2State(
            mission_id=mission_id,
            contexts=tuple(SUTAuthContext.from_dict(value) for value in latest.values()),
            transition_history=tuple(history),
        )

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        rows = conn.execute("SELECT DISTINCT projection_seq FROM r3e2_origin_records WHERE mission_id=?", (mission_id,)).fetchall()
        if not rows:
            return None
        values = {int(row[0]) for row in rows}
        return next(iter(values)) if len(values) == 1 else -1

    def verify(self, replayed_state: R3E2State, projected_state: R3E2State | None) -> dict[str, Any]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}


def scope_rows(conn: sqlite3.Connection, scope: SUTAuthContextScope) -> list[dict[str, Any]]:
    return [
        _decode(row["state_json"])
        for row in conn.execute(
            "SELECT state_json FROM r3e2_auth_contexts WHERE scope_key=? ORDER BY context_key",
            (scope.key,),
        ).fetchall()
    ]
