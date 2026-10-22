#!/usr/bin/env python3
from __future__ import annotations

import hashlib
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
from rc8_center.artifacts import FileArtifactStore
from rc8_center.formal_artifacts import FormalArtifactService
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
from rc8_runtime import CentralR1RuntimeLedger
from rc8_runtime.governance import StageInstance, StageState


def runtime_payload(*, lease_id: str, event_id: str, run_id: str, work_item_id: str,
                    event_type: str, sequence: int, attempt_id: str, data: dict) -> dict:
    return {
        "lease_id": lease_id,
        "event_id": event_id,
        "test_run_id": run_id,
        "work_item_id": work_item_id,
        "node_id": "node-artifact-it",
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
    with tempfile.TemporaryDirectory(prefix="rc8-formal-artifact-it-") as temp_dir:
        temp = Path(temp_dir)
        settings = CenterSettings(
            database_url=os.environ["RC8_DATABASE_URL"],
            redis_url=os.environ["RC8_REDIS_URL"],
            environment="integration-test",
            artifact_root=str(temp / "artifacts"),
            r1_root=str(temp / "r1"),
            artifact_chunk_max_bytes=1024 * 1024,
        )
        postgres = PostgresStore(build_engine(settings.database_url))
        redis = RedisCoordination.from_url(settings.redis_url, namespace="rc8-artifact-it-%s" % uuid.uuid4().hex[:8])
        governance_repository = PostgresGovernanceRepository(postgres)
        coverage_repository = PostgresCoverageRepository(postgres)
        artifact_repository = PostgresArtifactRepository(postgres)
        control_repository = PostgresCenterRepository(postgres)
        projection = GovernanceProjectionService(governance_repository, coverage_repository)

        ledger_path = str(temp / "r1" / "event-stream.jsonl")
        ledger = CentralR1RuntimeLedger(ledger_path)
        projector = GovernanceEventProjector(ledger, governance_repository, coverage_repository, artifact_repository)
        control = FormalCenterControlPlane(control_repository, redis, ledger, projector)
        artifact_store = FileArtifactStore(settings.artifact_root, artifact_repository)
        artifact_service = FormalArtifactService(artifact_store, control, projector)
        app = create_app(
            settings=settings,
            postgres=postgres,
            redis_coordination=redis,
            governance_projection=projection,
            formal_control=control,
            artifact_service=artifact_service,
        )
        client = TestClient(app)

        run_id = "artifact-it-%s" % uuid.uuid4().hex[:10]
        assert client.post("/api/v1/test-runs", json={"test_run_id": run_id}).status_code == 201
        assert client.post(
            "/api/v1/nodes/register",
            json={
                "node_id": "node-artifact-it",
                "operator_ref": "artifact-integration",
                "os_family": "linux",
                "architecture": "x86_64",
                "shell": "bash",
                "registered_at": 1,
            },
        ).status_code == 200
        assert client.post(
            "/api/v1/nodes/node-artifact-it/capabilities",
            json={
                "capability_id": "maven-junit",
                "state": "VERIFIED",
                "probe_ref": "probe:artifact-it",
                "evidence_refs": ["artifact:probe-artifact-it"],
                "verified_at": 2,
            },
        ).status_code == 200

        stage_id = "stage-%s" % uuid.uuid4().hex[:8]
        governance_repository.upsert_stage(StageInstance(
            stage_instance_id=stage_id,
            test_run_id=run_id,
            stage_type="APPLICABLE_LAYER_EXECUTION",
            scope_version="scope:artifact-it@v1",
            attempt_no=1,
            state=StageState.EXECUTING,
            assigned_worker="L1UnitWorker",
            started_at=100,
        ))

        work_item_id = "work-%s" % uuid.uuid4().hex[:8]
        attempt_id = "attempt-%s" % uuid.uuid4().hex[:8]
        artifact_id = "junit-%s" % uuid.uuid4().hex[:8]
        assert client.post(
            "/api/v1/work-items/register",
            json={
                "work_item_id": work_item_id,
                "test_run_id": run_id,
                "stage": "L1_EXECUTION",
                "scope_refs": ["scope:artifact-it@v1"],
                "required_capabilities": ["maven-junit"],
            },
        ).status_code == 200
        lease_response = client.post(
            "/api/v1/work-items/%s/lease" % work_item_id,
            json={"node_id": "node-artifact-it", "ttl_seconds": 120},
        )
        assert lease_response.status_code == 200, lease_response.text
        lease_id = lease_response.json()["work_item"]["lease_id"]
        assert client.post(
            "/api/v1/work-items/%s/start" % work_item_id,
            json={"node_id": "node-artifact-it", "lease_id": lease_id},
        ).status_code == 200

        assert client.post(
            "/api/v1/runtime-events",
            json=runtime_payload(
                lease_id=lease_id,
                event_id="evt-start-%s" % uuid.uuid4().hex[:8],
                run_id=run_id,
                work_item_id=work_item_id,
                event_type="ATTEMPT_STARTED",
                sequence=1,
                attempt_id=attempt_id,
                data={"stage_instance_id": stage_id, "input_snapshot_ref": "git:artifact-it", "started_at": 101},
            ),
        ).status_code == 200

        content = b"<?xml version='1.0'?><testsuite tests='1' failures='0' errors='0'><testcase name='real'/></testsuite>"
        digest = hashlib.sha256(content).hexdigest()
        assert client.post(
            "/api/v1/runtime-events",
            json=runtime_payload(
                lease_id=lease_id,
                event_id="evt-complete-%s" % uuid.uuid4().hex[:8],
                run_id=run_id,
                work_item_id=work_item_id,
                event_type="ATTEMPT_COMPLETED",
                sequence=2,
                attempt_id=attempt_id,
                data={
                    "stage_instance_id": stage_id,
                    "input_snapshot_ref": "git:artifact-it",
                    "evidence_refs": ["artifact:%s" % artifact_id],
                    "assertion_refs": ["assertion:artifact-it"],
                    "finished_at": 102,
                },
            ),
        ).status_code == 200
        pending_attempt = governance_repository.get_attempt(attempt_id)
        assert pending_attempt is not None and pending_attempt.status.value == "STARTED"

        manifest_body = {
            "lease_id": lease_id,
            "artifact_id": artifact_id,
            "test_run_id": run_id,
            "work_item_id": work_item_id,
            "node_id": "node-artifact-it",
            "kind": "JUNIT_XML",
            "producer_kind": "WORKER",
            "producer_ref": "L1UnitWorker",
            "file_name": "TEST-real.xml",
            "sha256": digest,
            "size_bytes": len(content),
            "attempt_id": attempt_id,
            "refs": ["assertion:artifact-it"],
            "metadata": {"source": "formal-upload-api"},
            "created_at": 102,
        }

        wrong_lease = dict(manifest_body)
        wrong_lease["lease_id"] = "wrong-token"
        denied = client.post("/api/v1/artifacts/begin", json=wrong_lease)
        assert denied.status_code == 409, denied.text
        assert artifact_repository.get(artifact_id) is None

        begun = client.post("/api/v1/artifacts/begin", json=manifest_body)
        assert begun.status_code == 201, begun.text
        assert begun.headers["upload-offset"] == "0"
        assert begun.json()["manifest"]["availability"] == "PENDING_UPLOAD"

        headers = {
            "X-RC8-Node-Id": "node-artifact-it",
            "X-RC8-Lease-Id": lease_id,
            "Content-Type": "application/octet-stream",
        }
        wrong_offset = client.put(
            "/api/v1/artifacts/%s/content?offset=1" % artifact_id,
            headers=headers,
            content=content[:10],
        )
        assert wrong_offset.status_code == 409, wrong_offset.text

        split = max(1, len(content) // 2)
        first = client.put(
            "/api/v1/artifacts/%s/content?offset=0" % artifact_id,
            headers=headers,
            content=content[:split],
        )
        assert first.status_code == 200, first.text
        assert first.json()["offset"] == split

        upload_status = client.get(
            "/api/v1/artifacts/%s/upload-status" % artifact_id,
            headers={"X-RC8-Node-Id": "node-artifact-it", "X-RC8-Lease-Id": lease_id},
        )
        assert upload_status.status_code == 200, upload_status.text
        assert upload_status.json()["offset"] == split

        # Simulate Center service reconstruction between chunks. PostgreSQL metadata
        # plus the durable .part file are sufficient to continue at the exact offset.
        resumed_store = FileArtifactStore(settings.artifact_root, PostgresArtifactRepository(postgres))
        resumed_service = FormalArtifactService(resumed_store, control, projector)
        app.state.artifact_service = resumed_service
        second = client.put(
            "/api/v1/artifacts/%s/content?offset=%d" % (artifact_id, split),
            headers=headers,
            content=content[split:],
        )
        assert second.status_code == 200, second.text
        assert second.json()["offset"] == len(content)

        completed = client.post(
            "/api/v1/artifacts/%s/complete" % artifact_id,
            json={"node_id": "node-artifact-it", "lease_id": lease_id},
        )
        assert completed.status_code == 200, completed.text
        completed_body = completed.json()
        assert completed_body["manifest"]["availability"] == "AVAILABLE"
        assert completed_body["truth_note"] == "ARTIFACT_AVAILABLE_AFTER_SIZE_SHA256_VERIFICATION"
        final_path = resumed_store.content_path(artifact_id)
        assert final_path.read_bytes() == content

        # Making evidence AVAILABLE automatically replays the previously PENDING
        # terminal Attempt; no direct repository mutation is allowed in the test.
        now_completed = governance_repository.get_attempt(attempt_id)
        assert now_completed is not None and now_completed.status.value == "COMPLETED"
        governance = client.get("/api/v1/test-runs/%s/governance" % run_id)
        assert governance.status_code == 200
        assert governance.json()["attempts"][0]["status"] == "COMPLETED"

        # Wrong hash is durable UPLOAD_FAILED and cannot be promoted AVAILABLE.
        bad_id = "bad-%s" % uuid.uuid4().hex[:8]
        bad_body = dict(manifest_body)
        bad_body.update({
            "artifact_id": bad_id,
            "file_name": "bad.log",
            "sha256": "0" * 64,
            "size_bytes": 3,
            "refs": [],
        })
        assert client.post("/api/v1/artifacts/begin", json=bad_body).status_code == 201
        assert client.put(
            "/api/v1/artifacts/%s/content?offset=0" % bad_id,
            headers=headers,
            content=b"abc",
        ).status_code == 200
        bad_complete = client.post(
            "/api/v1/artifacts/%s/complete" % bad_id,
            json={"node_id": "node-artifact-it", "lease_id": lease_id},
        )
        assert bad_complete.status_code == 422, bad_complete.text
        assert artifact_repository.get(bad_id).availability.value == "UPLOAD_FAILED"

        assert client.post(
            "/api/v1/work-items/%s/complete" % work_item_id,
            json={"node_id": "node-artifact-it", "lease_id": lease_id},
        ).status_code == 200

        late_id = "late-%s" % uuid.uuid4().hex[:8]
        late_body = dict(manifest_body)
        late_body["artifact_id"] = late_id
        late_body["file_name"] = "late.log"
        late = client.post("/api/v1/artifacts/begin", json=late_body)
        assert late.status_code == 409, late.text
        assert artifact_repository.get(late_id) is None

        print({
            "status": "FORMAL_ARTIFACT_UPLOAD_VERIFIED",
            "scope": "LEASE_AUTH_RESUMABLE_HASH_SIZE_AVAILABLE_R1_REPLAY",
            "test_run_id": run_id,
            "artifact_id": artifact_id,
            "late_upload_rejected": True,
            "hash_mismatch_rejected": True,
        })
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
