#!/usr/bin/env python3
"""Transparent metadata-only trace proxy for Ollama's OpenAI-compatible API.

This diagnostic helper forwards request/response bytes without modifying JSON
payloads. It logs only request shape and timing metadata; prompt contents,
response bodies, Authorization headers, and API keys are never logged.
"""
from __future__ import annotations

import argparse
import http.client
import json
import threading
import time
import uuid
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def _content_chars(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(_content_chars(item) for item in value)
    if isinstance(value, dict):
        return sum(
            _content_chars(value.get(key))
            for key in ("content", "text")
            if key in value
        )
    return 0


def _request_metadata(body: bytes) -> dict[str, Any]:
    meta: dict[str, Any] = {"body_bytes": len(body)}
    if not body:
        return meta
    try:
        payload = json.loads(body)
    except Exception:
        meta["json"] = False
        return meta
    if not isinstance(payload, dict):
        meta["json"] = True
        meta["json_type"] = type(payload).__name__
        return meta

    messages = payload.get("messages")
    tools = payload.get("tools")
    roles: Counter[str] = Counter()
    message_chars = 0
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            roles[str(message.get("role") or "unknown")] += 1
            message_chars += _content_chars(message.get("content"))

    tool_schema_bytes = 0
    if isinstance(tools, list):
        try:
            tool_schema_bytes = len(
                json.dumps(tools, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
        except Exception:
            tool_schema_bytes = 0

    meta.update(
        {
            "json": True,
            "model": payload.get("model"),
            "stream": payload.get("stream"),
            "max_tokens": payload.get("max_tokens"),
            "reasoning_effort": payload.get("reasoning_effort"),
            "message_count": len(messages) if isinstance(messages, list) else 0,
            "message_chars": message_chars,
            "message_roles": dict(sorted(roles.items())),
            "tool_count": len(tools) if isinstance(tools, list) else 0,
            "tool_schema_bytes": tool_schema_bytes,
            "has_chat_template_kwargs": "chat_template_kwargs" in payload,
        }
    )
    return meta


class TraceState:
    def __init__(self, log_path: Path, upstream_host: str, upstream_port: int) -> None:
        self.log_path = log_path
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self._lock = threading.Lock()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, record: dict[str, Any]) -> None:
        row = {"ts_unix": time.time(), **record}
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(encoded + "\n")
                handle.flush()


class TraceHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "RC7OllamaTrace/1.0"

    @property
    def state(self) -> TraceState:
        return self.server.trace_state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/__trace_health":
            body = b'{"status":"ok"}\n'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
            return
        self._proxy()

    def do_POST(self) -> None:
        self._proxy()

    def do_HEAD(self) -> None:
        self._proxy()

    def _proxy(self) -> None:
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        length_header = self.headers.get("Content-Length")
        try:
            body_length = int(length_header) if length_header else 0
        except ValueError:
            body_length = 0
        body = self.rfile.read(body_length) if body_length > 0 else b""

        self.state.emit(
            {
                "event": "request_received",
                "request_id": request_id,
                "method": self.command,
                "path": self.path,
                **_request_metadata(body),
            }
        )

        upstream_headers: dict[str, str] = {}
        for name, value in self.headers.items():
            lower = name.lower()
            if lower in _HOP_BY_HOP or lower in {"host", "content-length"}:
                continue
            upstream_headers[name] = value
        if body:
            upstream_headers["Content-Length"] = str(len(body))

        conn = http.client.HTTPConnection(
            self.state.upstream_host,
            self.state.upstream_port,
            timeout=600,
        )
        response_bytes = 0
        first_byte_ms: int | None = None
        try:
            conn.request(self.command, self.path, body=body or None, headers=upstream_headers)
            response = conn.getresponse()
            headers_ms = int((time.monotonic() - started) * 1000)
            self.state.emit(
                {
                    "event": "response_headers",
                    "request_id": request_id,
                    "status": response.status,
                    "headers_ms": headers_ms,
                    "content_type": response.getheader("Content-Type"),
                    "upstream_content_length": response.getheader("Content-Length"),
                }
            )

            self.send_response(response.status, response.reason)
            for name, value in response.getheaders():
                lower = name.lower()
                if lower in _HOP_BY_HOP or lower == "content-length":
                    continue
                self.send_header(name, value)
            self.send_header("Connection", "close")
            self.end_headers()

            if self.command != "HEAD":
                while True:
                    chunk = response.read1(8192)
                    if not chunk:
                        break
                    if first_byte_ms is None:
                        first_byte_ms = int((time.monotonic() - started) * 1000)
                        self.state.emit(
                            {
                                "event": "response_first_byte",
                                "request_id": request_id,
                                "first_byte_ms": first_byte_ms,
                            }
                        )
                    response_bytes += len(chunk)
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        self.state.emit(
                            {
                                "event": "downstream_closed",
                                "request_id": request_id,
                                "response_bytes": response_bytes,
                                "elapsed_ms": int((time.monotonic() - started) * 1000),
                            }
                        )
                        return

            self.state.emit(
                {
                    "event": "response_complete",
                    "request_id": request_id,
                    "status": response.status,
                    "response_bytes": response_bytes,
                    "first_byte_ms": first_byte_ms,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                }
            )
        except Exception as exc:
            self.state.emit(
                {
                    "event": "proxy_error",
                    "request_id": request_id,
                    "error_type": type(exc).__name__,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                }
            )
            try:
                self.send_error(502, "upstream proxy failure")
            except Exception:
                pass
        finally:
            self.close_connection = True
            conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=11435)
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--upstream-port", type=int, default=11434)
    parser.add_argument("--log", required=True)
    args = parser.parse_args()

    state = TraceState(Path(args.log), args.upstream_host, args.upstream_port)
    server = ThreadingHTTPServer((args.listen_host, args.listen_port), TraceHandler)
    server.trace_state = state  # type: ignore[attr-defined]
    state.emit(
        {
            "event": "proxy_started",
            "listen_host": args.listen_host,
            "listen_port": args.listen_port,
            "upstream_host": args.upstream_host,
            "upstream_port": args.upstream_port,
        }
    )
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
