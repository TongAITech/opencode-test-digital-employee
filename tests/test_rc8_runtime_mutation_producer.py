from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine

from rc8_center.executable_readiness import (
    CenterExecutableReadinessService,
    ExecutableReadinessError,
    ExecutableReadinessState,
)
from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_executable_readiness import PostgresExecutableSpecRepository
from rc8_center.infrastructure.postgres_prepared_attempt import PostgresPreparedAttemptRepository
from rc8_center.prepared_attempt import CenterPreparedAttemptService, PreparedAttemptState
from rc8_center.runtime_invalidation import CenterRuntimeInvalidationCoordinator
from rc8_center.runtime_invalidation_projector import CenterRuntimeInvalidationProjector
from rc8_center.runtime_invalidation_recorder import CenterRuntimeInvalidationRecorder
from rc8_center.runtime_invalidation_service import CenterRuntimeInvalidationService
from rc8_center.runtime_mutation_producer import CenterRuntimeMutationProducer
from rc8_runtime import CentralR1RuntimeLedger, RuntimeProducerKind, runtime_event


class RuntimeMutationProducerTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        database = Path(self.tmpdir.name) / "center.db"
        engine = create_engine("sqlite+pysqlite:///%s" % database.as_posix(), future=True)
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.store = PostgresStore(engine)
        self.prepared_repo = PostgresPreparedAttemptRepository(self.store)
        self.executable_repo = PostgresExecutableSpecRepository(self.store)
        self.prepared = CenterPreparedAttemptService(self.prepared_repo, now_fn=lambda: 100)
        self.executable = CenterExecutableReadinessService(
            self.executable_repo,
            self.prepared,
            now_fn=lambda: 100,
        )
        self.ledger = CentralR1RuntimeLedger(str(Path(self.tmpdir.name) / "r1.jsonl"))
        coordinator = CenterRuntimeInvalidationCoordinator(self.prepared, self.executable)
        self.projector = CenterRuntimeInvalidationProjector(self.ledger, coordinator)
        self.service = CenterRuntimeInvalidationService(
            recorder=CenterRuntimeInvalidationRecorder(self.ledger),
            projector=self.projector,
            prepared_attempts=self.prepared,
        )
        self.producer = CenterRuntimeMutationProducer(
            ledger=self.ledger,
            invalidation_service=self.service,
            executable_readiness=self.executable,
        )
        self._ready()

    def _ready(self):
        self.prepared.select(
            prepared_attempt_id="prep-1",
            test_run_id="run-1",
            mission_node_id="run-1:scope:N5_TEST_DATA_PRECONDITIONS",
            case_id="case-1",
            attempt_id="attempt-1",
            reality_snapshot_id="reality:run-1:scope:v1",
            data_refs=("data://customer/001",),
        )
        self.prepared.verify("prep-1", evidence_refs=("evidence://verify/1",))
        self.prepared.reserve(
            "prep-1",
            reservation_ref="reservation://customer/001",
            evidence_refs=("evidence://reserve/1",),
        )
        self.prepared.freshness_check(
            "prep-1",
            data_freshness_ref="freshness://data/1",
            auth_session_ref="auth://4a/current/1",
            auth_acquired_at=90,
            auth_expires_at=200,
            evidence_refs=("evidence://auth/1",),
        )
        self.prepared.bind(
            "prep-1",
            environment_ref="env://pfc/test",
            route_ref="route://browser-network/customer/v1",
            evidence_refs=("evidence://bind/1",),
        )
        self.executable.build(
            executable_spec_id="exec-1",
            test_run_id="run-1",
            mission_node_id="run-1:scope:N6_SCRIPT_BUILD_READINESS",
            case_id="case-1",
            attempt_id="attempt-1",
            prepared_attempt_id="prep-1",
            frozen_case_ref="case://case-1/rev-1",
            driver_ref="pytest://driver",
            script_artifact_ref="artifact://script/1",
            fixture_binding_refs=("fixture://customer/001",),
            assertion_refs=("assertion://business/1",),
            evidence_collector_refs=("collector://runtime/1",),
            build_evidence_refs=("evidence://build/1",),
        )
        self.executable.verify("exec-1", semantic_evidence_refs=("evidence://semantic/1",))
        self.executable.mark_ready("exec-1")

    def _append_source(self, *, event_id, event_type, observed_ref, sequence):
        event = runtime_event(
            event_id=event_id,
            test_run_id="run-1",
            work_item_id="wi-1",
            node_id="node-1",
            producer_kind=RuntimeProducerKind.TOOL,
            producer_ref="bank-runtime-observer",
            event_type=event_type,
            sequence=sequence,
            case_id="case-1",
            attempt_id="attempt-1",
            refs=["evidence://mutation/%s" % event_id],
            data={"observed_ref": observed_ref},
            occurred_at=110,
        )
        self.ledger.assert_next_node_sequence(event)
        self.ledger.append_runtime(event)
        return event

    def test_restart_replay_derives_invalidation_from_persisted_auth_change(self):
        source = self._append_source(
            event_id="mutation-auth-1",
            event_type="AUTH_CHANGED",
            observed_ref="auth://4a/current/2",
            sequence=1,
        )

        result = self.producer.replay()
        self.assertEqual("REPLAY_COMPLETE", result["status"])
        self.assertEqual(1, result["produced"])
        self.assertEqual(0, result["pending"])

        prepared = self.prepared_repo.get_prepared_attempt("prep-1")
        executable = self.executable_repo.get_executable_spec("exec-1")
        self.assertEqual(PreparedAttemptState.QUARANTINED, prepared.state)
        self.assertEqual(ExecutableReadinessState.INVALIDATED, executable.state)
        self.assertEqual("AUTH_BINDING_CHANGED", executable.invalidation_reason)

        events = self.ledger.runtime_events(test_run_id="run-1")
        invalidations = [
            event for event in events
            if event.get("event_type") == "INVALIDATION_RECORDED"
            and (event.get("data") or {}).get("source_runtime_event_id") == source.event_id
        ]
        self.assertEqual(1, len(invalidations))
        self.assertIn(source.event_id, invalidations[0]["refs"])
        self.assertIn(invalidations[0]["event_id"], self.projector.receipts)

        with self.assertRaisesRegex(
            ExecutableReadinessError,
            "TEST_EXECUTION_REQUIRES_CURRENT_EXECUTABLE_SPEC",
        ):
            self.executable.require_ready_for_execution(
                executable_spec_id="exec-1",
                prepared_attempt_id="prep-1",
                test_run_id="run-1",
                case_id="case-1",
                attempt_id="attempt-1",
            )

        reconstructed_prepared = CenterPreparedAttemptService(
            self.prepared_repo,
            now_fn=lambda: 120,
        )
        reconstructed_executable = CenterExecutableReadinessService(
            self.executable_repo,
            reconstructed_prepared,
            now_fn=lambda: 120,
        )
        reconstructed_coordinator = CenterRuntimeInvalidationCoordinator(
            reconstructed_prepared,
            reconstructed_executable,
        )
        reconstructed_projector = CenterRuntimeInvalidationProjector(
            self.ledger,
            reconstructed_coordinator,
        )
        reconstructed_service = CenterRuntimeInvalidationService(
            recorder=CenterRuntimeInvalidationRecorder(self.ledger),
            projector=reconstructed_projector,
            prepared_attempts=reconstructed_prepared,
        )
        reconstructed_producer = CenterRuntimeMutationProducer(
            ledger=self.ledger,
            invalidation_service=reconstructed_service,
            executable_readiness=reconstructed_executable,
        )
        replay = reconstructed_producer.replay()
        self.assertEqual("REPLAY_COMPLETE", replay["status"])
        self.assertEqual(0, replay["produced"])
        self.assertEqual(1, replay["already_recorded"])
        self.assertEqual(0, replay["pending"])
        invalidations_after_restart = [
            event for event in self.ledger.runtime_events(test_run_id="run-1")
            if event.get("event_type") == "INVALIDATION_RECORDED"
            and (event.get("data") or {}).get("source_runtime_event_id") == source.event_id
        ]
        self.assertEqual(1, len(invalidations_after_restart))

    def test_case_revision_uses_center_owned_frozen_n6_revision(self):
        source = self._append_source(
            event_id="mutation-case-1",
            event_type="CASE_REVISION_CHANGED",
            observed_ref="case://case-1/rev-2",
            sequence=1,
        )

        invalidation_event_id = self.producer.process_runtime_event(source)
        self.assertIsNotNone(invalidation_event_id)
        invalidation = next(
            event for event in self.ledger.runtime_events(test_run_id="run-1")
            if event.get("event_id") == invalidation_event_id
        )
        self.assertEqual(
            "case://case-1/rev-1",
            invalidation["data"]["source_ref"],
        )
        self.assertEqual(
            "case://case-1/rev-2",
            invalidation["data"]["observed_ref"],
        )
        self.assertEqual(
            "FROZEN_CASE_REVISION_CHANGED",
            invalidation["data"]["reason"],
        )
        self.assertEqual(
            ExecutableReadinessState.INVALIDATED,
            self.executable_repo.get_executable_spec("exec-1").state,
        )


if __name__ == "__main__":
    unittest.main()
