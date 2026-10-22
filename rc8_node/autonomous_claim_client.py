"""Dependency-free HTTP client for autonomous RC8 WorkItem claiming.

The client discovers work through Center's claim-next API. It never scans local
files, guesses WorkItem IDs, or bypasses the existing lease protocol.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence


class AutonomousClaimError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClaimedWork:
    claimed: bool
    work_item: Optional[Dict[str, Any]]
    stage_instance_id: Optional[str]
    truth_note: str

    @property
    def work_item_id(self) -> Optional[str]:
        if not self.work_item:
            return None
        identity = self.work_item.get("identity") or {}
        value = identity.get("work_item_id")
        return str(value) if value else None

    @property
    def lease_id(self) -> Optional[str]:
        if not self.work_item:
            return None
        value = self.work_item.get("lease_id")
        return str(value) if value else None

    @property
    def stage(self) -> Optional[str]:
        if not self.work_item:
            return None
        identity = self.work_item.get("identity") or {}
        value = identity.get("stage")
        return str(value) if value else None


class AutonomousClaimClient:
    def __init__(self, center_url: str, node_id: str, *, timeout_seconds: int = 30) -> None:
        self.center_url = str(center_url or "").strip().rstrip("/")
        self.node_id = str(node_id or "").strip()
        self.timeout_seconds = int(timeout_seconds)
        if not self.center_url:
            raise AutonomousClaimError("CENTER_URL_REQUIRED")
        if not self.node_id:
            raise AutonomousClaimError("NODE_ID_REQUIRED")
        if self.timeout_seconds <= 0:
            raise AutonomousClaimError("HTTP_TIMEOUT_INVALID")

    def claim_next(
        self,
        *,
        ttl_seconds: int = 60,
        test_run_id: Optional[str] = None,
        stage_types: Optional[Sequence[str]] = None,
    ) -> ClaimedWork:
        payload: Dict[str, Any] = {"ttl_seconds": int(ttl_seconds)}
        if test_run_id:
            payload["test_run_id"] = str(test_run_id)
        if stage_types is not None:
            payload["stage_types"] = [
                str(value).strip()
                for value in stage_types
                if str(value or "").strip()
            ]
        node = urllib.parse.quote(self.node_id, safe="")
        body = self._json_request("POST", "/api/v1/nodes/%s/work/claim-next" % node, payload)
        return ClaimedWork(
            claimed=bool(body.get("claimed")),
            work_item=body.get("work_item") if isinstance(body.get("work_item"), dict) else None,
            stage_instance_id=str(body["stage_instance_id"]) if body.get("stage_instance_id") else None,
            truth_note=str(body.get("truth_note") or ""),
        )

    def _json_request(self, method: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.center_url + path,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                detail = json.loads(raw.decode("utf-8")).get("detail")
            except Exception:
                detail = raw.decode("utf-8", errors="replace")
            raise AutonomousClaimError("CENTER_HTTP_%s:%s" % (exc.code, detail)) from exc
        except OSError as exc:
            raise AutonomousClaimError("CENTER_HTTP_UNREACHABLE:%s" % exc) from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise AutonomousClaimError("CENTER_RESPONSE_INVALID_JSON") from exc
        if not isinstance(value, dict):
            raise AutonomousClaimError("CENTER_RESPONSE_OBJECT_REQUIRED")
        return value
