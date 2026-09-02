"""Process-only OpenCode 1.18.3 lifecycle boundary.

This module intentionally has zero dependency on the historical PFC AI-test
runtime. It owns only executable/version admission, web process launch, health,
state and stop. Mission/Plan/Task/Evidence truth is never read or written here.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

EXPECTED_OPENCODE_VERSION = "1.18.3"
VERSION_RE = re.compile(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)")


def _workspace() -> Path:
    raw = os.environ.get("AITEST_WORKSPACE_ROOT")
    if not raw:
        raise RuntimeError("AITEST_WORKSPACE_ROOT_REQUIRED")
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError(f"AITEST_WORKSPACE_ROOT_INVALID: {root}")
    return root


def _state_root() -> Path:
    raw = os.environ.get("PFC_LOCAL_STATE_ROOT")
    if not raw:
        raise RuntimeError("PFC_LOCAL_STATE_ROOT_REQUIRED")
    root = Path(raw).expanduser().resolve()
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    return root


def _state_path() -> Path:
    return _state_root() / "state" / "opencode-web-runtime.json"


def _log_path() -> Path:
    return _state_root() / "logs" / "opencode-web.log"


def _read_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_state(value: dict[str, Any]) -> None:
    path = _state_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _pid_running(pid: Any) -> bool:
    """Check liveness without ever signaling/killing the Windows process.

    `os.kill(pid, 0)` is a normal POSIX probe, but it is not used on Windows:
    Windows `os.kill` is backed by process signaling/termination semantics.
    Querying the package-owned PID through Win32 is read-only and therefore
    safe for STATUS/START idempotency checks.
    """
    try:
        number = int(pid)
    except (TypeError, ValueError):
        return False
    if number <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(number, 0)
            return True
        except OSError:
            return False

    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, number)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return int(code.value) == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError):
        return False


def _probe(url: str, timeout: float = 2.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/global/health", timeout=timeout) as response:
            raw = response.read(4096)
            text = raw.decode("utf-8", errors="replace")
            payload: Any = None
            if text.strip():
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = text
            return {"status": "PASS", "http_status": int(response.status), "payload": payload}
    except urllib.error.HTTPError as exc:
        # The web process is reachable even if auth policy rejects this route.
        if exc.code in {401, 403}:
            return {"status": "PASS", "http_status": int(exc.code), "auth_required": True}
        return {"status": "FAIL", "http_status": int(exc.code), "error": str(exc)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _bash_path() -> str:
    bash = shutil.which("bash")
    if not bash:
        raise RuntimeError("GIT_BASH_SHELL_NOT_FOUND")
    return str(bash)


def _git_bash_argv(args: list[str]) -> list[str]:
    # `opencode` itself is deliberately not resolved to an absolute .cmd/.ps1
    # path. The bank-proven authority is the command as resolved by the current
    # Git Bash environment, and version probe + Web launch use that same path.
    command = " ".join(["opencode", *(shlex.quote(str(item)) for item in args)])
    return [_bash_path(), "-lc", command]


def version() -> dict[str, Any]:
    workspace = str(_workspace())
    command_v = subprocess.run(
        [_bash_path(), "-lc", "command -v opencode"],
        cwd=workspace, capture_output=True, text=True, timeout=15, check=False,
    )
    proc = subprocess.run(
        _git_bash_argv(["--version"]),
        cwd=workspace, capture_output=True, text=True, timeout=15, check=False,
    )
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    match = VERSION_RE.search(text)
    actual = match.group(1) if match else None
    ok = proc.returncode == 0 and actual == EXPECTED_OPENCODE_VERSION
    return {
        "status": "PASS" if ok else "FAIL",
        "command": "opencode",
        "invocation_mode": "GIT_BASH_SHELL_RESOLVED",
        "command_v_evidence": (command_v.stdout or "").strip(),
        "command_v_exit_code": command_v.returncode,
        "expected_version": EXPECTED_OPENCODE_VERSION,
        "actual_version": actual,
        "exit_code": proc.returncode,
    }

def start() -> dict[str, Any]:
    existing = _read_state()
    endpoint = str(existing.get("endpoint") or "")
    if _pid_running(existing.get("pid")) and endpoint and _probe(endpoint).get("status") == "PASS":
        return {"status": "PASS", "lifecycle": "ALREADY_RUNNING", **existing, "health": _probe(endpoint)}

    admitted = version()
    if admitted["status"] != "PASS":
        return {"status": "FAIL", "lifecycle": "VERSION_REJECTED", "version": admitted}

    port = _free_port()
    endpoint = f"http://127.0.0.1:{port}"
    path = admitted["command"]
    argv = _git_bash_argv(["web", "--hostname", "127.0.0.1", "--port", str(port)])
    log_path = _log_path()
    log = log_path.open("ab", buffering=0)
    child_env = dict(os.environ)
    # The OpenCode instance uses a dynamic package-owned port. Every Agent/tool
    # spawned inside that instance must address this exact server rather than
    # silently falling back to the historical 4096 default.
    child_env["AITEST_OPENCODE_ENDPOINT"] = endpoint
    child_env["AITEST_WORKSPACE_ROOT"] = str(_workspace())
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(
            argv,
            cwd=str(_workspace()),
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    finally:
        # Child owns its duplicated/inherited output handle after Popen.
        log.close()
    state = {
        "pid": int(process.pid),
        "endpoint": endpoint,
        "workspace": str(_workspace()),
        "command": path,
        "invocation_mode": "GIT_BASH_SHELL_RESOLVED",
        "shell_executable": argv[0],
        "version": EXPECTED_OPENCODE_VERSION,
        "log_path": str(log_path),
    }
    _write_state(state)
    deadline = time.time() + 20
    last: dict[str, Any] = {"status": "FAIL", "error": "STARTUP_TIMEOUT"}
    while time.time() < deadline:
        if process.poll() is not None:
            return {"status": "FAIL", "lifecycle": "PROCESS_EXITED", **state, "exit_code": process.returncode}
        last = _probe(endpoint)
        if last.get("status") == "PASS":
            return {"status": "PASS", "lifecycle": "STARTED", **state, "health": last}
        time.sleep(0.4)
    return {"status": "FAIL", "lifecycle": "HEALTH_TIMEOUT", **state, "health": last}


def status() -> dict[str, Any]:
    state = _read_state()
    if not state:
        return {"status": "REPAIR", "lifecycle": "NOT_STARTED"}
    running = _pid_running(state.get("pid"))
    health = _probe(str(state.get("endpoint") or "")) if state.get("endpoint") else {"status": "FAIL"}
    ok = running and health.get("status") == "PASS"
    return {"status": "PASS" if ok else "REPAIR", "lifecycle": "RUNNING" if ok else "NOT_HEALTHY", **state, "pid_running": running, "health": health}


def stop() -> dict[str, Any]:
    state = _read_state()
    pid = state.get("pid")
    if not _pid_running(pid):
        endpoint = str(state.get("endpoint") or "")
        health = _probe(endpoint) if endpoint else {"status": "FAIL"}
        if health.get("status") == "PASS":
            return {
                "status": "REPAIR", "lifecycle": "ORPHAN_ENDPOINT_REACHABLE", **state,
                "pid_running": False, "health": health,
            }
        return {"status": "PASS", "lifecycle": "ALREADY_STOPPED", **state}
    number = int(pid)
    try:
        if os.name == "nt":
            # The process was launched with CREATE_NEW_PROCESS_GROUP. Ask that
            # package-owned group to stop gracefully first. This is bounded to
            # the known PID/group and never uses broad image-name termination.
            try:
                os.kill(number, signal.CTRL_BREAK_EVENT)
            except (AttributeError, OSError):
                pass
            deadline = time.time() + 5
            while time.time() < deadline and _pid_running(number):
                time.sleep(0.1)
            if _pid_running(number):
                # Last resort is the single recorded wrapper PID only. `/T` is
                # intentionally forbidden by the frozen process-lifecycle
                # contract; no unrelated process tree may be killed.
                killed = subprocess.run(
                    ["taskkill", "/PID", str(number), "/F"],
                    capture_output=True, text=True, timeout=15, check=False,
                )
                if killed.returncode != 0 and _pid_running(number):
                    return {
                        "status": "FAIL", "lifecycle": "STOP_FAILED", **state,
                        "error": (killed.stderr or killed.stdout or "taskkill failed").strip()[:2000],
                    }
        else:
            os.kill(number, signal.SIGTERM)
            deadline = time.time() + 5
            while time.time() < deadline and _pid_running(number):
                time.sleep(0.1)
            if _pid_running(number):
                os.kill(number, signal.SIGKILL)
    except OSError as exc:
        return {"status": "FAIL", "lifecycle": "STOP_FAILED", **state, "error": str(exc)}
    endpoint = str(state.get("endpoint") or "")
    health = _probe(endpoint, timeout=0.8) if endpoint else {"status": "FAIL"}
    if health.get("status") == "PASS":
        return {
            "status": "REPAIR", "lifecycle": "STOP_ENDPOINT_STILL_REACHABLE", **state,
            "pid_running": _pid_running(number), "health": health,
        }
    return {"status": "PASS", "lifecycle": "STOPPED", **state, "health": health}


__all__ = ["EXPECTED_OPENCODE_VERSION", "start", "status", "stop", "version"]
