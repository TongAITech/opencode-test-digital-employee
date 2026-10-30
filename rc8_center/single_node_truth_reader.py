"""Production durable truth reader for RC8 SINGLE_NODE proof.

This adapter deliberately reads the same Center PostgreSQL repositories and the
canonical R1 runtime ledger used by production. It does not infer truth from
plans, UI projections, mocks, or worker return values.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

from sqlalchemy import select

from rc8_runtime.r1_runtime import CentralR1RuntimeLedger

from .infrastructure.postgres import AttemptRow, PostgresStore
from .infrastructure.postgres_artifact import PostgresArtifactRepository
from .infrastructure.postgres_control import PostgresCenterRepository


class ProductionTruthReaderError(RuntimeError):
    pass


class ProductionCenterR1TruthReader:
    """Read WorkItem/Attempt/Artifact/R1 truth from production persistence."""

    def __init__(self, *, store: PostgresStore, r1_ledger: CentralR1RuntimeLedger) -> None:
        if not isinstance(store, PostgresStore):
            raise ProductionTruthReaderError("POSTGRES_STORE_REQUIRED")
        if not isinstance(r1_ledger, CentralR1RuntimeLedger):
            raise ProductionTruthReaderError("CENTRAL_R1_LEDGER_REQUIRED")
        self.store = store
        self.r1_ledger = r1_ledger
        self.center_repository = PostgresCenterRepository(store)
        self.artifact_repository = PostgresArtifactRepository(store)

    def assert_no_attempts_for_test_run(self, test_run_id: str) -> None:
        run_id = str(test_run_id or "").strip()
        if not run_id:
            raise ProductionTruthReaderError("TEST_RUN_ID_REQUIRED")
        with self.store.session() as session:
            attempt_id = session.execute(
                select(AttemptRow.attempt_id).where(AttemptRow.test_run_id == run_id).limit(1)
            ).scalar_one_or_none()
        if attempt_id is not None:
            raise ProductionTruthReaderError(
                "PRODUCTION_CAUSALITY_PREFLIGHT_ATTEMPT_ALREADY_EXISTS:%s" % attempt_id
            )

    def attempt_ids_for_test_run(self, test_run_id: str) -> Tuple[str, ...]:
        """Return the complete durable Attempt identity set for a TestRun."""
        run_id = str(test_run_id or "").strip()
        if not run_id:
            raise ProductionTruthReaderError("TEST_RUN_ID_REQUIRED")
        with self.store.session() as session:
            attempt_ids = tuple(
                str(value)
                for value in session.execute(
                    select(AttemptRow.attempt_id)
                    .where(AttemptRow.test_run_id == run_id)
                    .order_by(AttemptRow.attempt_id.asc())
                ).scalars().all()
            )
        if any(not attempt_id for attempt_id in attempt_ids):
            raise ProductionTruthReaderError("DURABLE_ATTEMPT_ID_MISSING:%s" % run_id)
        if len(set(attempt_ids)) != len(attempt_ids):
            raise ProductionTruthReaderError("DURABLE_ATTEMPT_ID_NOT_UNIQUE:%s" % run_id)
        return attempt_ids

    def assert_attempt_ids_match_observed_leases(
        self, *, test_run_id: str, observed_lease_ids: Iterable[str]
    ) -> None:
        """Require post-run durable Attempts to equal Center leases observed this traversal."""
        run_id = str(test_run_id or "").strip()
        if not run_id:
            raise ProductionTruthReaderError("TEST_RUN_ID_REQUIRED")
        observed = tuple(str(value or "").strip() for value in observed_lease_ids)
        if any(not value for value in observed):
            raise ProductionTruthReaderError("OBSERVED_LEASE_ID_MISSING:%s" % run_id)
        if len(set(observed)) != len(observed):
            raise ProductionTruthReaderError("OBSERVED_LEASE_ID_NOT_UNIQUE:%s" % run_id)
        durable = self.attempt_ids_for_test_run(run_id)
        if set(durable) != set(observed):
            missing = sorted(set(observed) - set(durable))
            unexpected = sorted(set(durable) - set(observed))
            raise ProductionTruthReaderError(
                "PRODUCTION_CAUSALITY_ATTEMPT_LEASE_SET_MISMATCH:%s:missing=%s:unexpected=%s"
                % (run_id, ",".join(missing) or "-", ",".join(unexpected) or "-")
            )

    def get_work_item(self, work_item_id: str) -> Optional[Dict[str, Any]]:
        value = self.center_repository.get_work_item(work_item_id)
        if value is None:
            return None
        return {"work_item_id": value.identity.work_item_id, "test_run_id": value.identity.test_run_id,
                "stage": value.identity.stage, "status": value.state.value}

    def get_attempt(self, attempt_id: str) -> Optional[Dict[str, Any]]:
        with self.store.session() as session:
            row = session.get(AttemptRow, attempt_id)
            if row is None:
                return None
            return {"attempt_id": row.attempt_id, "test_run_id": row.test_run_id,
                    "stage_instance_id": row.stage_instance_id, "work_item_id": row.work_item_id,
                    "producer_node_id": row.producer_node_id, "producer_ref": row.producer_ref,
                    "status": row.status}

    def get_artifact(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        value = self.artifact_repository.get(artifact_id)
        if value is None:
            return None
        return {"artifact_id": value.artifact_id, "test_run_id": value.test_run_id,
                "work_item_id": value.work_item_id, "attempt_id": value.attempt_id,
                "node_id": value.node_id, "producer_kind": value.producer_kind.value,
                "producer_ref": value.producer_ref,
                "status": "COMPLETED" if value.availability.value == "AVAILABLE" else value.availability.value}

    def find_r1_attempt_completed(self, *, test_run_id: str, work_item_id: str, attempt_id: str) -> Optional[Dict[str, Any]]:
        matches = []
        for event in self.r1_ledger.runtime_events(test_run_id=test_run_id, work_item_id=work_item_id):
            if event.get("event_type") == "ATTEMPT_COMPLETED" and event.get("attempt_id") == attempt_id:
                matches.append(event)
        if not matches:
            return None
        if len(matches) != 1:
            raise ProductionTruthReaderError("R1_ATTEMPT_COMPLETED_NOT_UNIQUE:%s" % attempt_id)
        return dict(matches[0])
