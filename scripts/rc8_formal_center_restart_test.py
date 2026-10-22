#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rc8_center.control_plane import WorkItemState
from rc8_center.infrastructure import (
    PostgresCenterRepository,
    PostgresGovernanceRepository,
    PostgresStore,
    RedisCoordination,
    build_engine,
)
from rc8_node import FormalNodeAgent, HttpCenterClient
from rc8_runtime import (
    ArtifactAvailability,
    CapabilityQualification,
    CapabilityState,
    NodeIdentity,
    RuntimeProducerKind,
    runtime_event,
)
from rc8_runtime.artifacts import ArtifactManifest
from rc8_runtime.governance import AttemptStatus, StageInstance, StageState


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_ready(base_url: str, process: subprocess.Popen, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("CENTER_EXITED_BEFORE_READY:%s" % process.returncode)
        try:
            response = httpx.get(base_url + "/health", timeout=1.0)
            last = response.text
            if response.status_code == 200 and response.json().get("status") == "READY":
                return
        except Exception as exc:
            last = repr(exc)
        time.sleep(0.25)
    raise RuntimeError("CENTER_READY_TIMEOUT:%s" % last)


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def r1_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    database_url = os.environ["RC8_DATABASE_URL"]
    redis_base = os.environ["RC8_REDIS_URL"]
    redis_url = redis_base.rsplit("/", 1)[0] + "/1"

    with tempfile.TemporaryDirectory(prefix="rc8-center-restart-") as temp_dir:
        root = Path(temp_dir)
        artifact_root = root / "artifacts"
        r1_root = root / "r1"
        ledger_path = r1_root / "event-stream.jsonl"
        log_path = root / "center.log"
        port = free_port()
        base = "http://127.0.0.1:%d" % port
        env = dict(os.environ)
        env.update({
            "RC8_DATABASE_URL": database_url,
            "RC8_REDIS_URL": redis_url,
            "RC8_ARTIFACT_ROOT": str(artifact_root),
            "RC8_R1_ROOT": str(r1_root),
            "RC8_ENVIRONMENT": "restart-integration-test",
            "PYTHONPATH": str(ROOT),
        })

        probe_store = PostgresStore(build_engine(database_url))
        control_repository = PostgresCenterRepository(probe_store)
        governance_repository = PostgresGovernanceRepository(probe_store)
        redis_probe = RedisCoordination.from_url(redis_url)
        log_file = log_path.open("ab")

        def start_center() -> subprocess.Popen:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "rc8_center.formal_app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "warning",
                ],
                cwd=str(ROOT),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
            wait_ready(base, process)
            return process

        process = start_center()
        try:
            center = HttpCenterClient(base, timeout_seconds=5)
            run_id = "restart-it-%s" % uuid.uuid4().hex[:10]
            node_id = "node-restart-it"
            work_item_id = "work-%s" % uuid.uuid4().hex[:8]
            attempt_id = "attempt-%s" % uuid.uuid4().hex[:8]
            artifact_id = "restart-art-%s" % uuid.uuid4().hex[:8]
            stage_id = "stage-restart-%s" % uuid.uuid4().hex[:8]
            start_event_id = "evt-start-%s" % uuid.uuid4().hex[:8]
            complete_event_id = "evt-complete-%s" % uuid.uuid4().hex[:8]
            identity = NodeIdentity(
                node_id=node_id,
                operator_ref="restart-test",
                os_family="linux",
                architecture="x86_64",
                shell="bash",
                registered_at=1,
            )
            agent = FormalNodeAgent(identity, center)

            center.post("/api/v1/test-runs", {"test_run_id": run_id})
            agent.register()
            agent.report_capability(CapabilityQualification(
                node_id=node_id,
                capability_id="maven-junit",
                state=CapabilityState.VERIFIED,
                probe_ref="probe:restart",
                evidence_refs=["artifact:restart-probe"],
                verified_at=2,
            ))
            center.post("/api/v1/work-items/register", {
                "work_item_id": work_item_id,
                "test_run_id": run_id,
                "stage": "L1_EXECUTION",
                "scope_refs": ["scope:restart-it@v1"],
                "required_capabilities": ["maven-junit"],
            })
            lease_response = agent.lease(work_item_id, ttl_seconds=300)
            lease = FormalNodeAgent.lease_id(lease_response)
            agent.start(work_item_id, lease_id=lease)

            # Stage identity is durable PostgreSQL governance state. Seeding the
            # stage lets the runtime event project a real Attempt so restart can
            # prove replay idempotency/no-duplication rather than merely retaining
            # a PENDING receipt for an unknown stage.
            governance_repository.upsert_stage(StageInstance(
                stage_instance_id=stage_id,
                test_run_id=run_id,
                stage_type="L1_EXECUTION",
                scope_version="scope:restart-it@v1",
                attempt_no=1,
                state=StageState.EXECUTING,
                input_refs=("git:restart-it",),
                assigned_worker="L1UnitWorker",
                started_at=100,
            ))

            started_event = runtime_event(
                event_id=start_event_id,
                test_run_id=run_id,
                work_item_id=work_item_id,
                node_id=node_id,
                producer_kind=RuntimeProducerKind.WORKER,
                producer_ref="L1UnitWorker",
                event_type="ATTEMPT_STARTED",
                sequence=1,
                attempt_id=attempt_id,
                data={
                    "stage_instance_id": stage_id,
                    "input_snapshot_ref": "git:restart-it",
                    "started_at": 101,
                },
                occurred_at=101,
            )
            started = agent.append_runtime_event(started_event, lease_id=lease)
            assert started["receipt"]["status"] == "PERSISTENCE_VERIFIED"
            assert started["projection"]["projection"]["status"] == "PROJECTED"

            projection_before = center.get("/api/v1/test-runs/%s/governance" % run_id)
            assert projection_before["stage_count"] == 1
            assert projection_before["attempt_count"] == 1
            assert projection_before["attempts"][0]["attempt_id"] == attempt_id
            assert projection_before["attempts"][0]["status"] == AttemptStatus.STARTED.value

            work_before = control_repository.get_work_item(work_item_id)
            assert work_before is not None
            assert work_before.state == WorkItemState.RUNNING
            assert work_before.lease_id == lease
            assert work_before.lease_owner_node_id == node_id
            redis_before = redis_probe.lease_info("work-item", work_item_id)
            assert redis_before is not None
            assert redis_before["owner_id"] == node_id
            assert redis_before["lease_id"] == lease

            content = b"restart-proof-artifact-content-0123456789"
            source_file = root / "restart-proof.bin"
            source_file.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            manifest = ArtifactManifest(
                artifact_id=artifact_id,
                test_run_id=run_id,
                work_item_id=work_item_id,
                node_id=node_id,
                kind="RESTART_PROOF",
                producer_kind=RuntimeProducerKind.WORKER,
                producer_ref="L1UnitWorker",
                file_name="restart-proof.bin",
                sha256=digest,
                size_bytes=len(content),
                availability=ArtifactAvailability.PENDING_UPLOAD,
                attempt_id=attempt_id,
                refs=[],
                metadata={"phase": "before-restart"},
                created_at=102,
            )

            # Start the exact formal upload protocol and persist only half of the
            # payload. The .part file must itself be durable across process loss.
            begin_payload = {
                "lease_id": lease,
                "artifact_id": manifest.artifact_id,
                "test_run_id": manifest.test_run_id,
                "work_item_id": manifest.work_item_id,
                "node_id": manifest.node_id,
                "kind": manifest.kind,
                "producer_kind": manifest.producer_kind.value,
                "producer_ref": manifest.producer_ref,
                "file_name": manifest.file_name,
                "sha256": manifest.sha256,
                "size_bytes": manifest.size_bytes,
                "case_id": manifest.case_id,
                "attempt_id": manifest.attempt_id,
                "step_id": manifest.step_id,
                "refs": list(manifest.refs),
                "metadata": dict(manifest.metadata),
                "created_at": manifest.created_at,
            }
            begun = center.post("/api/v1/artifacts/begin", begin_payload)
            assert begun["offset"] == 0
            split = len(content) // 2
            first = center.put_bytes(
                "/api/v1/artifacts/%s/content?offset=0" % artifact_id,
                content[:split],
                headers={"X-RC8-Node-Id": node_id, "X-RC8-Lease-Id": lease},
            )
            assert first["offset"] == split
            part_path = artifact_root / "pending" / (artifact_id + ".part")
            assert part_path.exists() and part_path.stat().st_size == split

            # Persist the terminal Attempt fact to R1 while evidence is still only
            # UPLOADING. Projection must remain PENDING. After Center restart and
            # Artifact AVAILABLE, replay must advance the same Attempt row instead
            # of creating a duplicate.
            completion_event = runtime_event(
                event_id=complete_event_id,
                test_run_id=run_id,
                work_item_id=work_item_id,
                node_id=node_id,
                producer_kind=RuntimeProducerKind.WORKER,
                producer_ref="L1UnitWorker",
                event_type="ATTEMPT_COMPLETED",
                sequence=2,
                attempt_id=attempt_id,
                data={
                    "stage_instance_id": stage_id,
                    "input_snapshot_ref": "git:restart-it",
                    "action_refs": ["action:restart-proof"],
                    "assertion_refs": ["assertion:restart-proof"],
                    "evidence_refs": ["artifact:%s" % artifact_id],
                    "finished_at": 103,
                },
                occurred_at=103,
            )
            pending_completion = agent.append_runtime_event(completion_event, lease_id=lease)
            assert pending_completion["receipt"]["status"] == "PERSISTENCE_VERIFIED"
            pending_projection = pending_completion["projection"]["projection"]
            assert pending_projection["status"] == "PENDING"
            assert str(pending_projection.get("detail") or "").startswith("ARTIFACT_NOT_AVAILABLE")
            attempt_before_restart = governance_repository.get_attempt(attempt_id)
            assert attempt_before_restart is not None
            assert attempt_before_restart.status == AttemptStatus.STARTED
            before_r1 = r1_events(ledger_path)
            assert [event["event_id"] for event in before_r1] == [start_event_id, complete_event_id]

            # Real process termination: no FastAPI/Uvicorn application or service
            # object survives. PostgreSQL, Redis, R1 and the .part file do.
            stop_process(process)
            process = start_center()

            # Recreate both HTTP client and formal Node agent. No in-memory lease
            # or DSH/model session state is carried over.
            center = HttpCenterClient(base, timeout_seconds=5)
            agent = FormalNodeAgent(identity, center)

            # Durable control truth must survive exactly once across restart.
            work_after_restart = control_repository.get_work_item(work_item_id)
            assert work_after_restart is not None
            assert work_after_restart.state == WorkItemState.RUNNING
            assert work_after_restart.lease_id == lease
            assert work_after_restart.lease_owner_node_id == node_id
            matching_work_items = [
                item for item in control_repository.list_work_items()
                if item.identity.work_item_id == work_item_id
            ]
            assert len(matching_work_items) == 1
            redis_after_restart = redis_probe.lease_info("work-item", work_item_id)
            assert redis_after_restart is not None
            assert redis_after_restart["owner_id"] == node_id
            assert redis_after_restart["lease_id"] == lease

            # Center startup replays canonical R1. Because the Artifact is still
            # UPLOADING, the terminal event remains pending and the already-started
            # Attempt remains one row, not a replay duplicate.
            projection_after_restart = center.get("/api/v1/test-runs/%s/governance" % run_id)
            assert projection_after_restart["stage_count"] == 1
            assert projection_after_restart["attempt_count"] == 1
            assert projection_after_restart["attempts"][0]["attempt_id"] == attempt_id
            assert projection_after_restart["attempts"][0]["status"] == AttemptStatus.STARTED.value
            receipt_after_restart = next(
                item for item in projection_after_restart["projection_receipts"]
                if item["event_id"] == complete_event_id
            )
            assert receipt_after_restart["status"] == "PENDING"
            assert part_path.exists() and part_path.stat().st_size == split
            after_restart_r1 = r1_events(ledger_path)
            assert len(after_restart_r1) == 2
            assert len({event["event_id"] for event in after_restart_r1}) == 2

            resumed = center.get(
                "/api/v1/artifacts/%s/upload-status" % artifact_id,
                headers={"X-RC8-Node-Id": node_id, "X-RC8-Lease-Id": lease},
            )
            assert resumed["offset"] == split
            assert resumed["manifest"]["availability"] == "UPLOADING"

            completed = agent.upload_artifact_file(
                manifest,
                str(source_file),
                lease_id=lease,
                chunk_size=7,
            )
            assert completed["manifest"]["availability"] == "AVAILABLE"
            assert completed["projection"]["status"] == "REPLAY_COMPLETE"
            assert completed["projection"]["pending"] == 0

            # Artifact AVAILABLE triggers replay of the terminal R1 fact. The same
            # Attempt identity must advance to COMPLETED exactly once.
            projection_after_available = center.get("/api/v1/test-runs/%s/governance" % run_id)
            assert projection_after_available["attempt_count"] == 1
            assert projection_after_available["attempts"][0]["attempt_id"] == attempt_id
            assert projection_after_available["attempts"][0]["status"] == AttemptStatus.COMPLETED.value
            assert projection_after_available["attempts"][0]["evidence_refs"] == ["artifact:%s" % artifact_id]
            receipt_after_available = next(
                item for item in projection_after_available["projection_receipts"]
                if item["event_id"] == complete_event_id
            )
            assert receipt_after_available["status"] == "PROJECTED"
            attempts_after_available = governance_repository.list_attempts(run_id)
            assert len(attempts_after_available) == 1
            assert attempts_after_available[0].attempt_id == attempt_id
            assert attempts_after_available[0].status == AttemptStatus.COMPLETED

            final_file = artifact_root / "available" / artifact_id / "restart-proof.bin"
            assert final_file.read_bytes() == content
            assert not part_path.exists()
            final_r1 = r1_events(ledger_path)
            assert len(final_r1) == 2
            assert [event["event_id"] for event in final_r1] == [start_event_id, complete_event_id]

            # WorkItem terminalization is separate from Attempt evidence replay.
            # It must release the same durable Redis lease and keep one PostgreSQL
            # WorkItem identity.
            agent.complete(work_item_id, lease_id=lease)
            final_work = control_repository.get_work_item(work_item_id)
            assert final_work is not None
            assert final_work.state == WorkItemState.COMPLETED
            assert final_work.lease_id is None
            assert final_work.lease_owner_node_id is None
            assert redis_probe.lease_info("work-item", work_item_id) is None
            final_matching_work_items = [
                item for item in control_repository.list_work_items()
                if item.identity.work_item_id == work_item_id
            ]
            assert len(final_matching_work_items) == 1

            print({
                "status": "FORMAL_NODE_CENTER_PROCESS_RESTART_RECOVERY_VERIFIED",
                "scope": "R1_PG_REDIS_PART_FILE_RESTART_REPLAY_RESUME_NO_DUPLICATE_WORKITEM_ATTEMPT",
                "test_run_id": run_id,
                "artifact_id": artifact_id,
                "r1_event_count": len(final_r1),
                "work_item_count": len(final_matching_work_items),
                "attempt_count": len(attempts_after_available),
                "terminal_attempt_replayed_after_artifact_available": True,
                "mission_sufficient": False,
                "bank_server_reality": False,
            })
            return 0
        finally:
            stop_process(process)
            probe_store.engine.dispose()
            log_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
