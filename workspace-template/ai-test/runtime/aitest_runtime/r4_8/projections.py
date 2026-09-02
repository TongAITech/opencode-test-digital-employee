from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from typing import Any

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import EXTENSION_ID, R48State
from .reducer import _state_digest


PROJECTION_TABLES = frozenset(
    {
        "r48_coordination_cycles",
        "r48_coordination_steps",
        "r48_coordination_operations",
        "r48_reentry_records",
    }
)

_CYCLES = "r48_coordination_cycles"
_STEPS = "r48_coordination_steps"
_OPERATIONS = "r48_coordination_operations"
_REENTRIES = "r48_reentry_records"

MIGRATION_SQL = (
    """CREATE TABLE r48_coordination_cycles (
        cycle_id TEXT PRIMARY KEY,
        owner_mission_id TEXT NOT NULL,
        phase TEXT NOT NULL,
        status TEXT NOT NULL,
        quality_version_ref_json TEXT NOT NULL,
        campaign_ref_json TEXT NOT NULL,
        trigger_ref_json TEXT NOT NULL,
        impact_ref_json TEXT,
        source_cursor INTEGER NOT NULL,
        policy_digest TEXT NOT NULL,
        field_validation_required INTEGER NOT NULL,
        learning_promotion_disposition TEXT NOT NULL,
        legacy_reconciliation_disposition TEXT NOT NULL,
        last_seq INTEGER NOT NULL,
        state_json TEXT NOT NULL,
        record_digest TEXT NOT NULL,
        state_digest TEXT NOT NULL,
        projection_seq INTEGER NOT NULL
    )""",
    """CREATE TABLE r48_coordination_steps (
        step_id TEXT PRIMARY KEY,
        cycle_id TEXT NOT NULL,
        step_revision INTEGER NOT NULL,
        phase TEXT NOT NULL,
        status TEXT NOT NULL,
        authority TEXT NOT NULL,
        operation_kind TEXT NOT NULL,
        stage_disposition TEXT NOT NULL,
        policy_digest TEXT NOT NULL,
        input_digest TEXT NOT NULL,
        last_operation_id TEXT,
        last_receipt_id TEXT,
        reason_code TEXT,
        source_cursor INTEGER NOT NULL,
        state_json TEXT NOT NULL,
        record_digest TEXT NOT NULL,
        state_digest TEXT NOT NULL,
        projection_seq INTEGER NOT NULL
    )""",
    """CREATE TABLE r48_coordination_operations (
        operation_id TEXT PRIMARY KEY,
        cycle_id TEXT NOT NULL,
        step_id TEXT NOT NULL,
        step_revision INTEGER NOT NULL,
        authority TEXT NOT NULL,
        operation_kind TEXT NOT NULL,
        authority_idempotency_key TEXT NOT NULL,
        input_digest TEXT NOT NULL,
        request_ref_json TEXT,
        status TEXT NOT NULL,
        receipt_ref_json TEXT,
        authority_operation_id TEXT,
        authority_outcome TEXT,
        result_ref_json TEXT,
        result_digest TEXT,
        authority_revision TEXT,
        proof_digest TEXT,
        owner_cursor INTEGER,
        observed_source_cursor INTEGER,
        state_json TEXT NOT NULL,
        record_digest TEXT NOT NULL,
        state_digest TEXT NOT NULL,
        projection_seq INTEGER NOT NULL
    )""",
    """CREATE TABLE r48_reentry_records (
        reentry_id TEXT PRIMARY KEY,
        cycle_id TEXT NOT NULL,
        prior_step_id TEXT NOT NULL,
        prior_step_revision INTEGER NOT NULL,
        target_phase TEXT NOT NULL,
        target_step_id TEXT NOT NULL,
        target_step_revision INTEGER NOT NULL,
        reentry_kind TEXT NOT NULL,
        operation_id TEXT,
        input_digest TEXT NOT NULL,
        reconciliation_evidence_ref_json TEXT,
        observed_owner_cursor INTEGER,
        reason_code TEXT NOT NULL,
        state_json TEXT NOT NULL,
        record_digest TEXT NOT NULL,
        projection_seq INTEGER NOT NULL
    )""",
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


class R48MigrationContribution:
    extension_id = EXTENSION_ID
    migrations = (MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),)


def _insert(conn: sqlite3.Connection, table: str, columns: tuple[str, ...], values: tuple[Any, ...]) -> None:
    marks = ",".join("?" for _ in columns)
    conn.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({marks})", values)


def _mission_cycle_ids(conn: sqlite3.Connection, mission_id: str) -> tuple[str, ...]:
    return tuple(
        row[0]
        for row in conn.execute(
            "SELECT cycle_id FROM r48_coordination_cycles WHERE owner_mission_id=?",
            (mission_id,),
        ).fetchall()
    )


class R48ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        if mission_id is None:
            for table in (_REENTRIES, _OPERATIONS, _STEPS, _CYCLES):
                conn.execute(f"DELETE FROM {table}")
            return
        cycle_ids = _mission_cycle_ids(conn, mission_id)
        for table in (_REENTRIES, _OPERATIONS, _STEPS):
            for cycle_id in cycle_ids:
                conn.execute(f"DELETE FROM {table} WHERE cycle_id=?", (cycle_id,))
        conn.execute("DELETE FROM r48_coordination_cycles WHERE owner_mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R48State):
            raise TypeError("R4.8 projection requires R48State")
        self.clear(conn, composed.mission_id)
        for cycle in sorted(state.cycles, key=lambda item: item.context.cycle_id):
            context = cycle.context
            cycle_json = canonical_json(cycle.to_dict())
            _insert(
                conn,
                _CYCLES,
                (
                    "cycle_id", "owner_mission_id", "phase", "status", "quality_version_ref_json",
                    "campaign_ref_json", "trigger_ref_json", "impact_ref_json", "source_cursor",
                    "policy_digest", "field_validation_required", "learning_promotion_disposition",
                    "legacy_reconciliation_disposition", "last_seq", "state_json", "record_digest",
                    "state_digest", "projection_seq",
                ),
                (
                    context.cycle_id, context.owner_mission_id, cycle.phase.value, cycle.status.value,
                    canonical_json(context.quality_version_ref.to_dict()), canonical_json(context.campaign_ref.to_dict()),
                    canonical_json(context.trigger_ref.to_dict()), canonical_json(context.impact_ref.to_dict()) if context.impact_ref else None,
                    context.source_cursor, context.policy_snapshot.policy_digest, int(context.policy_snapshot.field_validation_required),
                    context.policy_snapshot.learning_promotion_disposition.value,
                    context.policy_snapshot.legacy_reconciliation_disposition.value, cycle.last_seq, cycle_json,
                    context.record_digest, cycle.state_digest, composed.seq,
                ),
            )
            for step in sorted(cycle.steps, key=lambda item: item.step_id):
                _insert(
                    conn, _STEPS,
                    ("step_id", "cycle_id", "step_revision", "phase", "status", "authority", "operation_kind", "stage_disposition", "policy_digest", "input_digest", "last_operation_id", "last_receipt_id", "reason_code", "source_cursor", "state_json", "record_digest", "state_digest", "projection_seq"),
                    (step.step_id, step.cycle_id, step.step_revision, step.phase.value, step.status.value, step.authority.value, step.operation_kind.value, step.stage_disposition.value, step.policy_digest, step.input_digest, step.last_operation_id, step.last_receipt_id, step.reason_code, step.source_cursor, canonical_json(step.to_dict()), "", step.state_digest, composed.seq),
                )
            receipt_by_id = {receipt.receipt_id: receipt for receipt in cycle.receipts}
            for operation in sorted(cycle.operations, key=lambda item: item.operation_id):
                receipt = receipt_by_id.get(operation.current_receipt_id or "")
                _insert(
                    conn, _OPERATIONS,
                    ("operation_id", "cycle_id", "step_id", "step_revision", "authority", "operation_kind", "authority_idempotency_key", "input_digest", "request_ref_json", "status", "receipt_ref_json", "authority_operation_id", "authority_outcome", "result_ref_json", "result_digest", "authority_revision", "proof_digest", "owner_cursor", "observed_source_cursor", "state_json", "record_digest", "state_digest", "projection_seq"),
                    (operation.operation_id, operation.cycle_id, operation.step_id, operation.step_revision, operation.authority.value, operation.operation_kind.value, operation.authority_idempotency_key, operation.input_digest, canonical_json(operation.request_ref.to_dict()) if operation.request_ref else None, operation.current_status.value, canonical_json(receipt.to_dict()) if receipt else None, operation.authority_operation_id, operation.authority_outcome.value if operation.authority_outcome else None, canonical_json(operation.result_ref.to_dict()) if operation.result_ref else None, operation.result_digest, operation.authority_revision, operation.proof_digest, operation.owner_cursor, operation.observed_source_cursor, canonical_json(operation.to_dict()), operation.request_record_digest, operation.current_state_digest, composed.seq),
                )
            for reentry in sorted(cycle.reentries, key=lambda item: item.reentry_id):
                _insert(
                    conn, _REENTRIES,
                    ("reentry_id", "cycle_id", "prior_step_id", "prior_step_revision", "target_phase", "target_step_id", "target_step_revision", "reentry_kind", "operation_id", "input_digest", "reconciliation_evidence_ref_json", "observed_owner_cursor", "reason_code", "state_json", "record_digest", "projection_seq"),
                    (reentry.reentry_id, reentry.cycle_id, reentry.prior_step_id, reentry.prior_step_revision, reentry.target_phase.value, reentry.target_step_id, reentry.target_step_revision, reentry.kind.value, reentry.operation_id, reentry.input_digest, canonical_json(reentry.reconciliation_evidence.to_dict()) if reentry.reconciliation_evidence else None, reentry.observed_owner_cursor, reentry.reason_code, canonical_json(reentry.to_dict()), reentry.record_digest, composed.seq),
                )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R48State:
        from .contracts import R48CycleState

        cycles = []
        for row in conn.execute("SELECT state_json FROM r48_coordination_cycles WHERE owner_mission_id=? ORDER BY cycle_id", (mission_id,)).fetchall():
            cycles.append(R48CycleState.from_dict(json.loads(row[0])))
        value = R48State(mission_id, tuple(cycles), max((cycle.last_seq for cycle in cycles), default=0), "")
        return replace(value, state_digest=_state_digest(value))

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        row = conn.execute("SELECT MAX(projection_seq) FROM r48_coordination_cycles WHERE owner_mission_id=?", (mission_id,)).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def verify(self, replayed_state: R48State, projected_state: R48State | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}


__all__ = ["PROJECTION_TABLES", "MIGRATION_SQL", "R48MigrationContribution", "R48ProjectionContribution"]
