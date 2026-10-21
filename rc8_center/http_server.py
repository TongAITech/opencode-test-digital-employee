"""Small W1 HTTP boundary for RC8 Center/Node protocol.

The HTTP layer contains no business decisions: ownership/capability/runtime
truth checks remain in CenterControlPlane. Artifact bytes are accepted only
through Artifact Sync and only for the node that holds the active WorkItem
lease. The implementation uses Python stdlib so the first bank slice has no
hidden web-framework install dependency.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from rc8_runtime import (
    ArtifactAvailability,
    CapabilityQualification,
    CapabilityState,
    NodeIdentity,
    RuntimeEventEnvelope,
    RuntimeProducerKind,
    WorkItemIdentity,
)
from rc8_runtime.artifacts import ArtifactManifest

from .artifacts import ArtifactSyncError, FileArtifactStore
from .control_plane import CenterControlError, CenterControlPlane, NodeStatus


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


def _node_identity(body: Dict[str, Any]) -> NodeIdentity:
    return NodeIdentity(
        node_id=str(body.get("node_id") or ""),
        operator_ref=str(body.get("operator_ref") or ""),
        os_family=str(body.get("os_family") or ""),
        architecture=str(body.get("architecture") or ""),
        shell=str(body.get("shell") or ""),
        registered_at=int(body.get("registered_at") or 0),
    )


def _capability(body: Dict[str, Any]) -> CapabilityQualification:
    verified_at = body.get("verified_at")
    return CapabilityQualification(
        node_id=str(body.get("node_id") or ""),
        capability_id=str(body.get("capability_id") or ""),
        state=CapabilityState(str(body.get("state") or "")),
        probe_ref=str(body["probe_ref"]) if body.get("probe_ref") is not None else None,
        evidence_refs=list(body.get("evidence_refs") or []),
        verified_at=int(verified_at) if verified_at is not None else None,
    )


def _work_identity(body: Dict[str, Any]) -> WorkItemIdentity:
    return WorkItemIdentity(
        work_item_id=str(body.get("work_item_id") or ""),
        test_run_id=str(body.get("test_run_id") or ""),
        stage=str(body.get("stage") or ""),
        scope_refs=list(body.get("scope_refs") or []),
        required_capabilities=list(body.get("required_capabilities") or []),
    )


def _runtime_event(body: Dict[str, Any]) -> RuntimeEventEnvelope:
    return RuntimeEventEnvelope(
        event_id=str(body.get("event_id") or ""),
        test_run_id=str(body.get("test_run_id") or ""),
        work_item_id=str(body.get("work_item_id") or ""),
        node_id=str(body.get("node_id") or ""),
        producer_kind=RuntimeProducerKind(str(body.get("producer_kind") or "")),
        producer_ref=str(body.get("producer_ref") or ""),
        event_type=str(body.get("event_type") or ""),
        sequence=int(body.get("sequence") or 0),
        case_id=str(body["case_id"]) if body.get("case_id") is not None else None,
        attempt_id=str(body["attempt_id"]) if body.get("attempt_id") is not None else None,
        step_id=str(body["step_id"]) if body.get("step_id") is not None else None,
        refs=list(body.get("refs") or []),
        data=dict(body.get("data") or {}),
        occurred_at=int(body.get("occurred_at") or 0),
    )


def _artifact_manifest(body: Dict[str, Any]) -> ArtifactManifest:
    created_at = body.get("created_at")
    kwargs: Dict[str, Any] = {
        "artifact_id": str(body.get("artifact_id") or ""),
        "test_run_id": str(body.get("test_run_id") or ""),
        "work_item_id": str(body.get("work_item_id") or ""),
        "node_id": str(body.get("node_id") or ""),
        "kind": str(body.get("kind") or ""),
        "producer_kind": RuntimeProducerKind(str(body.get("producer_kind") or "")),
        "producer_ref": str(body.get("producer_ref") or ""),
        "file_name": str(body.get("file_name") or ""),
        "sha256": str(body.get("sha256") or ""),
        "size_bytes": int(body.get("size_bytes") or 0),
        "availability": ArtifactAvailability(str(body.get("availability") or ArtifactAvailability.PENDING_UPLOAD.value)),
        "case_id": str(body["case_id"]) if body.get("case_id") is not None else None,
        "attempt_id": str(body["attempt_id"]) if body.get("attempt_id") is not None else None,
        "step_id": str(body["step_id"]) if body.get("step_id") is not None else None,
        "refs": list(body.get("refs") or []),
        "metadata": dict(body.get("metadata") or {}),
    }
    if created_at is not None:
        kwargs["created_at"] = int(created_at)
    return ArtifactManifest(**kwargs)


class CenterHttpApplication:
    def __init__(self, control: CenterControlPlane, artifact_store: Optional[FileArtifactStore] = None) -> None:
        self.control = control
        self.artifact_store = artifact_store

    def get(self, path: str) -> Dict[str, Any]:
        clean = path.strip("/")
        parts = clean.split("/")
        if clean == "health":
            return {"status": "READY", "service": "RC8_CENTER"}
        if clean == "api/v1/nodes":
            return {"items": [_jsonable(v) for v in self.control.repository.list_nodes()]}
        if clean == "api/v1/work-items":
            return {"items": [_jsonable(v) for v in self.control.repository.list_work_items()]}
        if len(parts) == 5 and parts[:3] == ["api", "v1", "artifacts"] and parts[4] == "offset":
            store = self._artifacts()
            artifact_id = parts[3]
            manifest = store.repository.get(artifact_id)
            if manifest is None:
                raise ArtifactSyncError("ARTIFACT_NOT_FOUND")
            return {
                "artifact_id": artifact_id,
                "offset": store.current_offset(artifact_id),
                "availability": manifest.availability.value,
            }
        raise CenterControlError("ENDPOINT_NOT_FOUND")

    def post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        clean = path.strip("/")
        parts = clean.split("/")
        if clean == "api/v1/nodes/register":
            return {"node": _jsonable(self.control.register_node(_node_identity(body)))}
        if clean == "api/v1/work-items/register":
            return {"work_item": _jsonable(self.control.register_work_item(_work_identity(body)))}
        if clean == "api/v1/runtime-events":
            return {"receipt": _jsonable(self.control.append_runtime_event(_runtime_event(body)))}
        if clean == "api/v1/artifacts/begin":
            manifest = _artifact_manifest(body)
            self.control.authorize_work_item_write(
                test_run_id=manifest.test_run_id,
                work_item_id=manifest.work_item_id,
                node_id=manifest.node_id,
            )
            return {"artifact": _jsonable(self._artifacts().begin(manifest))}

        if len(parts) == 5 and parts[:3] == ["api", "v1", "nodes"]:
            node_id, action = parts[3], parts[4]
            if action == "heartbeat":
                status = body.get("status")
                parsed = NodeStatus(str(status)) if status is not None else None
                return {"node": _jsonable(self.control.heartbeat(node_id, status=parsed))}
            if action == "capabilities":
                value = _capability(dict(body, node_id=node_id))
                return {"capability": _jsonable(self.control.qualify_capability(value))}

        if len(parts) == 5 and parts[:3] == ["api", "v1", "work-items"]:
            work_item_id, action = parts[3], parts[4]
            node_id = str(body.get("node_id") or "")
            if action == "lease":
                ttl = int(body.get("ttl_seconds") or 60)
                return {"work_item": _jsonable(self.control.lease_work_item(work_item_id, node_id, ttl_seconds=ttl))}
            if action == "start":
                return {"work_item": _jsonable(self.control.start_work_item(work_item_id, node_id))}
            if action == "complete":
                return {"work_item": _jsonable(self.control.complete_work_item(work_item_id, node_id))}

        if len(parts) == 5 and parts[:3] == ["api", "v1", "artifacts"] and parts[4] == "complete":
            artifact_id = parts[3]
            store = self._artifacts()
            manifest = store.repository.get(artifact_id)
            if manifest is None:
                raise ArtifactSyncError("ARTIFACT_NOT_FOUND")
            self.control.authorize_work_item_write(
                test_run_id=manifest.test_run_id,
                work_item_id=manifest.work_item_id,
                node_id=manifest.node_id,
            )
            return {"artifact": _jsonable(store.complete(artifact_id))}
        raise CenterControlError("ENDPOINT_NOT_FOUND")

    def put(self, path: str, query: Dict[str, Any], data: bytes) -> Dict[str, Any]:
        clean = path.strip("/")
        parts = clean.split("/")
        if len(parts) == 5 and parts[:3] == ["api", "v1", "artifacts"] and parts[4] == "content":
            artifact_id = parts[3]
            store = self._artifacts()
            manifest = store.repository.get(artifact_id)
            if manifest is None:
                raise ArtifactSyncError("ARTIFACT_NOT_FOUND")
            self.control.authorize_work_item_write(
                test_run_id=manifest.test_run_id,
                work_item_id=manifest.work_item_id,
                node_id=manifest.node_id,
            )
            offset_values = query.get("offset") or []
            if not offset_values:
                raise ArtifactSyncError("ARTIFACT_OFFSET_REQUIRED")
            offset = int(offset_values[0])
            return {"artifact_id": artifact_id, "next_offset": store.upload_chunk(artifact_id, offset=offset, data=data)}
        raise CenterControlError("ENDPOINT_NOT_FOUND")

    def _artifacts(self) -> FileArtifactStore:
        if self.artifact_store is None:
            raise ArtifactSyncError("ARTIFACT_STORE_NOT_CONFIGURED")
        return self.artifact_store


def _handler(application: CenterHttpApplication):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RC8CenterW1/1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                self._json(HTTPStatus.OK, application.get(parsed.path))
            except (CenterControlError, ArtifactSyncError, ValueError, KeyError) as exc:
                status = HTTPStatus.NOT_FOUND if str(exc) == "ENDPOINT_NOT_FOUND" else HTTPStatus.BAD_REQUEST
                self._json(status, {"error": str(exc)})
            except Exception as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "CENTER_INTERNAL_ERROR", "detail": str(exc)})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                body = json.loads(raw.decode("utf-8"))
                if not isinstance(body, dict):
                    raise CenterControlError("REQUEST_BODY_MUST_BE_OBJECT")
                self._json(HTTPStatus.OK, application.post(parsed.path, body))
            except (CenterControlError, ArtifactSyncError, ValueError, KeyError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "CENTER_INTERNAL_ERROR", "detail": str(exc)})

        def do_PUT(self) -> None:
            parsed = urlparse(self.path)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b""
                self._json(HTTPStatus.OK, application.put(parsed.path, parse_qs(parsed.query), raw))
            except (CenterControlError, ArtifactSyncError, ValueError, KeyError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "CENTER_INTERNAL_ERROR", "detail": str(exc)})

        def _json(self, status: HTTPStatus, payload: Dict[str, Any]) -> None:
            encoded = json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def create_server(application: CenterHttpApplication, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), _handler(application))
