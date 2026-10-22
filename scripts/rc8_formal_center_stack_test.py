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
from rc8_center.formal_control import FormalCenterControlPlane
from rc8_center.formal_settings import CenterSettings
from rc8_center.governance_event_projector import GovernanceEventProjector
from rc8_center.governance_projection import GovernanceProjectionService
from rc8_center.infrastructure import (
    PostgresArtifactRepository,
    PostgresCenterRepository,
    PostgresCoverageRepository,
    PostgresGovernanceRepository,
    PostgresStore,
    RedisCoordination,
    build_engine,
)
from rc8_runtime import ArtifactAvailability, CentralR1RuntimeLedger, RuntimeProducerKind
from rc8_runtime.artifacts import ArtifactManifest
from rc8_runtime.governance import StageInstance, StageState


def _runtime_payload(*, lease_id: str, event_id: str, run_id: str, work_item_id: str, event_type: str,
                     sequence: int, attempt_id: str, data: dict) -> dict:
    return {
        "lease_id": lease_id,
        "event_id": event_id,
        "test_run_id": run_id,
        "work_item_id": work_item_id,
        "node_id": "node-it-01",
        "producer_kind": "WORKER",
        "producer_ref": "L1UnitWorker",
        "event_type": event_type,
        "sequence": sequence,
        "attempt_id": attempt_id,
        "refs": [],
        "data": data,
        "occurred_at": 100 + sequence,
    }


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
    control_repository = PostgresCenterRepository(postgres)
    projection = GovernanceProjectionService(governance_repository, coverage_repository)

    assert postgres.ping(), "POSTGRES_PING_FAILED"
    assert redis.ping(), "REDIS_PING_FAILED"

    with tempfile.TemporaryDirectory(prefix="rc8-r1-formal-it-") as temp_dir:
        ledger_path = str(Path(temp_dir) / "event-stream.jsonl")
        ledger = CentralR1RuntimeLedger(ledger_path)
        projector = GovernanceEventProjector(ledger, governance_repository, coverage_repository, artifact_repository)
        formal_control = FormalCenterControlPlane(control_repository, redis, ledger, projector)
        app = create_app(
            settings=settings,
            postgres=postgres,
            redis_coordination=redis,
            governance_projection=projection,
            formal_control=formal_control,
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
        assert architecture_body["truth_rules"]["runtime_write_requires_pg_and_redis_lease_token"] is True

        run_id = "formal-it-%s" % uuid.uuid4().hex[:12]
        created = client.post(
            "/api/v1/test-runs",
            json={"test_run_id": run_id, "production_batch_id": "PB-IT", "payload": {"scope": "formal-center-integration"}},
        )
        assert created.status_code == 201, created.text
        assert created.headers["location"] == "/api/v1/test-runs/%s" % run_id
        assert created.json()["current_state"] == "PLANNED"
        assert client.post("/api/v1/test-runs", json={"test_run_id": run_id}).status_code == 409
        assert client.post("/api/v1/test-runs", json={"test_run_id": "", "unexpected": True}).status_code == 422

        # Formal governance control state is PostgreSQL-backed and scope-bound.
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
        assert hydrated is not None and hydrated.scope_version == "scope:SST-IT@app-cfg-center@v1"

        # Formal Node / Capability / WorkItem APIs persist identities in PostgreSQL.
        node = client.post(
            "/api/v1/nodes/register",
            json={
                "node_id": "node-it-01",
                "operator_ref": "integration-test",
                "os_family": "linux",
                "architecture": "x86_64",
                "shell": "bash",
                "registered_at": 1,
            },
        )
        assert node.status_code == 200, node.text
        capability = client.post(
            "/api/v1/nodes/node-it-01/capabilities",
            json={
                "capability_id": "maven-junit",
                "state": "VERIFIED",
                "probe_ref": "probe:formal-it",
                "evidence_refs": ["artifact:capability-probe-it"],
                "verified_at": 2,
            },
        )
        assert capability.status_code == 200, capability.text

        attempt_id = "attempt-%s" % uuid.uuid4().hex[:10]
        work_item_id = "work-%s" % uuid.uuid4().hex[:10]
        artifact_id = "evidence-%s" % uuid.uuid4().hex[:10]
        registered = client.post(
            "/api/v1/work-items/register",
            json={
                "work_item_id": work_item_id,
                "test_run_id": run_id,
                "stage": "L1_EXECUTION",
                "scope_refs": ["scope:SST-IT@app-cfg-center@v1"],
                "required_capabilities": ["maven-junit"],
            },
        )
        assert registered.status_code == 200, registered.text
        leased = client.post("/api/v1/work-items/%s/lease" % work_item_id, json={"node_id": "node-it-01", "ttl_seconds": 120})
        assert leased.status_code == 200, leased.text
        lease_id = leased.json()["work_item"]["lease_id"]
        assert lease_id
        assert redis.lease_info("work-item", work_item_id)["lease_id"] == lease_id
        started_work = client.post("/api/v1/work-items/%s/start" % work_item_id, json={"node_id": "node-it-01", "lease_id": lease_id})
        assert started_work.status_code == 200, started_work.text
        assert started_work.json()["work_item"]["state"] == "RUNNING"

        # Wrong/stale token cannot write a runtime event and cannot consume R1 sequence.
        rejected_event_id = "evt-rejected-%s" % uuid.uuid4().hex[:10]
        rejected = client.post(
            "/api/v1/runtime-events",
            json=_runtime_payload(
                lease_id="stale-token",
                event_id=rejected_event_id,
                run_id=run_id,
                work_item_id=work_item_id,
                event_type="ATTEMPT_STARTED",
                sequence=1,
                attempt_id=attempt_id,
                data={"stage_instance_id": stage_id, "input_snapshot_ref": "git:abc123", "started_at": 101},
            ),
        )
        assert rejected.status_code == 409, rejected.text
        assert ledger.event_by_id(rejected_event_id) is None

        accepted_start_id = "evt-start-%s" % uuid.uuid4().hex[:10]
        accepted = client.post(
            "/api/v1/runtime-events",
            json=_runtime_payload(
                lease_id=lease_id,
                event_id=accepted_start_id,
                run_id=run_id,
                work_item_id=work_item_id,
                event_type="ATTEMPT_STARTED",
                sequence=1,
                attempt_id=attempt_id,
                data={"stage_instance_id": stage_id, "input_snapshot_ref": "git:abc123", "started_at": 101},
            ),
        )
        assert accepted.status_code == 200, accepted.text
        accepted_body = accepted.json()
        assert accepted_body["receipt"]["status"] == "PERSISTENCE_VERIFIED"
        assert accepted_body["truth_note"] == "R1_PERSISTED_BEFORE_PROJECTION"
        attempt = governance_repository.get_attempt(attempt_id)
        assert attempt is not None and attempt.status.value == "STARTED"

        # Terminal Attempt enters R1 but remains projection-PENDING until its Artifact is AVAILABLE.
        completed_event_id = "evt-complete-%s" % uuid.uuid4().hex[:10]
        completed = client.post(
            "/api/v1/runtime-events",
            json=_runtime_payload(
                lease_id=lease_id,
                event_id=completed_event_id,
                run_id=run_id,
                work_item_id=work_item_id,
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
            ),
        )
        assert completed.status_code == 200, completed.text
        pending_receipt = governance_repository.projection_receipt(completed_event_id)
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
        replay = projector.replay()
        assert replay["status"] == "REPLAY_COMPLETE", replay
        assert replay["pending"] == 0
        completed_attempt = governance_repository.get_attempt(attempt_id)
        assert completed_attempt is not None and completed_attempt.status.value == "COMPLETED"
        assert completed_attempt.evidence_refs == ("artifact:%s" % artifact_id,)

        completed_work = client.post(
            "/api/v1/work-items/%s/complete" % work_item_id,
            json={"node_id": "node-it-01", "lease_id": lease_id},
        )
        assert completed_work.status_code == 200, completed_work.text
        assert completed_work.json()["work_item"]["state"] == "COMPLETED"
        assert redis.lease_info("work-item", work_item_id) is None

        stale_after_complete = client.post(
            "/api/v1/runtime-events",
            json=_runtime_payload(
                lease_id=lease_id,
                event_id="evt-stale-%s" % uuid.uuid4().hex[:10],
                run_id=run_id,
                work_item_id=work_item_id,
                event_type="ATTEMPT_STARTED",
                sequence=3,
                attempt_id="attempt-stale",
                data={"stage_instance_id": stage_id, "input_snapshot_ref": "git:stale", "started_at": 103},
            ),
        )
        assert stale_after_complete.status_code == 409
        assert len(ledger.runtime_events()) == 2

        # Center-process restart: reconstruct ledger/projector and replay exact R1 idempotently.
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
        assert governance_body["stage_count"] == 1
        assert governance_body["attempt_count"] == 1
        assert governance_body["attempts"][0]["status"] == "COMPLETED"
        assert governance_body["projection_pending_count"] == 0
        assert governance_body["latest_mission_sufficiency"] is None
        assert governance_body["latest_release_decision"] is None

        # Redis loss does not erase durable truth, but an in-flight WorkItem must
        # fail closed rather than silently reacquire and duplicate actions.
        recovery_work_id = "work-recovery-%s" % uuid.uuid4().hex[:8]
        assert client.post(
            "/api/v1/work-items/register",
            json={
                "work_item_id": recovery_work_id,
                "test_run_id": run_id,
                "stage": "L1_EXECUTION",
                "scope_refs": ["scope:SST-IT@app-cfg-center@v1"],
                "required_capabilities": ["maven-junit"],
            },
        ).status_code == 200
        recovery_lease_response = client.post(
            "/api/v1/work-items/%s/lease" % recovery_work_id,
            json={"node_id": "node-it-01", "ttl_seconds": 120},
        )
        assert recovery_lease_response.status_code == 200
        recovery_lease = recovery_lease_response.json()["work_item"]["lease_id"]
        assert client.post(
            "/api/v1/work-items/%s/start" % recovery_work_id,
            json={"node_id": "node-it-01", "lease_id": recovery_lease},
        ).status_code == 200
        redis.client.flushdb()
        blocked_after_redis_loss = client.post(
            "/api/v1/runtime-events",
            json=_runtime_payload(
                lease_id=recovery_lease,
                event_id="evt-after-redis-loss-%s" % uuid.uuid4().hex[:8],
                run_id=run_id,
                work_item_id=recovery_work_id,
                event_type="ATTEMPT_STARTED",
                sequence=3,
                attempt_id="attempt-after-redis-loss",
                data={"stage_instance_id": stage_id, "input_snapshot_ref": "git:recovery", "started_at": 103},
            ),
        )
        assert blocked_after_redis_loss.status_code == 409
        assert blocked_after_redis_loss.json()["detail"] == "ACTIVE_WORK_ITEM_LEASE_REQUIRED"
        retry_lease = client.post(
            "/api/v1/work-items/%s/lease" % recovery_work_id,
            json={"node_id": "node-it-01", "ttl_seconds": 120},
        )
        assert retry_lease.status_code == 409
        assert retry_lease.json()["detail"] == "WORK_ITEM_LEASE_RECOVERY_REQUIRED"
        assert control_repository.get_work_item(recovery_work_id).state.value == "RUNNING"
        assert postgres.get_test_run(run_id) is not None
        assert client.get("/api/v1/test-runs/%s/governance" % run_id).json()["attempts"][0]["status"] == "COMPLETED"

        # Projection checkpoint is monotonic.
        first = postgres.set_checkpoint("governance", last_event_id="evt-10", last_sequence=10, detail="first")
        assert first.last_sequence == 10
        assert postgres.set_checkpoint("governance", last_event_id="evt-10", last_sequence=10, detail="replay").last_sequence == 10
        try:
            postgres.set_checkpoint("governance", last_event_id="evt-9", last_sequence=9)
            raise AssertionError("CHECKPOINT_REGRESSION_ACCEPTED")
        except ValueError as exc:
            assert str(exc) == "PROJECTION_CHECKPOINT_CANNOT_REGRESS"

        # Queue remains transient coordination only.
        queue = "dispatch-%s" % uuid.uuid4().hex[:8]
        redis.enqueue(queue, {"work_item_id": work_item_id, "test_run_id": run_id})
        assert redis.dequeue(queue) == {"test_run_id": run_id, "work_item_id": work_item_id}
        assert redis.dequeue(queue) is None

    print(
        {
            "status": "FORMAL_CENTER_LEASE_R1_POSTGRES_FASTAPI_CHAIN_VERIFIED",
            "scope": "FORMAL_CONTROL_AND_GOVERNANCE_FOUNDATION_ONLY",
            "test_run_id": run_id,
            "mission_sufficient": False,
            "product_closed": False,
            "artifact_upload_api_formalized": False,
            "redis_loss_recovery_coordinator_complete": False,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
