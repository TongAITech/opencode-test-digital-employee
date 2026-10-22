#!/usr/bin/env python3
from __future__ import annotations

import hashlib
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


def main() -> int:
    database_url = os.environ["RC8_DATABASE_URL"]
    redis_base = os.environ["RC8_REDIS_URL"]
    redis_url = redis_base.rsplit("/", 1)[0] + "/1"

    with tempfile.TemporaryDirectory(prefix="rc8-center-restart-") as temp_dir:
        root = Path(temp_dir)
        artifact_root = root / "artifacts"
        r1_root = root / "r1"
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

            # The formal public API does not yet expose Mission Stage creation.
            # Therefore this scoped restart test intentionally leaves projection
            # PENDING on an unknown stage while proving that the canonical R1 fact
            # itself survives process loss. Full Stage/Attempt replay is covered by
            # the formal governance integration and is not inferred from this test.
            stage_id = "stage-restart-%s" % uuid.uuid4().hex[:8]
            event = runtime_event(
                event_id="evt-start-%s" % uuid.uuid4().hex[:8],
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
            started = agent.append_runtime_event(event, lease_id=lease)
            assert started["receipt"]["status"] == "PERSISTENCE_VERIFIED"

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

            # Start the transfer through the exact formal protocol and upload only
            # half. The second half is deliberately delegated to FormalNodeAgent
            # after the Center process has been destroyed and recreated.
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

            # Real process termination: no application/service object survives.
            stop_process(process)
            process = start_center()

            # Recreate both HTTP client and formal Node agent. No hidden in-memory
            # lease/session state is carried over; the explicit durable lease token
            # and Center stores are enough to resume the exact byte offset.
            center = HttpCenterClient(base, timeout_seconds=5)
            agent = FormalNodeAgent(identity, center)
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
            agent.complete(work_item_id, lease_id=lease)

            final_file = artifact_root / "available" / artifact_id / "restart-proof.bin"
            assert final_file.read_bytes() == content
            ledger_path = r1_root / "event-stream.jsonl"
            assert ledger_path.exists() and ledger_path.read_text(encoding="utf-8").strip()

            print({
                "status": "FORMAL_NODE_CENTER_PROCESS_RESTART_RECOVERY_VERIFIED",
                "scope": "FORMAL_NODE_EXPLICIT_LEASE_R1_PARTIAL_ARTIFACT_RESUME_AFTER_REAL_UVICORN_RESTART",
                "test_run_id": run_id,
                "artifact_id": artifact_id,
                "mission_sufficient": False,
                "bank_server_reality": False,
            })
            return 0
        finally:
            stop_process(process)
            log_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
