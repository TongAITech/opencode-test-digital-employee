from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from .server import AdminApplication, AdminProjectionError
from .requirement_hierarchy import RequirementHierarchyView


class ProductAdminApplication(AdminApplication):
    def __init__(self, r1_path: str) -> None:
        super().__init__(r1_path)
        self.requirement_hierarchy = RequirementHierarchyView(self.truth)

    def dispatch_get(self, path: str, params: Dict[str, list]) -> Dict[str, Any]:
        clean = path.strip("/")
        if clean == "api/requirement-hierarchy":
            page, page_size, filters = self._query_params(params)
            level = (params.get("level") or [""])[0]
            if level:
                filters["level"] = str(level)
            return self.requirement_hierarchy.list(page=page, page_size=page_size, filters=filters)
        if clean == "api/meta":
            result = super().dispatch_get(path, params)
            resources = set(result.get("resources") or [])
            resources.add("requirement-hierarchy")
            result["resources"] = sorted(resources)
            result["product_surface"] = "RC7_ADMIN_PRODUCT_V4"
            return result
        return super().dispatch_get(path, params)


class WorkbenchPublicApplication:
    """Static/meta facade: safe CLI never opens or creates an R1 store."""
    def dispatch_get(self, path, params):
        if path != '/api/meta':raise AdminProjectionError('FORBIDDEN')
        return {'resources':['workbench'], 'product_surface':'DSH_WORKBENCH', 'host_identity_required':True}


def _static_root() -> Path:
    return Path(__file__).resolve().parent / "static"


def _handler(application: ProductAdminApplication, workbench_handler=None, *, workbench_mode=False):
    mounted_workbench = workbench_mode or workbench_handler is not None
    class Handler(workbench_handler or BaseHTTPRequestHandler):
        server_version = "RC7AdminProduct/4"
        def log_message(self, format: str, *args: Any) -> None: return

        def _handle_workbench_request(self, method: str) -> None:
            if workbench_handler is not None:
                getattr(workbench_handler, 'do_' + method)(self)
                return
            # The source archive can start before a business/Host adapter is
            # installed. Keep these routes closed using only the admin package.
            path = urlparse(self.path).path
            writable_route = ('/batches/' in path or
                              re.fullmatch(r'/api/workbench/v1/projects/[^/]+/metadata', path) is not None)
            if method == 'GET' or (method in ('POST', 'PATCH', 'DELETE') and writable_route):
                status, code = HTTPStatus.SERVICE_UNAVAILABLE, 'HOST_IDENTITY_UNAVAILABLE'
            else:
                status, code = HTTPStatus.METHOD_NOT_ALLOWED, 'METHOD_NOT_ALLOWED'
            try:
                self._json(status, {'error': {'code': code}})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.close_connection = True

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/workbench/v1" or parsed.path.startswith("/api/workbench/v1/"):
                self._handle_workbench_request('GET')
                return
            if mounted_workbench and parsed.path.startswith("/api/") and parsed.path != "/api/meta":
                self._json(HTTPStatus.FORBIDDEN, {"error": {"code": "FORBIDDEN"}})
                return
            if parsed.path.startswith("/api/"):
                try:
                    self._json(HTTPStatus.OK, application.dispatch_get(parsed.path, parse_qs(parsed.query)))
                except AdminProjectionError as exc:
                    self._json(HTTPStatus.NOT_FOUND if str(exc).endswith("NOT_FOUND") else HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                except Exception as exc:
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "ADMIN_INTERNAL_ERROR", "detail": str(exc)})
                return
            self._static(parsed.path)
        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/workbench/v1" or parsed.path.startswith("/api/workbench/v1/"):
                self._handle_workbench_request('POST')
                return
            if mounted_workbench and parsed.path.startswith("/api/"):
                self.close_connection = True
                self._json(HTTPStatus.FORBIDDEN, {"error": {"code": "FORBIDDEN"}})
                return
            if not parsed.path.startswith("/api/"):
                self._json(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"}); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads((self.rfile.read(length) if length else b"{}").decode("utf-8"))
                if not isinstance(body, dict): raise AdminProjectionError("REQUEST_BODY_MUST_BE_OBJECT")
                self._json(HTTPStatus.OK, application.dispatch_post(parsed.path, body))
            except (AdminProjectionError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "ADMIN_INTERNAL_ERROR", "detail": str(exc)})

        def do_PATCH(self) -> None:
            self._handle_workbench_request('PATCH')

        def do_DELETE(self) -> None:
            self._handle_workbench_request('DELETE')

        def do_PUT(self) -> None:
            self._handle_workbench_request('PUT')

        def _json(self, status: HTTPStatus, payload: Dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(int(status)); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
        def _static(self, request_path: str) -> None:
            relative = "workbench/index.html" if request_path in {"/workbench", "/workbench/"} else ("product-index.html" if request_path in {"", "/"} else request_path.lstrip("/"))
            if ".." in Path(relative).parts: self.send_error(HTTPStatus.NOT_FOUND); return
            path = (_static_root() / relative).resolve(); root = _static_root().resolve()
            try: path.relative_to(root)
            except ValueError: self.send_error(HTTPStatus.NOT_FOUND); return
            if not path.is_file(): path = root / "product-index.html"
            data = path.read_bytes(); content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}: content_type += "; charset=utf-8"
            self.send_response(HTTPStatus.OK); self.send_header("Content-Type", content_type); self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    return Handler


def create_server(application: ProductAdminApplication, host: str = "127.0.0.1", port: int = 4097, *, workbench_handler=None, workbench_mode=False) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), _handler(application, workbench_handler, workbench_mode=workbench_mode))


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="RC7 测试数字员工产品化后管")
    parser.add_argument("--r1", default=os.environ.get("PFC_RC7_R1_PATH", "runtime-state/r1/event-stream.jsonl"))
    parser.add_argument("--host", default=os.environ.get("PFC_RC7_ADMIN_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PFC_RC7_ADMIN_PORT", "4097")))
    parser.add_argument("--workbench", action="store_true", help="Disable legacy private APIs; Host integration is still required")
    args = parser.parse_args(argv)
    app = WorkbenchPublicApplication() if args.workbench else ProductAdminApplication(args.r1)
    server = create_server(app, args.host, args.port, workbench_mode=args.workbench)
    if args.workbench:
        print("DSH_WORKBENCH_READY http://%s:%s HOST_INTEGRATION_REQUIRED" % (args.host, server.server_address[1]), flush=True)
    else:
        print("RC7_ADMIN_PRODUCT_READY http://%s:%s r1=%s" % (args.host, server.server_address[1], app.r1_path), flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
    return 0


if __name__ == "__main__": raise SystemExit(main())
