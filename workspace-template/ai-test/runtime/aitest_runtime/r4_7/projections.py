from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import *
from .errors import R47Error


PROJECTION_TABLES = frozenset(
    {
        "r47_reconciliation_cases",
        "r47_source_observations",
        "r47_assessments",
        "r47_mappings",
        "r47_handoffs",
        "r47_receipts",
        "r47_operational_health",
    }
)

_SOURCE_OBSERVATIONS = "r47_source_observations"
_ASSESSMENTS = "r47_assessments"
_MAPPINGS = "r47_mappings"
_HANDOFFS = "r47_handoffs"
_RECEIPTS = "r47_receipts"
_CASES = "r47_reconciliation_cases"
_OPERATIONAL_HEALTH = "r47_operational_health"
_TABLES = (
    _SOURCE_OBSERVATIONS,
    _ASSESSMENTS,
    _MAPPINGS,
    _HANDOFFS,
    _RECEIPTS,
    _CASES,
    _OPERATIONAL_HEALTH,
)

MIGRATION_SQL = tuple(
    f"""CREATE TABLE {table} (
        mission_id TEXT NOT NULL,
        object_kind TEXT NOT NULL,
        object_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )""" for table in _TABLES
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class R47MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),)


def _case_key(value: ReconciliationCase) -> str:
    return value.case_id


class R47ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        for table in _TABLES:
            if mission_id is None:
                conn.execute(f"DELETE FROM {table}")
            else:
                conn.execute(f"DELETE FROM {table} WHERE mission_id=?", (mission_id,))

    @staticmethod
    def _insert(conn: sqlite3.Connection, table: str, kind: str, object_id: str, value: Any, seq: int, mission_id: str) -> None:
        state_json = canonical_json(value)
        conn.execute(
            f"INSERT INTO {table}(mission_id,object_kind,object_id,state_json,state_hash,projection_seq) VALUES(?,?,?,?,?,?)",
            (mission_id, kind, object_id, state_json, canonical_sha256(value), seq),
        )

    @staticmethod
    def _case_projection_value(state: R47State, item: ReconciliationCase) -> dict[str, Any]:
        value = item.to_dict()
        decision_ref = item.current_decision_ref
        if isinstance(decision_ref, dict):
            decision = state.decision(str(decision_ref.get("object_id", "")))
            if decision is not None:
                # Decision facts remain inside the derived case aggregate; no
                # independent decision projection is registered.
                value["current_decision"] = decision.to_dict()
        return value

    @staticmethod
    def _operational_health_values(state: R47State, seq: int, mission_id: str) -> tuple[tuple[str, str, dict[str, Any]], ...]:
        projection_set = sorted(PROJECTION_TABLES)
        projection_set_digest = canonical_sha256(projection_set)
        state_hash = canonical_sha256(state.to_dict())
        checkpoint = RebuildCheckpoint(
            owner_mission_id=mission_id,
            owner_stream_key=f"r4.7:{mission_id}",
            rebuild_checkpoint_id=f"r4.7:rebuild:{seq}",
            projection_set=tuple(projection_set),
            projection_set_digest=projection_set_digest,
            source_event_cursor=seq,
            attempt_id=f"r4.7:projection:{seq}",
            result="REBUILT",
            state_hash=state_hash,
            verification_result="PASS",
            as_of_seq=seq,
            created_seq=seq,
            created_at=f"projection-seq:{seq}",
        )
        return (
            (
                "SHADOW_TRUTH",
                "shadow_truth",
                {
                    "status": ShadowTruthStatus.IDENTIFIED.value,
                    "state": ShadowTruthStatus.NOT_CUT_OVER.value,
                    "source": "LEGACY_INPUT",
                },
            ),
            (
                "REBUILD",
                "rebuild",
                {
                    "status": "VERIFIED",
                    "state": "REBUILT_FROM_R1_EVENT_STREAM",
                    "checkpoint": checkpoint.to_dict(),
                    "projection_set": projection_set,
                    "projection_set_digest": projection_set_digest,
                    "source_event_cursor": seq,
                    "verification_result": "PASS",
                },
            ),
        )

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R47State):
            raise R47Error("R4_7_PROJECTION_INPUT_INVALID", "invalid R4.7 projection state")
        self.clear(conn, composed.mission_id)
        for item in sorted(state.observations, key=lambda value: (value.observation_id, value.revision)):
            self._insert(conn, _SOURCE_OBSERVATIONS, "legacy_source_observation", f"{item.observation_id}:{item.revision}", item.to_dict(), composed.seq, composed.mission_id)
        for item in sorted(state.assessments, key=lambda value: (value.assessment_id, value.revision)):
            self._insert(conn, _ASSESSMENTS, "reconciliation_assessment", f"{item.assessment_id}:{item.revision}", item.to_dict(), composed.seq, composed.mission_id)
        for item in sorted(state.mappings, key=lambda value: (value.mapping_id, value.revision)):
            self._insert(conn, _MAPPINGS, "legacy_canonical_mapping", f"{item.mapping_id}:{item.revision}", item.to_dict(), composed.seq, composed.mission_id)
        for item in sorted(state.handoffs, key=lambda value: (value.handoff_id, value.revision)):
            self._insert(conn, _HANDOFFS, "canonical_handoff_linkage", f"{item.handoff_id}:{item.revision}", item.to_dict(), composed.seq, composed.mission_id)
        for item in sorted(state.receipts, key=lambda value: (value.receipt_id, value.revision)):
            self._insert(conn, _RECEIPTS, "reconciliation_receipt", f"{item.receipt_id}:{item.revision}", item.to_dict(), composed.seq, composed.mission_id)
        for item in state.cases():
            self._insert(conn, _CASES, "reconciliation_case", item.case_id, self._case_projection_value(state, item), composed.seq, composed.mission_id)
        for kind, object_id, value in self._operational_health_values(state, composed.seq, composed.mission_id):
            self._insert(conn, _OPERATIONAL_HEALTH, kind, object_id, value, composed.seq, composed.mission_id)

    @staticmethod
    def _read_rows(conn: sqlite3.Connection, table: str, mission_id: str, cls: type[Any]) -> tuple[Any, ...]:
        values = []
        for row in conn.execute(f"SELECT state_json FROM {table} WHERE mission_id=?", (mission_id,)).fetchall():
            values.append(cls.from_dict(json.loads(row[0])))
        values.sort(
            key=lambda value: (
                int(getattr(value, "created_seq", 0)),
                int(getattr(value, "revision", 0)),
                str(next((getattr(value, name) for name in ("observation_id", "assessment_id", "mapping_id", "decision_id", "handoff_id", "receipt_id") if hasattr(value, name)), "")),
            )
        )
        return tuple(values)

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R47State:
        decisions = []
        for row in conn.execute(f"SELECT state_json FROM {_CASES} WHERE mission_id=?", (mission_id,)).fetchall():
            value = json.loads(row[0])
            decision = value.get("current_decision") if isinstance(value, dict) else None
            if isinstance(decision, dict):
                decisions.append(ReconciliationDecision.from_dict(decision))
        decisions.sort(key=lambda value: (value.created_seq, value.revision, value.decision_id))
        return R47State(
            mission_id,
            self._read_rows(conn, _SOURCE_OBSERVATIONS, mission_id, LegacySourceObservation),
            self._read_rows(conn, _ASSESSMENTS, mission_id, ReconciliationAssessment),
            self._read_rows(conn, _MAPPINGS, mission_id, LegacyCanonicalMapping),
            tuple(decisions),
            self._read_rows(conn, _HANDOFFS, mission_id, CanonicalHandoffLinkage),
            self._read_rows(conn, _RECEIPTS, mission_id, ReconciliationReceipt),
        )

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        row = conn.execute("SELECT MAX(seq) FROM events WHERE mission_id=?", (mission_id,)).fetchone()
        if row is None or row[0] is None:
            return None
        values = {int(row[0]) for table in PROJECTION_TABLES for row in conn.execute(f"SELECT projection_seq FROM {table} WHERE mission_id=?", (mission_id,)).fetchall()}
        return int(row[0]) if not values else next(iter(values)) if len(values) == 1 else -1

    def verify(self, replayed_state: R47State, projected_state: R47State | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}


__all__ = ["PROJECTION_TABLES", "R47MigrationContribution", "R47ProjectionContribution", "MIGRATION_SQL"]
