from __future__ import annotations

import hashlib
import json
import locale
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence


class DatabaseExecutorError(RuntimeError):
    pass


_DEFAULT_TIMEOUT_SECONDS = 60
_DEFAULT_MAX_CHARS = 200000
_MAX_SQL_CHARS = 2_000_000


def _required_text(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DatabaseExecutorError(code)
    if "\x00" in text or "\r" in text or "\n" in text:
        raise DatabaseExecutorError(code + "_INVALID")
    return text


def _decode(value: bytes) -> str:
    candidates = ("utf-8", locale.getpreferredencoding(False), "gb18030")
    seen = set()
    for encoding in candidates:
        if not encoding or encoding.lower() in seen:
            continue
        seen.add(encoding.lower())
        try:
            return value.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    return value.decode("utf-8", errors="replace")


def _bounded(value: str, max_chars: int) -> Dict[str, Any]:
    original_chars = len(value)
    return {
        "text": value[:max_chars],
        "truncated": original_chars > max_chars,
        "original_chars": original_chars,
        "sha256": hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest(),
    }


def _workspace() -> Path:
    configured = os.environ.get("PFC_WORKSPACE") or os.environ.get("PFC_AITEST_HOME") or os.getcwd()
    path = Path(configured).expanduser().resolve()
    if not path.is_dir():
        raise DatabaseExecutorError("DATABASE_WORKSPACE_NOT_FOUND")
    return path


def _resolve_client() -> str:
    configured = str(os.environ.get("PFC_DB_CLIENT_BIN") or "").strip()
    if not configured:
        raise DatabaseExecutorError("DATABASE_CLIENT_NOT_CONFIGURED")
    candidate = Path(configured).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    found = shutil.which(configured)
    if found:
        return found
    raise DatabaseExecutorError("DATABASE_CLIENT_NOT_FOUND")


def _client_args() -> List[str]:
    raw = str(os.environ.get("PFC_DB_CLIENT_ARGS_JSON") or "[]").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DatabaseExecutorError("DATABASE_CLIENT_ARGS_JSON_INVALID") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise DatabaseExecutorError("DATABASE_CLIENT_ARGS_MUST_BE_STRING_LIST")
    values: List[str] = []
    for item in parsed:
        if "\x00" in item or "\r" in item or "\n" in item:
            raise DatabaseExecutorError("DATABASE_CLIENT_ARG_INVALID")
        values.append(item)
    return values


def _validate_sql(sql: object) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise DatabaseExecutorError("DATABASE_SQL_REQUIRED")
    if "\x00" in sql:
        raise DatabaseExecutorError("DATABASE_SQL_INVALID")
    if len(sql) > _MAX_SQL_CHARS:
        raise DatabaseExecutorError("DATABASE_SQL_TOO_LARGE")
    return sql


def execute_database_sql(
    *,
    sql: str,
    target_id: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> Dict[str, Any]:
    """Execute SQL through a capability-configured real database client.

    The executable and static connection arguments are supplied by the runtime
    environment (``PFC_DB_CLIENT_BIN`` / ``PFC_DB_CLIENT_ARGS_JSON``). SQL is
    sent only on stdin; no shell is used and SQL is never placed in argv.

    Connection secrets remain an operator/runtime concern (for example client
    config files or inherited vendor environment variables). This function
    deliberately does not copy environment variables, argv, or SQL text into
    the returned result/provenance surface.
    """

    target = _required_text(target_id, "DATABASE_TARGET_ID_REQUIRED")
    statement = _validate_sql(sql)
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1 or timeout_seconds > 300:
        raise DatabaseExecutorError("DATABASE_TIMEOUT_INVALID")
    if not isinstance(max_chars, int) or max_chars < 1000 or max_chars > 1_000_000:
        raise DatabaseExecutorError("DATABASE_MAX_CHARS_INVALID")

    client = _resolve_client()
    command: Sequence[str] = [client] + _client_args()
    sql_sha256 = hashlib.sha256(statement.encode("utf-8")).hexdigest()
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(_workspace()),
            input=statement.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _decode(exc.stdout if isinstance(exc.stdout, bytes) else b"")
        stderr = _decode(exc.stderr if isinstance(exc.stderr, bytes) else b"")
        detail = (stderr or stdout or "timeout").strip()[:1000]
        raise DatabaseExecutorError("DATABASE_EXECUTION_TIMEOUT:%s" % detail) from exc
    except OSError as exc:
        raise DatabaseExecutorError("DATABASE_EXECUTION_FAILED:%s" % type(exc).__name__) from exc

    stdout_text = _decode(proc.stdout or b"")
    stderr_text = _decode(proc.stderr or b"")
    if proc.returncode != 0:
        detail = (stderr_text or stdout_text or "database client failed").strip()[:1000]
        raise DatabaseExecutorError("DATABASE_CLIENT_EXIT_NONZERO:%s" % detail)

    client_name = Path(client).name
    invocation_ref = "database://%s/%s/%s" % (target, client_name, sql_sha256[:24])
    return {
        "tool": "database",
        "target_id": target,
        "client": client_name,
        "exit_code": int(proc.returncode),
        "sql_sha256": sql_sha256,
        "invocation_ref": invocation_ref,
        "stdout": _bounded(stdout_text, max_chars),
        "stderr": _bounded(stderr_text, min(max_chars, 50_000)),
        "shell": False,
        "sql_transport": "STDIN",
        "client_args_persisted": False,
    }
