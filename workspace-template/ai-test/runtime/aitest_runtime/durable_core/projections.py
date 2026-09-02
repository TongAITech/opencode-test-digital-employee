from __future__ import annotations

import json
import sqlite3

from .canonical import canonical_json, canonical_sha256
from .contracts import ComposedRuntimeState, ExtensionRegistry, RuntimeError, RuntimeState
from .event_store import list_events
from .reducer import initial_composed_state, initial_state, reduce, reduce_composed


_WRITE_ACTIONS = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
_SCHEMA_ACTIONS = {
    sqlite3.SQLITE_ALTER_TABLE,
    sqlite3.SQLITE_CREATE_INDEX,
    sqlite3.SQLITE_CREATE_TABLE,
    sqlite3.SQLITE_CREATE_TRIGGER,
    sqlite3.SQLITE_CREATE_VIEW,
    sqlite3.SQLITE_DROP_INDEX,
    sqlite3.SQLITE_DROP_TABLE,
    sqlite3.SQLITE_DROP_TRIGGER,
    sqlite3.SQLITE_DROP_VIEW,
}
_CONTROL_ACTIONS = {
    getattr(sqlite3, name)
    for name in (
        "SQLITE_ATTACH",
        "SQLITE_DETACH",
        "SQLITE_PRAGMA",
        "SQLITE_TRANSACTION",
        "SQLITE_SAVEPOINT",
        "SQLITE_CREATE_VTABLE",
        "SQLITE_DROP_VTABLE",
    )
    if hasattr(sqlite3, name)
}


def _authorize_all(action, first, second, database, source):
    return sqlite3.SQLITE_OK


def _projection_call(
    conn: sqlite3.Connection,
    manifest,
    callback,
    *,
    allow_writes: bool,
):
    allowed_tables = set(manifest.projection_contribution.projection_tables) if allow_writes else set()

    def authorize(action, first, second, database, source):
        if action in _WRITE_ACTIONS and first not in allowed_tables:
            return sqlite3.SQLITE_DENY
        if action in _SCHEMA_ACTIONS or action in _CONTROL_ACTIONS:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(authorize)
    try:
        return callback()
    except sqlite3.DatabaseError as exc:
        if "authorized" in str(exc).lower() or "prohibited" in str(exc).lower():
            raise RuntimeError(
                "EXTENSION_STATE_WRITE_FORBIDDEN",
                f"Extension {manifest.extension_id} attempted a forbidden projection write",
            ) from exc
        raise
    finally:
        # Python 3.9's bundled sqlite can leave an already-prepared COMMIT
        # unauthorized when the callback is reset with None. A permissive
        # callback restores normal Runtime-owned statements without granting
        # the Extension callback any additional execution window.
        conn.set_authorizer(_authorize_all)


def read_extension_projection(
    conn: sqlite3.Connection,
    manifest,
    mission_id: str,
):
    return _projection_call(
        conn,
        manifest,
        lambda: manifest.projection_contribution.read(conn, mission_id),
        allow_writes=False,
    )


def _apply_projection(conn: sqlite3.Connection, state: RuntimeState) -> None:
    if state.mission is None:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "cannot project an absent Mission")
    conn.execute("DELETE FROM goal_projection WHERE mission_id=?", (state.mission_id,))
    conn.execute("DELETE FROM session_projection WHERE mission_id=?", (state.mission_id,))
    conn.execute("DELETE FROM mission_projection WHERE mission_id=?", (state.mission_id,))
    conn.execute(
        "INSERT INTO mission_projection(mission_id,seq,state_json,state_hash) VALUES(?,?,?,?)",
        (
            state.mission_id,
            state.seq,
            canonical_json(state.mission.to_dict()),
            canonical_sha256(state.to_dict()),
        ),
    )
    conn.executemany(
        "INSERT INTO goal_projection(mission_id,goal_id,state_json) VALUES(?,?,?)",
        [(state.mission_id, goal.goal_id, canonical_json(goal.to_dict())) for goal in state.goals],
    )
    conn.executemany(
        "INSERT INTO session_projection(mission_id,session_id,state_json) VALUES(?,?,?)",
        [(state.mission_id, session.session_id, canonical_json(session.to_dict())) for session in state.sessions],
    )


def projection_state(conn: sqlite3.Connection, mission_id: str) -> RuntimeState | None:
    mission_row = conn.execute("SELECT * FROM mission_projection WHERE mission_id=?", (mission_id,)).fetchone()
    if mission_row is None:
        return None
    goals = {
        row["goal_id"]: json.loads(row["state_json"])
        for row in conn.execute("SELECT * FROM goal_projection WHERE mission_id=? ORDER BY goal_id", (mission_id,)).fetchall()
    }
    sessions = {
        row["session_id"]: json.loads(row["state_json"])
        for row in conn.execute("SELECT * FROM session_projection WHERE mission_id=? ORDER BY session_id", (mission_id,)).fetchall()
    }
    return RuntimeState.from_dict(
        {
            "mission_id": mission_id,
            "seq": int(mission_row["seq"]),
            "mission": json.loads(mission_row["state_json"]),
            "goals": goals,
            "sessions": sessions,
        }
    )


def replay_state(conn: sqlite3.Connection, mission_id: str, through_seq: int | None = None) -> RuntimeState:
    state = initial_state(mission_id)
    for event in list_events(conn, mission_id, through_seq=through_seq):
        state = reduce(state, event)
    return state


def replay_composed_state(
    conn: sqlite3.Connection,
    mission_id: str,
    registry: ExtensionRegistry,
    through_seq: int | None = None,
) -> ComposedRuntimeState:
    state = initial_composed_state(mission_id, registry)
    for event in list_events(conn, mission_id, through_seq=through_seq):
        state = reduce_composed(state, event, registry)
    return state


def _apply_composed_projection(
    conn: sqlite3.Connection,
    state: ComposedRuntimeState,
    registry: ExtensionRegistry,
) -> None:
    _apply_projection(conn, state.core_state)
    for manifest in registry.manifests:
        _projection_call(
            conn,
            manifest,
            lambda current=manifest: current.projection_contribution.apply(conn, state),
            allow_writes=True,
        )


def composed_projection_state(
    conn: sqlite3.Connection,
    mission_id: str,
    registry: ExtensionRegistry,
) -> ComposedRuntimeState | None:
    core_state = projection_state(conn, mission_id)
    if core_state is None:
        return None
    extension_states = {
        manifest.extension_id: read_extension_projection(conn, manifest, mission_id)
        for manifest in registry.manifests
    }
    return ComposedRuntimeState(mission_id, core_state.seq, core_state, extension_states)


def verify_composed_projection(
    conn: sqlite3.Connection,
    mission_id: str,
    registry: ExtensionRegistry,
) -> dict[str, object]:
    replayed = replay_composed_state(conn, mission_id, registry)
    projected = composed_projection_state(conn, mission_id, registry)
    core_replay_hash = canonical_sha256(replayed.core_state.to_dict())
    core_projection_hash = canonical_sha256(projected.core_state.to_dict()) if projected else None
    extension_results: dict[str, object] = {}
    extension_ok = True
    for manifest in registry.manifests:
        replayed_extension = replayed.extension_states[manifest.extension_id]
        projected_extension = projected.extension_states[manifest.extension_id] if projected else None
        result = manifest.projection_contribution.verify(replayed_extension, projected_extension)
        projection_seq_reader = getattr(manifest.projection_contribution, "projection_seq", None)
        projected_seq = (
            _projection_call(
                conn,
                manifest,
                lambda: projection_seq_reader(conn, mission_id),
                allow_writes=False,
            )
            if callable(projection_seq_reader)
            else None
        )
        if projected_seq is not None and projected_seq != replayed.seq:
            result = dict(result)
            result["ok"] = False
            result["projection_seq"] = projected_seq
            result["expected_seq"] = replayed.seq
        extension_results[manifest.extension_id] = result
        extension_ok = extension_ok and bool(result.get("ok"))
    composed_replay_hash = canonical_sha256(replayed.to_dict())
    composed_projection_hash = canonical_sha256(projected.to_dict()) if projected else None
    if (
        replayed.core_state.mission is None
        or projected is None
        or core_replay_hash != core_projection_hash
        or not extension_ok
        or composed_replay_hash != composed_projection_hash
    ):
        raise RuntimeError(
            "COMPOSED_PROJECTION_DRIFT",
            f"composed projection differs from Event replay for Mission {mission_id}",
            {
                "replay_hash": core_replay_hash,
                "projection_hash": core_projection_hash,
                "composed_replay_hash": composed_replay_hash,
                "composed_projection_hash": composed_projection_hash,
            },
        )
    return {
        "ok": True,
        "mission_id": mission_id,
        "replay_hash": core_replay_hash,
        "projection_hash": core_projection_hash,
        "composed_replay_hash": composed_replay_hash,
        "composed_projection_hash": composed_projection_hash,
        "extensions": extension_results,
    }


def verify_projection(conn: sqlite3.Connection, mission_id: str) -> dict[str, object]:
    replayed = replay_state(conn, mission_id)
    projected = projection_state(conn, mission_id)
    replay_hash = canonical_sha256(replayed.to_dict())
    projection_hash = canonical_sha256(projected.to_dict()) if projected else None
    if replayed.mission is None or projected is None or replay_hash != projection_hash:
        raise RuntimeError(
            "PROJECTION_DRIFT",
            f"projection differs from Event replay for Mission {mission_id}",
            {"replay_hash": replay_hash, "projection_hash": projection_hash},
        )
    return {
        "ok": True,
        "mission_id": mission_id,
        "replay_hash": replay_hash,
        "projection_hash": projection_hash,
    }


def _rebuild_projections(conn: sqlite3.Connection, mission_id: str | None = None) -> dict[str, object]:
    if mission_id is None:
        mission_ids = [row["mission_id"] for row in conn.execute("SELECT DISTINCT mission_id FROM events ORDER BY mission_id")]
        conn.execute("DELETE FROM goal_projection")
        conn.execute("DELETE FROM session_projection")
        conn.execute("DELETE FROM mission_projection")
    else:
        mission_ids = [mission_id]
        conn.execute("DELETE FROM goal_projection WHERE mission_id=?", (mission_id,))
        conn.execute("DELETE FROM session_projection WHERE mission_id=?", (mission_id,))
        conn.execute("DELETE FROM mission_projection WHERE mission_id=?", (mission_id,))
    hashes: dict[str, str] = {}
    for current_id in mission_ids:
        state = replay_state(conn, current_id)
        if state.mission is not None:
            _apply_projection(conn, state)
            hashes[current_id] = canonical_sha256(state.to_dict())
    return {"rebuilt": len(hashes), "state_hashes": hashes}


def _rebuild_composed_projections(
    conn: sqlite3.Connection,
    registry: ExtensionRegistry,
    mission_id: str | None = None,
) -> dict[str, object]:
    if mission_id is None:
        mission_ids = [row["mission_id"] for row in conn.execute("SELECT DISTINCT mission_id FROM events ORDER BY mission_id")]
        conn.execute("DELETE FROM goal_projection")
        conn.execute("DELETE FROM session_projection")
        conn.execute("DELETE FROM mission_projection")
        for manifest in registry.manifests:
            _projection_call(
                conn,
                manifest,
                lambda current=manifest: current.projection_contribution.clear(conn),
                allow_writes=True,
            )
    else:
        mission_ids = [mission_id]
        conn.execute("DELETE FROM goal_projection WHERE mission_id=?", (mission_id,))
        conn.execute("DELETE FROM session_projection WHERE mission_id=?", (mission_id,))
        conn.execute("DELETE FROM mission_projection WHERE mission_id=?", (mission_id,))
        for manifest in registry.manifests:
            _projection_call(
                conn,
                manifest,
                lambda current=manifest: current.projection_contribution.clear(conn, mission_id),
                allow_writes=True,
            )
    hashes: dict[str, str] = {}
    extension_hashes: dict[str, dict[str, str]] = {}
    for current_id in mission_ids:
        state = replay_composed_state(conn, current_id, registry)
        if state.core_state.mission is not None:
            _apply_composed_projection(conn, state, registry)
            hashes[current_id] = canonical_sha256(state.to_dict())
            extension_hashes[current_id] = {
                manifest.extension_id: manifest.state_contribution.hash(
                    state.extension_states[manifest.extension_id]
                )
                for manifest in registry.manifests
            }
    return {
        "rebuilt": len(hashes),
        "state_hashes": hashes,
        "extension_state_hashes": extension_hashes,
    }
