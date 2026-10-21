"""Dependency-free RC8 Node -> Center HTTP client."""

from __future__ import annotations

import json
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rc8_control.codec import (
    artifact_from_dict,
    artifact_to_dict,
    capability_from_dict,
    event_from_dict,
    event_to_dict,
    lease_from_dict,
    node_from_dict,
    node_to_dict,
)
from rc8_control.models import CapabilityState, ExecutionNode
from rc8_control.runtime_contracts import ArtifactManifest, RuntimeEventEnvelope


class CenterHttpError(RuntimeError):
    pass


class HttpCenterClient:
    """Implements the Center method contract consumed by NodeAgent."""

    def __init__(self, base_url: str, timeout_seconds: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _post(self, path: str, payload: Optional[Dict] = None) -> Dict:
        encoded = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=encoded,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(detail)
                detail = payload.get("error") or detail
            except Exception:
                pass
            raise CenterHttpError("CENTER_HTTP_%s:%s" % (exc.code, detail))
        except URLError as exc:
            raise CenterHttpError("CENTER_UNREACHABLE:%s" % exc.reason)

    def register_node(self, node: ExecutionNode, now: Optional[int] = None) -> ExecutionNode:
        payload = {"node": node_to_dict(node)}
        if now is not None:
            payload["now"] = int(now)
        return node_from_dict(self._post("/api/control/nodes/register", payload)["node"])

    def heartbeat(self, node_id: str, now: Optional[int] = None) -> ExecutionNode:
        payload = {"node_id": node_id}
        if now is not None:
            payload["now"] = int(now)
        return node_from_dict(self._post("/api/control/nodes/heartbeat", payload)["node"])

    def report_capability(
        self,
        node_id: str,
        capability_name: str,
        state: CapabilityState,
        evidence_refs: Optional[List[str]] = None,
        detail: Optional[str] = None,
        now: Optional[int] = None,
    ):
        payload = {
            "node_id": node_id,
            "capability_name": capability_name,
            "state": state.value,
            "evidence_refs": list(evidence_refs or []),
            "detail": detail,
        }
        if now is not None:
            payload["now"] = int(now)
        return capability_from_dict(self._post("/api/control/nodes/capability", payload)["capability"])

    def lease_work_item(
        self,
        work_item_id: str,
        node_id: str,
        required_capabilities: List[str],
        ttl_seconds: int,
        now: Optional[int] = None,
    ):
        payload = {
            "work_item_id": work_item_id,
            "node_id": node_id,
            "required_capabilities": list(required_capabilities),
            "ttl_seconds": ttl_seconds,
        }
        if now is not None:
            payload["now"] = int(now)
        return lease_from_dict(self._post("/api/control/work-items/lease", payload)["lease"])

    def renew_lease(self, work_item_id: str, node_id: str, ttl_seconds: int, now: Optional[int] = None):
        payload = {"work_item_id": work_item_id, "node_id": node_id, "ttl_seconds": ttl_seconds}
        if now is not None:
            payload["now"] = int(now)
        return lease_from_dict(self._post("/api/control/work-items/renew", payload)["lease"])

    def release_lease(self, work_item_id: str, node_id: str):
        return lease_from_dict(
            self._post("/api/control/work-items/release", {"work_item_id": work_item_id, "node_id": node_id})["lease"]
        )

    def ingest_runtime_event(self, envelope: RuntimeEventEnvelope) -> RuntimeEventEnvelope:
        return event_from_dict(self._post("/api/control/events", {"event": event_to_dict(envelope)})["event"])

    def declare_artifact(self, manifest: ArtifactManifest) -> ArtifactManifest:
        return artifact_from_dict(
            self._post("/api/control/artifacts/declare", {"artifact": artifact_to_dict(manifest)})["artifact"]
        )

    def begin_artifact_upload(self, artifact_id: str) -> ArtifactManifest:
        return artifact_from_dict(
            self._post("/api/control/artifacts/begin", {"artifact_id": artifact_id})["artifact"]
        )

    def complete_artifact_upload(self, artifact_id: str, verified_size_bytes: int, verified_sha256: str) -> ArtifactManifest:
        return artifact_from_dict(
            self._post(
                "/api/control/artifacts/complete",
                {
                    "artifact_id": artifact_id,
                    "verified_size_bytes": verified_size_bytes,
                    "verified_sha256": verified_sha256,
                },
            )["artifact"]
        )
