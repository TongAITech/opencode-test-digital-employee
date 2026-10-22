#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from rc8_center.api import create_app
from rc8_center.formal_settings import CenterSettings
from rc8_center.governance_event_projector import GovernanceEventProjector
from rc8_center.governance_projection import GovernanceProjectionService
from rc8_center.infrastructure import (
    PostgresArtifactRepository,
    PostgresCoverageRepository,
    PostgresGovernanceRepository,
    PostgresStore,
    RedisCoordination,
    build_engine,
)
from rc8_runtime import (
    ArtifactAvailability,
    CentralR1RuntimeLedger,
    RuntimeProducerKind,
    runtime_event,
)
from rc8_runtime.artifacts import ArtifactManifest
from rc8_runtime.governance import StageInstance, StageState


def main() -> int:
    settings = CenterSettings(
        database_url=os.environ["RC8_DATABASE_URL"],
        redis_url=os.environ["RC8_REDIS_URL"],
        environment="integration-test",
    )
    postgres = PostgresStore(build_engine(settings.database_url))
    redis = RedisCoordination.from_url(settings.redis_url, namespace="rc8-it")
    governance_repository = PostgresGovernanceRepository(postgres)
    coverage_repository = PostgresCoverageRepository(postgres)
    artifact_repository = PostgresArtifactRepository(postgres)
    projection = GovernanceProjectionService(governance_repository, coverage_repository)

    assert postgres.ping(), "POSTGRES_PING_FAILED"
    assert redis.ping(), "REDIS_PING_FAILED"

    app = create_app(
        settings=settings,
        postgres=postgres,
        redis_coordination=redis,
        governance_projection=projection,
    )
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200, health.text
    body = health.json()
    assert body["status"] == "READY", body
    assert body["database"] == "READY", body
    assert body["redis"] == "READY", body
    assert body["runtime_truth"] == "R1_EVENT_STREAM", body

    architecture = client.get("/api/v1/system/architecture")
    assert architecture.status_code == 200, architecture.text
    architecture_body = architecture.json()
    assert architecture_body["status"] == "FROZEN"
    assert architecture_body["technology"]["backend"] == "FastAPI"
    assert architecture_body["technology"]["persistence"] == "PostgreSQL"
    assert architecture_body["technology"]["coordination"] == "Redis"
    assert architecture_body["technology"]["frontend"] == "Vue3+TypeScript+Vite"
    assert architecture_body["truth_rules"]["redis_authoritative"] is False
    assert architecture_body["truth_rules"]["ui_may_infer_pass"] is False

    run_id = "formal-it-%s" % uuid.uuid4().hex[:12]
    created = client.post(
        "/api/v1/test-runs",
        json={
            "test_run_id": run_id,
            "production_batch_id": "PB-IT",
            "payload": {"scope": "formal-center-integration"},
        },
    )
    assert created.status_code == 201, created.text
    assert created.headers["location"] == "/api/v1/test-runs/%s" % run_id
    assert created.json()["current_state"] == "PLANNED"

    duplicate = client.post("/api/v1/test-runs", json={"test_run_id": run_id})
    assert duplicate.status_code == 409, duplicate.text
    invalid = client.post("/api/v1/test-runs", json={"test_run_id": "", "unexpected": True})
    assert invalid.status_code == 422, invalid.text

    # Formal governance control state is PostgreSQL-backed.
    stage_id = "stage-%s" % uuid.uuid4().hex[:10]
    stage = StageInstance(
        stage_instance_id=stage_id,
        test_run_id=run_id,
        stage_type="APPLICABLE_LAYER_EXECUTION",
        scope_version="scope:SST-IT@app-cfg-center@v1",
        attempt_no=1,
        state=StageState.EXECUTING,
        assigned_worker="L1UnitWorker",
        started_at=100,
    )
    governance_repository.upsert_stage(stage)
    hydrated = governance_repository.get_stage(stage_id)
    assert hydrated is not None
    assert hydrated.scope_version == "scope:SST-IT@app-cfg-center@v1"
    assert hydrated.attempt_no == 1

    attempt_id = "attempt-%s" % uuid.uuid4().hex[:10]
    work_item_id = "work-%s" % uuid.uuid4().hex[:10]
    artifact_id = "evidence-%s" % uuid.uuid4().hex[:10]

    with tempfile.TemporaryDirectory(prefix="rc8-r1-formal-it-") as temp_dir:
        ledger_path = str(Path(temp_dir) / "event-stream.jsonl")
        ledger = CentralR1RuntimeLedger(ledger_path)
        projector = GovernanceEventProjector(
            ledger,
            governance_repository,
            coverage_repository,
            artifact_repository,
        )

        started = runtime_event(
            event_id="evt-start-%s" % uuid.uuid4().hex[:10],
            test_run_id=run_id,
            work_item_id=work_item_id,
            node_id="node-it-01",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="L1UnitWorker",
            event_type="ATTEMPT_STARTED",
            sequence=1,
            attempt_id=attempt_id,
            data={
                "stage_instance_id": stage_id,
                "input_snapshot_ref": "git:abc123",
                "started_at": 101,
            },
        )
        receipt = ledger.append_runtime(started)
        assert receipt["status"] == "PERSISTENCE_VERIFIED"
        replay_started = projector.replay()
        assert replay_started["status"] == "REPLAY_COMPLETE", replay_started
        attempt = governance_repository.get_attempt(attempt_id)
        assert attempt is not None and attempt.status.value == "STARTED"

        # Terminal Attempt cannot project until referenced evidence is AVAILABLE.
        completed = runtime_event(
            event_id="evt-complete-%s" % uuid.uuid4().hex[:10],
            test_run_id=run_id,
            work_item_id=work_item_id,
            node_id="node-it-01",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="L1UnitWorker",
            event_type="ATTEMPT_COMPLETED",
            sequence=2,
            attempt_id=attempt_id,
            data={
                "stage_instance_id": stage_id,
                "input_snapshot_ref": "git:abc123",
                "evidence_refs": ["artifact:%s" % artifact_id],
                "assertion_refs": ["assertion:it-1"],
                "finished_at": 102,
            },
        )
        ledger.append_runtime(completed)
        pending = projector.replay()
        assert pending["pending"] >= 1, pending
        pending_receipt = governance_repository.projection_receipt(completed.event_id)
        assert pending_receipt is not None and pending_receipt["status"] == "PENDING"
        assert governance_repository.get_attempt(attempt_id).status.value == "STARTED"

        artifact_repository.upsert(
            ArtifactManifest(
                artifact_id=artifact_id,
                test_run_id=run_id,
                work_item_id=work_item_id,
                node_id="node-it-01",
                kind="JUNIT_XML",
                producer_kind=RuntimeProducerKind.WORKER,
                producer_ref="L1UnitWorker",
                file_name="TEST-it.xml",
                sha256="a" * 64,
                size_bytes=128,
                availability=ArtifactAvailability.AVAILABLE,
                attempt_id=attempt_id,
                refs=["assertion:it-1"],
                metadata={"integration": True},
                created_at=102,
            )
        )
        projected = projector.replay()
        assert projected["status"] == "REPLAY_COMPLETE", projected
        completed_attempt = governance_repository.get_attempt(attempt_id)
        assert completed_attempt is not None
        assert completed_attempt.status.value == "COMPLETED"
        assert completed_attempt.evidence_refs == ("artifact:%s" % artifact_id,)
        projected_receipt = governance_repository.projection_receipt(completed.event_id)
        assert projected_receipt is not None and projected_receipt["status"] == "PROJECTED"

        # Recreate projector to simulate Center process restart: exact R1 replay is idempotent.
        restarted_projector = GovernanceEventProjector(
            CentralR1RuntimeLedger(ledger_path),
            PostgresGovernanceRepository(postgres),
            PostgresCoverageRepository(postgres),
            PostgresArtifactRepository(postgres),
        )
        replay_after_restart = restarted_projector.replay()
        assert replay_after_restart["status"] == "REPLAY_COMPLETE"
        assert replay_after_restart["pending"] == 0

    governance = client.get("/api/v1/test-runs/%s/governance" % run_id)
    assert governance.status_code == 200, governance.text
    governance_body = governance.json()
    assert governance_body["test_run_id"] == run_id
    assert governance_body["stage_count"] == 1
    assert governance_body["attempt_count"] == 1
    assert governance_body["attempts"][0]["status"] == "COMPLETED"
    assert governance_body["projection_pending_count"] == 0
    assert governance_body["latest_mission_sufficiency"] is None
    assert governance_body["latest_release_decision"] is None

    projector_checkpoint = "governance"
    first = postgres.set_checkpoint(projector_checkpoint, last_event_id="evt-10", last_sequence=10, detail="first")
    assert first.last_sequence == 10
    exact = postgres.set_checkpoint(projector_checkpoint, last_event_id="evt-10", last_sequence=10, detail="replay")
    assert exact.last_sequence == 10
    try:
        postgres.set_checkpoint(projector_checkpoint, last_event_id="evt-9", last_sequence=9)
        raise AssertionError("CHECKPOINT_REGRESSION_ACCEPTED")
    except ValueError as exc:
        assert str(exc) == "PROJECTION_CHECKPOINT_CANNOT_REGRESS"

    lease_resource = "work-%s" % uuid.uuid4().hex[:8]
    assert redis.acquire_lease("work-item", lease_resource, "node-a", 30)
    assert not redis.acquire_lease("work-item", lease_resource, "node-b", 30)
    assert redis.lease_owner("work-item", lease_resource) == "node-a"
    assert redis.renew_lease("work-item", lease_resource, "node-a", 30)
    assert not redis.renew_lease("work-item", lease_resource, "node-b", 30)
    try:
        redis.release_lease("work-item", lease_resource, "node-b")
        raise AssertionError("WRONG_OWNER_RELEASE_ACCEPTED")
    except ValueError as exc:
        assert str(exc) == "LEASE_OWNER_MISMATCH"
    assert redis.release_lease("work-item", lease_resource, "node-a")

    queue = "dispatch-%s" % uuid.uuid4().hex[:8]
    redis.enqueue(queue, {"work_item_id": lease_resource, "test_run_id": run_id})
    assert redis.dequeue(queue) == {"test_run_id": run_id, "work_item_id": lease_resource}
    assert redis.dequeue(queue) is None

    # Redis is coordination only. Removing transient state cannot erase PostgreSQL/R1-derived truth.
    redis.client.flushdb()
    assert postgres.get_test_run(run_id) is not None
    after_redis_loss = client.get("/api/v1/test-runs/%s/governance" % run_id)
    assert after_redis_loss.status_code == 200
    assert after_redis_loss.json()["attempts"][0]["status"] == "COMPLETED"

    print(
        {
            "status": "FORMAL_CENTER_R1_POSTGRES_FASTAPI_CHAIN_VERIFIED",
            "scope": "R1_POSTGRES_GOVERNANCE_FOUNDATION_ONLY",
            "test_run_id": run_id,
            "mission_sufficient": False,
            "product_closed": False,
            "runtime_event_write_api_formalized": False,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
