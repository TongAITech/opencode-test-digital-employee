#!/usr/bin/env python3
"""Real PostgreSQL + Redis + R1 proof for N4 -> N5 -> N6 readiness authority.

The proof uses a hash-verified AVAILABLE N4 case inventory, a lease-bound N5
PreparedAttempt and a distinct Center-owned N6 governance Attempt. N6 must
consume the N4 frozen case revision and the N5 case-execution Attempt; neither
identity may be chosen by the Worker.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from rc8_center.api import create_app
from rc8_center.artifacts import FileArtifactStore
from rc8_center.case_inventory import CASE_INVENTORY_KIND, CASE_INVENTORY_SCHEMA, CenterFrozenCaseInventoryResolver
from rc8_center.control_plane import WorkItemRecord, WorkItemState
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
from rc8_runtime import CentralR1RuntimeLedger, RuntimeProducerKind, WorkItemIdentity
from rc8_runtime.artifacts import ArtifactManifest
from rc8_runtime.governance import AttemptRecord, AttemptStatus, StageInstance, StageState
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


def _register_work(
    client: TestClient,
    *,
    work_item_id: str,
    run_id: str,
    stage: str,
    case_id: str,
    scope_version: str,
    case_revision_ref: str,
    inventory_ref: str,
    fingerprint_ref: str,
) -> None:
    _post(client, "/api/v1/work-items/register", {
        "work_item_id": work_item_id,
        "test_run_id": run_id,
        "stage": stage,
        "scope_refs": [
            scope_version,
            "case:%s" % case_id,
            case_revision_ref,
            inventory_ref,
            fingerprint_ref,
        ],
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
    case_revision_ref = "case-revision:%s:v3" % case_id
    scope_version = "scope:SST-N6@app-cfg-center@%s" % suffix
    n4_stage_id = "stage-n4-%s" % suffix
    n4_work_id = "work-n4-%s" % suffix
    n4_attempt_id = "attempt-n4-%s" % suffix
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
        artifact_store = FileArtifactStore(str(Path(temp_dir) / "artifacts"), artifact_repository)
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
        case_inventory_resolver = CenterFrozenCaseInventoryResolver(
            governance_repository=governance_repository,
            control_repository=control_repository,
            artifact_repository=artifact_repository,
            artifact_store=artifact_store,
        )
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
        app.state.artifact_store = artifact_store
        app.state.case_inventory_resolver = case_inventory_resolver
        client = TestClient(app)

        postgres.create_test_run(run_id, payload={"truth_scope": "N4_N5_N6_READY_REALITY"})
        _register_node(client, n5_node_id)
        _register_node(client, n6_node_id)

        # N4 frozen inventory authority: completed design Stage + completed
        # Attempt + AVAILABLE artifact whose bytes match the declared SHA-256.
        inventory_payload = {
            "schema_version": CASE_INVENTORY_SCHEMA,
            "test_run_id": run_id,
            "stage_instance_id": n4_stage_id,
            "scope_version": scope_version,
            "cases": [{"case_id": case_id, "case_revision_ref": case_revision_ref}],
        }
        inventory_bytes = json.dumps(inventory_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        inventory_sha = hashlib.sha256(inventory_bytes).hexdigest()
        inventory_artifact_id = "case-inventory-%s" % suffix
        inventory_ref = "artifact:%s" % inventory_artifact_id
        fingerprint_ref = "case-inventory-sha256:%s" % inventory_sha

        governance_repository.upsert_stage(StageInstance(
            stage_instance_id=n4_stage_id,
            test_run_id=run_id,
            stage_type="TEST_DESIGN",
            scope_version=scope_version,
            attempt_no=1,
            state=StageState.COMPLETED,
            output_refs=(inventory_ref,),
            assigned_worker="N4TestDesignWorker",
            started_at=10,
            finished_at=20,
        ))
        control_repository.upsert_work_item(WorkItemRecord(
            identity=WorkItemIdentity(
                work_item_id=n4_work_id,
                test_run_id=run_id,
                stage="TEST_DESIGN",
                scope_refs=[scope_version],
                required_capabilities=[],
            ),
            state=WorkItemState.COMPLETED,
        ))
        control_repository.link_work_item_to_stage(
            work_item_id=n4_work_id,
            stage_instance_id=n4_stage_id,
            test_run_id=run_id,
            created_at=1,
        )
        governance_repository.upsert_attempt(AttemptRecord(
            attempt_id=n4_attempt_id,
            test_run_id=run_id,
            stage_instance_id=n4_stage_id,
            work_item_id=n4_work_id,
            producer_node_id=n5_node_id,
            producer_ref="N4TestDesignWorker",
            input_snapshot_ref=scope_version,
            status=AttemptStatus.COMPLETED,
            evidence_refs=(inventory_ref,),
            started_at=10,
            finished_at=20,
        ))
        manifest = ArtifactManifest(
            artifact_id=inventory_artifact_id,
            test_run_id=run_id,
            work_item_id=n4_work_id,
            node_id=n5_node_id,
            kind=CASE_INVENTORY_KIND,
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="N4TestDesignWorker",
            file_name="case-inventory.json",
            sha256=inventory_sha,
            size_bytes=len(inventory_bytes),
            attempt_id=n4_attempt_id,
            metadata={"schema_version": CASE_INVENTORY_SCHEMA},
        )
        artifact_store.begin(manifest)
        artifact_store.upload_chunk(inventory_artifact_id, offset=0, data=inventory_bytes)
        assert artifact_store.complete(inventory_artifact_id).availability.value == "AVAILABLE"
        resolved_inventory = case_inventory_resolver.resolve(test_run_id=run_id, scope_version=scope_version)
        assert resolved_inventory.artifact_ref == inventory_ref
        assert resolved_inventory.fingerprint_ref == fingerprint_ref
        assert resolved_inventory.cases[0].case_revision_ref == case_revision_ref

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

        _register_work(
            client,
            work_item_id=n5_work_id,
            run_id=run_id,
            stage="PRECONDITION_DATA_PREP",
            case_id=case_id,
            scope_version=scope_version,
            case_revision_ref=case_revision_ref,
            inventory_ref=inventory_ref,
            fingerprint_ref=fingerprint_ref,
        )
        _register_work(
            client,
            work_item_id=n6_work_id,
            run_id=run_id,
            stage="EXECUTABLE_SPEC",
            case_id=case_id,
            scope_version=scope_version,
            case_revision_ref=case_revision_ref,
            inventory_ref=inventory_ref,
            fingerprint_ref=fingerprint_ref,
        )
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
            "driver_ref": "driver:pytest-junit:%s" % suffix,
            "script_artifact_ref": "artifact:test-script:%s" % suffix,
            "fixture_binding_refs": ["fixture:prepared:%s" % suffix],
            "assertion_refs": ["assertion:business:%s" % suffix],
            "evidence_collector_refs": ["collector:junit:%s" % suffix],
            "build_evidence_refs": ["evidence:script-build:%s" % suffix],
        }

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

        # Worker cannot choose the N5 execution Attempt or the N4 frozen case.
        forged = dict(build_body)
        forged["attempt_id"] = n6_lease
        forged["frozen_case_ref"] = "forged-case-revision"
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
        assert built["case_inventory_ref"] == inventory_ref
        assert built["case_inventory_fingerprint_ref"] == fingerprint_ref
        assert built["n6_governance_attempt_id"] != built["case_execution_attempt_id"]
        assert spec["executable_spec_id"] == executable_spec_id
        assert spec["state"] == "BUILT"
        assert spec["mission_node_id"] == expected_n6_mission_node
        assert spec["attempt_id"] == n5_lease
        assert spec["attempt_id"] != n6_lease
        assert spec["prepared_attempt_id"] == prepared_id
        assert spec["frozen_case_ref"] == case_revision_ref

        repeated = _post(client, "/api/v1/work-items/%s/executable-specs/build" % n6_work_id, build_body)
        assert repeated["executable_spec"]["executable_spec_id"] == executable_spec_id
        changed_body = dict(build_body)
        changed_body["script_artifact_ref"] = "artifact:test-script:changed:%s" % suffix
        changed = client.post("/api/v1/work-items/%s/executable-specs/build" % n6_work_id, json=changed_body)
        assert changed.status_code == 409, changed.text
        assert changed.json()["detail"] == "EXECUTABLE_SPEC_ID_CONFLICT"

        premature_ready = client.post(
            "/api/v1/work-items/%s/executable-specs/ready" % n6_work_id,
            json={"lease_id": n6_lease},
        )
        assert premature_ready.status_code == 400, premature_ready.text
        assert premature_ready.json()["detail"] == "EXECUTABLE_SPEC_STATE_REQUIRED:VERIFIED"

        forged_verify = client.post(
            "/api/v1/work-items/%s/executable-specs/verify" % n6_work_id,
            json={
                "lease_id": n6_lease,
                "semantic_evidence_refs": ["evidence:semantic:%s" % suffix],
                "executable_spec_id": "forged-executable",
            },
        )
        assert forged_verify.status_code == 422, forged_verify.text

        verified = _post(client, "/api/v1/work-items/%s/executable-specs/verify" % n6_work_id, {
            "lease_id": n6_lease,
            "semantic_evidence_refs": [
                "evidence:semantic-contract:%s" % suffix,
                "evidence:assertion-map:%s" % suffix,
            ],
        })
        verified_spec = verified["executable_spec"]
        assert verified["transition"] == "VERIFIED"
        assert verified_spec["state"] == "VERIFIED"
        assert verified["n6_governance_attempt_id"] == n6_lease
        assert verified["case_execution_attempt_id"] == n5_lease
        assert verified["case_inventory_ref"] == inventory_ref
        assert verified_spec["attempt_id"] == n5_lease

        ready = _post(client, "/api/v1/work-items/%s/executable-specs/ready" % n6_work_id, {
            "lease_id": n6_lease,
        })
        ready_spec = ready["executable_spec"]
        assert ready["transition"] == "READY"
        assert ready_spec["state"] == "READY"
        assert ready["n6_governance_attempt_id"] == n6_lease
        assert ready["case_execution_attempt_id"] == n5_lease
        assert ready["case_inventory_fingerprint_ref"] == fingerprint_ref
        assert ready_spec["attempt_id"] == n5_lease
        assert ready_spec["attempt_id"] != n6_lease

        persisted_spec = executable_repository.get_executable_spec(executable_spec_id)
        assert persisted_spec is not None
        assert persisted_spec.state == ExecutableReadinessState.READY
        assert persisted_spec.attempt_id == n5_lease
        assert persisted_spec.prepared_attempt_id == prepared_id
        assert persisted_spec.mission_node_id == expected_n6_mission_node
        assert persisted_spec.frozen_case_ref == case_revision_ref
        assert persisted_spec.semantic_evidence_refs == (
            "evidence:semantic-contract:%s" % suffix,
            "evidence:assertion-map:%s" % suffix,
        )

        execution_ready = executable_readiness.require_ready_for_execution(
            executable_spec_id=executable_spec_id,
            prepared_attempt_id=prepared_id,
            test_run_id=run_id,
            case_id=case_id,
            attempt_id=n5_lease,
        )
        assert execution_ready.state == ExecutableReadinessState.READY
        assert execution_ready.attempt_id == n5_lease

        stale = client.post(
            "/api/v1/work-items/%s/executable-specs/ready" % n6_work_id,
            json={"lease_id": "stale-n6-lease"},
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"] == "ACTIVE_WORK_ITEM_LEASE_REQUIRED"

        print({
            "status": "RC8_N6_FROZEN_CASE_AUTHORITY_READY_HTTP_PASS",
            "test_run_id": run_id,
            "case_id": case_id,
            "n4_inventory_ref": inventory_ref,
            "n4_inventory_fingerprint_ref": fingerprint_ref,
            "n5_case_execution_attempt_id": n5_lease,
            "n6_governance_attempt_id": n6_lease,
            "prepared_attempt_id": prepared_id,
            "executable_spec_id": executable_spec_id,
            "executable_state": persisted_spec.state.value,
            "truth_note": "N4 owns frozen case identity, N5 owns case execution identity, and N6 lease only authorizes readiness transitions.",
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
