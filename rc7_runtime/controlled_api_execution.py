"""Parent-owned API runtime proof for RC7 L3 formal execution.

A generated/reused test script is not trusted to prove that an HTTP call really
happened.  The child process receives only a loopback RC7 proxy URL.  The proxy
is owned by the parent runtime, is bound to one configured target base URL, does
the real HTTP request itself, and keeps receipts in parent memory.  Only those
receipts are converted into ``api-runtime`` tool calls and an actual result.

Any ``api-runtime`` tool_call or actual_result written by the child into the
legacy runner manifest is deliberately ignored by this adapter.  Therefore a
script cannot obtain L3 PASS by writing JSON that claims a request happened.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid

from rc6_runtime.automation import RunnerAdapter, RunnerExecutionResult


class ControlledApiRuntimeError(RuntimeError):
    pass


_MAX_REQUEST_BYTES = 1024 * 1024
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


@dataclass(frozen=True)
class ApiRuntimeReceipt:
    receipt_id: str
    method: str
    target_url: str
    request_body_sha256: str
    status_code: int
    response_content_type: str
    response_body_sha256: str
    response_json: Optional[Any]
    response_text: str
    capture_as: Optional[str]
    elapsed_ms: int

    def actual_result(self) -> Dict[str, Any]:
        if isinstance(self.response_json, dict):
            value = deepcopy(self.response_json)
            value["_http"] = {
                "status_code": self.status_code,
                "target_url": self.target_url,
                "receipt_id": self.receipt_id,
            }
            return value
        return {
            "body": deepcopy(self.response_json) if self.response_json is not None else self.response_text,
            "_http": {
                "status_code": self.status_code,
                "target_url": self.target_url,
                "receipt_id": self.receipt_id,
            },
        }


class ControlledApiRuntimeProxy:
    """Loopback-only, exact-target HTTP forwarder with parent-memory receipts."""

    def __init__(self, *, target_base_url: str, timeout_seconds: int = 30) -> None:
        parsed = urlsplit(str(target_base_url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ControlledApiRuntimeError("API_TARGET_BASE_URL_INVALID")
        if parsed.username or parsed.password or parsed.fragment:
            raise ControlledApiRuntimeError("API_TARGET_BASE_URL_UNSAFE")
        if parsed.query:
            raise ControlledApiRuntimeError("API_TARGET_BASE_URL_QUERY_FORBIDDEN")
        self._base_scheme = parsed.scheme
        self._base_netloc = parsed.netloc
        self._base_path = parsed.path.rstrip("/")
        self.timeout_seconds = int(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ControlledApiRuntimeError("API_RUNTIME_TIMEOUT_INVALID")
        self._receipts: List[ApiRuntimeReceipt] = []
        self._lock = threading.Lock()
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def receipts(self) -> Tuple[ApiRuntimeReceipt, ...]:
        with self._lock:
            return tuple(self._receipts)

    @property
    def proxy_url(self) -> str:
        if self._server is None:
            raise ControlledApiRuntimeError("API_RUNTIME_PROXY_NOT_STARTED")
        host, port = self._server.server_address[:2]
        return "http://%s:%s/invoke" % (host, port)

    def __enter__(self) -> "ControlledApiRuntimeProxy":
        runtime = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_POST(self):  # noqa: N802
                if self.path != "/invoke":
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                except ValueError:
                    self.send_error(400)
                    return
                if length <= 0 or length > _MAX_REQUEST_BYTES:
                    self.send_error(413 if length > _MAX_REQUEST_BYTES else 400)
                    return
                try:
                    request_body = self.rfile.read(length)
                    command = json.loads(request_body.decode("utf-8"))
                    receipt = runtime._invoke(command)
                    payload = {
                        "receipt_id": receipt.receipt_id,
                        "status_code": receipt.status_code,
                        "response": receipt.response_json if receipt.response_json is not None else receipt.response_text,
                    }
                    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except ControlledApiRuntimeError as exc:
                    raw = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except Exception as exc:  # fail the child call, but never forge a receipt
                    raw = json.dumps({"error": "%s:%s" % (type(exc).__name__, exc)}, ensure_ascii=False).encode("utf-8")
                    self.send_response(502)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="rc7-api-runtime-proxy", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None

    def _target_url(self, path: object) -> str:
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ControlledApiRuntimeError("API_RUNTIME_RELATIVE_PATH_REQUIRED")
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            raise ControlledApiRuntimeError("API_RUNTIME_PATH_ESCAPES_TARGET")
        target_path = self._base_path + parsed.path
        return urlunsplit((self._base_scheme, self._base_netloc, target_path, parsed.query, ""))

    def _invoke(self, command: object) -> ApiRuntimeReceipt:
        if not isinstance(command, dict):
            raise ControlledApiRuntimeError("API_RUNTIME_COMMAND_OBJECT_REQUIRED")
        method = str(command.get("method") or "GET").upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}:
            raise ControlledApiRuntimeError("API_RUNTIME_METHOD_FORBIDDEN")
        target_url = self._target_url(command.get("path"))
        raw_headers = command.get("headers") or {}
        if not isinstance(raw_headers, dict):
            raise ControlledApiRuntimeError("API_RUNTIME_HEADERS_OBJECT_REQUIRED")
        headers: Dict[str, str] = {}
        for key, value in raw_headers.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ControlledApiRuntimeError("API_RUNTIME_HEADER_STRING_REQUIRED")
            if key.lower() in _HOP_BY_HOP_HEADERS:
                continue
            headers[key] = value

        body = command.get("body")
        if body is None:
            encoded_body = None
        elif isinstance(body, (dict, list)):
            encoded_body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers.setdefault("Content-Type", "application/json; charset=utf-8")
        elif isinstance(body, str):
            encoded_body = body.encode("utf-8")
        else:
            raise ControlledApiRuntimeError("API_RUNTIME_BODY_INVALID")
        if encoded_body is not None and len(encoded_body) > _MAX_REQUEST_BYTES:
            raise ControlledApiRuntimeError("API_RUNTIME_BODY_TOO_LARGE")

        capture_as = command.get("capture_as")
        if capture_as is not None and capture_as != "actual_result":
            raise ControlledApiRuntimeError("API_RUNTIME_CAPTURE_AS_INVALID")
        request = Request(target_url, data=encoded_body, headers=headers, method=method)
        opener = build_opener(_NoRedirect())
        started = time.monotonic()
        status_code = 0
        response_headers: Mapping[str, str] = {}
        response_bytes = b""
        try:
            response = opener.open(request, timeout=self.timeout_seconds)
            try:
                status_code = int(response.getcode())
                response_headers = dict(response.headers.items())
                response_bytes = response.read(_MAX_RESPONSE_BYTES + 1)
            finally:
                response.close()
        except HTTPError as exc:
            status_code = int(exc.code)
            response_headers = dict(exc.headers.items()) if exc.headers else {}
            response_bytes = exc.read(_MAX_RESPONSE_BYTES + 1)
        if len(response_bytes) > _MAX_RESPONSE_BYTES:
            raise ControlledApiRuntimeError("API_RUNTIME_RESPONSE_TOO_LARGE")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        content_type = str(response_headers.get("Content-Type") or "")
        try:
            response_text = response_bytes.decode("utf-8")
        except UnicodeDecodeError:
            response_text = response_bytes.decode("utf-8", errors="replace")
        response_json = None
        try:
            response_json = json.loads(response_text) if response_text else None
        except json.JSONDecodeError:
            response_json = None
        receipt = ApiRuntimeReceipt(
            receipt_id="APIREC-" + uuid.uuid4().hex,
            method=method,
            target_url=target_url,
            request_body_sha256=hashlib.sha256(encoded_body or b"").hexdigest(),
            status_code=status_code,
            response_content_type=content_type,
            response_body_sha256=hashlib.sha256(response_bytes).hexdigest(),
            response_json=deepcopy(response_json),
            response_text=response_text,
            capture_as=capture_as,
            elapsed_ms=elapsed_ms,
        )
        with self._lock:
            self._receipts.append(receipt)
        return receipt


class ControlledApiRunnerAdapter:
    """Runner facade that trusts only parent proxy receipts for ``api-runtime``."""

    def __init__(
        self,
        *,
        delegate: RunnerAdapter,
        target_base_url: str,
        evidence_root: str,
        attempt_id: str,
        proxy_timeout_seconds: int = 30,
    ) -> None:
        self.delegate = delegate
        self.runner_type = delegate.runner_type
        self.target_base_url = target_base_url
        self.evidence_root = Path(evidence_root).resolve()
        self.attempt_id = attempt_id
        self.proxy_timeout_seconds = int(proxy_timeout_seconds)

    def execute(self, *, spec, script, validation, cwd: str, env: Optional[Mapping[str, str]] = None) -> RunnerExecutionResult:
        with ControlledApiRuntimeProxy(
            target_base_url=self.target_base_url,
            timeout_seconds=self.proxy_timeout_seconds,
        ) as proxy:
            child_env = dict(env or {})
            child_env["RC7_API_RUNTIME_PROXY_URL"] = proxy.proxy_url
            child_env["RC7_API_RUNTIME_ATTEMPT_ID"] = self.attempt_id
            raw = self.delegate.execute(
                spec=spec,
                script=script,
                validation=validation,
                cwd=cwd,
                env=child_env,
            )
            receipts = proxy.receipts

        receipt_dir = self.evidence_root / "api-runtime" / self.attempt_id
        receipt_dir.mkdir(parents=True, exist_ok=True)
        tool_calls = [deepcopy(call) for call in raw.tool_calls if call.get("tool_id") != "api-runtime"]
        receipt_refs: List[str] = []
        captured = []
        for receipt in receipts:
            path = receipt_dir / (receipt.receipt_id + ".json")
            payload = json.dumps(asdict(receipt), ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
            path.write_text(payload, encoding="utf-8")
            evidence_ref = "file://" + str(path)
            receipt_refs.append(evidence_ref)
            tool_calls.append({
                "tool_id": "api-runtime",
                "call_ref": "api-runtime://" + receipt.receipt_id,
                "evidence_ref": evidence_ref,
            })
            if receipt.capture_as == "actual_result":
                captured.append(receipt.actual_result())
        actual = captured[0] if len(captured) == 1 else {}
        call_refs = tuple(dict.fromkeys(list(raw.tool_call_refs) + [call["call_ref"] for call in tool_calls]))
        evidence = tuple(dict.fromkeys(list(raw.evidence_refs) + receipt_refs + [call["evidence_ref"] for call in tool_calls]))
        return RunnerExecutionResult(
            runner_type=raw.runner_type,
            test_symbol=raw.test_symbol,
            exit_code=raw.exit_code,
            status=raw.status,
            actual_result=actual,
            stdout_ref=raw.stdout_ref,
            stderr_ref=raw.stderr_ref,
            tool_calls=tuple(tool_calls),
            tool_call_refs=call_refs,
            evidence_refs=evidence,
            duration_ms=raw.duration_ms,
        )
