from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import (
    EXTENSION_ID, CaseExecutionAttempt, CaseReview, EvidenceRequirement, ExecutionReadinessAssessment,
    OracleEvaluation, OracleSpecification, PreconditionRequirement, PreconditionResolution, R34Error,
    R34State, R34ReuseReference, ReviewerContextSnapshot, TestDataRequirement, TestDataResolution,
    TestResult,
)


PROJECTION_TABLES = frozenset({
    "r34_reviewer_contexts", "r34_case_reviews", "r34_execution_readiness",
    "r34_precondition_requirements", "r34_precondition_resolutions",
    "r34_test_data_requirements", "r34_test_data_resolutions",
    "r34_oracle_specifications", "r34_evidence_requirements",
    "r34_case_execution_attempts", "r34_oracle_evaluations", "r34_test_results", "r34_reuses",
})

TABLE_ID_COLUMNS = {
    "r34_reviewer_contexts": "reviewer_context_id",
    "r34_case_reviews": "case_review_id",
    "r34_execution_readiness": "execution_readiness_id",
    "r34_precondition_requirements": "precondition_requirement_id",
    "r34_precondition_resolutions": "precondition_resolution_id",
    "r34_test_data_requirements": "test_data_requirement_id",
    "r34_test_data_resolutions": "test_data_resolution_id",
    "r34_oracle_specifications": "oracle_specification_id",
    "r34_evidence_requirements": "evidence_requirement_id",
    "r34_case_execution_attempts": "case_execution_attempt_id",
    "r34_oracle_evaluations": "oracle_evaluation_id",
    "r34_test_results": "test_result_id",
    "r34_reuses": "reuse_id",
}


MIGRATION_SQL = (
    """
    CREATE TABLE r34_reviewer_contexts (
        mission_id TEXT NOT NULL, reviewer_context_id TEXT NOT NULL, state_json TEXT NOT NULL, projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, reviewer_context_id)
    )
    """,
    """
    CREATE TABLE r34_case_reviews (
        mission_id TEXT NOT NULL, case_review_id TEXT NOT NULL, state_json TEXT NOT NULL, projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, case_review_id)
    )
    """,
    """
    CREATE TABLE r34_execution_readiness (
        mission_id TEXT NOT NULL, execution_readiness_id TEXT NOT NULL, state_json TEXT NOT NULL, projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, execution_readiness_id)
    )
    """,
    """
    CREATE TABLE r34_precondition_requirements (
        mission_id TEXT NOT NULL, precondition_requirement_id TEXT NOT NULL, state_json TEXT NOT NULL, projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, precondition_requirement_id)
    )
    """,
    """
    CREATE TABLE r34_precondition_resolutions (
        mission_id TEXT NOT NULL, precondition_resolution_id TEXT NOT NULL, state_json TEXT NOT NULL, projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, precondition_resolution_id)
    )
    """,
    """
    CREATE TABLE r34_test_data_requirements (
        mission_id TEXT NOT NULL, test_data_requirement_id TEXT NOT NULL, state_json TEXT NOT NULL, projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, test_data_requirement_id)
    )
    """,
    """
    CREATE TABLE r34_test_data_resolutions (
        mission_id TEXT NOT NULL, test_data_resolution_id TEXT NOT NULL, state_json TEXT NOT NULL, projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, test_data_resolution_id)
    )
    """,
    """
    CREATE TABLE r34_oracle_specifications (
        mission_id TEXT NOT NULL, oracle_specification_id TEXT NOT NULL, state_json TEXT NOT NULL, projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, oracle_specification_id)
    )
    """,
    """
    CREATE TABLE r34_evidence_requirements (
        mission_id TEXT NOT NULL, evidence_requirement_id TEXT NOT NULL, state_json TEXT NOT NULL, projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, evidence_requirement_id)
    )
    """,
    """
    CREATE TABLE r34_case_execution_attempts (
        mission_id TEXT NOT NULL, case_execution_attempt_id TEXT NOT NULL, state_json TEXT NOT NULL, projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, case_execution_attempt_id)
    )
    """,
    """
    CREATE TABLE r34_oracle_evaluations (
        mission_id TEXT NOT NULL, oracle_evaluation_id TEXT NOT NULL, state_json TEXT NOT NULL, projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, oracle_evaluation_id)
    )
    """,
    """
    CREATE TABLE r34_test_results (
        mission_id TEXT NOT NULL, test_result_id TEXT NOT NULL, state_json TEXT NOT NULL, projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, test_result_id)
    )
    """,
    """
    CREATE TABLE r34_reuses (
        mission_id TEXT NOT NULL, reuse_id TEXT NOT NULL, state_json TEXT NOT NULL, projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, reuse_id)
    )
    """,
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class R34MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),)


class R34ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        for table in sorted(PROJECTION_TABLES):
            if mission_id is None:
                conn.execute(f"DELETE FROM {table}")
            else:
                conn.execute(f"DELETE FROM {table} WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R34State):
            raise R34Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.4 projection input")
        self.clear(conn, composed.mission_id)
        rows = {
            "r34_reviewer_contexts": [(item.reviewer_context_id, item.to_dict()) for item in state.reviewer_contexts],
            "r34_case_reviews": [(item.case_review_id, item.to_dict()) for item in state.case_reviews],
            "r34_execution_readiness": [(item.execution_readiness_id, item.to_dict()) for item in state.execution_readiness],
            "r34_precondition_requirements": [(item.precondition_requirement_id, item.to_dict()) for item in state.precondition_requirements],
            "r34_precondition_resolutions": [(item.precondition_resolution_id, item.to_dict()) for item in state.precondition_resolutions],
            "r34_test_data_requirements": [(item.test_data_requirement_id, item.to_dict()) for item in state.test_data_requirements],
            "r34_test_data_resolutions": [(item.test_data_resolution_id, item.to_dict()) for item in state.test_data_resolutions],
            "r34_oracle_specifications": [(item.oracle_specification_id, item.to_dict()) for item in state.oracle_specifications],
            "r34_evidence_requirements": [(item.evidence_requirement_id, item.to_dict()) for item in state.evidence_requirements],
            "r34_case_execution_attempts": [(item.case_execution_attempt_id, item.to_dict()) for item in state.case_execution_attempts],
            "r34_oracle_evaluations": [(item.oracle_evaluation_id, item.to_dict()) for item in state.oracle_evaluations],
            "r34_test_results": [(item.test_result_id, item.to_dict()) for item in state.test_results],
            "r34_reuses": [(item.reuse_id, item.to_dict()) for item in state.reuses],
        }
        for table, values in rows.items():
            conn.executemany(
                f"INSERT INTO {table}(mission_id,{TABLE_ID_COLUMNS[table]},state_json,projection_seq) VALUES(?,?,?,?)",
                [(composed.mission_id, identity, canonical_json(payload), composed.seq) for identity, payload in values],
            )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R34State:
        def rows(table: str) -> list[dict[str, object]]:
            return [json.loads(row["state_json"]) for row in conn.execute(f"SELECT state_json FROM {table} WHERE mission_id=? ORDER BY state_json", (mission_id,))]
        return R34State(
            mission_id=mission_id,
            reviewer_contexts=tuple(ReviewerContextSnapshot.from_dict(item) for item in rows("r34_reviewer_contexts")),
            case_reviews=tuple(CaseReview.from_dict(item) for item in rows("r34_case_reviews")),
            execution_readiness=tuple(ExecutionReadinessAssessment.from_dict(item) for item in rows("r34_execution_readiness")),
            precondition_requirements=tuple(PreconditionRequirement.from_dict(item) for item in rows("r34_precondition_requirements")),
            precondition_resolutions=tuple(PreconditionResolution.from_dict(item) for item in rows("r34_precondition_resolutions")),
            test_data_requirements=tuple(TestDataRequirement.from_dict(item) for item in rows("r34_test_data_requirements")),
            test_data_resolutions=tuple(TestDataResolution.from_dict(item) for item in rows("r34_test_data_resolutions")),
            oracle_specifications=tuple(OracleSpecification.from_dict(item) for item in rows("r34_oracle_specifications")),
            evidence_requirements=tuple(EvidenceRequirement.from_dict(item) for item in rows("r34_evidence_requirements")),
            case_execution_attempts=tuple(CaseExecutionAttempt.from_dict(item) for item in rows("r34_case_execution_attempts")),
            oracle_evaluations=tuple(OracleEvaluation.from_dict(item) for item in rows("r34_oracle_evaluations")),
            test_results=tuple(TestResult.from_dict(item) for item in rows("r34_test_results")),
            reuses=tuple(R34ReuseReference.from_dict(item) for item in rows("r34_reuses")),
        )

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        row = conn.execute("SELECT seq FROM mission_projection WHERE mission_id=?", (mission_id,)).fetchone()
        return int(row[0]) if row is not None else None

    def verify(self, replayed_state: R34State, projected_state: R34State | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}
