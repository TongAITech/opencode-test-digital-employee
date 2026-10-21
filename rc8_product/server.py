"""Dependency-free RC8 Center HTTP surface for product and node control."""

from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

from rc8_center import CenterControlPlane
from rc8_control.codec import (
    artifact_from_dict,
    artifact_to_dict,
    capability_to_dict,
    event_from_dict,
    event_to_dict,
    lease_to_dict,
    node_from_dict,
    node_to_dict,
)
from rc8_control.models import CapabilityState
from rc8_control.node_registry import NodeRegistryError
from rc8_control.runtime_ingest import RuntimeIngestError

from .application import ProductApplication, ProductError


def _static_root() -> Path:
    return Path(__file__).resolve().parent / "static"


def _first(params: Dict[str, list], key: str) -> str:
    values = params.get(key) or []
    return str(values[0]) if values else ""


def _optional_int(payload: Dict[str, Any], key: str) -> Optional[int]:
    value = payload.get(key)
    return None if value is None else int(value)


def _handler(application: ProductApplication):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RC8Center/0.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                self._json(HTTPStatus.OK, application.health())
                return
            if parsed.path == "/api/nodes":
                query = parse_qs(parsed.query)
                params = {key: _first(query, key) for key in ("status", "operator", "capability", "q")}
                self._json(HTTPStatus.OK, application.list_nodes(params))
                return
            if parsed.path.startswith("/api/nodes/"):
                node_id = unquote(parsed.path[len("/api/nodes/"):])
                try:
                    self._json(HTTPStatus.OK, application.node_detail(node_id))
                except ProductError as exc:
                    self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            if parsed.path.startswith("/api/"):
                self._json(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"})
                return
            self._static(parsed.path)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/control/"):
                self._json(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"})
                return
            try:
                payload = self._read_json()
                result = self._control_post(parsed.path, payload)
                self._json(HTTPStatus.OK, result)
            except (KeyError, TypeError, ValueError, NodeRegistryError, RuntimeIngestError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "CENTER_INTERNAL_ERROR", "detail": str(exc)})

        def _control_post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
            center = application.center
            if path == "/api/control/nodes/register":
                node = center.register_node(node_from_dict(payload["node"]), now=_optional_int(payload, "now"))
                return {"node": node_to_dict(node)}
            if path == "/api/control/nodes/heartbeat":
                node = center.heartbeat(str(payload["node_id"]), now=_optional_int(payload, "now"))
                return {"node": node_to_dict(node)}
            if path == "/api/control/nodes/capability":
                capability = center.report_capability(
                    node_id=str(payload["node_id"]),
                    capability_name=str(payload["capability_name"]),
                    state=CapabilityState(str(payload["state"])),
                    evidence_refs=list(payload.get("evidence_refs") or []),
                    detail=payload.get("detail"),
                    now=_optional_int(payload, "now"),
                )
                return {"capability": capability_to_dict(capability)}
            if path == "/api/control/work-items/lease":
                lease = center.lease_work_item(
                    work_item_id=str(payload["work_item_id"]),
                    node_id=str(payload["node_id"]),
                    required_capabilities=list(payload.get("required_capabilities") or []),
                    ttl_seconds=int(payload["ttl_seconds"]),
                    now=_optional_int(payload, "now"),
                )
                return {"lease": lease_to_dict(lease)}
            if path == "/api/control/work-items/renew":
                lease = center.renew_lease(
                    work_item_id=str(payload["work_item_id"]),
                    node_id=str(payload["node_id"]),
                    ttl_seconds=int(payload["ttl_seconds"]),
                    now=_optional_int(payload, "now"),
                )
                return {"lease": lease_to_dict(lease)}
            if path == "/api/control/work-items/release":
                lease = center.release_lease(str(payload["work_item_id"]), str(payload["node_id"]))
                return {"lease": lease_to_dict(lease)}
            if path == "/api/control/events":
                event = center.ingest_runtime_event(event_from_dict(payload["event"]))
                return {"event": event_to_dict(event)}
            if path == "/api/control/artifacts/declare":
                artifact = center.declare_artifact(artifact_from_dict(payload["artifact"]))
                return {"artifact": artifact_to_dict(artifact)}
            if path == "/api/control/artifacts/begin":
                artifact = center.begin_artifact_upload(str(payload["artifact_id"]))
                return {"artifact": artifact_to_dict(artifact)}
            if path == "/api/control/artifacts/complete":
                artifact = center.complete_artifact_upload(
                    artifact_id=str(payload["artifact_id"]),
                    verified_size_bytes=int(payload["verified_size_bytes"]),
                    verified_sha256=str(payload["verified_sha256"]),
                )
                return {"artifact": artifact_to_dict(artifact)}
            raise ValueError("CONTROL_ROUTE_NOT_FOUND:%s" % path)

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("REQUEST_BODY_MUST_BE_OBJECT")
            return value

        def _json(self, status: HTTPStatus, payload: Dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _static(self, request_path: str) -> None:
            relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
            if ".." in Path(relative).parts:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            root = _static_root().resolve()
            path = (root / relative).resolve()
            try:
                path.relative_to(root)
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not path.is_file():
                path = root / "index.html"
            data = path.read_bytes()
            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
                content_type += "; charset=utf-8"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def create_server(application: ProductApplication, host: str = "127.0.0.1", port: int = 4098) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), _handler(application))


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="RC8 测试数字员工中央后管")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4098)
    args = parser.parse_args(argv)
    center = CenterControlPlane()
    application = ProductApplication(center)
    server = create_server(application, args.host, args.port)
    print("RC8_CENTER_READY http://%s:%s" % (args.host, server.server_address[1]), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
