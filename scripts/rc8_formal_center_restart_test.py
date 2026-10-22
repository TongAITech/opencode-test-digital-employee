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


def must(response: httpx.Response, code: int) -> dict:
    if response.status_code != code:
        raise AssertionError("HTTP_%s_EXPECTED_%s:%s" % (response.status_code, code, response.text))
    return response.json()


def main() -> int:
    database_url = os.environ["RC8_DATABASE_URL"]
    redis_base = os.environ["RC8_REDIS_URL"]
    # Use a separate Redis logical DB so this process-level recovery test cannot
    # destroy transient state belonging to the preceding integration assertions.
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
            client = httpx.Client(base_url=base, timeout=5.0)
            run_id = "restart-it-%s" % uuid.uuid4().hex[:10]
            node_id = "node-restart-it"
            work_item_id = "work-%s" % uuid.uuid4().hex[:8]
            attempt_id = "attempt-%s" % uuid.uuid4().hex[:8]
            artifact_id = "restart-art-%s" % uuid.uuid4().hex[:8]

            must(client.post("/api/v1/test-runs", json={"test_run_id": run_id}), 201)
            must(client.post("/api/v1/nodes/register", json={
                "node_id": node_id,
                "operator_ref": "restart-test",
                "os_family": "linux",
                "architecture": "x86_64",
                "shell": "bash",
                "registered_at": 1,
            }), 200)
            must(client.post("/api/v1/nodes/%s/capabilities" % node_id, json={
                "capability_id": "maven-junit",
                "state": "VERIFIED",
                "probe_ref": "probe:restart",
                "evidence_refs": ["artifact:restart-probe"],
                "verified_at": 2,
            }), 200)
            must(client.post("/api/v1/work-items/register", json={
                "work_item_id": work_item_id,
                "test_run_id": run_id,
                "stage": "L1_EXECUTION",
                "scope_refs": ["scope:restart-it@v1"],
                "required_capabilities": ["maven-junit"],
            }), 200)
            lease = must(client.post("/api/v1/work-items/%s/lease" % work_item_id, json={
                "node_id": node_id,
                "ttl_seconds": 300,
            }), 200)["work_item"]["lease_id"]
            must(client.post("/api/v1/work-items/%s/start" % work_item_id, json={
                "node_id": node_id,
                "lease_id": lease,
            }), 200)

            # Use a stage instance generated through the existing governance path is
            # not yet exposed as a formal public API. The projector accepts the
            # runtime event but cannot materialize Attempt without a Stage, so this
            # restart test focuses on R1 persistence + Artifact resume. Governance
            # completion is separately covered by the formal Artifact integration test.
            stage_id = "stage-restart-%s" % uuid.uuid4().hex[:8]
            start_payload = {
                "lease_id": lease,
                "event_id": "evt-start-%s" % uuid.uuid4().hex[:8],
                "test_run_id": run_id,
                "work_item_id": work_item_id,
                "node_id": node_id,
                "producer_kind": "WORKER",
                "producer_ref": "L1UnitWorker",
                "event_type": "ATTEMPT_STARTED",
                "sequence": 1,
                "attempt_id": attempt_id,
                "refs": [],
                "data": {
                    "stage_instance_id": stage_id,
                    "input_snapshot_ref": "git:restart-it",
                    "started_at": 101,
                },
                "occurred_at": 101,
            }
            # Unknown Stage means projection may remain pending, but R1 persistence
            # must still succeed before the process is killed.
            started = must(client.post("/api/v1/runtime-events", json=start_payload), 200)
            assert started["receipt"]["status"] == "PERSISTENCE_VERIFIED"

            content = b"restart-proof-artifact-content-0123456789"
            digest = hashlib.sha256(content).hexdigest()
            manifest = {
                "lease_id": lease,
                "artifact_id": artifact_id,
                "test_run_id": run_id,
                "work_item_id": work_item_id,
                "node_id": node_id,
                "kind": "RESTART_PROOF",
                "producer_kind": "WORKER",
                "producer_ref": "L1UnitWorker",
                "file_name": "restart-proof.bin",
                "sha256": digest,
                "size_bytes": len(content),
                "attempt_id": attempt_id,
                "refs": [],
                "metadata": {"phase": "before-restart"},
                "created_at": 102,
            }
            begin = must(client.post("/api/v1/artifacts/begin", json=manifest), 201)
            assert begin["offset"] == 0
            split = len(content) // 2
            headers = {
                "X-RC8-Node-Id": node_id,
                "X-RC8-Lease-Id": lease,
                "Content-Type": "application/octet-stream",
            }
            first = must(client.put(
                "/api/v1/artifacts/%s/content?offset=0" % artifact_id,
                headers=headers,
                content=content[:split],
            ), 200)
            assert first["offset"] == split
            client.close()

            # Real process termination: no in-memory repository/service object can
            # survive. PostgreSQL, Redis, R1 file and Artifact .part remain durable.
            stop_process(process)
            process = start_center()
            client = httpx.Client(base_url=base, timeout=5.0)

            resumed = must(client.get(
                "/api/v1/artifacts/%s/upload-status" % artifact_id,
                headers={"X-RC8-Node-Id": node_id, "X-RC8-Lease-Id": lease},
            ), 200)
            assert resumed["offset"] == split
            assert resumed["manifest"]["availability"] == "UPLOADING"

            second = must(client.put(
                "/api/v1/artifacts/%s/content?offset=%d" % (artifact_id, split),
                headers=headers,
                content=content[split:],
            ), 200)
            assert second["offset"] == len(content)
            completed = must(client.post(
                "/api/v1/artifacts/%s/complete" % artifact_id,
                json={"node_id": node_id, "lease_id": lease},
            ), 200)
            assert completed["manifest"]["availability"] == "AVAILABLE"

            must(client.post("/api/v1/work-items/%s/complete" % work_item_id, json={
                "node_id": node_id,
                "lease_id": lease,
            }), 200)

            final_file = artifact_root / "available" / artifact_id / "restart-proof.bin"
            assert final_file.read_bytes() == content
            assert (r1_root / "event-stream.jsonl").exists()
            assert (r1_root / "event-stream.jsonl").read_text(encoding="utf-8").strip()

            client.close()
            print({
                "status": "FORMAL_CENTER_PROCESS_RESTART_RECOVERY_VERIFIED",
                "scope": "PG_REDIS_R1_PARTIAL_ARTIFACT_RESUME_AFTER_REAL_UVICORN_RESTART",
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
