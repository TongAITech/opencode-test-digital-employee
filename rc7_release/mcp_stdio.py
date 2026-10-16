from __future__ import annotations

import json
import locale
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence


class McpStdioError(RuntimeError):
    pass


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", locale.getpreferredencoding(False), "gb18030"):
        if not encoding:
            continue
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode("utf-8", errors="replace")


class JsonLineMcpClient:
    """Small JSON-RPC-over-stdio MCP client that is Windows pipe safe.

    Python's select() cannot be used reliably with ordinary Windows anonymous
    pipes.  Field validation hit WinError 10093 while talking to CodeGraph.
    Dedicated reader threads + queues work on Windows and POSIX and keep stderr
    drained so a verbose server cannot deadlock the client.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Optional[Mapping[str, str]] = None,
        timeout_seconds: int = 30,
    ) -> None:
        if not command:
            raise McpStdioError("MCP_COMMAND_REQUIRED")
        if timeout_seconds < 1 or timeout_seconds > 300:
            raise McpStdioError("MCP_TIMEOUT_INVALID")
        self.command = [str(item) for item in command]
        self.cwd = Path(cwd).resolve()
        self.timeout_seconds = int(timeout_seconds)
        self._responses: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._stderr_lines: "queue.Queue[str]" = queue.Queue()
        self._next_id = 1
        self._closed = False
        self.proc = subprocess.Popen(
            self.command,
            cwd=str(self.cwd),
            env=dict(env) if env is not None else None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            bufsize=0,
        )
        if self.proc.stdin is None or self.proc.stdout is None or self.proc.stderr is None:
            self.close()
            raise McpStdioError("MCP_STDIO_PIPE_UNAVAILABLE")
        self._stdout_thread = threading.Thread(target=self._stdout_reader, name="mcp-stdout-reader", daemon=True)
        self._stderr_thread = threading.Thread(target=self._stderr_reader, name="mcp-stderr-reader", daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _stdout_reader(self) -> None:
        assert self.proc.stdout is not None
        while True:
            raw = self.proc.stdout.readline()
            if not raw:
                return
            text = _decode(raw).strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                # MCP servers may emit startup diagnostics on stdout.  Preserve
                # them as diagnostics but never misparse them as responses.
                self._stderr_lines.put("STDOUT_NON_JSON:" + text[:2000])
                continue
            if isinstance(message, dict):
                self._responses.put(message)

    def _stderr_reader(self) -> None:
        assert self.proc.stderr is not None
        while True:
            raw = self.proc.stderr.readline()
            if not raw:
                return
            text = _decode(raw).rstrip()
            if text:
                self._stderr_lines.put(text[:4000])

    def _diagnostics(self, limit: int = 20) -> str:
        rows: List[str] = []
        while len(rows) < limit:
            try:
                rows.append(self._stderr_lines.get_nowait())
            except queue.Empty:
                break
        return "\n".join(rows)[-8000:]

    def _write(self, message: Dict[str, Any]) -> None:
        if self._closed or self.proc.poll() is not None:
            raise McpStdioError("MCP_PROCESS_NOT_RUNNING:%s" % self._diagnostics())
        assert self.proc.stdin is not None
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        try:
            self.proc.stdin.write(payload)
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise McpStdioError("MCP_STDIN_WRITE_FAILED:%s" % self._diagnostics()) from exc

    def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        msg_id = self._next_id
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout_seconds
        deferred: List[Dict[str, Any]] = []
        try:
            while time.monotonic() < deadline:
                if self.proc.poll() is not None and self._responses.empty():
                    raise McpStdioError(
                        "MCP_PROCESS_EXITED:%s:%s" % (self.proc.returncode, self._diagnostics())
                    )
                try:
                    message = self._responses.get(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
                except queue.Empty:
                    continue
                if message.get("id") != msg_id:
                    deferred.append(message)
                    continue
                if "error" in message:
                    raise McpStdioError("MCP_REMOTE_ERROR:%s" % json.dumps(message["error"], ensure_ascii=False))
                result = message.get("result")
                if not isinstance(result, dict):
                    raise McpStdioError("MCP_RESULT_OBJECT_REQUIRED")
                return result
            raise McpStdioError("MCP_REQUEST_TIMEOUT:%s:%s" % (method, self._diagnostics()))
        finally:
            for message in deferred:
                self._responses.put(message)

    def initialize(self) -> Dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pfc-aitest-rc7", "version": "7-field-hardening"},
            },
        )
        self.notify("notifications/initialized", {})
        return result

    def tools_list(self) -> List[Dict[str, Any]]:
        result = self.request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise McpStdioError("MCP_TOOLS_LIST_INVALID")
        return [dict(item) for item in tools if isinstance(item, dict)]

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not name:
            raise McpStdioError("MCP_TOOL_NAME_REQUIRED")
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)

    def __enter__(self) -> "JsonLineMcpClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
