"""Dependency-free local HTTP server for the RC7 administration platform."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.truth_overlay import install_rc7_truth_overlay
from .derived import AdminDerivedViews
from .projection import AdminProjection, AdminProjectionError, RESOURCE_TYPES

install_rc7_truth_overlay()
DERIVED_RESOURCES = {"test-obligations", "scripts"}


class AdminApplication:
    def __init__(self, r1_path: str) -> None:
        if not isinstance(r1_path, str) or not r1_path.strip():
            raise ValueError("R1_PATH_REQUIRED")
        self.r1_path = str(Path(r1_path).expanduser().resolve())
        self.truth = TruthRuntime(self.r1_path)
        self.projection = AdminProjection(self.truth)
        self.derived = AdminDerivedViews(self.truth)

    def health(self) -> Dict[str, Any]:
        return {"status": "UP", "truth": "R1_EVENT_STREAM", "r1_path": self.r1_path,
                "inventory": self.projection.inventory()}

    def dispatch_get(self, path: str, params: Dict[str, list]) -> Dict[str, Any]:
        clean = path.strip("/")
        if clean == "api/health": return self.health()
        if clean == "api/meta":
            return {"resources": sorted(set(RESOURCE_TYPES) | DERIVED_RESOURCES), "truth": "R1_EVENT_STREAM"}
        if not clean.startswith("api/"): raise AdminProjectionError("UNKNOWN_API")
        parts = clean.split("/")
        if len(parts) == 4 and parts[1] == "missions" and parts[3] in {"overview", "detail"}:
            mission_id = unquote(parts[2])
            return self.derived.mission_detail(mission_id) if parts[3] == "detail" else self.projection.mission_overview(mission_id)
        if len(parts) == 4 and parts[1] == "defects" and parts[3] == "detail":
            return self.derived.defect_detail(unquote(parts[2]))
        resource = parts[1] if len(parts) > 1 else ""
        if resource in DERIVED_RESOURCES:
            page, page_size, filters = self._query_params(params)
            if resource == "test-obligations":
                return self.derived.test_obligations(page=page, page_size=page_size, filters=filters)
            return self.derived.script_readiness(page=page, page_size=page_size, filters=filters)
        if resource not in RESOURCE_TYPES: raise AdminProjectionError("UNKNOWN_RESOURCE")
        if len(parts) == 3 and parts[2]:
            return {"item": self.projection.get_resource(resource, unquote(parts[2]))}
        page, page_size, filters = self._query_params(params)
        return self.projection.list_resource(resource, page=page, page_size=page_size, filters=filters)

    def dispatch_post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        parts = path.strip("/").split("/")
        if parts == ["api", "test-cases"]:
            return self.projection.create_test_case(body.get("case", body))
        if len(parts) == 4 and parts[:2] == ["api", "test-cases"] and parts[3] == "revisions":
            return self.projection.append_test_case_revision(unquote(parts[2]), body.get("case", body))
        if len(parts) == 4 and parts[:2] == ["api", "test-cases"] and parts[3] == "quarantine":
            return self.projection.quarantine_test_case(unquote(parts[2]), str(body.get("reason") or ""))
        raise AdminProjectionError("UNKNOWN_COMMAND")

    @staticmethod
    def _query_params(params: Dict[str, list]):
        page = _int_param(params, "page", 1); page_size = _int_param(params, "page_size", 20)
        filters = {}
        for key in ("version", "requirement", "sst", "status", "node", "risk", "source_revision", "date_from", "date_to", "q"):
            value = _first(params, key)
            if value: filters[key] = value
        return page, page_size, filters


def _first(params: Dict[str, list], key: str) -> str:
    values = params.get(key) or []
    return str(values[0]) if values else ""


def _int_param(params: Dict[str, list], key: str, default: int) -> int:
    raw = _first(params, key)
    if not raw: return default
    try: return int(raw)
    except ValueError as exc: raise AdminProjectionError("INVALID_%s" % key.upper()) from exc


def _static_root() -> Path: return Path(__file__).resolve().parent / "static"


def _handler(application: AdminApplication):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RC7Admin/2"
        def log_message(self, format: str, *args: Any) -> None: return
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                try: self._json(HTTPStatus.OK, application.dispatch_get(parsed.path, parse_qs(parsed.query)))
                except AdminProjectionError as exc:
                    self._json(HTTPStatus.NOT_FOUND if str(exc).endswith("NOT_FOUND") else HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                except Exception as exc: self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "ADMIN_INTERNAL_ERROR", "detail": str(exc)})
                return
            self._static(parsed.path)
        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/"): self._json(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"}); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 2 * 1024 * 1024: raise AdminProjectionError("REQUEST_BODY_TOO_LARGE")
                body = json.loads((self.rfile.read(length) if length else b"{}").decode("utf-8"))
                if not isinstance(body, dict): raise AdminProjectionError("REQUEST_BODY_MUST_BE_OBJECT")
                self._json(HTTPStatus.OK, application.dispatch_post(parsed.path, body))
            except (AdminProjectionError, json.JSONDecodeError) as exc: self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc: self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "ADMIN_INTERNAL_ERROR", "detail": str(exc)})
        def _json(self, status: HTTPStatus, payload: Dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(int(status)); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
        def _static(self, request_path: str) -> None:
            relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
            if ".." in Path(relative).parts: self.send_error(HTTPStatus.NOT_FOUND); return
            path = (_static_root() / relative).resolve(); root = _static_root().resolve()
            try: path.relative_to(root)
            except ValueError: self.send_error(HTTPStatus.NOT_FOUND); return
            if not path.is_file(): path = root / "index.html"
            data = path.read_bytes(); content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}: content_type += "; charset=utf-8"
            self.send_response(HTTPStatus.OK); self.send_header("Content-Type", content_type); self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    return Handler


def create_server(application: AdminApplication, host: str = "127.0.0.1", port: int = 4097) -> ThreadingHTTPServer:
    if not host: raise ValueError("HOST_REQUIRED")
    if port < 0 or port > 65535: raise ValueError("PORT_INVALID")
    return ThreadingHTTPServer((host, port), _handler(application))


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="RC7 测试数字员工后管平台")
    parser.add_argument("--r1", default=os.environ.get("PFC_RC7_R1_PATH", "state/rc7-r1.jsonl"))
    parser.add_argument("--host", default=os.environ.get("PFC_RC7_ADMIN_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PFC_RC7_ADMIN_PORT", "4097")))
    args = parser.parse_args(argv); application = AdminApplication(args.r1); server = create_server(application, args.host, args.port)
    print("RC7_ADMIN_READY http://%s:%s r1=%s" % (args.host, server.server_address[1], application.r1_path), flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
    return 0

if __name__ == "__main__": raise SystemExit(main())
