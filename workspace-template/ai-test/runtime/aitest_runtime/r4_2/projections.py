from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from aitest_runtime.durable_core import ComposedRuntimeState, MigrationStep, canonical_json, canonical_sha256

from .contracts import (
    EXTENSION_ID,
    ImpactAssessment,
    PlanRevisionBridgeReceipt,
    PlanRevisionIntent,
    R42State,
    SelectionRevisionLink,
    ContinuousTestTrigger,
)
from .errors import R42Error


PROJECTION_TABLES = frozenset(
    {
        "r42_trigger_receipts",
        "r42_impact_assessments",
        "r42_campaign_selection_links",
        "r42_plan_bridge_receipts",
    }
)

MIGRATION_SQL = (
    """
    CREATE TABLE r42_trigger_receipts (
        mission_id TEXT NOT NULL,
        object_id TEXT NOT NULL,
        trigger_id TEXT NOT NULL,
        dedupe_key TEXT NOT NULL,
        source_stream_key TEXT NOT NULL,
        source_revision INTEGER NOT NULL,
        source_cursor TEXT,
        coalescing_key TEXT NOT NULL,
        trigger_digest TEXT NOT NULL,
        state_json TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )
    """,
    "CREATE INDEX r42_trigger_mission_dedupe ON r42_trigger_receipts(mission_id, dedupe_key)",
    "CREATE INDEX r42_trigger_mission_source ON r42_trigger_receipts(mission_id, source_stream_key, source_revision, source_cursor)",
    "CREATE INDEX r42_trigger_mission_coalescing ON r42_trigger_receipts(mission_id, coalescing_key)",
    """
    CREATE TABLE r42_impact_assessments (
        mission_id TEXT NOT NULL,
        object_id TEXT NOT NULL,
        impact_assessment_id TEXT NOT NULL,
        assessment_digest TEXT NOT NULL,
        input_set_digest TEXT NOT NULL,
        state_json TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )
    """,
    "CREATE INDEX r42_impact_mission_assessment ON r42_impact_assessments(mission_id, impact_assessment_id)",
    """
    CREATE TABLE r42_campaign_selection_links (
        mission_id TEXT NOT NULL,
        object_id TEXT NOT NULL,
        selection_link_id TEXT NOT NULL,
        impact_assessment_id TEXT NOT NULL,
        selection_revision_id TEXT NOT NULL,
        selection_revision_digest TEXT NOT NULL,
        state_json TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )
    """,
    """
    CREATE TABLE r42_plan_bridge_receipts (
        mission_id TEXT NOT NULL,
        object_id TEXT NOT NULL,
        bridge_receipt_id TEXT NOT NULL,
        planner_request_id TEXT NOT NULL,
        plan_revision_intent_id TEXT NOT NULL,
        intent_json TEXT NOT NULL,
        bridge_status TEXT NOT NULL,
        r2_result_digest TEXT NOT NULL,
        state_json TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        projection_seq INTEGER NOT NULL,
        PRIMARY KEY(mission_id, object_id)
    )
    """,
    "CREATE INDEX r42_bridge_mission_planner_request ON r42_plan_bridge_receipts(mission_id, planner_request_id)",
)


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in MIGRATION_SQL:
        conn.execute(statement)


@dataclass(frozen=True)
class R42MigrationContribution:
    extension_id: str = EXTENSION_ID
    migrations: tuple[MigrationStep, ...] = (
        MigrationStep(1, canonical_sha256(list(MIGRATION_SQL)), _apply_schema),
    )


class R42ProjectionContribution:
    projection_tables = PROJECTION_TABLES

    def clear(self, conn: sqlite3.Connection, mission_id: str | None = None) -> None:
        for table in sorted(PROJECTION_TABLES):
            if mission_id is None:
                conn.execute(f"DELETE FROM {table}")
            else:
                conn.execute(f"DELETE FROM {table} WHERE mission_id=?", (mission_id,))

    def apply(self, conn: sqlite3.Connection, composed: ComposedRuntimeState) -> None:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R42State):
            raise R42Error("R4_2_PROJECTION_INPUT_INVALID", "invalid R4.2 projection input")
        self.clear(conn, composed.mission_id)
        conn.executemany(
            """INSERT INTO r42_trigger_receipts(
                mission_id,object_id,trigger_id,dedupe_key,source_stream_key,source_revision,source_cursor,
                coalescing_key,trigger_digest,state_json,state_hash,projection_seq
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    composed.mission_id, item.trigger_id, item.trigger_id, item.dedupe_key, item.source_stream_key,
                    item.source_revision, item.source_cursor, item.coalescing_key, item.trigger_digest,
                    canonical_json(item.to_dict()), canonical_sha256(item.to_dict()), composed.seq,
                )
                for item in state.triggers
            ],
        )
        conn.executemany(
            """INSERT INTO r42_impact_assessments(
                mission_id,object_id,impact_assessment_id,assessment_digest,input_set_digest,state_json,state_hash,projection_seq
            ) VALUES(?,?,?,?,?,?,?,?)""",
            [
                (
                    composed.mission_id, item.impact_assessment_id, item.impact_assessment_id, item.assessment_digest,
                    item.input_set_digest, canonical_json(item.to_dict()), canonical_sha256(item.to_dict()), composed.seq,
                )
                for item in state.assessments
            ],
        )
        conn.executemany(
            """INSERT INTO r42_campaign_selection_links(
                mission_id,object_id,selection_link_id,impact_assessment_id,selection_revision_id,
                selection_revision_digest,state_json,state_hash,projection_seq
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            [
                (
                    composed.mission_id, item.selection_link_id, item.selection_link_id, item.impact_assessment_ref.object_id,
                    item.r4_1_selection_revision_ref.object_id, item.selection_revision_digest,
                    canonical_json(item.to_dict()), canonical_sha256(item.to_dict()), composed.seq,
                )
                for item in state.selection_links
            ],
        )
        conn.executemany(
            """INSERT INTO r42_plan_bridge_receipts(
                mission_id,object_id,bridge_receipt_id,planner_request_id,plan_revision_intent_id,intent_json,
                bridge_status,r2_result_digest,state_json,state_hash,projection_seq
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    composed.mission_id, item.bridge_receipt_id, item.bridge_receipt_id, item.planner_request_id,
                    item.plan_revision_intent_ref.object_id,
                    canonical_json((state.intent(item.plan_revision_intent_ref.object_id) or {}).to_dict() if state.intent(item.plan_revision_intent_ref.object_id) else {}),
                    item.bridge_status.value, item.r2_result_digest, canonical_json(item.to_dict()), canonical_sha256(item.to_dict()), composed.seq,
                )
                for item in state.bridge_receipts
            ],
        )

    def read(self, conn: sqlite3.Connection, mission_id: str) -> R42State:
        triggers = tuple(
            ContinuousTestTrigger.from_dict(json.loads(row["state_json"]))
            for row in conn.execute("SELECT state_json FROM r42_trigger_receipts WHERE mission_id=? ORDER BY object_id", (mission_id,)).fetchall()
        )
        assessments = tuple(
            ImpactAssessment.from_dict(json.loads(row["state_json"]))
            for row in conn.execute("SELECT state_json FROM r42_impact_assessments WHERE mission_id=? ORDER BY object_id", (mission_id,)).fetchall()
        )
        links = tuple(
            SelectionRevisionLink.from_dict(json.loads(row["state_json"]))
            for row in conn.execute("SELECT state_json FROM r42_campaign_selection_links WHERE mission_id=? ORDER BY object_id", (mission_id,)).fetchall()
        )
        bridge_rows = conn.execute("SELECT state_json,intent_json FROM r42_plan_bridge_receipts WHERE mission_id=? ORDER BY object_id", (mission_id,)).fetchall()
        receipts = tuple(PlanRevisionBridgeReceipt.from_dict(json.loads(row["state_json"])) for row in bridge_rows)
        intents = tuple(PlanRevisionIntent.from_dict(json.loads(row["intent_json"])) for row in bridge_rows if json.loads(row["intent_json"]))
        return R42State(mission_id, triggers, assessments, links, intents, receipts)

    def projection_seq(self, conn: sqlite3.Connection, mission_id: str) -> int | None:
        rows = conn.execute(
            "SELECT projection_seq FROM r42_trigger_receipts WHERE mission_id=? "
            "UNION ALL SELECT projection_seq FROM r42_impact_assessments WHERE mission_id=? "
            "UNION ALL SELECT projection_seq FROM r42_campaign_selection_links WHERE mission_id=? "
            "UNION ALL SELECT projection_seq FROM r42_plan_bridge_receipts WHERE mission_id=?",
            (mission_id, mission_id, mission_id, mission_id),
        ).fetchall()
        if not rows:
            return None
        values = {int(row[0]) for row in rows}
        return next(iter(values)) if len(values) == 1 else -1

    def verify(self, replayed_state: R42State, projected_state: R42State | None) -> dict[str, object]:
        replay_hash = canonical_sha256(replayed_state.to_dict())
        projection_hash = canonical_sha256(projected_state.to_dict()) if projected_state is not None else None
        return {"ok": replay_hash == projection_hash, "replay_hash": replay_hash, "projection_hash": projection_hash}


__all__ = ["MIGRATION_SQL", "PROJECTION_TABLES", "R42MigrationContribution", "R42ProjectionContribution"]
