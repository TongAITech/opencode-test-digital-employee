from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import EXTENSION_ID, R46State
from .errors import R46Error


_TABLES = (
    "r46_candidate_revisions",
    "r46_candidate_dispositions",
    "r46_eligibility_assessments",
    "r46_promotion_requests",
    "r46_promotion_receipts",
    "r46_current_candidates",
)

MIGRATION_SQL = tuple(
    f"""CREATE TABLE {table} (
        mission_id TEXT NOT NULL,
        object_kind TEXT NOT NULL,
        object_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        {('candidate_id TEXT NOT NULL, revision INTEGER NOT NULL,' if table == 'r46_candidate_revisions' else '')}
        {('target_candidate_revision_id TEXT NOT NULL, disposition_kind TEXT NOT NULL,' if table == 'r46_candidate_dispositions' else '')}
        {('candidate_revision_id TEXT NOT NULL, status TEXT NOT NULL,' if table == 'r46_eligibility_assessments' else '')}
        {('candidate_revision_id TEXT NOT NULL, state TEXT NOT NULL,' if table == 'r46_promotion_requests' else '')}
        {('request_id TEXT NOT NULL, status TEXT NOT NULL,' if table == 'r46_promotion_receipts' else '')}
        {('current_lifecycle_state TEXT NOT NULL, current_validation_outcome TEXT NOT NULL,' if table == 'r46_current_candidates' else '')}
        PRIMARY KEY(mission_id, object_id)
    )""" for table in _TABLES
) + (
    "CREATE INDEX r46_candidate_revisions_lookup ON r46_candidate_revisions(mission_id, candidate_id, revision)",
    "CREATE INDEX r46_candidate_dispositions_lookup ON r46_candidate_dispositions(mission_id, target_candidate_revision_id, disposition_kind)",
    "CREATE INDEX r46_eligibility_assessments_lookup ON r46_eligibility_assessments(mission_id, candidate_revision_id, status)",
    "CREATE INDEX r46_promotion_requests_lookup ON r46_promotion_requests(mission_id, state, candidate_revision_id)",
    "CREATE INDEX r46_promotion_receipts_lookup ON r46_promotion_receipts(mission_id, request_id, status)",
    "CREATE INDEX r46_current_candidates_lookup ON r46_current_candidates(mission_id, current_lifecycle_state, current_validation_outcome)",
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class R46MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),)


class R46ProjectionContribution:
    projection_tables = frozenset(_TABLES)

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        for table in _TABLES:
            if mission_id is None:
                conn.execute(f"DELETE FROM {table}")
            else:
                conn.execute(f"DELETE FROM {table} WHERE mission_id=?", (mission_id,))

    @staticmethod
    def _insert(conn: sqlite3.Connection, table: str, kind: str, object_id: str, value: object, seq: int, mission_id: str, extra: tuple[tuple[str, Any], ...] = ()) -> None:
        state_json = canonical_json(value)
        columns = ["mission_id", "object_kind", "object_id", "state_json", "state_hash", "projection_seq"]
        values: list[Any] = [mission_id, kind, object_id, state_json, canonical_sha256(value), seq]
        for name, item in extra:
            columns.append(name)
            values.append(item)
        conn.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in values)})", tuple(values))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R46State):
            raise R46Error("R4_6_PROJECTION_INPUT_INVALID", "invalid R4.6 projection state")
        self.clear(conn, composed.mission_id)
        for item in sorted(state.candidate_revisions, key=lambda value: value.revision_id):
            self._insert(conn, _TABLES[0], "candidate_revision", item.revision_id, item.to_dict(), composed.seq, composed.mission_id, (("candidate_id", item.candidate_id), ("revision", item.revision)))
        for item in sorted(state.candidate_dispositions, key=lambda value: value.disposition_id):
            self._insert(conn, _TABLES[1], "candidate_disposition", item.disposition_id, item.to_dict(), composed.seq, composed.mission_id, (("target_candidate_revision_id", item.target_candidate_revision_ref.object_id), ("disposition_kind", item.disposition_kind.value)))
        for item in sorted(state.eligibility_assessments, key=lambda value: value.eligibility_id):
            self._insert(conn, _TABLES[2], "eligibility", item.eligibility_id, item.to_dict(), composed.seq, composed.mission_id, (("candidate_revision_id", item.candidate_revision_ref.object_id), ("status", item.status.value)))
        for item in sorted(state.promotion_requests, key=lambda value: value.request_id):
            self._insert(conn, _TABLES[3], "promotion_request", item.request_id, item.to_dict(), composed.seq, composed.mission_id, (("candidate_revision_id", item.candidate_revision_ref.object_id), ("state", item.state.value)))
        for item in sorted(state.promotion_receipts, key=lambda value: value.receipt_id):
            self._insert(conn, _TABLES[4], "promotion_receipt", item.receipt_id, item.to_dict(), composed.seq, composed.mission_id, (("request_id", item.request_ref.object_id), ("status", item.status.value)))
        candidates = {item.candidate_id: item for item in (state.candidate(candidate_id) for candidate_id in sorted({value.candidate_id for value in state.candidate_revisions})) if item is not None}
        for candidate_id, item in sorted(candidates.items()):
            self._insert(conn, _TABLES[5], "candidate_current", candidate_id, item.to_dict(), composed.seq, composed.mission_id, (("current_lifecycle_state", item.current_lifecycle_state.value if item.current_lifecycle_state else ""), ("current_validation_outcome", item.current_validation_outcome.value if item.current_validation_outcome else "")))

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R46State:
        from .contracts import R46CandidateDisposition, R46CandidateRevision, R46KnowledgePromotionReceipt, R46KnowledgePromotionRequest, R46PromotionEligibilityAssessment
        def read_table(table: str, cls: type[Any]) -> tuple[Any, ...]:
            return tuple(cls.from_dict(json.loads(row[0])) for row in conn.execute(f"SELECT state_json FROM {table} WHERE mission_id=? ORDER BY object_id", (mission_id,)).fetchall())
        return R46State(mission_id, read_table(_TABLES[0], R46CandidateRevision), read_table(_TABLES[2], R46PromotionEligibilityAssessment), read_table(_TABLES[3], R46KnowledgePromotionRequest), read_table(_TABLES[4], R46KnowledgePromotionReceipt), read_table(_TABLES[1], R46CandidateDisposition))

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        values = {int(row[0]) for table in _TABLES for row in conn.execute(f"SELECT projection_seq FROM {table} WHERE mission_id=?", (mission_id,)).fetchall()}
        return next(iter(values)) if len(values) == 1 else -1 if values else None

    def verify(self, replayed_state: R46State, projected_state: R46State | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}


__all__ = ["R46MigrationContribution", "R46ProjectionContribution", "MIGRATION_SQL"]
