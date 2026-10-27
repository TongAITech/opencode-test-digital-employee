#!/usr/bin/env python3
"""Real PostgreSQL + Redis + R1 + HTTP proof for N7 result-tool authority.

This proof deliberately distinguishes a WorkItem lease from result-producing
tool authority. A node holding the real N7 lease cannot forge TOOL provenance
through the generic runtime/artifact APIs. Only a Center-issued invocation grant
for the current N6 driver/collector can publish assertion facts and evidence
that the deterministic N7 result evaluator may consume.

This is RC8 infrastructure reality, not bank Maven/JUnit/4A reality.
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
from rc8_center.executable_readiness import CenterExecutableReadinessService
from rc8_center.execution_admission import CenterN7ExecutionAdmissionGate
from rc8_center.formal_artifacts import FormalArtifactService
from rc8_center.formal_control import FormalCenterControlPlane
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
from rc8_center.n7_execution_result import CenterN7CaseExecutionResultAuthority, N7CaseExecutionOutcome
from rc8_center.n7_formal_control import N7AdmissionAwareFormalCenterControlPlane
from rc8_center.n7_tool_invocation import CenterN7ToolInvocationAuthority
from rc8_center.prepared_attempt import CenterPreparedAttemptService
from rc8_center.scope_aware_governance_projector import ScopeAwareGovernanceEventProjector
from rc8_runtime import CentralR1RuntimeLedger, RuntimeProducerKind, WorkItemIdentity
from rc8_runtime.artifacts import ArtifactManifest
from rc8_runtime.governance import AttemptRecord, AttemptStatus, StageInstance, StageState
from rc8_runtime.mission_nodes import MissionNodeAdoptionGraph, MissionNodeType


def _post_ok(client: TestClient, path: str, body: dict) -> dict:
    response = client.post(path, json=body)
    assert response.status_code == 200, "%s -> %s %s" % (path, response.status_code, response.text)
    return response.json()


def main() -> int:
    suffix = uuid.uuid4().hex[:10]
    run_id = "n7-tool-%s" % suffix
    case_id = "CASE-N7-TOOL-%s" % suffix
    scope_version = "scope:SST-N7-TOOL@app-cfg-center@%s" % suffix
    case_revision_ref = "case-revision:%s:v1" % case_id
    n4_stage_id = "stage-n4-tool-%s" % suffix
    n4_work_id = "work-n4-tool-%s" % suffix
    n4_attempt_id = "attempt-n4-tool-%s" % suffix
    n7_stage_id = "stage-n7-tool-%s" % suffix
    n7_work_id = "work-n7-tool-%s" % suffix
    node_id = "node-n7-tool-%s" % suffix
    case_attempt_id = "case-attempt-tool-%s" % suffix
    prepared_id = "prepared:%s" % case_attempt_id
    executable_spec_id = "executable:%s" % prepared_id
    driver_ref = "driver:maven-junit:%s" % suffix
    collector_ref = "collector:junit:%s" % suffix
    assertion_ref = "assertion:business:%s" % suffix

    postgres = PostgresStore(build_engine(os.environ["RC8_DATABASE_URL"]))
    redis = RedisCoordination.from_url(os.environ["RC8_REDIS_URL"], namespace="rc8-n7-tool-%s" % suffix)
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

    with tempfile.TemporaryDirectory(prefix="rc8-n7-tool-") as temp_dir:
        artifact_store = FileArtifactStore(str(Path(temp_dir) / "artifacts"), artifact_repository)
        ledger = CentralR1RuntimeLedger(str(Path(temp_dir) / "event-stream.jsonl"))
        projector = ScopeAwareGovernanceEventProjector(
            ledger,
            governance_repository,
            coverage_repository,
            artifact_repository,
        )
        core = FormalCenterControlPlane(control_repository, redis, ledger, projector)
        inventory_resolver = CenterFrozenCaseInventoryResolver(
            governance_repository=governance_repository,
            control_repository=control_repository,
            artifact_repository=artifact_repository,
            artifact_store=artifact_store,
        )
        admission_gate = CenterN7ExecutionAdmissionGate(
            governance_repository=governance_repository,
            case_inventory_resolver=inventory_resolver,
            prepared_attempts=prepared_attempts,
            executable_readiness=executable_readiness,
            artifact_store=None,
        )
        result_authority = CenterN7CaseExecutionResultAuthority(
            runtime_ledger=ledger,
            executable_readiness=executable_readiness,
            artifact_repository=artifact_repository,
        )
        tool_authority = CenterN7ToolInvocationAuthority(redis, executable_readiness)
        formal_control = N7AdmissionAwareFormalCenterControlPlane(
            core,
            admission_gate,
            result_authority,
            tool_authority,
        )
        artifact_service = FormalArtifactService(artifact_store, formal_control, projector)
        app = create_app(
            postgres=postgres,
            redis_coordination=redis,
            formal_control=formal_control,
            artifact_service=artifact_service,
        )
        app.state.control_repository = control_repository
        app.state.artifact_store = artifact_store
        app.state.n7_execution_admission = admission_gate
        app.state.n7_tool_invocation_authority = tool_authority
        client = TestClient(app)

        postgres.create_test_run(run_id, payload={"truth_scope": "N7_RESULT_TOOL_AUTHORITY_REALITY"})
        _post_ok(client, "/api/v1/nodes/register", {
            "node_id": node_id,
            "operator_ref": "n7-tool-authority-reality",
            "os_family": "linux",
            "architecture": "x86_64",
            "shell": "bash",
            "registered_at": 1,
        })

        # Build a real frozen N4 inventory backed by an AVAILABLE artifact.
        inventory_payload = {
            "schema_version": CASE_INVENTORY_SCHEMA,
            "test_run_id": run_id,
            "stage_instance_id": n4_stage_id,
            "scope_version": scope_version,
            "cases": [{"case_id": case_id, "case_revision_ref": case_revision_ref}],
        }
        inventory_bytes = json.dumps(inventory_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        inventory_sha = hashlib.sha256(inventory_bytes).hexdigest()
        inventory_artifact_id = "case-inventory-tool-%s" % suffix
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
            producer_node_id=node_id,
            producer_ref="N4TestDesignWorker",
            input_snapshot_ref=scope_version,
            status=AttemptStatus.COMPLETED,
            evidence_refs=(inventory_ref,),
            started_at=10,
            finished_at=20,
        ))
        inventory_manifest = ArtifactManifest(
            artifact_id=inventory_artifact_id,
            test_run_id=run_id,
            work_item_id=n4_work_id,
            node_id=node_id,
            kind=CASE_INVENTORY_KIND,
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="N4TestDesignWorker",
            file_name="case-inventory.json",
            sha256=inventory_sha,
            size_bytes=len(inventory_bytes),
            attempt_id=n4_attempt_id,
            metadata={"schema_version": CASE_INVENTORY_SCHEMA},
        )
        artifact_store.begin(inventory_manifest)
        artifact_store.upload_chunk(inventory_artifact_id, offset=0, data=inventory_bytes)
        artifact_store.complete(inventory_artifact_id)
        inventory = inventory_resolver.resolve(test_run_id=run_id, scope_version=scope_version)
        assert inventory.artifact_ref == inventory_ref
        assert inventory.fingerprint_ref == fingerprint_ref

        # Build real N5 PreparedAttempt and N6 READY executable authority.
        graph = MissionNodeAdoptionGraph(run_id, scope_version)
        n5_node_id = graph.node(MissionNodeType.N5_TEST_DATA_PRECONDITIONS).mission_node_id
        n6_node_id = graph.node(MissionNodeType.N6_SCRIPT_BUILD_READINESS).mission_node_id
        now = int(time.time())
        prepared_attempts.select(
            prepared_attempt_id=prepared_id,
            test_run_id=run_id,
            mission_node_id=n5_node_id,
            case_id=case_id,
            attempt_id=case_attempt_id,
            reality_snapshot_id="reality:%s" % suffix,
            data_refs=["data:account:%s" % suffix],
        )
        prepared_attempts.verify(prepared_id, evidence_refs=["evidence:data:%s" % suffix])
        prepared_attempts.reserve(
            prepared_id,
            reservation_ref="reservation:%s" % suffix,
            evidence_refs=["evidence:reservation:%s" % suffix],
        )
        prepared_attempts.freshness_check(
            prepared_id,
            data_freshness_ref="freshness:%s" % suffix,
            auth_session_ref="auth:4a:fresh:%s" % suffix,
            auth_acquired_at=max(0, now - 1),
            auth_expires_at=now + 600,
            evidence_refs=["evidence:fresh-auth:%s" % suffix],
        )
        prepared_attempts.bind(
            prepared_id,
            environment_ref="env:pfc:test:%s" % suffix,
            route_ref="route:browser-network:%s" % suffix,
            evidence_refs=["evidence:environment-route:%s" % suffix],
        )
        executable_readiness.build(
            executable_spec_id=executable_spec_id,
            test_run_id=run_id,
            mission_node_id=n6_node_id,
            case_id=case_id,
            attempt_id=case_attempt_id,
            prepared_attempt_id=prepared_id,
            frozen_case_ref=case_revision_ref,
            driver_ref=driver_ref,
            script_artifact_ref="artifact:test-script:%s" % suffix,
            fixture_binding_refs=["fixture:%s" % suffix],
            assertion_refs=[assertion_ref],
            evidence_collector_refs=[collector_ref],
            build_evidence_refs=["evidence:build:%s" % suffix],
        )
        executable_readiness.verify(executable_spec_id, semantic_evidence_refs=["evidence:semantic:%s" % suffix])
        executable_readiness.mark_ready(executable_spec_id)

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
        _post_ok(client, "/api/v1/work-items/register", {
            "work_item_id": n7_work_id,
            "test_run_id": run_id,
            "stage": "APPLICABLE_LAYER_EXECUTION",
            "scope_refs": [scope_version, "case:%s" % case_id, case_revision_ref, inventory_ref, fingerprint_ref],
            "required_capabilities": [],
        })
        control_repository.link_work_item_to_stage(
            work_item_id=n7_work_id,
            stage_instance_id=n7_stage_id,
            test_run_id=run_id,
            created_at=2,
        )
        leased = _post_ok(client, "/api/v1/work-items/%s/lease" % n7_work_id, {
            "node_id": node_id,
            "ttl_seconds": 180,
        })
        lease_id = leased["work_item"]["lease_id"]
        started = _post_ok(client, "/api/v1/work-items/%s/start" % n7_work_id, {
            "node_id": node_id,
            "lease_id": lease_id,
        })
        assert started["work_item"]["state"] == "RUNNING"

        work = control_repository.get_work_item(n7_work_id)
        admission = admission_gate.authorize_start(work=work, stage_instance_id=n7_stage_id)
        assert admission is not None
        grant = tool_authority.issue(admission, node_id=node_id, governance_lease_id=lease_id)
        assert grant.token

        def assertion_body(event_id: str, evidence_refs: list) -> dict:
            return {
                "lease_id": lease_id,
                "event_id": event_id,
                "test_run_id": run_id,
                "work_item_id": n7_work_id,
                "node_id": node_id,
                "producer_kind": "TOOL",
                "producer_ref": driver_ref,
                "event_type": "ASSERTION_OBSERVED",
                "sequence": ledger.latest_node_sequence(test_run_id=run_id, node_id=node_id) + 1,
                "case_id": case_id,
                "attempt_id": case_attempt_id,
                "step_id": "assertion-step-1",
                "refs": [assertion_ref],
                "data": {
                    "assertion_ref": assertion_ref,
                    "outcome": "PASS",
                    "evidence_refs": evidence_refs,
                },
                "occurred_at": int(time.time()),
            }

        # Holding the real WorkItem lease is deliberately insufficient.
        forged_id = "forged-tool-pass-%s" % suffix
        forged = client.post("/api/v1/runtime-events", json=assertion_body(forged_id, []))
        assert forged.status_code == 400, forged.text
        assert forged.json()["detail"] == "N7_RESULT_TOOL_INVOCATION_AUTHORITY_REQUIRED"
        assert not [e for e in ledger.runtime_events(test_run_id=run_id) if e.get("event_id") == forged_id]

        wrong_id = "wrong-token-pass-%s" % suffix
        wrong = client.post(
            "/api/v1/n7/tool-runtime-events",
            json=assertion_body(wrong_id, []),
            headers={"X-RC8-N7-Tool-Invocation-Token": "wrong-token"},
        )
        assert wrong.status_code == 409, wrong.text
        assert wrong.json()["detail"] == "N7_TOOL_INVOCATION_TOKEN_MISMATCH"
        assert not [e for e in ledger.runtime_events(test_run_id=run_id) if e.get("event_id") == wrong_id]

        observed_id = "authorized-observation-%s" % suffix
        observed = client.post(
            "/api/v1/n7/tool-runtime-events",
            json=assertion_body(observed_id, []),
            headers={"X-RC8-N7-Tool-Invocation-Token": grant.token},
        )
        assert observed.status_code == 200, observed.text
        assert [e for e in ledger.runtime_events(test_run_id=run_id) if e.get("event_id") == observed_id]
        pending = result_authority.evaluate(admission)
        assert pending.outcome == N7CaseExecutionOutcome.PENDING

        # The same spoof rule applies to evidence manifests. Generic begin has
        # the real WorkItem lease but no invocation grant and must fail closed.
        evidence_bytes = b"real-n7-tool-evidence\n"
        evidence_sha = hashlib.sha256(evidence_bytes).hexdigest()
        evidence_id = "n7-tool-evidence-%s" % suffix
        artifact_body = {
            "lease_id": lease_id,
            "artifact_id": evidence_id,
            "test_run_id": run_id,
            "work_item_id": n7_work_id,
            "node_id": node_id,
            "kind": "N7_CASE_EXECUTION_EVIDENCE",
            "producer_kind": "TOOL",
            "producer_ref": driver_ref,
            "file_name": "assertion.txt",
            "sha256": evidence_sha,
            "size_bytes": len(evidence_bytes),
            "case_id": case_id,
            "attempt_id": case_attempt_id,
            "step_id": "assertion-step-1",
            "refs": [assertion_ref],
            "metadata": {"assertion_ref": assertion_ref},
            "created_at": int(time.time()),
        }
        forged_artifact = client.post("/api/v1/artifacts/begin", json=artifact_body)
        assert forged_artifact.status_code == 400, forged_artifact.text
        assert forged_artifact.json()["detail"] == "N7_RESULT_TOOL_INVOCATION_AUTHORITY_REQUIRED"
        assert artifact_repository.get(evidence_id) is None

        begun = client.post(
            "/api/v1/n7/tool-artifacts/begin",
            json=artifact_body,
            headers={"X-RC8-N7-Tool-Invocation-Token": grant.token},
        )
        assert begun.status_code == 201, begun.text
        uploaded = client.put(
            "/api/v1/artifacts/%s/content?offset=0" % evidence_id,
            content=evidence_bytes,
            headers={
                "Content-Type": "application/octet-stream",
                "X-RC8-Node-Id": node_id,
                "X-RC8-Lease-Id": lease_id,
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        completed_artifact = client.post(
            "/api/v1/artifacts/%s/complete" % evidence_id,
            json={"node_id": node_id, "lease_id": lease_id},
        )
        assert completed_artifact.status_code == 200, completed_artifact.text
        assert completed_artifact.json()["manifest"]["availability"] == "AVAILABLE"

        final_observation_id = "authorized-pass-with-evidence-%s" % suffix
        final_observation = client.post(
            "/api/v1/n7/tool-runtime-events",
            json=assertion_body(final_observation_id, ["artifact:%s" % evidence_id]),
            headers={"X-RC8-N7-Tool-Invocation-Token": grant.token},
        )
        assert final_observation.status_code == 200, final_observation.text

        result = result_authority.evaluate(admission)
        assert result.outcome == N7CaseExecutionOutcome.PASS, result
        assert result.evidence_refs == (evidence_id,)
        completed = _post_ok(client, "/api/v1/work-items/%s/complete" % n7_work_id, {
            "node_id": node_id,
            "lease_id": lease_id,
        })
        assert completed["work_item"]["state"] == "COMPLETED"

        print("N7_RESULT_TOOL_AUTHORITY_REALITY=PASS")
        print("GENERIC_TOOL_SPOOF=REJECTED")
        print("WRONG_INVOCATION_TOKEN=REJECTED")
        print("AUTHORIZED_ASSERTION_R1=%s" % final_observation_id)
        print("AUTHORIZED_EVIDENCE_AVAILABLE=%s" % evidence_id)
        print("CENTER_DERIVED_CASE_RESULT=%s" % result.outcome.value)
        print("TRUTH_NOTE=REAL_POSTGRESQL_REDIS_R1_HTTP_NOT_BANK_EXECUTION_REALITY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
