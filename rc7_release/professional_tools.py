from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


class ProfessionalToolError(RuntimeError):
    pass


_DEFAULT_TIMEOUT_SECONDS = 60
_DEFAULT_MAX_CHARS = 200000
_CODEGRAPH_QUERY_VERBS = {
    "query",
    "search",
    "symbol",
    "symbols",
    "callers",
    "callees",
    "references",
    "reference",
    "impact",
    "dependencies",
    "dependents",
    "path",
    "paths",
}
_CODEGRAPH_SAFE_OPTIONS = {
    "--json",
    "--format",
    "--depth",
    "--limit",
    "--symbol",
    "--path",
    "--query",
    "--target",
    "--repo",
    "--repository",
    "-j",
}
_CODEGRAPH_FORBIDDEN_TOKENS = {
    "index",
    "build",
    "init",
    "write",
    "update",
    "delete",
    "remove",
    "clean",
    "watch",
    "serve",
    "install",
    "uninstall",
    "config",
    "migrate",
    "import",
    "export",
    "apply",
    "fix",
}


def _workspace() -> Path:
    value = os.environ.get("PFC_WORKSPACE") or os.environ.get("PFC_AITEST_HOME") or os.getcwd()
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ProfessionalToolError("WORKSPACE_NOT_FOUND")
    return root


def _repo_path(repo_path: Optional[str]) -> Path:
    root = _workspace()
    if not repo_path or repo_path == ".":
        candidate = root
    else:
        relative = Path(repo_path)
        if relative.is_absolute():
            raise ProfessionalToolError("REPO_PATH_MUST_BE_WORKSPACE_RELATIVE")
        candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ProfessionalToolError("REPO_PATH_ESCAPES_WORKSPACE") from exc
    if not candidate.is_dir():
        raise ProfessionalToolError("REPO_PATH_NOT_FOUND")
    return candidate


def _resolve_binary(env_name: str, fallback: Optional[str] = None) -> str:
    configured = os.environ.get(env_name)
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return str(path.resolve())
        found = shutil.which(configured)
        if found:
            return found
        raise ProfessionalToolError("%s_NOT_FOUND" % env_name)
    if fallback:
        found = shutil.which(fallback)
        if found:
            return found
    raise ProfessionalToolError("%s_NOT_CONFIGURED" % env_name)


def _bounded_text(value: str, max_chars: int) -> Dict[str, Any]:
    if not isinstance(max_chars, int) or max_chars < 1000 or max_chars > 1000000:
        raise ProfessionalToolError("MAX_CHARS_INVALID")
    original_length = len(value)
    truncated = original_length > max_chars
    text = value[:max_chars] if truncated else value
    return {
        "text": text,
        "truncated": truncated,
        "original_chars": original_length,
        "sha256": hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest(),
    }


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> Dict[str, Any]:
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1 or timeout_seconds > 300:
        raise ProfessionalToolError("TOOL_TIMEOUT_INVALID")
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProfessionalToolError("TOOL_EXECUTION_FAILED:%s" % type(exc).__name__) from exc
    stdout = _bounded_text(proc.stdout or "", max_chars)
    stderr = _bounded_text(proc.stderr or "", min(max_chars, 50000))
    result = {
        "command": [str(item) for item in command],
        "cwd": str(cwd),
        "exit_code": int(proc.returncode),
        "stdout": stdout,
        "stderr": stderr,
    }
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "tool failed").strip()
        raise ProfessionalToolError("TOOL_EXIT_NONZERO:%s" % message[:1000])
    return result


def _safe_ref(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfessionalToolError("%s_REQUIRED" % field.upper())
    value = value.strip()
    if value.startswith("-") or "\x00" in value or "\n" in value or "\r" in value:
        raise ProfessionalToolError("%s_INVALID" % field.upper())
    if len(value) > 300:
        raise ProfessionalToolError("%s_TOO_LONG" % field.upper())
    return value


def _safe_paths(paths: Optional[Iterable[str]]) -> List[str]:
    values: List[str] = []
    for value in paths or ():
        if not isinstance(value, str) or not value.strip():
            raise ProfessionalToolError("GIT_PATH_INVALID")
        path = Path(value.strip())
        if path.is_absolute() or ".." in path.parts:
            raise ProfessionalToolError("GIT_PATH_ESCAPES_REPOSITORY")
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ProfessionalToolError("GIT_PATH_INVALID")
        values.append(value.strip())
    return values


def git_diff(
    *,
    repo_path: str = ".",
    base_ref: str,
    head_ref: str,
    paths: Optional[Iterable[str]] = None,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> Dict[str, Any]:
    repo = _repo_path(repo_path)
    git = _resolve_binary("PFC_GIT_BIN", "git")
    base = _safe_ref(base_ref, "base_ref")
    head = _safe_ref(head_ref, "head_ref")
    selected_paths = _safe_paths(paths)

    base_rev = _run([git, "rev-parse", "--verify", base + "^{commit}"], cwd=repo, max_chars=10000)["stdout"]["text"].strip()
    head_rev = _run([git, "rev-parse", "--verify", head + "^{commit}"], cwd=repo, max_chars=10000)["stdout"]["text"].strip()
    if not base_rev or not head_rev:
        raise ProfessionalToolError("GIT_REVISION_RESOLUTION_FAILED")

    name_command = [git, "diff", "--no-ext-diff", "--name-only", base_rev, head_rev, "--"] + selected_paths
    diff_command = [git, "diff", "--no-ext-diff", "--unified=3", base_rev, head_rev, "--"] + selected_paths
    changed = _run(name_command, cwd=repo, max_chars=min(max_chars, 100000))
    diff = _run(diff_command, cwd=repo, max_chars=max_chars)
    changed_files = [line.strip() for line in changed["stdout"]["text"].splitlines() if line.strip()]
    return {
        "tool": "git_diff",
        "repo": str(repo),
        "base_ref": base,
        "head_ref": head,
        "base_revision": base_rev,
        "head_revision": head_rev,
        "paths": selected_paths,
        "changed_files": changed_files,
        "diff": diff["stdout"],
    }


def git_show_revision(*, repo_path: str = ".", ref: str = "HEAD") -> Dict[str, Any]:
    repo = _repo_path(repo_path)
    git = _resolve_binary("PFC_GIT_BIN", "git")
    safe_ref = _safe_ref(ref, "ref")
    sha = _run([git, "rev-parse", "--verify", safe_ref + "^{commit}"], cwd=repo, max_chars=10000)["stdout"]["text"].strip()
    subject = _run([git, "show", "-s", "--format=%s", sha], cwd=repo, max_chars=20000)["stdout"]["text"].strip()
    return {"tool": "git_show_revision", "repo": str(repo), "ref": safe_ref, "revision": sha, "subject": subject}


def codegraph_probe(*, repo_path: str = ".") -> Dict[str, Any]:
    repo = _repo_path(repo_path)
    binary = _resolve_binary("PFC_CODEGRAPH_BIN")
    result = _run([binary, "--help"], cwd=repo, timeout_seconds=30, max_chars=50000)
    return {
        "tool": "codegraph_probe",
        "binary": binary,
        "repo": str(repo),
        "help": result["stdout"],
    }


def _validate_codegraph_args(args: Iterable[str]) -> List[str]:
    values = list(args)
    if not values or len(values) > 32:
        raise ProfessionalToolError("CODEGRAPH_QUERY_ARGS_INVALID")
    first_positional: Optional[str] = None
    expecting_option_value = False
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ProfessionalToolError("CODEGRAPH_QUERY_ARG_INVALID")
        token = value.strip()
        if len(token) > 512 or "\x00" in token or "\n" in token or "\r" in token:
            raise ProfessionalToolError("CODEGRAPH_QUERY_ARG_INVALID")
        lowered = token.lower()
        bare = lowered.lstrip("-").split("=", 1)[0]
        if bare in _CODEGRAPH_FORBIDDEN_TOKENS:
            raise ProfessionalToolError("CODEGRAPH_MUTATING_OPERATION_FORBIDDEN:%s" % bare)
        if token.startswith("-"):
            option = token.split("=", 1)[0]
            if option not in _CODEGRAPH_SAFE_OPTIONS:
                raise ProfessionalToolError("CODEGRAPH_OPTION_NOT_ALLOWED:%s" % option)
            expecting_option_value = "=" not in token and option not in {"--json", "-j"}
            continue
        if expecting_option_value:
            expecting_option_value = False
            continue
        if first_positional is None:
            first_positional = lowered
    if expecting_option_value:
        raise ProfessionalToolError("CODEGRAPH_OPTION_VALUE_MISSING")
    if first_positional is None or first_positional not in _CODEGRAPH_QUERY_VERBS:
        raise ProfessionalToolError("CODEGRAPH_QUERY_VERB_NOT_ALLOWED")
    return [value.strip() for value in values]


def codegraph_query(
    *,
    args: Iterable[str],
    repo_path: str = ".",
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> Dict[str, Any]:
    repo = _repo_path(repo_path)
    binary = _resolve_binary("PFC_CODEGRAPH_BIN")
    safe_args = _validate_codegraph_args(args)
    result = _run(
        [binary] + safe_args,
        cwd=repo,
        timeout_seconds=timeout_seconds,
        max_chars=max_chars,
    )
    return {
        "tool": "codegraph_query",
        "binary": binary,
        "repo": str(repo),
        "args": safe_args,
        "result": result["stdout"],
    }
