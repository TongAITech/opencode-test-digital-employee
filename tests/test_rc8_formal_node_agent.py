#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rc8_node import FormalNodeAgent, NodeAgentError
from rc8_runtime import (
    ArtifactAvailability,
    CapabilityQualification,
    CapabilityState,
    NodeIdentity,
    RuntimeProducerKind,
    runtime_event,
)
from rc8_runtime.artifacts import ArtifactManifest


class FakeCenter:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, str, Any, Optional[Dict[str, str]]]] = []
        self.remote_offset = 0

    def post(self, path: str, payload: Dict[str, Any], *, headers=None) -> Dict[str, Any]:
        self.calls.append(("POST", path, payload, headers))
        if path.endswith("/lease"):
            return {"work_item": {"lease_id": "lease-123", "state": "LEASED"}}
        if path == "/api/v1/artifacts/begin":
            self.remote_offset = 0
            return {"offset": 0, "manifest": {"availability": "PENDING_UPLOAD"}}
        if path.endswith("/complete") and "/artifacts/" in path:
            return {"manifest": {"availability": "AVAILABLE"}}
        return {"ok": True}

    def get(self, path: str, *, headers=None) -> Dict[str, Any]:
        self.calls.append(("GET", path, None, headers))
        return {"offset": self.remote_offset, "manifest": {"availability": "UPLOADING"}}

    def put_bytes(self, path: str, data: bytes, *, headers=None) -> Dict[str, Any]:
        self.calls.append(("PUT", path, data, headers))
        self.remote_offset += len(data)
        return {"offset": self.remote_offset, "availability": "UPLOADING"}


class FormalNodeAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.center = FakeCenter()
        self.identity = NodeIdentity(
            node_id="node-formal-01",
            operator_ref="test",
            os_family="windows",
            architecture="x86_64",
            shell="git-bash",
            registered_at=1,
        )
        self.agent = FormalNodeAgent(self.identity, self.center)

    def test_capability_request_uses_path_scoped_node_contract(self) -> None:
        qualification = CapabilityQualification(
            node_id="node-formal-01",
            capability_id="maven-junit",
            state=CapabilityState.VERIFIED,
            probe_ref="probe:formal-agent",
            evidence_refs=["artifact:formal-agent-probe"],
            verified_at=2,
        )
        self.agent.report_capability(qualification)
        method, path, payload, _ = self.center.calls[-1]
        self.assertEqual((method, path), ("POST", "/api/v1/nodes/node-formal-01/capabilities"))
        self.assertEqual(
            payload,
            {
                "capability_id": "maven-junit",
                "state": "VERIFIED",
                "probe_ref": "probe:formal-agent",
                "evidence_refs": ["artifact:formal-agent-probe"],
                "verified_at": 2,
            },
        )
        self.assertNotIn("node_id", payload)

        with self.assertRaisesRegex(NodeAgentError, "CAPABILITY_NODE_MISMATCH"):
            self.agent.report_capability(CapabilityQualification(
                node_id="another-node",
                capability_id="maven-junit",
                state=CapabilityState.VERIFIED,
                probe_ref="probe:other",
                evidence_refs=["artifact:other"],
                verified_at=3,
            ))

    def test_start_runtime_and_complete_require_explicit_lease(self) -> None:
        with self.assertRaisesRegex(NodeAgentError, "WORK_ITEM_LEASE_ID_REQUIRED"):
            self.agent.start("work-1", lease_id="")

        self.agent.start("work-1", lease_id="lease-123")
        method, path, payload, _ = self.center.calls[-1]
        self.assertEqual((method, path), ("POST", "/api/v1/work-items/work-1/start"))
        self.assertEqual(payload, {"node_id": "node-formal-01", "lease_id": "lease-123"})

        event = runtime_event(
            event_id="event-1",
            test_run_id="run-1",
            work_item_id="work-1",
            node_id="node-formal-01",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="L1UnitWorker",
            event_type="ATTEMPT_STARTED",
            sequence=1,
            attempt_id="attempt-1",
            data={"stage_instance_id": "stage-1"},
            occurred_at=2,
        )
        self.agent.append_runtime_event(event, lease_id="lease-123")
        payload = self.center.calls[-1][2]
        self.assertEqual(payload["lease_id"], "lease-123")
        self.assertEqual(payload["producer_kind"], "WORKER")
        self.assertNotIn("plane", payload)

        self.agent.complete("work-1", lease_id="lease-123")
        self.assertEqual(self.center.calls[-1][2]["lease_id"], "lease-123")

    def test_lease_id_is_explicitly_extracted(self) -> None:
        response = self.agent.lease("work-1", ttl_seconds=90)
        self.assertEqual(FormalNodeAgent.lease_id(response), "lease-123")
        with self.assertRaisesRegex(NodeAgentError, "WORK_ITEM_LEASE_ID_REQUIRED"):
            FormalNodeAgent.lease_id({"work_item": {"lease_id": ""}})

    def test_artifact_uses_formal_resumable_protocol(self) -> None:
        content = b"abcdef0123456789"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "TEST.xml"
            path.write_bytes(content)
            manifest = ArtifactManifest(
                artifact_id="artifact-formal-1",
                test_run_id="run-1",
                work_item_id="work-1",
                node_id="node-formal-01",
                kind="JUNIT_XML",
                producer_kind=RuntimeProducerKind.WORKER,
                producer_ref="L1UnitWorker",
                file_name="TEST.xml",
                sha256=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
                availability=ArtifactAvailability.PENDING_UPLOAD,
                attempt_id="attempt-1",
                created_at=3,
            )
            result = self.agent.upload_artifact_file(
                manifest,
                str(path),
                lease_id="lease-123",
                chunk_size=5,
            )
            self.assertEqual(result["manifest"]["availability"], "AVAILABLE")

        begin = next(call for call in self.center.calls if call[0] == "POST" and call[1] == "/api/v1/artifacts/begin")
        self.assertEqual(begin[2]["lease_id"], "lease-123")
        self.assertNotIn("availability", begin[2])

        status = next(call for call in self.center.calls if call[0] == "GET")
        self.assertEqual(status[1], "/api/v1/artifacts/artifact-formal-1/upload-status")
        self.assertEqual(status[3]["X-RC8-Node-Id"], "node-formal-01")
        self.assertEqual(status[3]["X-RC8-Lease-Id"], "lease-123")

        puts = [call for call in self.center.calls if call[0] == "PUT"]
        self.assertGreaterEqual(len(puts), 2)
        self.assertTrue(all("?offset=" in call[1] for call in puts))
        self.assertTrue(all(call[3]["X-RC8-Lease-Id"] == "lease-123" for call in puts))

        complete = [call for call in self.center.calls if call[0] == "POST" and call[1].endswith("/complete")][-1]
        self.assertEqual(complete[2], {"node_id": "node-formal-01", "lease_id": "lease-123"})

    def test_artifact_local_hash_and_size_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.bin"
            path.write_bytes(b"abc")
            manifest = ArtifactManifest(
                artifact_id="artifact-bad",
                test_run_id="run-1",
                work_item_id="work-1",
                node_id="node-formal-01",
                kind="LOG",
                producer_kind=RuntimeProducerKind.WORKER,
                producer_ref="worker",
                file_name="bad.bin",
                sha256="0" * 64,
                size_bytes=3,
                availability=ArtifactAvailability.PENDING_UPLOAD,
                created_at=4,
            )
            with self.assertRaisesRegex(NodeAgentError, "ARTIFACT_LOCAL_HASH_MISMATCH"):
                self.agent.upload_artifact_file(manifest, str(path), lease_id="lease-123")
            self.assertEqual(self.center.calls, [])


if __name__ == "__main__":
    unittest.main()
