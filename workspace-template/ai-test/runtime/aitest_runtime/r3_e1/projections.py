from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import (
    EXTENSION_ID,
    KnowledgeConflict,
    KnowledgeFact,
    KnowledgeFreshness,
    KnowledgeRelation,
    KnowledgeScopeIdentity,
    KnowledgeSourceRef,
    KnowledgeVersion,
    R3E1Error,
    R3E1State,
    _proof_for_status,
)


PROJECTION_TABLES = frozenset({
    "r3e1_facts",
    "r3e1_versions",
    "r3e1_source_refs",
    "r3e1_conflicts",
    "r3e1_freshness",
    "r3e1_relations",
    "r3e1_origin_records",
})

MIGRATION_SQL = (
    """
    CREATE TABLE r3e1_facts (
        scope_key TEXT NOT NULL,
        project_id TEXT NOT NULL,
        environment_id TEXT NOT NULL,
        version_scope TEXT NOT NULL,
        fact_id TEXT NOT NULL,
        current_version_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        origin_missions_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(scope_key, fact_id)
    )
    """,
    """
    CREATE TABLE r3e1_versions (
        scope_key TEXT NOT NULL,
        project_id TEXT NOT NULL,
        environment_id TEXT NOT NULL,
        version_scope TEXT NOT NULL,
        version_id TEXT NOT NULL,
        fact_id TEXT NOT NULL,
        version_number INTEGER NOT NULL,
        status TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        state_json TEXT NOT NULL,
        origin_missions_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(scope_key, version_id)
    )
    """,
    """
    CREATE TABLE r3e1_source_refs (
        scope_key TEXT NOT NULL,
        project_id TEXT NOT NULL,
        environment_id TEXT NOT NULL,
        version_scope TEXT NOT NULL,
        source_ref_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        origin_missions_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(scope_key, source_ref_id)
    )
    """,
    """
    CREATE TABLE r3e1_conflicts (
        scope_key TEXT NOT NULL,
        project_id TEXT NOT NULL,
        environment_id TEXT NOT NULL,
        version_scope TEXT NOT NULL,
        conflict_id TEXT NOT NULL,
        fact_id TEXT NOT NULL,
        status TEXT NOT NULL,
        state_json TEXT NOT NULL,
        origin_missions_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(scope_key, conflict_id)
    )
    """,
    """
    CREATE TABLE r3e1_freshness (
        scope_key TEXT NOT NULL,
        project_id TEXT NOT NULL,
        environment_id TEXT NOT NULL,
        version_scope TEXT NOT NULL,
        freshness_id TEXT NOT NULL,
        target_version_id TEXT NOT NULL,
        result TEXT NOT NULL,
        state_json TEXT NOT NULL,
        origin_missions_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(scope_key, freshness_id)
    )
    """,
    """
    CREATE TABLE r3e1_relations (
        scope_key TEXT NOT NULL,
        project_id TEXT NOT NULL,
        environment_id TEXT NOT NULL,
        version_scope TEXT NOT NULL,
        relation_id TEXT NOT NULL,
        relation_digest TEXT NOT NULL,
        status TEXT NOT NULL,
        state_json TEXT NOT NULL,
        origin_missions_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(scope_key, relation_id)
    )
    """,
    """
    CREATE TABLE r3e1_origin_records (
        mission_id TEXT NOT NULL,
        entity_kind TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        entity_version TEXT NOT NULL,
        state_json TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, entity_kind, entity_id, entity_version)
    )
    """,
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class R3E1MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),
    )


def _scope_fields(scope: KnowledgeScopeIdentity) -> tuple[str, str, str, str]:
    return scope.key, scope.project_id, scope.environment_id, scope.version_scope


def _decode(value: str) -> dict[str, Any]:
    return json.loads(value)


def _origins(value: str | None, mission_id: str) -> list[str]:
    existing = list(json.loads(value) if value else [])
    if mission_id not in existing:
        existing.append(mission_id)
    return sorted(set(existing))


def _canonical_identity(value: Mapping[str, Any], key: str) -> dict[str, Any]:
    result = dict(value)
    result.pop("origin_missions", None)
    result.pop("projection_seq", None)
    return result


def _same_identity(existing: Mapping[str, Any], incoming: Mapping[str, Any], key: str) -> bool:
    return canonical_sha256(_canonical_identity(existing, key)) == canonical_sha256(
        _canonical_identity(incoming, key)
    )


def _insert_origin(
    conn: sqlite3.Connection,
    mission_id: str,
    entity_kind: str,
    entity_id: str,
    entity_version: str,
    value: Mapping[str, Any],
    projection_seq: int,
) -> None:
    conn.execute(
        """
        INSERT INTO r3e1_origin_records(mission_id,entity_kind,entity_id,entity_version,state_json,projection_seq)
        VALUES(?,?,?,?,?,?)
        """,
        (mission_id, entity_kind, entity_id, entity_version, canonical_json(value), projection_seq),
    )


def _upsert(
    conn: sqlite3.Connection,
    table: str,
    identity_column: str,
    identity_value: str,
    value: Mapping[str, Any],
    scope: KnowledgeScopeIdentity,
    mission_id: str,
    projection_seq: int,
    *,
    mutable_status: bool = False,
) -> None:
    scope_key, project_id, environment_id, version_scope = _scope_fields(scope)
    row = conn.execute(
        f"SELECT state_json,origin_missions_json FROM {table} WHERE scope_key=? AND {identity_column}=?",
        (scope_key, identity_value),
    ).fetchone()
    incoming = dict(value)
    if row is None:
        origins = [mission_id]
        common = (scope_key, project_id, environment_id, version_scope, identity_value)
        state_values = (canonical_json(incoming), canonical_json(origins), projection_seq)
        if table == "r3e1_facts":
            conn.execute(
                "INSERT INTO r3e1_facts(scope_key,project_id,environment_id,version_scope,fact_id,current_version_id,state_json,origin_missions_json,projection_seq) VALUES(?,?,?,?,?,?,?,?,?)",
                common + (incoming["current_version_id"],) + state_values,
            )
        elif table == "r3e1_versions":
            conn.execute(
                "INSERT INTO r3e1_versions(scope_key,project_id,environment_id,version_scope,version_id,fact_id,version_number,status,fingerprint,state_json,origin_missions_json,projection_seq) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                common + (incoming["fact_id"], incoming["version_number"], incoming["status"], incoming["fingerprint"]) + state_values,
            )
        elif table == "r3e1_source_refs":
            conn.execute(
                "INSERT INTO r3e1_source_refs(scope_key,project_id,environment_id,version_scope,source_ref_id,state_json,origin_missions_json,projection_seq) VALUES(?,?,?,?,?,?,?,?)",
                common + state_values,
            )
        elif table == "r3e1_conflicts":
            conn.execute(
                "INSERT INTO r3e1_conflicts(scope_key,project_id,environment_id,version_scope,conflict_id,fact_id,status,state_json,origin_missions_json,projection_seq) VALUES(?,?,?,?,?,?,?,?,?,?)",
                common + (incoming["fact_id"], incoming["status"]) + state_values,
            )
        elif table == "r3e1_freshness":
            conn.execute(
                "INSERT INTO r3e1_freshness(scope_key,project_id,environment_id,version_scope,freshness_id,target_version_id,result,state_json,origin_missions_json,projection_seq) VALUES(?,?,?,?,?,?,?,?,?,?)",
                common + (incoming["target_version_id"], incoming["result"]) + state_values,
            )
        elif table == "r3e1_relations":
            conn.execute(
                "INSERT INTO r3e1_relations(scope_key,project_id,environment_id,version_scope,relation_id,relation_digest,status,state_json,origin_missions_json,projection_seq) VALUES(?,?,?,?,?,?,?,?,?,?)",
                common + (incoming["relation_digest"], incoming["status"]) + state_values,
            )
        else:
            raise R3E1Error("R3_E1_SCHEMA_INVALID", f"unsupported projection table: {table}")
        return

    existing = _decode(row["state_json"])
    if table == "r3e1_versions":
        immutable_fields = ("version_id", "fact_id", "version_number", "payload", "scope_identity", "payload_digest", "fingerprint")
        if any(existing.get(field) != incoming.get(field) for field in immutable_fields):
            raise R3E1Error("R3_E1_VERSION_IMMUTABLE", f"version identity conflicts across origins: {identity_value}")
        if mutable_status:
            incoming = dict(existing, status=incoming["status"])
            incoming["verification_proof"] = incoming.get("verification_proof") or existing.get("verification_proof") or {}
            incoming["source_ref_ids"] = sorted(set(existing.get("source_ref_ids", ())) | set(incoming.get("source_ref_ids", ())))
    elif table == "r3e1_facts":
        existing_immutable = dict(existing)
        incoming_immutable = dict(incoming)
        existing_immutable.pop("current_version_id", None)
        incoming_immutable.pop("current_version_id", None)
        if canonical_sha256(existing_immutable) != canonical_sha256(incoming_immutable):
            raise R3E1Error("R3_E1_VERSION_IMMUTABLE", f"canonical fact conflicts across origins: {identity_value}")
    elif not _same_identity(existing, incoming, identity_value):
        raise R3E1Error("R3_E1_VERSION_IMMUTABLE", f"canonical {identity_column} conflicts across origins: {identity_value}")
    merged_origins = _origins(row["origin_missions_json"], mission_id)
    set_values: list[Any] = []
    if table == "r3e1_facts":
        existing_version = conn.execute(
            "SELECT version_number FROM r3e1_versions WHERE scope_key=? AND version_id=?",
            (scope_key, existing["current_version_id"]),
        ).fetchone()
        incoming_version = conn.execute(
            "SELECT version_number FROM r3e1_versions WHERE scope_key=? AND version_id=?",
            (scope_key, incoming["current_version_id"]),
        ).fetchone()
        if existing_version is not None and incoming_version is not None:
            current_version_id = (
                incoming["current_version_id"]
                if int(incoming_version["version_number"]) >= int(existing_version["version_number"])
                else existing["current_version_id"]
            )
        else:
            current_version_id = incoming["current_version_id"]
        incoming["current_version_id"] = current_version_id
        set_values = [incoming["fact_id"], current_version_id]
        updates = "fact_id=?,current_version_id=?"
    elif table == "r3e1_versions":
        set_values = [incoming["fact_id"], incoming["version_number"], incoming["status"], incoming["fingerprint"]]
        updates = "fact_id=?,version_number=?,status=?,fingerprint=?"
    elif table == "r3e1_source_refs":
        updates = "source_ref_id=source_ref_id"
    elif table == "r3e1_conflicts":
        set_values = [incoming["fact_id"], incoming["status"]]
        updates = "fact_id=?,status=?"
    elif table == "r3e1_freshness":
        set_values = [incoming["target_version_id"], incoming["result"]]
        updates = "target_version_id=?,result=?"
    else:
        set_values = [incoming["relation_digest"], incoming["status"]]
        updates = "relation_digest=?,status=?"
    conn.execute(
        f"""
        UPDATE {table}
        SET {updates}, state_json=?, origin_missions_json=?, projection_seq=?
        WHERE scope_key=? AND {identity_column}=?
        """,
        (*set_values, canonical_json(incoming), canonical_json(merged_origins), projection_seq, scope_key, identity_value),
    )


def _write_state_origin(conn: sqlite3.Connection, state: R3E1State, projection_seq: int) -> None:
    for item in state.facts:
        _insert_origin(conn, state.mission_id, "FACT", item.fact_id, item.current_version_id, item.to_dict(), projection_seq)
    for item in state.versions:
        _insert_origin(conn, state.mission_id, "VERSION", item.version_id, str(item.version_number), item.to_dict(), projection_seq)
    for item in state.source_refs:
        _insert_origin(conn, state.mission_id, "SOURCE_REF", item.source_ref_id, "1", item.to_dict(), projection_seq)
    for item in state.conflicts:
        _insert_origin(conn, state.mission_id, "CONFLICT", item.conflict_id, "1", item.to_dict(), projection_seq)
    for item in state.freshness:
        _insert_origin(conn, state.mission_id, "FRESHNESS", item.freshness_id, "1", item.to_dict(), projection_seq)
    for item in state.relations:
        _insert_origin(conn, state.mission_id, "RELATION", item.relation_id, str(item.relation_version), item.to_dict(), projection_seq)
    for index, item in enumerate(state.lifecycle_events, 1):
        _insert_origin(
            conn,
            state.mission_id,
            "LIFECYCLE",
            str(item["version_id"]),
            str(item.get("event_seq") or index),
            item,
            projection_seq,
        )


def _apply_lifecycle(
    conn: sqlite3.Connection,
    scope: KnowledgeScopeIdentity,
    lifecycle: Mapping[str, Any],
    mission_id: str,
    projection_seq: int,
) -> None:
    scope_key = scope.key
    row = conn.execute(
        "SELECT state_json FROM r3e1_versions WHERE scope_key=? AND version_id=?",
        (scope_key, lifecycle["version_id"]),
    ).fetchone()
    if row is None:
        raise R3E1Error("R3_E1_VERSION_IMMUTABLE", f"lifecycle references missing canonical version: {lifecycle['version_id']}")
    version = KnowledgeVersion.from_dict(_decode(row["state_json"]))
    if version.status == lifecycle["to_status"]:
        return
    if version.status != lifecycle["from_status"]:
        raise R3E1Error("R3_E1_STATUS_TRANSITION_INVALID", "canonical lifecycle state differs from event from_status")
    # Lifecycle evidence is an append-only proof record.  The version's
    # source_ref_ids are immutable and a changed source set requires a new
    # KnowledgeVersion, per the frozen contract.
    updated = replace(
        version,
        status=lifecycle["to_status"],
        verification_proof=dict(lifecycle.get("proof") or {}),
    )
    _proof_for_status(updated.status, updated.source_ref_ids, updated.verification_proof)
    _upsert(
        conn,
        "r3e1_versions",
        "version_id",
        updated.version_id,
        updated.to_dict(),
        scope,
        mission_id,
        projection_seq,
        mutable_status=True,
    )


class R3E1ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        if mission_id is None:
            for table in sorted(PROJECTION_TABLES):
                conn.execute(f"DELETE FROM {table}")
        else:
            conn.execute("DELETE FROM r3e1_origin_records WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R3E1State):
            raise R3E1Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.E1 projection input")
        self.clear(conn, composed.mission_id)
        _write_state_origin(conn, state, composed.seq)

        for source in sorted(state.source_refs, key=lambda value: value.source_ref_id):
            _upsert(
                conn, "r3e1_source_refs", "source_ref_id", source.source_ref_id,
                source.to_dict(), source.scope_identity, composed.mission_id, composed.seq,
            )
        for version in sorted(state.versions, key=lambda value: value.version_id):
            _upsert(
                conn, "r3e1_versions", "version_id", version.version_id,
                version.to_dict(), version.scope_identity, composed.mission_id, composed.seq,
                mutable_status=True,
            )
        for fact in sorted(state.facts, key=lambda value: value.fact_id):
            _upsert(
                conn, "r3e1_facts", "fact_id", fact.fact_id,
                fact.to_dict(), fact.scope_identity, composed.mission_id, composed.seq,
            )
        for conflict in sorted(state.conflicts, key=lambda value: value.conflict_id):
            _upsert(
                conn, "r3e1_conflicts", "conflict_id", conflict.conflict_id,
                conflict.to_dict(), conflict.scope_identity, composed.mission_id, composed.seq,
            )
        for freshness in sorted(state.freshness, key=lambda value: value.freshness_id):
            _upsert(
                conn, "r3e1_freshness", "freshness_id", freshness.freshness_id,
                freshness.to_dict(), freshness.scope_identity, composed.mission_id, composed.seq,
            )
        for relation in sorted(state.relations, key=lambda value: value.relation_id):
            _upsert(
                conn, "r3e1_relations", "relation_id", relation.relation_id,
                relation.to_dict(), relation.scope_identity, composed.mission_id, composed.seq,
            )
        for lifecycle in state.lifecycle_events:
            scope = KnowledgeScopeIdentity.from_dict(lifecycle["scope_identity"])
            if lifecycle["version_id"] not in {item.version_id for item in state.versions}:
                _apply_lifecycle(conn, scope, lifecycle, composed.mission_id, composed.seq)

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R3E1State:
        rows = conn.execute(
            """
            SELECT entity_kind,state_json FROM r3e1_origin_records
            WHERE mission_id=?
            ORDER BY entity_kind,entity_id,entity_version
            """,
            (mission_id,),
        ).fetchall()
        values: dict[str, list[Any]] = {
            "FACT": [], "VERSION": [], "SOURCE_REF": [], "CONFLICT": [],
            "FRESHNESS": [], "RELATION": [], "LIFECYCLE": [],
        }
        for row in rows:
            values[row["entity_kind"]].append(_decode(row["state_json"]))
        return R3E1State(
            mission_id=mission_id,
            facts=tuple(KnowledgeFact.from_dict(item) for item in values["FACT"]),
            versions=tuple(KnowledgeVersion.from_dict(item) for item in values["VERSION"]),
            source_refs=tuple(KnowledgeSourceRef.from_dict(item) for item in values["SOURCE_REF"]),
            conflicts=tuple(KnowledgeConflict.from_dict(item) for item in values["CONFLICT"]),
            freshness=tuple(KnowledgeFreshness.from_dict(item) for item in values["FRESHNESS"]),
            relations=tuple(KnowledgeRelation.from_dict(item) for item in values["RELATION"]),
            lifecycle_events=tuple(values["LIFECYCLE"]),
        )

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        row = conn.execute(
            "SELECT DISTINCT projection_seq FROM r3e1_origin_records WHERE mission_id=?",
            (mission_id,),
        ).fetchall()
        if not row:
            return None
        values = {int(item[0]) for item in row}
        return next(iter(values)) if len(values) == 1 else -1

    def verify(self, replayed_state: R3E1State, projected_state: R3E1State | None) -> dict[str, Any]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {
            "ok": replay_hash == projection_hash,
            "replay_hash": replay_hash,
            "projection_hash": projection_hash,
        }


def scope_rows(conn: sqlite3.Connection, scope: KnowledgeScopeIdentity) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for table in (
        "r3e1_facts", "r3e1_versions", "r3e1_source_refs",
        "r3e1_conflicts", "r3e1_freshness", "r3e1_relations",
    ):
        result[table] = [
            _decode(row["state_json"])
            for row in conn.execute(
                f"SELECT state_json FROM {table} WHERE scope_key=? ORDER BY state_json",
                (scope.key,),
            )
        ]
    return result
