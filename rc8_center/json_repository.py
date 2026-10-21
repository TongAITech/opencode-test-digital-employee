"""Durable file repositories for the first RC8 single-node slice.

These adapters prove restart durability without adding hidden dependencies to
the bank smoke path. They are NOT the shared multi-user production database;
shared Center deployment will use the PostgreSQL adapter/schema behind the same
repository ports. The contracts deliberately stay storage-neutral.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from rc8_runtime import CapabilityQualification, CapabilityState, NodeIdentity, WorkItemIdentity
from rc8_runtime.artifacts import ArtifactManifest
from rc8_runtime import ArtifactAvailability, RuntimeProducerKind

from .control_plane import NodeRecord, NodeStatus, WorkItemRecord, WorkItemState


class DurableRepositoryError(ValueError):
    pass


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


class _AtomicJsonFile:
    def __init__(self, path: str, default: Dict[str, Any]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._default = default
        if not self.path.exists():
            self._write(default)

    def read(self) -> Dict[str, Any]:
        with self._lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise DurableRepositoryError("DURABLE_REPOSITORY_READ_FAILED") from exc
            if not isinstance(data, dict):
                raise DurableRepositoryError("DURABLE_REPOSITORY_ROOT_INVALID")
            return data

    def mutate(self, callback) -> None:
        with self._lock:
            data = self.read()
            callback(data)
            self._write(data)

    def _write(self, data: Dict[str, Any]) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        temp.write_text(encoded, encoding="utf-8")
        os.replace(str(temp), str(self.path))


class JsonFileCenterRepository:
    """Durable W1/local fallback implementing the CenterRepository port."""

    def __init__(self, path: str) -> None:
        self._file = _AtomicJsonFile(
            path,
            {"schema_version": 1, "nodes": {}, "capabilities": {}, "work_items": {}},
        )

    @staticmethod
    def _cap_key(node_id: str, capability_id: str) -> str:
        return "%s::%s" % (node_id, capability_id)

    def get_node(self, node_id: str) -> Optional[NodeRecord]:
        raw = self._file.read().get("nodes", {}).get(node_id)
        return self._node_from_raw(raw) if isinstance(raw, dict) else None

    def upsert_node(self, node: NodeRecord) -> None:
        def apply(data: Dict[str, Any]) -> None:
            data.setdefault("nodes", {})[node.identity.node_id] = _jsonable(node)
        self._file.mutate(apply)

    def list_nodes(self) -> List[NodeRecord]:
        raw = self._file.read().get("nodes", {})
        if not isinstance(raw, dict):
            raise DurableRepositoryError("DURABLE_NODES_INVALID")
        return [self._node_from_raw(raw[key]) for key in sorted(raw)]

    def get_capability(self, node_id: str, capability_id: str) -> Optional[CapabilityQualification]:
        raw = self._file.read().get("capabilities", {}).get(self._cap_key(node_id, capability_id))
        return self._capability_from_raw(raw) if isinstance(raw, dict) else None

    def upsert_capability(self, value: CapabilityQualification) -> None:
        key = self._cap_key(value.node_id, value.capability_id)
        def apply(data: Dict[str, Any]) -> None:
            data.setdefault("capabilities", {})[key] = _jsonable(value)
        self._file.mutate(apply)

    def list_capabilities(self, node_id: str) -> List[CapabilityQualification]:
        raw = self._file.read().get("capabilities", {})
        if not isinstance(raw, dict):
            raise DurableRepositoryError("DURABLE_CAPABILITIES_INVALID")
        prefix = node_id + "::"
        return [self._capability_from_raw(raw[key]) for key in sorted(raw) if key.startswith(prefix)]

    def get_work_item(self, work_item_id: str) -> Optional[WorkItemRecord]:
        raw = self._file.read().get("work_items", {}).get(work_item_id)
        return self._work_from_raw(raw) if isinstance(raw, dict) else None

    def upsert_work_item(self, value: WorkItemRecord) -> None:
        def apply(data: Dict[str, Any]) -> None:
            data.setdefault("work_items", {})[value.identity.work_item_id] = _jsonable(value)
        self._file.mutate(apply)

    def list_work_items(self) -> List[WorkItemRecord]:
        raw = self._file.read().get("work_items", {})
        if not isinstance(raw, dict):
            raise DurableRepositoryError("DURABLE_WORK_ITEMS_INVALID")
        return [self._work_from_raw(raw[key]) for key in sorted(raw)]

    @staticmethod
    def _node_from_raw(raw: Dict[str, Any]) -> NodeRecord:
        identity_raw = raw.get("identity")
        if not isinstance(identity_raw, dict):
            raise DurableRepositoryError("DURABLE_NODE_IDENTITY_INVALID")
        return NodeRecord(
            identity=NodeIdentity(**identity_raw),
            status=NodeStatus(str(raw.get("status"))),
            first_registered_at=int(raw.get("first_registered_at")),
            last_heartbeat_at=int(raw.get("last_heartbeat_at")),
        )

    @staticmethod
    def _capability_from_raw(raw: Dict[str, Any]) -> CapabilityQualification:
        return CapabilityQualification(
            node_id=str(raw.get("node_id") or ""),
            capability_id=str(raw.get("capability_id") or ""),
            state=CapabilityState(str(raw.get("state"))),
            probe_ref=str(raw["probe_ref"]) if raw.get("probe_ref") is not None else None,
            evidence_refs=list(raw.get("evidence_refs") or []),
            verified_at=int(raw["verified_at"]) if raw.get("verified_at") is not None else None,
        )

    @staticmethod
    def _work_from_raw(raw: Dict[str, Any]) -> WorkItemRecord:
        identity_raw = raw.get("identity")
        if not isinstance(identity_raw, dict):
            raise DurableRepositoryError("DURABLE_WORK_IDENTITY_INVALID")
        return WorkItemRecord(
            identity=WorkItemIdentity(**identity_raw),
            state=WorkItemState(str(raw.get("state"))),
            lease_id=str(raw["lease_id"]) if raw.get("lease_id") is not None else None,
            lease_owner_node_id=str(raw["lease_owner_node_id"]) if raw.get("lease_owner_node_id") is not None else None,
            lease_expires_at=int(raw["lease_expires_at"]) if raw.get("lease_expires_at") is not None else None,
        )


class JsonFileArtifactRepository:
    """Durable artifact metadata fallback paired with FileArtifactStore bytes."""

    def __init__(self, path: str) -> None:
        self._file = _AtomicJsonFile(path, {"schema_version": 1, "artifacts": {}})

    def get(self, artifact_id: str) -> Optional[ArtifactManifest]:
        raw = self._file.read().get("artifacts", {}).get(artifact_id)
        return self._artifact_from_raw(raw) if isinstance(raw, dict) else None

    def upsert(self, manifest: ArtifactManifest) -> None:
        def apply(data: Dict[str, Any]) -> None:
            data.setdefault("artifacts", {})[manifest.artifact_id] = _jsonable(manifest)
        self._file.mutate(apply)

    @staticmethod
    def _artifact_from_raw(raw: Dict[str, Any]) -> ArtifactManifest:
        return ArtifactManifest(
            artifact_id=str(raw.get("artifact_id") or ""),
            test_run_id=str(raw.get("test_run_id") or ""),
            work_item_id=str(raw.get("work_item_id") or ""),
            node_id=str(raw.get("node_id") or ""),
            kind=str(raw.get("kind") or ""),
            producer_kind=RuntimeProducerKind(str(raw.get("producer_kind"))),
            producer_ref=str(raw.get("producer_ref") or ""),
            file_name=str(raw.get("file_name") or ""),
            sha256=str(raw.get("sha256") or ""),
            size_bytes=int(raw.get("size_bytes") or 0),
            availability=ArtifactAvailability(str(raw.get("availability"))),
            case_id=str(raw["case_id"]) if raw.get("case_id") is not None else None,
            attempt_id=str(raw["attempt_id"]) if raw.get("attempt_id") is not None else None,
            step_id=str(raw["step_id"]) if raw.get("step_id") is not None else None,
            refs=list(raw.get("refs") or []),
            metadata=dict(raw.get("metadata") or {}),
            created_at=int(raw.get("created_at") or 0),
        )
