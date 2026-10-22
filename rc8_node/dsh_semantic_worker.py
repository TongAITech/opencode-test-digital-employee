"""RC8 DSH headless semantic worker for evidence-backed code analysis.

This adapter reuses the bank-proven DSH CLI protocol:
    dsh --profile headless [--patch <patch>] --json <task>

DSH session state is provenance only. The authoritative task identity, source
snapshot and evidence remain RC8 TestRun/WorkItem/Git/Artifact/R1 facts.
"""
from __future__ import annotations

import json
import locale
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


class DshSemanticWorkerError(RuntimeError):
    pass


_STAGE_MARKER = "[PFC_STAGE:code-analysis-semantic]"
_ASSERTION_MARKER = "[PFC_ASSERTION:code-analysis-semantic]"
_REQUIRED_READ_TOOL = "mcp__pfc_aitest_rc7__read_text"


def _decode_bytes(value: bytes) -> Tuple[str, str]:
    if not value:
        return "", "empty"
    candidates = ("utf-8", locale.getpreferredencoding(False), "gb18030")
    seen = set()
    for encoding in candidates:
        if not encoding:
            continue
        key = encoding.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            return value.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            pass
    return value.decode("utf-8", errors="replace"), "utf-8-replace"


def _walk_values(value: Any, keys: set) -> List[Any]:
    found: List[Any] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in keys:
                found.append(child)
            found.extend(_walk_values(child, keys))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_values(child, keys))
    return found


def _parse_json_lines(text: str) -> Tuple[Dict[str, Any], ...]:
    rows: List[Dict[str, Any]] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return tuple(rows)


def _event_kind(event: Mapping[str, Any]) -> str:
    return str(event.get("type") or event.get("event") or event.get("kind") or "").lower()


def _session_id(events: Sequence[Mapping[str, Any]]) -> str:
    for event in events:
        kind = _event_kind(event)
        candidates = _walk_values(event, {"session_id", "sessionid", "id"})
        for value in candidates:
            if isinstance(value, str) and value.startswith("session-") and ("session" in kind or value):
                return value
    return ""


def _tool_calls(events: Sequence[Mapping[str, Any]]) -> Tuple[Dict[str, Any], ...]:
    calls: List[Dict[str, Any]] = []
    for index, event in enumerate(events):
        kind = _event_kind(event)
        keys = {str(key).lower() for key in event.keys()}
        has_tool_name = bool(keys.intersection({"tool", "tool_name", "toolname", "name"}))
        if "tool_call" not in kind and "toolcall" not in kind and not ("tool" in kind and "result" not in kind and has_tool_name):
            continue
        names = _walk_values(event, {"tool_name", "toolname", "tool", "name"})
        tool_name = next((str(value).strip() for value in names if isinstance(value, str) and value.strip()), "unknown")
        call_ids = _walk_values(event, {"tool_call_id", "toolcallid", "call_id", "callid", "id"})
        call_id = next((str(value) for value in call_ids if isinstance(value, str) and value.strip()), "")
        calls.append({"event_index": index, "tool_name": tool_name, "call_id": call_id})
    return tuple(calls)


def _tool_results(events: Sequence[Mapping[str, Any]]) -> Tuple[Dict[str, Any], ...]:
    results: List[Dict[str, Any]] = []
    for index, event in enumerate(events):
        kind = _event_kind(event)
        lowered = json.dumps(event, ensure_ascii=False).lower()
        if not ("tool_result" in kind or "toolresult" in kind or ("tool" in kind and "result" in kind)):
            # Some DSH builds use generic result/message events with a tool_call_id.
            if not any(token in lowered for token in ("tool_call_id", "toolcallid", "call_id")):
                continue
            if "result" not in lowered and "output" not in lowered:
                continue
        call_ids = _walk_values(event, {"tool_call_id", "toolcallid", "call_id", "callid", "id"})
        call_id = next((str(value) for value in call_ids if isinstance(value, str) and value.strip()), "")
        results.append({"event_index": index, "call_id": call_id, "kind": kind})
    return tuple(results)


def _last_json_object(text: str) -> Optional[Dict[str, Any]]:
    decoder = json.JSONDecoder()
    candidates: List[Dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except ValueError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    return candidates[-1] if candidates else None


def _assistant_texts(events: Sequence[Mapping[str, Any]]) -> Tuple[str, ...]:
    values: List[str] = []
    for event in events:
        kind = _event_kind(event)
        if kind in {"text", "final", "message", "assistant"} or "final" in kind or "text" in kind or "assistant" in kind:
            values.extend(str(value) for value in _walk_values(event, {"text", "content", "message", "output"}) if isinstance(value, str))
    return tuple(values)


def _final_json(events: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    for text in reversed(_assistant_texts(events)):
        value = _last_json_object(text)
        if isinstance(value, dict):
            if isinstance(value.get("qualification_payload"), dict):
                return dict(value["qualification_payload"])
            return value
    return {}


def _resolve_binary(command: str) -> str:
    candidate = (command or "").strip()
    if not candidate:
        raise DshSemanticWorkerError("DSH_COMMAND_REQUIRED")
    path = Path(candidate).expanduser()
    if path.is_file():
        return str(path.resolve())
    found = shutil.which(candidate)
    if found:
        return found
    raise DshSemanticWorkerError("DSH_COMMAND_NOT_FOUND:%s" % candidate)


def _bounded(value: str, limit: int = 2000000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...<RC8_TRUNCATED>...\n"


@dataclass(frozen=True)
class DshSemanticResult:
    state: str
    classification: str
    session_id: str
    exit_code: int
    semantic_analysis: Dict[str, Any]
    tool_calls: Tuple[Dict[str, Any], ...]
    tool_results: Tuple[Dict[str, Any], ...]
    stdout_encoding: str
    stderr_encoding: str
    raw_jsonl_path: str
    provenance_path: str


class DshSemanticWorker:
    def __init__(
        self,
        evidence_dir: str,
        *,
        dsh_command: str,
        patch: Optional[str] = None,
        timeout_seconds: int = 600,
        command_runner=None,
    ) -> None:
        self.evidence_dir = Path(evidence_dir).resolve()
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.dsh_command = _resolve_binary(dsh_command) if command_runner is None else str(dsh_command)
        self.patch = (patch or "").strip()
        self.timeout_seconds = int(timeout_seconds)
        if self.timeout_seconds < 30 or self.timeout_seconds > 3600:
            raise DshSemanticWorkerError("DSH_TIMEOUT_INVALID")
        self.command_runner = command_runner or subprocess.run

    @staticmethod
    def build_prompt(request_file_name: str) -> str:
        return (
            "You are the RC8 code-analysis semantic worker. "
            "Do not guess APIs, call chains, database objects, business rules, or test impacts.\n"
            "MANDATORY_FIRST_ACTION: use the runtime-visible native tool " + _REQUIRED_READ_TOOL +
            " to read the file '" + request_file_name + "' from the current worker workspace. "
            "Follow the tool's runtime-visible schema exactly; do not invent arguments.\n"
            "The request contains one immutable Git snapshot, compact CodeGraph evidence, an allowlist of evidence_refs, "
            "and the exact output contract. Every formal claim must cite one or more evidence_refs from that allowlist. "
            "If evidence is insufficient, put the uncertainty in unknowns and set sufficiency.state=INSUFFICIENT.\n"
            + _STAGE_MARKER + "\n"
            "Before the final JSON, emit exactly this marker after you have checked all claims against evidence: "
            + _ASSERTION_MARKER + "\n"
            "Return one final strict JSON object only after the markers. No markdown fences."
        )

    def execute(self, *, request_path: str, env: Optional[Mapping[str, str]] = None) -> DshSemanticResult:
        request = Path(request_path).resolve()
        if not request.is_file():
            raise DshSemanticWorkerError("SEMANTIC_REQUEST_NOT_FOUND:%s" % request)
        try:
            request.relative_to(self.evidence_dir)
        except ValueError as exc:
            raise DshSemanticWorkerError("SEMANTIC_REQUEST_OUTSIDE_WORKER_DIR") from exc
        prompt = self.build_prompt(request.name)
        command: List[str] = [self.dsh_command, "--profile", "headless"]
        if self.patch:
            command.extend(["--patch", self.patch])
        command.extend(["--json", prompt])
        run_env = os.environ.copy()
        run_env.update({str(key): str(value) for key, value in dict(env or {}).items()})
        started = int(time.time())
        try:
            proc = self.command_runner(
                command,
                cwd=str(self.evidence_dir),
                env=run_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout_raw = exc.stdout if isinstance(exc.stdout, bytes) else b""
            stderr_raw = exc.stderr if isinstance(exc.stderr, bytes) else b""
            stdout, stdout_encoding = _decode_bytes(stdout_raw)
            stderr, stderr_encoding = _decode_bytes(stderr_raw)
            self._persist_raw(stdout, stderr)
            raise DshSemanticWorkerError("DSH_SEMANTIC_TIMEOUT") from exc
        except OSError as exc:
            raise DshSemanticWorkerError("DSH_SEMANTIC_LAUNCH_FAILED:%s" % type(exc).__name__) from exc

        stdout, stdout_encoding = _decode_bytes(proc.stdout or b"")
        stderr, stderr_encoding = _decode_bytes(proc.stderr or b"")
        raw_path = self._persist_raw(stdout, stderr)
        events = _parse_json_lines(stdout)
        session_id = _session_id(events)
        calls = _tool_calls(events)
        results = _tool_results(events)
        texts = _assistant_texts(events)
        semantic = _final_json(events)

        failure = ""
        if proc.returncode != 0:
            failure = "DSH_SEMANTIC_PROCESS_FAILED"
        elif not session_id:
            failure = "DSH_SEMANTIC_SESSION_ID_MISSING"
        elif not calls:
            failure = "DSH_SEMANTIC_REAL_TOOL_CALL_MISSING"
        elif not any(call.get("tool_name") == _REQUIRED_READ_TOOL for call in calls):
            failure = "DSH_SEMANTIC_REQUEST_READ_TOOL_MISSING"
        elif not results:
            failure = "DSH_SEMANTIC_TOOL_RESULT_MISSING"
        elif _STAGE_MARKER not in "\n".join(texts):
            failure = "DSH_SEMANTIC_STAGE_MARKER_MISSING"
        elif _ASSERTION_MARKER not in "\n".join(texts):
            failure = "DSH_SEMANTIC_ASSERTION_MARKER_MISSING"
        elif not semantic:
            failure = "DSH_SEMANTIC_STRICT_JSON_MISSING"

        provenance = {
            "schema_version": 1,
            "state": "PASS" if not failure else "FAIL",
            "classification": "DSH_SEMANTIC_WORKER_VERIFIED" if not failure else failure,
            "session_id": session_id,
            "exit_code": int(proc.returncode),
            "started_at": started,
            "finished_at": int(time.time()),
            "request_path": str(request),
            "tool_calls": list(calls),
            "tool_results": list(results),
            "stdout_encoding": stdout_encoding,
            "stderr_encoding": stderr_encoding,
            "raw_jsonl_path": str(raw_path),
            "semantic_analysis_present": bool(semantic),
            "truth_note": "DSH session/tool trace is provenance; RC8 validates semantic claims against the current snapshot evidence allowlist before promotion.",
        }
        provenance_path = self.evidence_dir / "dsh-semantic-provenance.json"
        provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        if failure:
            raise DshSemanticWorkerError(failure)
        return DshSemanticResult(
            state="PASS",
            classification="DSH_SEMANTIC_WORKER_VERIFIED",
            session_id=session_id,
            exit_code=int(proc.returncode),
            semantic_analysis=dict(semantic),
            tool_calls=calls,
            tool_results=results,
            stdout_encoding=stdout_encoding,
            stderr_encoding=stderr_encoding,
            raw_jsonl_path=str(raw_path),
            provenance_path=str(provenance_path),
        )

    def _persist_raw(self, stdout: str, stderr: str) -> Path:
        path = self.evidence_dir / "dsh-semantic.jsonl"
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(_bounded(stdout))
            if stderr:
                if stdout and not stdout.endswith("\n"):
                    handle.write("\n")
                handle.write(json.dumps({"type": "stderr", "text": _bounded(stderr, 200000)}, ensure_ascii=False))
                handle.write("\n")
        return path
