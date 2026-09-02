from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import EXTENSION_ID, PROJECTION_TABLES
from .errors import R44Error
from .reducer import R44State
from .contracts import (
    ExecutionLinkage,
    FixValidationAssessment,
    PostFixValidationCycle,
    SufficiencyHandoffReceipt,
    TargetedRegressionClosure,
    TargetedRegressionWorkSet,
)


MIGRATION_SQL = (
    "CREATE TABLE r44_validation_cycles (mission_id TEXT NOT NULL, object_id TEXT NOT NULL, object_version TEXT NOT NULL, cycle_digest TEXT NOT NULL, fix_link_id TEXT NOT NULL, fix_detection_id TEXT NOT NULL, quality_version_id TEXT NOT NULL, campaign_id TEXT NOT NULL, environment_id TEXT NOT NULL, deployment_id TEXT NOT NULL, state_json TEXT NOT NULL, entity_digest TEXT NOT NULL, state_hash TEXT NOT NULL, projection_seq INTEGER NOT NULL, PRIMARY KEY(mission_id, object_id))",
    "CREATE TABLE r44_targeted_regression_worksets (mission_id TEXT NOT NULL, object_id TEXT NOT NULL, object_version TEXT NOT NULL, cycle_id TEXT NOT NULL, fix_link_id TEXT NOT NULL, fix_detection_id TEXT NOT NULL, quality_version_id TEXT NOT NULL, campaign_id TEXT NOT NULL, state_json TEXT NOT NULL, entity_digest TEXT NOT NULL, state_hash TEXT NOT NULL, projection_seq INTEGER NOT NULL, PRIMARY KEY(mission_id, object_id))",
    "CREATE TABLE r44_execution_linkages (mission_id TEXT NOT NULL, object_id TEXT NOT NULL, object_version TEXT NOT NULL, cycle_id TEXT NOT NULL, workset_id TEXT, case_id TEXT NOT NULL, task_id TEXT, tool_execution_id TEXT, test_result_id TEXT, state_json TEXT NOT NULL, entity_digest TEXT NOT NULL, state_hash TEXT NOT NULL, projection_seq INTEGER NOT NULL, PRIMARY KEY(mission_id, object_id))",
    "CREATE TABLE r44_fix_validation_assessments (mission_id TEXT NOT NULL, object_id TEXT NOT NULL, object_version TEXT NOT NULL, cycle_id TEXT NOT NULL, fix_detection_id TEXT NOT NULL, environment_id TEXT NOT NULL, deployment_id TEXT NOT NULL, outcome TEXT NOT NULL, state_json TEXT NOT NULL, entity_digest TEXT NOT NULL, state_hash TEXT NOT NULL, projection_seq INTEGER NOT NULL, PRIMARY KEY(mission_id, object_id))",
    "CREATE TABLE r44_regression_closures (mission_id TEXT NOT NULL, object_id TEXT NOT NULL, object_version TEXT NOT NULL, cycle_id TEXT NOT NULL, workset_id TEXT NOT NULL, outcome TEXT NOT NULL, state_json TEXT NOT NULL, entity_digest TEXT NOT NULL, state_hash TEXT NOT NULL, projection_seq INTEGER NOT NULL, PRIMARY KEY(mission_id, object_id))",
    "CREATE TABLE r44_sufficiency_handoff_receipts (mission_id TEXT NOT NULL, object_id TEXT NOT NULL, object_version TEXT NOT NULL, cycle_id TEXT NOT NULL, workset_id TEXT NOT NULL, handoff_request_id TEXT NOT NULL, decision_id TEXT, request_status TEXT NOT NULL, state_json TEXT NOT NULL, entity_digest TEXT NOT NULL, state_hash TEXT NOT NULL, projection_seq INTEGER NOT NULL, PRIMARY KEY(mission_id, object_id))",
    "CREATE INDEX r44_cycle_by_fix_detection ON r44_validation_cycles(mission_id, fix_detection_id)",
    "CREATE INDEX r44_cycle_by_environment ON r44_validation_cycles(mission_id, environment_id, deployment_id)",
    "CREATE INDEX r44_workset_by_cycle ON r44_targeted_regression_worksets(mission_id, cycle_id)",
    "CREATE INDEX r44_linkage_by_case ON r44_execution_linkages(mission_id, case_id)",
    "CREATE INDEX r44_linkage_by_tool_execution ON r44_execution_linkages(mission_id, tool_execution_id)",
    "CREATE INDEX r44_assessment_by_cycle ON r44_fix_validation_assessments(mission_id, cycle_id)",
    "CREATE INDEX r44_closure_by_workset ON r44_regression_closures(mission_id, workset_id)",
    "CREATE INDEX r44_receipt_by_handoff ON r44_sufficiency_handoff_receipts(mission_id, handoff_request_id)",
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class R44MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),)


def _row(item: Any) -> tuple[str, str, str]:
    raw = item.to_dict()
    digest = canonical_sha256(raw)
    return canonical_json(raw), digest, digest


def _read(row: sqlite3.Row, cls: type[Any]) -> Any:
    raw = json.loads(row["state_json"])
    digest = canonical_sha256(raw)
    if row["entity_digest"] != digest or row["state_hash"] != digest:
        raise R44Error("R4_4_PROJECTION_TAMPERED", f"projection digest mismatch: {row['object_id']}")
    return cls.from_dict(raw)


class R44ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        for table in sorted(PROJECTION_TABLES):
            conn.execute(f"DELETE FROM {table}" if mission_id is None else f"DELETE FROM {table} WHERE mission_id=?", () if mission_id is None else (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R44State):
            raise R44Error("R4_4_PROJECTION_INPUT_INVALID", "invalid R4.4 extension state")
        self.clear(conn, composed.mission_id)
        for item in state.validation_cycles:
            raw, digest, state_hash = _row(item)
            conn.execute("INSERT INTO r44_validation_cycles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (composed.mission_id, item.cycle_id, "1", item.cycle_digest, item.fix_link_ref.object_id, item.fix_detection_ref.object_id, item.quality_version_ref.object_id, item.campaign_ref.object_id, item.target_environment_ref.object_id, item.target_deployment_ref.object_id, raw, digest, state_hash, composed.seq))
        for index, relation in enumerate(state.supersession_relations):
            raw = canonical_json({"_kind": "SUPERSESSION", **dict(relation)})
            digest = canonical_sha256(json.loads(raw))
            conn.execute("INSERT INTO r44_validation_cycles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (composed.mission_id, f"__supersession__:{index}:{digest}", "SUP", digest, "", "", "", "", "", "", raw, digest, digest, composed.seq))
        for item in state.regression_worksets:
            raw, digest, state_hash = _row(item)
            conn.execute("INSERT INTO r44_targeted_regression_worksets VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (composed.mission_id, item.workset_id, "1", item.cycle_ref.object_id, item.fix_link_ref.object_id, item.fix_detection_ref.object_id, item.quality_version_ref.object_id, item.campaign_ref.object_id, raw, digest, state_hash, composed.seq))
        for item in state.execution_linkages:
            raw, digest, state_hash = _row(item)
            task_id = item.r2_lineage_refs[0].object_id if item.r2_lineage_refs else None
            tool_id = item.tool_execution_refs[0].object_id if item.tool_execution_refs else None
            result_id = item.test_result_refs[0].object_id if item.test_result_refs else None
            conn.execute("INSERT INTO r44_execution_linkages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (composed.mission_id, item.linkage_id, "1", item.cycle_ref.object_id, item.workset_ref.object_id if item.workset_ref else None, item.case_ref.object_id, task_id, tool_id, result_id, raw, digest, state_hash, composed.seq))
        for item in state.fix_validation_assessments:
            raw, digest, state_hash = _row(item)
            conn.execute("INSERT INTO r44_fix_validation_assessments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (composed.mission_id, item.fix_validation_id, "1", item.cycle_ref.object_id, item.fix_detection_ref.object_id, item.target_environment_ref.object_id, item.target_deployment_ref.object_id, item.outcome.value, raw, digest, state_hash, composed.seq))
        for item in state.regression_closures:
            raw, digest, state_hash = _row(item)
            conn.execute("INSERT INTO r44_regression_closures VALUES(?,?,?,?,?,?,?,?,?,?)", (composed.mission_id, item.closure_id, "1", item.cycle_ref.object_id, item.workset_ref.object_id, item.outcome.value, raw, digest, state_hash, composed.seq))
        for item in state.sufficiency_handoff_receipts:
            raw, digest, state_hash = _row(item)
            conn.execute("INSERT INTO r44_sufficiency_handoff_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (composed.mission_id, item.receipt_id, "1", item.cycle_ref.object_id, item.workset_ref.object_id, item.handoff_request_id, item.decision_ref.object_id if item.decision_ref else None, item.request_status.value, raw, digest, state_hash, composed.seq))

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R44State:
        cycles: list[PostFixValidationCycle] = []
        relations: list[dict[str, Any]] = []
        for row in conn.execute("SELECT * FROM r44_validation_cycles WHERE mission_id=? ORDER BY object_id", (mission_id,)).fetchall():
            raw = json.loads(row["state_json"])
            digest = canonical_sha256(raw)
            if row["entity_digest"] != digest or row["state_hash"] != digest:
                raise R44Error("R4_4_PROJECTION_TAMPERED", f"projection digest mismatch: {row['object_id']}")
            if raw.get("_kind") == "SUPERSESSION":
                relations.append({key: value for key, value in raw.items() if key != "_kind"})
            else:
                cycles.append(PostFixValidationCycle.from_dict(raw))
        def read_many(table: str, cls: type[Any]) -> tuple[Any, ...]:
            return tuple(_read(row, cls) for row in conn.execute(f"SELECT * FROM {table} WHERE mission_id=? ORDER BY object_id", (mission_id,)).fetchall())
        return R44State(mission_id, tuple(cycles), read_many("r44_targeted_regression_worksets", TargetedRegressionWorkSet), read_many("r44_execution_linkages", ExecutionLinkage), read_many("r44_fix_validation_assessments", FixValidationAssessment), read_many("r44_regression_closures", TargetedRegressionClosure), read_many("r44_sufficiency_handoff_receipts", SufficiencyHandoffReceipt), tuple(relations))

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        values = {int(row[0]) for table in sorted(PROJECTION_TABLES) for row in conn.execute(f"SELECT projection_seq FROM {table} WHERE mission_id=?", (mission_id,)).fetchall()}
        if not values:
            return None
        return next(iter(values)) if len(values) == 1 else -1

    def verify(self, replayed_state: R44State, projected_state: R44State | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": projected_state is not None and replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash, "cycle_count": len(replayed_state.validation_cycles), "workset_count": len(replayed_state.regression_worksets), "linkage_count": len(replayed_state.execution_linkages), "assessment_count": len(replayed_state.fix_validation_assessments), "closure_count": len(replayed_state.regression_closures), "receipt_count": len(replayed_state.sufficiency_handoff_receipts)}


def rebuild_r44_projection(conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
    R44ProjectionContribution().apply(conn, composed)


__all__ = ["PROJECTION_TABLES", "MIGRATION_SQL", "R44MigrationContribution", "R44ProjectionContribution", "rebuild_r44_projection"]
