"""RC8 Node Agent skeleton.

The first slice talks to the in-process Center service boundary.  Later HTTP
transport will implement the same method contract; node semantics do not change.
"""

from __future__ import annotations

from typing import List, Optional

from rc8_control.models import CapabilityState, ExecutionNode, WorkItemLease
from rc8_control.runtime_contracts import ArtifactManifest, RuntimeEventEnvelope


class NodeAgent:
    def __init__(self, node: ExecutionNode, center) -> None:
        self.node = node
        self.center = center
        self.connected = False

    def connect(self, now: Optional[int] = None) -> ExecutionNode:
        registered = self.center.register_node(self.node, now=now)
        self.connected = True
        return registered

    def heartbeat(self, now: Optional[int] = None) -> ExecutionNode:
        if not self.connected:
            raise RuntimeError("NODE_AGENT_NOT_CONNECTED")
        return self.center.heartbeat(self.node.node_id, now=now)

    def report_capability(
        self,
        capability_name: str,
        state: CapabilityState,
        evidence_refs: Optional[List[str]] = None,
        detail: Optional[str] = None,
        now: Optional[int] = None,
    ):
        if not self.connected:
            raise RuntimeError("NODE_AGENT_NOT_CONNECTED")
        return self.center.report_capability(
            node_id=self.node.node_id,
            capability_name=capability_name,
            state=state,
            evidence_refs=evidence_refs,
            detail=detail,
            now=now,
        )

    def lease_work_item(
        self,
        work_item_id: str,
        required_capabilities: List[str],
        ttl_seconds: int,
        now: Optional[int] = None,
    ) -> WorkItemLease:
        if not self.connected:
            raise RuntimeError("NODE_AGENT_NOT_CONNECTED")
        return self.center.lease_work_item(
            work_item_id=work_item_id,
            node_id=self.node.node_id,
            required_capabilities=required_capabilities,
            ttl_seconds=ttl_seconds,
            now=now,
        )

    def renew_lease(self, work_item_id: str, ttl_seconds: int, now: Optional[int] = None) -> WorkItemLease:
        if not self.connected:
            raise RuntimeError("NODE_AGENT_NOT_CONNECTED")
        return self.center.renew_lease(
            work_item_id=work_item_id,
            node_id=self.node.node_id,
            ttl_seconds=ttl_seconds,
            now=now,
        )

    def release_lease(self, work_item_id: str) -> WorkItemLease:
        if not self.connected:
            raise RuntimeError("NODE_AGENT_NOT_CONNECTED")
        return self.center.release_lease(work_item_id, self.node.node_id)

    def publish_event(self, envelope: RuntimeEventEnvelope) -> RuntimeEventEnvelope:
        if not self.connected:
            raise RuntimeError("NODE_AGENT_NOT_CONNECTED")
        if envelope.node_id != self.node.node_id:
            raise RuntimeError("EVENT_NODE_ID_MISMATCH")
        return self.center.ingest_runtime_event(envelope)

    def declare_artifact(self, manifest: ArtifactManifest) -> ArtifactManifest:
        if not self.connected:
            raise RuntimeError("NODE_AGENT_NOT_CONNECTED")
        if manifest.node_id != self.node.node_id:
            raise RuntimeError("ARTIFACT_NODE_ID_MISMATCH")
        return self.center.declare_artifact(manifest)

    def begin_artifact_upload(self, artifact_id: str) -> ArtifactManifest:
        if not self.connected:
            raise RuntimeError("NODE_AGENT_NOT_CONNECTED")
        return self.center.begin_artifact_upload(artifact_id)

    def complete_artifact_upload(
        self,
        artifact_id: str,
        verified_size_bytes: int,
        verified_sha256: str,
    ) -> ArtifactManifest:
        if not self.connected:
            raise RuntimeError("NODE_AGENT_NOT_CONNECTED")
        return self.center.complete_artifact_upload(
            artifact_id=artifact_id,
            verified_size_bytes=verified_size_bytes,
            verified_sha256=verified_sha256,
        )
