from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import EXTENSION_ID, PROJECTION_TYPES, R37State, RemainingRiskItem, SemanticReuse, TestSufficiencyDecision
from .errors import R37Error


PROJECTION_TABLES = frozenset({"r37_entities"})
SCHEMA_SQL = """
CREATE TABLE r37_entities (
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
class R37MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (MigrationStep(1, canonical_sha256(SCHEMA_SQL), _apply_schema),)


def _rows(state: R37State) -> list[tuple[str, str, str, dict[str, Any], str]]:
    values: list[tuple[str, str, str, dict[str, Any], str]] = []
    for kind, items, id_name, digest_name in (
        ("REMAINING_RISK", state.remaining_risks, "risk_item_id", "risk_digest"),
        ("TEST_SUFFICIENCY_DECISION", state.decisions, "decision_id", "decision_digest"),
        ("SEMANTIC_REUSE", state.reuses, "reuse_id", "reuse_digest"),
    ):
        values.extend(
            (kind, str(getattr(item, id_name)), "1", item.to_dict(), str(getattr(item, digest_name)))
            for item in items
        )
    return sorted(values, key=lambda value: (value[0], value[1], value[2]))


def _decode(rows: list[sqlite3.Row], mission_id: str) -> R37State:
    values: dict[str, list[dict[str, Any]]] = {"REMAINING_RISK": [], "TEST_SUFFICIENCY_DECISION": [], "SEMANTIC_REUSE": []}
    digest_keys = {"REMAINING_RISK": "risk_digest", "TEST_SUFFICIENCY_DECISION": "decision_digest", "SEMANTIC_REUSE": "reuse_digest"}
    for row in rows:
        kind = str(row["entity_kind"])
        if kind not in values:
            raise R37Error("R3_7_PROJECTION_DRIFT", f"unknown R3.7 projection entity kind: {kind}")
        item = json.loads(row["state_json"])
        if item.get(digest_keys[kind]) != row["entity_digest"]:
            raise R37Error("R3_7_PROJECTION_DRIFT", f"projection digest mismatch for {kind}:{row['entity_id']}")
        values[kind].append(item)
    return R37State(
        mission_id=mission_id,
        decisions=tuple(TestSufficiencyDecision.from_dict(item) for item in values["TEST_SUFFICIENCY_DECISION"]),
        remaining_risks=tuple(RemainingRiskItem.from_dict(item) for item in values["REMAINING_RISK"]),
        reuses=tuple(SemanticReuse.from_dict(item) for item in values["SEMANTIC_REUSE"]),
    )


class R37ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        if mission_id is None:
            conn.execute("DELETE FROM r37_entities")
        else:
            conn.execute("DELETE FROM r37_entities WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R37State):
            raise R37Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.7 projection input")
        self.clear(conn, composed.mission_id)
        conn.executemany(
            "INSERT INTO r37_entities(mission_id,entity_kind,entity_id,entity_version,state_json,entity_digest,projection_seq) VALUES(?,?,?,?,?,?,?)",
            [
                (composed.mission_id, kind, entity_id, version, canonical_json(value), digest, composed.seq)
                for kind, entity_id, version, value, digest in _rows(state)
            ],
        )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R37State:
        rows = conn.execute(
            "SELECT entity_kind,entity_id,entity_version,state_json,entity_digest,projection_seq FROM r37_entities WHERE mission_id=? ORDER BY entity_kind,entity_id,entity_version",
            (mission_id,),
        ).fetchall()
        return _decode(rows, mission_id)

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        rows = conn.execute("SELECT DISTINCT projection_seq FROM r37_entities WHERE mission_id=?", (mission_id,)).fetchall()
        if not rows:
            return None
        values = {int(row[0]) for row in rows}
        if len(values) != 1:
            raise R37Error("R3_7_PROJECTION_DRIFT", "R3.7 projection contains multiple sequence values")
        return values.pop()

    def verify(self, replayed: R37State, projected: R37State | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed.to_dict())
        projected_hash = canonical_sha256(projected.to_dict()) if projected is not None else None
        return {
            "ok": projected is not None and replay_hash == projected_hash,
            "replayed_hash": replay_hash, "projected_hash": projected_hash,
            "decision_count": len(replayed.decisions), "remaining_risk_count": len(replayed.remaining_risks),
            "reuse_count": len(replayed.reuses),
        }


@dataclass(frozen=True)
class ProjectionEnvelope:
    projection_type: str
    scope: Mapping[str, Any]
    as_of_seq: int
    observed_at: str
    freshness: str
    source_cursors: Mapping[str, Any]
    payload: Mapping[str, Any]
    canonical: bool = False
    rebuildable: bool = True
    truth_source: str = "TYPED_UPSTREAM_PROJECTIONS"
    projection_digest: str | None = None

    def __post_init__(self) -> None:
        if self.projection_type not in PROJECTION_TYPES:
            raise R37Error("R3_7_SCHEMA_INVALID", f"invalid projection_type: {self.projection_type}")
        if self.canonical or not self.rebuildable:
            raise R37Error("R3_7_INDEPENDENT_REPORT_TRUTH_FORBIDDEN", "R3.7 operations projections are non-canonical and rebuildable")
        object.__setattr__(self, "scope", dict(self.scope))
        object.__setattr__(self, "source_cursors", dict(self.source_cursors))
        object.__setattr__(self, "payload", dict(self.payload))
        body = {
            "projection_type": self.projection_type, "scope": dict(self.scope), "as_of_seq": self.as_of_seq,
            "observed_at": self.observed_at, "freshness": self.freshness, "source_cursors": dict(self.source_cursors),
            "payload": dict(self.payload), "canonical": False, "rebuildable": True, "truth_source": self.truth_source,
        }
        expected = canonical_sha256(body)
        if self.projection_digest is not None and self.projection_digest != expected:
            raise R37Error("R3_7_PROJECTION_DRIFT", "projection digest does not match typed projection body")
        object.__setattr__(self, "projection_digest", expected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "projection_type": self.projection_type, "scope": dict(self.scope), "as_of_seq": self.as_of_seq,
            "observed_at": self.observed_at, "freshness": self.freshness, "source_cursors": dict(self.source_cursors),
            "payload": dict(self.payload), "canonical": False, "rebuildable": True,
            "truth_source": self.truth_source, "projection_digest": self.projection_digest,
        }


def _source_projection(source_payload: Mapping[str, Any] | None, key: str) -> list[Any]:
    if source_payload is None:
        return []
    value = source_payload.get(key) or []
    if not isinstance(value, (list, tuple)):
        raise R37Error("R3_7_SCHEMA_INVALID", f"projection source {key} must be an array")
    return [dict(item) if isinstance(item, Mapping) else item for item in value]


def build_operations_projection(
    state: R37State,
    projection_type: str,
    *,
    scope: Mapping[str, Any],
    as_of_seq: int,
    observed_at: str = "engineering",
    freshness: str = "CURRENT",
    source_cursors: Mapping[str, Any] | None = None,
    source_payload: Mapping[str, Any] | None = None,
) -> ProjectionEnvelope:
    if source_payload is not None:
        forbidden = {"llm_text", "report_text", "generated_report", "canonical_result"} & set(source_payload)
        if forbidden:
            raise R37Error("R3_7_INDEPENDENT_REPORT_TRUTH_FORBIDDEN", f"LLM/report text cannot be a projection truth source: {sorted(forbidden)}")
    source_payload = dict(source_payload or {})
    base = {
        "sufficiency_decisions": [item.to_dict() for item in state.decisions],
        "remaining_risk": [item.to_dict() for item in state.remaining_risks],
        "source_truth": "R3.1-R3.6/R1/R2_TYPED_PROJECTIONS",
        "report_rule": "REPORT_IS_PROJECTION_NOT_INDEPENDENT_TRUTH",
    }
    if projection_type == "COVERAGE_CENTER":
        base["coverage"] = _source_projection(source_payload, "coverage")
    elif projection_type == "TEST_CASE_CENTER":
        base["test_cases"] = _source_projection(source_payload, "test_cases")
    elif projection_type == "TEST_RUNS":
        base["test_runs"] = _source_projection(source_payload, "test_runs")
    elif projection_type == "EVIDENCE_LINKAGE":
        base["evidence_links"] = _source_projection(source_payload, "evidence_links")
    elif projection_type == "DEFECT_LINKAGE":
        base["defect_links"] = _source_projection(source_payload, "defect_links")
    elif projection_type == "TESTING_REPORT":
        for key in ("coverage", "test_cases", "test_runs", "evidence_links", "defect_links"):
            base[key] = _source_projection(source_payload, key)
        base["decision_values"] = [item.decision for item in state.decisions]
        base["decision_basis_refs"] = [
            {"ref_id": item.decision_id, "kind": "R3_7_TEST_SUFFICIENCY_DECISION", "digest": item.decision_digest or ""}
            for item in state.decisions
        ]
    return ProjectionEnvelope(
        projection_type=projection_type, scope=scope, as_of_seq=as_of_seq, observed_at=observed_at,
        freshness=freshness, source_cursors=source_cursors or {}, payload=base,
    )


def coverage_center(state: R37State, **kwargs: Any) -> ProjectionEnvelope:
    return build_operations_projection(state, "COVERAGE_CENTER", **kwargs)


def test_case_center(state: R37State, **kwargs: Any) -> ProjectionEnvelope:
    return build_operations_projection(state, "TEST_CASE_CENTER", **kwargs)


def test_runs(state: R37State, **kwargs: Any) -> ProjectionEnvelope:
    return build_operations_projection(state, "TEST_RUNS", **kwargs)


def evidence_linkage(state: R37State, **kwargs: Any) -> ProjectionEnvelope:
    return build_operations_projection(state, "EVIDENCE_LINKAGE", **kwargs)


def defect_linkage(state: R37State, **kwargs: Any) -> ProjectionEnvelope:
    return build_operations_projection(state, "DEFECT_LINKAGE", **kwargs)


def testing_report(state: R37State, **kwargs: Any) -> ProjectionEnvelope:
    return build_operations_projection(state, "TESTING_REPORT", **kwargs)
