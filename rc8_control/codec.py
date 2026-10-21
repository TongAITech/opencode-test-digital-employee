"""JSON-safe codecs shared by RC8 Center and Node HTTP transports."""

from __future__ import annotations

from typing import Any, Dict

from .models import CapabilityState, ExecutionNode, LeaseState, NodeCapability, NodeStatus, WorkItemLease
from .runtime_contracts import ArtifactAvailability, ArtifactManifest, RuntimeEventEnvelope


def node_to_dict(node: ExecutionNode) -> Dict[str, Any]:
    return {
        "node_id": node.node_id,
        "display_name": node.display_name,
        "platform": node.platform,
        "architecture": node.architecture,
        "operator": node.operator,
        "package_version": node.package_version,
        "status": node.status.value,
        "registered_at": node.registered_at,
        "heartbeat_at": node.heartbeat_at,
    }


def node_from_dict(data: Dict[str, Any]) -> ExecutionNode:
    node = ExecutionNode(
        node_id=str(data["node_id"]),
        display_name=str(data["display_name"]),
        platform=str(data["platform"]),
        architecture=str(data["architecture"]),
        operator=str(data.get("operator") or ""),
        package_version=str(data.get("package_version") or ""),
        status=NodeStatus(str(data.get("status") or NodeStatus.ONLINE.value)),
    )
    if "registered_at" in data:
        node.registered_at = int(data["registered_at"])
    if "heartbeat_at" in data:
        node.heartbeat_at = int(data["heartbeat_at"])
    return node


def capability_to_dict(capability: NodeCapability) -> Dict[str, Any]:
    return {
        "capability": capability.capability,
        "state": capability.state.value,
        "evidence_refs": list(capability.evidence_refs),
        "last_verified_at": capability.last_verified_at,
        "detail": capability.detail,
    }


def capability_from_dict(data: Dict[str, Any]) -> NodeCapability:
    return NodeCapability(
        capability=str(data["capability"]),
        state=CapabilityState(str(data["state"])),
        evidence_refs=list(data.get("evidence_refs") or []),
        last_verified_at=int(data["last_verified_at"]) if data.get("last_verified_at") is not None else None,
        detail=data.get("detail"),
    )


def lease_to_dict(lease: WorkItemLease) -> Dict[str, Any]:
    return {
        "lease_id": lease.lease_id,
        "work_item_id": lease.work_item_id,
        "node_id": lease.node_id,
        "required_capabilities": list(lease.required_capabilities),
        "issued_at": lease.issued_at,
        "expires_at": lease.expires_at,
        "state": lease.state.value,
    }


def lease_from_dict(data: Dict[str, Any]) -> WorkItemLease:
    return WorkItemLease(
        lease_id=str(data["lease_id"]),
        work_item_id=str(data["work_item_id"]),
        node_id=str(data["node_id"]),
        required_capabilities=list(data.get("required_capabilities") or []),
        issued_at=int(data["issued_at"]),
        expires_at=int(data["expires_at"]),
        state=LeaseState(str(data.get("state") or LeaseState.ACTIVE.value)),
    )


def event_to_dict(event: RuntimeEventEnvelope) -> Dict[str, Any]:
    return {
        "event_id": event.event_id,
        "test_run_id": event.test_run_id,
        "mission_id": event.mission_id,
        "work_item_id": event.work_item_id,
        "node_id": event.node_id,
        "event_type": event.event_type,
        "subject_type": event.subject_type,
        "subject_id": event.subject_id,
        "source_r1_event_id": event.source_r1_event_id,
        "source_r1_seq": event.source_r1_seq,
        "idempotency_key": event.idempotency_key,
        "refs": list(event.refs),
        "data": dict(event.data),
    }


def event_from_dict(data: Dict[str, Any]) -> RuntimeEventEnvelope:
    return RuntimeEventEnvelope(
        event_id=str(data["event_id"]),
        test_run_id=str(data["test_run_id"]),
        mission_id=str(data["mission_id"]),
        work_item_id=str(data["work_item_id"]),
        node_id=str(data["node_id"]),
        event_type=str(data["event_type"]),
        subject_type=str(data["subject_type"]),
        subject_id=str(data["subject_id"]),
        source_r1_event_id=str(data["source_r1_event_id"]),
        source_r1_seq=int(data["source_r1_seq"]),
        idempotency_key=str(data["idempotency_key"]),
        refs=list(data.get("refs") or []),
        data=dict(data.get("data") or {}),
    )


def artifact_to_dict(artifact: ArtifactManifest) -> Dict[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type,
        "test_run_id": artifact.test_run_id,
        "mission_id": artifact.mission_id,
        "work_item_id": artifact.work_item_id,
        "node_id": artifact.node_id,
        "producer_ref": artifact.producer_ref,
        "file_name": artifact.file_name,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
        "availability": artifact.availability.value,
        "case_id": artifact.case_id,
        "attempt_id": artifact.attempt_id,
        "step_id": artifact.step_id,
        "assertion_id": artifact.assertion_id,
        "subject_refs": list(artifact.subject_refs),
        "metadata": dict(artifact.metadata),
    }


def artifact_from_dict(data: Dict[str, Any]) -> ArtifactManifest:
    return ArtifactManifest(
        artifact_id=str(data["artifact_id"]),
        artifact_type=str(data["artifact_type"]),
        test_run_id=str(data["test_run_id"]),
        mission_id=str(data["mission_id"]),
        work_item_id=str(data["work_item_id"]),
        node_id=str(data["node_id"]),
        producer_ref=str(data["producer_ref"]),
        file_name=str(data["file_name"]),
        size_bytes=int(data["size_bytes"]),
        sha256=str(data["sha256"]),
        availability=ArtifactAvailability(str(data.get("availability") or ArtifactAvailability.DECLARED.value)),
        case_id=data.get("case_id"),
        attempt_id=data.get("attempt_id"),
        step_id=data.get("step_id"),
        assertion_id=data.get("assertion_id"),
        subject_refs=list(data.get("subject_refs") or []),
        metadata=dict(data.get("metadata") or {}),
    )
