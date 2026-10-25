from __future__ import annotations

import hashlib
import json
import locale
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


class BrowserExecutorError(RuntimeError):
    pass


_ALLOWED_KINDS = ("browser-skill", "playwright")
_DEFAULT_TIMEOUT_SECONDS = 120
_DEFAULT_MAX_CHARS = 200000


def _decode(value: bytes) -> str:
    for encoding in ("utf-8", locale.getpreferredencoding(False), "gb18030"):
        try:
            return value.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    return value.decode("utf-8", errors="replace")


def _bounded(value: str, max_chars: int) -> Dict[str, Any]:
    return {
        "text": value[:max_chars],
        "truncated": len(value) > max_chars,
        "original_chars": len(value),
        "sha256": hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest(),
    }


def _workspace() -> Path:
    configured = os.environ.get("PFC_WORKSPACE") or os.environ.get("PFC_AITEST_HOME") or os.getcwd()
    path = Path(configured).expanduser().resolve()
    if not path.is_dir():
        raise BrowserExecutorError("BROWSER_WORKSPACE_NOT_FOUND")
    return path


def _resolve_client() -> str:
    configured = str(os.environ.get("PFC_BROWSER_CLIENT_BIN") or "").strip()
    if not configured:
        raise BrowserExecutorError("BROWSER_CLIENT_NOT_CONFIGURED")
    candidate = Path(configured).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    found = shutil.which(configured)
    if found:
        return found
    raise BrowserExecutorError("BROWSER_CLIENT_NOT_FOUND")


def _client_args() -> List[str]:
    raw = str(os.environ.get("PFC_BROWSER_CLIENT_ARGS_JSON") or "[]").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BrowserExecutorError("BROWSER_CLIENT_ARGS_JSON_INVALID") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise BrowserExecutorError("BROWSER_CLIENT_ARGS_MUST_BE_STRING_LIST")
    if any("\x00" in item or "\r" in item or "\n" in item for item in parsed):
        raise BrowserExecutorError("BROWSER_CLIENT_ARG_INVALID")
    return list(parsed)


def _binding(target_id: object) -> tuple:
    target = str(target_id or "").strip()
    if not target:
        raise BrowserExecutorError("BROWSER_TARGET_ID_REQUIRED")
    configured_target = str(os.environ.get("PFC_BROWSER_TARGET_ID") or "").strip()
    if not configured_target:
        raise BrowserExecutorError("BROWSER_TARGET_NOT_CONFIGURED")
    if configured_target != target:
        raise BrowserExecutorError("BROWSER_TARGET_MISMATCH")
    kind = str(os.environ.get("PFC_BROWSER_TOOL_KIND") or "").strip().lower()
    if kind not in _ALLOWED_KINDS:
        raise BrowserExecutorError("BROWSER_TOOL_KIND_NOT_ADMITTED")
    return target, kind


def execute_browser_action(
    *,
    request: Mapping[str, Any],
    target_id: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> Dict[str, Any]:
    """Invoke a capability-configured BrowserSkill/Playwright process.

    The action is transported as canonical JSON on stdin with shell disabled.
    Runtime configuration binds both the exact TargetIdentity and admitted
    implementation kind. No invocation receipt is returned for failed calls.
    """
    if not isinstance(request, Mapping) or not request:
        raise BrowserExecutorError("BROWSER_REQUEST_REQUIRED")
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1 or timeout_seconds > 600:
        raise BrowserExecutorError("BROWSER_TIMEOUT_INVALID")
    if not isinstance(max_chars, int) or max_chars < 1000 or max_chars > 1000000:
        raise BrowserExecutorError("BROWSER_MAX_CHARS_INVALID")
    target, kind = _binding(target_id)
    client = _resolve_client()
    body = (json.dumps(dict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    request_sha256 = hashlib.sha256(body).hexdigest()
    command: Sequence[str] = [client] + _client_args()
    try:
        proc = subprocess.run(
            list(command), cwd=str(_workspace()), input=body,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout_seconds, check=False, shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BrowserExecutorError("BROWSER_EXECUTION_TIMEOUT") from exc
    except OSError as exc:
        raise BrowserExecutorError("BROWSER_EXECUTION_FAILED:%s" % type(exc).__name__) from exc
    stdout = _decode(proc.stdout or b"")
    stderr = _decode(proc.stderr or b"")
    if proc.returncode != 0:
        detail = (stderr or stdout or "browser client failed").strip()[:1000]
        raise BrowserExecutorError("BROWSER_CLIENT_EXIT_NONZERO:%s" % detail)
    client_name = Path(client).name
    invocation_ref = "%s://%s/%s/%s" % (kind, target, client_name, request_sha256[:24])
    return {
        "tool": "browser-skill",
        "implementation": kind,
        "target_id": target,
        "client": client_name,
        "exit_code": int(proc.returncode),
        "request_sha256": request_sha256,
        "invocation_ref": invocation_ref,
        "stdout": _bounded(stdout, max_chars),
        "stderr": _bounded(stderr, min(max_chars, 50000)),
        "shell": False,
        "request_transport": "STDIN_JSON",
        "client_args_persisted": False,
    }
