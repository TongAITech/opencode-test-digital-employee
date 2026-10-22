"""Truth-neutral DSH headless JSON runner for RC8 office-node workers.

This module deliberately owns no TestRun/WorkItem/R1 state. It validates only
whether one DSH subprocess invocation is a legitimate independent model worker:
- exact headless JSON CLI protocol;
- fresh session-* identity;
- at least one real tool-call event;
- strict final JSON object;
- process exit code zero.

Callers must publish Attempt/Artifact/Gap/Sufficiency facts through the formal
RC8 NodeAgent so R1 remains the only runtime truth.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


class DshJsonRunnerError(RuntimeError):
    def __init__(
        self,
        reason: str,
        *,
        stdout: str = "",
        stderr: str = "",
        exit_code: Optional[int] = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


@dataclass(frozen=True)
class DshJsonResult:
    session_id: str
    tool_calls: Tuple[Dict[str, Any], ...]
    output: Dict[str, Any]
    stdout: str
    stderr: str
    exit_code: int


CommandRunner = Callable[..., Any]


class DshJsonRunner:
    def __init__(
        self,
        *,
        dsh_bin: str = "dsh",
        patch_path: str,
        cwd: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
        timeout_seconds: int = 300,
        command_runner: CommandRunner = subprocess.run,
    ) -> None:
        self.dsh_bin = str(dsh_bin or "").strip()
        self.patch_path = str(patch_path or "").strip()
        self.cwd = str(cwd) if cwd is not None else None
        self.env = dict(env or {})
        self.timeout_seconds = int(timeout_seconds)
        self.command_runner = command_runner
        self._known_sessions = set()  # type: set[str]
        if not self.dsh_bin:
            raise DshJsonRunnerError("DSH_BINARY_REQUIRED")
        if not self.patch_path:
            raise DshJsonRunnerError("DSH_PATCH_REQUIRED")
        if self.timeout_seconds <= 0:
            raise DshJsonRunnerError("DSH_TIMEOUT_INVALID")

    def run(self, prompt: str) -> DshJsonResult:
        value = str(prompt or "").strip()
        if not value:
            raise DshJsonRunnerError("DSH_PROMPT_REQUIRED")
        if not self._dsh_available():
            raise DshJsonRunnerError("DSH_NOT_AVAILABLE")
        command = [
            self.dsh_bin,
            "--profile", "headless",
            "--patch", self.patch_path,
            "--json",
            value,
        ]
        run_env = os.environ.copy()
        run_env.update(self.env)
        try:
            proc = self.command_runner(
                command,
                cwd=self.cwd,
                env=run_env,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DshJsonRunnerError(
                "DSH_TIMEOUT",
                stdout=self._text(getattr(exc, "stdout", "")),
                stderr=self._text(getattr(exc, "stderr", "")),
            ) from exc
        except OSError as exc:
            raise DshJsonRunnerError("DSH_LAUNCH_FAILED:%s" % type(exc).__name__) from exc

        stdout = self._text(getattr(proc, "stdout", ""))
        stderr = self._text(getattr(proc, "stderr", ""))
        exit_code = int(getattr(proc, "returncode", -1))
        events = tuple(self._parse_json_lines(stdout))
        session_id = self._session_id(events)
        if not session_id:
            raise DshJsonRunnerError(
                "DSH_SESSION_ID_MISSING",
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
            )
        if session_id in self._known_sessions:
            raise DshJsonRunnerError(
                "WORKER_SESSION_NOT_INDEPENDENT",
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
            )
        self._known_sessions.add(session_id)

        calls = tuple(self._tool_calls(events))
        if not calls:
            raise DshJsonRunnerError(
                "REAL_TOOL_CALL_MISSING",
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
            )
        output = self._final_json(events)
        if not output:
            raise DshJsonRunnerError(
                "STRICT_JSON_OUTPUT_MISSING",
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
            )
        if exit_code != 0:
            raise DshJsonRunnerError(
                "WORKER_PROCESS_FAILED",
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
            )
        return DshJsonResult(
            session_id=session_id,
            tool_calls=calls,
            output=output,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        )

    def _dsh_available(self) -> bool:
        path = self.dsh_bin
        if os.path.isabs(path) or os.sep in path or (os.altsep and os.altsep in path):
            return Path(path).is_file()
        return shutil.which(path) is not None

    @staticmethod
    def _text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    @staticmethod
    def _parse_json_lines(text: str) -> Iterable[Dict[str, Any]]:
        for raw in text.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value

    @classmethod
    def _session_id(cls, events: Sequence[Dict[str, Any]]) -> str:
        for event in events:
            kind = str(event.get("type") or event.get("event") or event.get("kind") or "").lower()
            candidates = cls._walk_values(event, {"session_id", "sessionid", "id"})
            for value in candidates:
                if isinstance(value, str) and value.startswith("session-") and ("session" in kind or value):
                    return value
        return ""

    @classmethod
    def _tool_calls(cls, events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        calls: List[Dict[str, Any]] = []
        for index, event in enumerate(events):
            kind = str(event.get("type") or event.get("event") or event.get("kind") or "").lower()
            has_tool_name = any(
                str(key).lower() in {"tool", "tool_name", "toolname", "name"}
                for key in event.keys()
            )
            if "tool_call" not in kind and "toolcall" not in kind and not (
                "tool" in kind and "result" not in kind and has_tool_name
            ):
                continue
            tool_name = ""
            for key in ("tool_name", "toolName", "tool", "name"):
                candidate = event.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    tool_name = candidate.strip()
                    break
            if not tool_name:
                nested = cls._walk_values(event, {"tool_name", "toolname", "tool", "name"})
                tool_name = next(
                    (str(candidate) for candidate in nested if isinstance(candidate, str) and candidate.strip()),
                    "unknown",
                )
            calls.append({"call_ref": "dsh-event://tool-call/%d" % index, "tool_name": tool_name})
        return calls

    @classmethod
    def _final_json(cls, events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        strings: List[str] = []
        for event in events:
            kind = str(event.get("type") or event.get("event") or event.get("kind") or "").lower()
            if kind in {"text", "final", "message", "assistant"} or "final" in kind or "text" in kind:
                strings.extend(
                    str(value)
                    for value in cls._walk_values(event, {"text", "content", "message", "output"})
                    if isinstance(value, str)
                )
        for text in reversed(strings):
            obj = cls._last_json_object(text)
            if isinstance(obj, dict):
                qualification = obj.get("qualification_payload")
                return qualification if isinstance(qualification, dict) else obj
        return {}

    @staticmethod
    def _last_json_object(text: str) -> Optional[Dict[str, Any]]:
        decoder = json.JSONDecoder()
        candidates: List[Dict[str, Any]] = []
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                candidates.append(value)
        return candidates[-1] if candidates else None

    @staticmethod
    def _walk_values(value: Any, keys: set) -> List[Any]:
        found: List[Any] = []
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in keys:
                    found.append(child)
                found.extend(DshJsonRunner._walk_values(child, keys))
        elif isinstance(value, list):
            for child in value:
                found.extend(DshJsonRunner._walk_values(child, keys))
        return found
