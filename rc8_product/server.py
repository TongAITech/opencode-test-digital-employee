"""Minimal dependency-free HTTP surface for the RC8 product vertical slice."""

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

from .application import ProductApplication, ProductError


def _static_root() -> Path:
    return Path(__file__).resolve().parent / "static"


def _first(params: Dict[str, list], key: str) -> str:
    values = params.get(key) or []
    return str(values[0]) if values else ""


def _handler(application: ProductApplication):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RC8Product/0.1"

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
    print("RC8_PRODUCT_READY http://%s:%s" % (args.host, server.server_address[1]), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
