"""Storage-agnostic RC8 Center control service for the first vertical slice.

HTTP/PostgreSQL/Redis adapters are intentionally outside this class.  This
service establishes deterministic business/control semantics first so transport
and persistence can be swapped in without changing acceptance rules.
"""

from __future__ import annotations

from typing import List, Optional

from rc8_control.models import CapabilityState, ExecutionNode, WorkItemLease
from rc8_control.node_registry import NodeRegistry
from rc8_control.runtime_contracts import ArtifactManifest, RuntimeEventEnvelope
from rc8_control.runtime_ingest import RuntimeIngestStore


class CenterControlPlane:
    def __init__(self, offline_after_seconds: int = 60) -> None:
        self.nodes = NodeRegistry(offline_after_seconds=offline_after_seconds)
        self.runtime = RuntimeIngestStore()

    def register_node(self, node: ExecutionNode, now: Optional[int] = None) -> ExecutionNode:
        return self.nodes.register(node, now=now)

    def heartbeat(self, node_id: str, now: Optional[int] = None) -> ExecutionNode:
        return self.nodes.heartbeat(node_id, now=now)

    def report_capability(
        self,
        node_id: str,
        capability_name: str,
        state: CapabilityState,
        evidence_refs: Optional[List[str]] = None,
        detail: Optional[str] = None,
        now: Optional[int] = None,
    ):
        return self.nodes.report_capability(
            node_id=node_id,
            capability_name=capability_name,
            state=state,
            evidence_refs=evidence_refs,
            detail=detail,
            now=now,
        )

    def lease_work_item(
        self,
        work_item_id: str,
        node_id: str,
        required_capabilities: List[str],
        ttl_seconds: int,
        now: Optional[int] = None,
    ) -> WorkItemLease:
        return self.nodes.lease_work_item(
            work_item_id=work_item_id,
            node_id=node_id,
            required_capabilities=required_capabilities,
            ttl_seconds=ttl_seconds,
            now=now,
        )

    def renew_lease(
        self,
        work_item_id: str,
        node_id: str,
        ttl_seconds: int,
        now: Optional[int] = None,
    ) -> WorkItemLease:
        return self.nodes.renew_lease(
            work_item_id=work_item_id,
            node_id=node_id,
            ttl_seconds=ttl_seconds,
            now=now,
        )

    def release_lease(self, work_item_id: str, node_id: str) -> WorkItemLease:
        return self.nodes.release_lease(work_item_id, node_id)

    def ingest_runtime_event(self, envelope: RuntimeEventEnvelope) -> RuntimeEventEnvelope:
        return self.runtime.ingest_event(envelope)

    def declare_artifact(self, manifest: ArtifactManifest) -> ArtifactManifest:
        return self.runtime.declare_artifact(manifest)

    def begin_artifact_upload(self, artifact_id: str) -> ArtifactManifest:
        return self.runtime.begin_upload(artifact_id)

    def complete_artifact_upload(
        self,
        artifact_id: str,
        verified_size_bytes: int,
        verified_sha256: str,
    ) -> ArtifactManifest:
        return self.runtime.mark_available(
            artifact_id=artifact_id,
            verified_size_bytes=verified_size_bytes,
            verified_sha256=verified_sha256,
        )
