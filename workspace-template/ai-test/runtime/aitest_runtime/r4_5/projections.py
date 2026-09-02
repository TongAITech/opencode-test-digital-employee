from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import EXTENSION_ID
from .errors import R45Error
from .reducer import R45State


_TABLES = (
    "r45_release_risk_assessments",
    "r45_release_readiness_assessments",
    "r45_release_wait_states",
    "r45_release_wake_resumes",
    "r45_readiness_dispositions",
)

MIGRATION_SQL = (
    """
    CREATE TABLE r45_release_risk_assessments (
        mission_id TEXT NOT NULL,
        object_kind TEXT NOT NULL,
        object_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )
    """,
    """
    CREATE TABLE r45_release_readiness_assessments (
        mission_id TEXT NOT NULL,
        object_kind TEXT NOT NULL,
        object_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )
    """,
    """
    CREATE TABLE r45_release_wait_states (
        mission_id TEXT NOT NULL,
        object_kind TEXT NOT NULL,
        object_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )
    """,
    """
    CREATE TABLE r45_release_wake_resumes (
        mission_id TEXT NOT NULL,
        object_kind TEXT NOT NULL,
        object_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )
    """,
    """
    CREATE TABLE r45_readiness_dispositions (
        mission_id TEXT NOT NULL,
        object_kind TEXT NOT NULL,
        object_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )
    """,
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        getattr(conn, "execute")(statement)


@dataclass(frozen=True)
class R45MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),
    )


class R45ProjectionContribution:
    projection_tables = frozenset(_TABLES)

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        for table in _TABLES:
            if mission_id is None:
                getattr(conn, "execute")(f"DELETE FROM {table}")
            else:
                getattr(conn, "execute")(f"DELETE FROM {table} WHERE mission_id=?", (mission_id,))

    @staticmethod
    def _insert(conn: sqlite3.Connection, table: str, kind: str, identity: str, value: object, seq: int, mission_id: str) -> None:
        state_json = canonical_json(value)
        getattr(conn, "execute")(
            f"INSERT INTO {table}(mission_id,object_kind,object_id,state_json,state_hash,projection_seq) VALUES(?,?,?,?,?,?)",
            (mission_id, kind, identity, state_json, canonical_sha256(value), seq),
        )

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R45State):
            raise R45Error("R4_5_PROJECTION_INPUT_INVALID", "invalid R4.5 projection input")
        self.clear(conn, composed.mission_id)
        for value in sorted(state.release_risk_assessments, key=lambda item: item.risk_assessment_id):
            self._insert(conn, _TABLES[0], "risk", value.risk_assessment_id, value.to_dict(), composed.seq, composed.mission_id)
        for value in sorted(state.release_readiness_assessments, key=lambda item: item.readiness_assessment_id):
            self._insert(conn, _TABLES[1], "readiness", value.readiness_assessment_id, value.to_dict(), composed.seq, composed.mission_id)
        for value in sorted(state.release_wait_states, key=lambda item: item.wait_id):
            self._insert(conn, _TABLES[2], "wait", value.wait_id, value.to_dict(), composed.seq, composed.mission_id)
        for kind, values, identity in (
            ("wake", state.wake_linkages, "wake_linkage_id"),
            ("eligibility", state.resume_eligibility_assessments, "eligibility_id"),
            ("intent", state.resume_intents, "resume_intent_id"),
            ("receipt", state.resume_receipts, "resume_receipt_id"),
        ):
            for value in sorted(values, key=lambda item: getattr(item, identity)):
                self._insert(conn, _TABLES[3], kind, getattr(value, identity), value.to_dict(), composed.seq, composed.mission_id)
        for value in sorted(state.readiness_dispositions, key=lambda item: item.disposition_id):
            self._insert(conn, _TABLES[4], "disposition", value.disposition_id, value.to_dict(), composed.seq, composed.mission_id)

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R45State:
        risks = tuple(
            __import__("aitest_runtime.r4_5.contracts", fromlist=["ReleaseRiskAssessment"]).ReleaseRiskAssessment.from_dict(json.loads(row["state_json"]))
            for row in getattr(conn, "execute")(f"SELECT state_json FROM {_TABLES[0]} WHERE mission_id=? ORDER BY object_id", (mission_id,)).fetchall()
        )
        readiness = tuple(
            __import__("aitest_runtime.r4_5.contracts", fromlist=["ReleaseReadinessAssessment"]).ReleaseReadinessAssessment.from_dict(json.loads(row["state_json"]))
            for row in getattr(conn, "execute")(f"SELECT state_json FROM {_TABLES[1]} WHERE mission_id=? ORDER BY object_id", (mission_id,)).fetchall()
        )
        waits = tuple(
            __import__("aitest_runtime.r4_5.contracts", fromlist=["ReleaseWaitState"]).ReleaseWaitState.from_dict(json.loads(row["state_json"]))
            for row in getattr(conn, "execute")(f"SELECT state_json FROM {_TABLES[2]} WHERE mission_id=? ORDER BY object_id", (mission_id,)).fetchall()
        )
        contracts = __import__("aitest_runtime.r4_5.contracts", fromlist=["WakeLinkage", "ResumeEligibilityAssessment", "R2ResumeIntent", "R2ResumeReceipt"])
        wake = []
        eligibility = []
        intents = []
        receipts = []
        for row in getattr(conn, "execute")(f"SELECT object_kind,state_json FROM {_TABLES[3]} WHERE mission_id=? ORDER BY object_kind,object_id", (mission_id,)).fetchall():
            raw = json.loads(row["state_json"])
            if row["object_kind"] == "wake":
                wake.append(contracts.WakeLinkage.from_dict(raw))
            elif row["object_kind"] == "eligibility":
                eligibility.append(contracts.ResumeEligibilityAssessment.from_dict(raw))
            elif row["object_kind"] == "intent":
                intents.append(contracts.R2ResumeIntent.from_dict(raw))
            elif row["object_kind"] == "receipt":
                receipts.append(contracts.R2ResumeReceipt.from_dict(raw))
        dispositions = tuple(
            __import__("aitest_runtime.r4_5.contracts", fromlist=["ReadinessDispositionLinkage"]).ReadinessDispositionLinkage.from_dict(json.loads(row["state_json"]))
            for row in getattr(conn, "execute")(f"SELECT state_json FROM {_TABLES[4]} WHERE mission_id=? ORDER BY object_id", (mission_id,)).fetchall()
        )
        return R45State(mission_id, risks, readiness, waits, tuple(wake), tuple(eligibility), tuple(intents), tuple(receipts), dispositions)

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        values = {
            int(row[0])
            for table in _TABLES
            for row in getattr(conn, "execute")(f"SELECT projection_seq FROM {table} WHERE mission_id=?", (mission_id,)).fetchall()
        }
        return next(iter(values)) if len(values) == 1 else -1 if values else None

    def verify(self, replayed_state: R45State, projected_state: R45State | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}


__all__ = ["R45MigrationContribution", "R45ProjectionContribution", "MIGRATION_SQL"]
