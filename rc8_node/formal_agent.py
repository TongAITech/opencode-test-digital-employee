"""Formal RC8 office-node client for the frozen Center protocol.

Unlike the W1 compatibility NodeAgent, this adapter makes the active WorkItem
lease token an explicit argument to every runtime/evidence mutation. The token
is never inferred from a DSH session. This keeps WorkItem truth independent
from disposable model sessions and matches the PostgreSQL + Redis authorization
contract enforced by FormalCenterControlPlane.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

from rc8_runtime import CapabilityQualification, NodeIdentity, RuntimeEventEnvelope
from rc8_runtime.artifacts import ArtifactManifest

from .agent import HttpCenterClient, NodeAgentError


class FormalNodeAgent:
    def __init__(self, identity: NodeIdentity, center: HttpCenterClient) -> None:
        self.identity = identity
        self.center = center

    def register(self) -> Dict[str, Any]:
        return self.center.post("/api/v1/nodes/register", asdict(self.identity))

    def heartbeat(self, *, status: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if status is not None:
            payload["status"] = status
        return self.center.post("/api/v1/nodes/%s/heartbeat" % self.identity.node_id, payload)

    def report_capability(self, value: CapabilityQualification) -> Dict[str, Any]:
        if value.node_id != self.identity.node_id:
            raise NodeAgentError("CAPABILITY_NODE_MISMATCH")
        payload = {
            "capability_id": value.capability_id,
            "state": value.state.value,
            "probe_ref": value.probe_ref,
            "evidence_refs": list(value.evidence_refs),
            "verified_at": value.verified_at,
        }
        return self.center.post("/api/v1/nodes/%s/capabilities" % self.identity.node_id, payload)

    def lease(self, work_item_id: str, *, ttl_seconds: int = 60) -> Dict[str, Any]:
        return self.center.post(
            "/api/v1/work-items/%s/lease" % work_item_id,
            {"node_id": self.identity.node_id, "ttl_seconds": ttl_seconds},
        )

    @staticmethod
    def lease_id(response: Dict[str, Any]) -> str:
        work = response.get("work_item")
        if not isinstance(work, dict):
            raise NodeAgentError("WORK_ITEM_RESPONSE_REQUIRED")
        value = work.get("lease_id")
        if not isinstance(value, str) or not value.strip():
            raise NodeAgentError("WORK_ITEM_LEASE_ID_REQUIRED")
        return value.strip()

    def start(self, work_item_id: str, *, lease_id: str) -> Dict[str, Any]:
        return self.center.post(
            "/api/v1/work-items/%s/start" % work_item_id,
            {"node_id": self.identity.node_id, "lease_id": self._required_lease(lease_id)},
        )

    def append_runtime_event(self, event: RuntimeEventEnvelope, *, lease_id: str) -> Dict[str, Any]:
        if event.node_id != self.identity.node_id:
            raise NodeAgentError("RUNTIME_EVENT_NODE_MISMATCH")
        payload = {
            "lease_id": self._required_lease(lease_id),
            "event_id": event.event_id,
            "test_run_id": event.test_run_id,
            "work_item_id": event.work_item_id,
            "node_id": event.node_id,
            "producer_kind": event.producer_kind.value,
            "producer_ref": event.producer_ref,
            "event_type": event.event_type,
            "sequence": event.sequence,
            "case_id": event.case_id,
            "attempt_id": event.attempt_id,
            "step_id": event.step_id,
            "refs": list(event.refs),
            "data": dict(event.data),
            "occurred_at": event.occurred_at,
        }
        return self.center.post("/api/v1/runtime-events", payload)

    def upload_artifact_file(
        self,
        manifest: ArtifactManifest,
        file_path: str,
        *,
        lease_id: str,
        chunk_size: int = 1024 * 1024,
    ) -> Dict[str, Any]:
        if manifest.node_id != self.identity.node_id:
            raise NodeAgentError("ARTIFACT_NODE_MISMATCH")
        lease = self._required_lease(lease_id)
        if not isinstance(chunk_size, int) or chunk_size <= 0:
            raise NodeAgentError("ARTIFACT_CHUNK_SIZE_INVALID")

        path = Path(file_path)
        if not path.is_file():
            raise NodeAgentError("ARTIFACT_FILE_NOT_FOUND")
        if path.stat().st_size != manifest.size_bytes:
            raise NodeAgentError("ARTIFACT_LOCAL_SIZE_MISMATCH")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
        if digest.hexdigest().lower() != manifest.sha256.lower():
            raise NodeAgentError("ARTIFACT_LOCAL_HASH_MISMATCH")

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
        begun = self.center.post("/api/v1/artifacts/begin", begin_payload)
        offset = self._offset_from(begun)

        auth_headers = {
            "X-RC8-Node-Id": self.identity.node_id,
            "X-RC8-Lease-Id": lease,
        }
        status = self.center.get(
            "/api/v1/artifacts/%s/upload-status" % manifest.artifact_id,
            headers=auth_headers,
        )
        remote_offset = self._offset_from(status)
        if remote_offset != offset:
            raise NodeAgentError("ARTIFACT_REMOTE_OFFSET_DIVERGED:%s:%s" % (remote_offset, offset))
        if offset < 0 or offset > manifest.size_bytes:
            raise NodeAgentError("ARTIFACT_REMOTE_OFFSET_INVALID")

        with path.open("rb") as handle:
            handle.seek(offset)
            while offset < manifest.size_bytes:
                chunk = handle.read(min(chunk_size, manifest.size_bytes - offset))
                if not chunk:
                    raise NodeAgentError("ARTIFACT_LOCAL_READ_UNEXPECTED_EOF")
                uploaded = self.center.put_bytes(
                    "/api/v1/artifacts/%s/content?offset=%s" % (manifest.artifact_id, offset),
                    chunk,
                    headers=auth_headers,
                )
                next_offset = self._offset_from(uploaded)
                expected = offset + len(chunk)
                if next_offset != expected:
                    raise NodeAgentError("ARTIFACT_REMOTE_OFFSET_DIVERGED:%s:%s" % (next_offset, expected))
                offset = next_offset

        return self.center.post(
            "/api/v1/artifacts/%s/complete" % manifest.artifact_id,
            {"node_id": self.identity.node_id, "lease_id": lease},
        )

    def complete(self, work_item_id: str, *, lease_id: str) -> Dict[str, Any]:
        return self.center.post(
            "/api/v1/work-items/%s/complete" % work_item_id,
            {"node_id": self.identity.node_id, "lease_id": self._required_lease(lease_id)},
        )

    def fail(self, work_item_id: str, *, lease_id: str) -> Dict[str, Any]:
        """Terminalize only after RC8 R1 contains evidenced FAILED/BLOCKED Attempt truth."""
        return self.center.post(
            "/api/v1/work-items/%s/fail" % work_item_id,
            {"node_id": self.identity.node_id, "lease_id": self._required_lease(lease_id)},
        )

    @staticmethod
    def _required_lease(lease_id: str) -> str:
        if not isinstance(lease_id, str) or not lease_id.strip():
            raise NodeAgentError("WORK_ITEM_LEASE_ID_REQUIRED")
        return lease_id.strip()

    @staticmethod
    def _offset_from(payload: Dict[str, Any]) -> int:
        value = payload.get("offset")
        if not isinstance(value, int):
            raise NodeAgentError("ARTIFACT_REMOTE_OFFSET_REQUIRED")
        return value
