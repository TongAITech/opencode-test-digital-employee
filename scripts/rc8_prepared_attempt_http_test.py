#!/usr/bin/env python3
"""Real PostgreSQL + Redis + R1 HTTP proof for the N5 PreparedAttempt entry.

This verifies the production authority chain rather than a memory/mock path:
case-scoped N5 WorkItem -> Redis/PG lease -> Center /start -> canonical R1
ATTEMPT_STARTED -> governance projection -> lease-bound PreparedAttempt SELECTED
persisted in PostgreSQL.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from rc8_center.api import create_app
from rc8_center.artifacts import FileArtifactStore
from rc8_center.executable_readiness import CenterExecutableReadinessService
from rc8_center.formal_control import FormalCenterControlPlane
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
from rc8_center.infrastructure.postgres_executable_readiness import PostgresExecutableSpecRepository
from rc8_center.infrastructure.postgres_prepared_attempt import PostgresPreparedAttemptRepository
from rc8_center.prepared_attempt import CenterPreparedAttemptService
from rc8_center.runtime_invalidation import CenterRuntimeInvalidationCoordinator
from rc8_center.runtime_invalidation_projector import CenterRuntimeInvalidationProjector
from rc8_center.runtime_invalidation_recorder import CenterRuntimeInvalidationRecorder
from rc8_center.runtime_invalidation_service import CenterRuntimeInvalidationService
from rc8_center.runtime_mutation_producer import (
    CenterRuntimeMutationProducer,
    RuntimeMutationAwareFormalCenterControlPlane,
)
from rc8_center.scope_aware_governance_projector import ScopeAwareGovernanceEventProjector
from rc8_runtime import CentralR1RuntimeLedger, NodeIdentity, WorkItemIdentity
from rc8_runtime.governance import AttemptStatus, StageInstance, StageState
from rc8_runtime.mission_nodes import MissionNodeAdoptionGraph, MissionNodeType


def main() -> int:
    suffix = uuid.uuid4().hex[:10]
    run_id = "n5-http-%s" % suffix
    stage_id = "stage-n5-%s" % suffix
    work_item_id = "work-n5-%s" % suffix
    case_id = "CASE-N5-%s" % suffix
    node_id = "node-n5-%s" % suffix
    scope_version = "scope:SST-N5@app-cfg-center@%s" % suffix

    postgres = PostgresStore(build_engine(os.environ["RC8_DATABASE_URL"]))
    redis = RedisCoordination.from_url(
        os.environ["RC8_REDIS_URL"],
        namespace="rc8-n5-http-%s" % suffix,
    )
    assert postgres.ping(), "POSTGRES_PING_FAILED"
    assert redis.ping(), "REDIS_PING_FAILED"

    governance_repository = PostgresGovernanceRepository(postgres)
    coverage_repository = PostgresCoverageRepository(postgres)
    artifact_repository = PostgresArtifactRepository(postgres)
    control_repository = PostgresCenterRepository(postgres)
    prepared_attempt_repository = PostgresPreparedAttemptRepository(postgres)
    executable_spec_repository = PostgresExecutableSpecRepository(postgres)
    prepared_attempts = CenterPreparedAttemptService(prepared_attempt_repository)
    executable_readiness = CenterExecutableReadinessService(executable_spec_repository, prepared_attempts)

    with tempfile.TemporaryDirectory(prefix="rc8-n5-http-") as temp_dir:
        ledger = CentralR1RuntimeLedger(str(Path(temp_dir) / "event-stream.jsonl"))
        invalidation_coordinator = CenterRuntimeInvalidationCoordinator(prepared_attempts, executable_readiness)
        invalidation_projector = CenterRuntimeInvalidationProjector(ledger, invalidation_coordinator)
        invalidation_recorder = CenterRuntimeInvalidationRecorder(ledger)
        invalidation_service = CenterRuntimeInvalidationService(
            recorder=invalidation_recorder,
            projector=invalidation_projector,
            prepared_attempts=prepared_attempts,
        )
        mutation_producer = CenterRuntimeMutationProducer(
            ledger=ledger,
            invalidation_service=invalidation_service,
            executable_readiness=executable_readiness,
        )
        projector = ScopeAwareGovernanceEventProjector(
            ledger,
            governance_repository,
            coverage_repository,
            artifact_repository,
        )
        core = FormalCenterControlPlane(
            control_repository,
            redis,
            ledger,
            projector,
        )
        formal_control = RuntimeMutationAwareFormalCenterControlPlane(core, mutation_producer)
        projection = GovernanceProjectionService(governance_repository, coverage_repository)
        artifact_store = FileArtifactStore(str(Path(temp_dir) / "artifacts"), artifact_repository)
        app = create_app(
            postgres=postgres,
            redis_coordination=redis,
            governance_projection=projection,
            formal_control=formal_control,
        )
        # formal_app wires these same production services after create_app;
        # the route reads them only when the request executes.
        app.state.control_repository = control_repository
        app.state.governance_repository = governance_repository
        app.state.prepared_attempt_repository = prepared_attempt_repository
        app.state.prepared_attempts = prepared_attempts
        app.state.artifact_store = artifact_store
        client = TestClient(app)

        postgres.create_test_run(run_id, payload={"truth_scope": "N5_LEASE_BOUND_HTTP_REALITY"})
        governance_repository.upsert_stage(
            StageInstance(
                stage_instance_id=stage_id,
                test_run_id=run_id,
                stage_type="PRECONDITION_DATA_PREP",
                scope_version=scope_version,
                attempt_no=1,
                state=StageState.EXECUTING,
                assigned_worker="N5PreparedAttemptWorker",
                started_at=100,
            )
        )

        registered_node = client.post(
            "/api/v1/nodes/register",
            json={
                "node_id": node_id,
                "operator_ref": "n5-http-integration",
                "os_family": "linux",
                "architecture": "x86_64",
                "shell": "bash",
                "registered_at": 1,
            },
        )
        assert registered_node.status_code == 200, registered_node.text

        registered_work = client.post(
            "/api/v1/work-items/register",
            json={
                "work_item_id": work_item_id,
                "test_run_id": run_id,
                "stage": "PRECONDITION_DATA_PREP",
                "scope_refs": ["case:%s" % case_id, scope_version],
                "required_capabilities": [],
            },
        )
        assert registered_work.status_code == 200, registered_work.text
        control_repository.link_work_item_to_stage(
            work_item_id=work_item_id,
            stage_instance_id=stage_id,
            test_run_id=run_id,
            created_at=2,
        )

        leased = client.post(
            "/api/v1/work-items/%s/lease" % work_item_id,
            json={"node_id": node_id, "ttl_seconds": 120},
        )
        assert leased.status_code == 200, leased.text
        lease_id = leased.json()["work_item"]["lease_id"]
        assert lease_id
        assert redis.lease_info("work-item", work_item_id)["lease_id"] == lease_id

        # N5 selection is forbidden before Center /start establishes the R1
        # Attempt authority and moves the WorkItem to RUNNING.
        before_start = client.post(
            "/api/v1/work-items/%s/prepared-attempts/select" % work_item_id,
            json={
                "lease_id": lease_id,
                "reality_snapshot_id": "reality:%s" % suffix,
                "data_refs": ["data:account:%s" % suffix],
            },
        )
        assert before_start.status_code == 400, before_start.text
        assert before_start.json()["detail"] == "N5_WORK_ITEM_MUST_BE_RUNNING"

        started = client.post(
            "/api/v1/work-items/%s/start" % work_item_id,
            json={"node_id": node_id, "lease_id": lease_id},
        )
        assert started.status_code == 200, started.text
        assert started.json()["work_item"]["state"] == "RUNNING"

        projected_attempt = governance_repository.get_attempt(lease_id)
        assert projected_attempt is not None
        assert projected_attempt.status == AttemptStatus.STARTED
        assert projected_attempt.test_run_id == run_id
        assert projected_attempt.work_item_id == work_item_id
        assert projected_attempt.stage_instance_id == stage_id
        assert projected_attempt.case_id == case_id
        assert projected_attempt.producer_node_id == node_id
        assert projected_attempt.input_snapshot_ref == scope_version
        assert any(
            event.get("event_type") == "ATTEMPT_STARTED" and event.get("attempt_id") == lease_id
            for event in ledger.runtime_events(test_run_id=run_id, work_item_id=work_item_id)
        )

        # Worker is not allowed to inject Center-owned identities.
        forged_identity = client.post(
            "/api/v1/work-items/%s/prepared-attempts/select" % work_item_id,
            json={
                "lease_id": lease_id,
                "reality_snapshot_id": "reality:%s" % suffix,
                "data_refs": ["data:account:%s" % suffix],
                "attempt_id": "forged-attempt",
            },
        )
        assert forged_identity.status_code == 422, forged_identity.text

        selected = client.post(
            "/api/v1/work-items/%s/prepared-attempts/select" % work_item_id,
            json={
                "lease_id": lease_id,
                "reality_snapshot_id": "reality:%s" % suffix,
                "data_refs": ["data:account:%s" % suffix, "data:loan:%s" % suffix],
            },
        )
        assert selected.status_code == 200, selected.text
        body = selected.json()
        value = body["prepared_attempt"]
        prepared_attempt_id = "prepared:%s" % lease_id
        expected_mission_node_id = MissionNodeAdoptionGraph(
            run_id,
            scope_version,
        ).node(MissionNodeType.N5_TEST_DATA_PRECONDITIONS).mission_node_id
        assert value["prepared_attempt_id"] == prepared_attempt_id
        assert value["test_run_id"] == run_id
        assert value["mission_node_id"] == expected_mission_node_id
        assert value["case_id"] == case_id
        assert value["attempt_id"] == lease_id
        assert value["state"] == "SELECTED"
        assert value["reality_snapshot_id"] == "reality:%s" % suffix
        assert value["data_refs"] == ["data:account:%s" % suffix, "data:loan:%s" % suffix]
        assert body["truth_note"] == "CENTER_DERIVED_FROM_RUNNING_N5_WORK_ITEM_ACTIVE_LEASE_AND_R1_PROJECTED_ATTEMPT"

        persisted = prepared_attempt_repository.get_prepared_attempt(prepared_attempt_id)
        assert persisted is not None
        assert persisted.attempt_id == lease_id
        assert persisted.case_id == case_id
        assert persisted.mission_node_id == expected_mission_node_id

        # Same Center identity is idempotent; a stale token is not.
        repeated = client.post(
            "/api/v1/work-items/%s/prepared-attempts/select" % work_item_id,
            json={
                "lease_id": lease_id,
                "reality_snapshot_id": "reality:%s" % suffix,
                "data_refs": ["data:account:%s" % suffix, "data:loan:%s" % suffix],
            },
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["prepared_attempt"]["prepared_attempt_id"] == prepared_attempt_id

        stale = client.post(
            "/api/v1/work-items/%s/prepared-attempts/select" % work_item_id,
            json={
                "lease_id": "stale-lease",
                "reality_snapshot_id": "reality:%s" % suffix,
                "data_refs": ["data:account:%s" % suffix],
            },
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"] == "ACTIVE_WORK_ITEM_LEASE_REQUIRED"

        print({
            "status": "RC8_N5_LEASE_BOUND_PREPARED_ATTEMPT_HTTP_PASS",
            "test_run_id": run_id,
            "work_item_id": work_item_id,
            "case_id": case_id,
            "attempt_id": lease_id,
            "prepared_attempt_id": prepared_attempt_id,
            "mission_node_id": expected_mission_node_id,
            "truth_note": "PostgreSQL + Redis lease and R1-projected Center Attempt own N5 PreparedAttempt identity.",
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
