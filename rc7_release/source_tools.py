from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict


class SourceToolError(RuntimeError):
    pass


_SCOPES = {
    "workspace": "PFC_WORKSPACE",
    "state": "PFC_AITEST_STATE_DIR",
}


def _scope_root(scope: str) -> Path:
    if scope not in _SCOPES:
        raise SourceToolError("SOURCE_SCOPE_INVALID")
    env_name = _SCOPES[scope]
    value = os.environ.get(env_name)
    if not value and scope == "workspace":
        value = os.environ.get("PFC_AITEST_HOME")
    if not value:
        raise SourceToolError("%s_NOT_CONFIGURED" % env_name)
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise SourceToolError("SOURCE_ROOT_NOT_FOUND")
    return root


def read_text(
    *,
    path: str,
    scope: str = "workspace",
    max_chars: int = 200000,
) -> Dict[str, Any]:
    if not isinstance(path, str) or not path.strip():
        raise SourceToolError("SOURCE_PATH_REQUIRED")
    if not isinstance(max_chars, int) or max_chars < 1000 or max_chars > 1000000:
        raise SourceToolError("SOURCE_MAX_CHARS_INVALID")
    relative = Path(path.strip())
    if relative.is_absolute() or ".." in relative.parts:
        raise SourceToolError("SOURCE_PATH_MUST_BE_SCOPE_RELATIVE")
    root = _scope_root(scope)
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SourceToolError("SOURCE_PATH_ESCAPES_SCOPE") from exc
    if not target.is_file():
        raise SourceToolError("SOURCE_FILE_NOT_FOUND")
    raw = target.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceToolError("SOURCE_FILE_NOT_UTF8") from exc
    truncated = len(text) > max_chars
    return {
        "tool": "read_text",
        "scope": scope,
        "path": path.strip(),
        "resolved_path": str(target),
        "file_uri": "file://" + str(target),
        "text": text[:max_chars] if truncated else text,
        "truncated": truncated,
        "original_chars": len(text),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
