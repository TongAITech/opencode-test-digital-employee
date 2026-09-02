"""Package-owned lifecycle for the G2.1 autonomous Control Loop process.

Operational PID/log files are not business truth. Mission/Task/Session truth is
owned only by the R1 Event Stream consumed by aitest_runtime.control_loop.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    return _state_root() / "state" / "aitest-control-loop.json"


def _log_path() -> Path:
    return _state_root() / "logs" / "aitest-control-loop.log"


def _heartbeat_path() -> Path:
    return _state_root() / "state" / "aitest-control-loop-heartbeat.json"


def _read_heartbeat() -> dict[str, Any]:
    path = _heartbeat_path()
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _heartbeat_owned(state: dict[str, Any], heartbeat: dict[str, Any]) -> bool:
    """Return True only when a fresh heartbeat proves PID ownership.

    PID reuse must never make the package kill or adopt an unrelated process.
    Health status is deliberately separate: even a fresh TICK_FAIL heartbeat
    still proves ownership and can be stopped safely.
    """
    if not heartbeat:
        return False
    if int(heartbeat.get("pid") or 0) != int(state.get("pid") or -1):
        return False
    written = heartbeat.get("written_at")
    if not isinstance(written, str):
        return False
    try:
        then = datetime.fromisoformat(written.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - then).total_seconds()
    except (ValueError, TypeError):
        return False
    try:
        interval = float(state.get("interval_seconds") or 10)
    except (TypeError, ValueError):
        interval = 10.0
    return age <= max(30.0, interval * 3.0)


def _heartbeat_healthy(state: dict[str, Any], heartbeat: dict[str, Any]) -> bool:
    return _heartbeat_owned(state, heartbeat) and heartbeat.get("status") in {"PASS", "STARTED"}


def _runtime_admission(heartbeat: dict[str, Any]) -> str:
    tick = heartbeat.get("tick")
    if isinstance(tick, dict):
        value = tick.get("runtime_admission")
        if isinstance(value, str) and value:
            return value
        if tick.get("status") == "PASS":
            return "READY"
    return "UNKNOWN"


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
    try:
        number = int(pid)
    except (TypeError, ValueError):
        return False
    if number <= 0:
        return False
    if os.name != "nt":
        # Reap a child if this process owns it; otherwise detect Linux zombies
        # before falling back to the non-destructive signal-0 probe.
        try:
            waited, _status = os.waitpid(number, os.WNOHANG)
            if waited == number:
                return False
        except ChildProcessError:
            pass
        proc_stat = Path(f"/proc/{number}/stat")
        if proc_stat.is_file():
            try:
                fields = proc_stat.read_text(encoding="utf-8", errors="replace").split()
                if len(fields) > 2 and fields[2] == "Z":
                    return False
            except OSError:
                pass
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


def start(endpoint: str) -> dict[str, Any]:
    endpoint = str(endpoint or "").rstrip("/")
    if not endpoint:
        return {"status": "FAIL", "lifecycle": "ENDPOINT_REQUIRED"}
    existing = _read_state()
    if _pid_running(existing.get("pid")):
        heartbeat = _read_heartbeat()
        if not _heartbeat_owned(existing, heartbeat):
            # A recycled/stale PID is not sufficient authority to kill or adopt
            # a process. Fail closed rather than overwrite state and orphan it.
            return {"status": "FAIL", "lifecycle": "RUNNING_PROCESS_OWNERSHIP_UNVERIFIED", **existing, "heartbeat": heartbeat}
        if existing.get("endpoint") == endpoint and _heartbeat_healthy(existing, heartbeat):
            return {"status": "PASS", "lifecycle": "ALREADY_RUNNING", **existing, "heartbeat": heartbeat}
        stopped = stop()
        if stopped.get("status") != "PASS":
            return {"status": "FAIL", "lifecycle": "EXISTING_CONTROL_LOOP_STOP_FAILED", "existing": existing, "stop": stopped}
    workspace = _workspace()
    runtime_root = workspace / "ai-test" / "runtime"
    if not runtime_root.is_dir():
        return {"status": "FAIL", "lifecycle": "RUNTIME_ROOT_MISSING", "runtime_root": str(runtime_root)}
    log_path = _log_path()
    log = log_path.open("ab", buffering=0)
    env = dict(os.environ)
    env["AITEST_WORKSPACE_ROOT"] = str(workspace)
    env["AITEST_OPENCODE_ENDPOINT"] = endpoint
    env["AITEST_CONTROL_LOOP_HEARTBEAT_PATH"] = str(_heartbeat_path())
    env["PYTHONPATH"] = os.pathsep.join([str(runtime_root), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    interval = env.get("AITEST_CONTROL_LOOP_INTERVAL_SECONDS", "10")
    argv = [sys.executable, "-m", "aitest_runtime.control_loop", "--workspace-root", str(workspace), "--interval", interval]
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    try:
        child = subprocess.Popen(
            argv, cwd=str(workspace), env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, creationflags=creationflags,
        )
    finally:
        log.close()
    state = {
        "pid": int(child.pid), "endpoint": endpoint, "workspace": str(workspace),
        "python": sys.executable, "interval_seconds": interval, "log_path": str(log_path),
    }
    _write_state(state)
    deadline = time.time() + 12
    heartbeat: dict[str, Any] = {}
    while time.time() < deadline:
        if child.poll() is not None:
            return {"status": "FAIL", "lifecycle": "PROCESS_EXITED", **state, "exit_code": child.returncode, "heartbeat": _read_heartbeat()}
        heartbeat = _read_heartbeat()
        if heartbeat.get("status") == "PASS" and int(heartbeat.get("pid") or 0) == int(child.pid):
            return {"status": "PASS", "lifecycle": "STARTED", **state, "heartbeat": heartbeat,
                    "runtime_admission": _runtime_admission(heartbeat)}
        if heartbeat.get("status") in {"TICK_FAIL", "FAIL"} and int(heartbeat.get("pid") or 0) == int(child.pid):
            stop()
            return {"status": "FAIL", "lifecycle": "FIRST_TICK_FAILED", **state, "heartbeat": heartbeat}
        time.sleep(0.1)
    stop()
    return {"status": "FAIL", "lifecycle": "HEARTBEAT_TIMEOUT", **state, "heartbeat": heartbeat}


def status() -> dict[str, Any]:
    state = _read_state()
    if not state:
        return {"status": "REPAIR", "lifecycle": "NOT_STARTED"}
    running = _pid_running(state.get("pid"))
    heartbeat = _read_heartbeat()
    healthy = running and _heartbeat_healthy(state, heartbeat)
    return {"status": "PASS" if healthy else "REPAIR", "lifecycle": "RUNNING" if healthy else "NOT_HEALTHY",
            **state, "pid_running": running, "heartbeat": heartbeat, "runtime_admission": _runtime_admission(heartbeat)}


def stop() -> dict[str, Any]:
    state = _read_state()
    pid = state.get("pid")
    if not _pid_running(pid):
        return {"status": "PASS", "lifecycle": "ALREADY_STOPPED", **state}
    heartbeat = _read_heartbeat()
    if not _heartbeat_owned(state, heartbeat):
        return {"status": "FAIL", "lifecycle": "STOP_OWNERSHIP_UNVERIFIED", **state, "heartbeat": heartbeat}
    number = int(pid)
    try:
        if os.name == "nt":
            try:
                os.kill(number, signal.CTRL_BREAK_EVENT)
            except (AttributeError, OSError):
                pass
            deadline = time.time() + 4
            while time.time() < deadline and _pid_running(number):
                time.sleep(0.1)
            if _pid_running(number):
                killed = subprocess.run(["taskkill", "/PID", str(number), "/F"], capture_output=True, text=True, timeout=15, check=False)
                if killed.returncode != 0 and _pid_running(number):
                    return {"status": "FAIL", "lifecycle": "STOP_FAILED", **state,
                            "error": (killed.stderr or killed.stdout or "taskkill failed").strip()[:2000]}
        else:
            os.kill(number, signal.SIGTERM)
            deadline = time.time() + 4
            while time.time() < deadline and _pid_running(number):
                time.sleep(0.1)
            if _pid_running(number):
                os.kill(number, signal.SIGKILL)
            deadline = time.time() + 2
            while time.time() < deadline and _pid_running(number):
                time.sleep(0.05)
    except OSError as exc:
        return {"status": "FAIL", "lifecycle": "STOP_FAILED", **state, "error": str(exc)}
    running = _pid_running(number)
    return {"status": "PASS" if not running else "FAIL", "lifecycle": "STOPPED" if not running else "STOP_FAILED", **state, "pid_running": running, "heartbeat": _read_heartbeat()}


__all__ = ["start", "status", "stop"]
