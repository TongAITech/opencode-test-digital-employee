from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

WORKSPACE_ROOT = Path(os.environ.get("AITEST_WORKSPACE_ROOT") or Path(__file__).resolve().parents[3]).resolve()
AI_ROOT = WORKSPACE_ROOT / "ai-test"
DB_PATH = Path(os.environ.get("AITEST_DB_PATH") or (AI_ROOT / "state" / "aitest.db")).resolve()
VERSION = "1.11.1"

SENSITIVE_KEY_RE = re.compile(
    r"(?i)(password|passwd|pwd|token|authorization|cookie|secret|client[_-]?secret|access[_-]?key|private[_-]?key|otp|mfa)"
)
SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._~+/=-]{8,}|basic\s+[a-z0-9+/=]{8,}|(?:password|passwd|pwd|token|secret|otp|mfa)\s*[:=]\s*[^\s,;]+)"
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {path}: {exc}") from exc


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, pretty_json(value))


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL: {path}:{no}: {exc}") from exc
        if isinstance(value, dict):
            rows.append(value)
    return rows


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def redact(value: Any, key: str = "") -> Any:
    if key and SENSITIVE_KEY_RE.search(key):
        if isinstance(value, str) and value.startswith(("secret://", "profile://", "env://")):
            return value
        return "<REDACTED>"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return SENSITIVE_VALUE_RE.sub("<REDACTED>", value)
    return value


def safe_id(value: str, fallback: str = "item") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return text or fallback


def ensure_dirs() -> None:
    for rel in (
        "state", "evidence", "artifacts/cache", "migrations", "local/adapters", "local/secrets", "local/cache",
        "reports", "exports", "control-plane/browser-profiles", "control-plane/browser-traces"
    ):
        (AI_ROOT / rel).mkdir(parents=True, exist_ok=True)


def run_process(args: list[str], *, cwd: Path | None = None, timeout: int = 60, env: dict[str, str] | None = None) -> dict[str, Any]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    try:
        cp = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            env=merged,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return {
            "ok": cp.returncode == 0,
            "returncode": cp.returncode,
            "stdout": cp.stdout.strip(),
            "stderr": cp.stderr.strip(),
            "command": args,
        }
    except FileNotFoundError:
        return {"ok": False, "returncode": 127, "stdout": "", "stderr": f"not found: {args[0]}", "command": args}
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": 124,
            "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            "stderr": f"timeout after {timeout}s",
            "command": args,
        }


def path_within(path: Path, roots: Iterable[Path]) -> bool:
    target = path.resolve()
    for root in roots:
        try:
            target.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def parse_json_arg(text: str | None, default: Any = None) -> Any:
    if text is None or text == "":
        return default
    return json.loads(text)


def runtime_python_command() -> list[str]:
    """Return only the package-relative Windows portable Python executable."""
    candidate = WORKSPACE_ROOT / "runtime" / "python" / "python.exe"
    return [str(candidate)] if candidate.is_file() else []
