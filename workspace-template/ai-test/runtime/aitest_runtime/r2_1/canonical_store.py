"""R2.1 snapshots persisted as existing G3 facts in the canonical R1 stream.

The adapter is Mission-bound, including the pre-Goal intake interval. No legacy
SQL connection, extra event family, or alternate durable authority is involved.
"""
from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from typing import Any, Mapping

from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.g3.contracts import FACT_RECORDED
from aitest_runtime.g3.service import G3TestingIntelligenceService
from .contracts import IdempotencyConflict, R2_1Error, validate_secret_boundary


class CanonicalObservationSnapshotStore:
    def __init__(self, runtime: Any, mission_id: str):
        self.runtime = runtime
        self.mission_id = mission_id
        self.g3 = G3TestingIntelligenceService(runtime)

    def _records(self):
        # Global resolution identity retains the frozen R2.1 conflict boundary.
        # Query the authority (events), never the legacy observation database.
        # A sqlite transaction context commits/rolls back but does not close its
        # connection. Close before yielding so even short-circuit lookups release
        # the database file immediately (required by Windows restart/cleanup).
        with closing(sqlite3.connect(str(self.runtime.db_path))) as connection:
            rows = connection.execute("SELECT payload_json FROM events WHERE event_type=? ORDER BY rowid", (FACT_RECORDED,)).fetchall()
        for (payload,) in rows:
            value = json.loads(payload)
            if value.get("fact_kind") == "RUNTIME_FACTS_RESOLUTION":
                yield value["payload"]["resolution"]

    def find_by_resolution(self, resolution_id_or_project: str, resolution_id: str | None = None) -> dict[str, Any] | None:
        lookup = resolution_id or resolution_id_or_project
        return next((dict(x) for x in self._records() if x["resolution_id"] == lookup), None)

    def save(self, resolution: Mapping[str, Any]) -> dict[str, Any]:
        validate_secret_boundary(resolution)
        existing = self.find_by_resolution(str(resolution["resolution_id"]))
        if existing:
            if existing.get("request_digest") != resolution.get("request_digest"):
                raise IdempotencyConflict(str(resolution["resolution_id"]))
            return existing
        fact_id = "r2.1:snapshot:" + canonical_sha256({"resolution_id": resolution["resolution_id"]})[:32]
        result = {**dict(resolution), "snapshot_id": fact_id}
        self.g3._record(self.mission_id, "RUNTIME_FACTS_RESOLUTION", {"resolution": result},
                        provenance_refs=tuple(resolution.get("source_refs") or ()), fact_id=fact_id)
        return result

    def read(self, snapshot_id: str) -> dict[str, Any]:
        for resolution in self._records():
            if resolution.get("snapshot_id") == snapshot_id:
                return dict(resolution)
        raise R2_1Error("SNAPSHOT_NOT_FOUND", snapshot_id)
