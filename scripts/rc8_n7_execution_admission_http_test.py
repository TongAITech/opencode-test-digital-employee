#!/usr/bin/env python3
"""Real PostgreSQL + Redis + R1 proof for N7 execution admission.

N7 may start only while the exact current N4 frozen case, N5 PreparedAttempt and
N6 READY ExecutableSpec agree. Admission is also rechecked on every runtime
write so a real runtime mutation cannot leave an already-running stale N7
attempt able to claim completion. This proves admission/invalidation authority;
it does not claim Maven/JUnit execution or test PASS.
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
from rc8_center.execution_admission import CenterN7ExecutionAdmissionGate
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
from rc8_center.n7_formal_control import N7AdmissionAwareFormalCenterControlPlane
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
        "operator_ref": "n7-admission-reality",
        "os_family": "linux",
        "architecture": "x86_64",
        "shell": "bash",
        "registered_at": 1,
    })


def _register_n7_work(
    client: TestClient,
    *,
    work_item_id: str,
    run_id: str,
    case_id: str,
    scope_version: str,
    case_revision_ref: str,
    inventory_ref: str,
    fingerprint_ref: str,
) -> None:
    _post(client, "/api/v1/work-items/register", {
        "work_item_id": work_item_id,
        "test_run_id": run_id,
        "stage": "APPLICABLE_LAYER_EXECUTION",
        "scope_refs": [scope_version, "case:%s" % case_id, case_revision_ref, inventory_ref, fingerprint_ref],
        "required_capabilities": [],
    })


def _lease(client: TestClient, *, work_item_id: str, node_id: str) -> str:
    leased = _post(client, "/api/v1/work-items/%s/lease" % work_item_id, {
        "node_id": node_id,
        "ttl_seconds": 180,
    })
    lease_id = leased["work_item"]["lease_id"]
    assert lease_id
    return lease_id


def main() -> int:
    suffix = uuid.uuid4().hex[:10]
    run_id = "n7-admission-%s" % suffix
    case_id = "CASE-N7-%s" % suffix
    case_revision_ref = "case-revision:%s:v1" % case_id
    scope_version = "scope:SST-N7@app-cfg-center@%s" % suffix
    n4_stage_id = "stage-n4-%s" % suffix
    n4_work_id = "work-n4-%s" % suffix
    n4_attempt_id = "attempt-n4-%s" % suffix
    n7_stage_id = "stage-n7-%s" % suffix
    n7_work_id = "work-n7-%s" % suffix
    stale_n7_work_id = "work-n7-stale-%s" % suffix
    n7_node_id = "node-n7-%s" % suffix

    postgres = PostgresStore(build_engine(os.environ["RC8_DATABASE_URL"]))
    redis = RedisCoordination.from_url(os.environ["RC8_REDIS_URL"], namespace="rc8-n7-admission-%s" % suffix)
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

    with tempfile.TemporaryDirectory(prefix="rc8-n7-admission-") as temp_dir:
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
        projector = ScopeAwareGovernanceEventProjector(ledger, governance_repository, coverage_repository, artifact_repository)
        core = FormalCenterControlPlane(control_repository, redis, ledger, projector)
        runtime_control = RuntimeMutationAwareFormalCenterControlPlane(core, mutation_producer)
        case_inventory_resolver = CenterFrozenCaseInventoryResolver(
            governance_repository=governance_repository,
            control_repository=control_repository,
            artifact_repository=artifact_repository,
            artifact_store=artifact_store,
        )
        admission = CenterN7ExecutionAdmissionGate(
            governance_repository=governance_repository,
            case_inventory_resolver=case_inventory_resolver,
            prepared_attempts=prepared_attempts,
            executable_readiness=executable_readiness,
        )
        formal_control = N7AdmissionAwareFormalCenterControlPlane(runtime_control, admission)
        app = create_app(
            postgres=postgres,
            redis_coordination=redis,
            governance_projection=GovernanceProjectionService(governance_repository, coverage_repository),
            formal_control=formal_control,
        )
        client = TestClient(app)

        postgres.create_test_run(run_id, payload={"truth_scope": "N7_EXECUTION_ADMISSION_REALITY"})
        _register_node(client, n7_node_id)

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
            producer_node_id=n7_node_id,
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
            node_id=n7_node_id,
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
        inventory = case_inventory_resolver.resolve(test_run_id=run_id, scope_version=scope_version)
        assert inventory.artifact_ref == inventory_ref
        assert inventory.fingerprint_ref == fingerprint_ref

        graph = MissionNodeAdoptionGraph(run_id, scope_version)
        n5_mission_node_id = graph.node(MissionNodeType.N5_TEST_DATA_PRECONDITIONS).mission_node_id
        n6_mission_node_id = graph.node(MissionNodeType.N6_SCRIPT_BUILD_READINESS).mission_node_id
        case_attempt_id = "case-attempt-%s" % suffix
        prepared_id = "prepared:%s" % case_attempt_id
        now = int(time.time())
        prepared_attempts.select(
            prepared_attempt_id=prepared_id,
            test_run_id=run_id,
            mission_node_id=n5_mission_node_id,
            case_id=case_id,
            attempt_id=case_attempt_id,
            reality_snapshot_id="reality:%s" % suffix,
            data_refs=["data:account:%s" % suffix],
        )
        prepared_attempts.verify(prepared_id, evidence_refs=["evidence:data-verify:%s" % suffix])
        prepared_attempts.reserve(
            prepared_id,
            reservation_ref="reservation:account:%s" % suffix,
            evidence_refs=["evidence:reservation:%s" % suffix],
        )
        prepared_attempts.freshness_check(
            prepared_id,
            data_freshness_ref="freshness:data:%s" % suffix,
            auth_session_ref="auth:4a:fresh:%s" % suffix,
            auth_acquired_at=max(0, now - 1),
            auth_expires_at=now + 600,
            evidence_refs=["evidence:fresh-auth:%s" % suffix],
        )
        prepared = prepared_attempts.bind(
            prepared_id,
            environment_ref="env:pfc:test:%s" % suffix,
            route_ref="route:browser-network:%s" % suffix,
            evidence_refs=["evidence:environment-route:%s" % suffix],
        )
        assert prepared.state == PreparedAttemptState.PREPARED

        executable_spec_id = "executable:%s" % prepared_id
        executable_readiness.build(
            executable_spec_id=executable_spec_id,
            test_run_id=run_id,
            mission_node_id=n6_mission_node_id,
            case_id=case_id,
            attempt_id=case_attempt_id,
            prepared_attempt_id=prepared_id,
            frozen_case_ref=case_revision_ref,
            driver_ref="driver:maven-junit:%s" % suffix,
            script_artifact_ref="artifact:test-script:%s" % suffix,
            fixture_binding_refs=["fixture:prepared:%s" % suffix],
            assertion_refs=["assertion:business:%s" % suffix],
            evidence_collector_refs=["collector:junit:%s" % suffix],
            build_evidence_refs=["evidence:script-build:%s" % suffix],
        )

        governance_repository.upsert_stage(StageInstance(
            stage_instance_id=n7_stage_id,
            test_run_id=run_id,
            stage_type="APPLICABLE_LAYER_EXECUTION",
            scope_version=scope_version,
            attempt_no=1,
            state=StageState.EXECUTING,
            assigned_worker="N7ExecutionWorker",
            started_at=100,
        ))
        _register_n7_work(
            client,
            work_item_id=n7_work_id,
            run_id=run_id,
            case_id=case_id,
            scope_version=scope_version,
            case_revision_ref=case_revision_ref,
            inventory_ref=inventory_ref,
            fingerprint_ref=fingerprint_ref,
        )
        control_repository.link_work_item_to_stage(
            work_item_id=n7_work_id,
            stage_instance_id=n7_stage_id,
            test_run_id=run_id,
            created_at=2,
        )
        n7_lease = _lease(client, work_item_id=n7_work_id, node_id=n7_node_id)

        blocked = client.post("/api/v1/work-items/%s/start" % n7_work_id, json={
            "node_id": n7_node_id,
            "lease_id": n7_lease,
        })
        assert blocked.status_code == 400, blocked.text
        assert blocked.json()["detail"] == "N7_REQUIRES_CURRENT_N6_READY:TEST_EXECUTION_REQUIRES_EXECUTABLE_READY"
        assert governance_repository.get_attempt(n7_lease) is None, "BLOCKED_N7_START_MUST_NOT_CREATE_ATTEMPT"
        assert not [
            event for event in ledger.runtime_events(test_run_id=run_id, work_item_id=n7_work_id)
            if str(event.get("event_type") or "") == "ATTEMPT_STARTED"
        ], "BLOCKED_N7_START_MUST_NOT_WRITE_R1_ATTEMPT_STARTED"

        executable_readiness.verify(
            executable_spec_id,
            semantic_evidence_refs=["evidence:semantic-contract:%s" % suffix, "evidence:assertion-map:%s" % suffix],
        )
        ready = executable_readiness.mark_ready(executable_spec_id)
        assert ready.state == ExecutableReadinessState.READY

        started = _post(client, "/api/v1/work-items/%s/start" % n7_work_id, {
            "node_id": n7_node_id,
            "lease_id": n7_lease,
        })
        assert started["work_item"]["state"] == "RUNNING"
        n7_attempt = governance_repository.get_attempt(n7_lease)
        assert n7_attempt is not None and n7_attempt.status == AttemptStatus.STARTED
        assert n7_attempt.work_item_id == n7_work_id
        assert n7_attempt.case_id == case_id
        assert n7_attempt.input_snapshot_ref == scope_version
        assert n7_attempt.attempt_id == n7_lease
        assert n7_attempt.attempt_id != case_attempt_id

        # A real runtime mutation is accepted while the N7 authority is still current.
        # The Center must persist the TOOL fact, record canonical invalidation in R1,
        # project it into durable N5/N6 state, and then reject every later stale write.
        mutation_event_id = "runtime-reality-changed-%s" % suffix
        mutation = _post(client, "/api/v1/runtime-events", {
            "lease_id": n7_lease,
            "event_id": mutation_event_id,
            "test_run_id": run_id,
            "work_item_id": n7_work_id,
            "node_id": n7_node_id,
            "producer_kind": "TOOL",
            "producer_ref": "runtime-reality-probe",
            "event_type": "REALITY_CHANGED",
            "sequence": ledger.latest_node_sequence(test_run_id=run_id, node_id=n7_node_id) + 1,
            "case_id": case_id,
            "attempt_id": case_attempt_id,
            "refs": ["evidence:reality-change:%s" % suffix],
            "data": {"observed_ref": "reality:%s:changed" % suffix},
            "occurred_at": int(time.time()),
        })
        invalidation = mutation.get("runtime_invalidation") or {}
        assert invalidation.get("status") == "PROJECTED", mutation
        invalidation_event_id = str(invalidation.get("invalidation_event_id") or "")
        assert invalidation_event_id

        recorded = [
            event for event in ledger.runtime_events(test_run_id=run_id)
            if str(event.get("event_id") or "") == invalidation_event_id
            and str(event.get("event_type") or "") == "INVALIDATION_RECORDED"
        ]
        assert len(recorded) == 1, "CANONICAL_R1_INVALIDATION_REQUIRED"
        recorded_data = recorded[0].get("data") if isinstance(recorded[0].get("data"), dict) else {}
        assert str(recorded_data.get("source_runtime_event_id") or "") == mutation_event_id
        assert str(recorded_data.get("reason") or "") == "REALITY_SNAPSHOT_BINDING_CHANGED"
        projected = [
            event for event in ledger.runtime_events(test_run_id=run_id)
            if str(event.get("event_type") or "") == "N5_N6_INVALIDATION_PROJECTED"
            and isinstance(event.get("data"), dict)
            and str(event["data"].get("source_event_id") or "") == invalidation_event_id
            and invalidation_event_id in tuple(event.get("refs") or ())
        ]
        assert len(projected) == 1, "CANONICAL_R1_INVALIDATION_PROJECTION_RECEIPT_REQUIRED"
        projected_data = projected[0]["data"]
        assert str(projected_data.get("prepared_attempt_id") or "") == prepared_id
        assert str(projected_data.get("executable_spec_id") or "") == executable_spec_id
        assert str(projected_data.get("reason") or "") == "REALITY_SNAPSHOT_BINDING_CHANGED"

        persisted_prepared = prepared_repository.get_prepared_attempt(prepared_id)
        assert persisted_prepared is not None and persisted_prepared.state == PreparedAttemptState.QUARANTINED
        persisted_executable = executable_repository.get_executable_spec(executable_spec_id)
        assert persisted_executable is not None and persisted_executable.state == ExecutableReadinessState.INVALIDATED

        stale_terminal_event_id = "stale-attempt-completed-%s" % suffix
        stale_terminal = client.post("/api/v1/runtime-events", json={
            "lease_id": n7_lease,
            "event_id": stale_terminal_event_id,
            "test_run_id": run_id,
            "work_item_id": n7_work_id,
            "node_id": n7_node_id,
            "producer_kind": "WORKER",
            "producer_ref": "worker:stale-n7",
            "event_type": "ATTEMPT_COMPLETED",
            "sequence": ledger.latest_node_sequence(test_run_id=run_id, node_id=n7_node_id) + 1,
            "case_id": case_id,
            "attempt_id": n7_lease,
            "refs": [],
            "data": {},
            "occurred_at": int(time.time()),
        })
        assert stale_terminal.status_code == 400, stale_terminal.text
        assert stale_terminal.json()["detail"] == "N7_REQUIRES_CURRENT_N5_PREPARED_ATTEMPT"
        assert not [
            event for event in ledger.runtime_events(test_run_id=run_id, work_item_id=n7_work_id)
            if str(event.get("event_id") or "") == stale_terminal_event_id
        ], "STALE_N7_TERMINAL_EVENT_MUST_NOT_REACH_R1"
        still_started = governance_repository.get_attempt(n7_lease)
        assert still_started is not None and still_started.status == AttemptStatus.STARTED

        # A fresh N7 WorkItem with the same stale N5/N6 authority is also blocked
        # before Center creates a new governance Attempt.
        _register_n7_work(
            client,
            work_item_id=stale_n7_work_id,
            run_id=run_id,
            case_id=case_id,
            scope_version=scope_version,
            case_revision_ref=case_revision_ref,
            inventory_ref=inventory_ref,
            fingerprint_ref=fingerprint_ref,
        )
        control_repository.link_work_item_to_stage(
            work_item_id=stale_n7_work_id,
            stage_instance_id=n7_stage_id,
            test_run_id=run_id,
            created_at=3,
        )
        stale_lease = _lease(client, work_item_id=stale_n7_work_id, node_id=n7_node_id)
        stale = client.post("/api/v1/work-items/%s/start" % stale_n7_work_id, json={
            "node_id": n7_node_id,
            "lease_id": stale_lease,
        })
        assert stale.status_code == 400, stale.text
        assert stale.json()["detail"] == "N7_REQUIRES_CURRENT_N5_PREPARED_ATTEMPT"
        assert governance_repository.get_attempt(stale_lease) is None, "STALE_N7_START_MUST_NOT_CREATE_ATTEMPT"

        print({
            "status": "RC8_N7_EXECUTION_ADMISSION_REALITY_PASS",
            "test_run_id": run_id,
            "case_id": case_id,
            "n4_inventory_ref": inventory_ref,
            "n5_case_execution_attempt_id": case_attempt_id,
            "n6_executable_spec_id": executable_spec_id,
            "n7_governance_attempt_id": n7_lease,
            "blocked_before_ready_without_attempt": True,
            "runtime_mutation_projected": True,
            "stale_running_terminal_write_blocked": True,
            "stale_identity_blocked_without_attempt": True,
            "truth_note": "N7 admission is Center-owned at start and runtime writes; real R1 invalidation blocks stale completion. Maven/JUnit execution is not claimed by this proof.",
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
