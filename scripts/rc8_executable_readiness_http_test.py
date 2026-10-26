#!/usr/bin/env python3
"""Real PostgreSQL + Redis + R1 proof for the N5 -> N6 build authority boundary."""
from __future__ import annotations

import os
import tempfile
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from rc8_center.api import create_app
from rc8_center.executable_readiness import CenterExecutableReadinessService, ExecutableReadinessState
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
from rc8_center.prepared_attempt import CenterPreparedAttemptService, PreparedAttemptState
from rc8_center.runtime_invalidation import CenterRuntimeInvalidationCoordinator
from rc8_center.runtime_invalidation_projector import CenterRuntimeInvalidationProjector
from rc8_center.runtime_invalidation_recorder import CenterRuntimeInvalidationRecorder
from rc8_center.runtime_invalidation_service import CenterRuntimeInvalidationService
from rc8_center.runtime_mutation_producer import CenterRuntimeMutationProducer, RuntimeMutationAwareFormalCenterControlPlane
from rc8_center.scope_aware_governance_projector import ScopeAwareGovernanceEventProjector
from rc8_runtime import CentralR1RuntimeLedger
from rc8_runtime.governance import AttemptStatus, StageInstance, StageState
from rc8_runtime.mission_nodes import MissionNodeAdoptionGraph, MissionNodeType


def _post(client: TestClient, path: str, body: dict) -> dict:
    response = client.post(path, json=body)
    assert response.status_code == 200, "%s -> %s %s" % (path, response.status_code, response.text)
    return response.json()


def _register_node(client: TestClient, node_id: str) -> None:
    _post(client, "/api/v1/nodes/register", {
        "node_id": node_id,
        "operator_ref": "n6-http-integration",
        "os_family": "linux",
        "architecture": "x86_64",
        "shell": "bash",
        "registered_at": 1,
    })


def _register_work(client: TestClient, *, work_item_id: str, run_id: str, stage: str, case_id: str, scope_version: str) -> None:
    _post(client, "/api/v1/work-items/register", {
        "work_item_id": work_item_id,
        "test_run_id": run_id,
        "stage": stage,
        "scope_refs": ["case:%s" % case_id, scope_version],
        "required_capabilities": [],
    })


def _lease_start(client: TestClient, *, work_item_id: str, node_id: str) -> str:
    leased = _post(client, "/api/v1/work-items/%s/lease" % work_item_id, {
        "node_id": node_id,
        "ttl_seconds": 180,
    })
    lease_id = leased["work_item"]["lease_id"]
    assert lease_id
    started = _post(client, "/api/v1/work-items/%s/start" % work_item_id, {
        "node_id": node_id,
        "lease_id": lease_id,
    })
    assert started["work_item"]["state"] == "RUNNING"
    return lease_id


def main() -> int:
    suffix = uuid.uuid4().hex[:10]
    run_id = "n6-http-%s" % suffix
    case_id = "CASE-N6-%s" % suffix
    scope_version = "scope:SST-N6@app-cfg-center@%s" % suffix
    n5_stage_id = "stage-n5-%s" % suffix
    n6_stage_id = "stage-n6-%s" % suffix
    n5_work_id = "work-n5-%s" % suffix
    n6_work_id = "work-n6-%s" % suffix
    n5_node_id = "node-n5-%s" % suffix
    n6_node_id = "node-n6-%s" % suffix

    postgres = PostgresStore(build_engine(os.environ["RC8_DATABASE_URL"]))
    redis = RedisCoordination.from_url(os.environ["RC8_REDIS_URL"], namespace="rc8-n6-http-%s" % suffix)
    assert postgres.ping(), "POSTGRES_PING_FAILED"
    assert redis.ping(), "REDIS_PING_FAILED"

    governance_repository = PostgresGovernanceRepository(postgres)
    coverage_repository = PostgresCoverageRepository(postgres)
    artifact_repository = PostgresArtifactRepository(postgres)
    control_repository = PostgresCenterRepository(postgres)
    prepared_repository = PostgresPreparedAttemptRepository(postgres)
    executable_repository = PostgresExecutableSpecRepository(postgres)
    prepared_attempts = CenterPreparedAttemptService(prepared_repository)
    executable_readiness = CenterExecutableReadinessService(executable_repository, prepared_attempts)

    with tempfile.TemporaryDirectory(prefix="rc8-n6-http-") as temp_dir:
        ledger = CentralR1RuntimeLedger(str(Path(temp_dir) / "event-stream.jsonl"))
        invalidation_coordinator = CenterRuntimeInvalidationCoordinator(prepared_attempts, executable_readiness)
        invalidation_projector = CenterRuntimeInvalidationProjector(ledger, invalidation_coordinator)
        invalidation_service = CenterRuntimeInvalidationService(
            recorder=CenterRuntimeInvalidationRecorder(ledger),
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
        core = FormalCenterControlPlane(control_repository, redis, ledger, projector)
        formal_control = RuntimeMutationAwareFormalCenterControlPlane(core, mutation_producer)
        app = create_app(
            postgres=postgres,
            redis_coordination=redis,
            governance_projection=GovernanceProjectionService(governance_repository, coverage_repository),
            formal_control=formal_control,
        )
        app.state.control_repository = control_repository
        app.state.governance_repository = governance_repository
        app.state.prepared_attempts = prepared_attempts
        app.state.prepared_attempt_repository = prepared_repository
        app.state.executable_readiness = executable_readiness
        app.state.executable_spec_repository = executable_repository
        client = TestClient(app)

        postgres.create_test_run(run_id, payload={"truth_scope": "N5_TO_N6_IDENTITY_SPLIT_REALITY"})
        governance_repository.upsert_stage(StageInstance(
            stage_instance_id=n5_stage_id,
            test_run_id=run_id,
            stage_type="PRECONDITION_DATA_PREP",
            scope_version=scope_version,
            attempt_no=1,
            state=StageState.EXECUTING,
            assigned_worker="N5PreparedAttemptWorker",
            started_at=100,
        ))
        governance_repository.upsert_stage(StageInstance(
            stage_instance_id=n6_stage_id,
            test_run_id=run_id,
            stage_type="EXECUTABLE_SPEC",
            scope_version=scope_version,
            attempt_no=1,
            state=StageState.EXECUTING,
            assigned_worker="N6ExecutableReadinessWorker",
            started_at=101,
        ))

        _register_node(client, n5_node_id)
        _register_node(client, n6_node_id)
        _register_work(client, work_item_id=n5_work_id, run_id=run_id, stage="PRECONDITION_DATA_PREP", case_id=case_id, scope_version=scope_version)
        _register_work(client, work_item_id=n6_work_id, run_id=run_id, stage="EXECUTABLE_SPEC", case_id=case_id, scope_version=scope_version)
        control_repository.link_work_item_to_stage(work_item_id=n5_work_id, stage_instance_id=n5_stage_id, test_run_id=run_id, created_at=2)
        control_repository.link_work_item_to_stage(work_item_id=n6_work_id, stage_instance_id=n6_stage_id, test_run_id=run_id, created_at=3)

        n5_lease = _lease_start(client, work_item_id=n5_work_id, node_id=n5_node_id)
        selected = _post(client, "/api/v1/work-items/%s/prepared-attempts/select" % n5_work_id, {
            "lease_id": n5_lease,
            "reality_snapshot_id": "reality:%s" % suffix,
            "data_refs": ["data:account:%s" % suffix],
        })
        prepared_id = selected["prepared_attempt"]["prepared_attempt_id"]
        assert selected["prepared_attempt"]["state"] == "SELECTED"
        assert selected["prepared_attempt"]["attempt_id"] == n5_lease

        n6_lease = _lease_start(client, work_item_id=n6_work_id, node_id=n6_node_id)
        assert n6_lease != n5_lease, "N6_GOVERNANCE_ATTEMPT_MUST_DIFFER_FROM_CASE_EXECUTION_ATTEMPT"
        n6_attempt = governance_repository.get_attempt(n6_lease)
        assert n6_attempt is not None and n6_attempt.status == AttemptStatus.STARTED
        assert n6_attempt.work_item_id == n6_work_id
        assert n6_attempt.case_id == case_id
        assert n6_attempt.input_snapshot_ref == scope_version

        build_body = {
            "lease_id": n6_lease,
            "frozen_case_ref": "case-artifact:%s" % case_id,
            "driver_ref": "driver:pytest-junit:%s" % suffix,
            "script_artifact_ref": "artifact:test-script:%s" % suffix,
            "fixture_binding_refs": ["fixture:prepared:%s" % suffix],
            "assertion_refs": ["assertion:business:%s" % suffix],
            "evidence_collector_refs": ["collector:junit:%s" % suffix],
            "build_evidence_refs": ["evidence:script-build:%s" % suffix],
        }

        # N6 may have its own valid lease and STARTED governance Attempt, but it
        # still cannot build while the case execution attempt is only SELECTED.
        blocked = client.post("/api/v1/work-items/%s/executable-specs/build" % n6_work_id, json=build_body)
        assert blocked.status_code == 400, blocked.text
        assert blocked.json()["detail"] == "N6_REQUIRES_N5_PREPARED_STATE"

        _post(client, "/api/v1/work-items/%s/prepared-attempts/verify" % n5_work_id, {
            "lease_id": n5_lease,
            "evidence_refs": ["evidence:data-verify:%s" % suffix],
        })
        _post(client, "/api/v1/work-items/%s/prepared-attempts/reserve" % n5_work_id, {
            "lease_id": n5_lease,
            "reservation_ref": "reservation:customer:%s" % suffix,
            "evidence_refs": ["evidence:reservation:%s" % suffix],
        })
        now = int(time.time())
        _post(client, "/api/v1/work-items/%s/prepared-attempts/freshness-check" % n5_work_id, {
            "lease_id": n5_lease,
            "data_freshness_ref": "freshness:data:%s" % suffix,
            "auth_session_ref": "auth:4a:fresh:%s" % suffix,
            "auth_acquired_at": max(0, now - 1),
            "auth_expires_at": now + 600,
            "evidence_refs": ["evidence:fresh-auth:%s" % suffix],
        })
        prepared = _post(client, "/api/v1/work-items/%s/prepared-attempts/bind" % n5_work_id, {
            "lease_id": n5_lease,
            "environment_ref": "env:pfc:test:%s" % suffix,
            "route_ref": "route:browser-network:%s" % suffix,
            "evidence_refs": ["evidence:environment-route:%s" % suffix],
        })
        assert prepared["prepared_attempt"]["state"] == "PREPARED"
        persisted_prepared = prepared_repository.get_prepared_attempt(prepared_id)
        assert persisted_prepared is not None and persisted_prepared.state == PreparedAttemptState.PREPARED

        forged = dict(build_body)
        forged["attempt_id"] = n6_lease
        forged_response = client.post("/api/v1/work-items/%s/executable-specs/build" % n6_work_id, json=forged)
        assert forged_response.status_code == 422, forged_response.text

        built = _post(client, "/api/v1/work-items/%s/executable-specs/build" % n6_work_id, build_body)
        spec = built["executable_spec"]
        executable_spec_id = "executable:%s" % prepared_id
        expected_n6_mission_node = MissionNodeAdoptionGraph(run_id, scope_version).node(
            MissionNodeType.N6_SCRIPT_BUILD_READINESS
        ).mission_node_id
        assert built["n6_governance_attempt_id"] == n6_lease
        assert built["case_execution_attempt_id"] == n5_lease
        assert built["n6_governance_attempt_id"] != built["case_execution_attempt_id"]
        assert spec["executable_spec_id"] == executable_spec_id
        assert spec["state"] == "BUILT"
        assert spec["test_run_id"] == run_id
        assert spec["mission_node_id"] == expected_n6_mission_node
        assert spec["case_id"] == case_id
        assert spec["attempt_id"] == n5_lease
        assert spec["attempt_id"] != n6_lease
        assert spec["prepared_attempt_id"] == prepared_id

        persisted_spec = executable_repository.get_executable_spec(executable_spec_id)
        assert persisted_spec is not None
        assert persisted_spec.state == ExecutableReadinessState.BUILT
        assert persisted_spec.attempt_id == n5_lease
        assert persisted_spec.prepared_attempt_id == prepared_id
        assert persisted_spec.mission_node_id == expected_n6_mission_node

        stale = dict(build_body)
        stale["lease_id"] = "stale-n6-lease"
        stale_response = client.post("/api/v1/work-items/%s/executable-specs/build" % n6_work_id, json=stale)
        assert stale_response.status_code == 409, stale_response.text
        assert stale_response.json()["detail"] == "ACTIVE_WORK_ITEM_LEASE_REQUIRED"

        print({
            "status": "RC8_N6_LEASE_BOUND_BUILD_HTTP_PASS",
            "test_run_id": run_id,
            "case_id": case_id,
            "n5_case_execution_attempt_id": n5_lease,
            "n6_governance_attempt_id": n6_lease,
            "prepared_attempt_id": prepared_id,
            "executable_spec_id": executable_spec_id,
            "truth_note": "N6 governance lease authorizes build while N5 PreparedAttempt retains case execution identity.",
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
