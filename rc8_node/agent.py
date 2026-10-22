"""RC8 Node Agent W1 client/runtime.

The node initiates outbound connections to Center. It never receives Center DB
credentials and never writes Center storage directly.

`NodeAgent` remains the W1 compatibility adapter. The formal Center protocol is
implemented by `rc8_node.formal_agent.FormalNodeAgent`; shared HTTP primitives
accept explicit headers so lease tokens remain visible protocol inputs rather
than hidden session state.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rc8_runtime import CapabilityQualification, NodeIdentity, RuntimeEventEnvelope
from rc8_runtime.artifacts import ArtifactManifest


class NodeAgentError(RuntimeError):
    pass


class HttpCenterClient:
    def __init__(self, base_url: str, *, timeout_seconds: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        if not self.base_url:
            raise NodeAgentError("CENTER_URL_REQUIRED")
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _headers(base: Dict[str, str], extra: Optional[Dict[str, str]]) -> Dict[str, str]:
        result = dict(base)
        if extra:
            result.update({str(key): str(value) for key, value in extra.items()})
        return result

    def get(self, path: str, *, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        request = Request(
            self.base_url + path,
            method="GET",
            headers=self._headers({"Accept": "application/json"}, headers),
        )
        return self._send(request)

    def post(
        self,
        path: str,
        payload: Dict[str, Any],
        *,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            method="POST",
            headers=self._headers(
                {"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"},
                headers,
            ),
        )
        return self._send(request)

    def put_bytes(
        self,
        path: str,
        data: bytes,
        *,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        request = Request(
            self.base_url + path,
            data=data,
            method="PUT",
            headers=self._headers(
                {"Accept": "application/json", "Content-Type": "application/octet-stream"},
                headers,
            ),
        )
        return self._send(request)

    def _send(self, request: Request) -> Dict[str, Any]:
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                payload = json.loads(raw or "{}")
                if not isinstance(payload, dict):
                    raise NodeAgentError("CENTER_RESPONSE_MUST_BE_OBJECT")
                return payload
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(detail)
                message = str(payload.get("detail") or payload.get("error") or detail)
            except ValueError:
                message = detail or str(exc)
            raise NodeAgentError("CENTER_HTTP_%s:%s" % (exc.code, message)) from exc
        except URLError as exc:
            raise NodeAgentError("CENTER_UNREACHABLE:%s" % exc.reason) from exc


class NodeIdentityStore:
    """Persists stable node identity locally so DSH/Node restarts reuse it."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load_or_create(
        self,
        *,
        node_id: str,
        operator_ref: str,
        os_family: str,
        architecture: str,
        shell: str,
        now: Optional[int] = None,
    ) -> NodeIdentity:
        if self.path.is_file():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise NodeAgentError("NODE_IDENTITY_FILE_INVALID")
            identity = NodeIdentity(**raw)
            if identity.node_id != node_id:
                raise NodeAgentError("NODE_IDENTITY_FILE_NODE_MISMATCH")
            return identity

        identity = NodeIdentity(
            node_id=node_id,
            operator_ref=operator_ref,
            os_family=os_family,
            architecture=architecture,
            shell=shell,
            registered_at=int(now if now is not None else time.time()),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(asdict(identity), ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(str(temp), str(self.path))
        return identity


class NodeAgent:
    """Legacy W1 compatibility adapter. New formal flows use FormalNodeAgent."""

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
        payload = asdict(value)
        payload["state"] = value.state.value
        return self.center.post("/api/v1/nodes/%s/capabilities" % self.identity.node_id, payload)

    def lease(self, work_item_id: str, *, ttl_seconds: int = 60) -> Dict[str, Any]:
        return self.center.post(
            "/api/v1/work-items/%s/lease" % work_item_id,
            {"node_id": self.identity.node_id, "ttl_seconds": ttl_seconds},
        )

    def start(self, work_item_id: str) -> Dict[str, Any]:
        return self.center.post(
            "/api/v1/work-items/%s/start" % work_item_id,
            {"node_id": self.identity.node_id},
        )

    def append_runtime_event(self, event: RuntimeEventEnvelope) -> Dict[str, Any]:
        if event.node_id != self.identity.node_id:
            raise NodeAgentError("RUNTIME_EVENT_NODE_MISMATCH")
        payload = asdict(event)
        payload["plane"] = event.plane.value
        payload["producer_kind"] = event.producer_kind.value
        return self.center.post("/api/v1/runtime-events", payload)

    def upload_artifact_file(
        self,
        manifest: ArtifactManifest,
        file_path: str,
        *,
        chunk_size: int = 1024 * 1024,
    ) -> Dict[str, Any]:
        if manifest.node_id != self.identity.node_id:
            raise NodeAgentError("ARTIFACT_NODE_MISMATCH")
        if not isinstance(chunk_size, int) or chunk_size <= 0:
            raise NodeAgentError("ARTIFACT_CHUNK_SIZE_INVALID")
        path = Path(file_path)
        if not path.is_file():
            raise NodeAgentError("ARTIFACT_FILE_NOT_FOUND")
        actual_size = path.stat().st_size
        if actual_size != manifest.size_bytes:
            raise NodeAgentError("ARTIFACT_LOCAL_SIZE_MISMATCH")
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            while True:
                block = fh.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
        if digest.hexdigest().lower() != manifest.sha256.lower():
            raise NodeAgentError("ARTIFACT_LOCAL_HASH_MISMATCH")

        payload = asdict(manifest)
        payload["availability"] = manifest.availability.value
        payload["producer_kind"] = manifest.producer_kind.value
        self.center.post("/api/v1/artifacts/begin", payload)
        offset_payload = self.center.get("/api/v1/artifacts/%s/offset" % manifest.artifact_id)
        offset = int(offset_payload.get("offset") or 0)
        if offset < 0 or offset > manifest.size_bytes:
            raise NodeAgentError("ARTIFACT_REMOTE_OFFSET_INVALID")

        with path.open("rb") as fh:
            fh.seek(offset)
            while offset < manifest.size_bytes:
                chunk = fh.read(min(chunk_size, manifest.size_bytes - offset))
                if not chunk:
                    raise NodeAgentError("ARTIFACT_LOCAL_READ_UNEXPECTED_EOF")
                uploaded = self.center.put_bytes(
                    "/api/v1/artifacts/%s/content?offset=%s" % (manifest.artifact_id, offset),
                    chunk,
                )
                next_offset = int(uploaded.get("next_offset") or -1)
                expected = offset + len(chunk)
                if next_offset != expected:
                    raise NodeAgentError("ARTIFACT_REMOTE_OFFSET_DIVERGED:%s:%s" % (next_offset, expected))
                offset = next_offset
        return self.center.post("/api/v1/artifacts/%s/complete" % manifest.artifact_id, {})

    def complete(self, work_item_id: str) -> Dict[str, Any]:
        return self.center.post(
            "/api/v1/work-items/%s/complete" % work_item_id,
            {"node_id": self.identity.node_id},
        )


def detect_platform() -> Dict[str, str]:
    forced_os = os.environ.get("RC8_NODE_OS", "").strip().lower()
    forced_shell = os.environ.get("RC8_NODE_SHELL", "").strip().lower()
    system = forced_os or platform.system().lower()
    architecture = platform.machine().lower() or "unknown"
    if system.startswith("win") or system in {"msys", "mingw", "cygwin"}:
        return {"os_family": "windows", "architecture": architecture, "shell": forced_shell or "git-bash"}
    if system == "linux":
        return {"os_family": "linux", "architecture": architecture, "shell": forced_shell or "bash"}
    raise NodeAgentError("NODE_PLATFORM_UNSUPPORTED:%s" % system)
