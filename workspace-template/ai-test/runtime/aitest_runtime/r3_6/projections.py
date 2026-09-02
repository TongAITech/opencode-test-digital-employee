from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import (
    EXTENSION_ID,
    R36State,
    TestAnomaly,
    DefectCandidate,
    EvidenceDeepeningReceipt,
    EvidenceAssessment,
    CrossSourceCorrelation,
    ReproducibilityAssessment,
    FalsePositiveAssessment,
    DefectAssessment,
    RCARecord,
    InvestigationCheckpoint,
    SemanticReuse,
)
from .errors import R36Error


PROJECTION_TABLES = frozenset({"r3_6_entities"})
SCHEMA_SQL = """
CREATE TABLE r3_6_entities (
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
class R36MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(SCHEMA_SQL), _apply_schema),
    )


def _rows(state: R36State) -> list[tuple[str, str, str, dict[str, Any], str]]:
    values: list[tuple[str, str, str, dict[str, Any], str]] = []
    entries = (
        ("TEST_ANOMALY", state.anomalies, "anomaly_id", "anomaly_digest"),
        ("DEFECT_CANDIDATE", state.candidates, "candidate_id", "candidate_digest"),
        ("EVIDENCE_DEEPENING", state.deepenings, "deepening_id", "deepening_digest"),
        ("EVIDENCE_ASSESSMENT", state.evidence_assessments, "assessment_id", "assessment_digest"),
        ("CROSS_SOURCE_CORRELATION", state.correlations, "correlation_id", "correlation_digest"),
        ("REPRODUCIBILITY", state.reproducibility_assessments, "reproducibility_id", "reproducibility_digest"),
        ("FALSE_POSITIVE", state.false_positive_assessments, "false_positive_id", "false_positive_digest"),
        ("DEFECT_ASSESSMENT", state.defect_assessments, "assessment_id", "defect_assessment_digest"),
        ("RCA", state.rca_records, "rca_id", "rca_digest"),
        ("CHECKPOINT", state.checkpoints, "checkpoint_id", "checkpoint_digest"),
        ("REUSE", state.reuses, "reuse_id", "reuse_digest"),
    )
    for kind, items, id_name, digest_name in entries:
        values.extend(
            (kind, str(getattr(item, id_name)), "1", item.to_dict(), str(getattr(item, digest_name)))
            for item in items
        )
    return sorted(values, key=lambda value: (value[0], value[1], value[2]))


def _decode(rows: list[sqlite3.Row], mission_id: str) -> R36State:
    values: dict[str, list[dict[str, Any]]] = {
        "TEST_ANOMALY": [], "DEFECT_CANDIDATE": [], "EVIDENCE_DEEPENING": [],
        "EVIDENCE_ASSESSMENT": [], "CROSS_SOURCE_CORRELATION": [], "REPRODUCIBILITY": [],
        "FALSE_POSITIVE": [], "DEFECT_ASSESSMENT": [], "RCA": [], "CHECKPOINT": [], "REUSE": [],
    }
    digest_keys = {
        "TEST_ANOMALY": "anomaly_digest", "DEFECT_CANDIDATE": "candidate_digest",
        "EVIDENCE_DEEPENING": "deepening_digest", "EVIDENCE_ASSESSMENT": "assessment_digest",
        "CROSS_SOURCE_CORRELATION": "correlation_digest", "REPRODUCIBILITY": "reproducibility_digest",
        "FALSE_POSITIVE": "false_positive_digest", "DEFECT_ASSESSMENT": "defect_assessment_digest",
        "RCA": "rca_digest", "CHECKPOINT": "checkpoint_digest", "REUSE": "reuse_digest",
    }
    for row in rows:
        kind = str(row["entity_kind"])
        if kind not in values:
            raise R36Error("R3_6_PROJECTION_DRIFT", f"unknown R3.6 projection entity kind: {kind}")
        item = json.loads(row["state_json"])
        if item.get(digest_keys[kind]) != row["entity_digest"]:
            raise R36Error("R3_6_PROJECTION_DRIFT", f"projection digest mismatch for {kind}:{row['entity_id']}")
        values[kind].append(item)
    return R36State(
        mission_id=mission_id,
        anomalies=tuple(TestAnomaly.from_dict(item) for item in values["TEST_ANOMALY"]),
        candidates=tuple(DefectCandidate.from_dict(item) for item in values["DEFECT_CANDIDATE"]),
        deepenings=tuple(EvidenceDeepeningReceipt.from_dict(item) for item in values["EVIDENCE_DEEPENING"]),
        evidence_assessments=tuple(EvidenceAssessment.from_dict(item) for item in values["EVIDENCE_ASSESSMENT"]),
        correlations=tuple(CrossSourceCorrelation.from_dict(item) for item in values["CROSS_SOURCE_CORRELATION"]),
        reproducibility_assessments=tuple(ReproducibilityAssessment.from_dict(item) for item in values["REPRODUCIBILITY"]),
        false_positive_assessments=tuple(FalsePositiveAssessment.from_dict(item) for item in values["FALSE_POSITIVE"]),
        defect_assessments=tuple(DefectAssessment.from_dict(item) for item in values["DEFECT_ASSESSMENT"]),
        rca_records=tuple(RCARecord.from_dict(item) for item in values["RCA"]),
        checkpoints=tuple(InvestigationCheckpoint.from_dict(item) for item in values["CHECKPOINT"]),
        reuses=tuple(SemanticReuse.from_dict(item) for item in values["REUSE"]),
    )


class R36ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        if mission_id is None:
            conn.execute("DELETE FROM r3_6_entities")
        else:
            conn.execute("DELETE FROM r3_6_entities WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R36State):
            raise R36Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.6 projection input")
        self.clear(conn, composed.mission_id)
        conn.executemany(
            """
            INSERT INTO r3_6_entities(
                mission_id,entity_kind,entity_id,entity_version,state_json,entity_digest,projection_seq
            ) VALUES(?,?,?,?,?,?,?)
            """,
            [
                (composed.mission_id, kind, entity_id, version, canonical_json(value), digest, composed.seq)
                for kind, entity_id, version, value, digest in _rows(state)
            ],
        )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R36State:
        rows = conn.execute(
            """
            SELECT entity_kind,entity_id,entity_version,state_json,entity_digest,projection_seq
            FROM r3_6_entities WHERE mission_id=? ORDER BY entity_kind,entity_id,entity_version
            """,
            (mission_id,),
        ).fetchall()
        return _decode(rows, mission_id)

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        rows = conn.execute("SELECT DISTINCT projection_seq FROM r3_6_entities WHERE mission_id=?", (mission_id,)).fetchall()
        if not rows:
            return None
        values = {int(row[0]) for row in rows}
        if len(values) != 1:
            raise R36Error("R3_6_PROJECTION_DRIFT", "R3.6 projection contains multiple sequence values")
        return values.pop()

    def verify(self, replayed: R36State, projected: R36State | None) -> dict[str, object]:
        replayed_hash = canonical_sha256(replayed.to_dict())
        projected_hash = canonical_sha256(projected.to_dict()) if projected is not None else None
        return {
            "ok": projected is not None and replayed_hash == projected_hash,
            "replayed_hash": replayed_hash,
            "projected_hash": projected_hash,
            "entity_count": sum(len(items) for items in (
                replayed.anomalies, replayed.candidates, replayed.deepenings,
                replayed.evidence_assessments, replayed.correlations,
                replayed.reproducibility_assessments, replayed.false_positive_assessments,
                replayed.defect_assessments, replayed.rca_records, replayed.checkpoints, replayed.reuses,
            )),
        }
