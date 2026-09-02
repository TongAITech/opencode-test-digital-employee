from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .contracts import ExtensionRegistry, RuntimeError


_MIGRATION_WRITE_ACTIONS = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
_MIGRATION_FORBIDDEN_ACTIONS = {
    getattr(sqlite3, name)
    for name in (
        "SQLITE_ATTACH",
        "SQLITE_DETACH",
        "SQLITE_PRAGMA",
        "SQLITE_TRANSACTION",
        "SQLITE_SAVEPOINT",
        "SQLITE_CREATE_TRIGGER",
        "SQLITE_CREATE_VIEW",
        "SQLITE_DROP_TRIGGER",
        "SQLITE_DROP_VIEW",
        "SQLITE_CREATE_VTABLE",
        "SQLITE_DROP_VTABLE",
    )
    if hasattr(sqlite3, name)
}


def _authorize_all(action, first, second, database, source):
    return sqlite3.SQLITE_OK


def _apply_extension_migration(conn, manifest, step, allowed_tables: set[str]) -> None:
    create_table = sqlite3.SQLITE_CREATE_TABLE
    create_index = sqlite3.SQLITE_CREATE_INDEX
    drop_table = sqlite3.SQLITE_DROP_TABLE
    drop_index = sqlite3.SQLITE_DROP_INDEX
    alter_table = sqlite3.SQLITE_ALTER_TABLE

    def authorize(action, first, second, database, source):
        if action in _MIGRATION_WRITE_ACTIONS and first not in allowed_tables and first != "sqlite_master":
            return sqlite3.SQLITE_DENY
        if action in {create_table, drop_table} and first not in allowed_tables:
            return sqlite3.SQLITE_DENY
        if action in {create_index, drop_index} and second not in allowed_tables:
            return sqlite3.SQLITE_DENY
        if action == alter_table and second not in allowed_tables:
            return sqlite3.SQLITE_DENY
        if action in _MIGRATION_FORBIDDEN_ACTIONS:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(authorize)
    try:
        step.apply(conn)
    except sqlite3.DatabaseError as exc:
        if "authorized" in str(exc).lower() or "prohibited" in str(exc).lower():
            raise RuntimeError(
                "PROJECTION_TABLE_FORBIDDEN",
                f"Extension {manifest.extension_id} migration exceeded its schema boundary",
            ) from exc
        raise
    finally:
        conn.set_authorizer(_authorize_all)


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS commands (
    command_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    session_id TEXT,
    command_type TEXT NOT NULL,
    expected_seq INTEGER NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    idempotency_key TEXT,
    correlation_id TEXT NOT NULL,
    command_fingerprint TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('APPLIED','REJECTED')),
    first_seq INTEGER,
    last_seq INTEGER,
    result_json TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    received_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS commands_applied_idempotency
ON commands(idempotency_key)
WHERE status = 'APPLIED' AND idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    session_id TEXT,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    initiator_type TEXT NOT NULL,
    initiator_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    UNIQUE(mission_id, seq),
    FOREIGN KEY(command_id) REFERENCES commands(command_id)
);

CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'EVENTS_APPEND_ONLY');
END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'EVENTS_APPEND_ONLY');
END;

CREATE TABLE IF NOT EXISTS mission_projection (
    mission_id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    state_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS goal_projection (
    mission_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    PRIMARY KEY(mission_id, goal_id)
);

CREATE TABLE IF NOT EXISTS session_projection (
    mission_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    PRIMARY KEY(mission_id, session_id)
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def initialize(db_path: str | Path) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(1)")
    finally:
        conn.close()


def initialize_extensions(db_path: str | Path, registry: ExtensionRegistry, applied_at: str) -> None:
    if not registry.enabled:
        return
    conn = connect(db_path)
    try:
        with immediate_transaction(conn):
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS extension_migrations (
                    extension_id TEXT NOT NULL,
                    migration_version INTEGER NOT NULL,
                    migration_checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    PRIMARY KEY(extension_id, migration_version)
                )
                """
            )
            for manifest in registry.manifests:
                allowed_tables = set(manifest.projection_contribution.projection_tables)
                for step in registry.migration_steps(manifest):
                    row = conn.execute(
                        "SELECT migration_checksum FROM extension_migrations WHERE extension_id=? AND migration_version=?",
                        (manifest.extension_id, step.version),
                    ).fetchone()
                    if row is not None:
                        if row["migration_checksum"] != step.checksum:
                            raise RuntimeError(
                                "EXTENSION_MIGRATION_CHECKSUM_MISMATCH",
                                f"migration checksum changed: {manifest.extension_id}:{step.version}",
                            )
                        continue
                    before_schema = {
                        (item["type"], item["name"], item["tbl_name"]): item["sql"]
                        for item in conn.execute(
                            "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                        ).fetchall()
                    }
                    before = {name for (kind, name, _) in before_schema if kind == "table"}
                    _apply_extension_migration(conn, manifest, step, allowed_tables)
                    after_schema = {
                        (item["type"], item["name"], item["tbl_name"]): item["sql"]
                        for item in conn.execute(
                            "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                        ).fetchall()
                    }
                    after = {name for (kind, name, _) in after_schema if kind == "table"}
                    unexpected = (after - before) - allowed_tables
                    if unexpected:
                        raise RuntimeError(
                            "PROJECTION_TABLE_FORBIDDEN",
                            f"migration created undeclared tables: {sorted(unexpected)}",
                        )
                    protected = {
                        key: value
                        for key, value in before_schema.items()
                        if key[1] not in allowed_tables and key[2] not in allowed_tables
                    }
                    changed_protected = [
                        f"{kind}:{name}"
                        for (kind, name, table), definition in protected.items()
                        if after_schema.get((kind, name, table)) != definition
                    ]
                    unauthorized_objects = [
                        f"{kind}:{name}"
                        for (kind, name, table) in after_schema.keys() - before_schema.keys()
                        if name not in allowed_tables and table not in allowed_tables
                    ]
                    if changed_protected or unauthorized_objects:
                        raise RuntimeError(
                            "PROJECTION_TABLE_FORBIDDEN",
                            "extension migration changed objects outside its projection schema",
                            {
                                "changed": sorted(changed_protected),
                                "created": sorted(unauthorized_objects),
                            },
                        )
                    conn.execute(
                        "INSERT INTO extension_migrations(extension_id,migration_version,migration_checksum,applied_at) VALUES(?,?,?,?)",
                        (manifest.extension_id, step.version, step.checksum, applied_at),
                    )
                installed_tables = {
                    item["name"]
                    for item in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                }
                missing_tables = allowed_tables - installed_tables
                if missing_tables:
                    raise RuntimeError(
                        "EXTENSION_SCHEMA_MISMATCH",
                        f"extension projection tables are missing: {sorted(missing_tables)}",
                    )
    finally:
        conn.close()


@contextmanager
def immediate_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
