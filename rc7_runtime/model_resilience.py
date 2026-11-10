"""RC7.1 model request governor and transient failure recovery.

This module is a bounded field-hardening overlay around the existing DSH Worker
launcher. It does not change testing authority or manufacture PASS. It adds:

* a file-backed sliding-window governor shared by all RC7 Python processes;
* deterministic classification of provider/network failures;
* bounded automatic retry before any uncertain side effect;
* R1 lifecycle events for admission, waiting, failure, retry and recovery;
* fail-closed handoff when tool side effects may already have happened.

The bank limit defaults to 100 requests / 600 seconds and is configurable via
PFC_RC71_MODEL_RATE_MAX / PFC_RC71_MODEL_RATE_WINDOW_SECONDS. All retry calls
consume the same shared budget.
"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from rc6_runtime import agent_runtime as _agent_runtime
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import AgentRuntimeError, WorkerAssignment


MODEL_RESILIENCE_EVENT_TYPES = (
    "MODEL_REQUEST_ADMITTED",
    "MODEL_RATE_LIMIT_WAIT",
    "MODEL_CALL_FAILED",
    "MODEL_RETRY_SCHEDULED",
    "MODEL_RETRY_STARTED",
    "MODEL_RECOVERED",
    "MODEL_RECOVERY_BLOCKED_SIDE_EFFECT",
    "MODEL_RETRY_EXHAUSTED",
)

_SAFE_TOOL_TOKENS = {
    "read",
    "list",
    "get",
    "query",
    "search",
    "grep",
    "status",
    "inspect",
    "find",
    "diff",
    "codegraph",
    "select",
    "explain",
    "describe",
    "head",
}

_MUTATING_TOOL_TOKENS = {
    "write",
    "delete",
    "update",
    "create",
    "execute",
    "run",
    "publish",
    "submit",
    "insert",
    "upsert",
    "patch",
    "put",
    "post",
    "remove",
    "move",
    "copy",
    "click",
    "type",
    "upload",
    "send",
    "commit",
    "merge",
    "deploy",
    "start",
    "stop",
    "restart",
}


@dataclass(frozen=True)
class RateReservation:
    admitted: bool
    wait_seconds: float
    request_count: int
    reset_at: float


@dataclass(frozen=True)
class ModelFailure:
    category: str
    retryable: bool
    detail: str


def _register_events() -> None:
    current = tuple(_agent_runtime.AGENT_RUNTIME_EVENT_TYPES)
    missing = tuple(name for name in MODEL_RESILIENCE_EVENT_TYPES if name not in current)
    if missing:
        _agent_runtime.AGENT_RUNTIME_EVENT_TYPES = current + missing
    for name in MODEL_RESILIENCE_EVENT_TYPES:
        _truth.EVENT_TYPES.setdefault(name, ("agent_runtime_event", "id"))


_register_events()


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


class PersistentSlidingWindowGovernor:
    """Cross-process request governor using a small locked JSON state file."""

    def __init__(
        self,
        state_root: Path,
        *,
        max_requests: int = 100,
        window_seconds: float = 600.0,
        now_fn=None,
        sleep_fn=None,
    ) -> None:
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(0.1, float(window_seconds))
        self.now_fn = now_fn or time.time
        self.sleep_fn = sleep_fn or time.sleep
        root = Path(state_root).expanduser().resolve() / "model-governor"
        if root.is_symlink():
            raise AgentRuntimeError("MODEL_RATE_GOVERNOR_STATE_UNVERIFIED")
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise AgentRuntimeError("MODEL_RATE_GOVERNOR_STATE_UNVERIFIED")
        self.state_path = root / "shared-window.json"
        self.lock_path = root / "shared-window.lock"
        self._lock_fd = None

    def reserve(self) -> RateReservation:
        self._lock()
        try:
            now = float(self.now_fn())
            state = self._load()
            # A damaged shared request ledger is NOT an empty rate window.
            # Missing/invalid historic requests must never permit new model IO.
            timestamps = [stamp for stamp in state["timestamps"]
                          if stamp > now - self.window_seconds]
            timestamps.sort()
            if len(timestamps) < self.max_requests:
                timestamps.append(now)
                self._save({"schema": "rc7.1-model-rate-window-v1", "timestamps": timestamps})
                reset_at = timestamps[0] + self.window_seconds if timestamps else now
                return RateReservation(True, 0.0, len(timestamps), reset_at)
            reset_at = timestamps[0] + self.window_seconds
            wait_seconds = max(0.01, reset_at - now + 0.05)
            self._save({"schema": "rc7.1-model-rate-window-v1", "timestamps": timestamps})
            return RateReservation(False, wait_seconds, len(timestamps), reset_at)
        finally:
            self._unlock()

    def _load(self) -> Dict[str, Any]:
        # Absence on first launch is distinct from a present but corrupt state.
        # In particular, an interrupted write, invalid JSON, wrong schema or
        # non-finite timestamp must fail closed across all RC7.2 processes.
        if (self.state_path.is_symlink()
                or self.state_path.parent.is_symlink()):
            raise AgentRuntimeError("MODEL_RATE_GOVERNOR_STATE_UNVERIFIED")
        if not self.state_path.exists():
            return {"timestamps": []}
        try:
            value = json.loads(
                self.state_path.read_text(encoding="utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
        except (OSError, UnicodeError, ValueError):
            raise AgentRuntimeError("MODEL_RATE_GOVERNOR_STATE_UNVERIFIED") from None
        if (not isinstance(value, dict)
                or value.get("schema") != "rc7.1-model-rate-window-v1"
                or not isinstance(value.get("timestamps"), list)):
            raise AgentRuntimeError("MODEL_RATE_GOVERNOR_STATE_UNVERIFIED")
        stamps = []
        for item in value["timestamps"]:
            if (type(item) not in (int, float) or not math.isfinite(item)
                    or item < 0):
                raise AgentRuntimeError("MODEL_RATE_GOVERNOR_STATE_UNVERIFIED")
            stamps.append(float(item))
        return {"timestamps": stamps}

    def _save(self, value: Dict[str, Any]) -> None:
        root = self.state_path.parent
        if (root.is_symlink() or self.state_path.is_symlink()
                or not root.is_dir()):
            raise AgentRuntimeError("MODEL_RATE_GOVERNOR_STATE_UNVERIFIED")
        temp = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", newline="\n",
                    prefix=".shared-window-", suffix=".tmp",
                    dir=str(root), delete=False) as output:
                temp = Path(output.name)
                output.write(json.dumps(
                    value, ensure_ascii=False, sort_keys=True) + "\n")
                output.flush()
                os.fsync(output.fileno())
            if self.state_path.is_symlink():
                raise AgentRuntimeError("MODEL_RATE_GOVERNOR_STATE_UNVERIFIED")
            os.replace(str(temp), str(self.state_path))
            if os.name != "nt":
                directory_fd = os.open(str(root), os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except OSError:
            raise AgentRuntimeError("MODEL_RATE_GOVERNOR_STATE_WRITE_FAILED") from None
        finally:
            if temp is not None and temp.exists():
                temp.unlink()

    def _lock(self) -> None:
        # Use an OS advisory lock instead of an O_EXCL lock-file lease. The
        # previous stale-file deletion could evict a live process after 30s,
        # and its later unlink could remove a successor's lock. A persistent
        # file plus kernel-managed ownership survives process death safely.
        if self._lock_fd is not None:
            raise AgentRuntimeError("MODEL_RATE_GOVERNOR_LOCK_REENTRY_FORBIDDEN")
        if self.lock_path.is_symlink() or self.lock_path.parent.is_symlink():
            raise AgentRuntimeError("MODEL_RATE_GOVERNOR_LOCK_PATH_UNVERIFIED")
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(str(self.lock_path), flags, 0o600)
        except OSError:
            raise AgentRuntimeError("MODEL_RATE_GOVERNOR_LOCK_PATH_UNVERIFIED") from None
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise AgentRuntimeError("MODEL_RATE_GOVERNOR_LOCK_PATH_UNVERIFIED")
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"0")
            os.fsync(fd)
        deadline = time.monotonic() + 10.0
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._lock_fd = fd
                return
            except OSError as exc:
                contended = (
                    exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK)
                    or getattr(exc, "winerror", None) in (33, 36)
                )
                if not contended:
                    os.close(fd)
                    raise AgentRuntimeError(
                        "MODEL_RATE_GOVERNOR_LOCK_UNAVAILABLE") from None
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise AgentRuntimeError("MODEL_RATE_GOVERNOR_LOCK_TIMEOUT")
                time.sleep(0.02)

    def _unlock(self) -> None:
        fd = self._lock_fd
        self._lock_fd = None
        if fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field")
        value[key] = item
    return value


def classify_failure(text: str) -> ModelFailure:
    raw = str(text or "")
    lowered = raw.lower()
    if (re.search(r"(?<![0-9])429(?![0-9])", lowered)
            or "rate limit" in lowered or "too many requests" in lowered
            or "频率" in raw):
        return ModelFailure("RATE_LIMIT", True, "provider throttle")
    if "sse stream ended without [done]" in lowered or "stream_closed" in lowered or "stream closed" in lowered:
        return ModelFailure("SSE_STREAM_CLOSED_BEFORE_DONE", True, "SSE ended before DONE")
    for code, phrases in (
            ("502", ("bad gateway", "gateway error")),
            ("503", ("service unavailable", "provider unavailable")),
            ("504", ("gateway timeout", "upstream timeout"))):
        if (re.search(r"(?<![0-9])%s(?![0-9])" % code, lowered)
                or any(phrase in lowered for phrase in phrases)):
            return ModelFailure("HTTP_%s" % code, True, "provider HTTP %s" % code)
    if "connect timeout" in lowered or "connection timed out" in lowered:
        return ModelFailure("CONNECT_TIMEOUT", True, "connect timeout")
    if "read timeout" in lowered:
        return ModelFailure("READ_TIMEOUT", True, "read timeout")
    if "timeoutexpired" in lowered or "provider timeout" in lowered or "模型处理超时" in raw:
        return ModelFailure("PROVIDER_TIMEOUT", True, "provider/model timeout")
    if "connection reset" in lowered or "connection aborted" in lowered or "network" in lowered or "网络波动" in raw:
        return ModelFailure("NETWORK_TRANSIENT", True, "network transient")
    if "service unavailable" in lowered or "provider unavailable" in lowered:
        return ModelFailure("PROVIDER_UNAVAILABLE", True, "provider unavailable")
    if "auth" in lowered and ("401" in lowered or "403" in lowered or "unauthorized" in lowered or "forbidden" in lowered):
        return ModelFailure("PROVIDER_AUTH_FAILURE", False, "provider auth failure")
    if "badrequesterror" in lowered or "bad request" in lowered or "400" in lowered:
        return ModelFailure("NON_RETRYABLE_REQUEST_ERROR", False, "bad request")
    return ModelFailure("UNKNOWN_MODEL_FAILURE", False, "unclassified model failure")


def _raw_output_path(launcher: Any, assignment: WorkerAssignment) -> Path:
    return Path(launcher.state_root) / "worker-evidence" / assignment.mission_id / (assignment.assignment_id + ".jsonl")


def _failure_text(launcher: Any, assignment: WorkerAssignment, exc: BaseException) -> str:
    parts = [str(exc)]
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        parts.append(type(cause).__name__)
        parts.append(str(cause))
    path = _raw_output_path(launcher, assignment)
    if path.is_file():
        try:
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return "\n".join(parts)


def _observed_tool_names(launcher: Any, assignment: WorkerAssignment) -> Tuple[str, ...]:
    path = _raw_output_path(launcher, assignment)
    if not path.is_file():
        return ()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    events = tuple(launcher._parse_json_lines(text))
    calls = launcher._tool_calls(events)
    names = []
    for call in calls:
        name = str(call.get("tool_name") or "").strip()
        if name:
            names.append(name)
    return tuple(names)


def _tool_tokens(name: str) -> Tuple[str, ...]:
    """Tokenize MCP/tool names so `runtime` is not mistaken for action `run`."""
    lowered = str(name or "").lower()
    return tuple(token for token in re.split(r"[^a-z0-9]+", lowered) if token)


def _tool_is_read_only(name: str) -> bool:
    tokens = set(_tool_tokens(name))
    if not tokens:
        return False
    if tokens.intersection(_MUTATING_TOOL_TOKENS):
        return False
    return bool(tokens.intersection(_SAFE_TOOL_TOKENS))


def _task_id(assignment: WorkerAssignment) -> Optional[str]:
    scope = str(assignment.scope or "")
    return scope[len("task:") :] if scope.startswith("task:") else None


def _deterministic_jitter(assignment: WorkerAssignment, retry_index: int, base_seconds: float) -> float:
    raw = "%s\x1f%s\x1f%d" % (assignment.assignment_id, assignment.attempt_id, retry_index)
    fraction = int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:4], 16) / float(0xFFFF)
    return fraction * max(0.0, base_seconds * 0.25)


def install_rc7_1_model_resilience() -> None:
    """Wrap the existing launcher with shared throttling and bounded recovery."""

    current = _agent_runtime.DshHeadlessWorkerLauncher.execute
    if getattr(current, "_rc71_model_resilience", False):
        return
    original = current

    def resilient_execute(self, assignment, prompt):
        max_requests = _env_int("PFC_RC71_MODEL_RATE_MAX", 100)
        window_seconds = _env_float("PFC_RC71_MODEL_RATE_WINDOW_SECONDS", 600.0, 0.1)
        max_retries = _env_int("PFC_RC71_MODEL_TRANSIENT_RETRIES", 3, 0)
        backoff_base = _env_float("PFC_RC71_MODEL_RETRY_BACKOFF_SECONDS", 2.0, 0.0)
        backoff_cap = _env_float("PFC_RC71_MODEL_RETRY_BACKOFF_CAP_SECONDS", 30.0, 0.0)
        sleeper = getattr(self, "_rc71_sleep_fn", time.sleep)
        governor = PersistentSlidingWindowGovernor(
            Path(self.state_root),
            max_requests=max_requests,
            window_seconds=window_seconds,
            sleep_fn=sleeper,
        )
        retry_index = 0
        task_id = _task_id(assignment)

        while True:
            # Entry must be R1-read-only if this signed Assignment was ever
            # launched, even before touching the shared request governor or
            # emitting retry telemetry. Model switch/restart is a NEW attempt.
            started = self.truth.query("agent_runtime_event",
                assignment_id=assignment.assignment_id)
            if any(row.get("event_name") == "WORKER_STARTED" for row in started):
                raise AgentRuntimeError("WORKER_ASSIGNMENT_REPLAY_FORBIDDEN_RECONCILE_R1")
            reservation = governor.reserve()
            if not reservation.admitted:
                self.emit_control_event(
                    "MODEL_RATE_LIMIT_WAIT",
                    assignment.mission_id,
                    task_id=task_id,
                    assignment_id=assignment.assignment_id,
                    attempt_id=assignment.attempt_id,
                    request_count=reservation.request_count,
                    max_requests=max_requests,
                    window_seconds=window_seconds,
                    wait_seconds=round(reservation.wait_seconds, 3),
                    reset_at=reservation.reset_at,
                    auto_resume=True,
                )
                sleeper(reservation.wait_seconds)
                continue

            self.emit_control_event(
                "MODEL_REQUEST_ADMITTED",
                assignment.mission_id,
                task_id=task_id,
                assignment_id=assignment.assignment_id,
                attempt_id=assignment.attempt_id,
                retry_index=retry_index,
                request_count=reservation.request_count,
                max_requests=max_requests,
                window_seconds=window_seconds,
            )
            if retry_index:
                self.emit_control_event(
                    "MODEL_RETRY_STARTED",
                    assignment.mission_id,
                    task_id=task_id,
                    assignment_id=assignment.assignment_id,
                    attempt_id=assignment.attempt_id,
                    retry_index=retry_index,
                )
            try:
                result = original(self, assignment, prompt)
            except AgentRuntimeError as exc:
                failure = classify_failure(_failure_text(self, assignment, exc))
                tools = _observed_tool_names(self, assignment)
                unsafe_tools = tuple(name for name in tools if not _tool_is_read_only(name))
                self.emit_control_event(
                    "MODEL_CALL_FAILED",
                    assignment.mission_id,
                    task_id=task_id,
                    assignment_id=assignment.assignment_id,
                    attempt_id=assignment.attempt_id,
                    retry_index=retry_index,
                    failure_category=failure.category,
                    retryable=failure.retryable,
                    observed_tool_calls=list(tools),
                    unsafe_tool_calls=list(unsafe_tools),
                )
                if not failure.retryable:
                    raise
                if unsafe_tools:
                    self.emit_control_event(
                        "MODEL_RECOVERY_BLOCKED_SIDE_EFFECT",
                        assignment.mission_id,
                        task_id=task_id,
                        assignment_id=assignment.assignment_id,
                        attempt_id=assignment.attempt_id,
                        failure_category=failure.category,
                        unsafe_tool_calls=list(unsafe_tools),
                        recovery_action="MISSION_AUTOPILOT_R1_RESUME_REQUIRED",
                    )
                    raise AgentRuntimeError("MODEL_RECOVERY_REQUIRED:SIDE_EFFECT_UNCERTAIN") from exc
                # A signed Worker STARTED event outlives this Python process.
                # Even when no tool receipt was captured, a broken stream does
                # not prove that the bank side effect never happened. Resume a
                # new independently admitted Attempt from R1; NEVER re-launch
                # the same assignment via the local automatic retry loop.
                started = any(row.get("event_name") == "WORKER_STARTED"
                              for row in self.truth.query("agent_runtime_event",
                                  assignment_id=assignment.assignment_id))
                if started:
                    self.emit_control_event(
                        "MODEL_RECOVERY_BLOCKED_SIDE_EFFECT",
                        assignment.mission_id,
                        task_id=task_id,
                        assignment_id=assignment.assignment_id,
                        attempt_id=assignment.attempt_id,
                        failure_category=failure.category,
                        unsafe_tool_calls=[],
                        reason="R1_WORKER_STARTED_UNKNOWN_EFFECT",
                        recovery_action="MISSION_AUTOPILOT_R1_RESUME_REQUIRED",
                    )
                    raise
                if retry_index >= max_retries:
                    self.emit_control_event(
                        "MODEL_RETRY_EXHAUSTED",
                        assignment.mission_id,
                        task_id=task_id,
                        assignment_id=assignment.assignment_id,
                        attempt_id=assignment.attempt_id,
                        retry_index=retry_index,
                        failure_category=failure.category,
                        final_error=str(exc),
                    )
                    # Preserve the established fail-closed error contract for
                    # existing RC7 callers. R1 records that retries were
                    # exhausted; callers still receive the original failure.
                    raise
                delay = min(backoff_cap, backoff_base * (2 ** retry_index)) if backoff_cap else 0.0
                delay += _deterministic_jitter(assignment, retry_index, backoff_base)
                retry_index += 1
                self.emit_control_event(
                    "MODEL_RETRY_SCHEDULED",
                    assignment.mission_id,
                    task_id=task_id,
                    assignment_id=assignment.assignment_id,
                    attempt_id=assignment.attempt_id,
                    retry_index=retry_index,
                    failure_category=failure.category,
                    delay_seconds=round(delay, 3),
                    auto_resume=True,
                )
                sleeper(delay)
                continue

            if retry_index:
                self.emit_control_event(
                    "MODEL_RECOVERED",
                    assignment.mission_id,
                    task_id=task_id,
                    assignment_id=assignment.assignment_id,
                    attempt_id=assignment.attempt_id,
                    retry_count=retry_index,
                    auto_resumed=True,
                )
            return result

    resilient_execute._rc71_model_resilience = True
    _agent_runtime.DshHeadlessWorkerLauncher.execute = resilient_execute
