"""RC7.1 model request governor and transient failure recovery.

This module is a bounded field-hardening overlay around the existing DSH Worker
launcher.  It does not change testing authority or manufacture PASS.  It adds:

* a file-backed sliding-window governor shared by all RC7 Python processes;
* deterministic classification of provider/network failures;
* bounded automatic retry before any uncertain side effect;
* R1 lifecycle events for admission, waiting, failure, retry and recovery;
* fail-closed handoff when tool side effects may already have happened.

The bank limit defaults to 100 requests / 600 seconds and is configurable via
PFC_RC71_MODEL_RATE_MAX / PFC_RC71_MODEL_RATE_WINDOW_SECONDS.  All retry calls
consume the same shared budget.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

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

_RETRYABLE = {
    "RATE_LIMIT",
    "HTTP_502",
    "HTTP_503",
    "HTTP_504",
    "SSE_STREAM_CLOSED_BEFORE_DONE",
    "CONNECT_TIMEOUT",
    "READ_TIMEOUT",
    "PROVIDER_TIMEOUT",
    "PROVIDER_UNAVAILABLE",
    "NETWORK_TRANSIENT",
}

_SAFE_TOOL_MARKERS = (
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
)


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
        root.mkdir(parents=True, exist_ok=True)
        self.state_path = root / "shared-window.json"
        self.lock_path = root / "shared-window.lock"

    def reserve(self) -> RateReservation:
        self._lock()
        try:
            now = float(self.now_fn())
            state = self._load()
            timestamps = []
            for value in state.get("timestamps", []):
                try:
                    stamp = float(value)
                except (TypeError, ValueError):
                    continue
                if stamp > now - self.window_seconds:
                    timestamps.append(stamp)
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
        if not self.state_path.is_file():
            return {"timestamps": []}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {"timestamps": []}
        return value if isinstance(value, dict) else {"timestamps": []}

    def _save(self, value: Dict[str, Any]) -> None:
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(str(temp), str(self.state_path))

    def _lock(self) -> None:
        deadline = float(self.now_fn()) + 10.0
        while True:
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
                finally:
                    os.close(fd)
                return
            except FileExistsError:
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                    if age > 30.0:
                        self.lock_path.unlink()
                        continue
                except OSError:
                    pass
                if float(self.now_fn()) >= deadline:
                    raise AgentRuntimeError("MODEL_RATE_GOVERNOR_LOCK_TIMEOUT")
                self.sleep_fn(0.02)

    def _unlock(self) -> None:
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass


def classify_failure(text: str) -> ModelFailure:
    raw = str(text or "")
    lowered = raw.lower()
    if "429" in lowered or "rate limit" in lowered or "too many requests" in lowered or "频率" in raw:
        return ModelFailure("RATE_LIMIT", True, "provider throttle")
    if "sse stream ended without [done]" in lowered or "stream_closed" in lowered or "stream closed" in lowered:
        return ModelFailure("SSE_STREAM_CLOSED_BEFORE_DONE", True, "SSE ended before DONE")
    for code in ("502", "503", "504"):
        if ("code" in lowered or "http" in lowered or "status" in lowered) and code in lowered:
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


def _tool_is_read_only(name: str) -> bool:
    lowered = str(name or "").lower()
    if any(marker in lowered for marker in _SAFE_TOOL_MARKERS):
        dangerous = ("write", "delete", "update", "create", "execute", "run", "publish", "submit", "insert")
        return not any(marker in lowered for marker in dangerous)
    return False


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
                if retry_index >= max_retries:
                    self.emit_control_event(
                        "MODEL_RETRY_EXHAUSTED",
                        assignment.mission_id,
                        task_id=task_id,
                        assignment_id=assignment.assignment_id,
                        attempt_id=assignment.attempt_id,
                        retry_index=retry_index,
                        failure_category=failure.category,
                    )
                    raise AgentRuntimeError("MODEL_TRANSIENT_RETRY_EXHAUSTED:%s" % failure.category) from exc
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
