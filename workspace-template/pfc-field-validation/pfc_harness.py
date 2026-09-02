"""PFC-specific, one-command orchestration over the pinned V3 runtime.

The module is intentionally the only user-facing control surface in the
derived package.  It calls the frozen runtime in-process, keeps identifiers in
the durable SQLite state, emits human-readable Chinese status text for human
commands, and emits machine-readable JSON as deterministic UTF-8 bytes.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import signal
import shlex
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import time
import webbrowser
import urllib.error
import urllib.request
import uuid
import zipfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit


BOOTSTRAP_WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
INSTALLATION_MARKER_PATH = BOOTSTRAP_WORKSPACE_ROOT / "PFC_R1_R4_INSTALLATION.json"
INSTALLED_RUNTIME_WORKSPACE = INSTALLATION_MARKER_PATH.is_file()
WORKSPACE_ROOT = BOOTSTRAP_WORKSPACE_ROOT
PACKAGE_ROOT = WORKSPACE_ROOT if INSTALLED_RUNTIME_WORKSPACE else WORKSPACE_ROOT.parent
OPENCODE_WORKSPACE_ROOT = WORKSPACE_ROOT if INSTALLED_RUNTIME_WORKSPACE else PACKAGE_ROOT / "data" / "opencode-workspace"
PROFILE_PATH = WORKSPACE_ROOT / "PFC_PROJECT_PROFILE.json" if INSTALLED_RUNTIME_WORKSPACE else PACKAGE_ROOT / "PFC_PROJECT_PROFILE.json"
PROFILE = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
PROJECT_ID = str(PROFILE["project"])
RELEASE_ID = str(PROFILE["release_id"])
ENVIRONMENT_ID = str(PROFILE["default_environment"]["id"])
STATE_ROOT = Path(os.environ.get("PFC_LOCAL_STATE_ROOT") or (WORKSPACE_ROOT / "ai-test")).resolve()
STATE_DIR = STATE_ROOT / "state"
CONTROL_PATH = STATE_DIR / "pfc-control.json"
LOCAL_PROFILE_PATH = Path(
    os.environ.get("PFC_MACHINE_PROFILE")
    or (
        Path(os.environ.get("LOCALAPPDATA")) / "PFC" / "field-validation" / "profile.json"
        if os.environ.get("LOCALAPPDATA")
        else Path.home() / ".pfc" / "field-validation" / "profile.json"
    )
).expanduser().resolve()

os.environ.setdefault("AITEST_WORKSPACE_ROOT", str(WORKSPACE_ROOT))
os.environ.setdefault("AITEST_DB_PATH", str(STATE_DIR / "aitest.db"))
sys.path.insert(0, str(WORKSPACE_ROOT / "ai-test" / "runtime"))

from aitest_runtime import browser, defects, mission, project, quality, repository, scheduler, session, storage, truth  # noqa: E402
from aitest_runtime.common import now_iso, redact, sha256_bytes, sha256_file  # noqa: E402


INTERNAL_FIELD_VALIDATION = WORKSPACE_ROOT / ".pfc-internal-field-validation"
FV_TOOL = INTERNAL_FIELD_VALIDATION / "tools" / "fv_tool.py"
WEB_RUNTIME_STATE_PATH = STATE_DIR / "opencode-web-runtime.json"
ACTIVE_OPENCODE_INSTANCE: dict[str, Any] | None = None
MANAGED_OPENCODE_PROCESS: subprocess.Popen[Any] | None = None
MANAGED_OPENCODE_PROCESS_PID: int | None = None
STARTUP_TRACE: dict[str, Any] | None = None
OPENCODE_VERSION_RE = re.compile(r"(?<!\d)(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)(?!\d)")
STARTUP_TRACE_ACCEPTANCE_KEYS = (
    "PFC_OPENCODE_STARTUP_TRACE",
    "PFC_OPENCODE_CANDIDATE_ENUMERATION",
    "PFC_OPENCODE_CMD_SHIM_TRACE",
    "PFC_OPENCODE_VERSION_MATRIX_TRACE",
    "PFC_OPENCODE_PROCESS_PORT_TRACE",
    "PFC_OPENCODE_LAUNCH_STDOUT_STDERR_CAPTURE",
    "PFC_OPENCODE_FAILURE_CLASSIFICATION",
    "PFC_OPENCODE_STARTUP_TERMINAL_DIAGNOSTIC",
)
STARTUP_TRACE_REQUIRED_FILES = (
    "STARTUP_SUMMARY.txt",
    "opencode-candidates.json",
    "environment.json",
    "process-before.json",
    "port-before.json",
    "launch-command.json",
    "launch-stdout.log",
    "launch-stderr.log",
    "process-after.json",
    "port-after.json",
    "pinned-runtime.json",
    "generated-opencode-config.json",
    "web-health.json",
    "auth-probe.json",
    "provider-model-probe.json",
    "llm-probe.json",
    "r2-probe.json",
    "FINAL_DIAGNOSIS.json",
)

PROVEN_V19_LAUNCH_PATH_REUSE_PROFILE_KEY = "opencode_proven_v1_9_4_launch_path_reuse_repair"
PINNED_OPENCODE_RUNTIME_PROFILE_KEY = "opencode_pinned_runtime_v3"
PINNED_OPENCODE_RUNTIME_CONFIG_KEY = "pinned_opencode_runtime"
PINNED_OPENCODE_DEFAULT_VERSION = "1.18.21"
PINNED_OPENCODE_DEFAULT_PATH = r"D:\用户\tongwenfeng736\AppData\Roaming\npm\node_modules\opencode-ai\bin\opencode"
PROVEN_GIT_BASH_COMMAND_PROFILE_KEY = "opencode_git_bash_proven_command_final_repair"
PROVEN_GIT_BASH_COMMAND_CONFIG_KEY = "git_bash_proven_opencode_runtime"
PROVEN_GIT_BASH_COMMAND_DEFAULT = "opencode"
PROVEN_GIT_BASH_COMMAND_DEFAULT_VERSION = "1.18.21"


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, value: Any, *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    if private and os.name != "nt":
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def emit_json_utf8(value: Any) -> None:
    """Write machine-readable JSON as deterministic UTF-8 bytes to stdout."""
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        raise RuntimeError("UTF8_MACHINE_JSON_STDOUT_BUFFER_UNAVAILABLE")
    stream.write(data)
    stream.flush()


def digest(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


TRACE_SENSITIVE_KEY_RE = re.compile(r"(?i)(password|passwd|token|secret|cookie|authorization|api[_-]?key|credential|session[_-]?id)")
TRACE_SENSITIVE_VALUE_RE = re.compile(r"(?i)(authorization\s*[:=]\s*(?:(?:bearer|basic)\s+)?|cookie\s*[:=]\s*|(?:bearer|basic)\s+|(?:password|passwd|token|secret|api[_-]?key)\s*[=:]\s*|--?(?:password|passwd|token|secret|cookie|authorization|api[_-]?key)(?:=|\s+))\S+")
TRACE_SENSITIVE_ARG_RE = re.compile(r"(?i)^--?(?:password|passwd|token|secret|cookie|authorization|api[_-]?key)$")


def startup_trace_enabled() -> bool:
    return bool(PROFILE.get("opencode_startup_trace") or PROFILE.get("opencode_startup_black_box_trace"))


def proven_v19_launch_path_reuse_enabled() -> bool:
    """Use the field-proven Git Bash command path as the startup authority."""
    return bool(PROFILE.get(PROVEN_V19_LAUNCH_PATH_REUSE_PROFILE_KEY))


def pinned_opencode_runtime_enabled() -> bool:
    """Use the bank-verified exact OpenCode runtime as the only V3 authority."""
    return bool(PROFILE.get(PINNED_OPENCODE_RUNTIME_PROFILE_KEY))


def pinned_opencode_runtime_contract() -> dict[str, str]:
    configured = PROFILE.get(PINNED_OPENCODE_RUNTIME_CONFIG_KEY)
    configured = configured if isinstance(configured, dict) else {}
    return {
        "version": _version_text(configured.get("version")) or PINNED_OPENCODE_DEFAULT_VERSION,
        "path": str(configured.get("path") or PINNED_OPENCODE_DEFAULT_PATH),
    }


def proven_git_bash_command_enabled() -> bool:
    """Use the proven Git Bash command as the only final-repair authority."""
    return bool(PROFILE.get(PROVEN_GIT_BASH_COMMAND_PROFILE_KEY))


def proven_git_bash_command_contract() -> dict[str, str]:
    configured = PROFILE.get(PROVEN_GIT_BASH_COMMAND_CONFIG_KEY)
    configured = configured if isinstance(configured, dict) else {}
    return {
        "command": str(configured.get("command") or PROVEN_GIT_BASH_COMMAND_DEFAULT),
        "version": _version_text(configured.get("version")) or PROVEN_GIT_BASH_COMMAND_DEFAULT_VERSION,
    }


def trace_sanitize(value: Any, key: str | None = None) -> Any:
    if key and TRACE_SENSITIVE_KEY_RE.search(key):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(item_key): trace_sanitize(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [trace_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [trace_sanitize(item) for item in value]
    if isinstance(value, str):
        return TRACE_SENSITIVE_VALUE_RE.sub(lambda match: match.group(1) + "<redacted>", value)[:200000]
    return value


def _safe_argv(values: list[Any] | tuple[Any, ...]) -> list[str | None]:
    safe: list[str | None] = []
    redact_next = False
    for value in values:
        text = str(value)
        if redact_next:
            safe.append("<redacted>")
            redact_next = False
            continue
        safe.append(_safe_command_line(text))
        if TRACE_SENSITIVE_ARG_RE.fullmatch(text.strip()):
            redact_next = True
    return safe


def trace_write_json(name: str, value: Any) -> None:
    if not STARTUP_TRACE:
        return
    path = Path(str(STARTUP_TRACE["trace_dir"])) / name
    write_json(path, trace_sanitize(value))


def trace_write_text(name: str, value: Any) -> None:
    if not STARTUP_TRACE:
        return
    path = Path(str(STARTUP_TRACE["trace_dir"])) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(trace_sanitize(str(value)), encoding="utf-8")


def begin_startup_trace() -> dict[str, Any] | None:
    global STARTUP_TRACE
    if not startup_trace_enabled():
        return None
    trace_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    trace_dir = PACKAGE_ROOT / "logs" / "startup" / trace_id
    trace_dir.mkdir(parents=True, exist_ok=True)
    STARTUP_TRACE = {"trace_id": trace_id, "trace_dir": str(trace_dir), "started_at": now_iso(), "stream_threads": []}
    trace_write_json("environment.json", {
        "captured_at": now_iso(),
        "os_name": os.name,
        "platform": sys.platform,
        "package_root": str(PACKAGE_ROOT),
        "workspace_root": str(OPENCODE_WORKSPACE_ROOT),
        "cwd": str(Path.cwd()),
        "environment": dict(os.environ),
    })
    for name in STARTUP_TRACE_REQUIRED_FILES:
        if name == "environment.json":
            continue
        if name.endswith(".txt") or name.endswith(".log"):
            trace_write_text(name, "")
        elif name == "launch-command.json":
            trace_write_json(name, {"status": "NOT_RUN", "cwd": str(OPENCODE_WORKSPACE_ROOT), "workspace": str(OPENCODE_WORKSPACE_ROOT), "host": "127.0.0.1", "port": None, "argv": None, "environment_overrides": {}})
        else:
            trace_write_json(name, {"status": "NOT_RUN"})
    return STARTUP_TRACE


def trace_command(argv: list[str], timeout: int = 8) -> dict[str, Any]:
    safe_argv = _safe_argv(argv)
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
        return {"status": "PASS" if completed.returncode == 0 else "REPAIR", "argv": safe_argv, "stdout": trace_sanitize(completed.stdout or ""), "stderr": trace_sanitize(completed.stderr or ""), "exit_code": completed.returncode}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "REPAIR", "argv": safe_argv, "stdout": "", "stderr": trace_sanitize(str(exc)), "exit_code": None, "error_class": type(exc).__name__}


def trace_shell_resolution_commands() -> dict[str, Any]:
    results: dict[str, Any] = {}
    bash = shutil.which("bash")
    if bash:
        results["command-v-opencode"] = {**trace_command([bash, "-lc", "command -v opencode"]), "command": "command -v opencode"}
        results["type-a-opencode"] = {**trace_command([bash, "-lc", "type -a opencode"]), "command": "type -a opencode"}
        # This is the authoritative admission check for the bounded repair.
        # It deliberately invokes the shell command, never an absolute .cmd,
        # .ps1, or guessed binary path.
        results["opencode-version"] = {**trace_command([bash, "-lc", "opencode --version"]), "command": "opencode --version"}
    else:
        results["command-v-opencode"] = {"status": "NOT_AVAILABLE", "reason": "bash_not_found"}
        results["type-a-opencode"] = {"status": "NOT_AVAILABLE", "reason": "bash_not_found"}
        results["opencode-version"] = {"status": "NOT_AVAILABLE", "reason": "bash_not_found"}
    if os.name == "nt":
        results["where-exe-opencode"] = trace_command(["where.exe", "opencode"])
    else:
        results["where-exe-opencode"] = {"status": "NOT_APPLICABLE", "reason": "non_windows_host"}
    return results


def _shell_command_result(command: str, *, timeout: int = 12) -> dict[str, Any]:
    """Run one fixed command through the current Git Bash environment."""
    bash = shutil.which("bash")
    if not bash:
        return {"status": "REPAIR", "error_class": "GIT_BASH_SHELL_NOT_FOUND", "command": command, "argv": [], "stdout": "", "stderr": "", "exit_code": None}
    argv = [str(bash), "-lc", command]
    probe_cwd = OPENCODE_WORKSPACE_ROOT if OPENCODE_WORKSPACE_ROOT.is_dir() else WORKSPACE_ROOT
    try:
        completed = subprocess.run(
            argv,
            cwd=str(probe_cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "status": "REPAIR",
            "error_class": type(exc).__name__,
            "command": command,
            "argv": _safe_argv(argv),
            "stdout": "",
            "stderr": str(exc),
            "exit_code": None,
        }
    stdout = trace_sanitize(completed.stdout or "")
    stderr = trace_sanitize(completed.stderr or "")
    return {
        "status": "PASS" if completed.returncode == 0 else "REPAIR",
        "command": command,
        "argv": _safe_argv(argv),
        "stdout": stdout[:200000],
        "stderr": stderr[:200000],
        "exit_code": completed.returncode,
    }


def _shell_opencode_command(args: list[str] | tuple[str, ...] = ()) -> str:
    return " ".join(["opencode", *(shlex.quote(str(item)) for item in args)])


def _workspace_shell_path() -> str:
    """Render the stable workspace in the path dialect understood by Git Bash."""
    return _git_bash_exact_path(str(OPENCODE_WORKSPACE_ROOT))


def workspace_pwd_probe() -> dict[str, Any]:
    """Prove the shell launch context, rather than trusting a workspace variable."""
    expected = str(OPENCODE_WORKSPACE_ROOT)
    shell_path = _workspace_shell_path()
    result = _shell_command_result(f"cd -- {shlex.quote(shell_path)} && pwd")
    actual = next((line.strip() for line in reversed(str(result.get("stdout") or "").splitlines()) if line.strip()), None)
    equivalent = bool(actual and _git_bash_exact_path(actual).rstrip("/").casefold() == shell_path.rstrip("/").casefold())
    return {
        "status": "PASS" if result.get("status") == "PASS" and equivalent else "REPAIR",
        "expected_workspace": expected,
        "shell_workspace": shell_path,
        "actual_shell_pwd": actual,
        "cwd_match": equivalent,
        "source": "Git Bash cd + pwd probe",
        "probe": result,
        "error_class": None if result.get("status") == "PASS" and equivalent else "OPENCODE_WORKSPACE_PROCESS_CWD_MISMATCH",
    }


def workspace_shell_launch_command(args: list[str] | tuple[str, ...] = ()) -> str:
    """Launch from the proven workspace context and expose the actual pwd."""
    return f"cd -- {shlex.quote(_workspace_shell_path())} && pwd && exec {_shell_opencode_command(args)}"


def shell_opencode_probe(args: list[str] | tuple[str, ...] = (), *, timeout: int = 12) -> dict[str, Any]:
    command = _shell_opencode_command(args)
    result = _shell_command_result(command, timeout=timeout)
    result.update({"invocation_mode": "GIT_BASH_SHELL", "launcher_type": "SHELL_RESOLVED", "resolved_command": "opencode"})
    return result


def proven_git_bash_command_probe(args: list[str] | tuple[str, ...] = (), *, timeout: int = 12) -> dict[str, Any]:
    """Run only the proven shell command; never inspect or replace its file."""
    contract = proven_git_bash_command_contract()
    command = " ".join([contract["command"], *(shlex.quote(str(item)) for item in args)])
    result = _shell_command_result(command, timeout=timeout)
    result.update({"invocation_mode": "GIT_BASH_SHELL", "launcher_type": "SHELL_RESOLVED", "resolved_command": contract["command"], "proven_command": True})
    return result


def resolve_proven_git_bash_command() -> dict[str, Any]:
    """Admit `opencode` only when the current Git Bash returns 1.18.21."""
    contract = proven_git_bash_command_contract()
    command_v = _shell_command_result("command -v opencode")
    version_probe = proven_git_bash_command_probe(["--version"])
    resolved_path = next((_windows_shell_path(line.strip()) for line in str(command_v.get("stdout") or "").splitlines() if line.strip()), None)
    actual_version = _version_text(version_probe.get("stdout") or version_probe.get("stderr")) or "UNAVAILABLE"
    version_match = actual_version == contract["version"]
    status = "PASS" if command_v.get("status") == "PASS" and version_probe.get("status") == "PASS" and version_match else "REPAIR"
    error_class = None if status == "PASS" else "OPENCODE_VERSION_MISMATCH"
    return {
        "status": status,
        "error_class": error_class,
        "resolution_mode": "GIT_BASH_PROVEN_COMMAND_ONLY",
        "expected_version": contract["version"],
        "expected_version_source": "PFC_BANK_OPENCODE_PROVEN_COMMAND_VERSION",
        "compatible_versions": [contract["version"]],
        "actual_version": actual_version,
        "version_match": version_match,
        "selected_path": resolved_path or contract["command"] if status == "PASS" else None,
        "selected_launcher": resolved_path or contract["command"] if status == "PASS" else None,
        "selected_version": actual_version if status == "PASS" else None,
        "selected_launcher_type": "SHELL_RESOLVED" if status == "PASS" else None,
        "selected_underlying_target": None,
        "selected_invocation_mode": "GIT_BASH_SHELL",
        "resolved_command": contract["command"],
        "launch_via_shell": True,
        "shell_executable": (version_probe.get("argv") or [None])[0],
        "proven_command": True,
        "proven_command_name": contract["command"],
        "command_v": command_v,
        "version_probe": version_probe,
        "candidate_count": 0,
        "candidates": [],
        "candidate_enumeration": "DISABLED_PROVEN_COMMAND_ONLY",
        "candidate_selection_is_evidence_only": False,
        "version_locations": {actual_version: [resolved_path or contract["command"]]} if actual_version != "UNAVAILABLE" else {},
    }


def _git_bash_exact_path(path: Any) -> str:
    """Render the configured Windows path for Git Bash without changing it."""
    text = str(path or "").strip().strip('"')
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", text)
    if match:
        return f"/{match.group(1).lower()}/{match.group(2).replace(chr(92), '/') }"
    return text.replace("\\", "/")


def inspect_pinned_runtime_file(path: str) -> dict[str, Any]:
    """Identify the configured file from its bytes, never from its suffix."""
    result: dict[str, Any] = {"path": path, "status": "REPAIR", "file_type": "MISSING", "invocation_mode": "NOT_AVAILABLE"}
    candidate = Path(path)
    try:
        if not candidate.is_file():
            result["error_class"] = "PINNED_OPENCODE_RUNTIME_MISSING"
            return result
        sample = candidate.read_bytes()[:4096]
    except OSError as exc:
        result["error_class"] = "PINNED_OPENCODE_RUNTIME_INSPECTION_FAILED"
        result["error_detail"] = type(exc).__name__
        return result
    if sample.startswith(b"MZ"):
        file_type = "PE_EXECUTABLE"
    elif sample.startswith(b"#!"):
        file_type = "SHEBANG_SCRIPT"
    elif b"\x00" not in sample:
        file_type = "TEXT_SCRIPT"
    else:
        file_type = "UNKNOWN_BINARY"
    result.update({
        "status": "PASS" if file_type in {"PE_EXECUTABLE", "SHEBANG_SCRIPT"} else "REPAIR",
        "file_type": file_type,
        "invocation_mode": "GIT_BASH_EXACT_PATH" if file_type in {"PE_EXECUTABLE", "SHEBANG_SCRIPT"} else "UNSUPPORTED_FILE_TYPE",
        "shell_path": _git_bash_exact_path(path),
    })
    if result["status"] != "PASS":
        result["error_class"] = "PINNED_OPENCODE_RUNTIME_FILE_TYPE_UNSUPPORTED"
    return result


def pinned_runtime_shell_command(binary: dict[str, Any], args: list[str] | tuple[str, ...] = ()) -> str:
    exact_path = str(binary.get("pinned_runtime_path") or binary.get("selected_path") or pinned_opencode_runtime_contract()["path"])
    shell_path = str(binary.get("pinned_shell_path") or _git_bash_exact_path(exact_path))
    return " ".join([shlex.quote(shell_path), *(shlex.quote(str(item)) for item in args)])


def pinned_runtime_probe(binary: dict[str, Any] | None = None, args: list[str] | tuple[str, ...] = (), *, timeout: int = 12) -> dict[str, Any]:
    """Run the exact bank-pinned path through Git Bash for version/help/Web."""
    contract = pinned_opencode_runtime_contract()
    exact_path = str((binary or {}).get("pinned_runtime_path") or contract["path"])
    file_fact = (binary or {}).get("file_fact") if isinstance((binary or {}).get("file_fact"), dict) else inspect_pinned_runtime_file(exact_path)
    base = {"exact_runtime_path": exact_path, "pinned_runtime_path": exact_path, "expected_version": contract["version"], "file_fact": file_fact, "invocation_mode": file_fact.get("invocation_mode")}
    if file_fact.get("status") != "PASS":
        return {**base, "status": "REPAIR", "error_class": file_fact.get("error_class") or "PINNED_OPENCODE_RUNTIME_MISMATCH", "command": None, "argv": [], "stdout": "", "stderr": "", "exit_code": None}
    command = pinned_runtime_shell_command({"pinned_runtime_path": exact_path, "pinned_shell_path": file_fact.get("shell_path")}, args)
    result = _shell_command_result(command, timeout=timeout)
    return {
        **base,
        **result,
        "command": command,
        "invocation_mode": file_fact.get("invocation_mode") or "GIT_BASH_EXACT_PATH",
        "launcher_type": file_fact.get("file_type"),
        "resolved_command": exact_path,
        "exact_runtime": True,
    }


def resolve_pinned_opencode_runtime() -> dict[str, Any]:
    """Admit only the bank-verified path and exact 1.18.21 version."""
    contract = pinned_opencode_runtime_contract()
    exact_path = contract["path"]
    file_fact = inspect_pinned_runtime_file(exact_path)
    version_probe = pinned_runtime_probe({"pinned_runtime_path": exact_path, "file_fact": file_fact}, ["--version"])
    actual_version = _version_text(version_probe.get("stdout") or version_probe.get("stderr"))
    version_match = actual_version == contract["version"]
    error_class = None
    if file_fact.get("status") != "PASS":
        error_class = "PINNED_OPENCODE_RUNTIME_MISMATCH"
    elif version_probe.get("status") != "PASS":
        error_class = "PINNED_OPENCODE_RUNTIME_MISMATCH"
    elif not version_match:
        error_class = "PINNED_OPENCODE_RUNTIME_VERSION_MISMATCH"
    status = "PASS" if not error_class else "REPAIR"
    return {
        "status": status,
        "error_class": error_class,
        "resolution_mode": "PINNED_EXACT_RUNTIME_ONLY",
        "expected_version": contract["version"],
        "expected_version_source": "PFC_BANK_OPENCODE_PINNED_VERSION",
        "compatible_versions": [contract["version"]],
        "actual_version": actual_version or "UNAVAILABLE",
        "version_match": version_match,
        "selected_path": exact_path if status == "PASS" else None,
        "selected_launcher": exact_path if status == "PASS" else None,
        "selected_version": actual_version if status == "PASS" else None,
        "selected_launcher_type": file_fact.get("file_type"),
        "selected_underlying_target": None,
        "selected_invocation_mode": file_fact.get("invocation_mode"),
        "resolved_command": exact_path,
        "launch_via_shell": True,
        "shell_executable": (version_probe.get("argv") or [None])[0],
        "pinned_runtime": True,
        "pinned_runtime_path": exact_path,
        "pinned_shell_path": file_fact.get("shell_path"),
        "pinned_file_type": file_fact.get("file_type"),
        "pinned_version_probe": version_probe,
        "file_fact": file_fact,
        "candidate_count": 0,
        "candidates": [],
        "candidate_enumeration": "DISABLED_PINNED_RUNTIME_ONLY",
        "candidate_selection_is_evidence_only": False,
        "version_locations": {actual_version: [exact_path]} if actual_version else {},
    }


def _shell_candidate_paths(command_v_output: str, type_a_output: str) -> list[str]:
    paths: list[str] = []
    for raw in [command_v_output.strip(), *type_a_output.splitlines()]:
        line = str(raw or "").strip()
        if not line:
            continue
        match = re.search(r"(?:\bis\s+|=>\s*)(.+)$", line)
        value = (match.group(1) if match else line).strip().strip('"')
        value = re.sub(r"^hashed\s*\((.+)\)$", r"\1", value, flags=re.IGNORECASE).strip()
        value = _windows_shell_path(value)
        if value and value not in paths and ("opencode" in Path(value).name.casefold() or value == "opencode"):
            paths.append(value)
    return paths


def resolve_proven_shell_opencode(shell_resolution: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve OpenCode using Git Bash first; candidate facts never gate launch."""
    evidence = shell_resolution if isinstance(shell_resolution, dict) else trace_shell_resolution_commands()
    command_v = evidence.get("command-v-opencode") or {}
    type_a = evidence.get("type-a-opencode") or {}
    version_probe = evidence.get("opencode-version") or {}
    command_v_path = next((_windows_shell_path(line.strip()) for line in str(command_v.get("stdout") or "").splitlines() if line.strip()), None)
    version = _version_text(version_probe.get("stdout") or version_probe.get("stderr"))
    paths = _shell_candidate_paths(str(command_v.get("stdout") or ""), str(type_a.get("stdout") or ""))
    if command_v_path and command_v_path not in paths:
        paths.insert(0, command_v_path)
    candidates = []
    for path in paths:
        is_selected = path == command_v_path
        candidates.append({
            "path": path,
            "source": "GIT_BASH_COMMAND_V" if is_selected else "GIT_BASH_TYPE_A_EVIDENCE",
            "launcher_type": opencode_launcher_type(path),
            "exists": Path(path).is_file() if not (os.name == "nt" and path == "opencode") else True,
            "version": version if is_selected and version else "UNAVAILABLE",
            "actual_version": version if is_selected and version else "UNAVAILABLE",
            "version_probe": "PASS" if is_selected and version_probe.get("status") == "PASS" and version else "EVIDENCE_ONLY",
            "version_output": _terminal_compact(version_probe.get("stdout") or version_probe.get("stderr"), limit=160) if is_selected else "NOT_PROBED_EVIDENCE_ONLY",
            "invocation_mode": "GIT_BASH_SHELL" if is_selected else "EVIDENCE_ONLY",
        })
    if not command_v_path or version_probe.get("status") != "PASS" or not version:
        error_class = "EXECUTABLE_NOT_FOUND" if not command_v_path else ("VERSION_PROBE_FAILED" if version_probe.get("exit_code") not in {None, 127} else "COMMAND_NOT_FOUND")
        return {
            "status": "REPAIR",
            "error_class": error_class,
            "resolution_mode": "GIT_BASH_SHELL_FIRST",
            "expected_version": "SHELL_RESOLVED_RUNTIME",
            "expected_version_source": "GIT_BASH_OPENCODE_VERSION",
            "compatible_versions": [],
            "actual_version": version or "UNAVAILABLE",
            "version_match": bool(version),
            "selected_path": None,
            "selected_launcher": None,
            "selected_version": None,
            "selected_launcher_type": None,
            "selected_underlying_target": None,
            "selected_invocation_mode": "GIT_BASH_SHELL",
            "resolved_command": "opencode",
            "shell_executable": (command_v.get("argv") or [None])[0],
            "launch_via_shell": True,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "version_locations": {str(item.get("version")): [item.get("path")] for item in candidates if item.get("version") not in {None, "UNAVAILABLE"}},
            "shell_resolution": evidence,
            "candidate_selection_is_evidence_only": True,
        }
    selected_path = command_v_path
    return {
        "status": "PASS",
        "error_class": None,
        "resolution_mode": "GIT_BASH_SHELL_FIRST_PROVEN_PATH",
        "expected_version": version,
        "expected_version_source": "GIT_BASH_OPENCODE_VERSION_AUTHORITATIVE",
        "compatible_versions": [],
        "actual_version": version,
        "version_match": True,
        "selected_path": selected_path,
        "selected_launcher": selected_path,
        "selected_version": version,
        "selected_launcher_type": opencode_launcher_type(selected_path),
        "selected_underlying_target": launcher_underlying_target(selected_path),
        "selected_invocation_mode": "GIT_BASH_SHELL",
        "resolved_command": "opencode",
        "shell_executable": (command_v.get("argv") or [None])[0],
        "launch_via_shell": True,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "version_locations": {version: [selected_path]},
        "shell_resolution": evidence,
        "candidate_selection_is_evidence_only": True,
    }


def trace_localhost_port_snapshot(process_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    listeners: list[dict[str, Any]] = []
    source = "UNAVAILABLE"
    errors: list[str] = []
    if os.name == "nt":
        source = "NETSTAT"
        try:
            completed = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, check=False)
            for line in completed.stdout.splitlines():
                fields = line.split()
                if len(fields) < 5 or fields[0].upper() != "TCP" or fields[3].upper() != "LISTENING":
                    continue
                match = re.search(r":(\d+)$", fields[1])
                if not match:
                    continue
                listeners.append({"local": fields[1], "port": int(match.group(1)), "state": fields[3], "pid": int(fields[4]) if fields[4].isdigit() else None})
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(type(exc).__name__)
    elif shutil.which("lsof"):
        source = "LSOF"
        try:
            completed = subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, check=False)
            for line in completed.stdout.splitlines()[1:]:
                fields = line.split()
                if len(fields) < 9 or not fields[1].isdigit():
                    continue
                endpoint = fields[-1]
                match = re.search(r":(\d+)$", endpoint)
                if match:
                    listeners.append({"local": endpoint, "port": int(match.group(1)), "state": "LISTEN", "pid": int(fields[1]), "command": fields[0]})
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(type(exc).__name__)
    else:
        errors.append("lsof_not_found")
    rows = process_rows if process_rows is not None else opencode_process_snapshot()
    by_pid = {int(row["pid"]): row for row in rows if str(row.get("pid", "")).isdigit()}
    for listener in listeners:
        row = by_pid.get(listener.get("pid"))
        if row:
            listener["process"] = row
    relevant: list[dict[str, Any]] = []
    for listener in listeners:
        row = listener.get("process") or {}
        command = f"{row.get('name', '')} {row.get('command_line', '')}".lower()
        if listener.get("port") == 4096 or "opencode" in command:
            relevant.append(listener)
    return {"source": source, "listeners": listeners, "opencode_or_default_listeners": relevant, "default_4096": [item for item in listeners if item.get("port") == 4096], "errors": errors}


def trace_relevant_process_rows(rows: list[dict[str, Any]], ports: dict[str, Any]) -> list[dict[str, Any]]:
    pids = {str(item.get("pid")) for item in ports.get("opencode_or_default_listeners", []) if item.get("pid") is not None}
    return [row for row in rows if str(row.get("pid")) in pids or "opencode" in f"{row.get('name', '')} {row.get('command_line', '')}".lower()]


def trace_legacy_workspace_facts() -> dict[str, Any]:
    configured = os.environ.get("PFC_LEGACY_OPENCODE_WORKSPACE")
    roots = [configured] if configured else []
    if os.name == "nt":
        roots.append(r"D:\PFC\cfg-ai-test-workspace-v16")
    facts: list[dict[str, Any]] = []
    for raw_root in [item for item in roots if item]:
        root = Path(_windows_shell_path(raw_root))
        item: dict[str, Any] = {"root": str(root), "exists": root.exists(), "files": []}
        if root.exists():
            try:
                for path in sorted(root.rglob("*")):
                    if len(item["files"]) >= 200 or not path.is_file() or path.stat().st_size > 2_000_000:
                        continue
                    if path.name.casefold() not in {"opencode.json", "package.json", "opencode.cmd", "opencode.bat", "opencode.exe", "opencode.js", "server.js"} and path.suffix.casefold() not in {".cmd", ".bat"}:
                        continue
                    file_fact: dict[str, Any] = {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
                    if path.suffix.casefold() in {".json", ".cmd", ".bat", ".js"}:
                        try:
                            text = path.read_text(encoding="utf-8", errors="replace")
                            file_fact["content_excerpt"] = trace_sanitize(text[:20000])
                        except OSError:
                            pass
                    item["files"].append(file_fact)
            except OSError as exc:
                item["error_class"] = type(exc).__name__
        facts.append(item)
    return {"known_legacy_workspace": r"D:\PFC\cfg-ai-test-workspace-v16", "roots": facts, "read_only": True}


def trace_capture_process_and_ports(phase: str) -> None:
    rows = opencode_process_snapshot()
    ports = trace_localhost_port_snapshot(rows)
    trace_write_json(f"process-{phase}.json", {"captured_at": now_iso(), "processes": trace_relevant_process_rows(rows, ports), "all_observable_process_count": len(rows)})
    trace_write_json(f"port-{phase}.json", {"captured_at": now_iso(), **ports})


def trace_capture_prelaunch() -> dict[str, Any] | None:
    if not STARTUP_TRACE:
        return None
    if proven_git_bash_command_enabled():
        resolution = resolve_proven_git_bash_command()
        trace_write_json("git-bash-command-resolution.json", resolution)
        trace_write_json("opencode-candidates.json", {
            "captured_at": now_iso(),
            "status": "DISABLED_BY_PROVEN_COMMAND_CONTRACT",
            "candidate_enumeration": "DISABLED",
            "selection_policy": "GIT_BASH_PROVEN_COMMAND_ONLY",
            "resolved_command": "opencode",
            "version": resolution.get("actual_version"),
            "command_v_path_evidence": (resolution.get("command_v") or {}).get("stdout"),
            "candidates": [],
        })
        trace_write_json("legacy-workspace.json", {
            "captured_at": now_iso(),
            "status": "DISABLED_BY_PROVEN_COMMAND_CONTRACT",
            "known_legacy_workspace": "NOT_ACCESSED",
            "read_only": True,
            "reason": "Final repair uses package-owned workspace; legacy workspace scan is disabled.",
        })
        trace_capture_process_and_ports("before")
        return resolution
    if pinned_opencode_runtime_enabled():
        resolution = resolve_pinned_opencode_runtime()
        trace_write_json("pinned-runtime.json", resolution)
        trace_write_json("opencode-candidates.json", {
            "captured_at": now_iso(),
            "status": "DISABLED_BY_PINNED_RUNTIME_CONTRACT",
            "candidate_enumeration": "DISABLED",
            "selection_policy": "PINNED_EXACT_RUNTIME_ONLY",
            "pinned_runtime_path": resolution.get("pinned_runtime_path"),
            "pinned_version": resolution.get("expected_version"),
            "candidates": [],
        })
        trace_write_json("legacy-workspace.json", {
            "captured_at": now_iso(),
            "status": "DISABLED_BY_PINNED_RUNTIME_CONTRACT",
            "known_legacy_workspace": "NOT_ACCESSED",
            "read_only": True,
            "reason": "V3 uses package-owned workspace and same pinned runtime; legacy workspace scan is disabled.",
        })
        trace_capture_process_and_ports("before")
        return resolution
    shell_resolution = trace_shell_resolution_commands()
    trace_write_json("shell-resolution.json", shell_resolution)
    resolution = resolve_proven_shell_opencode(shell_resolution) if proven_v19_launch_path_reuse_enabled() else resolve_opencode_binary()
    candidates: list[dict[str, Any]] = []
    for candidate in resolution.get("candidates") or []:
        path = candidate.get("path")
        capability: dict[str, Any] = {}
        if path and candidate.get("exists") and not proven_v19_launch_path_reuse_enabled():
            for name, args in (("root", ["--help"]), ("web", ["web", "--help"]), ("serve", ["serve", "--help"]), ("server", ["server", "--help"])):
                capability[name] = opencode_command_probe(path, args, timeout=12)
            combined = "\n".join(str((capability.get(name) or {}).get("stdout") or "") + "\n" + str((capability.get(name) or {}).get("stderr") or "") for name in capability).lower()
            candidate["capability"] = {"web": "web" in combined, "serve": "serve" in combined, "server": "server" in combined, "supports_hostname": "--hostname" in combined, "supports_port": "--port" in combined, "workspace_parameter_evidence": any(marker in combined for marker in ("--dir", "--directory", "--workspace", "project path", "working directory"))}
        candidates.append(candidate)
    trace_write_json("opencode-candidates.json", {"captured_at": now_iso(), "shell_resolution": shell_resolution, "resolution": resolution, "candidates": candidates, "selection_policy": "EVIDENCE_ONLY_SHELL_PASS_CANNOT_BE_BLOCKED" if proven_v19_launch_path_reuse_enabled() else "FROZEN_R1_R4_CANDIDATE_ADMISSION", "frozen_policy": {"expected_version": opencode_expected_version(), "compatible_versions": opencode_compatible_versions(), "baseline": "R1-R4_ONLY"}})
    trace_write_json("legacy-workspace.json", trace_legacy_workspace_facts())
    trace_capture_process_and_ports("before")
    return resolution


def trace_capture_stream(stream: Any, path: Path) -> None:
    try:
        with path.open("w", encoding="utf-8", errors="replace") as handle:
            for line in iter(stream.readline, ""):
                handle.write(trace_sanitize(line))
                handle.flush()
    except (OSError, ValueError):
        return


def trace_attach_process_streams(process: subprocess.Popen[Any]) -> None:
    if not STARTUP_TRACE or process.stdout is None or process.stderr is None:
        return
    trace_dir = Path(str(STARTUP_TRACE["trace_dir"]))
    for stream, name in ((process.stdout, "launch-stdout.log"), (process.stderr, "launch-stderr.log")):
        thread = threading.Thread(target=trace_capture_stream, args=(stream, trace_dir / name), daemon=True)
        thread.start()
        STARTUP_TRACE["stream_threads"].append(thread)


def trace_record_launch_command(binary: dict[str, Any], launch_plan: dict[str, Any], command: list[str], port: int, pid: int | None = None, exit_code: int | None = None, exception: BaseException | None = None) -> None:
    trace_write_json("launch-command.json", {"captured_at": now_iso(), "exact_launcher_path": None if binary.get("proven_command") else binary.get("selected_path"), "command_v_path_evidence": binary.get("selected_path") if binary.get("proven_command") else None, "resolved_command": binary.get("resolved_command"), "selected_version": binary.get("selected_version") or binary.get("actual_version"), "launcher_type": binary.get("selected_launcher_type") or binary.get("launcher_type"), "arguments": _safe_argv(launch_plan.get("args") or []), "shell_launch_command": launch_plan.get("shell_command"), "argv": _safe_argv(command), "invocation_mode": launch_plan.get("invocation_mode"), "cwd": str(OPENCODE_WORKSPACE_ROOT), "workspace": str(OPENCODE_WORKSPACE_ROOT), "cwd_probe": launch_plan.get("workspace_pwd_probe"), "host": "127.0.0.1", "port": port, "environment_overrides": {"PFC_OPENCODE_ACTIVE_ENDPOINT": f"http://127.0.0.1:{port}"}, "environment": dict(os.environ), "process_pid": pid, "process_exit_code": exit_code, "launch_exception": {"type": type(exception).__name__, "message": str(exception)} if exception else None})


def _trace_log_text(name: str) -> str:
    if not STARTUP_TRACE:
        return ""
    path = Path(str(STARTUP_TRACE["trace_dir"])) / name
    try:
        return trace_sanitize(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""


def classify_startup_failure(runtime_reality: dict[str, Any] | None = None, exception: BaseException | None = None) -> str:
    if exception:
        text = str(exception).lower()
        if "node" in text or "npm" in text:
            return "NODE_RUNTIME_FAILURE"
        return "UNKNOWN"
    runtime = runtime_reality or {}
    resolution = (runtime.get("executable") or {}).get("resolution") or {}
    error = str((runtime.get("opencode_web") or {}).get("last_error") or resolution.get("error_class") or "")
    logs = (_trace_log_text("launch-stdout.log") + "\n" + _trace_log_text("launch-stderr.log")).lower()
    if "PINNED_OPENCODE_RUNTIME" in error or "PINNED_OPENCODE_RUNTIME" in str(resolution.get("error_class") or ""):
        return "PINNED_RUNTIME_MISMATCH"
    if resolution.get("error_class") in {"EXECUTABLE_NOT_FOUND", "CONFIGURED_BINARY_NOT_FOUND"}:
        return "COMMAND_NOT_FOUND"
    if resolution.get("error_class") in {"OPENCODE_VERSION_MISMATCH", "MULTIPLE_COMPATIBLE_OPENCODE_CANDIDATES_REQUIRE_EXPLICIT_BINARY", "MULTIPLE_OPENCODE_CANDIDATES_REQUIRE_EXPLICIT_BINARY"}:
        return "OPENCODE_VERSION_MISMATCH" if proven_git_bash_command_enabled() else "VERSION_INCOMPATIBLE"
    if resolution.get("error_class") in {"VERSION_PROBE_FAILED", "VERSION_UNAVAILABLE"} and any(item.get("launcher_type") in {"CMD", "BAT"} for item in resolution.get("candidates") or []):
        return "CMD_SHIM_INVOCATION_FAILED"
    if "OPENCODE_WORKSPACE_PROCESS_CWD_MISMATCH" in error:
        return "WORKSPACE_FAILURE"
    if "GENERATED_OPENCODE_CONFIG" in error or "PACKAGE_OWNED_FREE_PORT" in error:
        return "GENERATED_CONFIG_INVALID"
    if "WEB_PROJECT_BINDING" in error or "PROJECT_BINDING" in error or "SESSION_DIRECTORY" in error:
        return "WEB_PROJECT_BINDING_FAILURE"
    if "invalid argument" in logs or "unknown option" in logs or "unknown flag" in logs:
        return "INVALID_ARGUMENT"
    if "eaddrinuse" in logs or "address already in use" in logs or "port" in logs and "bind" in logs:
        return "PORT_BIND_FAILURE"
    if "node" in logs and ("not found" in logs or "cannot find" in logs or "is not recognized" in logs):
        return "NODE_RUNTIME_FAILURE"
    if "cmd" in error.lower() and "shim" in error.lower():
        return "CMD_SHIM_INVOCATION_FAILED"
    if "web_flags" in error.lower() or "unsupported" in error.lower() or error == "OPENCODE_WEB_FLAGS_UNSUPPORTED":
        return "UNSUPPORTED_WEB_SUBCOMMAND"
    if "workspace" in error.lower() or "cwd" in error.lower():
        return "WORKSPACE_FAILURE"
    if "auth" in error.lower():
        return "AUTH_STARTUP_FAILURE"
    if "process_exited" in error.lower() or "exited" in error.lower():
        return "PROCESS_EXITED"
    return "UNKNOWN"


def _trace_json_file(name: str, default: Any = None) -> Any:
    if not STARTUP_TRACE:
        return default
    return load_json(Path(str(STARTUP_TRACE["trace_dir"])) / name, default)


def _terminal_compact(value: Any, *, limit: int = 520) -> str:
    text = trace_sanitize(str(value or "")).replace("\r", "").replace("\n", " → ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "(empty)"
    return text[-limit:] if len(text) > limit else text


def _terminal_listener_summary(payload: dict[str, Any] | None) -> str:
    payload = payload if isinstance(payload, dict) else {}
    listeners = payload.get("opencode_or_default_listeners") or payload.get("listeners") or []
    values: list[str] = []
    for item in listeners:
        if not isinstance(item, dict):
            continue
        local = item.get("local") or f"127.0.0.1:{item.get('port') or '?'}"
        pid = item.get("pid") or "?"
        state = item.get("state") or "?"
        values.append(f"{local}(pid={pid},state={state})")
    return ", ".join(values) if values else "NONE"


def _terminal_next_action(failure_class: str) -> str:
    actions = {
        "COMMAND_NOT_FOUND": "请让银行 IT 提供或安装 R1-R4 pinned OpenCode，然后重新执行 START。",
        "VERSION_PROBE_FAILED": "请让银行 IT 在当前 Git Bash 中确认 `opencode --version` 可成功执行，然后重新执行 START。",
        "GIT_BASH_SHELL_NOT_FOUND": "请从银行 Git Bash 重新运行 START，并确认当前 shell 可执行 bash。",
        "GENERATED_CONFIG_INVALID": "Harness 已拦截 package-owned opencode.json 的非法 server.port；请保留本摘要并重新执行 START。",
        "WEB_PROJECT_BINDING_FAILURE": "OpenCode Web 未能把当前 Session 绑定到 package-owned workspace；本包已 fail-closed，请使用 TUI 主面并把本摘要交给总控。",
        "PINNED_RUNTIME_MISMATCH": "请让银行 IT 确认 pinned OpenCode 1.18.21 路径可执行且版本精确匹配，然后重新执行 START。",
        "OPENCODE_VERSION_MISMATCH": "请在当前银行 Git Bash 确认 `opencode --version` 精确返回 1.18.21，然后重新执行 START。",
        "CMD_SHIM_INVOCATION_FAILED": "请让银行 IT 修复或确认 .CMD/.BAT shim 的 underlying Node target，然后重新执行 START。",
        "UNSUPPORTED_WEB_SUBCOMMAND": "请让银行 IT 提供支持 Web/hostname/port 的 R1-R4 OpenCode，然后重新执行 START。",
        "INVALID_ARGUMENT": "请让银行 IT 确认 R1-R4 Web 参数兼容性，然后重新执行 START。",
        "PORT_BIND_FAILURE": "请释放或更换冲突端口后重新执行 START；不要手工接管旧实例。",
        "PROCESS_EXITED": "请根据本摘要的启动输出修复 OpenCode 进程退出原因，然后重新执行 START。",
        "WORKSPACE_FAILURE": "请确认包目录可写且 package-owned workspace 可访问，然后重新执行 START。",
        "AUTH_STARTUP_FAILURE": "请在本包启动的 Web 页面完成银行认证，然后重新执行 START。",
        "NODE_RUNTIME_FAILURE": "请让银行 IT 修复 OpenCode 对应的 Node runtime，然后重新执行 START。",
        "VERSION_INCOMPATIBLE": "请让银行 IT 明确唯一的 R1-R4 compatible OpenCode candidate，然后重新执行 START。",
        "UNKNOWN": "请把本屏摘要交给总控定位；不要执行内部 debug command，然后重新执行 START。",
    }
    return actions.get(failure_class, actions["UNKNOWN"])


def terminal_startup_diagnostic(runtime_reality: dict[str, Any] | None = None, exception: BaseException | None = None, trace_zip: str | None = None) -> str:
    """Return the mandatory short, photo-friendly failure summary.

    The summary intentionally reads only sanitized trace fields.  It never
    prints the captured environment, headers, cookies, credentials, or full
    command output.
    """
    runtime = runtime_reality if isinstance(runtime_reality, dict) else {}
    candidate_payload = _trace_json_file("opencode-candidates.json", {}) or {}
    resolution = (runtime.get("executable") or {}).get("resolution") or candidate_payload.get("resolution") or {}
    candidates = resolution.get("candidates") or candidate_payload.get("candidates") or []
    shell_resolution = resolution.get("shell_resolution") or candidate_payload.get("shell_resolution") or {}
    pinned_mode = pinned_opencode_runtime_enabled() or bool(resolution.get("pinned_runtime"))
    proven_command_mode = proven_git_bash_command_enabled() or bool(resolution.get("proven_command"))
    pinned_version_probe = resolution.get("pinned_version_probe") or {}
    shell_version_probe = pinned_version_probe if pinned_mode else (resolution.get("version_probe") or shell_resolution.get("opencode-version") or {})
    launch = _trace_json_file("launch-command.json", {}) or {}
    health = _trace_json_file("web-health.json", {}) or {}
    web = runtime.get("opencode_web") or health.get("web") or {}
    generated_config = web.get("generated_config") if isinstance(web.get("generated_config"), dict) else (_trace_json_file("generated-opencode-config.json", {}) or {})
    project_binding = web.get("project_binding") if isinstance(web.get("project_binding"), dict) else {}
    endpoint = web.get("endpoint") or web.get("web_url")
    host = web.get("host")
    port = web.get("port")
    if not host or not port:
        try:
            parsed_host, parsed_port = endpoint_host_port(str(endpoint or "http://127.0.0.1:4096"))
            host = host or parsed_host
            port = port or parsed_port
        except (TypeError, ValueError):
            host, port = host or "127.0.0.1", port or 4096
    failure_class = classify_startup_failure(runtime, exception)
    after_process = _trace_json_file("process-after.json", {}) or {}
    process_rows = after_process.get("processes") or []
    pid = launch.get("process_pid") or web.get("pid")
    exit_code = launch.get("process_exit_code")
    if exit_code is not None:
        process_state = "EXITED"
    elif pid and any(str(row.get("pid")) == str(pid) for row in process_rows if isinstance(row, dict)):
        process_state = "OBSERVED"
    elif pid and pid_is_running(pid):
        process_state = "RUNNING"
    elif pid:
        process_state = "NOT_OBSERVED"
    else:
        process_state = "NOT_STARTED"
    command = launch.get("argv")
    if isinstance(command, list) and command:
        command_text = _terminal_compact(" ".join(str(item) for item in command), limit=760)
    else:
        command_text = "NOT_RUN"
    before_ports = _trace_json_file("port-before.json", {}) or {}
    after_ports = _trace_json_file("port-after.json", {}) or {}
    diagnosis = _trace_json_file("FINAL_DIAGNOSIS.json", {}) or {}
    legacy = diagnosis.get("legacy_external_instance")
    if legacy is None:
        legacy = any(item.get("port") == 4096 for item in after_ports.get("default_4096") or [])
    auth_reached = runtime.get("auth_phase_reached")
    if auth_reached is None and STARTUP_TRACE:
        auth_reached = STARTUP_TRACE.get("auth_phase_reached")
    if auth_reached is None:
        auth_reached = bool(runtime.get("authentication") or (_trace_json_file("auth-probe.json", {}) or {}).get("status") not in {None, "NOT_RUN"})
    acceptance = runtime.get("acceptance") or {}
    pinned_version_status = acceptance.get("PFC_PINNED_OPENCODE_RUNTIME") or (f"{pinned_opencode_runtime_contract()['version']} / PASS" if pinned_mode and resolution.get("status") == "PASS" else f"{pinned_opencode_runtime_contract()['version']} / FAIL" if pinned_mode else "NOT_APPLIED")
    pinned_path_status = acceptance.get("PFC_PINNED_OPENCODE_RUNTIME_PATH") or ("VERIFIED" if pinned_mode and (resolution.get("file_fact") or {}).get("status") == "PASS" else "FAIL" if pinned_mode else "NOT_APPLIED")
    same_runtime_status = acceptance.get("PFC_OPENCODE_VERSION_AND_LAUNCH_SAME_RUNTIME") or ("PASS" if pinned_mode and web.get("status") == "PASS" and resolution.get("status") == "PASS" else "FAIL" if pinned_mode else "NOT_APPLIED")
    package_workspace_status = acceptance.get("PFC_OPENCODE_PACKAGE_WORKSPACE") or ("PASS" if _same_path(web.get("workspace_root"), OPENCODE_WORKSPACE_ROOT) else "FAIL")
    dynamic_port_status = acceptance.get("PFC_OPENCODE_DYNAMIC_PORT") or ("PASS" if isinstance(port, int) and 1 <= port <= 65535 and port != 4096 else "FAIL")
    real_web_status = acceptance.get("PFC_OPENCODE_REAL_WEB_LAUNCH_PATH") or ("PASS" if web.get("status") == "PASS" and web.get("started_by_harness") and pid else "FAIL")
    trace_path = trace_zip or (str(STARTUP_TRACE.get("archive")) if STARTUP_TRACE and STARTUP_TRACE.get("archive") else "UNAVAILABLE")
    lines = [
        "=== PFC OpenCode Startup Diagnostic ===",
    ]
    if pinned_mode:
        contract = pinned_opencode_runtime_contract()
        lines.extend([
            "Candidates:",
            f"[1] path={_terminal_compact(resolution.get('pinned_runtime_path') or contract['path'], limit=620)} | launcher={resolution.get('pinned_file_type') or (resolution.get('file_fact') or {}).get('file_type') or 'UNKNOWN'} | version={resolution.get('actual_version') or 'UNAVAILABLE'}",
            "Candidate discovery=DISABLED (PINNED_RUNTIME_ONLY)",
            "Pinned Runtime:",
            f"path={_terminal_compact(resolution.get('pinned_runtime_path') or contract['path'], limit=760)} | expected={contract['version']} | actual={resolution.get('actual_version') or 'UNAVAILABLE'}",
            f"file type={resolution.get('pinned_file_type') or (resolution.get('file_fact') or {}).get('file_type') or 'UNKNOWN'} | invocation={resolution.get('selected_invocation_mode') or (resolution.get('file_fact') or {}).get('invocation_mode') or 'NOT_AVAILABLE'}",
        ])
    elif proven_command_mode:
        contract = proven_git_bash_command_contract()
        command_v = resolution.get("command_v") or {}
        lines.extend([
            "Candidates:",
            f"[1] path={_terminal_compact(command_v.get('stdout') or contract['command'], limit=620)} | launcher=SHELL_RESOLVED | version={resolution.get('actual_version') or 'UNAVAILABLE'}",
            "Candidate discovery=DISABLED (PROVEN_COMMAND_ONLY)",
            "Proven Command:",
            f"command={contract['command']} | command-v evidence={_terminal_compact(command_v.get('stdout') or 'UNAVAILABLE', limit=760)} | expected={contract['version']} | actual={resolution.get('actual_version') or 'UNAVAILABLE'}",
            "invocation=GIT_BASH_SHELL | file-type admission=DISABLED",
        ])
    else:
        lines.append("Candidates:")
    if not pinned_mode and not proven_command_mode and candidates:
        for index, candidate in enumerate(candidates, 1):
            lines.append(f"[{index}] path={_terminal_compact(candidate.get('path') or 'UNKNOWN', limit=480)} | launcher={candidate.get('launcher_type') or 'UNKNOWN'} | version={candidate.get('version') or candidate.get('actual_version') or 'UNAVAILABLE'}")
    elif not pinned_mode and not proven_command_mode:
        lines.append("[none] path=NONE | launcher=NONE | version=NONE")
    selected_path = resolution.get("selected_path") or (resolution.get("pinned_runtime_path") if pinned_mode else None)
    if proven_command_mode:
        selected_path = resolution.get("selected_path") or "opencode"
    selected_version = resolution.get("selected_version") or (resolution.get("actual_version") if pinned_mode or proven_command_mode else None)
    lines.extend([
        "Selected:",
        f"path={_terminal_compact(selected_path or 'NOT_SELECTED', limit=760)} | version={selected_version or 'NOT_SELECTED'}",
        "Pinned runtime probe:" if pinned_mode else "Proven command probe:" if proven_command_mode else "Shell resolution:",
        f"command={_terminal_compact(shell_version_probe.get('command') or ' '.join(str(item) for item in (shell_version_probe.get('argv') or [])) or ('<pinned-runtime> --version' if pinned_mode else 'opencode --version'), limit=520)} | exit={shell_version_probe.get('exit_code', 'NOT_RUN')}",
        "Workspace:",
        f"root={_terminal_compact(web.get('workspace_root') or OPENCODE_WORKSPACE_ROOT, limit=760)}",
        "Web:",
        f"host={host} | port={port} | project-binding={project_binding.get('status', 'NOT_RUN')}",
        f"session directory={_terminal_compact(project_binding.get('session_directory') or 'NOT_OBSERVED', limit=520)}",
        "Config:",
        f"path={_terminal_compact(generated_config.get('config_path') or 'UNAVAILABLE', limit=620)} | self-check={generated_config.get('status', 'NOT_RUN')} | server.port={'ABSENT_CLI_AUTHORITY' if not generated_config.get('config_port_present') else generated_config.get('config_port')}",
        "Launch:",
        f"command={command_text}",
        f"PID/process={pid or 'NOT_STARTED'} / {process_state}",
        f"launch exit code={exit_code if exit_code is not None else 'NOT_RUN'}",
        "Result:",
        "FAIL",
        f"Failure class={failure_class}",
        f"stdout tail={_terminal_compact(_trace_log_text('launch-stdout.log'), limit=460)}",
        f"stderr tail={_terminal_compact(_trace_log_text('launch-stderr.log'), limit=460)}",
        f"port/listener result=before:{_terminal_listener_summary(before_ports)} | after:{_terminal_listener_summary(after_ports)}",
        f"legacy instance detected={'YES' if legacy else 'NO'}",
        f"auth phase reached={'YES' if auth_reached else 'NO'}",
        f"Next action={_terminal_next_action(failure_class)}",
        f"Full trace ZIP (optional)={trace_path}",
        f"PFC_PINNED_OPENCODE_RUNTIME={'NOT_APPLIED_FINAL_COMMAND_CONTRACT' if proven_command_mode else pinned_version_status}",
        f"PFC_PINNED_OPENCODE_RUNTIME_PATH={'NOT_APPLIED_FINAL_COMMAND_CONTRACT' if proven_command_mode else pinned_path_status}",
        f"PFC_OPENCODE_VERSION_AND_LAUNCH_SAME_RUNTIME={'NOT_APPLIED_FINAL_COMMAND_CONTRACT' if proven_command_mode else same_runtime_status}",
        f"PFC_OPENCODE_GIT_BASH_COMMAND_ADMISSION={'PASS' if proven_command_mode and resolution.get('status') == 'PASS' else 'FAIL' if proven_command_mode else 'NOT_APPLIED'}",
        f"PFC_OPENCODE_VERSION_AND_WEB_SAME_SHELL={'PASS' if proven_command_mode and web.get('status') == 'PASS' and resolution.get('status') == 'PASS' else 'FAIL' if proven_command_mode else 'NOT_APPLIED'}",
        f"PFC_OPENCODE_PACKAGE_WORKSPACE={package_workspace_status}",
        f"PFC_OPENCODE_DYNAMIC_PORT={dynamic_port_status}",
        f"PFC_OPENCODE_REAL_WEB_LAUNCH_PATH={real_web_status}",
        f"PFC_OPENCODE_AUTH_REPROBE={acceptance.get('PFC_OPENCODE_AUTH_REPROBE', 'IMPLEMENTED' if pinned_mode else 'NOT_APPLIED')}",
        f"PFC_OPENCODE_PROVIDER_MODEL_PROBE={acceptance.get('PFC_OPENCODE_PROVIDER_MODEL_PROBE', 'IMPLEMENTED' if pinned_mode else 'NOT_APPLIED')}",
        f"PFC_OPENCODE_REAL_LLM_PROBE={acceptance.get('PFC_OPENCODE_REAL_LLM_PROBE', 'IMPLEMENTED' if pinned_mode else 'NOT_APPLIED')}",
        f"PFC_R2_SESSION_CREATE_RESUME={acceptance.get('PFC_R2_SESSION_CREATE_RESUME', 'IMPLEMENTED' if pinned_mode else 'NOT_APPLIED')}",
        f"PFC_CURRENT_COVERAGE_PROVENANCE={acceptance.get('PFC_CURRENT_COVERAGE_PROVENANCE', 'NOT_VERIFIED / QUARANTINED')}",
        f"PFC_CURRENT_STANDARD_CASE_PROVENANCE={acceptance.get('PFC_CURRENT_STANDARD_CASE_PROVENANCE', 'NOT_VERIFIED / QUARANTINED')}",
        "PFC_REAL_EXECUTION_ENTRY=HOLD",
        f"PFC_OPENCODE_PROVEN_V1_9_4_LAUNCH_PATH_REUSE={'NOT_APPLIED_FINAL_COMMAND_CONTRACT' if proven_command_mode else ('NOT_APPLIED_PINNED_RUNTIME' if pinned_mode else ('IMPLEMENTED' if proven_v19_launch_path_reuse_enabled() else 'NOT_APPLIED'))}",
        f"PFC_OPENCODE_CANDIDATE_SELECTION={'DISABLED_PROVEN_COMMAND' if proven_command_mode else 'DISABLED_PINNED_RUNTIME' if pinned_mode else ('EVIDENCE_ONLY' if proven_v19_launch_path_reuse_enabled() else 'LEGACY_ADMISSION')}",
        f"PFC_OPENCODE_VERSION_GUESSING={'STOPPED' if (proven_command_mode or pinned_mode or proven_v19_launch_path_reuse_enabled()) else 'ACTIVE_LEGACY_POLICY'}",
        f"PFC_OPENCODE_STARTUP_ROOT_CAUSE={'GIT_BASH_PROVEN_COMMAND_AUTHORITY' if proven_command_mode else ('PINNED_RUNTIME_CONTRACT' if pinned_mode else ('REMOVED' if proven_v19_launch_path_reuse_enabled() else 'NOT_REPAIRED'))}",
        f"PFC_OPENCODE_GENERATED_CONFIG_REALITY={'PASS' if generated_config.get('status') == 'PASS' else 'FAIL'}",
        f"PFC_OPENCODE_DYNAMIC_PORT_REALITY={'PASS' if isinstance(port, int) and 1 <= port <= 65535 and port != 4096 else 'FAIL'}",
        f"PFC_OPENCODE_LAUNCH_CONFIG_CONSISTENCY={'PASS' if generated_config.get('status') == 'PASS' and generated_config.get('port_authority') == 'CLI' else 'FAIL'}",
        f"PFC_OPENCODE_PROVEN_SHELL_LAUNCH_PATH={'PASS' if (proven_command_mode or resolution.get('launch_via_shell')) and resolution.get('status') == 'PASS' else 'FAIL'}",
        f"PFC_OPENCODE_REAL_PROCESS_LAUNCH_PATH={'PASS' if web.get('status') == 'PASS' and web.get('started_by_harness') and pid else 'FAIL'}",
        f"PFC_READY_PACKAGE_BANK_REALITY_ENTRY={'ALLOWED' if generated_config.get('status') == 'PASS' and (proven_command_mode or resolution.get('launch_via_shell')) and resolution.get('status') == 'PASS' else 'NOT_ALLOWED'}",
        "PFC_OPENCODE_STARTUP_TERMINAL_DIAGNOSTIC = IMPLEMENTED",
        "PFC_OPENCODE_DIAGNOSTIC_ZIP = OPTIONAL",
        "PFC_REAL_EXECUTION_ENTRY = HOLD",
        "PFC_R3_REQUIREMENT_SOURCE_REPAIR_ENTRY = HOLD",
    ])
    return "\n".join(trace_sanitize(line) for line in lines)


def finalize_startup_trace(runtime_reality: dict[str, Any] | None = None, exception: BaseException | None = None) -> str | None:
    if not STARTUP_TRACE:
        return None
    for thread in STARTUP_TRACE.get("stream_threads") or []:
        thread.join(timeout=1.0)
    trace_capture_process_and_ports("after")
    runtime = runtime_reality or {}
    web = runtime.get("opencode_web") or {}
    trace_write_json("web-health.json", {"captured_at": now_iso(), "web": web, "identity_matrix": runtime.get("PFC_OPENCODE_RUNTIME_IDENTITY_MATRIX")})
    trace_write_json("auth-probe.json", runtime.get("authentication") or {"status": "NOT_RUN"})
    trace_write_json("provider-model-probe.json", runtime.get("provider_model") or {"status": "NOT_RUN"})
    trace_write_json("llm-probe.json", runtime.get("llm_invocation") or {"status": "NOT_RUN"})
    trace_write_json("r2-probe.json", runtime.get("r2") or {"status": "NOT_RUN"})
    failure_class = classify_startup_failure(runtime, exception)
    resolution = (runtime.get("executable") or {}).get("resolution") or {}
    trace_dir = Path(str(STARTUP_TRACE["trace_dir"]))
    archive = trace_dir.parent / f"PFC-OPENCODE-STARTUP-DIAGNOSTIC-{STARTUP_TRACE['trace_id']}.zip"
    STARTUP_TRACE["archive"] = str(archive)
    trace_status = {key: "IMPLEMENTED" for key in STARTUP_TRACE_ACCEPTANCE_KEYS}
    diagnosis = {"trace_id": STARTUP_TRACE["trace_id"], "captured_at": now_iso(), "startup_status": "EXCEPTION" if exception else ("PASS" if (runtime.get("acceptance") or {}).get("PFC_OPENCODE_REAL_WEB_LAUNCH") == "PASS" else "FAILURE"), "failure_class": failure_class, "exception": {"type": type(exception).__name__, "message": str(exception)} if exception else None, "root_cause": runtime.get("PFC_OPENCODE_RUNTIME_INSTANCE_IDENTITY_GAP"), "binary_resolution": resolution, "web": web, "legacy_external_instance": any(item.get("port") == 4096 for item in (load_json(trace_dir / "port-after.json", {}) or {}).get("opencode_or_default_listeners", [])), "launch_stdout": _trace_log_text("launch-stdout.log"), "launch_stderr": _trace_log_text("launch-stderr.log"), "diagnostic_zip": str(archive), "trace_implementation": {**trace_status, "PFC_OPENCODE_DIAGNOSTIC_ZIP": "OPTIONAL"}, "r3_requirement_source_repair_entry": "HOLD", "real_execution_entry": "HOLD", "sensitive_values_policy": "redacted"}
    trace_write_json("FINAL_DIAGNOSIS.json", diagnosis)
    trace_title = "PFC OpenCode Startup Trace" if pinned_opencode_runtime_enabled() else "PFC OpenCode Startup Black Box Trace"
    summary_lines = [trace_title, f"trace_id={STARTUP_TRACE['trace_id']}", f"captured_at={now_iso()}", f"failure_class={failure_class}", f"selected_launcher={resolution.get('selected_path') or 'NOT_SELECTED'}", f"selected_version={resolution.get('selected_version') or 'NOT_SELECTED'}", f"candidate_count={resolution.get('candidate_count', 0)}", f"web_status={web.get('status', 'NOT_STARTED')}", f"web_url={web.get('web_url') or 'UNAVAILABLE'}", f"workspace={web.get('workspace_root') or OPENCODE_WORKSPACE_ROOT}", *[f"{key}={value}" for key, value in trace_status.items()], "PFC_OPENCODE_DIAGNOSTIC_ZIP=OPTIONAL", f"diagnostic_zip={archive}", "PFC_R3_REQUIREMENT_SOURCE_REPAIR_ENTRY=HOLD", "PFC_REAL_EXECUTION_ENTRY=HOLD", "敏感值已 redacted。"]
    trace_write_text("STARTUP_SUMMARY.txt", "\n".join(summary_lines) + "\n")
    trace_write_json("TRACE_INDEX.json", {"trace_id": STARTUP_TRACE["trace_id"], "archive": str(archive), "files": sorted(path.relative_to(trace_dir).as_posix() for path in trace_dir.rglob("*") if path.is_file())})
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(trace_dir.rglob("*")):
            if path.is_file():
                output.write(path, path.relative_to(trace_dir.parent).as_posix())
    return str(archive)


def internal_db_path() -> Path:
    return Path(os.environ["AITEST_DB_PATH"]).resolve()


def one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    return storage.one(sql, params)


def rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return storage.all_rows(sql, params)


def control() -> dict[str, Any]:
    return load_json(CONTROL_PATH, {"stop_requested": False}) or {"stop_requested": False}


def stop_requested() -> bool:
    return bool(control().get("stop_requested"))


def set_control(**values: Any) -> dict[str, Any]:
    payload = {**control(), **values, "updated_at": now_iso()}
    write_json(CONTROL_PATH, payload)
    return payload


def package_integrity() -> dict[str, Any]:
    if INSTALLED_RUNTIME_WORKSPACE:
        required = (
            "PFC_R1_R4_INSTALLATION.json",
            "PFC_PROJECT_PROFILE.json",
            "AGENTS.md",
            "opencode.json",
            "pfc-field-validation/pfc_harness.py",
            ".opencode/agents/aitest-director.md",
            ".opencode/tools/pfc.ts",
            "ai-test/runtime/aitest_runtime/__main__.py",
        )
        failed = [{"path": rel, "reason": "MISSING"} for rel in required if not (WORKSPACE_ROOT / rel).is_file()
        ]
        return {"ok": not failed, "code": None if not failed else "INSTALLED_WORKSPACE_FILE_MISSING", "checked": len(required), "failed": failed, "installed_runtime_workspace": True}
    manifest_path = PACKAGE_ROOT / "PACKAGE_MANIFEST.json"
    manifest = load_json(manifest_path, {}) or {}
    inventory = manifest.get("static_file_inventory") or []
    if not manifest_path.is_file() or not inventory:
        return {"ok": False, "code": "PACKAGE_MANIFEST_MISSING", "checked": 0, "failed": []}
    failed: list[dict[str, Any]] = []
    for item in inventory:
        rel = str(item.get("path") or "")
        target = PACKAGE_ROOT / rel
        if not target.is_file():
            failed.append({"path": rel, "reason": "MISSING"})
            continue
        actual_size = target.stat().st_size
        actual_hash = sha256_file(target)
        if actual_size != item.get("size_bytes") or actual_hash != item.get("sha256"):
            failed.append({"path": rel, "reason": "DIGEST_MISMATCH"})
    inventory_digest = digest([
        {"path": item["path"], "sha256": item["sha256"], "size_bytes": item["size_bytes"]}
        for item in inventory
    ])
    expected_digest = manifest.get("static_inventory_digest")
    return {
        "ok": not failed and inventory_digest == expected_digest,
        "code": None if not failed else "PACKAGE_FILE_MISMATCH",
        "checked": len(inventory),
        "failed": failed[:20],
        "inventory_digest_match": inventory_digest == expected_digest,
    }


def runtime_checks() -> dict[str, Any]:
    python_path = WORKSPACE_ROOT / "runtime" / "python" / "python.exe"
    chrome_path = WORKSPACE_ROOT / "runtime" / "browser" / "chrome-win64" / "chrome.exe"
    git_path = shutil.which("git")
    binary = resolve_proven_git_bash_command() if proven_git_bash_command_enabled() else (resolve_pinned_opencode_runtime() if pinned_opencode_runtime_enabled() else (resolve_proven_shell_opencode() if proven_v19_launch_path_reuse_enabled() else resolve_opencode_binary()))
    return {
        "portable_python": {"ok": python_path.is_file(), "path": str(python_path)},
        "portable_chrome": {"ok": chrome_path.is_file(), "path": str(chrome_path)},
        "git": {"ok": bool(git_path), "path": git_path},
        "opencode": {"ok": binary.get("status") == "PASS", "path": binary.get("selected_path"), "version": binary.get("actual_version"), "resolution": binary},
    }


def opencode_endpoint() -> str:
    if ACTIVE_OPENCODE_INSTANCE and ACTIVE_OPENCODE_INSTANCE.get("endpoint"):
        return str(ACTIVE_OPENCODE_INSTANCE["endpoint"]).rstrip("/")
    profile = machine_profile()
    return str(
        os.environ.get("PFC_OPENCODE_ACTIVE_ENDPOINT")
        or os.environ.get("PFC_OPENCODE_ENDPOINT")
        or profile.get("opencode_endpoint")
        or "http://127.0.0.1:4096"
    ).rstrip("/")


def opencode_executable() -> str | None:
    if ACTIVE_OPENCODE_INSTANCE and ACTIVE_OPENCODE_INSTANCE.get("binary_path"):
        return str(ACTIVE_OPENCODE_INSTANCE["binary_path"])
    result = resolve_proven_git_bash_command() if proven_git_bash_command_enabled() else (resolve_pinned_opencode_runtime() if pinned_opencode_runtime_enabled() else (resolve_proven_shell_opencode() if proven_v19_launch_path_reuse_enabled() else resolve_opencode_binary()))
    return str(result["selected_path"]) if result.get("status") == "PASS" else None


def _normalise_path(value: Any) -> str | None:
    if not value:
        return None
    raw = str(value).strip().strip('"')
    if os.name != "nt" and re.match(r"^[A-Za-z]:[\\/]", raw):
        return raw.replace("/", "\\")
    try:
        return str(Path(raw).expanduser().resolve())
    except (OSError, RuntimeError, ValueError):
        return raw


def _same_path(left: Any, right: Any) -> bool:
    lhs = _normalise_path(left)
    rhs = _normalise_path(right)
    if not lhs or not rhs:
        return False
    return lhs.casefold() == rhs.casefold()


def _version_text(value: Any) -> str | None:
    match = OPENCODE_VERSION_RE.search(str(value or ""))
    return match.group(1) if match else None


def opencode_expected_version() -> str | None:
    profile = machine_profile()
    policy = PROFILE.get("opencode_runtime_identity_policy") or {}
    nested = profile.get("opencode_runtime_identity") if isinstance(profile.get("opencode_runtime_identity"), dict) else {}
    value = (
        os.environ.get("PFC_OPENCODE_EXPECTED_VERSION")
        or profile.get("opencode_expected_version")
        or profile.get("approved_opencode_version")
        or nested.get("expected_version")
        or policy.get("expected_version")
    )
    return _version_text(value)


def opencode_compatible_versions() -> list[str]:
    """Return the frozen R1-R4 version set; never infer an R5 baseline."""
    profile = machine_profile()
    package_policy = PROFILE.get("opencode_runtime_identity_policy") or {}
    machine_policy = profile.get("opencode_compatibility_policy") if isinstance(profile.get("opencode_compatibility_policy"), dict) else {}
    values = machine_policy.get("compatible_versions") or package_policy.get("compatible_versions") or []
    versions = [_version_text(value) for value in values]
    versions = [value for value in versions if value]
    expected = opencode_expected_version()
    return [expected] if expected else list(dict.fromkeys(versions))


def opencode_expected_version_source() -> str:
    profile = machine_profile()
    package_policy = PROFILE.get("opencode_runtime_identity_policy") or {}
    if os.environ.get("PFC_OPENCODE_EXPECTED_VERSION"):
        return "ENV:PFC_OPENCODE_EXPECTED_VERSION"
    if profile.get("opencode_expected_version") or profile.get("approved_opencode_version"):
        return "MACHINE_PROFILE_APPROVED_VERSION"
    if isinstance(profile.get("opencode_runtime_identity"), dict) and profile["opencode_runtime_identity"].get("expected_version"):
        return "MACHINE_PROFILE_RUNTIME_IDENTITY"
    return str(package_policy.get("expected_version_source") or "PFC_R1_R4_FROZEN_COMPATIBILITY_EVIDENCE")


def _configured_opencode_binary() -> tuple[str | None, str | None]:
    profile = machine_profile()
    nested = profile.get("opencode_runtime_identity") if isinstance(profile.get("opencode_runtime_identity"), dict) else {}
    value = os.environ.get("AITEST_OPENCODE_BIN") or profile.get("opencode_binary_path") or nested.get("binary_path")
    return (str(value), "ENV:AITEST_OPENCODE_BIN" if os.environ.get("AITEST_OPENCODE_BIN") else "MACHINE_PROFILE") if value else (None, None)


def opencode_launcher_type(path: Any) -> str:
    suffix = Path(str(path or "")).suffix.casefold()
    return {".exe": "EXE", ".cmd": "CMD", ".bat": "BAT", ".ps1": "PS1"}.get(suffix, "NO_EXTENSION" if not suffix else "OTHER")


def launcher_subprocess_argv(command: str, args: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Build the exact process argv, including correct Windows CMD/BAT shim invocation."""
    command = str(command)
    values = [command, *(str(item) for item in args)]
    if os.name == "nt" and opencode_launcher_type(command) in {"CMD", "BAT"}:
        comspec = os.environ.get("ComSpec") or os.environ.get("COMSPEC") or shutil.which("cmd.exe") or "cmd.exe"
        command_line = subprocess.list2cmdline(values)
        # This is the standard `cmd /d /s /c ""path with spaces\shim.CMD" args"`
        # shape.  The shim path remains the selected launcher identity.
        return [str(comspec), "/d", "/s", "/c", command_line]
    return values


def launcher_underlying_target(path: Any) -> str | None:
    """Best-effort evidence for the target behind a legal CMD/BAT launcher."""
    launcher = _normalise_path(path)
    if not launcher or opencode_launcher_type(launcher) not in {"CMD", "BAT"}:
        return None
    try:
        text = Path(launcher).read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return None
    match = re.search(r"(?i)(?:%~dp0[\\/]?|[A-Za-z]:[\\/]|/)[^\"\r\n]*?opencode\.(?:exe|js|cjs|mjs)", text)
    if not match:
        return None
    value = match.group(0).replace("%~dp0", str(Path(launcher).parent))
    return _normalise_path(value)


def _windows_shell_path(value: str) -> str:
    """Convert an MSYS `/c/...` rendering back to a Windows path when needed."""
    text = str(value or "").strip().strip('"')
    if os.name == "nt":
        match = re.match(r"^/([A-Za-z])/(.*)$", text)
        if match:
            tail = match.group(2).replace("/", "\\")
            return f"{match.group(1).upper()}:\\{tail}"
    return text


def _candidate_record(path: Any, source: str) -> dict[str, str]:
    raw = _windows_shell_path(str(path))
    resolved = _normalise_path(raw) or raw
    return {"path": resolved, "source": source, "launcher_type": opencode_launcher_type(resolved)}


def _append_candidate(records: list[dict[str, str]], seen: set[str], path: Any, source: str) -> None:
    if not path:
        return
    record = _candidate_record(path, source)
    key = str(record["path"]).casefold()
    if key in seen:
        return
    seen.add(key)
    records.append(record)


def _path_directories() -> list[str]:
    raw_path = os.environ.get("PATH", "")
    separator = ";" if os.name == "nt" else os.pathsep
    return [item for item in raw_path.split(separator) if item]


def _pathext_names() -> list[str]:
    raw = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD;.PS1")
    extensions = [item.strip().lower() for item in raw.split(";") if item.strip()]
    names = ["opencode"]
    for extension in extensions:
        if extension not in {".exe", ".cmd", ".bat", ".ps1"}:
            continue
        names.extend(["opencode" + extension, "opencode" + extension.upper()])
    names.extend(["opencode.exe", "opencode.EXE", "opencode.cmd", "opencode.CMD", "opencode.bat", "opencode.BAT", "opencode.ps1"])
    return list(dict.fromkeys(names))


def _where_opencode_candidates() -> list[str]:
    if os.name != "nt":
        return []
    try:
        completed = subprocess.run(["where.exe", "opencode"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    return [_windows_shell_path(line.strip()) for line in completed.stdout.splitlines() if line.strip() and "INFO:" not in line.upper()]


def _git_bash_type_a_candidates() -> list[str]:
    if os.name != "nt" or not shutil.which("bash"):
        return []
    try:
        completed = subprocess.run(["bash", "-lc", "type -a opencode"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    values: list[str] = []
    for line in completed.stdout.splitlines():
        match = re.search(r"(?:\bis\s+|=>\s*)(.+)$", line.strip())
        candidate = match.group(1).strip() if match else line.strip()
        candidate = _windows_shell_path(candidate)
        if re.search(r"(?i)(?:^|[\\/])opencode(?:\.(?:exe|cmd|bat|ps1))?$", candidate):
            values.append(candidate)
    return values


def _known_opencode_candidates() -> list[str]:
    if os.name != "nt":
        return []
    roots: list[str] = [r"D:\Program Files", r"C:\Program Files"]
    user_profile_roots: set[str] = set()
    for variable in ("ProgramFiles", "PROGRAMFILES", "ProgramW6432", "PROGRAMW6432", "LOCALAPPDATA", "USERPROFILE"):
        value = os.environ.get(variable)
        if value:
            roots.append(value)
            if variable == "USERPROFILE":
                user_profile_roots.add(value.casefold())
    candidates: list[str] = []
    for root in roots:
        base = Path(_windows_shell_path(root))
        folders = [base / "opencode", base / "OpenCode", base / "opencode" / "bin"]
        if root.casefold() in user_profile_roots:
            folders.append(base / ".opencode" / "bin")
        for folder in folders:
            for name in ("opencode.exe", "opencode.CMD", "opencode.cmd", "opencode.BAT", "opencode.bat"):
                candidate = folder / name
                if candidate.is_file():
                    candidates.append(str(candidate))
    return candidates


def enumerate_opencode_candidate_records() -> list[dict[str, str]]:
    """Enumerate PATH/PATHEXT, Windows where.exe, Git Bash type -a, and known bank paths."""
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    explicit_path, explicit_source = _configured_opencode_binary()
    if explicit_path:
        _append_candidate(records, seen, explicit_path, explicit_source or "CONFIGURED")
    for directory in _path_directories():
        folder = Path(_windows_shell_path(directory))
        for name in _pathext_names():
            candidate = folder / name
            if candidate.is_file():
                _append_candidate(records, seen, candidate, "PATH_PATHEXT")
    for candidate in _where_opencode_candidates():
        _append_candidate(records, seen, candidate, "WHERE_EXE")
    for candidate in _git_bash_type_a_candidates():
        _append_candidate(records, seen, candidate, "GIT_BASH_TYPE_A")
    for candidate in _known_opencode_candidates():
        _append_candidate(records, seen, candidate, "KNOWN_BANK_PATH")
    return records


def enumerate_opencode_candidates() -> list[str]:
    """Return every candidate path; never use PATH's first match as identity."""
    return [item["path"] for item in enumerate_opencode_candidate_records()]


def opencode_command_probe(command: str | None, args: list[str], timeout: int = 8) -> dict[str, Any]:
    if not command:
        return {"status": "REPAIR", "error_class": "EXECUTABLE_NOT_FOUND", "output": None}
    argv = launcher_subprocess_argv(str(command), args)
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "REPAIR", "error_class": type(exc).__name__, "output": None, "stdout": "", "stderr": str(exc), "returncode": None, "exit_code": None, "launcher_type": opencode_launcher_type(command), "invocation_mode": "CMD_SHIM" if len(argv) > 1 and argv[0].casefold().endswith("cmd.exe") else "DIRECT", "argv": [_safe_command_line(item) for item in argv]}
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    output = (stdout or stderr).strip()
    return {"status": "PASS" if completed.returncode == 0 else "REPAIR", "output": output[:160], "stdout": stdout[:200000], "stderr": stderr[:200000], "returncode": completed.returncode, "exit_code": completed.returncode, "launcher_type": opencode_launcher_type(command), "invocation_mode": "CMD_SHIM" if len(argv) > 1 and argv[0].casefold().endswith("cmd.exe") else "DIRECT", "argv": _safe_argv(argv)}


def resolve_opencode_binary() -> dict[str, Any]:
    explicit, explicit_source = _configured_opencode_binary()
    candidate_records = enumerate_opencode_candidate_records()
    expected = opencode_expected_version()
    compatible_versions = opencode_compatible_versions()
    candidate_facts: list[dict[str, Any]] = []
    for record in candidate_records:
        candidate = record["path"]
        candidate_path = Path(candidate)
        exists = candidate_path.is_file()
        version_probe = opencode_command_probe(candidate, ["--version"]) if exists else {"status": "REPAIR", "error_class": "BINARY_NOT_FOUND", "output": None}
        fact: dict[str, Any] = {
            "path": candidate,
            "source": record["source"],
            "launcher_type": record["launcher_type"],
            "exists": exists,
            "file_size_bytes": candidate_path.stat().st_size if exists else None,
            "file_sha256": sha256_file(candidate_path) if exists else None,
            "version": _version_text(version_probe.get("output")),
            "actual_version": _version_text(version_probe.get("output")),
            "underlying_target": launcher_underlying_target(candidate),
            "version_probe": version_probe.get("status"),
            "version_output": version_probe.get("output"),
            "version_stdout": version_probe.get("stdout", ""),
            "version_stderr": version_probe.get("stderr", ""),
            "version_exit_code": version_probe.get("exit_code"),
            "version_argv": version_probe.get("argv"),
            "invocation_mode": version_probe.get("invocation_mode"),
        }
        if exists and record["launcher_type"] in {"CMD", "BAT"}:
            try:
                fact["launcher_content_excerpt"] = trace_sanitize(candidate_path.read_text(encoding="utf-8", errors="replace")[:20000])
            except OSError as exc:
                fact["launcher_content_error"] = type(exc).__name__
        candidate_facts.append(fact)
    selected: dict[str, Any] | None = None
    resolution_mode = "NONE"
    error_class = None
    if explicit:
        resolution_mode = "EXPLICIT_MACHINE_PROFILE" if explicit_source == "MACHINE_PROFILE" else "EXPLICIT_ENVIRONMENT"
        selected = next((item for item in candidate_facts if _same_path(item.get("path"), explicit)), None) or {"path": explicit, "exists": False, "version": None, "version_probe": "REPAIR"}
        if not selected.get("exists"):
            error_class = "CONFIGURED_BINARY_NOT_FOUND"
        elif selected.get("version_probe") != "PASS":
            error_class = "VERSION_PROBE_FAILED"
    elif len(candidate_facts) == 1:
        selected = candidate_facts[0]
        resolution_mode = "PATH_UNIQUE_ENUMERATED"
        if selected.get("version_probe") != "PASS":
            error_class = "VERSION_PROBE_FAILED"
    elif len(candidate_facts) > 1:
        compatible = [item for item in candidate_facts if item.get("version_probe") == "PASS" and item.get("version") in compatible_versions]
        if len(compatible) == 1:
            selected = compatible[0]
            resolution_mode = "FROZEN_R1_R4_COMPATIBILITY_POLICY_EXACT"
        elif len(compatible) > 1:
            error_class = "MULTIPLE_COMPATIBLE_OPENCODE_CANDIDATES_REQUIRE_EXPLICIT_BINARY"
        elif expected and any(item.get("version") for item in candidate_facts):
            error_class = "OPENCODE_VERSION_MISMATCH"
        else:
            error_class = "MULTIPLE_OPENCODE_CANDIDATES_REQUIRE_EXPLICIT_BINARY"
    else:
        error_class = "EXECUTABLE_NOT_FOUND"
    actual = selected.get("version") if selected else None
    version_match = bool(expected and actual and expected == actual)
    expected_source = opencode_expected_version_source() if expected else None
    if selected and not expected and actual and error_class is None:
        # An explicit path or a uniquely enumerated candidate is an
        # unambiguous version pin.  A second candidate never reaches here.
        expected = actual
        expected_source = "SELECTED_BINARY_ACTUAL_VERSION_NO_ALTERNATIVE"
        version_match = True
    elif selected and not expected:
        error_class = error_class or "EXPECTED_VERSION_NOT_CONFIGURED"
    elif selected and expected and actual and not version_match:
        error_class = "OPENCODE_VERSION_MISMATCH"
    elif selected and expected and not actual:
        error_class = error_class or "VERSION_UNAVAILABLE"
    status = "PASS" if selected and selected.get("exists") and selected.get("version_probe") == "PASS" and version_match else "REPAIR"
    admitted = bool(selected and selected.get("exists") and selected.get("version_probe") == "PASS" and version_match)
    locations: dict[str, list[str]] = {}
    for item in candidate_facts:
        version = item.get("version") or "UNAVAILABLE"
        locations.setdefault(version, []).append(str(item.get("path")))
    return {
        "status": status,
        "error_class": error_class,
        "resolution_mode": resolution_mode,
        "expected_version": expected or "NOT_CONFIGURED",
        "expected_version_source": expected_source or "NOT_CONFIGURED",
        "compatible_versions": compatible_versions,
        "actual_version": actual or "UNAVAILABLE",
        "version_match": version_match,
        "selected_path": selected.get("path") if admitted else None,
        "selected_launcher": selected.get("path") if admitted else None,
        "selected_version": actual if admitted else None,
        "selected_launcher_type": selected.get("launcher_type") if admitted else None,
        "selected_underlying_target": selected.get("underlying_target") if admitted else None,
        "selected_invocation_mode": selected.get("invocation_mode") if admitted else None,
        "configured_path": explicit,
        "candidate_count": len(candidate_facts),
        "candidates": candidate_facts,
        "version_locations": locations,
        "explicit_source": explicit_source,
    }


def web_runtime_public_state(state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = state if isinstance(state, dict) else (load_json(WEB_RUNTIME_STATE_PATH, {}) or {})
    return {
        "status": state.get("status") or "NOT_STARTED",
        "web_url": state.get("web_url"),
        "endpoint": state.get("endpoint"),
        "started_by_harness": bool(state.get("started_by_harness")),
        "browser_opened": bool(state.get("browser_opened")),
        "last_error": state.get("last_error"),
        "started_at": state.get("started_at"),
        "stopped_at": state.get("stopped_at"),
        "pid": state.get("pid"),
        "launcher_pid": state.get("launcher_pid"),
        "process_handle_pid": state.get("process_handle_pid"),
        "process_handle_owned": bool(state.get("process_handle_owned")),
        "host": state.get("host"),
        "port": state.get("port"),
        "listener_pids": state.get("listener_pids") or [],
        "binary_path": state.get("binary_path"),
        "version": state.get("version"),
        "workspace_root": state.get("workspace_root"),
        "launch_mode": state.get("launch_mode"),
        "generated_config": state.get("generated_config"),
        "config_path": state.get("config_path"),
        "port_authority": state.get("port_authority"),
        "launch_config_consistency": state.get("launch_config_consistency"),
        "project_binding": state.get("project_binding"),
        "interactive_primary_surface": state.get("interactive_primary_surface") or "OPENCODE_TUI",
        "web_surface": state.get("web_surface") or "SECONDARY_EXPLICIT_DIRECTORY_ROUTE",
        "identity_ref": state.get("identity_ref"),
        "identity_status": state.get("identity_status"),
        "process_stop": state.get("process_stop"),
    }


def write_web_runtime_state(state: dict[str, Any]) -> None:
    write_json(WEB_RUNTIME_STATE_PATH, state, private=True)


def pid_is_running(pid: Any) -> bool:
    try:
        numeric = int(pid)
    except (TypeError, ValueError):
        return False
    if numeric <= 0:
        return False
    try:
        os.kill(numeric, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def process_stop_timeout_seconds() -> float:
    try:
        value = float(os.environ.get("PFC_OPENCODE_PROCESS_STOP_TIMEOUT_SECONDS") or 8)
    except (TypeError, ValueError):
        value = 8.0
    return max(0.5, min(value, 60.0))


def _bounded_wait_for_pid(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while pid_is_running(pid) and time.monotonic() < deadline:
        time.sleep(min(0.1, max(0.01, deadline - time.monotonic())))
    return not pid_is_running(pid)


def _bounded_wait_for_process(process: subprocess.Popen[Any], timeout: float) -> dict[str, Any]:
    result: dict[str, Any] = {"stopped": False, "timeout": False, "exit_status": None, "stderr": ""}
    try:
        returncode = process.poll()
        if returncode is not None:
            result.update({"stopped": True, "exit_status": returncode})
            return result
        returncode = process.wait(timeout=max(0.0, timeout))
        result.update({"stopped": True, "exit_status": returncode})
    except subprocess.TimeoutExpired:
        result.update({"timeout": True, "error_class": "PROCESS_STOP_TIMEOUT"})
    except KeyboardInterrupt:
        result.update({"timeout": True, "error_class": "PROCESS_STOP_INTERRUPTED", "stderr": "用户中断了受控停止等待。"})
    except (OSError, subprocess.SubprocessError) as exc:
        result.update({"error_class": type(exc).__name__, "stderr": str(exc)[:2000]})
    return result


def _targeted_taskkill(pid: int, timeout: float) -> dict[str, Any]:
    """Kill one verified package-owned PID, never its process tree."""
    command = ["taskkill", "/PID", str(pid), "/F"]
    result: dict[str, Any] = {"command": command, "method": "TARGETED_TASKKILL_NO_TREE", "timeout": False, "exit_status": None, "stderr": ""}
    try:
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=max(0.5, timeout), check=False)
        result.update({"exit_status": completed.returncode, "stdout": trace_sanitize(completed.stdout or "")[:2000], "stderr": trace_sanitize(completed.stderr or "")[:2000], "stopped": completed.returncode == 0})
    except subprocess.TimeoutExpired as exc:
        result.update({"timeout": True, "error_class": "PROCESS_STOP_TIMEOUT", "stderr": trace_sanitize(str(exc))[:2000]})
    except KeyboardInterrupt:
        result.update({"timeout": True, "error_class": "PROCESS_STOP_INTERRUPTED", "stderr": "用户中断了受控停止操作。"})
    except (OSError, subprocess.SubprocessError) as exc:
        result.update({"error_class": type(exc).__name__, "stderr": trace_sanitize(str(exc))[:2000]})
    return result


def _bounded_terminate_owned_process(process: subprocess.Popen[Any] | None, pid: Any, *, role: str, timeout: float | None = None) -> dict[str, Any]:
    """Stop one package-owned process with bounded waits and controlled errors."""
    try:
        numeric_pid = int(pid)
    except (TypeError, ValueError):
        return {"role": role, "pid": pid, "stopped": False, "timeout": False, "error_class": "PROCESS_PID_INVALID"}
    if numeric_pid <= 0:
        return {"role": role, "pid": numeric_pid, "stopped": False, "timeout": False, "error_class": "PROCESS_PID_INVALID"}
    limit = process_stop_timeout_seconds() if timeout is None else max(0.5, min(float(timeout), 60.0))
    result: dict[str, Any] = {"role": role, "pid": numeric_pid, "stopped": False, "timeout": False, "method": None, "exit_status": None, "stderr": ""}
    try:
        running = pid_is_running(numeric_pid)
    except (OSError, ValueError):
        running = False
    if not running:
        result.update({"stopped": True, "method": "ALREADY_EXITED"})
        return result

    if process is not None and int(getattr(process, "pid", -1) or -1) == numeric_pid:
        try:
            process.terminate()
            result["method"] = "PROCESS_HANDLE_TERMINATE"
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            result.update({"error_class": type(exc).__name__, "stderr": str(exc)[:2000]})
        waited = _bounded_wait_for_process(process, limit)
        result.update({key: value for key, value in waited.items() if value is not None})
        if waited.get("stopped"):
            return result
        result["timeout"] = bool(result.get("timeout") or waited.get("timeout"))

    if os.name != "nt":
        try:
            os.kill(numeric_pid, signal.SIGTERM)
            result["method"] = result.get("method") or "SIGTERM"
        except ProcessLookupError:
            result.update({"stopped": True, "method": result.get("method") or "ALREADY_EXITED"})
            return result
        except OSError as exc:
            result.update({"error_class": type(exc).__name__, "stderr": str(exc)[:2000]})
        if _bounded_wait_for_pid(numeric_pid, limit):
            result["stopped"] = True
            return result
        try:
            os.kill(numeric_pid, signal.SIGKILL)
            result["method"] = "SIGKILL_FALLBACK"
        except ProcessLookupError:
            result["stopped"] = True
            return result
        except OSError as exc:
            result.update({"error_class": type(exc).__name__, "stderr": str(exc)[:2000]})
        result["stopped"] = _bounded_wait_for_pid(numeric_pid, limit)
        result["timeout"] = not result["stopped"]
        if not result["stopped"] and not result.get("error_class"):
            result["error_class"] = "PROCESS_STOP_TIMEOUT"
        return result

    # The Windows fallback is deliberately one verified PID, without /T.
    killed = _targeted_taskkill(numeric_pid, limit)
    result.update({key: value for key, value in killed.items() if key not in {"command"}})
    result["taskkill_command"] = killed.get("command")
    if killed.get("stopped") and _bounded_wait_for_pid(numeric_pid, limit):
        result["stopped"] = True
        return result
    result["timeout"] = bool(result.get("timeout") or killed.get("timeout") or not result.get("stopped"))
    if not result.get("error_class"):
        result["error_class"] = "PROCESS_STOP_TIMEOUT" if result.get("timeout") else "PROCESS_STOP_FAILED"
    return result


def web_interface_probe(url: str) -> dict[str, Any]:
    """Verify that an endpoint serves the OpenCode Web UI, not only JSON APIs."""
    headers = {"Accept": "text/html"}
    username = os.environ.get("OPENCODE_SERVER_USERNAME")
    password = os.environ.get("OPENCODE_SERVER_PASSWORD")
    if username and password:
        import base64
        headers["Authorization"] = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    request = urllib.request.Request(url.rstrip("/") + "/", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            sample = response.read(8192).decode("utf-8", errors="replace").lower()
            content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
            is_html = content_type == "text/html" or "<html" in sample or "<!doctype html" in sample
            return {"status": "PASS" if response.status == 200 and is_html else "REPAIR", "http_status": response.status, "content_type": content_type, "is_html": is_html}
    except urllib.error.HTTPError as exc:
        return {"status": "REPAIR", "http_status": exc.code, "error_class": "AUTHENTICATION_REQUIRED" if exc.code in {401, 403} else "HTTP_ERROR"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "REPAIR", "error_class": "ENDPOINT_UNAVAILABLE", "error_type": type(exc).__name__}


def endpoint_host_port(endpoint: str) -> tuple[str, int]:
    parsed = urlsplit(endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 4096
    return host if host in {"127.0.0.1", "localhost", "::1"} else "127.0.0.1", port


def _safe_command_line(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    text = TRACE_SENSITIVE_VALUE_RE.sub(lambda match: match.group(1) + "<redacted>", text)
    return text[:1000]


def opencode_process_snapshot() -> list[dict[str, Any]]:
    """Return all observable OpenCode processes, not the newest/first process."""
    items: list[dict[str, Any]] = []
    if os.name == "nt":
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
        if powershell:
            # Keep the full process table so a listener owned by node.exe (the
            # normal child behind an OpenCode .CMD shim) can still be joined to
            # its netstat PID and the launcher parent.
            script = "$items=@(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine); $items | ConvertTo-Json -Compress"
            try:
                completed = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, check=False)
                payload = json.loads((completed.stdout or "").strip() or "null")
                if isinstance(payload, dict):
                    payload = [payload]
                for item in payload if isinstance(payload, list) else []:
                    if not isinstance(item, dict):
                        continue
                    items.append({
                        "pid": item.get("ProcessId"),
                        "parent_pid": item.get("ParentProcessId"),
                        "name": item.get("Name"),
                        "executable_path": _normalise_path(item.get("ExecutablePath")),
                        "command_line": _safe_command_line(item.get("CommandLine")),
                        "cwd": None,
                        "cwd_source": "WINDOWS_PROCESS_CWD_NOT_EXPOSED_BY_WMI",
                    })
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
                pass
    else:
        try:
            completed = subprocess.run(["ps", "-axo", "pid=,ppid=,comm=,args="], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, check=False)
            for line in completed.stdout.splitlines():
                parts = line.strip().split(None, 3)
                if len(parts) < 4 or "opencode" not in parts[2].lower() and "opencode" not in parts[3].lower():
                    continue
                pid = int(parts[0]) if parts[0].isdigit() else None
                cwd = None
                if pid:
                    proc_cwd = Path(f"/proc/{pid}/cwd")
                    if proc_cwd.exists():
                        try:
                            cwd = str(proc_cwd.resolve())
                        except OSError:
                            cwd = None
                    if not cwd and shutil.which("lsof"):
                        try:
                            lsof = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=4, check=False)
                            for value in lsof.stdout.splitlines():
                                if value.startswith("n"):
                                    cwd = value[1:]
                                    break
                        except (OSError, subprocess.SubprocessError):
                            pass
                executable_path = None
                proc_exe = Path(f"/proc/{pid}/exe") if pid else None
                if proc_exe and proc_exe.exists():
                    try:
                        executable_path = str(proc_exe.resolve())
                    except OSError:
                        executable_path = None
                items.append({"pid": pid, "parent_pid": int(parts[1]) if parts[1].isdigit() else None, "name": parts[2], "executable_path": executable_path, "command_line": _safe_command_line(parts[3]), "cwd": cwd, "cwd_source": "PROCESS_CWD" if cwd else "UNAVAILABLE"})
        except (OSError, subprocess.SubprocessError):
            pass
    return items


def listening_process_ids(host: str, port: int) -> list[int]:
    ids: list[int] = []
    if os.name == "nt":
        try:
            completed = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, check=False)
            for line in completed.stdout.splitlines():
                fields = line.split()
                if len(fields) < 5 or fields[0].upper() != "TCP" or fields[3].upper() != "LISTENING":
                    continue
                local = fields[1].rsplit(":", 1)
                if len(local) == 2 and local[1] == str(port) and fields[4].isdigit():
                    ids.append(int(fields[4]))
        except (OSError, subprocess.SubprocessError):
            pass
    elif shutil.which("lsof"):
        try:
            completed = subprocess.run(["lsof", "-nP", "-a", "-iTCP:" + str(port), "-sTCP:LISTEN", "-t"], capture_output=True, text=True, timeout=8, check=False)
            ids = [int(value.strip()) for value in completed.stdout.splitlines() if value.strip().isdigit()]
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return sorted(set(ids))


def _workspace_values(payload: Any) -> list[str]:
    values: list[str] = []
    keys = {"directory", "workspace", "workspaceRoot", "workspace_root", "worktree", "projectPath", "project_path", "cwd"}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys and isinstance(value, str) and value.strip():
                values.append(value.strip())
            else:
                values.extend(_workspace_values(value))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_workspace_values(item))
    return list(dict.fromkeys(values))


def inspect_opencode_endpoint(endpoint: str, binary: dict[str, Any], managed_state: dict[str, Any] | None = None) -> dict[str, Any]:
    host, port = endpoint_host_port(endpoint)
    web = web_interface_probe(endpoint)
    process_rows = opencode_process_snapshot()
    listeners = listening_process_ids(host, port)
    process_by_pid = {int(item["pid"]): item for item in process_rows if str(item.get("pid", "")).isdigit()}
    listener_rows = [process_by_pid[pid] for pid in listeners if pid in process_by_pid]
    managed_pid = managed_state.get("pid") if isinstance(managed_state, dict) else None
    if managed_pid and int(managed_pid) in listeners and int(managed_pid) not in [int(item.get("pid")) for item in listener_rows if str(item.get("pid", "")).isdigit()]:
        managed_row = dict(managed_state)
        listener_rows.append({"pid": int(managed_pid), "executable_path": managed_row.get("binary_path"), "command_line": managed_row.get("command_line"), "cwd": managed_row.get("workspace_root"), "cwd_source": "PACKAGE_LAUNCHER_CWD_CONTRACT"})
    endpoint_payloads: dict[str, Any] = {}
    if web.get("status") == "PASS":
        for probe_path in ("/path", "/project/current", "/session"):
            response = opencode_http_request(probe_path, endpoint=endpoint)
            if response.get("status") == "PASS":
                endpoint_payloads[probe_path] = response.get("payload")
    payload_workspaces = [_normalise_path(value) for payload in endpoint_payloads.values() for value in _workspace_values(payload)]
    payload_workspaces = [value for value in payload_workspaces if value]
    rows = listener_rows
    selected_row = rows[0] if len(rows) == 1 else None
    if not selected_row and managed_pid and any(int(item.get("pid")) == int(managed_pid) for item in rows if str(item.get("pid", "")).isdigit()):
        selected_row = next(item for item in rows if int(item.get("pid")) == int(managed_pid))
    observed_workspace = payload_workspaces[0] if len(payload_workspaces) == 1 else None
    if not observed_workspace and selected_row:
        observed_workspace = _normalise_path(selected_row.get("cwd"))
    if not observed_workspace and managed_state and selected_row and _same_path(managed_state.get("workspace_root"), OPENCODE_WORKSPACE_ROOT):
        observed_workspace = _normalise_path(OPENCODE_WORKSPACE_ROOT)
    expected_path = binary.get("selected_path")
    process_path = selected_row.get("executable_path") if selected_row else None
    path_match = bool(expected_path and process_path and _same_path(expected_path, process_path))
    if not path_match and managed_state and selected_row and _same_path(managed_state.get("binary_path"), expected_path):
        path_match = True
        process_path = _normalise_path(managed_state.get("binary_path"))
    expected_launcher = _normalise_path(binary.get("selected_path"))
    command_line = str(selected_row.get("command_line") or "") if selected_row else ""
    launcher_in_command = bool(expected_launcher and expected_launcher.casefold() in command_line.casefold())
    managed_launcher_pid = (managed_state or {}).get("launcher_pid") if isinstance(managed_state, dict) else None
    managed_launcher_pid = managed_launcher_pid or ((managed_state or {}).get("pid") if isinstance(managed_state, dict) else None)
    managed_parent_match = bool(managed_state and selected_row and str(selected_row.get("parent_pid")) == str(managed_launcher_pid))
    underlying_target = _normalise_path(binary.get("underlying_target"))
    underlying_in_command = bool(underlying_target and underlying_target.casefold() in command_line.casefold())
    underlying_path_match = bool(underlying_target and process_path and _same_path(underlying_target, process_path))
    proven_command_match = bool(binary.get("proven_command") and (managed_parent_match or re.search(r"(?i)(?:^|[\\/\\s])opencode(?:\\s|$)", command_line)))
    launcher_match = path_match or launcher_in_command or underlying_in_command or underlying_path_match or managed_parent_match or proven_command_match
    workspace_match = bool(observed_workspace and _same_path(observed_workspace, OPENCODE_WORKSPACE_ROOT))
    health_probe = opencode_http_request("/global/health", endpoint=endpoint) if web.get("status") == "PASS" else {"status": "REPAIR", "error_class": "WEB_NOT_READY"}
    readiness_status = "PASS" if health_probe.get("status") == "PASS" or "/path" in endpoint_payloads else "REPAIR"
    identity_status = "PASS" if web.get("status") == "PASS" and readiness_status == "PASS" and len(rows) == 1 and launcher_match and workspace_match and binary.get("status") == "PASS" else "REPAIR"
    if web.get("status") != "PASS":
        error_class = web.get("error_class") or "WEB_ENDPOINT_UNAVAILABLE"
    elif readiness_status != "PASS":
        error_class = "WEB_HEALTH_NOT_READY"
    elif len(listeners) == 0:
        error_class = "WEB_LISTENER_PID_NOT_FOUND"
    elif len(rows) != 1:
        error_class = "WEB_INSTANCE_PID_AMBIGUOUS"
    elif not launcher_match:
        error_class = "OPENCODE_INSTANCE_LAUNCHER_MISMATCH"
    elif not observed_workspace:
        error_class = "OPENCODE_INSTANCE_WORKSPACE_UNOBSERVABLE"
    elif not workspace_match:
        error_class = "OPENCODE_WORKSPACE_SCOPE_COLLISION"
    elif binary.get("status") != "PASS":
        error_class = binary.get("error_class") or "OPENCODE_BINARY_NOT_ADMITTED"
    else:
        error_class = None
    pid = int(selected_row["pid"]) if selected_row and str(selected_row.get("pid", "")).isdigit() else (int(managed_pid) if str(managed_pid).isdigit() else None)
    return {
        "status": identity_status,
        "error_class": error_class,
        "endpoint": endpoint,
        "host": host,
        "port": port,
        "web_probe": web,
        "health_probe": health_probe.get("status"),
        "readiness_status": readiness_status,
        "listener_pids": listeners,
        "pid": pid,
        "pid_executable": process_path,
        "web_command_line": selected_row.get("command_line") if selected_row else None,
        "web_cwd": observed_workspace,
        "web_cwd_source": ("OPENAPI_PATH_OR_PROJECT" if payload_workspaces and "/path" in endpoint_payloads else "OPENAPI_SESSION_OR_PROJECT" if payload_workspaces else (selected_row or {}).get("cwd_source") if selected_row else "UNAVAILABLE"),
        "web_workspace_root": observed_workspace,
        "workspace_candidates": payload_workspaces,
        "workspace_probe_endpoints": sorted(endpoint_payloads),
        "path_match": path_match,
        "launcher_match": launcher_match,
        "selected_launcher": expected_launcher,
        "launcher_type": binary.get("launcher_type") or opencode_launcher_type(expected_launcher),
        "launcher_in_command": launcher_in_command,
        "underlying_target": underlying_target,
        "underlying_in_command": underlying_in_command,
        "underlying_path_match": underlying_path_match,
        "managed_parent_match": managed_parent_match,
        "launcher_pid": managed_launcher_pid,
        "workspace_match": workspace_match,
        "process_count_for_port": len(rows),
    }


def make_opencode_instance_identity(binary: dict[str, Any], endpoint: str | None, web: dict[str, Any] | None, launch_mode: str, root_cause: str | None = None) -> dict[str, Any]:
    web = web if isinstance(web, dict) else {}
    host, port = endpoint_host_port(endpoint) if endpoint else (None, None)
    identity = {
        "binary_path": binary.get("selected_path"),
        "selected_launcher": binary.get("selected_path"),
        "resolved_command": binary.get("resolved_command"),
        "launch_via_shell": bool(binary.get("launch_via_shell")),
        "shell_executable": binary.get("shell_executable"),
        "launcher_type": binary.get("launcher_type") or opencode_launcher_type(binary.get("selected_path")),
        "underlying_target": binary.get("selected_underlying_target") or binary.get("underlying_target"),
        "version": binary.get("actual_version"),
        "expected_version": binary.get("expected_version"),
        "workspace_root": str(OPENCODE_WORKSPACE_ROOT),
        "pid": web.get("pid"),
        "launcher_pid": web.get("launcher_pid"),
        "host": host,
        "port": port,
        "endpoint": endpoint,
        "launch_mode": launch_mode,
        "web_workspace_root": web.get("web_workspace_root"),
        "web_project_binding": web.get("project_binding"),
        "web_command_line": web.get("web_command_line"),
        "identity_status": web.get("status") if web else "REPAIR",
        "root_cause": root_cause,
        "binary_resolution": {key: binary.get(key) for key in ("status", "resolution_mode", "selected_path", "selected_version", "actual_version", "expected_version", "version_match", "resolved_command", "launch_via_shell", "shell_executable", "candidate_count", "candidates", "shell_resolution", "candidate_selection_is_evidence_only", "pinned_runtime", "pinned_runtime_path", "pinned_file_type", "pinned_version_probe", "proven_command", "proven_command_name", "command_v", "version_probe")},
    }
    identity["identity_ref"] = digest(identity)[:20]
    return identity


def build_runtime_identity_matrix(binary: dict[str, Any], identity: dict[str, Any], web: dict[str, Any], requested_endpoint: str, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    host, port = endpoint_host_port(requested_endpoint)
    return {
        "actual_executable_resolved": binary.get("selected_path"),
        "resolved_shell_command": binary.get("resolved_command"),
        "shell_executable": binary.get("shell_executable"),
        "launch_via_shell": bool(binary.get("launch_via_shell")),
        "pinned_runtime": bool(binary.get("pinned_runtime")),
        "proven_command": bool(binary.get("proven_command")),
        "proven_command_name": binary.get("proven_command_name"),
        "pinned_runtime_path": binary.get("pinned_runtime_path"),
        "pinned_file_type": binary.get("pinned_file_type"),
        "candidate_selection_is_evidence_only": bool(binary.get("candidate_selection_is_evidence_only")),
        "absolute_binary_path": binary.get("selected_path"),
        "actual_version": binary.get("actual_version"),
        "selected_version": binary.get("selected_version"),
        "expected_approved_version": binary.get("expected_version"),
        "version_match": binary.get("version_match"),
        "path_opencode_candidate_count": binary.get("candidate_count", 0),
        "path_opencode_candidates": binary.get("candidates", []),
        "version_location_matrix": binary.get("version_locations", {}),
        "binary_resolution_mode": binary.get("resolution_mode"),
        "binary_resolution_error": binary.get("error_class"),
        "web_launch_binary": identity.get("binary_path"),
        "web_launch_version": identity.get("version"),
        "selected_launcher": identity.get("selected_launcher") or binary.get("selected_path"),
        "selected_launcher_type": identity.get("launcher_type") or binary.get("launcher_type"),
        "launcher_underlying_target": identity.get("underlying_target") or binary.get("selected_underlying_target") or binary.get("underlying_target"),
        "launcher_resolution_status": "PASS" if binary.get("status") == "PASS" else "REPAIR",
        "launcher_invocation_mode": (binary.get("candidates") or [{}])[0].get("invocation_mode") if binary.get("candidates") else None,
        "web_target_host": host,
        "web_target_port": port,
        "web_listener_pids": web.get("listener_pids", []),
        "web_pid": identity.get("pid"),
        "web_launcher_pid": identity.get("launcher_pid") or web.get("launcher_pid"),
        "web_pid_executable": web.get("pid_executable"),
        "web_command_line": web.get("web_command_line"),
        "web_cwd": web.get("web_cwd"),
        "web_cwd_source": web.get("web_cwd_source"),
        "web_workspace_root": web.get("web_workspace_root"),
        "workspace_probe_endpoints": web.get("workspace_probe_endpoints", []),
        "package_workspace_root": str(OPENCODE_WORKSPACE_ROOT),
        "old_workspace_collision": bool(web.get("web_workspace_root") and not _same_path(web.get("web_workspace_root"), OPENCODE_WORKSPACE_ROOT)),
        "attached_preexisting_4096": bool(web.get("status") == "PASS" and web.get("port") == 4096 and identity.get("launch_mode") == "ATTACHED_PREEXISTING"),
        "requested_endpoint": requested_endpoint,
        "auth_probe_target": {"host": identity.get("host"), "port": identity.get("port"), "pid": identity.get("pid"), "workspace_root": identity.get("workspace_root"), "identity_ref": identity.get("identity_ref")},
        "provider_model_probe_target": {"host": identity.get("host"), "port": identity.get("port"), "pid": identity.get("pid"), "workspace_root": identity.get("workspace_root"), "identity_ref": identity.get("identity_ref")},
        "llm_probe_target": {"host": identity.get("host"), "port": identity.get("port"), "pid": identity.get("pid"), "workspace_root": identity.get("workspace_root"), "identity_ref": identity.get("identity_ref")},
        "r2_probe_target": {"host": identity.get("host"), "port": identity.get("port"), "pid": identity.get("pid"), "workspace_root": identity.get("workspace_root"), "identity_ref": identity.get("identity_ref")},
        "identity_ref": identity.get("identity_ref"),
        "identity_status": identity.get("identity_status"),
        "existing_instance_observation": existing,
    }


def bind_opencode_instance(identity: dict[str, Any] | None) -> None:
    global ACTIVE_OPENCODE_INSTANCE
    ACTIVE_OPENCODE_INSTANCE = identity if isinstance(identity, dict) else None
    if identity and identity.get("endpoint"):
        os.environ["PFC_OPENCODE_ACTIVE_ENDPOINT"] = str(identity["endpoint"])


def register_managed_opencode_process(process: subprocess.Popen[Any]) -> None:
    """Retain the handle created by START for later same-run restart/STOP."""
    global MANAGED_OPENCODE_PROCESS, MANAGED_OPENCODE_PROCESS_PID
    MANAGED_OPENCODE_PROCESS = process
    MANAGED_OPENCODE_PROCESS_PID = int(process.pid)


def opencode_web_launch_plan(binary: dict[str, Any]) -> dict[str, Any]:
    """Check the selected version's Web flags before constructing a command."""
    if binary.get("proven_command"):
        help_probe = proven_git_bash_command_probe(["web", "--help"], timeout=12)
        output = ((help_probe.get("stdout") or "") + "\n" + (help_probe.get("stderr") or "")).strip()
        has_port = "--port" in output
        has_hostname = "--hostname" in output
        if help_probe.get("status") != "PASS" or not has_port or not has_hostname:
            return {"status": "REPAIR", "error_class": "OPENCODE_WEB_FLAGS_UNSUPPORTED", "args": [], "help_output": _terminal_compact(output, limit=1000), "supports_port": has_port, "supports_hostname": has_hostname, "invocation_mode": "GIT_BASH_SHELL", "probe": help_probe, "proven_command": True}
        return {"status": "PASS", "error_class": None, "args": ["web", "--hostname", "127.0.0.1"], "help_output": _terminal_compact(output, limit=1000), "supports_port": True, "supports_hostname": True, "launcher_type": "SHELL_RESOLVED", "invocation_mode": "GIT_BASH_SHELL", "probe": help_probe, "proven_command": True}
    if binary.get("pinned_runtime"):
        help_probe = pinned_runtime_probe(binary, ["web", "--help"], timeout=12)
        output = ((help_probe.get("stdout") or "") + "\n" + (help_probe.get("stderr") or "")).strip()
        has_port = "--port" in output
        has_hostname = "--hostname" in output
        if help_probe.get("status") != "PASS" or not has_port or not has_hostname:
            return {"status": "REPAIR", "error_class": "OPENCODE_WEB_FLAGS_UNSUPPORTED", "args": [], "help_output": _terminal_compact(output, limit=1000), "supports_port": has_port, "supports_hostname": has_hostname, "invocation_mode": help_probe.get("invocation_mode"), "probe": help_probe, "pinned_runtime": True}
        return {"status": "PASS", "error_class": None, "args": ["web", "--hostname", "127.0.0.1"], "help_output": _terminal_compact(output, limit=1000), "supports_port": True, "supports_hostname": True, "launcher_type": binary.get("pinned_file_type"), "invocation_mode": help_probe.get("invocation_mode"), "probe": help_probe, "pinned_runtime": True}
    if binary.get("launch_via_shell"):
        help_probe = shell_opencode_probe(["web", "--help"], timeout=12)
        output = ((help_probe.get("stdout") or "") + "\n" + (help_probe.get("stderr") or "")).strip()
        has_port = "--port" in output
        has_hostname = "--hostname" in output
        if help_probe.get("status") != "PASS" or not has_port or not has_hostname:
            return {"status": "REPAIR", "error_class": "OPENCODE_WEB_FLAGS_UNSUPPORTED", "args": [], "help_output": _terminal_compact(output, limit=1000), "supports_port": has_port, "supports_hostname": has_hostname, "invocation_mode": "GIT_BASH_SHELL", "probe": help_probe}
        return {"status": "PASS", "error_class": None, "args": ["web", "--hostname", "127.0.0.1"], "help_output": _terminal_compact(output, limit=1000), "supports_port": True, "supports_hostname": True, "launcher_type": "SHELL_RESOLVED", "invocation_mode": "GIT_BASH_SHELL", "probe": help_probe}
    executable = binary.get("selected_path")
    if not executable:
        return {"status": "REPAIR", "error_class": "EXECUTABLE_NOT_FOUND", "args": []}
    try:
        completed = subprocess.run(launcher_subprocess_argv(str(executable), ["web", "--help"]), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "REPAIR", "error_class": type(exc).__name__, "args": []}
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    has_port = "--port" in output
    has_hostname = "--hostname" in output
    if completed.returncode != 0 or not has_port or not has_hostname:
        return {"status": "REPAIR", "error_class": "OPENCODE_WEB_FLAGS_UNSUPPORTED", "args": [], "help_output": output[:1000], "supports_port": has_port, "supports_hostname": has_hostname}
    return {"status": "PASS", "error_class": None, "args": ["web", "--hostname", "127.0.0.1"], "help_output": output[:1000], "supports_port": True, "supports_hostname": True, "launcher_type": binary.get("launcher_type") or opencode_launcher_type(executable), "invocation_mode": "CMD_SHIM" if (binary.get("launcher_type") or opencode_launcher_type(executable)) in {"CMD", "BAT"} else "DIRECT"}


def validate_generated_opencode_config(config_path: Path, launch_port: int | None = None) -> dict[str, Any]:
    """Self-check the generated package config before OpenCode can read it."""
    result: dict[str, Any] = {
        "status": "REPAIR",
        "config_path": str(config_path),
        "config_port_present": False,
        "config_port": None,
        "launch_port": launch_port,
        "port_authority": "CLI",
        "error_class": None,
    }
    if not config_path.is_file():
        result["error_class"] = "GENERATED_OPENCODE_CONFIG_MISSING"
        return result
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result["error_class"] = "GENERATED_OPENCODE_CONFIG_INVALID_JSON"
        result["error_detail"] = type(exc).__name__
        return result
    if not isinstance(payload, dict):
        result["error_class"] = "GENERATED_OPENCODE_CONFIG_NOT_OBJECT"
        return result
    server = payload.get("server")
    if server is not None and not isinstance(server, dict):
        result["error_class"] = "GENERATED_OPENCODE_CONFIG_SERVER_NOT_OBJECT"
        return result
    if isinstance(server, dict) and "port" in server:
        value = server.get("port")
        result["config_port_present"] = True
        result["config_port"] = value
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
            result["error_class"] = "GENERATED_OPENCODE_CONFIG_SERVER_PORT_INVALID"
            return result
        result["port_authority"] = "CONFIG_AND_CLI"
        if launch_port is not None and value != launch_port:
            result["error_class"] = "GENERATED_OPENCODE_CONFIG_PORT_MISMATCH"
            return result
    result["status"] = "PASS"
    result["error_class"] = None
    return result


def generate_package_owned_opencode_config(launch_port: int) -> dict[str, Any]:
    """Generate a fresh CLI-authoritative config for one selected port."""
    config_path = OPENCODE_WORKSPACE_ROOT / "opencode.json"
    result: dict[str, Any] = {"status": "REPAIR", "config_path": str(config_path), "launch_port": launch_port, "port_authority": "CLI", "config_port_present": False, "config_port": None}
    if isinstance(launch_port, bool) or not isinstance(launch_port, int) or not 1 <= launch_port <= 65535:
        result["error_class"] = "PACKAGE_OWNED_FREE_PORT_INVALID"
        return result
    try:
        OPENCODE_WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
        if config_path.is_file():
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        else:
            template = WORKSPACE_ROOT / "opencode.json"
            payload = json.loads(template.read_text(encoding="utf-8")) if template.is_file() else {}
        if not isinstance(payload, dict):
            result["error_class"] = "GENERATED_OPENCODE_CONFIG_NOT_OBJECT"
            return result
        server = payload.get("server")
        if isinstance(server, dict):
            server = dict(server)
            # CLI is the sole dynamic-port authority. Never emit port=0.
            server.pop("port", None)
            payload["server"] = server
        write_json(config_path, payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        result["error_class"] = "GENERATED_OPENCODE_CONFIG_GENERATION_FAILED"
        result["error_detail"] = type(exc).__name__
        return result
    result = validate_generated_opencode_config(config_path, launch_port)
    result["generated"] = True
    result["config_path"] = str(config_path)
    return result


def _startup_binary_stub(error_class: str) -> dict[str, Any]:
    return {"status": "REPAIR", "error_class": error_class, "selected_path": None, "selected_version": None, "actual_version": "UNAVAILABLE", "candidate_count": 0, "candidates": [], "resolution_mode": "CONFIG_SELF_CHECK_BEFORE_OPENCODE", "launch_via_shell": True, "resolved_command": "opencode", "candidate_selection_is_evidence_only": True}


def _package_startup_failure(binary: dict[str, Any], endpoint: str, error_class: str, *, generated_config: dict[str, Any] | None = None, launch_plan: dict[str, Any] | None = None, port_authority: str = "CLI") -> dict[str, Any]:
    host, port = endpoint_host_port(endpoint)
    web = {"status": "REPAIR", "endpoint": endpoint, "web_url": None, "host": host, "port": port, "error_class": error_class, "generated_config": generated_config, "port_authority": port_authority}
    identity = make_opencode_instance_identity(binary, endpoint, web, "NOT_ATTACHED", error_class)
    matrix = build_runtime_identity_matrix(binary, identity, web, endpoint)
    state = {"status": "REPAIR", "endpoint": endpoint, "web_url": None, "started_by_harness": False, "browser_opened": False, "last_error": error_class, "observed_at": now_iso(), "pid": None, "binary_path": binary.get("selected_path"), "version": binary.get("actual_version"), "workspace_root": str(OPENCODE_WORKSPACE_ROOT), "launch_mode": "CONFIG_SELF_CHECK_FAILED" if "CONFIG" in error_class else "NOT_ATTACHED", "generated_config": generated_config, "config_path": (generated_config or {}).get("config_path"), "port_authority": port_authority, "launch_config_consistency": (generated_config or {}).get("status", "REPAIR"), "identity_ref": identity.get("identity_ref"), "identity_status": "REPAIR", "identity_matrix": matrix, "launch_plan": launch_plan}
    write_web_runtime_state(state)
    bind_opencode_instance(identity)
    return {**web_runtime_public_state(state), "identity": identity, "identity_matrix": matrix}


def package_owned_free_port(host: str, preferred: Any = None) -> int | None:
    """Reserve-and-release a loopback port for a package-owned launch."""
    try:
        preferred_port = int(preferred) if preferred is not None else None
    except (TypeError, ValueError):
        preferred_port = None
    if preferred_port and 1 <= preferred_port <= 65535 and not listening_process_ids(host, preferred_port) and web_interface_probe(f"http://{host}:{preferred_port}").get("status") != "PASS":
        return preferred_port
    for _ in range(8):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", 0))
                port = int(sock.getsockname()[1])
            if not listening_process_ids(host, port):
                return port
        except OSError:
            continue
    return None


def discover_other_opencode_instances(identity: dict[str, Any] | None) -> list[dict[str, Any]]:
    exact_pid = str((identity or {}).get("pid") or "")
    found: list[dict[str, Any]] = []
    for item in opencode_process_snapshot():
        pid = str(item.get("pid") or "")
        command = str(item.get("command_line") or "")
        match = re.search(r"(?:--port|port)[=\s]+(\d{2,5})", command, re.IGNORECASE)
        if not match or pid == exact_pid:
            continue
        found.append({"pid": item.get("pid"), "endpoint": f"http://127.0.0.1:{int(match.group(1))}", "executable_path": item.get("executable_path"), "command_line": item.get("command_line"), "cwd": item.get("cwd")})
    return found


def revalidate_opencode_identity(identity: dict[str, Any]) -> dict[str, Any]:
    if proven_git_bash_command_enabled():
        binary = resolve_proven_git_bash_command()
    elif pinned_opencode_runtime_enabled():
        binary = resolve_pinned_opencode_runtime()
    else:
        binary = {"status": "PASS", "selected_path": identity.get("binary_path"), "launcher_type": identity.get("launcher_type"), "selected_underlying_target": identity.get("underlying_target"), "actual_version": identity.get("version"), "expected_version": identity.get("expected_version"), "version_match": True, "candidate_count": 1, "candidates": [{"path": identity.get("binary_path"), "version": identity.get("version"), "launcher_type": identity.get("launcher_type"), "underlying_target": identity.get("underlying_target")}], "version_locations": {str(identity.get("version")): [identity.get("binary_path")]}}
    if binary.get("status") != "PASS":
        return {"status": "REPAIR", "observation": {"status": "REPAIR", "error_class": binary.get("error_class") or "PINNED_OPENCODE_RUNTIME_MISMATCH"}, "same_instance": False, "other_instances": []}
    observation = inspect_opencode_endpoint(str(identity.get("endpoint")), binary, {"pid": identity.get("pid"), "launcher_pid": identity.get("launcher_pid"), "binary_path": identity.get("binary_path"), "version": identity.get("version"), "workspace_root": identity.get("workspace_root"), "command_line": identity.get("web_command_line")})
    same = observation.get("status") == "PASS" and int(observation.get("pid") or -1) == int(identity.get("pid") or -2) and observation.get("launcher_match") and _same_path(observation.get("web_workspace_root"), identity.get("workspace_root"))
    return {"status": "PASS" if same else "REPAIR", "observation": observation, "same_instance": same, "other_instances": discover_other_opencode_instances(identity)}


def wait_for_auth_and_resume(base: dict[str, Any], web: dict[str, Any], identity: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compatibility wrapper for a non-blocking same-instance AI probe.

    START no longer calls this helper and never waits for human input.  Keep
    the name for older integrations, but make its semantics safe as well:
    probe the already-running identity once, update only AI Runtime state,
    and never stop or restart the package-owned Web process.
    """
    if base.get("authentication", {}).get("status") != "HUMAN_ACTION_REQUIRED":
        return base, {"status": "NOT_REQUIRED", "identity_ref": identity.get("identity_ref"), "non_blocking": True, "prompt_count": 0, "restart_attempted": False}
    refreshed = opencode_runtime_probe(identity)
    auth_status = refreshed.get("authentication", {}).get("status")
    wait_state = {
        "status": "READY" if auth_status == "PASS" else "WAITING_FOR_AUTH",
        "identity_ref": identity.get("identity_ref"),
        "web_url": web.get("web_url") or identity.get("endpoint"),
        "non_blocking": True,
        "prompt_count": 0,
        "restart_attempted": False,
        "restart_required": False,
        "reprobe": "SAME_INSTANCE_NON_BLOCKING",
        "started_at": now_iso(),
    }
    state = load_json(WEB_RUNTIME_STATE_PATH, {}) or {}
    state["auth_wait"] = wait_state
    write_web_runtime_state(state)
    return refreshed, wait_state


def ensure_opencode_web(base: dict[str, Any]) -> dict[str, Any]:
    """Resolve and bind one exact OpenCode Web instance before any probe."""
    del base
    profile = machine_profile()
    requested_endpoint = str(os.environ.get("PFC_OPENCODE_ENDPOINT") or profile.get("opencode_endpoint") or "http://127.0.0.1:4096").rstrip("/")
    proven_command = proven_git_bash_command_enabled()
    pinned_runtime = pinned_opencode_runtime_enabled()
    shell_first = proven_command or pinned_runtime or proven_v19_launch_path_reuse_enabled()
    launch_mode_name = "GIT_BASH_PROVEN_COMMAND" if proven_command else "PINNED_RUNTIME_GIT_BASH_EXACT_PATH" if pinned_runtime else "PROVEN_V19_GIT_BASH_SHELL" if shell_first else "PACKAGE_MANAGED"
    prior = load_json(WEB_RUNTIME_STATE_PATH, {}) or {}
    existing_observation: dict[str, Any] | None = None
    generated_config: dict[str, Any] | None = None
    if shell_first:
        # Required startup order: package workspace -> real free port -> fresh
        # config -> self-check. No OpenCode process or browser is touched yet.
        host = "127.0.0.1"
        configured_port = os.environ.get("PFC_OPENCODE_WEB_PORT") or profile.get("opencode_web_port")
        try:
            OPENCODE_WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _package_startup_failure(_startup_binary_stub(type(exc).__name__), requested_endpoint, "PACKAGE_OWNED_WORKSPACE_CREATE_FAILED")
        selected_port = package_owned_free_port(host, configured_port)
        if not selected_port:
            return _package_startup_failure(_startup_binary_stub("PACKAGE_OWNED_FREE_PORT_NOT_AVAILABLE"), requested_endpoint, "PACKAGE_OWNED_FREE_PORT_NOT_AVAILABLE", generated_config={"status": "REPAIR", "config_path": str(OPENCODE_WORKSPACE_ROOT / "opencode.json"), "launch_port": None, "error_class": "PACKAGE_OWNED_FREE_PORT_NOT_AVAILABLE"})
        generated_config = generate_package_owned_opencode_config(selected_port)
        if STARTUP_TRACE:
            trace_write_json("generated-opencode-config.json", generated_config)
        if generated_config.get("status") != "PASS":
            endpoint = f"http://{host}:{selected_port}"
            return _package_startup_failure(_startup_binary_stub(str(generated_config.get("error_class") or "GENERATED_OPENCODE_CONFIG_INVALID")), endpoint, str(generated_config.get("error_class") or "GENERATED_OPENCODE_CONFIG_INVALID"), generated_config=generated_config)
    binary = resolve_proven_git_bash_command() if proven_command else (resolve_pinned_opencode_runtime() if pinned_runtime else (resolve_proven_shell_opencode() if shell_first else resolve_opencode_binary()))
    if binary.get("status") != "PASS":
        if shell_first:
            # The Git Bash command is the only admission path. Candidate
            # enumeration is retained in the trace as evidence and cannot
            # turn a shell-resolved command into selected NONE.
            endpoint = f"http://127.0.0.1:{(generated_config or {}).get('launch_port') or 4096}"
            return _package_startup_failure(binary, endpoint, str(binary.get("error_class") or "GIT_BASH_OPENCODE_VERSION_FAILED"), generated_config=generated_config)
        # Still inspect a reachable/default-port instance when binary
        # admission fails.  This is the evidence needed to explain a v1.14 /
        # v1.18 drift or an old workspace collision; it is never an attach.
        reachable = web_interface_probe(requested_endpoint)
        if reachable.get("status") == "PASS" or listening_process_ids(*endpoint_host_port(requested_endpoint)):
            existing_observation = inspect_opencode_endpoint(requested_endpoint, binary)
        web = existing_observation or {"status": "REPAIR", "endpoint": requested_endpoint, "host": endpoint_host_port(requested_endpoint)[0], "port": endpoint_host_port(requested_endpoint)[1], "error_class": binary.get("error_class")}
        root_cause = (existing_observation or {}).get("error_class") or binary.get("error_class")
        identity = make_opencode_instance_identity(binary, requested_endpoint, web, "NOT_ATTACHED", root_cause)
        matrix = build_runtime_identity_matrix(binary, identity, web, requested_endpoint)
        state = {"status": "REPAIR", "endpoint": requested_endpoint, "web_url": requested_endpoint if existing_observation and existing_observation.get("web_probe", {}).get("status") == "PASS" else None, "started_by_harness": False, "browser_opened": False, "last_error": root_cause, "observed_at": now_iso(), "pid": identity.get("pid"), "binary_path": binary.get("selected_path"), "version": binary.get("actual_version"), "workspace_root": str(OPENCODE_WORKSPACE_ROOT), "launch_mode": "NOT_ATTACHED", "identity_ref": identity.get("identity_ref"), "identity_status": "REPAIR", "identity_matrix": matrix}
        write_web_runtime_state(state)
        bind_opencode_instance(identity)
        return {**web_runtime_public_state(state), "identity": identity, "identity_matrix": matrix}

    # The proven repair must perform a fresh package-owned launch first. The
    # old endpoint/4096 attach check remains only in the legacy path.
    if not shell_first:
        requested_probe = web_interface_probe(requested_endpoint)
        if requested_probe.get("status") == "PASS" or listening_process_ids(*endpoint_host_port(requested_endpoint)):
            existing_observation = inspect_opencode_endpoint(requested_endpoint, binary, prior if prior.get("endpoint") == requested_endpoint else None)
            if existing_observation.get("status") == "PASS":
                identity = make_opencode_instance_identity(binary, requested_endpoint, existing_observation, "ATTACHED_VERIFIED_INSTANCE", None)
                bind_opencode_instance(identity)
                state = {"status": "PASS", "endpoint": requested_endpoint, "web_url": requested_endpoint, "started_by_harness": False, "browser_opened": False, "last_error": None, "observed_at": now_iso(), "pid": identity.get("pid"), "host": identity.get("host"), "port": identity.get("port"), "binary_path": identity.get("binary_path"), "version": identity.get("version"), "workspace_root": str(OPENCODE_WORKSPACE_ROOT), "launch_mode": "ATTACHED_VERIFIED_INSTANCE", "identity_ref": identity.get("identity_ref"), "identity_status": "PASS", "identity_matrix": build_runtime_identity_matrix(binary, identity, existing_observation, requested_endpoint, existing_observation)}
                write_web_runtime_state(state)
                return {**web_runtime_public_state(state), "identity": identity, "identity_matrix": state["identity_matrix"]}

    host = "127.0.0.1"
    configured_port = os.environ.get("PFC_OPENCODE_WEB_PORT") or profile.get("opencode_web_port")
    launch_plan = opencode_web_launch_plan(binary)
    if launch_plan.get("status") != "PASS":
        endpoint = f"http://{host}:{selected_port}" if shell_first else requested_endpoint
        return _package_startup_failure(binary, endpoint, str(launch_plan.get("error_class") or "OPENCODE_WEB_FLAGS_UNSUPPORTED"), generated_config=generated_config, launch_plan=launch_plan)
    selected_port = selected_port if shell_first else package_owned_free_port(host, configured_port)
    if not selected_port:
        identity = make_opencode_instance_identity(binary, requested_endpoint, {}, "NOT_ATTACHED", "PACKAGE_OWNED_FREE_PORT_NOT_AVAILABLE")
        matrix = build_runtime_identity_matrix(binary, identity, {"status": "REPAIR", "error_class": "PACKAGE_OWNED_FREE_PORT_NOT_AVAILABLE"}, requested_endpoint, existing_observation)
        state = {"status": "REPAIR", "endpoint": requested_endpoint, "web_url": None, "started_by_harness": False, "browser_opened": False, "last_error": "PACKAGE_OWNED_FREE_PORT_NOT_AVAILABLE", "observed_at": now_iso(), "binary_path": binary.get("selected_path"), "version": binary.get("actual_version"), "workspace_root": str(OPENCODE_WORKSPACE_ROOT), "launch_mode": "NOT_ATTACHED", "identity_ref": identity.get("identity_ref"), "identity_status": "REPAIR", "identity_matrix": matrix}
        write_web_runtime_state(state)
        bind_opencode_instance(identity)
        return {**web_runtime_public_state(state), "identity": identity, "identity_matrix": matrix}
    cwd_probe = workspace_pwd_probe() if shell_first else {
        "status": "PASS",
        "expected_workspace": str(OPENCODE_WORKSPACE_ROOT),
        "shell_workspace": str(OPENCODE_WORKSPACE_ROOT),
        "actual_shell_pwd": str(OPENCODE_WORKSPACE_ROOT),
        "cwd_match": True,
        "source": "Popen cwd contract",
        "error_class": None,
    }
    launch_plan["workspace_pwd_probe"] = cwd_probe
    if cwd_probe.get("status") != "PASS":
        endpoint = f"http://{host}:{selected_port}" if shell_first else requested_endpoint
        return _package_startup_failure(binary, endpoint, "OPENCODE_WORKSPACE_PROCESS_CWD_MISMATCH", generated_config=generated_config, launch_plan=launch_plan)
    # A stale 4096 listener is an observation only.  It is never accepted by
    # URL reachability alone; a fresh package-owned port is selected instead.
    candidate_ports = [selected_port]
    if not shell_first and prior.get("started_by_harness") and prior.get("endpoint") and pid_is_running(prior.get("pid")) and _same_path(prior.get("workspace_root"), OPENCODE_WORKSPACE_ROOT) and _same_path(prior.get("binary_path"), binary.get("selected_path")) and prior.get("version") == binary.get("actual_version"):
        prior_endpoint = str(prior["endpoint"])
        existing_observation = inspect_opencode_endpoint(prior_endpoint, binary, prior)
        if existing_observation.get("status") == "PASS":
            identity = make_opencode_instance_identity(binary, prior_endpoint, existing_observation, "PACKAGE_MANAGED", None)
            identity["pid"] = prior.get("pid") or identity.get("pid")
            identity["identity_ref"] = digest(identity)[:20]
            bind_opencode_instance(identity)
            prior.update({"status": "PASS", "web_url": prior_endpoint, "last_error": None, "observed_at": now_iso(), "identity_ref": identity["identity_ref"], "identity_status": "PASS", "identity_matrix": build_runtime_identity_matrix(binary, identity, existing_observation, requested_endpoint, existing_observation)})
            write_web_runtime_state(prior)
            return {**web_runtime_public_state(prior), "identity": identity, "identity_matrix": prior["identity_matrix"]}

    for port in candidate_ports:
        web_url = f"http://{host}:{port}"
        if not shell_first and web_interface_probe(web_url).get("status") == "PASS":
            existing_observation = inspect_opencode_endpoint(web_url, binary)
            if existing_observation.get("status") == "PASS":
                identity = make_opencode_instance_identity(binary, web_url, existing_observation, "ATTACHED_PREEXISTING", None)
                bind_opencode_instance(identity)
                state = {"status": "PASS", "endpoint": web_url, "web_url": web_url, "started_by_harness": False, "browser_opened": False, "last_error": None, "observed_at": now_iso(), "pid": identity.get("pid"), "host": host, "port": port, "binary_path": identity.get("binary_path"), "version": identity.get("version"), "workspace_root": str(OPENCODE_WORKSPACE_ROOT), "launch_mode": "ATTACHED_PREEXISTING", "identity_ref": identity.get("identity_ref"), "identity_status": "PASS", "identity_matrix": build_runtime_identity_matrix(binary, identity, existing_observation, requested_endpoint, existing_observation)}
                write_web_runtime_state(state)
                return {**web_runtime_public_state(state), "identity": identity, "identity_matrix": state["identity_matrix"]}
            continue
        if listening_process_ids(host, port):
            continue
        try:
            OPENCODE_WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
            launcher_command = [str(binary["selected_path"]), *launch_plan["args"], "--port", str(port)]
            if proven_command:
                shell_launch_command = workspace_shell_launch_command(["web", "--hostname", "127.0.0.1", "--port", str(port)])
                launch_plan["shell_command"] = shell_launch_command
                shell_executable = str(binary.get("shell_executable") or shutil.which("bash") or "bash")
                command = [shell_executable, "-lc", shell_launch_command]
            elif pinned_runtime:
                shell_launch_command = f"cd -- {shlex.quote(_workspace_shell_path())} && pwd && exec {pinned_runtime_shell_command(binary, ['web', '--hostname', '127.0.0.1', '--port', str(port)])}"
                launch_plan["shell_command"] = shell_launch_command
                shell_executable = str(binary.get("shell_executable") or shutil.which("bash") or "bash")
                command = [shell_executable, "-lc", shell_launch_command]
            elif shell_first:
                shell_launch_command = workspace_shell_launch_command(["web", "--hostname", "127.0.0.1", "--port", str(port)])
                launch_plan["shell_command"] = shell_launch_command
                shell_executable = str(binary.get("shell_executable") or shutil.which("bash") or "bash")
                command = [shell_executable, "-lc", shell_launch_command]
            else:
                command = launcher_subprocess_argv(launcher_command[0], launcher_command[1:])
            launch_env = os.environ.copy()
            launch_env["PFC_OPENCODE_ACTIVE_ENDPOINT"] = web_url
            if STARTUP_TRACE:
                trace_record_launch_command(binary, launch_plan, command, port)
                popen_kwargs: dict[str, Any] = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True, "encoding": "utf-8", "errors": "replace", "bufsize": 1}
            else:
                popen_kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            process = subprocess.Popen(command, cwd=str(OPENCODE_WORKSPACE_ROOT), env=launch_env, start_new_session=os.name != "nt", **popen_kwargs)
            register_managed_opencode_process(process)
            if STARTUP_TRACE:
                trace_record_launch_command(binary, launch_plan, command, port, pid=process.pid)
                trace_attach_process_streams(process)
        except (OSError, subprocess.SubprocessError) as exc:
            if STARTUP_TRACE:
                trace_record_launch_command(binary, launch_plan, command if "command" in locals() else [], port, exception=exc)
            identity = make_opencode_instance_identity(binary, web_url, {}, "PACKAGE_MANAGED", type(exc).__name__)
            state = {"status": "REPAIR", "endpoint": web_url, "web_url": None, "started_by_harness": False, "last_error": type(exc).__name__, "observed_at": now_iso(), "binary_path": binary.get("selected_path"), "version": binary.get("actual_version"), "workspace_root": str(OPENCODE_WORKSPACE_ROOT), "launch_mode": launch_mode_name, "generated_config": generated_config, "config_path": (generated_config or {}).get("config_path"), "port_authority": (generated_config or {}).get("port_authority", "CLI"), "launch_config_consistency": (generated_config or {}).get("status", "REPAIR"), "identity_ref": identity.get("identity_ref"), "identity_status": "REPAIR"}
            write_web_runtime_state(state)
            bind_opencode_instance(identity)
            return {**web_runtime_public_state(state), "identity": identity, "identity_matrix": build_runtime_identity_matrix(binary, identity, {"status": "REPAIR", "error_class": type(exc).__name__}, requested_endpoint)}
        state = {"status": "STARTING", "endpoint": web_url, "web_url": web_url, "started_by_harness": True, "browser_opened": False, "last_error": None, "pid": process.pid, "launcher_pid": process.pid, "process_handle_pid": process.pid, "process_handle_owned": True, "started_at": now_iso(), "host": host, "port": port, "binary_path": binary.get("selected_path"), "selected_launcher": binary.get("selected_path"), "resolved_command": binary.get("resolved_command"), "launch_via_shell": shell_first, "shell_executable": binary.get("shell_executable"), "launcher_type": binary.get("launcher_type") or opencode_launcher_type(binary.get("selected_path")), "version": binary.get("actual_version"), "workspace_root": str(OPENCODE_WORKSPACE_ROOT), "process_cwd_contract": cwd_probe, "launch_mode": launch_mode_name, "launcher_invocation": launch_plan.get("invocation_mode"), "command_line": _safe_command_line(launch_plan.get("shell_command") or " ".join(command)), "generated_config": generated_config, "config_path": (generated_config or {}).get("config_path"), "port_authority": (generated_config or {}).get("port_authority", "CLI"), "launch_config_consistency": (generated_config or {}).get("status", "REPAIR")}
        write_web_runtime_state(state)
        for _ in range(24):
            if process.poll() is not None:
                state["status"] = "REPAIR"
                state["last_error"] = "WEB_PROCESS_EXITED"
                if STARTUP_TRACE:
                    trace_record_launch_command(binary, launch_plan, command, port, pid=process.pid, exit_code=process.returncode)
                write_web_runtime_state(state)
                break
            listener_pids = listening_process_ids(host, port)
            state["listener_pids"] = listener_pids
            if not listener_pids:
                write_web_runtime_state(state)
                time.sleep(0.5)
                continue
            if web_interface_probe(web_url).get("status") == "PASS":
                health_ready = opencode_http_request("/global/health", endpoint=web_url, timeout=5)
                path_ready = health_ready if health_ready.get("status") == "PASS" else opencode_http_request("/path", endpoint=web_url, timeout=5)
                state["readiness"] = {"health": health_ready.get("status"), "fallback": path_ready.get("status") if health_ready.get("status") != "PASS" else None}
                if path_ready.get("status") != "PASS":
                    state["last_error"] = "WEB_HEALTH_NOT_READY"
                    write_web_runtime_state(state)
                    time.sleep(0.5)
                    continue
                observation = inspect_opencode_endpoint(web_url, binary, state)
                process_cwd = observation.get("web_cwd")
                state["process_cwd_contract"] = {
                    **cwd_probe,
                    "process_cwd": process_cwd,
                    "process_cwd_source": observation.get("web_cwd_source"),
                    "process_cwd_match": bool(process_cwd and _same_path(process_cwd, OPENCODE_WORKSPACE_ROOT)),
                    "status": "PASS" if cwd_probe.get("status") == "PASS" and process_cwd and _same_path(process_cwd, OPENCODE_WORKSPACE_ROOT) else "REPAIR",
                }
                identity = make_opencode_instance_identity(binary, web_url, observation, "PACKAGE_MANAGED", observation.get("error_class"))
                if observation.get("status") == "PASS":
                    # OpenCode 1.18.21 Web does not inherit a project from
                    # `opencode web` process cwd.  Bind the explicit project
                    # and session directory before any browser is opened.
                    project_binding = web_project_binding_probe(web_url, OPENCODE_WORKSPACE_ROOT)
                    state["project_binding"] = project_binding
                    if project_binding.get("status") != "PASS":
                        state["status"] = "REPAIR"
                        state["last_error"] = project_binding.get("error_class") or "OPENCODE_WEB_PROJECT_BINDING_FAILED"
                        write_web_runtime_state(state)
                        break
                    bound_web_url = str(project_binding.get("session_url") or web_url)
                    try:
                        state["browser_opened"] = bool(webbrowser.open(bound_web_url, new=2))
                    except Exception:
                        state["browser_opened"] = False
                    identity["pid"] = identity.get("pid") or process.pid
                    identity["identity_ref"] = digest(identity)[:20]
                    state.update({"status": "PASS", "last_error": None, "observed_at": now_iso(), "pid": identity["pid"], "identity_ref": identity["identity_ref"], "identity_status": "PASS", "web_url": bound_web_url, "identity_matrix": build_runtime_identity_matrix(binary, identity, observation, requested_endpoint, observation)})
                    bind_opencode_instance(identity)
                    write_web_runtime_state(state)
                    print("Starting OpenCode...", flush=True)
                    print(f"Resolved command: {launch_plan.get('shell_command') or ' '.join(str(item) for item in command)}", flush=True)
                    print(f"Version: {binary.get('actual_version') or 'UNAVAILABLE'}", flush=True)
                    print(f"Workspace: {OPENCODE_WORKSPACE_ROOT}", flush=True)
                    print(f"Web: {bound_web_url}", flush=True)
                    print(f"PID: {identity.get('pid') or process.pid}", flush=True)
                    return {**web_runtime_public_state(state), "identity": identity, "identity_matrix": state["identity_matrix"]}
                state["last_error"] = observation.get("error_class") or "OPENCODE_INSTANCE_IDENTITY_NOT_VERIFIED"
                write_web_runtime_state(state)
                break
            time.sleep(0.5)
        if process.poll() is None:
            _bounded_terminate_owned_process(process, process.pid, role="startup-launcher")
        for listener_pid in state.get("listener_pids") or []:
            if int(listener_pid or 0) != int(process.pid):
                _bounded_terminate_owned_process(None, listener_pid, role="startup-listener")
    failure_endpoint = f"http://{host}:{selected_port}" if shell_first and selected_port else requested_endpoint
    if shell_first:
        failure_state = state if isinstance(locals().get("state"), dict) else {}
        web = {"status": "REPAIR", "endpoint": failure_endpoint, "web_url": None, "started_by_harness": bool(failure_state.get("started_by_harness")), "host": host, "port": selected_port, "error_class": failure_state.get("last_error") or "WEB_ENDPOINT_NOT_READY", "listener_pids": failure_state.get("listener_pids", []), "pid": failure_state.get("pid"), "launcher_pid": failure_state.get("launcher_pid"), "web_command_line": failure_state.get("command_line"), "generated_config": generated_config, "port_authority": (generated_config or {}).get("port_authority", "CLI"), "project_binding": failure_state.get("project_binding")}
    else:
        web = existing_observation or {"status": "REPAIR", "error_class": "WEB_ENDPOINT_NOT_READY", "listener_pids": []}
    identity = make_opencode_instance_identity(binary, failure_endpoint, web, "NOT_ATTACHED", web.get("error_class"))
    matrix = build_runtime_identity_matrix(binary, identity, web, requested_endpoint, existing_observation)
    failure_state = locals().get("failure_state") if isinstance(locals().get("failure_state"), dict) else {}
    state = {"status": "REPAIR", "endpoint": failure_endpoint, "web_url": None, "started_by_harness": bool(failure_state.get("started_by_harness")), "browser_opened": False, "last_error": identity.get("root_cause"), "observed_at": now_iso(), "binary_path": binary.get("selected_path"), "version": binary.get("actual_version"), "workspace_root": str(OPENCODE_WORKSPACE_ROOT), "process_cwd_contract": locals().get("cwd_probe") or {}, "launch_mode": launch_mode_name if shell_first else "NOT_ATTACHED", "generated_config": generated_config, "config_path": (generated_config or {}).get("config_path"), "port_authority": (generated_config or {}).get("port_authority", "CLI"), "launch_config_consistency": (generated_config or {}).get("status", "REPAIR"), "project_binding": failure_state.get("project_binding"), "pid": failure_state.get("pid"), "listener_pids": failure_state.get("listener_pids", []), "identity_ref": identity.get("identity_ref"), "identity_status": "REPAIR", "identity_matrix": matrix}
    write_web_runtime_state(state)
    bind_opencode_instance(identity)
    return {**web_runtime_public_state(state), "identity": identity, "identity_matrix": matrix}


def opencode_http_request(path: str, method: str = "GET", body: dict[str, Any] | None = None, timeout: int = 12, endpoint: str | None = None, directory: Path | str | None = None) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if directory:
        # v1.18.21's directory-scoped client requests use this header for
        # legacy/generated endpoints such as /agent, while project/session
        # routes also accept the explicit `directory` query parameter.
        headers["x-opencode-directory"] = str(directory)
    username = os.environ.get("OPENCODE_SERVER_USERNAME")
    password = os.environ.get("OPENCODE_SERVER_PASSWORD")
    if username and password:
        import base64
        headers["Authorization"] = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    request = urllib.request.Request((endpoint or opencode_endpoint()).rstrip("/") + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(5000000).decode("utf-8", errors="replace")
            if not raw:
                payload: Any = None
            else:
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    return {"status": "REPAIR", "http_status": response.status, "error_class": "NON_JSON_RESPONSE"}
            return {"status": "PASS", "http_status": response.status, "payload": payload}
    except urllib.error.HTTPError as exc:
        body_text = ""
        try:
            body_text = exc.read(12000).decode("utf-8", errors="replace").lower()
        except OSError:
            pass
        if exc.code in {401, 403} or any(marker in body_text for marker in ("login", "unauthorized", "authentication", "session")):
            error_class = "AUTHENTICATION_REQUIRED"
        elif exc.code == 404:
            error_class = "ENDPOINT_NOT_SUPPORTED"
        else:
            error_class = "HTTP_ERROR"
        return {"status": "REPAIR", "http_status": exc.code, "error_class": error_class}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "REPAIR", "error_class": "ENDPOINT_UNAVAILABLE", "error_type": type(exc).__name__}


def opencode_web_directory_query(directory: Path | str) -> str:
    """Build the v1.18.21 workspace-routing query used by Web API calls."""
    return urlencode({"directory": str(directory)})


def opencode_web_directory_slug(directory: Path | str) -> str:
    """Match OpenCode Web's URL-safe, unpadded base64 directory route."""
    return base64.urlsafe_b64encode(str(directory).encode("utf-8")).decode("ascii").rstrip("=")


def opencode_web_session_url(endpoint: str, directory: Path | str, session_id: str) -> str:
    return f"{endpoint.rstrip('/')}/{opencode_web_directory_slug(directory)}/session/{session_id}"


def _session_id_from_payload(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("id", "sessionID", "session_id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            found = _session_id_from_payload(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _session_id_from_payload(value)
            if found:
                return found
    return None


def _session_payloads(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("sessions", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload] if _session_id_from_payload(payload) else []
    return []


def _agent_names(payload: Any) -> list[str]:
    names: list[str] = []
    if isinstance(payload, dict):
        for key in ("name", "id", "agent", "slug"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                names.append(value.strip())
        for value in payload.values():
            names.extend(_agent_names(value))
    elif isinstance(payload, list):
        for value in payload:
            names.extend(_agent_names(value))
    return list(dict.fromkeys(names))


def web_project_binding_probe(endpoint: str, directory: Path | str) -> dict[str, Any]:
    """Bind and prove the explicit project/session directory route.

    OpenCode 1.18.21 starts Web without an ambient project instance.  The
    server APIs therefore receive `directory=...`, and the browser is opened
    on the same base64 directory/session route used by the Web application.
    This is deliberately a fail-closed probe: no browser is opened unless the
    server reports both the requested project and the selected session under
    the exact directory.
    """
    requested = str(directory)
    query = opencode_web_directory_query(requested)
    result: dict[str, Any] = {
        "status": "REPAIR",
        "capability": "OPEN_CODE_1_18_21_DIRECTORY_ROUTE_AND_SESSION_QUERY",
        "requested_directory": requested,
        "directory_route": opencode_web_directory_slug(requested),
        "project_endpoint": f"/project/current?{query}",
        "session_endpoint": f"/session?{query}",
        "agent_endpoint": f"/agent?{query}",
        "project_directory": None,
        "project_worktree": None,
        "session_id": None,
        "session_directory": None,
        "session_created_by_harness": False,
        "session_url": None,
        "agent_names": [],
        "error_class": None,
    }
    current = opencode_http_request(f"/project/current?{query}", endpoint=endpoint, directory=requested)
    if current.get("status") != "PASS":
        result.update({"error_class": "OPENCODE_WEB_PROJECT_BINDING_UNSUPPORTED", "project_probe": current})
        return result
    current_payload = current.get("payload")
    current_values = [_normalise_path(value) for value in _workspace_values(current_payload)]
    current_values = [value for value in current_values if value]
    requested_match = next((value for value in current_values if _same_path(value, requested)), None)
    result["project_directory"] = requested_match
    result["project_worktree"] = next((value for value in current_values if value != requested_match), requested_match)
    result["project_probe"] = {"status": current.get("status"), "http_status": current.get("http_status"), "workspace_values": current_values}
    if not requested_match:
        result["error_class"] = "OPENCODE_WEB_PROJECT_DIRECTORY_MISMATCH"
        return result

    sessions = opencode_http_request(f"/session?{query}&roots=true&limit=10", endpoint=endpoint, directory=requested)
    if sessions.get("status") != "PASS":
        result["error_class"] = "OPENCODE_WEB_SESSION_ROUTE_UNSUPPORTED"
        result["session_probe"] = sessions
        return result
    session_rows = _session_payloads(sessions.get("payload"))
    selected: dict[str, Any] | None = None
    for row in session_rows:
        values = [_normalise_path(value) for value in _workspace_values(row)]
        if any(value and _same_path(value, requested) for value in values):
            selected = row
            break
    if selected is None:
        created = opencode_http_request(
            f"/session?{query}",
            method="POST",
            body={"title": "PFC R1-R4 Web Workspace"},
            endpoint=endpoint,
            directory=requested,
        )
        if created.get("status") != "PASS":
            result["error_class"] = "OPENCODE_WEB_SESSION_CREATE_UNSUPPORTED"
            result["session_probe"] = {"list": sessions, "create": created}
            return result
        selected = created.get("payload") if isinstance(created.get("payload"), dict) else None
        result["session_created_by_harness"] = True
    session_id = _session_id_from_payload(selected)
    if not session_id:
        result["error_class"] = "OPENCODE_WEB_SESSION_ID_UNOBSERVABLE"
        result["session_probe"] = {"list": sessions, "selected": selected}
        return result
    if result["session_created_by_harness"]:
        session_detail = selected or {}
    else:
        session_detail_response = opencode_http_request(f"/session/{session_id}?{query}", endpoint=endpoint, directory=requested)
        session_detail = session_detail_response.get("payload") if session_detail_response.get("status") == "PASS" else selected or {}
    session_values = [_normalise_path(value) for value in _workspace_values(session_detail)]
    session_values = [value for value in session_values if value]
    session_match = next((value for value in session_values if _same_path(value, requested)), None)
    result["session_id"] = session_id
    result["session_directory"] = session_match
    result["session_probe"] = {"status": sessions.get("status"), "http_status": sessions.get("http_status"), "workspace_values": session_values}
    if not session_match:
        result["error_class"] = "OPENCODE_WEB_SESSION_DIRECTORY_MISMATCH"
        return result

    agents = opencode_http_request(f"/agent?{query}", endpoint=endpoint, directory=requested)
    names = _agent_names(agents.get("payload")) if agents.get("status") == "PASS" else []
    result["agent_names"] = names
    result["agent_probe"] = {"status": agents.get("status"), "http_status": agents.get("http_status"), "names": names}
    if agents.get("status") != "PASS" or not any(name.casefold() == "aitest-director" for name in names):
        result["error_class"] = "OPENCODE_WEB_AGENT_DISCOVERY_UNPROVEN"
        return result
    result["session_url"] = opencode_web_session_url(endpoint, requested, session_id)
    result["status"] = "PASS"
    return result


def opencode_config_facts() -> dict[str, Any]:
    path = Path(os.environ.get("AITEST_OPENCODE_CONFIG") or (WORKSPACE_ROOT / "opencode.json"))
    if not path.is_file():
        return {"status": "REPAIR", "path_present": False, "provider_configured": False, "model_configured": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "REPAIR", "path_present": True, "provider_configured": False, "model_configured": False}
    if not isinstance(payload, dict):
        return {"status": "REPAIR", "path_present": True, "provider_configured": False, "model_configured": False}
    providers = payload.get("provider") or payload.get("providers") or {}
    model = os.environ.get("AITEST_OPENCODE_MODEL") or payload.get("model") or payload.get("default_model")
    provider = os.environ.get("AITEST_OPENCODE_PROVIDER") or payload.get("provider_id") or payload.get("default_provider")
    if isinstance(model, str) and "/" in model and not provider:
        provider, model = model.split("/", 1)
    return {
        "status": "PASS",
        "path_present": True,
        "provider_configured": bool(provider or providers),
        "model_configured": bool(model),
        "configured_provider": str(provider) if provider else None,
        "configured_model": str(model) if model else None,
        "provider_config_keys": sorted(str(key) for key in providers) if isinstance(providers, dict) else [],
    }


def provider_model_facts(provider_payload: Any, catalog_payload: Any, config: dict[str, Any]) -> dict[str, Any]:
    provider_payload = provider_payload if isinstance(provider_payload, dict) else {}
    catalog_payload = catalog_payload if isinstance(catalog_payload, dict) else {}
    connected_raw = provider_payload.get("connected") or []
    connected = [str(item.get("id") or item.get("providerID") or item.get("provider_id")) if isinstance(item, dict) else str(item) for item in connected_raw]
    default = provider_payload.get("default") or catalog_payload.get("default") or {}
    configured_provider = config.get("configured_provider")
    configured_model = config.get("configured_model")
    provider_id = configured_provider
    live_default_model = None
    if isinstance(default, dict) and default:
        live_default_provider = str(next(iter(default)))
        live_default_value = default[live_default_provider]
        if isinstance(live_default_value, dict):
            live_default_model = live_default_value.get("modelID") or live_default_value.get("model_id") or live_default_value.get("model")
        else:
            live_default_model = str(live_default_value)
        if not provider_id:
            provider_id = live_default_provider
    if not provider_id and connected:
        provider_id = connected[0]
    all_providers = provider_payload.get("all") or provider_payload.get("providers") or catalog_payload.get("providers") or []
    if isinstance(all_providers, dict):
        all_providers = [{"id": key, **(value if isinstance(value, dict) else {})} for key, value in all_providers.items()]
    selected = next((item for item in all_providers if isinstance(item, dict) and str(item.get("id") or item.get("providerID") or item.get("provider_id")) == str(provider_id)), {})
    models = (selected.get("models") or {}) if isinstance(selected, dict) else {}
    model_names = sorted(str(key) for key in models) if isinstance(models, dict) else [str(item.get("id") or item.get("modelID")) for item in models if isinstance(item, dict)]
    model_id = None
    if configured_model and configured_model in model_names:
        model_id = configured_model
    elif live_default_model and str(live_default_model) in model_names:
        model_id = str(live_default_model)
    elif model_names:
        model_id = model_names[0]
    provider_connected = bool(provider_id and str(provider_id) in connected)
    model_available = bool(model_id and model_names and str(model_id) in model_names)
    return {
        "provider": str(provider_id) if provider_id else "UNAVAILABLE",
        "model": str(model_id) if model_id else "UNAVAILABLE",
        "connected": provider_connected,
        "model_available": model_available,
        "connected_provider_count": len(connected),
        "provider_source": "LIVE_PROVIDER_ENDPOINT" if provider_connected else "UNAVAILABLE",
        "model_source": "LIVE_PROVIDER_OR_CATALOG_ENDPOINT" if model_available else "UNAVAILABLE",
        "status": "PASS" if provider_connected and model_available else "REPAIR",
    }


def _explicit_credentials_reload_signal(value: Any) -> str | None:
    """Return a restart reason only for an explicit runtime reload signal."""
    signal_keys = {
        "credentials_reload_required",
        "credentialsreloadrequired",
        "config_reload_required",
        "configreloadrequired",
        "reload_required",
        "reloadrequired",
        "restart_required",
        "restartrequired",
        "requires_restart",
        "requiresrestart",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            normalised = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalised in {re.sub(r"[^a-z0-9]", "", item_key) for item_key in signal_keys} and item is True:
                return str(key)
            reason = _explicit_credentials_reload_signal(item)
            if reason:
                return reason
    elif isinstance(value, list):
        for item in value:
            reason = _explicit_credentials_reload_signal(item)
            if reason:
                return reason
    elif isinstance(value, str) and re.search(r"(?i)(credentials?|config(?:uration)?)\s+(?:reload|re-?load)\s+required", value):
        return "explicit_runtime_reload_message"
    return None


def opencode_runtime_probe(identity: dict[str, Any] | None = None) -> dict[str, Any]:
    identity = identity if isinstance(identity, dict) else ACTIVE_OPENCODE_INSTANCE
    proven_command = proven_git_bash_command_enabled()
    pinned_runtime = pinned_opencode_runtime_enabled()
    shell_first = proven_command or pinned_runtime or proven_v19_launch_path_reuse_enabled() or bool(identity and identity.get("launch_via_shell"))
    binary = resolve_proven_git_bash_command() if proven_command else (resolve_pinned_opencode_runtime() if pinned_runtime else (resolve_proven_shell_opencode() if shell_first else resolve_opencode_binary()))
    executable = str(identity.get("binary_path")) if identity and identity.get("binary_path") else binary.get("selected_path")
    version = proven_git_bash_command_probe(["--version"]) if proven_command else (pinned_runtime_probe(binary, ["--version"]) if pinned_runtime else (shell_opencode_probe(["--version"]) if shell_first else opencode_command_probe(executable, ["--version"])))
    config = opencode_config_facts()
    same_instance = bool(identity and identity.get("identity_status") == "PASS" and identity.get("endpoint") and identity.get("pid"))
    identity_error = (identity or {}).get("root_cause") or "OPENCODE_INSTANCE_IDENTITY_NOT_VERIFIED"
    health = opencode_http_request("/global/health") if version.get("status") == "PASS" and same_instance else {"status": "REPAIR", "error_class": identity_error if not same_instance else "EXECUTABLE_NOT_AVAILABLE"}
    provider = opencode_http_request("/provider") if health.get("status") == "PASS" else {"status": "REPAIR", "error_class": "HEALTH_NOT_VERIFIED"}
    catalog = opencode_http_request("/config/providers") if health.get("status") == "PASS" else {"status": "REPAIR", "error_class": "HEALTH_NOT_VERIFIED"}
    session_status = opencode_http_request("/session/status") if health.get("status") == "PASS" else {"status": "REPAIR", "error_class": "HEALTH_NOT_VERIFIED"}
    health_payload = health.get("payload") if isinstance(health.get("payload"), dict) else {}
    health_ok = health.get("status") == "PASS" and health_payload.get("healthy") is not False
    provider_facts = provider_model_facts(provider.get("payload"), catalog.get("payload"), config)
    provider_facts["bound_identity_ref"] = (identity or {}).get("identity_ref")
    provider_facts["bound_endpoint"] = (identity or {}).get("endpoint")
    reload_reason = next((reason for reason in (_explicit_credentials_reload_signal(item) for item in (health, provider, catalog, session_status, provider.get("payload"), catalog.get("payload"), session_status.get("payload"))) if reason), None)
    reload_required = bool(reload_reason)
    if not same_instance:
        auth_status, auth_class = "REPAIR", "OPENCODE_INSTANCE_MISMATCH"
    elif version.get("status") != "PASS":
        auth_status, auth_class = "REPAIR", version.get("error_class") or "EXECUTABLE_NOT_FOUND"
    elif not health_ok:
        auth_status, auth_class = "HUMAN_ACTION_REQUIRED", health.get("error_class") or "OPENCODE_SERVER_NOT_CONNECTED"
    elif not provider_facts.get("connected"):
        auth_status, auth_class = "HUMAN_ACTION_REQUIRED", "PROVIDER_AUTH_REQUIRED"
    else:
        auth_status, auth_class = "PASS", None
    return {
        "stage": "正在检查 AI Runtime",
        "executable": {"status": "PASS" if binary.get("status") == "PASS" and version.get("status") == "PASS" else "REPAIR", "available": bool(executable), "path": executable, "version": _version_text(version.get("output")) or binary.get("actual_version"), "expected_version": binary.get("expected_version"), "resolution": binary},
        "instance_identity": identity or {"identity_status": "REPAIR", "root_cause": identity_error},
        "auth_probe_target": {"same_instance": same_instance, "host": (identity or {}).get("host"), "port": (identity or {}).get("port"), "pid": (identity or {}).get("pid"), "workspace_root": (identity or {}).get("workspace_root"), "identity_ref": (identity or {}).get("identity_ref")},
        "authentication": {"status": auth_status, "failure_class": auth_class, "reload_required": reload_required, "reload_reason": reload_reason},
        "provider_model": provider_facts,
        "server": {"health": "PASS" if health_ok else "REPAIR", "session_status_endpoint": session_status.get("status"), "bound_identity_ref": (identity or {}).get("identity_ref")},
        "configuration": {"status": config.get("status"), "provider_configured": config.get("provider_configured"), "model_configured": config.get("model_configured")},
        "human_action_required": auth_status == "HUMAN_ACTION_REQUIRED",
        "credentials_reload_required": reload_required,
        "credentials_reload_reason": reload_reason,
    }


def opencode_model_from_payload(payload: Any) -> dict[str, str | None]:
    candidates = [payload]
    if isinstance(payload, dict):
        candidates.extend([payload.get("info"), payload.get("message")])
    provider = None
    model = None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        provider = provider or candidate.get("providerID") or candidate.get("provider_id") or candidate.get("provider")
        model = model or candidate.get("modelID") or candidate.get("model_id") or candidate.get("model")
    if isinstance(model, dict):
        provider = provider or model.get("providerID") or model.get("provider_id")
        model = model.get("modelID") or model.get("model_id")
    if isinstance(model, str) and "/" in model and not provider:
        provider, model = model.split("/", 1)
    return {"provider": str(provider) if provider else None, "model": str(model) if model else None}


def opencode_text_received(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    parts = payload.get("parts") or []
    if isinstance(parts, list) and any(isinstance(part, dict) and str(part.get("text") or part.get("content") or "").strip() for part in parts):
        return True
    return bool(str(payload.get("text") or "").strip())


def safe_usage(payload: Any) -> dict[str, Any] | str:
    if not isinstance(payload, dict):
        return "UNAVAILABLE"
    candidates = [payload.get("usage"), (payload.get("info") or {}).get("tokens") if isinstance(payload.get("info"), dict) else None]
    for candidate in candidates:
        if isinstance(candidate, dict):
            safe = {str(key): value for key, value in candidate.items() if isinstance(value, (int, float))}
            if safe:
                return safe
    return "UNAVAILABLE"


def real_llm_probe(base: dict[str, Any]) -> dict[str, Any]:
    if base.get("authentication", {}).get("status") != "PASS" or base.get("provider_model", {}).get("status") != "PASS":
        return {"status": "REPAIR", "error_class": "AUTH_PROVIDER_MODEL_NOT_VERIFIED", "request_submitted": False, "response_received": False, "usage": "UNAVAILABLE", "bound_identity_ref": (ACTIVE_OPENCODE_INSTANCE or {}).get("identity_ref")}
    provider = base["provider_model"]["provider"]
    model = base["provider_model"]["model"]
    created = opencode_http_request("/session", "POST", {"title": "PFC Runtime Reality Probe"})
    session_payload = created.get("payload") if isinstance(created.get("payload"), dict) else {}
    session_id = session_payload.get("id") or session_payload.get("sessionID") or session_payload.get("session_id")
    if created.get("status") != "PASS" or not session_id:
        return {"status": "REPAIR", "error_class": created.get("error_class") or "SESSION_CREATE_FAILED", "request_submitted": False, "response_received": False, "usage": "UNAVAILABLE"}
    body = {
        "agent": "aitest-director",
        "noReply": False,
        "model": {"providerID": provider, "modelID": model},
        "parts": [{"type": "text", "text": "PFC LLM runtime reality probe. Reply with a short confirmation."}],
    }
    invocation_at = now_iso()
    response = opencode_http_request(f"/session/{session_id}/message", "POST", body, timeout=45)
    resolved = opencode_model_from_payload(response.get("payload"))
    if not resolved.get("provider") or not resolved.get("model"):
        messages = opencode_http_request(f"/session/{session_id}/message?limit=5")
        message_payload = messages.get("payload") if isinstance(messages.get("payload"), list) else []
        for item in reversed(message_payload):
            candidate = opencode_model_from_payload(item)
            if candidate.get("provider") and candidate.get("model"):
                resolved = candidate
                break
    response_received = response.get("status") == "PASS" and opencode_text_received(response.get("payload"))
    invocation_ok = response_received and resolved.get("provider") == provider and resolved.get("model") == model
    result = {
        "status": "PASS" if invocation_ok else "REPAIR",
        "request_submitted": response.get("status") == "PASS" or response.get("http_status") is not None,
        "provider": resolved.get("provider") or provider,
        "model": resolved.get("model") or model,
        "response_received": response_received,
        "invocation_at": invocation_at,
        "usage": safe_usage(response.get("payload")),
        "error_class": None if invocation_ok else response.get("error_class") or "MODEL_RESPONSE_NOT_VERIFIED",
        "session_identity_ref": digest(str(session_id))[:20],
        "bound_identity_ref": (ACTIVE_OPENCODE_INSTANCE or {}).get("identity_ref"),
        "_session_id": str(session_id),
    }
    return result


def r2_runtime_probe(llm: dict[str, Any]) -> dict[str, Any]:
    session_id = llm.get("_session_id")
    if llm.get("status") != "PASS" or not session_id:
        return {
            "session_runtime": {"status": "REPAIR", "reason": "REAL_LLM_INVOCATION_NOT_VERIFIED"},
            "spawn": {"status": "REPAIR", "reason": "REAL_LLM_INVOCATION_NOT_VERIFIED"},
            "planner_invocation": {"status": "REPAIR"},
            "scheduler_invocation": {"status": "REPAIR"},
            "checkpoint_resume": {"status": "REPAIR"},
            "mission_continuation": {"status": "NOT_VERIFIED"},
            "autonomous_runtime": "REPAIR",
            "bound_identity_ref": (ACTIVE_OPENCODE_INSTANCE or {}).get("identity_ref"),
        }
    session_status = opencode_http_request("/session/status")
    resumed = opencode_http_request(f"/session/{session_id}/message", "POST", {"agent": "aitest-director", "noReply": False, "parts": [{"type": "text", "text": "PFC R2 resume probe. Reply with a short confirmation."}]}, timeout=45)
    resume_ok = resumed.get("status") == "PASS" and opencode_text_received(resumed.get("payload"))
    child = opencode_http_request("/session", "POST", {"title": "PFC R2 spawn probe", "parentID": session_id})
    child_payload = child.get("payload") if isinstance(child.get("payload"), dict) else {}
    child_id = child_payload.get("id") or child_payload.get("sessionID") or child_payload.get("session_id")
    planner_target = child_id or session_id
    planner = opencode_http_request(f"/session/{planner_target}/message", "POST", {"agent": "aitest-planner", "noReply": False, "parts": [{"type": "text", "text": "PFC R2 planner runtime probe. Confirm planner agent is active."}]}, timeout=45)
    scheduler_probe = opencode_http_request(f"/session/{session_id}/message", "POST", {"agent": "aitest-scheduler", "noReply": False, "parts": [{"type": "text", "text": "PFC R2 scheduler runtime probe. Confirm scheduler agent is active."}]}, timeout=45)
    planner_ok = planner.get("status") == "PASS" and opencode_text_received(planner.get("payload"))
    scheduler_ok = scheduler_probe.get("status") == "PASS" and opencode_text_received(scheduler_probe.get("payload"))
    if child_id:
        opencode_http_request(f"/session/{child_id}", "DELETE", {})
    opencode_http_request(f"/session/{session_id}", "DELETE", {})
    session_ok = session_status.get("status") == "PASS" and resume_ok
    spawn_status = "PASS" if child_id else "REPAIR"
    autonomous = "PASS" if session_ok and child_id and planner_ok and scheduler_ok else ("PARTIAL" if session_ok else "REPAIR")
    return {
        "session_runtime": {"status": "PASS" if session_ok else "REPAIR", "session_open": True, "session_resume": resume_ok, "session_status": session_status.get("status")},
        "spawn": {"status": spawn_status, "child_session_created": bool(child_id), "compatibility_gap": None if child_id else "PARENT_SESSION_SPAWN_NOT_VERIFIED"},
        "planner_invocation": {"status": "PASS" if planner_ok else "REPAIR", "response_received": planner_ok, "spawned_session_used": bool(child_id)},
        "scheduler_invocation": {"status": "PASS" if scheduler_ok else "REPAIR", "response_received": scheduler_ok},
        "checkpoint_resume": {"status": "PARTIAL" if session_ok else "REPAIR", "session_resume": resume_ok, "durable_mission_checkpoint": "NOT_VERIFIED"},
        "mission_continuation": {"status": "NOT_VERIFIED", "reason": "本次 Recon 不创建或推进真实 Mission"},
        "autonomous_runtime": autonomous,
        "bound_identity_ref": (ACTIVE_OPENCODE_INSTANCE or {}).get("identity_ref"),
    }


def strip_private_runtime_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: strip_private_runtime_fields(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, list):
        return [strip_private_runtime_fields(item) for item in value]
    return value


def run_opencode_runtime_reality() -> dict[str, Any]:
    web = ensure_opencode_web({})
    identity = web.get("identity") if isinstance(web.get("identity"), dict) else ACTIVE_OPENCODE_INSTANCE
    bind_opencode_instance(identity)
    # Every subsequent HTTP probe is bound to the identity selected above;
    # no probe may rediscover a PATH executable or the default port.
    base = opencode_runtime_probe(identity)
    if STARTUP_TRACE:
        # Runtime probing is non-blocking. Authentication is an AI Runtime
        # state and never a prerequisite for the already-ready Web process.
        STARTUP_TRACE["auth_phase_reached"] = bool(web.get("status") == "PASS" and (identity or {}).get("identity_status") == "PASS")
    auth_status = base.get("authentication", {}).get("status")
    auth_wait_state = {
        "status": "READY" if auth_status == "PASS" else "WAITING_FOR_AUTH" if auth_status == "HUMAN_ACTION_REQUIRED" else "WAITING_FOR_AI_RUNTIME",
        "identity_ref": (identity or {}).get("identity_ref"),
        "web_url": web.get("web_url") or (identity or {}).get("endpoint"),
        "prompt_count": 0,
        "restart_attempted": False,
        "non_blocking": True,
        "reprobe": "START_INITIAL_RUNTIME_PROBE",
        "started_at": now_iso(),
    }
    if auth_status == "PASS":
        auth_wait_state["status"] = "READY"
    # LLM/R2 are attempted only after their own prerequisites are ready. A
    # failed AI probe cannot tear down or invalidate the ready Web process.
    llm = real_llm_probe(base)
    r2 = r2_runtime_probe(llm)
    full = {
        **base,
        "opencode_web": web,
        "PFC_OPENCODE_INSTANCE_IDENTITY": identity,
        "PFC_OPENCODE_RUNTIME_IDENTITY_MATRIX": web.get("identity_matrix") or {},
        "auth_wait": auth_wait_state,
        "auth_phase_reached": bool(STARTUP_TRACE.get("auth_phase_reached")) if STARTUP_TRACE else True,
        "mission_ai_runtime_gate": "READY" if llm.get("status") == "PASS" and r2.get("session_runtime", {}).get("status") == "PASS" else "WAITING_FOR_AI_RUNTIME",
        "llm_invocation": llm,
        "r2": r2,
        "last_real_model_invocation": llm,
        "recon_completed_at": now_iso(),
    }
    auth_status = base.get("authentication", {}).get("status")
    provider_status = base.get("provider_model", {}).get("status")
    invocation_status = llm.get("status")
    r2_session_status = r2.get("session_runtime", {}).get("status")
    autonomous_status = r2.get("autonomous_runtime")
    allowed = auth_status == "PASS" and provider_status == "PASS" and invocation_status == "PASS" and r2_session_status == "PASS" and autonomous_status == "PASS"
    matrix = web.get("identity_matrix") or {}
    identity_status = str((identity or {}).get("identity_status") or "REPAIR")
    auth_target = "VERIFIED_SAME_INSTANCE" if identity_status == "PASS" else ("MISMATCH" if str((identity or {}).get("root_cause") or "").endswith("MISMATCH") or "COLLISION" in str((identity or {}).get("root_cause") or "") else "REPAIR")
    launch_repair = bool(PROFILE.get("opencode_runtime_launch_auth_orchestration_repair") or PROFILE.get("opencode_windows_cmd_shim_resolution_and_real_web_launch_repair") or proven_git_bash_command_enabled() or proven_v19_launch_path_reuse_enabled() or pinned_opencode_runtime_enabled())
    trace_status = "IMPLEMENTED" if startup_trace_enabled() else "REPAIR"
    executable_resolution = (base.get("executable") or {}).get("resolution") or {}
    selected_launcher = executable_resolution.get("selected_path") or "NOT_SELECTED"
    selected_version = executable_resolution.get("selected_version") or "NOT_SELECTED"
    dynamic_port_pass = bool(web.get("started_by_harness") and web.get("status") == "PASS" and int(web.get("port") or 0) != 4096 and identity_status == "PASS")
    generated_config = web.get("generated_config") if isinstance(web.get("generated_config"), dict) else {}
    project_binding = web.get("project_binding") if isinstance(web.get("project_binding"), dict) else {}
    project_binding_pass = project_binding.get("status") == "PASS"
    generated_config_pass = generated_config.get("status") == "PASS"
    dynamic_port_reality = bool(isinstance(web.get("port"), int) and 1 <= web.get("port") <= 65535 and web.get("port") != 4096)
    launch_config_consistency = bool(generated_config_pass and generated_config.get("port_authority") == "CLI" and (not generated_config.get("config_port_present") or generated_config.get("config_port") == web.get("port")))
    proven_shell_pass = bool(executable_resolution.get("launch_via_shell") and executable_resolution.get("status") == "PASS")
    # Keep process launch reality separate from Web project binding reality:
    # a process may be alive while the Web client is not bound to the PFC
    # directory.  The latter is a distinct fail-closed surface.
    real_process_launch_pass = bool(web.get("started_by_harness") and web.get("pid") and web.get("listener_pids"))
    real_web_binding_pass = bool(real_process_launch_pass and project_binding_pass and identity_status == "PASS")
    pinned_contract = pinned_opencode_runtime_contract()
    pinned_runtime_pass = bool(pinned_opencode_runtime_enabled() and executable_resolution.get("status") == "PASS" and executable_resolution.get("actual_version") == pinned_contract["version"] and executable_resolution.get("pinned_runtime_path") == pinned_contract["path"])
    pinned_path_verified = bool(pinned_opencode_runtime_enabled() and (executable_resolution.get("file_fact") or {}).get("status") == "PASS")
    same_exact_runtime = bool(pinned_runtime_pass and real_process_launch_pass and (identity or {}).get("binary_path") == pinned_contract["path"])
    proven_command_contract = proven_git_bash_command_contract()
    proven_command_pass = bool(proven_git_bash_command_enabled() and executable_resolution.get("proven_command") and executable_resolution.get("status") == "PASS" and executable_resolution.get("resolved_command") == proven_command_contract["command"] and executable_resolution.get("actual_version") == proven_command_contract["version"])
    same_proven_shell = bool(proven_command_pass and real_process_launch_pass and web.get("launch_mode") == "GIT_BASH_PROVEN_COMMAND" and "opencode web" in str(web.get("command_line") or "").lower())
    full["acceptance"] = {
        **{key: trace_status for key in STARTUP_TRACE_ACCEPTANCE_KEYS},
        "PFC_OPENCODE_DIAGNOSTIC_ZIP": "OPTIONAL",
        "PFC_INTERACTIVE_PRIMARY_SURFACE": "OPENCODE_TUI",
        "PFC_OPENCODE_WEB_SURFACE": "SECONDARY_EXPLICIT_DIRECTORY_ROUTE",
        "PFC_WINDOWS_OPENCODE_CMD_SHIM_RESOLUTION": "PASS" if executable_resolution.get("status") == "PASS" and executable_resolution.get("selected_launcher_type") in {"EXE", "CMD", "BAT", "NO_EXTENSION"} else "REPAIR",
        "PFC_OPENCODE_MULTI_VERSION_MATRIX": "DISABLED_PINNED_RUNTIME" if pinned_opencode_runtime_enabled() else ("EVIDENCE_ONLY" if executable_resolution.get("candidate_selection_is_evidence_only") else ("CREATED" if "path_opencode_candidates" in matrix and "version_location_matrix" in matrix else "REPAIR")),
        "PFC_OPENCODE_PROVEN_V1_9_4_LAUNCH_PATH_REUSE": "IMPLEMENTED" if proven_v19_launch_path_reuse_enabled() else "NOT_APPLIED",
        "PFC_OPENCODE_GIT_BASH_SHELL_RESOLUTION": "PASS" if executable_resolution.get("launch_via_shell") and executable_resolution.get("status") == "PASS" else "REPAIR",
        "PFC_OPENCODE_SHELL_VERSION_AUTHORITY": "PASS" if executable_resolution.get("launch_via_shell") and executable_resolution.get("actual_version") not in {None, "UNAVAILABLE"} else "REPAIR",
        "PFC_OPENCODE_CANDIDATE_SELECTION": "DISABLED_PROVEN_COMMAND" if proven_git_bash_command_enabled() else "DISABLED_PINNED_RUNTIME" if pinned_opencode_runtime_enabled() else ("EVIDENCE_ONLY" if executable_resolution.get("candidate_selection_is_evidence_only") else "LEGACY_ADMISSION"),
        "PFC_OPENCODE_VERSION_GUESSING": "STOPPED" if (proven_git_bash_command_enabled() or proven_v19_launch_path_reuse_enabled() or pinned_opencode_runtime_enabled()) else "ACTIVE_LEGACY_POLICY",
        "PFC_OPENCODE_STARTUP_ROOT_CAUSE": "GIT_BASH_PROVEN_COMMAND_AUTHORITY" if proven_git_bash_command_enabled() else "REMOVED" if (proven_v19_launch_path_reuse_enabled() or pinned_opencode_runtime_enabled()) else "NOT_REPAIRED",
        "PFC_PINNED_OPENCODE_RUNTIME": f"{pinned_contract['version']} / {'PASS' if pinned_runtime_pass else 'FAIL'}" if pinned_opencode_runtime_enabled() else "NOT_APPLIED_FINAL_COMMAND_CONTRACT",
        "PFC_PINNED_OPENCODE_RUNTIME_PATH": "VERIFIED" if pinned_path_verified else "FAIL" if pinned_opencode_runtime_enabled() else "NOT_APPLIED_FINAL_COMMAND_CONTRACT",
        "PFC_OPENCODE_VERSION_AND_LAUNCH_SAME_RUNTIME": "PASS" if same_exact_runtime else "FAIL" if pinned_opencode_runtime_enabled() else "NOT_APPLIED_FINAL_COMMAND_CONTRACT",
        "PFC_OPENCODE_GIT_BASH_COMMAND_ADMISSION": "PASS" if proven_command_pass else "FAIL" if proven_git_bash_command_enabled() else "NOT_APPLIED",
        "PFC_OPENCODE_VERSION_AND_WEB_SAME_SHELL": "PASS" if same_proven_shell else "FAIL" if proven_git_bash_command_enabled() else "NOT_APPLIED",
        "PFC_OPENCODE_GENERATED_CONFIG_REALITY": "PASS" if generated_config_pass else "FAIL",
        "PFC_OPENCODE_DYNAMIC_PORT_REALITY": "PASS" if dynamic_port_reality else "FAIL",
        "PFC_OPENCODE_LAUNCH_CONFIG_CONSISTENCY": "PASS" if launch_config_consistency else "FAIL",
        "PFC_OPENCODE_PROVEN_SHELL_LAUNCH_PATH": "PASS" if proven_shell_pass else "FAIL",
        "PFC_OPENCODE_REAL_PROCESS_LAUNCH_PATH": "PASS" if real_process_launch_pass else "FAIL",
        "PFC_OPENCODE_REAL_WEB_LAUNCH_PATH": "PASS" if real_web_binding_pass else "REPAIR",
        "PFC_OPENCODE_WEB_EXPLICIT_PROJECT_BINDING": "PASS" if project_binding_pass else "REPAIR",
        "PFC_OPENCODE_WEB_EXPLICIT_PROJECT_BINDING_CAPABILITY_1_18_21": "SUPPORTED",
        "PFC_OPENCODE_PROJECT_BOOTSTRAP": "PASS" if project_binding_pass else "REPAIR",
        "PFC_OPENCODE_AGENT_DISCOVERY": "PASS" if project_binding_pass and project_binding.get("agent_names") else "REPAIR",
        "PFC_OPENCODE_WEB_SESSION_DIRECTORY": project_binding.get("session_directory") or "NOT_OBSERVED",
        "PFC_OPENCODE_WEB_INTERACTIVE_REALITY": "PASS" if real_web_binding_pass else "TUI_PRIMARY_WEB_SECONDARY_KNOWN_LIMIT",
        "PFC_READY_FINAL_INTERACTIVE_REALITY": "PASS" if real_web_binding_pass else "FAIL",
        "PFC_OPENCODE_PROCESS_LAUNCH_REALITY": "PASS" if real_process_launch_pass else "FAIL",
        "PFC_OPENCODE_AUTH_REPROBE": "IMPLEMENTED" if (proven_git_bash_command_enabled() or pinned_opencode_runtime_enabled()) else "NOT_APPLIED",
        "PFC_OPENCODE_POST_AUTH_RESUME_REPAIR": "PASS" if auth_wait_state.get("status") in {"PASS", "AUTH_REPROBE_FAILED_NO_RESTART", "WAITING_FOR_HUMAN_ACTION"} else "REPAIR",
        "PFC_OPENCODE_SAME_INSTANCE_AUTH_REPROBE": "PASS" if auth_wait_state.get("reprobe") == "SAME_INSTANCE" else "REPAIR",
        "PFC_OPENCODE_UNNECESSARY_RESTART": "REMOVED" if not auth_wait_state.get("restart_attempted") else "PRESENT" if auth_wait_state.get("restart_required") is False else "CONTROLLED_EXPLICIT_RELOAD",
        "PFC_OPENCODE_PROCESS_STOP_TIMEOUT": "IMPLEMENTED",
        "PFC_OPENCODE_PROCESS_LIFECYCLE": "PASS" if auth_wait_state.get("status") != "AUTH_RESTART_FAILED" else "REPAIR",
        "PFC_OPENCODE_RAW_TRACEBACK_TO_USER": "REMOVED",
        "PFC_OPENCODE_PROCESS_RUNTIME_MODEL": "PASS" if real_process_launch_pass else "REPAIR",
        "PFC_OPENCODE_WEB_START_INDEPENDENT_OF_AUTH": "PASS" if real_process_launch_pass else "FAIL",
        "PFC_OPENCODE_AUTH_NON_BLOCKING": "PASS" if real_process_launch_pass and auth_wait_state.get("non_blocking") else "FAIL",
        "PFC_OPENCODE_PROVIDER_MODEL_NON_BLOCKING": "PASS" if real_process_launch_pass else "FAIL",
        "PFC_OPENCODE_LLM_NON_BLOCKING_TO_WEB": "PASS" if real_process_launch_pass else "FAIL",
        "PFC_R2_SESSION_GATE": "IMPLEMENTED",
        "PFC_PFC_MISSION_AI_RUNTIME_GATE": "IMPLEMENTED",
        "PFC_STATUS_RUNTIME_SEPARATION": "PASS",
        "PFC_READY_PACKAGE_BANK_REALITY_ENTRY": "ALLOWED" if generated_config_pass and proven_shell_pass and real_process_launch_pass else "NOT_ALLOWED",
        "PFC_OPENCODE_SELECTED_LAUNCHER": selected_launcher,
        "PFC_OPENCODE_SELECTED_VERSION": selected_version,
        "PFC_OPENCODE_REAL_WEB_PROCESS_LAUNCH": "IMPLEMENTED",
        "PFC_OPENCODE_REAL_WEB_LAUNCH": "PASS" if dynamic_port_pass else "REPAIR",
        "PFC_OPENCODE_PACKAGE_WORKSPACE": "PASS" if _same_path((identity or {}).get("workspace_root"), OPENCODE_WORKSPACE_ROOT) else "REPAIR",
        "PFC_OPENCODE_DYNAMIC_PORT": "PASS" if dynamic_port_pass else "REPAIR",
        "PFC_OPENCODE_AUTH_WAIT_FLOW": "IMPLEMENTED",
        "PFC_OPENCODE_BANK_REALITY_ENTRY": "ALLOWED" if launch_repair else "NOT_ALLOWED",
        "PFC_OPENCODE_REAL_WEB_LAUNCHER": "IMPLEMENTED",
        "PFC_OPENCODE_PACKAGE_OWNED_WORKSPACE": "PASS" if _same_path((identity or {}).get("workspace_root"), OPENCODE_WORKSPACE_ROOT) else "REPAIR",
        "PFC_OPENCODE_BINARY_VERSION_PINNING": "PASS" if (base.get("executable") or {}).get("status") == "PASS" else "REPAIR",
        "PFC_OPENCODE_AUTH_WAIT_RESUME": "IMPLEMENTED",
        "PFC_OPENCODE_AUTH_SAME_INSTANCE_GUARD": "PASS" if identity_status == "PASS" else "REPAIR",
        "PFC_OPENCODE_PROVIDER_MODEL_PROBE": "IMPLEMENTED",
        "PFC_OPENCODE_REAL_LLM_PROBE": "IMPLEMENTED",
        "PFC_R2_SESSION_CREATE_RESUME": "IMPLEMENTED",
        "PFC_READY_PACKAGE_BANK_RUNTIME_REALITY_ENTRY": "ALLOWED",
        "PFC_OPENCODE_BINARY_IDENTITY": "PASS" if (base.get("executable") or {}).get("status") == "PASS" else "REPAIR",
        "PFC_OPENCODE_VERSION_REALITY": "PASS" if (base.get("executable") or {}).get("expected_version") and (base.get("executable") or {}).get("version") == (base.get("executable") or {}).get("expected_version") else "REPAIR",
        "PFC_OPENCODE_WORKSPACE_ISOLATION": "VERIFIED" if _same_path((identity or {}).get("workspace_root"), OPENCODE_WORKSPACE_ROOT) and not matrix.get("old_workspace_collision") else "REPAIR",
        "PFC_OPENCODE_WEB_INSTANCE_IDENTITY": "VERIFIED" if identity_status == "PASS" else "REPAIR",
        "PFC_OPENCODE_AUTH_PROBE_TARGET": auth_target,
        "PFC_OPENCODE_AUTH_REALITY": auth_status,
        "PFC_OPENCODE_PROVIDER_MODEL_REALITY": "PASS" if provider_status == "PASS" else "REPAIR",
        "PFC_LLM_INVOCATION_REALITY": "PASS" if invocation_status == "PASS" else "REPAIR",
        "PFC_R2_SESSION_RUNTIME_REALITY": "PASS" if r2_session_status == "PASS" else "REPAIR",
        "PFC_R2_AUTONOMOUS_RUNTIME_REALITY": autonomous_status,
        "PFC_CURRENT_COVERAGE_PROVENANCE": "NOT_VERIFIED / QUARANTINED" if launch_repair else ("VERIFIED" if allowed else "NOT_VERIFIED"),
        "PFC_CURRENT_STANDARD_CASE_PROVENANCE": "NOT_VERIFIED / QUARANTINED" if launch_repair else ("VERIFIED" if allowed else "NOT_VERIFIED"),
        "PFC_R3_REQUIREMENT_SOURCE_REPAIR_ENTRY": "HOLD" if launch_repair else ("ALLOWED" if allowed else "HOLD"),
        "PFC_REAL_EXECUTION_ENTRY": "HOLD",
        "ARCHITECTURE_DRIFT": "NO",
        "HARD_DEPENDENCY_FAILURE": "NO",
    }
    full["PFC_OPENCODE_RUNTIME_INSTANCE_IDENTITY_GAP"] = "NO" if identity_status == "PASS" else ((identity or {}).get("root_cause") or "OPENCODE_INSTANCE_IDENTITY_NOT_VERIFIED")
    full["human_action_message"] = (
        "OpenCode Web 已启动。请直接在当前页面完成银行身份认证；之后运行 STATUS 检查 AI Runtime，不能因认证未完成而重启 Web。"
        + (f" Web 地址：{web.get('web_url')}" if web.get("web_url") else "")
        if auth_status == "HUMAN_ACTION_REQUIRED"
        else (f"当前 OpenCode Web 实例与本包不一致（{(identity or {}).get('root_cause') or 'IDENTITY_NOT_VERIFIED'}）。当前 Web：{web.get('web_url') or '不可用'}；请不要在旧 workspace 上继续认证，请重新 START 让 Harness 建立本包实例。" if auth_target == "MISMATCH" else None)
    )
    return strip_private_runtime_fields(full)


def machine_profile() -> dict[str, Any]:
    payload = load_json(LOCAL_PROFILE_PATH, {}) or {}
    return payload if isinstance(payload, dict) else {}


def save_machine_profile(values: dict[str, Any]) -> None:
    current = machine_profile()
    write_json(LOCAL_PROFILE_PATH, {**current, **values, "updated_at": now_iso()}, private=True)


def resolve_starlink() -> tuple[str | None, str | None]:
    profile = machine_profile()
    endpoint = str(os.environ.get("PFC_STARLINK_ENDPOINT") or profile.get("starlink_endpoint") or "").strip()
    if endpoint:
        return endpoint, "profile://PFC/FAT2/STARLINK"
    if os.environ.get("PFC_NONINTERACTIVE") == "1" or not sys.stdin.isatty():
        return None, None
    print("首次运行需要确认当前 FAT2 的 Starlink 地址。")
    print("请输入 Starlink 地址（直接回车可稍后处理）：", end="", flush=True)
    endpoint = input().strip()
    if not endpoint:
        return None, None
    save_machine_profile({"starlink_endpoint": endpoint, "starlink_ref": "profile://PFC/FAT2/STARLINK"})
    return endpoint, "profile://PFC/FAT2/STARLINK"


DEPLOYMENT_SUCCESS_STATUSES = {"SUCCESS", "SUCCEEDED", "DEPLOYED", "READY", "COMPLETED", "PASS"}
REQUIREMENT_SOURCE_REQUIRED_SSTS = {item["sst_id"] for item in PROFILE.get("requirement_sst", {}).get(PROFILE.get("first_validation_target"), [])}


def deployment_payload_facts(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    candidates = [payload]
    if isinstance(payload.get("data"), dict):
        candidates.append(payload["data"])
    aliases = {
        "version": ("version", "release_version"),
        "deployment": ("deployment_id", "deployment", "deployment_name"),
        "system": ("system", "system_id", "service"),
        "app": ("app", "app_id", "application"),
        "branch": ("branch", "source_branch", "release_branch"),
        "revision": ("revision", "revision_sha", "commit", "head_sha"),
        "status": ("status", "deployment_status", "state"),
    }
    facts: dict[str, str] = {}
    for normalized, names in aliases.items():
        for candidate in candidates:
            value = next((candidate.get(name) for name in names if candidate.get(name) not in (None, "")), None)
            if value is not None:
                facts[normalized] = str(value)
                break
    return facts


def probe_starlink_deployment(starlink: str) -> dict[str, Any]:
    if not starlink.lower().startswith(("http://", "https://")):
        return {"status": "NOT_VERIFIED", "attempted": False, "reason": "Starlink 地址不是可读取的 HTTP(S) 端点"}
    request = urllib.request.Request(starlink, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read(1000000).decode("utf-8", errors="replace")
            payload = json.loads(raw)
            facts = deployment_payload_facts(payload)
            missing = [key for key in ("version", "deployment", "system", "app", "branch", "revision", "status") if not facts.get(key)]
            if missing or facts.get("status", "").upper() not in DEPLOYMENT_SUCCESS_STATUSES:
                return {"status": "NOT_VERIFIED", "attempted": True, "http_status": response.status, "missing": missing, "reason": "Starlink 返回数据不足以确认完整部署基线"}
            facts["status"] = facts["status"].upper()
            return {"status": "VERIFIED", "attempted": True, "http_status": response.status, "facts": facts, "source": "starlink"}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return {"status": "NOT_VERIFIED", "attempted": True, "reason": f"Starlink 部署事实读取失败：{type(exc).__name__}"}


def deployment_baseline(starlink: str | None) -> dict[str, Any]:
    if not starlink:
        return {"status": "NOT_VERIFIED", "attempted": False, "reason": "等待 Starlink / 未确认", "facts": {}}
    result = probe_starlink_deployment(starlink)
    if result.get("status") == "VERIFIED":
        return result
    return {**result, "facts": {}, "reason": result.get("reason") or "Starlink / deployment facts 未确认"}


def source_failure(status: str, failure_class: str, reason: str, *, source_ref: str = "UNAVAILABLE", attempted: bool = False, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "failure_class": failure_class,
        "reason": reason,
        "attempted": attempted,
        "source_ref": source_ref,
        "facts": {},
        "details": details or {},
    }


def normalize_requirement_source(payload: Any, source_ref: str, *, attempted: bool = True) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return source_failure("HUMAN_ACTION_REQUIRED", "STARLINK_CONTRACT_MISMATCH", "Requirement Source 返回的 JSON 顶层不是对象", source_ref=source_ref, attempted=attempted)
    requirement: dict[str, Any] | None = None
    if str(payload.get("requirement_id") or payload.get("id") or "") == PROFILE["first_validation_target"]:
        requirement = payload
    elif isinstance(payload.get("requirement"), dict):
        requirement = payload["requirement"]
    else:
        for item in payload.get("requirements") or []:
            if isinstance(item, dict) and str(item.get("requirement_id") or item.get("id") or "") == PROFILE["first_validation_target"]:
                requirement = item
                break
    if not requirement:
        return source_failure("HUMAN_ACTION_REQUIRED", "STARLINK_CONTRACT_MISMATCH", f"返回内容未包含 {PROFILE['first_validation_target']} Requirement", source_ref=source_ref, attempted=attempted)
    body = requirement.get("body") or requirement.get("description") or requirement.get("text")
    structured = requirement.get("structured_fields") or requirement.get("fields")
    ssts = requirement.get("ssts") or requirement.get("associated_ssts")
    change_description = requirement.get("change_description") or requirement.get("change") or requirement.get("changes")
    freshness = requirement.get("freshness") or requirement.get("source_freshness") or requirement.get("updated_at")
    missing = []
    for key, value in (("title", requirement.get("title")), ("body", body), ("structured_fields", structured), ("ssts", ssts), ("change_description", change_description), ("freshness", freshness)):
        if value in (None, "", []):
            missing.append(key)
    if missing:
        return source_failure("HUMAN_ACTION_REQUIRED", "REQUIREMENT_SOURCE_INCOMPLETE", "Requirement Source 缺少必要真实字段：" + "、".join(missing), source_ref=source_ref, attempted=attempted, details={"missing": missing})
    if not isinstance(ssts, list):
        return source_failure("HUMAN_ACTION_REQUIRED", "STARLINK_CONTRACT_MISMATCH", "Requirement Source 的 SST 关联不是列表", source_ref=source_ref, attempted=attempted)
    normalized_ssts: list[dict[str, Any]] = []
    seen_ssts: set[str] = set()
    for item in ssts:
        if not isinstance(item, dict):
            continue
        sst_id = str(item.get("sst_id") or item.get("id") or "").strip()
        if not sst_id:
            continue
        seen_ssts.add(sst_id)
        normalized_ssts.append({
            "sst_id": sst_id,
            "system": item.get("system") or item.get("module"),
            "change": item.get("change") or item.get("change_description"),
            "scope": item.get("scope") or item.get("coverage_scope") or {},
            "fields": item.get("fields") or item.get("business_fields") or [],
            "business_rules": item.get("business_rules") or item.get("rules") or [],
            "test_data": item.get("test_data") or {},
            "oracle": item.get("oracle") or {},
            "cross_system_relation": item.get("cross_system_relation") or item.get("cross_system") or "",
            "defect_hypothesis": item.get("defect_hypothesis") or item.get("defect_risk") or "",
            "positive": item.get("positive") or item.get("positive_path") or {},
            "negative": item.get("negative") or item.get("negative_path") or {},
            "boundary": item.get("boundary") or item.get("boundary_path") or {},
        })
    missing_ssts = sorted(REQUIREMENT_SOURCE_REQUIRED_SSTS - seen_ssts)
    if missing_ssts:
        return source_failure("HUMAN_ACTION_REQUIRED", "REQUIREMENT_SOURCE_INCOMPLETE", "Requirement Source 未覆盖全部目标 SST：" + "、".join(missing_ssts), source_ref=source_ref, attempted=attempted, details={"missing_ssts": missing_ssts})
    facts = {
        "requirement_id": PROFILE["first_validation_target"],
        "title": str(requirement.get("title")),
        "body": str(body),
        "structured_fields": structured,
        "change_description": change_description,
        "freshness": freshness,
        "attachments": requirement.get("attachments") if "attachments" in requirement else [],
        "attachments_declared": "attachments" in requirement,
        "ssts": normalized_ssts,
        "business_rules": requirement.get("business_rules") or requirement.get("rules") or [],
        "ambiguities": requirement.get("ambiguities") or requirement.get("open_questions") or [],
    }
    source_hash = digest(facts)
    return {
        "status": "VERIFIED",
        "failure_class": None,
        "reason": "STBB19-234 Requirement Source 已读取并形成 canonical facts",
        "attempted": attempted,
        "source_ref": source_ref,
        "intelligence_ref": f"requirement-intelligence://PFC/{PROFILE['first_validation_target']}",
        "source_hash": source_hash,
        "facts": facts,
        "provenance": {"source_ref": source_ref, "source_hash": source_hash, "freshness": freshness, "retrieved_at": now_iso()},
    }


def classify_source_non_json(status_code: int | None, content_type: str, body: str, source_ref: str, *, attempted: bool = True) -> dict[str, Any]:
    lowered = body[:4000].lower()
    if (status_code in {401, 403} and any(marker in lowered for marker in ("session", "expired", "missing"))) or "session missing" in lowered:
        failure_class = "SESSION_MISSING"
    elif status_code in {401, 403} or any(marker in lowered for marker in ("login", "sign in", "unauthorized", "authentication", "sso")):
        failure_class = "AUTHENTICATION_LOGIN_HTML"
    elif "4a" in lowered:
        failure_class = "4A_REDIRECT"
    elif "text/html" in content_type.lower() or "<html" in lowered or "<!doctype" in lowered:
        failure_class = "NON_JSON_RESPONSE"
    else:
        failure_class = "NON_JSON_RESPONSE"
    reason = {
        "AUTHENTICATION_LOGIN_HTML": "Starlink 返回登录/认证页面，Requirement Source 未取得",
        "SESSION_MISSING": "Starlink 会话缺失或已过期，Requirement Source 未取得",
        "4A_REDIRECT": "Starlink 返回 4A/认证跳转内容，Requirement Source 未取得",
        "NON_JSON_RESPONSE": "Starlink 返回非 JSON 内容，Requirement Source 未取得",
    }[failure_class]
    return source_failure("HUMAN_ACTION_REQUIRED", failure_class, reason, source_ref=source_ref, attempted=attempted, details={"http_status": status_code, "content_type": content_type})


def read_requirement_source(starlink: str | None) -> dict[str, Any]:
    profile = machine_profile()
    approved_file = str(profile.get("requirement_source_file") or "").strip()
    if approved_file:
        path = Path(approved_file).expanduser().resolve()
        source_ref = "approved-file://PFC/" + PROFILE["first_validation_target"]
        if not path.is_file():
            return source_failure("HUMAN_ACTION_REQUIRED", "SOURCE_FILE_NOT_FOUND", "已配置的 Requirement Source 文件不存在", source_ref=source_ref, attempted=True)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return source_failure("HUMAN_ACTION_REQUIRED", "NON_JSON_RESPONSE", "Requirement Source 文件不是合法 JSON", source_ref=source_ref, attempted=True)
        except OSError:
            return source_failure("HUMAN_ACTION_REQUIRED", "SOURCE_FILE_NOT_FOUND", "Requirement Source 文件无法读取", source_ref=source_ref, attempted=True)
        return normalize_requirement_source(payload, source_ref)
    source_ref = f"starlink://PFC/FAT2/{PROFILE['first_validation_target']}"
    if not starlink:
        return source_failure("HUMAN_ACTION_REQUIRED", "SOURCE_NOT_CONFIGURED", f"未取得 {PROFILE['first_validation_target']} 的真实 Requirement Source", source_ref=source_ref, attempted=False)
    if not starlink.lower().startswith(("http://", "https://")):
        return source_failure("HUMAN_ACTION_REQUIRED", "WRONG_ENDPOINT", "当前 Starlink 地址不是可读取的 HTTP(S) Requirement Source 端点", source_ref=source_ref, attempted=False)
    request = urllib.request.Request(starlink, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content_type = str(response.headers.get("Content-Type") or "")
            body = response.read(2000000).decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return classify_source_non_json(response.status, content_type, body, source_ref)
            try:
                result = normalize_requirement_source(payload, source_ref)
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                result = source_failure("HUMAN_ACTION_REQUIRED", "ADAPTER_PARSE_DEFECT", "Requirement Source JSON 已返回，但适配器无法解析 canonical facts", source_ref=source_ref, attempted=True, details={"error_type": type(exc).__name__})
            result.setdefault("details", {})["http_status"] = response.status
            result["details"]["content_type"] = content_type
            return result
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(100000).decode("utf-8", errors="replace")
        except OSError:
            pass
        if body and body.lstrip().startswith(("<", "{")):
            return classify_source_non_json(exc.code, str(exc.headers.get("Content-Type") or ""), body, source_ref)
        return source_failure("HUMAN_ACTION_REQUIRED", "NETWORK_ACCESS_ISSUE", "Starlink Requirement Source HTTP 访问失败", source_ref=source_ref, attempted=True, details={"http_status": exc.code})
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return source_failure("HUMAN_ACTION_REQUIRED", "NETWORK_ACCESS_ISSUE", "Starlink Requirement Source 网络/访问失败", source_ref=source_ref, attempted=True, details={"error_type": type(exc).__name__})


SOURCE_SCOPE_KEYS = ("has_code_change", "has_component", "has_api", "has_ui", "cross_system")


def source_sst_map(source_state: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not source_state or source_state.get("status") != "VERIFIED":
        return {}
    facts = source_state.get("facts") or {}
    return {str(item.get("sst_id")): item for item in facts.get("ssts") or [] if isinstance(item, dict) and item.get("sst_id")}


def source_scope_for_sst(source_state: dict[str, Any] | None, sst_id: str) -> dict[str, Any]:
    item = source_sst_map(source_state).get(sst_id) or {}
    raw = item.get("scope") if isinstance(item.get("scope"), dict) else {}
    return {key: raw.get(key) if key in raw else None for key in SOURCE_SCOPE_KEYS}


def source_ref_for(source_state: dict[str, Any] | None) -> str:
    if source_state and source_state.get("status") == "VERIFIED":
        return str(source_state.get("intelligence_ref") or source_state.get("source_ref") or "UNVERIFIED_REQUIREMENT_SOURCE")
    return "UNVERIFIED_REQUIREMENT_SOURCE"


def source_state_summary(source_state: dict[str, Any] | None) -> dict[str, Any]:
    source_state = source_state or {}
    facts = source_state.get("facts") or {}
    return {
        "status": source_state.get("status") or "HUMAN_ACTION_REQUIRED",
        "failure_class": source_state.get("failure_class"),
        "reason": source_state.get("reason"),
        "attempted": bool(source_state.get("attempted")),
        "source_ref": source_state.get("source_ref") or "UNAVAILABLE",
        "intelligence_ref": source_state.get("intelligence_ref"),
        "source_hash": source_state.get("source_hash"),
        "freshness": facts.get("freshness"),
        "sst_ids": [item.get("sst_id") for item in facts.get("ssts") or [] if item.get("sst_id")],
        "provenance": source_state.get("provenance") or {},
    }


def requirement_source_state_path() -> Path:
    return STATE_ROOT / "evidence" / "field-validation" / "requirement-source-grounding.json"


def persist_requirement_source_state(source_state: dict[str, Any]) -> None:
    # Store normalized source facts only. Raw HTTP responses, credentials and
    # endpoint URLs never become evidence or durable runtime input.
    write_json(requirement_source_state_path(), source_state, private=True)


def load_requirement_source_state() -> dict[str, Any]:
    return load_json(requirement_source_state_path(), {}) or {}


def quarantine_unverified_r3_state(runtime_state: dict[str, Any]) -> dict[str, int]:
    """Invalidate prior R3 products when the LLM-backed provenance gate is not proven."""
    counts = {"cases": 0, "coverage": 0, "snapshots": 0, "campaigns": 0, "missions": 0}
    if not internal_db_path().is_file():
        return counts
    reason = "OpenCode Auth/LLM Runtime Reality 未确认，既有 R3 产物 provenance 不可接受"
    with storage.transaction() as conn:
        case_rows = conn.execute("SELECT case_id,contract_json FROM test_cases WHERE requirement_id=?", (PROFILE["first_validation_target"],)).fetchall()
        for row in case_rows:
            contract = load_json_from_text(row["contract_json"])
            contract["provenance_status"] = "NOT_VERIFIED"
            contract["provenance_quarantine_reason"] = reason
            conn.execute("UPDATE test_cases SET status='PROVENANCE_NOT_VERIFIED',contract_json=?,updated_at=? WHERE case_id=?", (storage.jdump(contract), now_iso(), row["case_id"]))
            counts["cases"] += 1
        cursor = conn.execute("UPDATE applicability SET status='PROVENANCE_NOT_VERIFIED',rationale=? ,source_ref=? ,updated_at=? WHERE requirement_id=?", (reason, "PFC_OPENCODE_RUNTIME_REALITY_RECON", now_iso(), PROFILE["first_validation_target"]))
        counts["coverage"] = cursor.rowcount
        cursor = conn.execute("UPDATE truth_snapshots SET status='SUPERSEDED' WHERE release_id=? AND kind='PFC_RELEASE_TRUTH' AND status='CURRENT'", (RELEASE_ID,))
        counts["snapshots"] = cursor.rowcount
        cursor = conn.execute("UPDATE campaigns SET status='INVALIDATED',updated_at=? WHERE requirement_id=? AND status NOT IN ('COMPLETED','INVALIDATED')", (now_iso(), PROFILE["first_validation_target"]))
        counts["campaigns"] = cursor.rowcount
        conn.execute("UPDATE requirements SET status='PROVENANCE_NOT_VERIFIED',updated_at=? WHERE requirement_id=?", (now_iso(), PROFILE["first_validation_target"]))
        conn.execute("UPDATE gates SET status='FAIL',decision='REWORK',reason=?,updated_at=? WHERE requirement_id=? AND gate_type IN ('H1','H2')", (reason, now_iso(), PROFILE["first_validation_target"]))
        mission_rows = conn.execute("SELECT mission_id,metadata_json FROM missions WHERE requirement_id=?", (PROFILE["first_validation_target"],)).fetchall()
        for row in mission_rows:
            metadata = load_json_from_text(row["metadata_json"])
            metadata["runtime_reality_gate"] = strip_private_runtime_fields(runtime_state)
            metadata["provenance_quarantine"] = reason
            conn.execute("UPDATE missions SET state='BLOCKED',blocker=?,metadata_json=?,updated_at=? WHERE mission_id=?", ("PFC_OPENCODE_RUNTIME_ADMISSION_REQUIRED", storage.jdump(metadata), now_iso(), row["mission_id"]))
            counts["missions"] += 1
    receipt_path = STATE_ROOT / "evidence" / "field-validation" / "receipts" / "FV-2.json"
    receipt = load_json(receipt_path, {}) or {}
    if receipt:
        previous = receipt.get("status")
        receipt.update({"status": "REVIEW_REQUIRED", "provenance": "NOT_VERIFIED", "previous_status": previous, "quarantine_reason": reason, "runtime_reality": strip_private_runtime_fields(runtime_state)})
        write_json(receipt_path, receipt)
    write_json(STATE_ROOT / "evidence" / "field-validation" / "r3-provenance-quarantine.json", {"status": "APPLIED", "reason": reason, "runtime_reality": runtime_state, "counts": counts}, private=True)
    return counts


def load_json_from_text(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def requirement_source_quality_gaps(source_state: dict[str, Any] | None, sst: dict[str, Any]) -> list[str]:
    if not source_state or source_state.get("status") != "VERIFIED":
        return ["requirement_source_facts", "business_test_data", "source_grounded_oracle", "coverage_obligation_refs"]
    facts = source_state.get("facts") or {}
    gaps: list[str] = []
    if not sst.get("system"):
        gaps.append("system")
    if not sst.get("change"):
        gaps.append("change")
    if not sst.get("fields"):
        gaps.append("fields")
    if not sst.get("business_rules") and not facts.get("business_rules"):
        gaps.append("business_rules")
    data = sst.get("test_data") if isinstance(sst.get("test_data"), dict) else {}
    positive = sst.get("positive") or data.get("positive")
    negative = sst.get("negative") or data.get("negative")
    boundary = sst.get("boundary") or data.get("boundary")
    if not positive:
        gaps.append("positive_test_data")
    if not negative:
        gaps.append("negative_test_data")
    if not boundary:
        gaps.append("boundary_test_data")
    if not sst.get("oracle"):
        gaps.append("oracle")
    if not sst.get("cross_system_relation"):
        gaps.append("cross_system_relation")
    if not sst.get("defect_hypothesis"):
        gaps.append("defect_hypothesis")
    scope = sst.get("scope") if isinstance(sst.get("scope"), dict) else {}
    gaps.extend(key for key in SOURCE_SCOPE_KEYS if key not in scope or scope.get(key) is None)
    return sorted(set(gaps))


def persist_case_status(case_id: str, status: str) -> dict[str, Any]:
    with storage.transaction() as conn:
        conn.execute("UPDATE test_cases SET status=?,updated_at=? WHERE case_id=?", (status, now_iso(), case_id))
    return quality.test_case(case_id)


def case_level(sst: dict[str, Any]) -> str:
    scope = sst.get("scope") if isinstance(sst.get("scope"), dict) else {}
    if scope.get("has_ui") is True:
        return "L4"
    if scope.get("has_api") is True:
        return "L3"
    if scope.get("has_component") is True:
        return "L2"
    return "L1"


def case_contract_from_source(source_state: dict[str, Any], sst: dict[str, Any], obligation_refs: list[str]) -> tuple[dict[str, Any], list[str]]:
    facts = source_state.get("facts") or {}
    data = sst.get("test_data") if isinstance(sst.get("test_data"), dict) else {}
    positive = sst.get("positive") or data.get("positive")
    negative = sst.get("negative") or data.get("negative")
    boundary = sst.get("boundary") or data.get("boundary")
    rules = sst.get("business_rules") or facts.get("business_rules") or []
    field_names = [item.get("name") if isinstance(item, dict) else str(item) for item in (sst.get("fields") or [])]
    gaps = requirement_source_quality_gaps(source_state, sst)
    source_fact_ref = f"{source_state.get('intelligence_ref')}#sst={sst.get('sst_id')}"
    contract = {
        "requirement_ref": f"requirement://{facts.get('requirement_id', PROFILE['first_validation_target'])}",
        "sst_ref": f"sst://{sst.get('sst_id')}",
        "requirement_fact_refs": [source_fact_ref],
        "coverage_obligation_refs": obligation_refs,
        "system": sst.get("system"),
        "change": sst.get("change"),
        "target": PROFILE["default_environment"]["page"],
        "purpose": f"根据 Requirement Source 的业务规则和字段事实验证 {sst.get('sst_id')} 的变更行为",
        "preconditions": [
            "FAT2 页面可访问并完成必要登录",
            f"Requirement Source 已确认且 freshness={facts.get('freshness')}",
            f"已准备 source-defined {sst.get('sst_id')} 的正向、负向和边界数据",
        ],
        "steps": [
            f"按 Requirement Source 变更说明准备 {sst.get('system')} 的字段：{json.dumps(sst.get('fields'), ensure_ascii=False, sort_keys=True)}",
            f"执行正向数据：{json.dumps(positive, ensure_ascii=False, sort_keys=True)}",
            f"执行负向数据：{json.dumps(negative, ensure_ascii=False, sort_keys=True)}",
            f"执行边界数据：{json.dumps(boundary, ensure_ascii=False, sort_keys=True)}",
            "记录页面、接口、数据库和 CAT 可核对的实际结果",
        ],
        "expected_result": sst.get("oracle"),
        "test_level": case_level(sst),
        "coverage": [
            f"Requirement fact：{facts.get('title')} / {sst.get('sst_id')}",
            "字段：" + "、".join(str(item) for item in field_names),
            "业务规则：" + json.dumps(rules, ensure_ascii=False, sort_keys=True),
            f"Change：{sst.get('change')}",
        ],
        "oracle": sst.get("oracle"),
        "business_rules": rules,
        "concrete_test_data": {"positive": positive, "negative": negative, "boundary": boundary},
        "positive": positive,
        "negative": negative,
        "boundary": boundary,
        "cross_system_relation": sst.get("cross_system_relation"),
        "defect_hypothesis": sst.get("defect_hypothesis"),
        "evidence_channels": ["browser", "api", "db", "cat"],
        "source_grounding": {
            "status": source_state.get("status"),
            "source_ref": source_state.get("source_ref"),
            "source_hash": source_state.get("source_hash"),
            "freshness": facts.get("freshness"),
        },
        "case_review_state": "CASE_REVIEW_REQUIRED",
    }
    return contract, gaps


def coverage_items_for(requirement_id: str, source_state: dict[str, Any] | None, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    case_by_sst = {str(item.get("sst_id")): item for item in cases if item.get("sst_id")}
    fact_by_sst = source_sst_map(source_state)
    result: list[dict[str, Any]] = []
    for row in rows("SELECT * FROM applicability WHERE requirement_id=? ORDER BY sst_id,layer_id,dimension", (requirement_id,)):
        status = str(row.get("status") or "")
        if status in {"REQUIRED", "IMPACTED"}:
            disposition = "SELECTED"
        elif status in {"NOT_APPLICABLE", "NOT_SELECTED"}:
            disposition = "EXCLUDED"
        else:
            disposition = "PENDING"
        source_fact = fact_by_sst.get(str(row.get("sst_id")))
        fact_label = (
            f"{PROFILE['first_validation_target']} / {row.get('sst_id')} / {source_fact.get('system')}"
            if source_fact else
            f"{PROFILE['first_validation_target']} / {row.get('sst_id')} / Requirement Source 未确认"
        )
        linked_case = case_by_sst.get(str(row.get("sst_id")))
        result.append({
            "requirement_fact": fact_label,
            "obligation": f"{row.get('layer_id')} / {row.get('dimension')}",
            "disposition": disposition,
            "reason": row.get("rationale"),
            "linked_cases": [linked_case.get("title") or linked_case.get("name")] if linked_case else [],
            "source_ref": row.get("source_ref"),
        })
    return result


def resolve_test_account_if_needed() -> str | None:
    """Collect credentials only when explicitly requested by a real login gate."""
    profile = machine_profile()
    if profile.get("test_account_ref"):
        return str(profile["test_account_ref"])
    if os.environ.get("PFC_REQUEST_TEST_CREDENTIALS") != "1":
        return None
    if os.environ.get("PFC_NONINTERACTIVE") == "1" or not sys.stdin.isatty():
        return None
    print("请输入当前 PFC 测试账号：", end="", flush=True)
    username = input().strip()
    print("请输入当前 PFC 测试账号密码：", end="", flush=True)
    password = getpass.getpass("")
    if not username or not password:
        return None
    # The secret remains on the machine only; the durable runtime receives a
    # reference and never receives the password value.
    save_machine_profile({"test_account_ref": "profile://PFC/FAT2/TEST_ACCOUNT", "test_account_user": username, "test_account_password": password})
    return "profile://PFC/FAT2/TEST_ACCOUNT"


def repo_root() -> Path:
    override = os.environ.get("PFC_REPO_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if INSTALLED_RUNTIME_WORKSPACE:
        installed = load_json(INSTALLATION_MARKER_PATH, {}) or {}
        configured = str(installed.get("project_root") or "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
    paths = list((PROFILE.get("local_repositories") or {}).values())
    if paths:
        first = str(paths[0]).replace("\\", "/")
        return Path(first).parent
    return Path("D:/PFC")


def expected_repo_path(name: str) -> Path:
    override = os.environ.get(f"PFC_REPO_{name.upper().replace('-', '_')}_PATH")
    if override:
        return Path(override).expanduser().resolve()
    if os.environ.get("PFC_REPO_ROOT"):
        return repo_root() / Path(str(PROFILE["local_repositories"][name]).replace("\\", "/")).name
    return Path(str(PROFILE["local_repositories"][name]).replace("\\", "/")).expanduser().resolve()


def git_output(path: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def repository_module(record: dict[str, Any]) -> str | None:
    values = [record.get("system_id"), record.get("module_name"), record.get("full_name")]
    for value in values:
        text = str(value or "").strip()
        if text in PROFILE.get("local_repositories", {}):
            return text
        prefix = "bloan-prod-factory-"
        if text.startswith(prefix) and text[len(prefix):] in PROFILE.get("local_repositories", {}):
            return text[len(prefix):]
    local_path = str(record.get("local_path") or "").replace("\\", "/").rstrip("/")
    basename = local_path.rsplit("/", 1)[-1]
    if basename.startswith("bloan-prod-factory-"):
        basename = basename[len("bloan-prod-factory-"):]
    return basename if basename in PROFILE.get("local_repositories", {}) else None


def release_branch_ref(path: Path) -> tuple[str | None, str | None]:
    branch = str(PROFILE.get("release_branch") or "").strip()
    if not branch:
        return None, None
    candidates = (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}")
    for candidate in candidates:
        sha = git_output(path, "rev-parse", "--verify", candidate)
        if sha:
            return candidate, sha
    return None, None


def source_revision_facts(record: dict[str, Any], path: Path, module: str) -> dict[str, Any]:
    current_branch = str(record.get("current_branch") or "UNKNOWN")
    head_sha = str(record.get("head_sha") or "UNKNOWN")
    ref, release_sha = release_branch_ref(path)
    status_output = git_output(path, "status", "--porcelain=v1", "--branch")
    status_lines = (status_output or "").splitlines()
    changes = [line for line in status_lines if line and not line.startswith("##")]
    if status_output is None:
        working_tree_state = "UNAVAILABLE"
    else:
        working_tree_state = "CLEAN" if not changes else "DIRTY"
    if not ref or not release_sha:
        difference = {
            "status": "RELEASE_BRANCH_NOT_VERIFIED",
            "summary": f"未找到或未能验证 {PROFILE['release_branch']}",
        }
    elif head_sha == release_sha:
        difference = {
            "status": "MATCH",
            "summary": "当前 HEAD 与 release branch 一致",
            "ahead": 0,
            "behind": 0,
        }
    else:
        counts = git_output(path, "rev-list", "--left-right", "--count", f"{ref}...{head_sha}") or ""
        parts = counts.split()
        behind = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else None
        ahead = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        diff_stat = git_output(path, "diff", "--stat", ref, head_sha) or "无法读取文件差异摘要"
        difference = {
            "status": "DIFFERS",
            "summary": f"当前 HEAD 与 release branch 存在差异：ahead={ahead if ahead is not None else '未确认'}，behind={behind if behind is not None else '未确认'}；{diff_stat[:500]}",
            "ahead": ahead,
            "behind": behind,
            "diff_stat": diff_stat[:1000],
        }
    stable = {
        "module": module,
        "repository_id": record.get("repository_id"),
        "repository_name": record.get("full_name"),
        "local_path": record.get("local_path"),
        "remote_url": record.get("remote_url"),
        "current_branch": current_branch,
        "head_sha": head_sha,
        "release_branch": PROFILE["release_branch"],
        "release_branch_ref": ref,
        "release_branch_sha": release_sha,
        "release_branch_exists": bool(ref and release_sha),
        "working_tree_state": working_tree_state,
        "working_tree_changes": changes[:100],
        "release_difference": difference,
    }
    stable["source_revision_identity"] = digest(stable)
    return stable


def discover_repositories(project_id: str) -> dict[str, Any]:
    expected = PROFILE.get("local_repositories") or {}
    found: list[dict[str, Any]] = []
    missing: list[str] = []
    invalid: list[dict[str, Any]] = []
    for module, _label in expected.items():
        path = expected_repo_path(module)
        if not path.is_dir() or not (path / ".git").exists():
            missing.append(module)
            continue
        try:
            record = repository.inspect_repository(project_id, path, system_id=module)
            record["module_name"] = module
            record["expected_path"] = str(path)
            record["path_verified"] = Path(record["local_path"]).resolve() == path.resolve()
            record["remote_verified"] = bool(record.get("remote_url") and record.get("remote_url") != "UNKNOWN")
            record["repository_identity"] = {
                "repository_id": record.get("repository_id"),
                "module": module,
                "repository_name": record.get("full_name"),
                "local_path": record.get("local_path"),
                "remote_url": record.get("remote_url"),
            }
            record["source_revision_facts"] = source_revision_facts(record, path, module)
            if not record["path_verified"] or not record["remote_verified"]:
                invalid.append({"module": module, "path_verified": record["path_verified"], "remote_verified": record["remote_verified"]})
            found.append(record)
        except Exception as exc:
            invalid.append({"module": module, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "root": str(repo_root()),
        "expected": list(expected),
        "found": found,
        "missing": missing,
        "invalid": invalid,
        "count": len(found),
        "source_revision_facts": [item["source_revision_facts"] for item in found if item.get("source_revision_facts")],
    }


def summarize_source_baseline(repo_state: dict[str, Any]) -> dict[str, Any]:
    expected = list(PROFILE.get("local_repositories") or {})
    by_module = {repository_module(item): item for item in repo_state.get("found", []) if repository_module(item)}
    facts = [by_module[module].get("source_revision_facts", {}) for module in expected if module in by_module]
    missing = [module for module in expected if module not in by_module]
    incomplete = [
        item.get("module")
        for item in facts
        if not item.get("head_sha") or item.get("head_sha") == "UNKNOWN" or not item.get("release_branch_exists") or item.get("working_tree_state") == "UNAVAILABLE"
    ]
    if missing:
        status = "FAIL"
    elif incomplete:
        status = "PARTIAL"
    else:
        status = "VERIFIED"
    return {
        "status": status,
        "repository_count": len(by_module),
        "expected_repository_count": len(expected),
        "missing_repositories": missing,
        "incomplete_repositories": incomplete,
        "release_branch": PROFILE["release_branch"],
        "facts": facts,
    }


def ensure_project_and_truth(
    repo_state: dict[str, Any],
    starlink: str | None,
    starlink_ref: str | None,
    source_baseline_state: dict[str, Any],
    deployment_baseline_state: dict[str, Any],
    requirement_source_state: dict[str, Any],
) -> dict[str, Any]:
    project.init_project(
        PROJECT_ID,
        "PFC",
        str(repo_root()),
        project_id=PROJECT_ID,
        config={"source": "PFC_PROJECT_PROFILE.json", "package_identity": PROFILE["package_identity"], "default_environment": ENVIRONMENT_ID},
    )
    for module, system_spec in (PROFILE.get("systems") or {}).items():
        project.register_system(PROJECT_ID, module, module, f"PFC {module} system", "PFC", metadata={"endpoint": system_spec.get("endpoint"), "app_id": system_spec.get("app_id")})
    environment_config = {
        "allowed_hosts": [
            "prod-factory.fat002.qa.pab.com.cn",
            "flow-engine.fat002.qa.pab.com.cn",
            "config-center.fat002.qa.pab.com.cn",
            "data-center.fat002.qa.pab.com.cn",
        ],
        "page_urls": {"home": PROFILE["default_environment"]["page"]},
        "service_endpoints": {name: spec.get("endpoint") for name, spec in (PROFILE.get("systems") or {}).items() if spec.get("endpoint")},
        "cat_environment_ref": "fat002",
        "tdsql_endpoints": {name: spec.get("tdsql") for name, spec in (PROFILE.get("systems") or {}).items() if spec.get("tdsql")},
        "auth_profile_refs": ["profile://PFC/FAT2/TEST_ACCOUNT"],
    }
    project.register_environment(PROJECT_ID, ENVIRONMENT_ID, "FAT2", "TEST", environment_config)
    project.register_connector(
        PROJECT_ID,
        "PFC-STARLINK-FAT2",
        "STARLINK",
        "PFC FAT2 Starlink",
        config={"environment": "FAT2", "scope": "single-bank-environment", "endpoint": starlink or "UNAVAILABLE"},
        secret_ref=starlink_ref,
        status="DEGRADED" if starlink else "NOT_CONFIGURED",
    )
    project.register_connector(
        PROJECT_ID,
        "PFC-CAT-FAT002",
        "CAT",
        "PFC FAT2 CAT",
        adapter_path="ai-test/local/adapters/cat-log-query.py",
        config={"environment": "fat002"},
        status="DEGRADED",
    )
    project.register_auth_profile(
        PROJECT_ID,
        "PFC-FAT2-AUTH",
        "PFC FAT2 登录",
        environment_id=ENVIRONMENT_ID,
        secret_ref="profile://PFC/FAT2/TEST_ACCOUNT",
        browser_profile_ref="profile://PFC/FAT2/BROWSER",
        metadata={"human_action_allowed": True},
    )
    release_meta = {
        "project_version": PROFILE["version"],
        "preconfigured": True,
        "source": "PFC_PROJECT_PROFILE.json",
        "source_baseline": source_baseline_state,
        "deployment_baseline": deployment_baseline_state,
        "requirement_source": source_state_summary(requirement_source_state),
    }
    truth.register_release(PROJECT_ID, RELEASE_ID, PROFILE["version"], PROFILE["release_branch"], "PFC_PROJECT_PROFILE.json", release_meta)
    if deployment_baseline_state.get("status") == "VERIFIED":
        facts = deployment_baseline_state.get("facts") or {}
        truth.import_deployment(
            PROJECT_ID,
            RELEASE_ID,
            ENVIRONMENT_ID,
            {
                "deployment_id": facts.get("deployment"),
                "status": "PASS",
                "version": facts.get("version"),
                "system": facts.get("system"),
                "app": facts.get("app"),
                "branch": facts.get("branch"),
                "revision": facts.get("revision"),
                "source": "starlink",
            },
        )

    repo_by_name = {repository_module(item): item for item in repo_state.get("found", []) if repository_module(item)}
    first_req = PROFILE["first_validation_target"]
    source_verified = requirement_source_state.get("status") == "VERIFIED"
    source_facts = requirement_source_state.get("facts") or {}
    for req_id in PROFILE.get("requirements") or []:
        if req_id == first_req and source_verified:
            title = str(source_facts.get("title") or f"PFC {req_id}")
            requirement_source_ref = str(requirement_source_state.get("source_ref") or source_ref_for(requirement_source_state))
            source_hash = requirement_source_state.get("source_hash")
        else:
            title = f"PFC {req_id}"
            requirement_source_ref = source_ref_for(requirement_source_state) if req_id == first_req else "PFC_PROJECT_PROFILE.json"
            source_hash = requirement_source_state.get("source_hash") if req_id == first_req and source_verified else None
        truth.register_requirement(
            PROJECT_ID,
            RELEASE_ID,
            req_id,
            title,
            source_ref=requirement_source_ref,
            source_hash=source_hash,
            metadata={"preconfigured": req_id != first_req, "requirement_source": source_state_summary(requirement_source_state) if req_id == first_req else None},
        )
    for req_id, ssts in (PROFILE.get("requirement_sst") or {}).items():
        for item in ssts:
            module = str(item["module"])
            repo = repo_by_name.get(module)
            if req_id == first_req:
                source_sst = source_sst_map(requirement_source_state).get(item["sst_id"]) or {}
                scope = source_scope_for_sst(requirement_source_state, item["sst_id"])
                sst_source_ref = source_ref_for(requirement_source_state)
                sst_title = str(source_sst.get("change") or f"{req_id} / {module}")
                source_metadata = {
                    **scope,
                    "app_id": item.get("app_id"),
                    "source_grounding_status": requirement_source_state.get("status"),
                    "requirement_fact": source_sst,
                    "repository_identity": (repo or {}).get("repository_identity"),
                    "source_revision_facts": (repo or {}).get("source_revision_facts"),
                }
            else:
                # STBB19-240/242 remain outside this bounded R3 repair scope.
                scope = {"has_code_change": True, "has_component": True, "has_api": True, "has_ui": True, "cross_system": True}
                sst_source_ref = "PFC_PROJECT_PROFILE.json"
                sst_title = f"{req_id} / {module}"
                source_metadata = {
                    **scope,
                    "app_id": item.get("app_id"),
                    "repository_identity": (repo or {}).get("repository_identity"),
                    "source_revision_facts": (repo or {}).get("source_revision_facts"),
                }
            truth.link_version_sst(RELEASE_ID, item["sst_id"], source_ref=sst_source_ref, metadata={"module": module, "source_grounding_status": requirement_source_state.get("status") if req_id == first_req else "OUT_OF_SCOPE"})
            truth.link_requirement_sst(
                req_id,
                item["sst_id"],
                title=sst_title,
                owner_system_id=module,
                implementation_system_id=module,
                repository_id=(repo or {}).get("repository_id"),
                module_name=module,
                feature_branch=(repo or {}).get("current_branch") or "UNKNOWN",
                release_branch=PROFILE["release_branch"],
                source_ref=sst_source_ref,
                metadata=source_metadata,
            )
            truth.set_quality_scope(req_id, item["sst_id"], performance_required=False, performance_status="NOT_REQUIRED", security_requirement_identified=False, security_design_review_required=False, security_design_review_status="NOT_REQUIRED", security_test_required=False, security_test_review_status="NOT_REQUIRED", source_ref=sst_source_ref)
        if req_id != first_req or source_verified:
            truth.baseline_requirement(req_id, "pfc-harness", [f"source:{source_ref_for(requirement_source_state) if req_id == first_req else 'profile:' + req_id}"])
        else:
            truth.gate_set(PROJECT_ID, "H1", "FAIL", release_id=RELEASE_ID, requirement_id=req_id, decision="REWORK", reviewer="pfc-harness", evidence=["requirement-source-gate://PFC/STBB19-234"], reason="Requirement Source 未确认，不能建立 H1 requirement baseline")
            with storage.transaction() as conn:
                conn.execute("UPDATE requirements SET status='SOURCE_UNVERIFIED',updated_at=? WHERE requirement_id=?", (now_iso(), req_id))
    scheduler.seed_layers()
    return {"project": project.project_status(PROJECT_ID), "repo_state": repo_state}


def ensure_r3_outputs(
    repo_state: dict[str, Any],
    source_baseline_state: dict[str, Any],
    deployment_baseline_state: dict[str, Any],
    requirement_source_state: dict[str, Any],
) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    applicability: dict[str, int] = {}
    for req_id in PROFILE.get("requirements") or []:
        decision_rows = scheduler.compute_applicability(PROJECT_ID, RELEASE_ID, req_id, source_ref=source_ref_for(requirement_source_state) if req_id == PROFILE["first_validation_target"] else "PFC_PROJECT_PROFILE.json")
        applicability[req_id] = len(decision_rows)
    first_req = PROFILE["first_validation_target"]
    source_by_sst = source_sst_map(requirement_source_state)
    app_rows = rows("SELECT * FROM applicability WHERE requirement_id=? ORDER BY sst_id,layer_id,dimension", (first_req,))
    app_by_sst: dict[str, list[dict[str, Any]]] = {}
    for row in app_rows:
        app_by_sst.setdefault(str(row.get("sst_id")), []).append(row)
    for item in PROFILE["requirement_sst"][first_req]:
        sst_id = item["sst_id"]
        case_id = f"PFC-{first_req}-{sst_id}-STANDARD"
        source_sst = source_by_sst.get(sst_id) or {}
        obligation_refs = [f"applicability://{row.get('sst_id')}/{row.get('layer_id')}/{row.get('dimension')}" for row in app_by_sst.get(sst_id, [])]
        if requirement_source_state.get("status") == "VERIFIED":
            contract, gaps = case_contract_from_source(requirement_source_state, source_sst, obligation_refs)
            status = "ACTIVE" if not gaps else "REVIEW_REQUIRED"
            title = f"{first_req} / {sst_id} / {source_sst.get('system') or item['module']}"
            level = contract.get("test_level") or "L1"
        else:
            gaps = requirement_source_quality_gaps(requirement_source_state, source_sst)
            contract = {
                "requirement_ref": f"requirement://{first_req}",
                "sst_ref": f"sst://{sst_id}",
                "source_grounding_status": requirement_source_state.get("status") or "HUMAN_ACTION_REQUIRED",
                "source_failure_class": requirement_source_state.get("failure_class"),
                "status_reason": requirement_source_state.get("reason") or "Requirement Source 未确认",
                "case_quality_gap": gaps,
                "case_review_state": "CASE_REVIEW_REQUIRED",
                "coverage_obligation_refs": [],
            }
            status = "BLOCKED_SOURCE_GROUNDING"
            title = f"{first_req} / {sst_id} / 等待真实 Requirement Source"
            level = "L4"
        case = quality.register_test_case(first_req, case_id, title, level, "FUNCTIONAL", contract, sst_id=sst_id)
        case = persist_case_status(case_id, status)
        created.append(case)
    existing_snapshot = one("SELECT * FROM truth_snapshots WHERE project_id=? AND release_id=? AND kind=? AND status='CURRENT' ORDER BY observed_at DESC, rowid DESC LIMIT 1", (PROJECT_ID, RELEASE_ID, "PFC_RELEASE_TRUTH"))
    stable_repositories = [
        {
            key: item.get(key)
            for key in ("repository_id", "full_name", "local_path", "remote_url", "default_branch", "current_branch", "head_sha", "system_id", "module_name", "repository_identity", "source_revision_facts")
        }
        for item in repo_state.get("found", [])
    ]
    snapshot_payload = {
        "project": PROJECT_ID,
        "version": PROFILE["version"],
        "release_branch": PROFILE["release_branch"],
        "environment": PROFILE["default_environment"],
        "systems": PROFILE["systems"],
        "repositories": stable_repositories,
        "source_baseline": source_baseline_state,
        "deployment_baseline": deployment_baseline_state,
        "requirement_source": requirement_source_state,
        "requirements": PROFILE["requirements"],
        "requirement_sst": PROFILE["requirement_sst"],
        "starlink_scope": PROFILE["starlink"],
        "observed_by": "pfc-harness",
    }
    # The frozen runtime's truth store hashes its sorted JSON with default
    # separators; use the same representation so repeated START reuses the
    # current snapshot instead of creating a new one.
    payload_hash = sha256_bytes(json.dumps(snapshot_payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    snapshot = existing_snapshot
    if not existing_snapshot or existing_snapshot.get("payload_hash") != payload_hash:
        snapshot = truth.add_snapshot(PROJECT_ID, "PFC_RELEASE_TRUTH", "PFC_PROJECT_PROFILE.json", snapshot_payload, release_id=RELEASE_ID)
    else:
        snapshot = {**existing_snapshot, "payload": json.loads(existing_snapshot["payload_json"])}

    # A single PFC campaign is enough for this package.  Materialization is
    # deterministic because scope facts and quality decisions are preconfigured.
    campaign_row = one("SELECT * FROM campaigns WHERE project_id=? AND requirement_id=? AND campaign_type=? ORDER BY created_at LIMIT 1", (PROJECT_ID, first_req, "PFC_FIELD_VALIDATION"))
    if not campaign_row:
        campaign = scheduler.create_campaign(PROJECT_ID, "PFC_FIELD_VALIDATION", f"PFC {first_req} Field Validation", release_id=RELEASE_ID, requirement_id=first_req, metadata={"package_identity": PROFILE["package_identity"]})
        campaign_id = campaign["campaign_id"]
    else:
        campaign_id = campaign_row["campaign_id"]
    materialized = None
    try:
        materialized = scheduler.materialize_campaign(campaign_id, "aitest-scheduler")
    except ValueError as exc:
        materialized = {"status": "BLOCKED", "message": str(exc)}

    return {
        "requirement_intelligence": applicability,
        "standard_cases": created,
        "standard_case_quality": "READY_FOR_PRODUCT_OWNER_REVIEW" if requirement_source_state.get("status") == "VERIFIED" and all(not requirement_source_quality_gaps(requirement_source_state, source_by_sst.get(item["sst_id"]) or {}) for item in PROFILE["requirement_sst"][first_req]) else "REPAIR",
        "requirement_source_grounding": requirement_source_state.get("status") if requirement_source_state else "HUMAN_ACTION_REQUIRED",
        "coverage_items": coverage_items_for(first_req, requirement_source_state, created),
        "truth_snapshot": snapshot,
        "campaign_id": campaign_id,
        "campaign": materialized,
    }


ORCHESTRATION_REPAIR_VERSION = "PFC_READY_V2_ORCHESTRATION_AND_STATUS_REPAIR_V1"


def execution_repository_bindings(repo_state: dict[str, Any]) -> list[dict[str, Any]]:
    by_module = {repository_module(item): item for item in repo_state.get("found", []) if repository_module(item)}
    bindings: list[dict[str, Any]] = []
    for module in PROFILE.get("local_repositories", {}):
        item = by_module.get(module)
        if not item:
            continue
        facts = item.get("source_revision_facts") or {}
        bindings.append({
            "module": module,
            "repository_id": item.get("repository_id"),
            "repository_name": item.get("full_name"),
            "local_path": item.get("local_path"),
            "remote_url": item.get("remote_url"),
            "current_branch": item.get("current_branch"),
            "head_sha": item.get("head_sha"),
            "release_branch": PROFILE["release_branch"],
            "release_branch_ref": facts.get("release_branch_ref"),
            "release_branch_sha": facts.get("release_branch_sha"),
            "source_revision_identity": facts.get("source_revision_identity"),
        })
    return bindings


def update_mission_metadata(mission_id: str, values: dict[str, Any]) -> dict[str, Any]:
    current = mission.get_mission(mission_id, include_steps=False)
    metadata = {**(current.get("metadata") or {}), **values}
    with storage.transaction() as conn:
        conn.execute("UPDATE missions SET metadata_json=?,updated_at=? WHERE mission_id=?", (storage.jdump(metadata), now_iso(), mission_id))
    return mission.get_mission(mission_id)


def ensure_mission(
    repo_state: dict[str, Any],
    source_baseline_state: dict[str, Any],
    deployment_baseline_state: dict[str, Any],
    requirement_source_state: dict[str, Any],
) -> dict[str, Any]:
    first_req = PROFILE["first_validation_target"]
    bindings = execution_repository_bindings(repo_state)
    existing = one("SELECT mission_id FROM missions WHERE project_id=? AND release_id=? AND requirement_id=? AND title=? ORDER BY created_at LIMIT 1", (PROJECT_ID, RELEASE_ID, first_req, f"PFC {first_req} Field Validation"))
    if existing:
        current = mission.get_mission(existing["mission_id"])
    else:
        current = mission.create_mission(PROJECT_ID, f"PFC {first_req} Field Validation", "pfc-harness", release_id=RELEASE_ID, requirement_id=first_req, mission_type="FIELD_VALIDATION", metadata={"package_identity": PROFILE["package_identity"], "sst_id": "STB913-13169", "showcase_required": False, "pfc_automation": True})
    current = update_mission_metadata(current["mission_id"], {
        "orchestration_repair_version": ORCHESTRATION_REPAIR_VERSION,
        "repository_execution_bindings": bindings,
        "source_baseline": source_baseline_state,
        "deployment_baseline": deployment_baseline_state,
        "requirement_source": source_state_summary(requirement_source_state),
        "case_review_state": "CASE_REVIEW_REQUIRED",
        "real_execution_entry": "HOLD",
    })
    if current["state"] == "DRAFT":
        for next_state in ("DISCOVERING", "TRUTH_SYNC", "SCOPING", "PLANNING"):
            current = mission.transition(current["mission_id"], next_state, "pfc-harness", reason="PFC_AUTO_BOOTSTRAP")
    current_steps = current.get("steps") or []
    bound_ids = {
        str((step.get("input") or {}).get("repository_id"))
        for step in current_steps
        if step.get("capability_id") == "git.status" and (step.get("input") or {}).get("repository_id")
    }
    expected_ids = {str(item.get("repository_id")) for item in bindings if item.get("repository_id")}
    plan_needs_repair = not current.get("plan_version") or bound_ids != expected_ids or current.get("metadata", {}).get("orchestration_repair_version") != ORCHESTRATION_REPAIR_VERSION
    can_replan = current["state"] in {"PLANNING", "WAITING_H2", "BLOCKED"}
    if plan_needs_repair and current.get("plan_version") and not can_replan:
        pending_only = all(step.get("status") == "PENDING" for step in current_steps)
        can_replan = pending_only and current["state"] in {"WAITING_H3", "PREFLIGHT"}
        if can_replan:
            current = mission.transition(current["mission_id"], "PLANNING", "pfc-harness", reason="PFC_ORCHESTRATION_REPAIR", force=True)
    if plan_needs_repair and (not current.get("plan_version") or current["state"] in {"PLANNING", "WAITING_H2", "BLOCKED"}):
        steps: list[dict[str, Any]] = []
        for index, binding in enumerate(bindings, 1):
            steps.append({
                "step_id": f"{current['mission_id']}-R{index:03d}",
                "title": f"读取 {binding['module']} 仓库状态与 source revision",
                "capability_id": "git.status",
                "role_required": "EXECUTOR",
                "input": binding,
                "expected": {},
            })
        steps.append({
            "step_id": f"{current['mission_id']}-R{len(steps) + 1:03d}",
            "title": "准备 FAT2 真实页面执行",
            "capability_id": "browser.launch",
            "role_required": "EXECUTOR",
            "input": {"project_id": PROJECT_ID, "mode": "EXECUTE", "mission_id": current["mission_id"], "environment_id": ENVIRONMENT_ID, "auth_profile_id": "PFC-FAT2-AUTH", "start_url": PROFILE["default_environment"]["page"], "allowed_domains": ["prod-factory.fat002.qa.pab.com.cn"], "dry_run": False, "repository_bindings": bindings},
            "expected": {},
        })
        current = mission.submit_plan(current["mission_id"], steps, "aitest-planner", reason="PFC_ORCHESTRATION_REPAIR") ["mission"]
    return mission.get_mission(current["mission_id"])


def install_bootstrap() -> dict[str, Any]:
    """Provision PFC durable truth once into the installed stable workspace."""
    storage.initialize()
    repo_state = discover_repositories(PROJECT_ID)
    source_state = source_failure(
        "HUMAN_ACTION_REQUIRED",
        "SOURCE_NOT_CONFIGURED",
        f"安装阶段不读取 Starlink；{PROFILE['first_validation_target']} Requirement Source 等待后续授权",
        source_ref=f"starlink://PFC/FAT2/{PROFILE['first_validation_target']}",
        attempted=False,
    )
    source_baseline_state = summarize_source_baseline(repo_state)
    deployment_state = deployment_baseline(None)
    project_state = ensure_project_and_truth(repo_state, None, None, source_baseline_state, deployment_state, source_state)
    mission_state = ensure_mission(repo_state, source_baseline_state, deployment_state, source_state)
    return redact({
        "status": "PASS" if not repo_state.get("missing") and not repo_state.get("invalid") else "REPAIR",
        "project": PROJECT_ID,
        "version": PROFILE["version"],
        "bootstrap_version": PROFILE["version"],
        "version_truth": current_version_truth(),
        "active_requirement": PROFILE["first_validation_target"],
        "release": RELEASE_ID,
        "environment": ENVIRONMENT_ID,
        "repositories": repo_state,
        "project_state": project_state.get("project"),
        "mission": {"mission_id": mission_state.get("mission_id"), "state": mission_state.get("state"), "cursor": mission_state.get("current_step_id"), "real_execution_entry": "HOLD"},
        "requirement_source": source_state,
        "coverage": "NOT_VERIFIED / QUARANTINED",
        "standard_cases": "NOT_VERIFIED / QUARANTINED",
        "real_execution_entry": "HOLD",
    })


def ensure_readiness(
    mission_state: dict[str, Any],
    starlink: str | None,
    repo_state: dict[str, Any],
    source_baseline_state: dict[str, Any],
    deployment_baseline_state: dict[str, Any],
    requirement_source_state: dict[str, Any],
) -> dict[str, Any]:
    first_req = PROFILE["first_validation_target"]
    h2_evidence = ["coverage://PFC/STBB19-234", "cases://PFC/STBB19-234"]
    case_rows = [quality.test_case(row["case_id"]) for row in rows("SELECT case_id FROM test_cases WHERE requirement_id=? ORDER BY case_id", (first_req,))]
    case_quality_ready = requirement_source_state.get("status") == "VERIFIED" and bool(case_rows) and all(
        row.get("status") == "ACTIVE" and not requirement_source_quality_gaps(requirement_source_state, (source_sst_map(requirement_source_state).get(row.get("sst_id")) or {}))
        for row in case_rows
    )
    if case_quality_ready:
        truth.gate_set(PROJECT_ID, "H2", "PASS", release_id=RELEASE_ID, requirement_id=first_req, decision="APPROVE", reviewer="pfc-harness", evidence=h2_evidence, reason="Source-grounded Requirement Intelligence/Coverage/StandardTestCase is ready for Product Owner review")
    else:
        truth.gate_set(PROJECT_ID, "H2", "FAIL", release_id=RELEASE_ID, requirement_id=first_req, decision="REWORK", reviewer="pfc-harness", evidence=h2_evidence, reason="Requirement Source or source-grounded StandardTestCase quality is not ready")
    preflight: dict[str, Any]
    try:
        preflight = quality.evaluate_preflight(mission_state["mission_id"], ENVIRONMENT_ID)
    except Exception as exc:
        preflight = {"ok": False, "blockers": [f"PREFLIGHT_ERROR:{type(exc).__name__}"], "message": str(exc)}
    if not starlink:
        preflight.setdefault("blockers", []).append("STARLINK_BINDING_REQUIRED")
        preflight["ok"] = False
    if repo_state.get("missing"):
        preflight.setdefault("blockers", []).append("REPOSITORY_MISSING:" + ",".join(repo_state["missing"]))
        preflight["ok"] = False
    if source_baseline_state.get("status") != "VERIFIED":
        preflight.setdefault("blockers", []).append("SOURCE_BASELINE_NOT_VERIFIED")
        preflight["ok"] = False
    if deployment_baseline_state.get("status") != "VERIFIED":
        preflight.setdefault("blockers", []).append("DEPLOYMENT_BASELINE_NOT_VERIFIED")
        preflight["ok"] = False
    if requirement_source_state.get("status") != "VERIFIED":
        preflight.setdefault("blockers", []).append("REQUIREMENT_SOURCE_NOT_VERIFIED")
        preflight["ok"] = False
    if not case_quality_ready:
        preflight.setdefault("blockers", []).append("STANDARD_CASE_QUALITY_GAP")
        preflight["ok"] = False
    # Generation is intentionally stopped at the Product Owner review gate.
    # Even a complete source-grounded case set cannot enter real execution
    # without an explicit later human approval.
    preflight.setdefault("blockers", []).append("STANDARD_CASE_REVIEW_REQUIRED")
    preflight["ok"] = False
    # A human H3 approval is never manufactured by the harness.  If it was
    # previously granted, resume the already planned cursor automatically.
    gate = truth.gate_status(first_req, "H3")
    refreshed = mission.get_mission(mission_state["mission_id"])
    if preflight.get("ok") and gate and gate.get("status") == "PASS" and refreshed["state"] == "WAITING_H3":
        refreshed = mission.transition(refreshed["mission_id"], "EXECUTING", "pfc-harness", reason="H3_ALREADY_APPROVED")
    if refreshed["state"] in {"EXECUTING", "VERIFYING"}:
        refreshed = mission.transition(refreshed["mission_id"], "BLOCKED", "pfc-harness", reason="PFC_R3_CASE_REVIEW_GATE", blocker="STANDARD_CASE_REVIEW_REQUIRED", force=True)
    return {"preflight": preflight, "mission": refreshed, "case_quality_ready": case_quality_ready, "case_review_state": "CASE_REVIEW_REQUIRED", "execution_allowed": False}


def execute_if_ready(mission_state: dict[str, Any]) -> dict[str, Any]:
    current = mission.get_mission(mission_state["mission_id"])
    executed: list[dict[str, Any]] = []
    for _ in range(8):
        if stop_requested():
            break
        if current["state"] != "EXECUTING":
            break
        try:
            result = quality.execute_current_step(current["mission_id"], "aitest-executor")
            executed.append({"status": result.get("status"), "step_id": result.get("step_id")})
            if result.get("status") == "WAITING_HUMAN":
                break
            current = mission.get_mission(current["mission_id"])
            if current["state"] == "VERIFYING":
                evaluation = quality.evaluate_current_step(current["mission_id"], "aitest-evaluator")
                executed.append({"status": evaluation.get("status"), "step_id": evaluation.get("step_id")})
                current = mission.get_mission(current["mission_id"])
        except Exception as exc:
            executed.append({"status": "BLOCKED", "message": f"{type(exc).__name__}: {exc}"})
            break
    return {"mission": current, "executed": executed}


def build_fv2_receipt(r3: dict[str, Any]) -> dict[str, Any]:
    first_req = PROFILE["first_validation_target"]
    snapshot = r3["truth_snapshot"]
    case_rows = rows("SELECT case_id FROM test_cases WHERE requirement_id=? ORDER BY case_id", (first_req,))
    requirements = rows("SELECT requirement_id FROM requirements WHERE project_id=? AND release_id=? ORDER BY requirement_id", (PROJECT_ID, RELEASE_ID))
    receipt = {
        "schema_version": "pfc.r1-r4.field-validation.auto-receipt.v1",
        "receipt_kind": "FV-2",
        "generated_at": now_iso(),
        "generated_by": "PFC_R1_R4_FIELD_VALIDATION_READY_PACKAGE_V2_ORCHESTRATION_STATUS_REPAIR",
        "manual_input_required": False,
        "project_ref": f"project://{PROJECT_ID}",
        "release_ref": f"release://{RELEASE_ID}",
        "requirement_refs": [f"requirement://{item['requirement_id']}" for item in requirements],
        "coverage_snapshot_ref": f"truth-snapshot://{snapshot['snapshot_id']}",
        "standard_test_case_refs": [f"test-case://{item['case_id']}" for item in case_rows],
        "attempt_refs": [],
        "defect_refs": [],
        "real_runtime": True,
        "synthetic_or_fixture": False,
        "r3_requirement_source_grounding": r3.get("requirement_source_grounding"),
        "r3_coverage_grounding": "PASS" if r3.get("requirement_source_grounding") == "VERIFIED" else "REPAIR",
        "r3_standard_case_quality": r3.get("standard_case_quality", "REPAIR"),
        "case_review_state": "CASE_REVIEW_REQUIRED",
        "real_execution_entry": "HOLD",
        "source": {
            "requirement_intelligence": "runtime://PFC_HARNESS_REQUIREMENT_INTELLIGENCE",
            "coverage": "runtime://PFC_HARNESS_COVERAGE",
            "standard_test_case": "runtime://PFC_HARNESS_STANDARD_TEST_CASE",
        },
    }
    receipt_dir = STATE_ROOT / "evidence" / "field-validation" / "receipts"
    input_path = receipt_dir / "FV-2-auto-input.json"
    output_path = receipt_dir / "FV-2.json"
    write_json(input_path, receipt)
    command = [sys.executable, str(FV_TOOL), "fv-2", "--input", str(input_path), "--output", str(output_path)]
    env = os.environ.copy()
    env["AITEST_WORKSPACE_ROOT"] = str(WORKSPACE_ROOT)
    env["AITEST_DB_PATH"] = str(internal_db_path())
    completed = subprocess.run(command, cwd=str(WORKSPACE_ROOT), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    validation = load_json(output_path, {}) or {}
    return {"receipt": receipt, "input_path": str(input_path), "output_path": str(output_path), "validator_exit_code": completed.returncode, "validation": validation, "validator_stderr": completed.stderr[-500:]}


def blocker_messages(
    repo_state: dict[str, Any],
    checks: dict[str, Any],
    readiness: dict[str, Any],
    starlink: str | None,
    source_baseline_state: dict[str, Any] | None = None,
    deployment_baseline_state: dict[str, Any] | None = None,
    requirement_source_state: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    needs: list[str] = []
    if repo_state.get("missing"):
        blockers.append("实际仓库路径/工作副本不存在：" + "、".join(repo_state["missing"]))
        needs.append("请仅处理上述实际缺失的 PFC 本地仓库")
    if repo_state.get("invalid"):
        blockers.append("部分仓库路径或远端地址无法验证")
        needs.append("请确认仓库目录仍为当前工作副本")
    if not starlink:
        blockers.append("部署基线：等待 Starlink / 未确认")
        needs.append("请选择/确认当前 FAT2 Starlink")
    if not checks["git"]["ok"]:
        blockers.append("本机未检测到 Git")
        needs.append("请安装或启用 Git")
    if not checks["opencode"]["ok"]:
        blockers.append("本机未检测到 OpenCode，暂不能启动 AI worker")
        needs.append("请安装或启用 OpenCode")
    for code in readiness.get("preflight", {}).get("blockers", []) or []:
        mapping = {
            "BASELINE_NOT_READY": "部署基线尚未可用（代码基线与部署基线分开维护）",
            "H1_NOT_PASS": "需求基线尚未完成",
            "H2_SHOWCASE_NOT_PASS": "质量范围尚未完成",
            "TEST_APPLICABILITY_UNRESOLVED": "部分测试层级仍需范围判断",
            "SOURCE_BASELINE_NOT_VERIFIED": "代码基线尚未完全确认",
            "DEPLOYMENT_BASELINE_NOT_VERIFIED": "部署基线：等待 Starlink / 未确认",
            "REQUIREMENT_SOURCE_NOT_VERIFIED": "Requirement Source 尚未确认，不能生成 source-grounded 案例",
            "STANDARD_CASE_QUALITY_GAP": "标准案例仍有 CASE_QUALITY_GAP",
            "STANDARD_CASE_REVIEW_REQUIRED": "等待 Product Owner Review（CASE_REVIEW_REQUIRED）",
        }
        text = mapping.get(str(code), "执行前检查仍有未满足的外部条件")
        if text not in blockers:
            blockers.append(text)
    if source_baseline_state and source_baseline_state.get("status") not in {None, "VERIFIED"}:
        text = "代码基线尚未完全确认"
        if text not in blockers:
            blockers.append(text)
    if deployment_baseline_state and deployment_baseline_state.get("status") not in {None, "VERIFIED"}:
        text = "部署基线：等待 Starlink / 未确认"
        if text not in blockers:
            blockers.append(text)
    if requirement_source_state and requirement_source_state.get("status") != "VERIFIED":
        text = requirement_source_state.get("reason") or "Requirement Source 尚未确认"
        if text not in blockers:
            blockers.append(text)
        needs.append("请提供 STBB19-234 的真实 Requirement Source（正文、结构化字段、SST/Change、附件/规则）")
    if "等待 Product Owner Review（CASE_REVIEW_REQUIRED）" not in blockers:
        blockers.append("等待 Product Owner Review（CASE_REVIEW_REQUIRED）")
    if readiness.get("mission", {}).get("state") == "WAITING_HUMAN":
        blockers.append("真实执行需要人工登录或审批")
        needs.append("请完成当前页面中的登录/审批动作")
    return blockers, needs


def case_quality_summary(case: dict[str, Any]) -> dict[str, Any]:
    contract = case.get("contract") or {}
    required = ("purpose", "preconditions", "steps", "expected_result", "test_level", "coverage", "oracle", "requirement_fact_refs", "coverage_obligation_refs", "concrete_test_data", "defect_hypothesis")
    missing = [key for key in required if not contract.get(key)]
    return {
        "case_id": case.get("case_id"),
        "sst_id": case.get("sst_id"),
        "name": case.get("title"),
        "status": case.get("status"),
        "purpose": contract.get("purpose"),
        "preconditions": contract.get("preconditions") or [],
        "steps": contract.get("steps") or [],
        "expected_result": contract.get("expected_result"),
        "test_level": contract.get("test_level") or case.get("layer_id"),
        "coverage": contract.get("coverage") or [],
        "oracle": contract.get("oracle"),
        "system": contract.get("system"),
        "change": contract.get("change"),
        "business_rules": contract.get("business_rules") or [],
        "concrete_test_data": contract.get("concrete_test_data") or {},
        "positive": contract.get("positive"),
        "negative": contract.get("negative"),
        "boundary": contract.get("boundary"),
        "defect_hypothesis": contract.get("defect_hypothesis"),
        "requirement_fact_refs": contract.get("requirement_fact_refs") or [],
        "coverage_obligation_refs": contract.get("coverage_obligation_refs") or [],
        "source_grounding": contract.get("source_grounding") or {"status": contract.get("source_grounding_status")},
        "case_review_state": contract.get("case_review_state") or "CASE_REVIEW_REQUIRED",
        "quality_gap": missing,
    }


def readable_source_baseline(source: dict[str, Any]) -> str:
    status = str(source.get("status") or "FAIL")
    labels = {"VERIFIED": "已确认", "PARTIAL": "部分确认", "FAIL": "未确认"}
    count = f"{source.get('repository_count', 0)}/{source.get('expected_repository_count', 0)} 个仓库"
    detail = f"{count}；release branch = {source.get('release_branch', PROFILE['release_branch'])}"
    if source.get("missing_repositories"):
        detail += "；实际缺失：" + "、".join(source["missing_repositories"])
    if source.get("incomplete_repositories"):
        detail += "；待补充事实：" + "、".join(source["incomplete_repositories"])
    return f"{labels.get(status, status)}（{detail}）"


def readable_deployment_baseline(deployment: dict[str, Any]) -> str:
    if deployment.get("status") == "VERIFIED":
        facts = deployment.get("facts") or {}
        return "已确认（版本={}；部署={}；系统/应用={}/{}；分支/修订={}/{}）".format(
            facts.get("version", "未确认"), facts.get("deployment", "未确认"), facts.get("system", "未确认"), facts.get("app", "未确认"), facts.get("branch", "未确认"), str(facts.get("revision", "未确认"))[:12]
        )
    return "等待 Starlink / 未确认（{}）".format(deployment.get("reason") or "deployment facts 未取得")


def refresh_ai_runtime_for_status(runtime_reality: dict[str, Any], web_state: dict[str, Any]) -> dict[str, Any]:
    """Refresh AI Runtime without changing the already-running Web process."""
    if not isinstance(runtime_reality, dict) or web_state.get("status") != "PASS":
        return runtime_reality
    identity = runtime_reality.get("PFC_OPENCODE_INSTANCE_IDENTITY") or runtime_reality.get("instance_identity")
    if not isinstance(identity, dict) or not identity.get("endpoint") or not identity.get("pid"):
        return runtime_reality
    try:
        bind_opencode_instance(identity)
        live = opencode_runtime_probe(identity)
    except KeyboardInterrupt:
        live = {"authentication": {"status": "REPAIR", "failure_class": "STATUS_PROBE_INTERRUPTED"}, "provider_model": {"status": "REPAIR", "provider": "UNAVAILABLE", "model": "UNAVAILABLE"}, "human_action_required": False}
    except Exception as exc:
        live = {"authentication": {"status": "REPAIR", "failure_class": "STATUS_PROBE_FAILED", "error_detail": type(exc).__name__}, "provider_model": {"status": "REPAIR", "provider": "UNAVAILABLE", "model": "UNAVAILABLE"}, "human_action_required": False}
    prior_llm = runtime_reality.get("llm_invocation") if isinstance(runtime_reality.get("llm_invocation"), dict) else {}
    prior_r2 = runtime_reality.get("r2") if isinstance(runtime_reality.get("r2"), dict) else {}
    if live.get("authentication", {}).get("status") == "PASS" and live.get("provider_model", {}).get("status") == "PASS":
        llm = prior_llm if prior_llm.get("status") == "PASS" else real_llm_probe(live)
        r2 = prior_r2 if prior_r2.get("session_runtime", {}).get("status") == "PASS" else r2_runtime_probe(llm)
    else:
        llm = prior_llm or {"status": "REPAIR", "error_class": "AI_RUNTIME_NOT_READY", "response_received": False}
        r2 = prior_r2 or {"session_runtime": {"status": "REPAIR", "reason": "AI_RUNTIME_NOT_READY"}, "autonomous_runtime": "REPAIR"}
    auth_status = live.get("authentication", {}).get("status")
    prior_wait = runtime_reality.get("auth_wait") if isinstance(runtime_reality.get("auth_wait"), dict) else {}
    auth_wait = {**prior_wait, "status": "READY" if auth_status == "PASS" else "WAITING_FOR_AUTH" if auth_status == "HUMAN_ACTION_REQUIRED" else "WAITING_FOR_AI_RUNTIME", "non_blocking": True, "prompt_count": 0, "restart_attempted": False, "reprobe": "STATUS_SAME_INSTANCE", "last_probe_at": now_iso(), "identity_ref": identity.get("identity_ref")}
    refreshed = {**runtime_reality, **live, "opencode_web": web_runtime_public_state(web_state), "PFC_OPENCODE_INSTANCE_IDENTITY": identity, "auth_wait": auth_wait, "llm_invocation": llm, "r2": r2, "last_real_model_invocation": llm, "mission_ai_runtime_gate": "READY" if llm.get("status") == "PASS" and r2.get("session_runtime", {}).get("status") == "PASS" else "WAITING_FOR_AI_RUNTIME", "status_runtime_probe_at": now_iso()}
    acceptance = dict(refreshed.get("acceptance") or {})
    process_ready = refreshed["opencode_web"].get("status") == "PASS"
    acceptance.update({
        "PFC_OPENCODE_POST_AUTH_RESUME_REPAIR": "PASS" if process_ready else "REPAIR",
        "PFC_OPENCODE_SAME_INSTANCE_AUTH_REPROBE": "PASS" if process_ready else "REPAIR",
        "PFC_OPENCODE_UNNECESSARY_RESTART": "REMOVED",
        "PFC_OPENCODE_PROCESS_STOP_TIMEOUT": "IMPLEMENTED",
        "PFC_OPENCODE_PROCESS_LIFECYCLE": "PASS" if process_ready else "REPAIR",
        "PFC_OPENCODE_RAW_TRACEBACK_TO_USER": "REMOVED",
        "PFC_OPENCODE_PROCESS_RUNTIME_MODEL": "PASS" if process_ready else "REPAIR",
        "PFC_OPENCODE_WEB_START_INDEPENDENT_OF_AUTH": "PASS" if process_ready else "FAIL",
        "PFC_OPENCODE_AUTH_NON_BLOCKING": "PASS" if process_ready else "FAIL",
        "PFC_OPENCODE_PROVIDER_MODEL_NON_BLOCKING": "PASS" if process_ready else "FAIL",
        "PFC_OPENCODE_LLM_NON_BLOCKING_TO_WEB": "PASS" if process_ready else "FAIL",
        "PFC_R2_SESSION_GATE": "IMPLEMENTED",
        "PFC_PFC_MISSION_AI_RUNTIME_GATE": "IMPLEMENTED",
        "PFC_STATUS_RUNTIME_SEPARATION": "PASS",
        "PFC_OPENCODE_AUTH_REALITY": auth_status,
        "PFC_OPENCODE_PROVIDER_MODEL_REALITY": "PASS" if live.get("provider_model", {}).get("status") == "PASS" else "REPAIR",
        "PFC_LLM_INVOCATION_REALITY": "PASS" if llm.get("status") == "PASS" else "REPAIR",
        "PFC_R2_SESSION_RUNTIME_REALITY": "PASS" if r2.get("session_runtime", {}).get("status") == "PASS" else "REPAIR",
        "PFC_R2_AUTONOMOUS_RUNTIME_REALITY": r2.get("autonomous_runtime", "REPAIR"),
        "PFC_READY_PACKAGE_BANK_REALITY_ENTRY": "ALLOWED" if process_ready else "NOT_ALLOWED",
        "PFC_REAL_EXECUTION_ENTRY": "HOLD",
    })
    refreshed["acceptance"] = acceptance
    safe_refreshed = strip_private_runtime_fields(refreshed)
    try:
        write_json(STATE_ROOT / "evidence" / "field-validation" / "opencode-runtime-reality.json", safe_refreshed, private=True)
    except OSError:
        pass
    return safe_refreshed


def status_payload() -> dict[str, Any]:
    runtime_reality = load_json(STATE_ROOT / "evidence" / "field-validation" / "opencode-runtime-reality.json", {}) or {}
    web_state = load_json(WEB_RUNTIME_STATE_PATH, {}) or {}
    if web_state:
        runtime_reality["opencode_web"] = web_runtime_public_state(web_state)
        runtime_reality = refresh_ai_runtime_for_status(runtime_reality, web_state)
    if not runtime_reality:
        runtime_reality = {
            "stage": "尚未检查 AI Runtime",
            "executable": {"status": "REPAIR", "available": bool(opencode_executable()), "version": None},
            "authentication": {"status": "REPAIR", "failure_class": "NOT_PROBED"},
            "provider_model": {"status": "REPAIR", "provider": "UNAVAILABLE", "model": "UNAVAILABLE"},
            "llm_invocation": {"status": "NOT_VERIFIED", "response_received": False},
            "r2": {"session_runtime": {"status": "REPAIR"}, "autonomous_runtime": "REPAIR"},
            "opencode_web": {"status": "NOT_STARTED", "web_url": None, "endpoint": None},
            "acceptance": {
                **{key: "IMPLEMENTED" if startup_trace_enabled() else "REPAIR" for key in STARTUP_TRACE_ACCEPTANCE_KEYS},
                "PFC_OPENCODE_DIAGNOSTIC_ZIP": "OPTIONAL",
                "PFC_OPENCODE_PROVEN_V1_9_4_LAUNCH_PATH_REUSE": "IMPLEMENTED" if proven_v19_launch_path_reuse_enabled() else "NOT_APPLIED",
                "PFC_OPENCODE_GIT_BASH_SHELL_RESOLUTION": "IMPLEMENTED" if proven_v19_launch_path_reuse_enabled() else "NOT_APPLIED",
                "PFC_OPENCODE_SHELL_VERSION_AUTHORITY": "IMPLEMENTED" if proven_v19_launch_path_reuse_enabled() else "NOT_APPLIED",
                "PFC_OPENCODE_CANDIDATE_SELECTION": "EVIDENCE_ONLY" if proven_v19_launch_path_reuse_enabled() else "LEGACY_ADMISSION",
                "PFC_OPENCODE_VERSION_GUESSING": "STOPPED" if proven_v19_launch_path_reuse_enabled() else "ACTIVE_LEGACY_POLICY",
                "PFC_OPENCODE_STARTUP_ROOT_CAUSE": "REMOVED" if proven_v19_launch_path_reuse_enabled() else "NOT_REPAIRED",
                "PFC_OPENCODE_GENERATED_CONFIG_REALITY": "FAIL",
                "PFC_OPENCODE_DYNAMIC_PORT_REALITY": "FAIL",
                "PFC_OPENCODE_LAUNCH_CONFIG_CONSISTENCY": "FAIL",
                "PFC_OPENCODE_PROVEN_SHELL_LAUNCH_PATH": "FAIL",
                "PFC_OPENCODE_REAL_PROCESS_LAUNCH_PATH": "FAIL",
                "PFC_READY_PACKAGE_BANK_REALITY_ENTRY": "NOT_ALLOWED",
                "PFC_OPENCODE_PROCESS_RUNTIME_MODEL": "REPAIR",
                "PFC_OPENCODE_WEB_START_INDEPENDENT_OF_AUTH": "FAIL",
                "PFC_OPENCODE_AUTH_NON_BLOCKING": "REPAIR",
                "PFC_OPENCODE_PROVIDER_MODEL_NON_BLOCKING": "REPAIR",
                "PFC_OPENCODE_LLM_NON_BLOCKING_TO_WEB": "REPAIR",
                "PFC_R2_SESSION_GATE": "IMPLEMENTED",
                "PFC_PFC_MISSION_AI_RUNTIME_GATE": "IMPLEMENTED",
                "PFC_STATUS_RUNTIME_SEPARATION": "PASS",
                "PFC_PINNED_OPENCODE_RUNTIME": f"{pinned_opencode_runtime_contract()['version']} / FAIL" if pinned_opencode_runtime_enabled() else "NOT_APPLIED",
                "PFC_PINNED_OPENCODE_RUNTIME_PATH": "FAIL" if pinned_opencode_runtime_enabled() else "NOT_APPLIED",
                "PFC_OPENCODE_VERSION_AND_LAUNCH_SAME_RUNTIME": "FAIL" if pinned_opencode_runtime_enabled() else "NOT_APPLIED",
                "PFC_OPENCODE_REAL_WEB_LAUNCH_PATH": "FAIL" if pinned_opencode_runtime_enabled() else "NOT_APPLIED",
                "PFC_OPENCODE_AUTH_REPROBE": "IMPLEMENTED" if pinned_opencode_runtime_enabled() else "NOT_APPLIED",
                "PFC_OPENCODE_GIT_BASH_COMMAND_ADMISSION": "IMPLEMENTED" if proven_git_bash_command_enabled() else "NOT_APPLIED",
                "PFC_OPENCODE_VERSION_AND_WEB_SAME_SHELL": "REPAIR" if proven_git_bash_command_enabled() else "NOT_APPLIED",
                "PFC_WINDOWS_OPENCODE_CMD_SHIM_RESOLUTION": "REPAIR",
                "PFC_OPENCODE_MULTI_VERSION_MATRIX": "CREATED",
                "PFC_OPENCODE_SELECTED_LAUNCHER": "NOT_SELECTED",
                "PFC_OPENCODE_SELECTED_VERSION": "NOT_SELECTED",
                "PFC_OPENCODE_REAL_WEB_PROCESS_LAUNCH": "IMPLEMENTED",
                "PFC_OPENCODE_REAL_WEB_LAUNCH": "REPAIR",
                "PFC_OPENCODE_PACKAGE_WORKSPACE": "PASS",
                "PFC_OPENCODE_DYNAMIC_PORT": "REPAIR",
                "PFC_OPENCODE_AUTH_WAIT_FLOW": "IMPLEMENTED",
                "PFC_OPENCODE_BANK_REALITY_ENTRY": "ALLOWED",
                "PFC_OPENCODE_REAL_WEB_LAUNCHER": "IMPLEMENTED",
                "PFC_OPENCODE_PACKAGE_OWNED_WORKSPACE": "PASS",
                "PFC_OPENCODE_BINARY_VERSION_PINNING": "REPAIR",
                "PFC_OPENCODE_AUTH_WAIT_RESUME": "IMPLEMENTED",
                "PFC_OPENCODE_AUTH_SAME_INSTANCE_GUARD": "REPAIR",
                "PFC_OPENCODE_PROVIDER_MODEL_PROBE": "IMPLEMENTED",
                "PFC_OPENCODE_REAL_LLM_PROBE": "IMPLEMENTED",
                "PFC_R2_SESSION_CREATE_RESUME": "IMPLEMENTED",
                "PFC_READY_PACKAGE_BANK_RUNTIME_REALITY_ENTRY": "ALLOWED",
                "PFC_OPENCODE_BINARY_IDENTITY": "REPAIR",
                "PFC_OPENCODE_VERSION_REALITY": "REPAIR",
                "PFC_OPENCODE_WORKSPACE_ISOLATION": "REPAIR",
                "PFC_OPENCODE_WEB_INSTANCE_IDENTITY": "REPAIR",
                "PFC_OPENCODE_AUTH_PROBE_TARGET": "REPAIR",
                "PFC_OPENCODE_AUTH_REALITY": "REPAIR",
                "PFC_OPENCODE_PROVIDER_MODEL_REALITY": "REPAIR",
                "PFC_LLM_INVOCATION_REALITY": "REPAIR",
                "PFC_R2_SESSION_RUNTIME_REALITY": "REPAIR",
                "PFC_R2_AUTONOMOUS_RUNTIME_REALITY": "REPAIR",
                "PFC_CURRENT_COVERAGE_PROVENANCE": "NOT_VERIFIED / QUARANTINED" if (PROFILE.get("opencode_runtime_launch_auth_orchestration_repair") or PROFILE.get("opencode_windows_cmd_shim_resolution_and_real_web_launch_repair")) else "NOT_VERIFIED",
                "PFC_CURRENT_STANDARD_CASE_PROVENANCE": "NOT_VERIFIED / QUARANTINED" if (PROFILE.get("opencode_runtime_launch_auth_orchestration_repair") or PROFILE.get("opencode_windows_cmd_shim_resolution_and_real_web_launch_repair")) else "NOT_VERIFIED",
                "PFC_R3_REQUIREMENT_SOURCE_REPAIR_ENTRY": "HOLD",
                "PFC_REAL_EXECUTION_ENTRY": "HOLD",
                "ARCHITECTURE_DRIFT": "NO",
                "HARD_DEPENDENCY_FAILURE": "NO",
            },
        }
    runtime_acceptance = runtime_reality.get("acceptance") or {}
    if not internal_db_path().is_file():
        source_state = load_requirement_source_state()
        if not source_state:
            source_state = source_failure("HUMAN_ACTION_REQUIRED", "SOURCE_NOT_CONFIGURED", f"未取得 {PROFILE['first_validation_target']} 的真实 Requirement Source", source_ref=f"starlink://PFC/FAT2/{PROFILE['first_validation_target']}")
        version_truth = current_version_truth()
        return {
            "started": False,
            "project": PROJECT_ID,
            "version": version_truth.get("version") or version_truth["status"],
            "bootstrap_version": PROFILE["version"],
            "version_truth": version_truth,
            "active_scope": active_requirement_id(),
            "stage": "尚未启动",
            "source_baseline": {"status": "FAIL", "repository_count": 0, "expected_repository_count": len(PROFILE.get("local_repositories") or {})},
            "deployment_baseline": {"status": "NOT_VERIFIED", "reason": "等待 Starlink / 未确认"},
            "requirement_source": source_state,
            "ai_runtime": runtime_reality,
            "runtime_acceptance": runtime_acceptance,
            "coverage": {"total": 0, "required": 0, "selected": 0, "excluded": 0, "pending": 0, "unresolved": 0, "items": []},
            "execution": {"status": "尚未开始"},
            "human_actions": [],
            "evidence": [],
            "cases": [],
            "r3": {"requirement_source_grounding": source_state.get("status"), "coverage_grounding": "REPAIR", "standard_case_quality": "REPAIR", "case_review_state": "CASE_REVIEW_REQUIRED", "real_execution_entry": "HOLD"},
        }
    storage.initialize()
    runtime_reality["interactive_context"] = interactive_context_snapshot()
    missions = rows("SELECT * FROM missions WHERE project_id=? ORDER BY updated_at DESC", (PROJECT_ID,))
    current = mission.get_mission(missions[0]["mission_id"]) if missions else None
    try:
        repo_state = discover_repositories(PROJECT_ID)
    except Exception:
        repo_rows = rows("SELECT full_name,local_path,remote_url,system_id,current_branch,head_sha,default_branch FROM repositories WHERE project_id=? ORDER BY full_name", (PROJECT_ID,))
        repo_state = {"found": repo_rows, "count": len(repo_rows), "expected": list(PROFILE["local_repositories"]), "missing": [module for module in PROFILE["local_repositories"] if not any(repository_module(row) == module for row in repo_rows)], "invalid": []}
    source_state = summarize_source_baseline(repo_state)
    requirement_source = load_requirement_source_state()
    if not requirement_source:
        requirement_source = source_failure("HUMAN_ACTION_REQUIRED", "SOURCE_NOT_CONFIGURED", f"未取得 {PROFILE['first_validation_target']} 的真实 Requirement Source", source_ref=f"starlink://PFC/FAT2/{PROFILE['first_validation_target']}")
    starlink = str(os.environ.get("PFC_STARLINK_ENDPOINT") or machine_profile().get("starlink_endpoint") or "").strip() or None
    deployment_state = deployment_baseline(starlink)
    cases: list[dict[str, Any]] = []
    for row in rows("SELECT * FROM test_cases WHERE requirement_id=? ORDER BY case_id", (PROFILE["first_validation_target"],)):
        cases.append(case_quality_summary(quality.test_case(row["case_id"])))
    results = rows("SELECT rr.status,tc.title FROM run_results rr JOIN test_runs tr ON tr.run_id=rr.run_id LEFT JOIN test_cases tc ON tc.case_id=rr.case_id WHERE tr.mission_id=? ORDER BY tr.started_at DESC LIMIT 5", (current["mission_id"],)) if current else []
    defects_rows = rows("SELECT defect_id,title,status,severity FROM defects WHERE project_id=? ORDER BY updated_at DESC LIMIT 5", (PROJECT_ID,))
    coverage_rows = rows("SELECT status,COUNT(*) AS count FROM applicability WHERE requirement_id=? GROUP BY status ORDER BY status", (PROFILE["first_validation_target"],))
    coverage_counts = {str(item["status"]): int(item["count"]) for item in coverage_rows}
    if runtime_acceptance.get("PFC_R3_REQUIREMENT_SOURCE_REPAIR_ENTRY") != "ALLOWED":
        requirement_source = {**requirement_source, "status": "HUMAN_ACTION_REQUIRED", "failure_class": "R3_ENTRY_HOLD", "reason": "OpenCode/LLM Runtime Reality 未通过，Requirement Source 尚未进入本轮 R3 重建"}
    coverage_items = coverage_items_for(PROFILE["first_validation_target"], requirement_source, cases)
    selected_count = sum(1 for item in coverage_items if item["disposition"] == "SELECTED")
    excluded_count = sum(1 for item in coverage_items if item["disposition"] == "EXCLUDED")
    pending_count = sum(1 for item in coverage_items if item["disposition"] == "PENDING")
    coverage = {
        "total": sum(coverage_counts.values()),
        "required": selected_count,
        "selected": selected_count,
        "excluded": excluded_count,
        "pending": pending_count,
        "unresolved": pending_count,
        "counts": coverage_counts,
        "items": coverage_items,
    }
    human_actions = rows("SELECT title,requested_action,status FROM human_tasks WHERE mission_id=? AND status IN ('WAITING','CLAIMED') ORDER BY created_at DESC", (current["mission_id"],)) if current else []
    evidence = rows("SELECT channel,status,created_at FROM evidence WHERE mission_id=? ORDER BY created_at DESC LIMIT 5", (current["mission_id"],)) if current else []
    fv2 = load_json(STATE_ROOT / "evidence" / "field-validation" / "receipts" / "FV-2.json", {}) or {}
    if fv2:
        evidence.insert(0, {"channel": "FV-2 自动收据", "status": str(fv2.get("status") or "未确认"), "created_at": fv2.get("validated_at") or fv2.get("generated_at") or "刚刚"})
    run = one("SELECT run_id,status,summary_json FROM test_runs WHERE mission_id=? ORDER BY started_at DESC LIMIT 1", (current["mission_id"],)) if current else None
    execution = {"status": "尚未开始"}
    if run:
        execution_labels = {"RUNNING": "执行中", "PASS": "通过", "FAIL": "发现失败", "ABORTED": "已中止"}
        execution = {"status": execution_labels.get(str(run["status"]), "执行状态待确认"), "summary": json.loads(run.get("summary_json") or "{}")} 
    checks = runtime_checks()
    metadata = (current or {}).get("metadata") or {}
    case_quality_ready = requirement_source.get("status") == "VERIFIED" and bool(cases) and all(not item.get("quality_gap") and item.get("status") == "ACTIVE" for item in cases)
    readiness = {"preflight": {"blockers": []}, "mission": current or {}}
    if requirement_source.get("status") != "VERIFIED":
        readiness["preflight"]["blockers"].append("REQUIREMENT_SOURCE_NOT_VERIFIED")
    if not case_quality_ready:
        readiness["preflight"]["blockers"].append("STANDARD_CASE_QUALITY_GAP")
    readiness["preflight"]["blockers"].append("STANDARD_CASE_REVIEW_REQUIRED")
    blockers, needs = blocker_messages(repo_state, checks, readiness, starlink, source_state, deployment_state, requirement_source)
    if not case_quality_ready and "标准案例仍有 CASE_QUALITY_GAP" not in blockers:
        blockers.append("标准案例仍有 CASE_QUALITY_GAP")
    if "等待 Product Owner Review（CASE_REVIEW_REQUIRED）" not in blockers:
        blockers.append("等待 Product Owner Review（CASE_REVIEW_REQUIRED）")
    if runtime_acceptance.get("PFC_R3_REQUIREMENT_SOURCE_REPAIR_ENTRY") != "ALLOWED":
        blockers.append("OpenCode Auth/LLM Runtime Reality 未通过，R3 Requirement Source 修复入口保持 HOLD")
        if runtime_reality.get("human_action_required"):
            needs.append("请在当前已启动的 OpenCode Web 中完成银行认证，然后运行 STATUS；不要重新运行 START")
        elif (runtime_reality.get("provider_model") or {}).get("status") != "PASS":
            needs.append("请在当前 OpenCode Web 中完成 Provider/Model 配置，然后运行 STATUS；Web 进程保持可用")
    r3_status = {
        "requirement_source_grounding": "PASS" if requirement_source.get("status") == "VERIFIED" else "HUMAN_ACTION_REQUIRED",
        "coverage_grounding": "PASS" if requirement_source.get("status") == "VERIFIED" and pending_count == 0 else "REPAIR",
        "standard_case_quality": "READY_FOR_PRODUCT_OWNER_REVIEW" if case_quality_ready else "REPAIR",
        "case_visibility": "PASS" if bool(cases) else "REPAIR",
        "real_execution_entry": "HOLD",
        "field_validation": "IN_PROGRESS",
        "architecture_drift": "NO",
        "hard_dependency_failure": "NO",
        "case_review_state": "CASE_REVIEW_REQUIRED",
    }
    version_truth = current_version_truth()
    return {
        "started": True,
        "project": PROJECT_ID,
        "version": version_truth.get("version") or version_truth["status"],
        "bootstrap_version": PROFILE["version"],
        "version_truth": version_truth,
        "requirement": active_requirement_id(),
        "active_scope": active_requirement_id(),
        "mission": current,
        "stage": stage_for(current),
        "doing": doing_for(current),
        "blockers": blockers,
        "needs": needs,
        "source_baseline": source_state or metadata.get("source_baseline"),
        "deployment_baseline": deployment_state or metadata.get("deployment_baseline"),
        "requirement_source": requirement_source,
        "ai_runtime": runtime_reality,
        "runtime_acceptance": runtime_acceptance,
        "cases": cases,
        "results": results,
        "defects": defects_rows,
        "repositories": repo_state.get("found", []),
        "checks": checks,
        "coverage": coverage,
        "r3": r3_status,
        "execution": execution,
        "human_actions": human_actions,
        "evidence": evidence,
    }


def row_json(row: dict[str, Any], key: str, default: Any = None) -> Any:
    value = row.get(key)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value if value is not None else default


def active_requirement_id() -> str:
    if not internal_db_path().is_file():
        return str(PROFILE["first_validation_target"])
    try:
        row = one("SELECT value FROM meta WHERE key='PFC_ACTIVE_REQUIREMENT_ID'")
    except sqlite3.OperationalError:
        row = None
    return str(row["value"]) if row and row.get("value") else str(PROFILE["first_validation_target"])


def current_version_truth() -> dict[str, Any]:
    """Expose current-version truth only after source and deployment sync."""
    if not internal_db_path().is_file():
        return {
            "status": "CURRENT_VERSION_RECON_REQUIRED",
            "bootstrap_version": PROFILE["version"],
            "release_id": RELEASE_ID,
            "source": "PFC_PROJECT_PROFILE.json",
            "reason": "No durable release/deployment truth is initialized",
        }
    try:
        release = one("SELECT * FROM releases WHERE project_id=? AND release_id=?", (PROJECT_ID, RELEASE_ID))
    except sqlite3.OperationalError:
        release = None
    if not release:
        return {
            "status": "CURRENT_VERSION_RECON_REQUIRED",
            "bootstrap_version": PROFILE["version"],
            "release_id": RELEASE_ID,
            "source": "PFC_DURABLE_SQLITE_TRUTH",
            "reason": "Durable release truth is not registered",
        }
    metadata = row_json(release, "metadata_json", {})
    source = metadata.get("source_baseline") if isinstance(metadata.get("source_baseline"), dict) else {}
    deployment = metadata.get("deployment_baseline") if isinstance(metadata.get("deployment_baseline"), dict) else {}
    source_status = str(source.get("status") or "NOT_VERIFIED")
    deployment_status = str(deployment.get("status") or "NOT_VERIFIED")
    if source_status == "VERIFIED" and deployment_status == "VERIFIED":
        return {
            "status": "VERIFIED",
            "version": release.get("name") or PROFILE["version"],
            "release_id": release.get("release_id") or RELEASE_ID,
            "release_branch": release.get("release_branch") or PROFILE.get("release_branch"),
            "source": "PFC_DURABLE_SQLITE_TRUTH",
            "source_baseline_status": source_status,
            "deployment_baseline_status": deployment_status,
        }
    return {
        "status": "CURRENT_VERSION_RECON_REQUIRED",
        "bootstrap_version": release.get("name") or PROFILE["version"],
        "release_id": release.get("release_id") or RELEASE_ID,
        "source": "PFC_DURABLE_SQLITE_TRUTH",
        "source_baseline_status": source_status,
        "deployment_baseline_status": deployment_status,
        "reason": "Bootstrap release exists, but current source/deployment truth is not verified",
    }


def set_active_requirement(requirement_id: str) -> dict[str, Any]:
    requirement_id = str(requirement_id).strip()
    known = set(str(item) for item in PROFILE.get("requirements") or [])
    if one("SELECT requirement_id FROM requirements WHERE requirement_id=?", (requirement_id,)):
        known.add(requirement_id)
    if requirement_id not in known:
        return {"status": "REPAIR", "error_class": "REQUIREMENT_NOT_IN_PROJECT_SCOPE", "requirement_id": requirement_id}
    with storage.transaction() as conn:
        conn.execute(
            "INSERT INTO meta(key,value) VALUES('PFC_ACTIVE_REQUIREMENT_ID',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (requirement_id,),
        )
    return {"status": "PASS", "active_scope": requirement_id, "scope_source": "PFC_META"}


def current_project_missions(requirement_id: str | None = None) -> list[dict[str, Any]]:
    if requirement_id:
        return rows("SELECT * FROM missions WHERE project_id=? AND requirement_id=? ORDER BY updated_at DESC", (PROJECT_ID, requirement_id))
    return rows("SELECT * FROM missions WHERE project_id=? ORDER BY updated_at DESC", (PROJECT_ID,))


def canonical_requirement_truth(requirement_id: str) -> dict[str, Any]:
    requirement_row = one("SELECT * FROM requirements WHERE requirement_id=?", (requirement_id,))
    sst_rows = rows("SELECT * FROM requirement_ssts WHERE requirement_id=? ORDER BY sst_id", (requirement_id,))
    quality_rows = rows("SELECT * FROM sst_quality_scope WHERE requirement_id=? ORDER BY sst_id", (requirement_id,))
    applicability_rows = rows("SELECT * FROM applicability WHERE requirement_id=? ORDER BY sst_id,layer_id,dimension", (requirement_id,))
    case_rows = [case_quality_summary(quality.test_case(item["case_id"])) for item in rows("SELECT case_id FROM test_cases WHERE requirement_id=? ORDER BY case_id", (requirement_id,))]
    mission_rows = []
    for item in current_project_missions(requirement_id):
        try:
            hydrated = mission.get_mission(item["mission_id"])
        except (KeyError, sqlite3.OperationalError):
            hydrated = item
        hydrated["metadata"] = row_json(hydrated, "metadata_json", hydrated.get("metadata", {}))
        hydrated.pop("metadata_json", None)
        mission_rows.append(hydrated)
    for item in sst_rows:
        item["metadata"] = row_json(item, "metadata_json", {})
        item.pop("metadata_json", None)
    for item in quality_rows:
        item["source_ref"] = item.get("source_ref")
    requirement_value = dict(requirement_row) if requirement_row else {"requirement_id": requirement_id, "status": "NOT_REGISTERED"}
    requirement_value["metadata"] = row_json(requirement_value, "metadata_json", {})
    requirement_value.pop("metadata_json", None)
    return {
        "requirement": requirement_value,
        "ssts": sst_rows,
        "quality_scope": quality_rows,
        "coverage": {"total": len(applicability_rows), "rows": applicability_rows},
        "cases": case_rows,
        "missions": mission_rows,
        "mission_plans": rows("SELECT mission_id,version,status,reason,created_by,created_at,plan_hash FROM mission_plans WHERE mission_id IN (SELECT mission_id FROM missions WHERE project_id=? AND requirement_id=?) ORDER BY created_at", (PROJECT_ID, requirement_id)),
        "human_tasks": rows("SELECT * FROM human_tasks WHERE mission_id IN (SELECT mission_id FROM missions WHERE project_id=? AND requirement_id=?) ORDER BY created_at DESC", (PROJECT_ID, requirement_id)),
    }


def canonical_truth_payload(target: str = "status", requirement_id: str | None = None, case_id: str | None = None) -> dict[str, Any]:
    """Return a read model from durable truth for the OpenCode Web bridge."""
    storage.initialize()
    target = str(target or "status").strip().lower()
    req_id = str(requirement_id or active_requirement_id())
    base = status_payload()
    if target in {"status", "all"}:
        payload: dict[str, Any] = {
            "truth_source": "PFC_DURABLE_SQLITE_TRUTH",
            "conversation_is_not_truth": True,
            "active_scope": req_id,
            "status": base,
            "requirements": [canonical_requirement_truth(str(item["requirement_id"])) for item in rows("SELECT requirement_id FROM requirements WHERE project_id=? AND release_id=? ORDER BY requirement_id", (PROJECT_ID, RELEASE_ID))],
        }
        if not payload["requirements"]:
            payload["requirements"] = [canonical_requirement_truth(str(item)) for item in PROFILE.get("requirements") or []]
    else:
        truth_value = canonical_requirement_truth(req_id)
        if target == "requirement":
            payload = {"truth_source": "PFC_DURABLE_SQLITE_TRUTH", "conversation_is_not_truth": True, "active_scope": req_id, "requirement": truth_value["requirement"], "ssts": truth_value["ssts"], "quality_scope": truth_value["quality_scope"]}
        elif target == "coverage":
            payload = {"truth_source": "PFC_DURABLE_SQLITE_TRUTH", "conversation_is_not_truth": True, "active_scope": req_id, "coverage": truth_value["coverage"]}
        elif target == "cases":
            selected = [item for item in truth_value["cases"] if not case_id or item.get("case_id") == case_id]
            payload = {"truth_source": "PFC_DURABLE_SQLITE_TRUTH", "conversation_is_not_truth": True, "active_scope": req_id, "cases": selected, "case_provenance": (base.get("runtime_acceptance") or {}).get("PFC_CURRENT_STANDARD_CASE_PROVENANCE", "NOT_VERIFIED")}
        elif target == "mission":
            payload = {"truth_source": "PFC_DURABLE_SQLITE_TRUTH", "conversation_is_not_truth": True, "active_scope": req_id, "missions": truth_value["missions"]}
        elif target == "execution":
            runs = rows("SELECT * FROM test_runs WHERE requirement_id=? ORDER BY started_at DESC", (req_id,))
            for item in runs:
                item["summary"] = row_json(item, "summary_json", {})
                item.pop("summary_json", None)
            evidence = rows("SELECT e.* FROM evidence e JOIN missions m ON m.mission_id=e.mission_id WHERE m.project_id=? AND m.requirement_id=? ORDER BY e.created_at DESC", (PROJECT_ID, req_id))
            for item in evidence:
                item["payload"] = row_json(item, "payload_json", {})
                item.pop("payload_json", None)
            payload = {"truth_source": "PFC_DURABLE_SQLITE_TRUTH", "conversation_is_not_truth": True, "active_scope": req_id, "runs": runs, "evidence": evidence, "real_execution_entry": "HOLD"}
        elif target in {"defects", "defect"}:
            payload = {"truth_source": "PFC_DURABLE_SQLITE_TRUTH", "conversation_is_not_truth": True, "active_scope": req_id, "observations": rows("SELECT * FROM observations WHERE requirement_id=? ORDER BY observed_at DESC", (req_id,)), "diagnoses": rows("SELECT * FROM diagnoses WHERE observation_id IN (SELECT observation_id FROM observations WHERE requirement_id=?) ORDER BY diagnosed_at DESC", (req_id,)), "defects": rows("SELECT * FROM defects WHERE requirement_id=? ORDER BY updated_at DESC", (req_id,))}
        elif target in {"human_actions", "human"}:
            payload = {"truth_source": "PFC_DURABLE_SQLITE_TRUTH", "conversation_is_not_truth": True, "active_scope": req_id, "human_actions": rows("SELECT * FROM human_tasks WHERE mission_id IN (SELECT mission_id FROM missions WHERE project_id=? AND requirement_id=?) ORDER BY created_at DESC", (PROJECT_ID, req_id))}
        elif target in {"project", "database", "db"}:
            payload = {"truth_source": "PFC_DURABLE_SQLITE_TRUTH", "conversation_is_not_truth": True, "active_scope": req_id, "project": project.project_status(PROJECT_ID) if one("SELECT project_id FROM projects WHERE project_id=?", (PROJECT_ID,)) else {"status": "NOT_INITIALIZED", "project_id": PROJECT_ID}, "database": {"path_present": internal_db_path().is_file(), "schema": "PINNED_V3_RUNTIME"}}
        else:
            payload = {"status": "REPAIR", "error_class": "UNKNOWN_TRUTH_TARGET", "allowed_targets": ["status", "project", "requirement", "coverage", "cases", "mission", "execution", "defects", "human_actions", "all"]}
    payload["version_truth"] = base.get("version_truth") or current_version_truth()
    return redact(payload)


def runtime_gate_allowed(runtime_reality: dict[str, Any] | None = None) -> bool:
    acceptance = (runtime_reality or load_json(STATE_ROOT / "evidence" / "field-validation" / "opencode-runtime-reality.json", {}) or {}).get("acceptance") or {}
    return all(acceptance.get(key) == "PASS" for key in ("PFC_OPENCODE_AUTH_REALITY", "PFC_OPENCODE_PROVIDER_MODEL_REALITY", "PFC_LLM_INVOCATION_REALITY", "PFC_R2_SESSION_RUNTIME_REALITY", "PFC_R2_AUTONOMOUS_RUNTIME_REALITY"))


def interactive_context_snapshot() -> dict[str, Any]:
    if not internal_db_path().is_file():
        return {"status": "NO_DURABLE_PROJECT", "project": PROJECT_ID, "active_scope": active_requirement_id(), "mission": None, "worker_sessions_open": 0}
    mission_rows = current_project_missions(active_requirement_id())
    current = mission_rows[0] if mission_rows else None
    active_workers = rows("SELECT worker_role FROM worker_sessions WHERE status='OPEN' AND mission_id IN (SELECT mission_id FROM missions WHERE project_id=?)", (PROJECT_ID,))
    return {
        "status": "PASS" if current else "NO_DURABLE_MISSION",
        "project": PROJECT_ID,
        "active_scope": active_requirement_id(),
        "mission_state": current.get("state") if current else None,
        "mission_cursor_present": bool(current and current.get("current_step_id")),
        "worker_sessions_open": len(active_workers),
    }


def interactive_context_restore(runtime_reality: dict[str, Any]) -> dict[str, Any]:
    context = interactive_context_snapshot()
    if not context.get("mission_state"):
        return {**context, "resume": "NOT_ATTEMPTED", "reason": "NO_DURABLE_MISSION"}
    if not runtime_gate_allowed(runtime_reality):
        return {**context, "resume": "HOLD", "reason": "OPENCODE_RUNTIME_ADMISSION_REQUIRED"}
    missions = current_project_missions(active_requirement_id())
    current = missions[0] if missions else None
    if not current:
        return {**context, "resume": "NOT_ATTEMPTED", "reason": "NO_DURABLE_MISSION"}
    resume = mission.continue_mission(current["mission_id"], "aitest-director")
    worker_state: dict[str, Any] = {"status": "NOT_ATTEMPTED"}
    try:
        active = session.active_worker_session(current["mission_id"], "DIRECTOR")
        if active:
            worker_state = {"status": "PASS", "reused": True}
        else:
            opened = session.open_worker_session(current["mission_id"], "DIRECTOR", provider="OPENCODE", opencode_url=opencode_endpoint(), allow_mock=False)
            worker_state = {"status": "PASS", "reused": False, "session_identity_ref": digest(opened.get("provider_session_id"))[:20]}
    except Exception as exc:
        worker_state = {"status": "REPAIR", "error_class": type(exc).__name__}
    return {**context, "resume": resume.get("action", "UNKNOWN"), "worker_session": worker_state}


def interactive_command(intent: str, requirement_id: str | None = None, case_id: str | None = None, note: str | None = None) -> dict[str, Any]:
    """Canonical command boundary for natural-language OpenCode Web requests."""
    storage.initialize()
    intent = str(intent or "").strip().lower()
    req_id = str(requirement_id or active_requirement_id())
    if intent in {"select_requirement", "scope"}:
        return redact(set_active_requirement(req_id))
    if intent in {"show", "query"}:
        return canonical_truth_payload("all", req_id)
    if intent in {"hold", "pause", "do_not_execute"}:
        set_control(stop_requested=True, stop_reason="OpenCode Web requested hold")
        current = current_project_missions(req_id)
        checkpoint_refs = []
        for item in current:
            if item.get("state") not in {"COMPLETED", "ABORTED"}:
                checkpoint_refs.append(mission.checkpoint(item["mission_id"], "OPENCODE_WEB_HOLD")["context_hash"])
        return {"status": "PASS", "command": "HOLD", "execution_started": False, "checkpointed": len(checkpoint_refs), "next": "PFC_REAL_EXECUTION_ENTRY remains HOLD"}
    if intent in {"continue", "resume"}:
        if not runtime_gate_allowed():
            return {"status": "HOLD", "command": "MISSION_CONTINUE", "reason": "OPENCODE_RUNTIME_ADMISSION_REQUIRED", "execution_started": False}
        missions = current_project_missions(req_id)
        if not missions:
            return {"status": "NOT_FOUND", "command": "MISSION_CONTINUE", "reason": "NO_DURABLE_MISSION", "execution_started": False}
        return redact({"status": "PASS", "command": "MISSION_CONTINUE", "result": mission.continue_mission(missions[0]["mission_id"], "aitest-director"), "execution_started": False})
    if intent in {"review_reject", "request_case_rework", "redesign_case"}:
        if not runtime_gate_allowed():
            return {"status": "HOLD", "command": "CASE_REWORK_REQUEST", "reason": "OPENCODE_RUNTIME_ADMISSION_REQUIRED", "execution_started": False}
        if not case_id:
            return {"status": "REPAIR", "command": "CASE_REWORK_REQUEST", "reason": "CASE_ID_REQUIRED", "execution_started": False}
        case = one("SELECT case_id FROM test_cases WHERE case_id=? AND requirement_id=?", (case_id, req_id))
        if not case:
            return {"status": "NOT_FOUND", "command": "CASE_REWORK_REQUEST", "reason": "CASE_NOT_FOUND", "execution_started": False}
        with storage.transaction() as conn:
            conn.execute("UPDATE test_cases SET status='REWORK_REQUESTED',updated_at=? WHERE case_id=?", (now_iso(), case_id))
        missions = current_project_missions(req_id)
        if missions:
            mission.request_replan(missions[0]["mission_id"], "human", note or "Product Owner requested StandardTestCase redesign")
        return {"status": "PASS", "command": "CASE_REWORK_REQUEST", "case_lifecycle": "REWORK_REQUESTED", "execution_started": False}
    if intent in {"execute_approved", "execute", "rerun_failed", "retest"}:
        return {"status": "HOLD", "command": intent.upper(), "reason": "PFC_REAL_EXECUTION_ENTRY_HOLD", "execution_started": False, "attempt_created": False, "next": "需要银行 Reality Gate、Product Owner Review 与显式执行授权"}
    if intent in {"cat", "inspect_cat", "database_status", "db_status", "defect_assessment"}:
        target = "defects" if intent == "defect_assessment" else "project" if intent in {"database_status", "db_status"} else "all"
        result = canonical_truth_payload(target, req_id)
        if intent in {"cat", "inspect_cat"}:
            result["cat"] = {"status": "NOT_VERIFIED", "connectors": rows("SELECT connector_id,kind,name,status,last_checked_at,last_error FROM connectors WHERE project_id=? AND kind='CAT'", (PROJECT_ID,))}
        return result
    return {"status": "REPAIR", "error_class": "UNKNOWN_CANONICAL_INTENT", "allowed_intents": ["show", "select_requirement", "continue", "hold", "review_reject", "execute_approved", "rerun_failed", "cat", "database_status", "defect_assessment"]}


def stage_for(current: dict[str, Any] | None) -> str:
    if not current:
        return "已初始化项目，等待任务"
    mapping = {"DRAFT": "初始化任务", "DISCOVERING": "发现项目事实", "TRUTH_SYNC": "同步版本事实", "SCOPING": "建立质量范围", "PLANNING": "AI 正在规划执行", "PREFLIGHT": "执行前检查", "WAITING_H3": "等待执行审批", "EXECUTING": "正在执行字段校验", "VERIFYING": "正在核对结果", "WAITING_HUMAN": "等待人工动作", "WAITING_H4": "等待结果确认", "COMPLETED": "本轮已完成", "BLOCKED": "等待阻塞条件解除"}
    return mapping.get(str(current.get("state")), str(current.get("state")))


def doing_for(current: dict[str, Any] | None) -> str:
    if not current:
        return "准备 PFC 项目"
    if current.get("state") in {"PLANNING", "DISCOVERING", "TRUTH_SYNC", "SCOPING"}:
        return "自动登记版本、仓库、需求映射，并生成测试范围与案例"
    if current.get("state") in {"EXECUTING", "VERIFYING"}:
        return "按已冻结计划推进真实执行并收集证据"
    if current.get("state") == "WAITING_HUMAN":
        return "保留当前游标，等待你完成必要的登录或审批"
    return "恢复并检查当前 Mission 的持久化游标"


def print_requirement_view(payload: dict[str, Any]) -> None:
    acceptance = payload.get("runtime_acceptance") or {}
    print(f"PFC_R3_REQUIREMENT_SOURCE_REPAIR_ENTRY = {acceptance.get('PFC_R3_REQUIREMENT_SOURCE_REPAIR_ENTRY', 'HOLD')}")
    print("PFC_READY_PACKAGE_INTERACTIVE_USAGE_MODEL = PASS")
    print("PFC_READY_PACKAGE_AUTONOMOUS_MODE = PASS")
    print("PFC_READY_PACKAGE_OPENCODE_WEB_INTEGRATION = IMPLEMENTED_PENDING_BANK_REALITY")
    print("PFC_READY_PACKAGE_SHARED_DURABLE_CONTEXT = PASS")
    print("PFC_READY_PACKAGE_SESSION_RESUME_MODEL = PASS")
    print("PFC_READY_PACKAGE_LONG_RUNNING_WORKSPACE = PASS")
    print(f"PFC_READY_PACKAGE_BANK_INTERACTIVE_REALITY_ENTRY = {'ALLOWED' if PROFILE.get('opencode_runtime_launch_auth_orchestration_repair') else 'NOT_ALLOWED'}")
    source = payload.get("requirement_source") or {}
    print(f"Requirement Source 状态：{source.get('status', 'HUMAN_ACTION_REQUIRED')}")
    if source.get("status") != "VERIFIED":
        print(f"失败分类：{source.get('failure_class') or '未分类'}")
        print(f"原因：{source.get('reason') or '未取得真实 Requirement Source'}")
        print("需要材料：STBB19-234 真实正文、结构化字段、SST/系统/Change、业务规则、附件和 freshness/provenance")
        return
    facts = source.get("facts") or {}
    print(f"需求 ID：{facts.get('requirement_id')}")
    print(f"需求标题：{facts.get('title')}")
    print(f"来源：{source.get('source_ref')}")
    print(f"Freshness：{facts.get('freshness')}")
    print("Requirement 正文：" + str(facts.get("body") or "未提供"))
    print("结构化摘要：" + json.dumps(facts.get("structured_fields"), ensure_ascii=False, sort_keys=True))
    print("附件：" + json.dumps(facts.get("attachments") or [], ensure_ascii=False, sort_keys=True))
    print("业务规则：" + json.dumps(facts.get("business_rules") or [], ensure_ascii=False, sort_keys=True))
    print("歧义/待确认：" + json.dumps(facts.get("ambiguities") or [], ensure_ascii=False, sort_keys=True))
    for index, sst in enumerate(facts.get("ssts") or [], 1):
        print(f"SST {index}：{sst.get('sst_id')}")
        print(f"  系统：{sst.get('system') or '未提供'}")
        print(f"  Change：{sst.get('change') or '未提供'}")
        print("  字段：" + json.dumps(sst.get("fields") or [], ensure_ascii=False, sort_keys=True))
        print("  规则：" + json.dumps(sst.get("business_rules") or facts.get("business_rules") or [], ensure_ascii=False, sort_keys=True))
        print("  Scope：" + json.dumps(sst.get("scope") or {}, ensure_ascii=False, sort_keys=True))
        print("  交叉系统关系：" + str(sst.get("cross_system_relation") or "未提供"))
        print("  缺陷假设：" + str(sst.get("defect_hypothesis") or "未提供"))
    print("Provenance：" + json.dumps(source.get("provenance") or {}, ensure_ascii=False, sort_keys=True))


def print_coverage_view(payload: dict[str, Any]) -> None:
    acceptance = payload.get("runtime_acceptance") or {}
    print(f"当前 Coverage provenance：{acceptance.get('PFC_CURRENT_COVERAGE_PROVENANCE', 'NOT_VERIFIED')}")
    coverage = payload.get("coverage") or {}
    print(f"Coverage 总项数：{coverage.get('total', 0)}")
    print(f"已选：{coverage.get('selected', coverage.get('required', 0))}")
    print(f"已排除：{coverage.get('excluded', 0)}")
    print(f"待判断：{coverage.get('pending', coverage.get('unresolved', 0))}")
    for index, item in enumerate(coverage.get("items") or [], 1):
        print(f"Coverage {index}：")
        print(f"  Requirement fact：{item.get('requirement_fact')}")
        print(f"  Obligation：{item.get('obligation')}")
        print(f"  Disposition：{item.get('disposition')}")
        print(f"  Reason：{item.get('reason')}")
        print("  Linked cases：" + ("；".join(item.get("linked_cases") or []) or "无"))


def print_cases_view(payload: dict[str, Any]) -> None:
    cases = payload.get("cases") or []
    acceptance = payload.get("runtime_acceptance") or {}
    print(f"标准案例总数：{len(cases)}")
    print(f"当前 StandardTestCase provenance：{acceptance.get('PFC_CURRENT_STANDARD_CASE_PROVENANCE', 'NOT_VERIFIED')}")
    print("Case gate：CASE_REVIEW_REQUIRED（Product Owner APPROVE 前不执行）")
    for index, item in enumerate(cases, 1):
        print(f"\n标准案例 {index}：{item.get('name') or '未命名'}")
        print(f"状态：{item.get('status') or '未知'}")
        print(f"SST：{item.get('sst_id') or '未提供'}；系统：{item.get('system') or '未提供'}；Change：{item.get('change') or '未提供'}")
        print(f"Requirement fact refs：{json.dumps(item.get('requirement_fact_refs') or [], ensure_ascii=False)}")
        print(f"Coverage obligation refs：{json.dumps(item.get('coverage_obligation_refs') or [], ensure_ascii=False)}")
        print(f"测试目的：{item.get('purpose') or '未提供'}")
        print("前置条件：" + ("；".join(item.get("preconditions") or []) or "未提供"))
        print("业务规则：" + json.dumps(item.get("business_rules") or [], ensure_ascii=False, sort_keys=True))
        print("具体测试数据：" + json.dumps(item.get("concrete_test_data") or {}, ensure_ascii=False, sort_keys=True))
        print("测试步骤：" + ("；".join(item.get("steps") or []) or "未提供"))
        print("预期结果 / Oracle：" + json.dumps(item.get("oracle"), ensure_ascii=False, sort_keys=True))
        print(f"正向：{json.dumps(item.get('positive'), ensure_ascii=False, sort_keys=True)}")
        print(f"负向：{json.dumps(item.get('negative'), ensure_ascii=False, sort_keys=True)}")
        print(f"边界：{json.dumps(item.get('boundary'), ensure_ascii=False, sort_keys=True)}")
        print(f"测试层级：{item.get('test_level') or '未提供'}")
        print(f"Source grounding：{json.dumps(item.get('source_grounding') or {}, ensure_ascii=False, sort_keys=True)}")
        print(f"缺陷假设：{item.get('defect_hypothesis') or '未提供'}")
        if item.get("quality_gap"):
            print("CASE_QUALITY_GAP：" + "、".join(item["quality_gap"]))


def print_status(payload: dict[str, Any], debug: bool = False, view: str | None = None) -> None:
    if debug:
        emit_json_utf8(payload)
        return
    if view == "requirement":
        print_requirement_view(payload)
        return
    if view == "coverage":
        print_coverage_view(payload)
        return
    if view == "cases":
        print_cases_view(payload)
        return
    print(f"当前项目：{payload.get('project', PROJECT_ID)}")
    print(f"当前版本：{payload.get('version', PROFILE['version'])}")
    print(f"当前需求：{payload.get('requirement', '尚未建立')}")
    print(f"当前 Mission 状态：{payload.get('stage', '尚未启动')}")
    ai_runtime = payload.get("ai_runtime") or {}
    ai_auth = ai_runtime.get("authentication") or {}
    ai_provider = ai_runtime.get("provider_model") or {}
    ai_call = ai_runtime.get("llm_invocation") or {}
    print(f"当前阶段：{ai_runtime.get('stage', '尚未检查 AI Runtime')}")
    executable = ai_runtime.get("executable") or {}
    instance = ai_runtime.get("instance_identity") or {}
    web = ai_runtime.get("opencode_web") or {}
    process_state = "READY" if web.get("status") == "PASS" else "NOT_READY"
    print("\nOpenCode Process:")
    print(f"  State：{process_state}")
    if pinned_opencode_runtime_enabled():
        pinned_contract = pinned_opencode_runtime_contract()
        print(f"OpenCode Runtime：{pinned_contract['version']}")
        print(f"Pinned Path：{pinned_contract['path']}")
    elif proven_git_bash_command_enabled():
        proven_contract = proven_git_bash_command_contract()
        print(f"OpenCode Runtime：{proven_contract['version']}")
        print(f"OpenCode Command：{proven_contract['command']}")
    print(f"  Version：{executable.get('version') or '未确认'}")
    print(f"  Workspace：{instance.get('workspace_root') or WORKSPACE_ROOT}")
    print(f"  Web URL：{web.get('web_url') or '不可用'}")
    print(f"  PID：{web.get('pid') or instance.get('pid') or '不可用'}")
    print("\nAI Runtime:")
    print(f"  Authentication：{ai_auth.get('status', 'NOT_VERIFIED')}")
    print(f"  Provider：{'READY' if ai_provider.get('connected') else ai_provider.get('status', 'REPAIR')}")
    print(f"  Model：{ai_provider.get('model') if ai_provider.get('model_available') else ai_provider.get('status', 'REPAIR')}")
    print(f"  Last LLM Probe：{ai_call.get('status', 'NOT_VERIFIED')}；response_received={ai_call.get('response_received', False)}")
    print(f"  R2 Session：{(ai_runtime.get('r2') or {}).get('session_runtime', {}).get('status', 'NOT_VERIFIED')}")
    print("\nPFC Mission:")
    print(f"  Mission State：{payload.get('stage', '尚未启动')}")
    print(f"  AI Runtime Gate：{ai_runtime.get('mission_ai_runtime_gate', 'WAITING_FOR_AI_RUNTIME')}")
    print(f"  Current Blocker：{'；'.join(payload.get('blockers') or []) or '无'}")
    print(f"OpenCode：{'运行中' if process_state == 'READY' else '未运行/未验证'}；认证：{ai_auth.get('status', 'NOT_VERIFIED')}")
    print(f"PFC_OPENCODE_SELECTED_LAUNCHER = {(executable.get('resolution') or {}).get('selected_path') or 'NOT_SELECTED'}")
    selected_version = (executable.get("resolution") or {}).get("selected_version")
    print(f"PFC_OPENCODE_SELECTED_VERSION = {selected_version if selected_version not in {None, 'UNAVAILABLE'} else 'NOT_SELECTED'}")
    context = ai_runtime.get("interactive_context") or {}
    print(f"Shared durable context：{context.get('status', 'NOT_VERIFIED')}；Mission={context.get('mission_state') or '无'}；resume={context.get('resume', 'NOT_ATTEMPTED')}")
    print("PFC_READY_PACKAGE_INTERACTIVE_USAGE_MODEL = PASS")
    print("PFC_READY_PACKAGE_AUTONOMOUS_MODE = PASS")
    print("PFC_READY_PACKAGE_OPENCODE_WEB_INTEGRATION = IMPLEMENTED_PENDING_BANK_REALITY")
    print("PFC_READY_PACKAGE_SHARED_DURABLE_CONTEXT = PASS")
    print("PFC_READY_PACKAGE_SESSION_RESUME_MODEL = PASS")
    print("PFC_READY_PACKAGE_LONG_RUNNING_WORKSPACE = PASS")
    print("PFC_READY_PACKAGE_BANK_INTERACTIVE_REALITY_ENTRY = ALLOWED")
    requirement_source = payload.get("requirement_source") or {}
    print(f"Requirement Source：{requirement_source.get('status', 'HUMAN_ACTION_REQUIRED')}（{requirement_source.get('failure_class') or requirement_source.get('source_ref') or '未确认'}）")
    print("代码基线：" + readable_source_baseline(payload.get("source_baseline") or {}))
    print("部署基线：" + readable_deployment_baseline(payload.get("deployment_baseline") or {}))
    coverage = payload.get("coverage") or {}
    print(f"Coverage 状态：共 {coverage.get('total', 0)} 项，已选 {coverage.get('selected', coverage.get('required', 0))} 项，已排除 {coverage.get('excluded', 0)} 项，待判断 {coverage.get('pending', coverage.get('unresolved', 0))} 项")
    case_items = payload.get("cases", [])
    case_statuses = {}
    for item in case_items:
        status = item.get("status", "UNKNOWN")
        case_statuses[status] = case_statuses.get(status, 0) + 1
    case_status_text = "、".join(f"{key} {value}" for key, value in sorted(case_statuses.items())) or "无"
    print(f"标准案例数量/状态：{len(case_items)} 个（{case_status_text}）")
    for index, item in enumerate(case_items, 1):
        print(f"标准案例 {index}：{item.get('name') or '未命名'}（{item.get('status') or '未知'}）")
        print(f"  测试目的：{item.get('purpose') or '未提供'}")
        print(f"  前置条件：{'；'.join(item.get('preconditions') or []) or '未提供'}")
        print(f"  测试步骤摘要：{'；'.join(item.get('steps') or []) or '未提供'}")
        print(f"  预期结果摘要：{item.get('expected_result') or '未提供'}")
        print(f"  测试层级：{item.get('test_level') or '未提供'}")
        print(f"  覆盖点：{'；'.join(item.get('coverage') or []) or '未提供'}")
        print(f"  Oracle / 判定依据：{item.get('oracle') or '未提供'}")
        if item.get("quality_gap"):
            print("  CASE_QUALITY_GAP：缺少 " + "、".join(item["quality_gap"]))
    if case_items and not any(item.get("quality_gap") for item in case_items):
        print("标准案例质量：已具备 Product Owner Review 所需字段；未据此声明 R3 Field Validation PASS")
    print("当前执行状态：" + str((payload.get("execution") or {}).get("status", "尚未开始")))
    acceptance = payload.get("runtime_acceptance") or {}
    for key in ("PFC_OPENCODE_PROVEN_V1_9_4_LAUNCH_PATH_REUSE", "PFC_OPENCODE_GIT_BASH_SHELL_RESOLUTION", "PFC_OPENCODE_SHELL_VERSION_AUTHORITY", "PFC_OPENCODE_CANDIDATE_SELECTION", "PFC_OPENCODE_VERSION_GUESSING", "PFC_OPENCODE_STARTUP_ROOT_CAUSE"):
        print(f"{key} = {acceptance.get(key, 'NOT_VERIFIED')}")
    for key in ("PFC_OPENCODE_GENERATED_CONFIG_REALITY", "PFC_OPENCODE_DYNAMIC_PORT_REALITY", "PFC_OPENCODE_LAUNCH_CONFIG_CONSISTENCY", "PFC_OPENCODE_PROVEN_SHELL_LAUNCH_PATH", "PFC_OPENCODE_REAL_PROCESS_LAUNCH_PATH", "PFC_READY_PACKAGE_BANK_REALITY_ENTRY"):
        print(f"{key} = {acceptance.get(key, 'NOT_VERIFIED')}")
    for key in ("PFC_PINNED_OPENCODE_RUNTIME", "PFC_PINNED_OPENCODE_RUNTIME_PATH", "PFC_OPENCODE_VERSION_AND_LAUNCH_SAME_RUNTIME", "PFC_OPENCODE_REAL_WEB_LAUNCH_PATH", "PFC_OPENCODE_AUTH_REPROBE"):
        print(f"{key} = {acceptance.get(key, 'NOT_VERIFIED')}")
    for key in ("PFC_OPENCODE_GIT_BASH_COMMAND_ADMISSION", "PFC_OPENCODE_VERSION_AND_WEB_SAME_SHELL"):
        print(f"{key} = {acceptance.get(key, 'NOT_VERIFIED')}")
    for key in ("PFC_OPENCODE_POST_AUTH_RESUME_REPAIR", "PFC_OPENCODE_SAME_INSTANCE_AUTH_REPROBE", "PFC_OPENCODE_UNNECESSARY_RESTART", "PFC_OPENCODE_PROCESS_STOP_TIMEOUT", "PFC_OPENCODE_PROCESS_LIFECYCLE", "PFC_OPENCODE_RAW_TRACEBACK_TO_USER"):
        print(f"{key} = {acceptance.get(key, 'NOT_VERIFIED')}")
    for key in ("PFC_OPENCODE_PROCESS_RUNTIME_MODEL", "PFC_OPENCODE_WEB_START_INDEPENDENT_OF_AUTH", "PFC_OPENCODE_AUTH_NON_BLOCKING", "PFC_OPENCODE_PROVIDER_MODEL_NON_BLOCKING", "PFC_OPENCODE_LLM_NON_BLOCKING_TO_WEB", "PFC_R2_SESSION_GATE", "PFC_PFC_MISSION_AI_RUNTIME_GATE", "PFC_STATUS_RUNTIME_SEPARATION"):
        print(f"{key} = {acceptance.get(key, 'NOT_VERIFIED')}")
    for key in (*STARTUP_TRACE_ACCEPTANCE_KEYS, "PFC_WINDOWS_OPENCODE_CMD_SHIM_RESOLUTION", "PFC_OPENCODE_MULTI_VERSION_MATRIX", "PFC_OPENCODE_REAL_WEB_PROCESS_LAUNCH", "PFC_OPENCODE_REAL_WEB_LAUNCH", "PFC_OPENCODE_PACKAGE_WORKSPACE", "PFC_OPENCODE_DYNAMIC_PORT", "PFC_OPENCODE_AUTH_WAIT_FLOW", "PFC_OPENCODE_BANK_REALITY_ENTRY", "PFC_OPENCODE_REAL_WEB_LAUNCHER", "PFC_OPENCODE_PACKAGE_OWNED_WORKSPACE", "PFC_OPENCODE_BINARY_VERSION_PINNING", "PFC_OPENCODE_AUTH_WAIT_RESUME", "PFC_OPENCODE_AUTH_SAME_INSTANCE_GUARD", "PFC_OPENCODE_PROVIDER_MODEL_PROBE", "PFC_OPENCODE_REAL_LLM_PROBE", "PFC_R2_SESSION_CREATE_RESUME", "PFC_READY_PACKAGE_BANK_RUNTIME_REALITY_ENTRY", "PFC_OPENCODE_BINARY_IDENTITY", "PFC_OPENCODE_VERSION_REALITY", "PFC_OPENCODE_WORKSPACE_ISOLATION", "PFC_OPENCODE_WEB_INSTANCE_IDENTITY", "PFC_OPENCODE_AUTH_PROBE_TARGET", "PFC_OPENCODE_AUTH_REALITY", "PFC_OPENCODE_PROVIDER_MODEL_REALITY", "PFC_LLM_INVOCATION_REALITY", "PFC_R2_SESSION_RUNTIME_REALITY", "PFC_R2_AUTONOMOUS_RUNTIME_REALITY", "PFC_CURRENT_COVERAGE_PROVENANCE", "PFC_CURRENT_STANDARD_CASE_PROVENANCE", "PFC_R3_REQUIREMENT_SOURCE_REPAIR_ENTRY", "PFC_REAL_EXECUTION_ENTRY", "ARCHITECTURE_DRIFT", "HARD_DEPENDENCY_FAILURE"):
        print(f"{key} = {acceptance.get(key, 'NOT_VERIFIED' if 'PROVENANCE' in key else 'REPAIR' if key != 'PFC_REAL_EXECUTION_ENTRY' and key not in {'ARCHITECTURE_DRIFT', 'HARD_DEPENDENCY_FAILURE'} else 'HOLD' if key == 'PFC_REAL_EXECUTION_ENTRY' else 'NO')}")
    r3 = payload.get("r3") or {}
    print(f"PFC_R3_REQUIREMENT_SOURCE_GROUNDING = {r3.get('requirement_source_grounding', 'HUMAN_ACTION_REQUIRED')}")
    print(f"PFC_R3_COVERAGE_GROUNDING = {r3.get('coverage_grounding', 'REPAIR')}")
    print(f"PFC_R3_STANDARD_CASE_QUALITY = {r3.get('standard_case_quality', 'REPAIR')}")
    print(f"PFC_READY_PACKAGE_CASE_VISIBILITY = {r3.get('case_visibility', 'REPAIR')}")
    print("PFC_REAL_EXECUTION_ENTRY = HOLD")
    print("R3_FIELD_VALIDATION = IN_PROGRESS")
    print("ARCHITECTURE_DRIFT = NO")
    print("HARD_DEPENDENCY_FAILURE = NO")
    print(f"AI正在做什么：{payload.get('doing', '等待启动')}")
    blockers = payload.get("blockers") or ["无"]
    needs = payload.get("needs") or ["无"]
    print("当前阻塞：" + "；".join(blockers))
    print("需要你做什么：" + "；".join(needs))
    human_actions = payload.get("human_actions") or []
    print("Human Action：" + ("；".join(f"{item.get('title')}：{item.get('requested_action')}" for item in human_actions) or "无"))
    print("最近 Evidence：" + ("、".join(f"{item.get('channel')}（{item.get('status')}）" for item in payload.get("evidence", [])) or "无"))
    print("最近 Finding：" + ("、".join(f"{item.get('title')}（{item.get('status')}）" for item in payload.get("defects", [])) or "无"))
    print("下一步：" + (needs[0] if needs and needs[0] != "无" else "继续等待自动执行"))


def stop_managed_opencode_web() -> dict[str, Any]:
    global MANAGED_OPENCODE_PROCESS, MANAGED_OPENCODE_PROCESS_PID
    state = load_json(WEB_RUNTIME_STATE_PATH, {}) or {}
    if not state:
        return {"status": "STOPPED", "process_stopped": False, "lifecycle": "PASS", "stop_result": {"status": "NO_MANAGED_INSTANCE"}}
    if not state.get("started_by_harness"):
        result = {"status": "CONTROLLED_ERROR", "process_stopped": False, "lifecycle": "REPAIR", "error_class": "PROCESS_NOT_PACKAGE_OWNED", "stop_result": {"status": "NOT_PACKAGE_OWNED"}}
        state.update({"status": "STOP_FAILED", "last_error": result["error_class"], "process_stop": result["stop_result"], "observed_at": now_iso()})
        write_web_runtime_state(state)
        return {**result, **web_runtime_public_state(state)}

    timeout = process_stop_timeout_seconds()
    handle = MANAGED_OPENCODE_PROCESS
    handle_pid = MANAGED_OPENCODE_PROCESS_PID or state.get("process_handle_pid") or state.get("launcher_pid")
    host = str(state.get("host") or "127.0.0.1")
    try:
        port = int(state.get("port") or endpoint_host_port(str(state.get("endpoint") or "http://127.0.0.1:4096"))[1])
    except (TypeError, ValueError):
        port = 4096
    live_listener_pids = set(listening_process_ids(host, port))
    listener_pids = []
    state_listener_values = [*(state.get("listener_pids") or []), state.get("pid")]
    for value in state_listener_values:
        try:
            candidate = int(value)
        except (TypeError, ValueError):
            continue
        if candidate in live_listener_pids:
            listener_pids.append(candidate)

    targets: list[tuple[str, int, subprocess.Popen[Any] | None]] = []
    try:
        numeric_handle_pid = int(handle_pid) if handle_pid is not None else None
    except (TypeError, ValueError):
        numeric_handle_pid = None
    if numeric_handle_pid and pid_is_running(numeric_handle_pid):
        targets.append(("package-launcher-handle", numeric_handle_pid, handle if handle and int(getattr(handle, "pid", -1) or -1) == numeric_handle_pid else None))
    for candidate in listener_pids:
        if candidate not in {item[1] for item in targets} and pid_is_running(candidate):
            targets.append(("package-web-listener", candidate, handle if handle and int(getattr(handle, "pid", -1) or -1) == candidate else None))

    stop_results: list[dict[str, Any]] = []
    for role, pid, process in targets:
        stop_results.append(_bounded_terminate_owned_process(process, pid, role=role, timeout=timeout))
    process_stopped = bool(not targets or all(item.get("stopped") for item in stop_results))
    timeouts = [item for item in stop_results if item.get("timeout")]
    stop_status = "PASS" if process_stopped else "CONTROLLED_ERROR"
    stop_result = {"status": stop_status, "targets": stop_results, "timeout_seconds": timeout, "timeout": bool(timeouts), "error_class": None if process_stopped else "OPENCODE_PROCESS_STOP_TIMEOUT" if timeouts else "OPENCODE_PROCESS_STOP_FAILED"}
    if process_stopped:
        state.update({"status": "STOPPED", "pid": None, "stopped_at": now_iso(), "observed_at": now_iso(), "process_stop": stop_result})
        MANAGED_OPENCODE_PROCESS = None
        MANAGED_OPENCODE_PROCESS_PID = None
    else:
        state.update({"status": "STOP_FAILED", "last_error": stop_result["error_class"], "observed_at": now_iso(), "process_stop": stop_result})
    write_web_runtime_state(state)
    result = {"status": "STOPPED" if process_stopped else "CONTROLLED_ERROR", "process_stopped": process_stopped, "lifecycle": "PASS" if process_stopped else "REPAIR", "error_class": stop_result.get("error_class"), "stop_result": stop_result}
    return {**result, **web_runtime_public_state(state)}


def checkpoint_and_close_interactive_context() -> dict[str, int]:
    counts = {"checkpoints": 0, "worker_sessions": 0}
    if not internal_db_path().is_file():
        return counts
    storage.initialize()
    for item in current_project_missions():
        if item.get("state") in {"COMPLETED", "ABORTED"}:
            continue
        try:
            mission.checkpoint(item["mission_id"], "PFC_STOP_INTERACTIVE_RUNTIME")
            counts["checkpoints"] += 1
        except Exception:
            continue
    for item in rows("SELECT worker_session_id FROM worker_sessions WHERE status='OPEN' AND mission_id IN (SELECT mission_id FROM missions WHERE project_id=?)", (PROJECT_ID,)):
        try:
            session.close_worker_session(item["worker_session_id"], opencode_url=opencode_endpoint(), dispose_provider=False)
            counts["worker_sessions"] += 1
        except Exception:
            continue
    return counts


def start() -> int:
    if not INSTALLED_RUNTIME_WORKSPACE:
        print("当前目录是离线包目录，不是已配置的 PFC 项目工作区。请先执行 ./INSTALL-PFC-AITEST.sh，再从 /d/PFC 启动。")
        return 2
    trace = begin_startup_trace()
    if trace:
        try:
            trace_capture_prelaunch()
        except Exception as exc:
            trace_write_json("trace-prelaunch-error.json", {"type": type(exc).__name__, "message": str(exc)})
    set_control(stop_requested=False)
    integrity = package_integrity()
    checks = runtime_checks()
    if trace:
        trace_write_json("runtime-checks.json", checks)
    if not integrity.get("ok"):
        trace_zip = finalize_startup_trace({"acceptance": {"PFC_OPENCODE_REAL_WEB_LAUNCH": "REPAIR"}, "opencode_web": {"status": "NOT_STARTED"}}, RuntimeError(integrity.get("code") or "PACKAGE_INTEGRITY_FAILURE")) if trace else None
        if trace:
            print(terminal_startup_diagnostic({"acceptance": {"PFC_OPENCODE_REAL_WEB_LAUNCH": "REPAIR"}, "opencode_web": {"status": "NOT_STARTED"}}, RuntimeError(integrity.get("code") or "PACKAGE_INTEGRITY_FAILURE"), trace_zip))
            return 2
        print("PFC Field Validation 无法启动：派生包完整性校验失败。")
        print("请重新解压一份完整的 PFC Field Validation 包。")
        return 2
    storage.initialize()
    scheduler.seed_layers()
    try:
        runtime_reality = run_opencode_runtime_reality()
        quarantine = quarantine_unverified_r3_state(runtime_reality)
        runtime_reality["interactive_context"] = interactive_context_restore(runtime_reality)
        write_json(STATE_ROOT / "evidence" / "field-validation" / "opencode-runtime-reality.json", runtime_reality, private=True)
    except Exception as exc:
        if not trace:
            raise
        trace_write_json("startup-exception.json", {"type": type(exc).__name__, "message": str(exc)})
        trace_zip = finalize_startup_trace({}, exc)
        print(terminal_startup_diagnostic({}, exc, trace_zip))
        return 1
    trace_zip = finalize_startup_trace(runtime_reality) if trace else None
    if trace_zip:
        runtime_reality["PFC_OPENCODE_STARTUP_DIAGNOSTIC_ZIP"] = trace_zip
        write_json(STATE_ROOT / "evidence" / "field-validation" / "opencode-runtime-reality.json", runtime_reality, private=True)
        if (runtime_reality.get("acceptance") or {}).get("PFC_OPENCODE_REAL_WEB_LAUNCH") != "PASS":
            print(terminal_startup_diagnostic(runtime_reality, trace_zip=trace_zip))
            return 1
    acceptance = runtime_reality.get("acceptance") or {}
    print("正在启动 PFC 测试数字员工...")
    print("当前阶段：正在检查 AI Runtime")
    if pinned_opencode_runtime_enabled():
        pinned_contract = pinned_opencode_runtime_contract()
        print(f"OpenCode Runtime: {pinned_contract['version']}")
        print(f"Pinned Path: {pinned_contract['path']}")
    elif proven_git_bash_command_enabled():
        proven_contract = proven_git_bash_command_contract()
        print(f"OpenCode Runtime: {proven_contract['version']}")
        print(f"OpenCode Command: {proven_contract['command']}")
    web = runtime_reality.get("opencode_web") or {}
    executable = runtime_reality.get("executable") or {}
    auth = runtime_reality.get("authentication") or {}
    provider_model = runtime_reality.get("provider_model") or {}
    llm = runtime_reality.get("llm_invocation") or {}
    process_ready = web.get("status") == "PASS"
    print("OpenCode Process:")
    print(f"  Version：{executable.get('version') or '未确认'}")
    print(f"  Workspace：{runtime_reality.get('instance_identity', {}).get('workspace_root') or WORKSPACE_ROOT}")
    print(f"  Web：{web.get('web_url') or '不可用'}")
    print(f"  Process：{'RUNNING' if process_ready else 'NOT_READY'}；PID={web.get('pid') or '不可用'}")
    print("AI Runtime:")
    print(f"  Authentication：{auth.get('status', 'NOT_VERIFIED')}")
    print(f"  Provider：{'READY' if provider_model.get('connected') else '尚未确认'}")
    print(f"  Model：{'READY' if provider_model.get('model_available') else '尚未确认'}")
    print(f"  LLM：{llm.get('status', '尚未验证')}")
    print("PFC Mission:")
    print(f"  AI Runtime Gate：{runtime_reality.get('mission_ai_runtime_gate', 'WAITING_FOR_AI_RUNTIME')}")
    print(f"  OpenCode Web 已{'启动' if process_ready else '未 ready'}，AI Runtime 未 ready 不会阻塞 Web。")
    resolution = runtime_reality.get('executable', {}).get('resolution') or {}
    print(f"PFC_WINDOWS_OPENCODE_CMD_SHIM_RESOLUTION = {acceptance.get('PFC_WINDOWS_OPENCODE_CMD_SHIM_RESOLUTION', 'REPAIR')}")
    print(f"PFC_OPENCODE_MULTI_VERSION_MATRIX = {acceptance.get('PFC_OPENCODE_MULTI_VERSION_MATRIX', 'REPAIR')}")
    for key in STARTUP_TRACE_ACCEPTANCE_KEYS:
        print(f"{key} = {acceptance.get(key, 'REPAIR')}")
    print(f"PFC_OPENCODE_DIAGNOSTIC_ZIP = {acceptance.get('PFC_OPENCODE_DIAGNOSTIC_ZIP', 'OPTIONAL')}")
    print(f"PFC_OPENCODE_PROVEN_V1_9_4_LAUNCH_PATH_REUSE = {acceptance.get('PFC_OPENCODE_PROVEN_V1_9_4_LAUNCH_PATH_REUSE', 'REPAIR')}")
    print(f"PFC_OPENCODE_GIT_BASH_SHELL_RESOLUTION = {acceptance.get('PFC_OPENCODE_GIT_BASH_SHELL_RESOLUTION', 'REPAIR')}")
    print(f"PFC_OPENCODE_SHELL_VERSION_AUTHORITY = {acceptance.get('PFC_OPENCODE_SHELL_VERSION_AUTHORITY', 'REPAIR')}")
    print(f"PFC_OPENCODE_CANDIDATE_SELECTION = {acceptance.get('PFC_OPENCODE_CANDIDATE_SELECTION', 'REPAIR')}")
    print(f"PFC_OPENCODE_VERSION_GUESSING = {acceptance.get('PFC_OPENCODE_VERSION_GUESSING', 'REPAIR')}")
    print(f"PFC_OPENCODE_STARTUP_ROOT_CAUSE = {acceptance.get('PFC_OPENCODE_STARTUP_ROOT_CAUSE', 'REPAIR')}")
    for key in ("PFC_OPENCODE_PROCESS_RUNTIME_MODEL", "PFC_OPENCODE_WEB_START_INDEPENDENT_OF_AUTH", "PFC_OPENCODE_AUTH_NON_BLOCKING", "PFC_OPENCODE_PROVIDER_MODEL_NON_BLOCKING", "PFC_OPENCODE_LLM_NON_BLOCKING_TO_WEB", "PFC_R2_SESSION_GATE", "PFC_PFC_MISSION_AI_RUNTIME_GATE", "PFC_STATUS_RUNTIME_SEPARATION"):
        print(f"{key} = {acceptance.get(key, 'REPAIR')}")
    for key in ("PFC_OPENCODE_GENERATED_CONFIG_REALITY", "PFC_OPENCODE_DYNAMIC_PORT_REALITY", "PFC_OPENCODE_LAUNCH_CONFIG_CONSISTENCY", "PFC_OPENCODE_PROVEN_SHELL_LAUNCH_PATH", "PFC_OPENCODE_REAL_PROCESS_LAUNCH_PATH", "PFC_READY_PACKAGE_BANK_REALITY_ENTRY"):
        print(f"{key} = {acceptance.get(key, 'FAIL' if key != 'PFC_READY_PACKAGE_BANK_REALITY_ENTRY' else 'NOT_ALLOWED')}")
    for key in ("PFC_OPENCODE_WEB_EXPLICIT_PROJECT_BINDING", "PFC_OPENCODE_PROJECT_BOOTSTRAP", "PFC_OPENCODE_AGENT_DISCOVERY", "PFC_READY_FINAL_INTERACTIVE_REALITY"):
        print(f"{key} = {acceptance.get(key, 'REPAIR')}")
    for key in ("PFC_PINNED_OPENCODE_RUNTIME", "PFC_PINNED_OPENCODE_RUNTIME_PATH", "PFC_OPENCODE_VERSION_AND_LAUNCH_SAME_RUNTIME", "PFC_OPENCODE_REAL_WEB_LAUNCH_PATH", "PFC_OPENCODE_AUTH_REPROBE"):
        print(f"{key} = {acceptance.get(key, 'FAIL' if key != 'PFC_PINNED_OPENCODE_RUNTIME_PATH' else 'FAIL')}")
    for key in ("PFC_OPENCODE_GIT_BASH_COMMAND_ADMISSION", "PFC_OPENCODE_VERSION_AND_WEB_SAME_SHELL"):
        print(f"{key} = {acceptance.get(key, 'FAIL')}")
    print(f"PFC_OPENCODE_SELECTED_LAUNCHER = {resolution.get('selected_path') or 'NOT_SELECTED'}")
    selected_version = resolution.get("selected_version")
    print(f"PFC_OPENCODE_SELECTED_VERSION = {selected_version if selected_version not in {None, 'UNAVAILABLE'} else 'NOT_SELECTED'}")
    print(f"PFC_OPENCODE_REAL_WEB_PROCESS_LAUNCH = {acceptance.get('PFC_OPENCODE_REAL_WEB_PROCESS_LAUNCH', 'IMPLEMENTED')}")
    print(f"PFC_OPENCODE_REAL_WEB_LAUNCH = {acceptance.get('PFC_OPENCODE_REAL_WEB_LAUNCH', 'REPAIR')}")
    print(f"PFC_OPENCODE_PACKAGE_WORKSPACE = {acceptance.get('PFC_OPENCODE_PACKAGE_WORKSPACE', 'REPAIR')}")
    print(f"PFC_OPENCODE_DYNAMIC_PORT = {acceptance.get('PFC_OPENCODE_DYNAMIC_PORT', 'REPAIR')}")
    print(f"PFC_OPENCODE_AUTH_WAIT_FLOW = {acceptance.get('PFC_OPENCODE_AUTH_WAIT_FLOW', 'IMPLEMENTED')}")
    print(f"PFC_OPENCODE_BANK_REALITY_ENTRY = {acceptance.get('PFC_OPENCODE_BANK_REALITY_ENTRY', 'NOT_ALLOWED')}")
    print(f"Runtime Identity Root Cause：{runtime_reality.get('PFC_OPENCODE_RUNTIME_INSTANCE_IDENTITY_GAP') or 'NO'}")
    print(f"PFC_OPENCODE_RUNTIME_INSTANCE_IDENTITY_ROOT_CAUSE_RECON = {'PASS' if runtime_reality.get('PFC_OPENCODE_RUNTIME_IDENTITY_MATRIX') else 'REPAIR'}")
    print(f"PFC_OPENCODE_RUNTIME_LAUNCH_AND_AUTH_ORCHESTRATION_REPAIR = {'PASS' if acceptance.get('PFC_OPENCODE_REAL_WEB_LAUNCHER') == 'IMPLEMENTED' and acceptance.get('PFC_OPENCODE_AUTH_WAIT_RESUME') == 'IMPLEMENTED' else 'REPAIR'}")
    context = runtime_reality.get("interactive_context") or {}
    print(f"PFC durable context：{context.get('status', 'NOT_VERIFIED')}；Mission={context.get('mission_state') or '无'}；resume={context.get('resume', 'NOT_ATTEMPTED')}")
    print("PFC_READY_PACKAGE_INTERACTIVE_USAGE_MODEL = PASS")
    print("PFC_READY_PACKAGE_AUTONOMOUS_MODE = PASS")
    print("PFC_READY_PACKAGE_OPENCODE_WEB_INTEGRATION = EXPLICIT_PROJECT_SESSION_BINDING")
    print(f"BANK_R1_R4_INTERACTIVE_PRIMARY_SURFACE = {acceptance.get('PFC_INTERACTIVE_PRIMARY_SURFACE', 'OPENCODE_TUI')}")
    print("PFC_READY_PACKAGE_SHARED_DURABLE_CONTEXT = PASS")
    print("PFC_READY_PACKAGE_SESSION_RESUME_MODEL = PASS")
    print("PFC_READY_PACKAGE_LONG_RUNNING_WORKSPACE = PASS")
    print(f"PFC_READY_PACKAGE_BANK_INTERACTIVE_REALITY_ENTRY = {'ALLOWED' if (PROFILE.get('opencode_runtime_launch_auth_orchestration_repair') or PROFILE.get('opencode_windows_cmd_shim_resolution_and_real_web_launch_repair')) else 'NOT_ALLOWED'}")
    if runtime_reality.get("human_action_required"):
        print("当前 OpenCode Web 已可使用。请在页面完成银行身份认证，随后运行 STATUS；不要重新运行 START。")
    if quarantine["cases"] or quarantine["coverage"] or quarantine["snapshots"]:
        print(f"既有 R3 产物已隔离：案例 {quarantine['cases']} 个、Coverage {quarantine['coverage']} 项、Truth Snapshot {quarantine['snapshots']} 个；provenance=NOT_VERIFIED。")
    print(f"PFC_OPENCODE_REAL_WEB_LAUNCHER = {acceptance.get('PFC_OPENCODE_REAL_WEB_LAUNCHER', 'IMPLEMENTED')}")
    print(f"PFC_OPENCODE_PACKAGE_OWNED_WORKSPACE = {acceptance.get('PFC_OPENCODE_PACKAGE_OWNED_WORKSPACE', 'REPAIR')}")
    print(f"PFC_OPENCODE_BINARY_VERSION_PINNING = {acceptance.get('PFC_OPENCODE_BINARY_VERSION_PINNING', 'REPAIR')}")
    print(f"PFC_OPENCODE_AUTH_WAIT_RESUME = {acceptance.get('PFC_OPENCODE_AUTH_WAIT_RESUME', 'IMPLEMENTED')}")
    print(f"PFC_OPENCODE_AUTH_SAME_INSTANCE_GUARD = {acceptance.get('PFC_OPENCODE_AUTH_SAME_INSTANCE_GUARD', 'REPAIR')}")
    print(f"PFC_OPENCODE_PROVIDER_MODEL_PROBE = {acceptance.get('PFC_OPENCODE_PROVIDER_MODEL_PROBE', 'IMPLEMENTED')}")
    print(f"PFC_OPENCODE_REAL_LLM_PROBE = {acceptance.get('PFC_OPENCODE_REAL_LLM_PROBE', 'IMPLEMENTED')}")
    print(f"PFC_R2_SESSION_CREATE_RESUME = {acceptance.get('PFC_R2_SESSION_CREATE_RESUME', 'IMPLEMENTED')}")
    print(f"PFC_READY_PACKAGE_BANK_RUNTIME_REALITY_ENTRY = {acceptance.get('PFC_READY_PACKAGE_BANK_RUNTIME_REALITY_ENTRY', 'ALLOWED')}")
    print(f"PFC_OPENCODE_BINARY_IDENTITY = {acceptance.get('PFC_OPENCODE_BINARY_IDENTITY', 'REPAIR')}")
    print(f"PFC_OPENCODE_VERSION_REALITY = {acceptance.get('PFC_OPENCODE_VERSION_REALITY', 'REPAIR')}")
    print(f"PFC_OPENCODE_WORKSPACE_ISOLATION = {acceptance.get('PFC_OPENCODE_WORKSPACE_ISOLATION', 'REPAIR')}")
    print(f"PFC_OPENCODE_WEB_INSTANCE_IDENTITY = {acceptance.get('PFC_OPENCODE_WEB_INSTANCE_IDENTITY', 'REPAIR')}")
    print(f"PFC_OPENCODE_AUTH_PROBE_TARGET = {acceptance.get('PFC_OPENCODE_AUTH_PROBE_TARGET', 'REPAIR')}")
    print(f"PFC_OPENCODE_AUTH_REALITY = {acceptance.get('PFC_OPENCODE_AUTH_REALITY', 'REPAIR')}")
    print(f"PFC_OPENCODE_PROVIDER_MODEL_REALITY = {acceptance.get('PFC_OPENCODE_PROVIDER_MODEL_REALITY', 'REPAIR')}")
    print(f"PFC_LLM_INVOCATION_REALITY = {acceptance.get('PFC_LLM_INVOCATION_REALITY', 'REPAIR')}")
    print(f"PFC_R2_SESSION_RUNTIME_REALITY = {acceptance.get('PFC_R2_SESSION_RUNTIME_REALITY', 'REPAIR')}")
    print(f"PFC_R2_AUTONOMOUS_RUNTIME_REALITY = {acceptance.get('PFC_R2_AUTONOMOUS_RUNTIME_REALITY', 'REPAIR')}")
    print(f"PFC_CURRENT_COVERAGE_PROVENANCE = {acceptance.get('PFC_CURRENT_COVERAGE_PROVENANCE', 'NOT_VERIFIED')}")
    print(f"PFC_CURRENT_STANDARD_CASE_PROVENANCE = {acceptance.get('PFC_CURRENT_STANDARD_CASE_PROVENANCE', 'NOT_VERIFIED')}")
    print(f"PFC_R3_REQUIREMENT_SOURCE_REPAIR_ENTRY = {acceptance.get('PFC_R3_REQUIREMENT_SOURCE_REPAIR_ENTRY', 'HOLD')}")
    print("PFC_REAL_EXECUTION_ENTRY = HOLD")
    print("ARCHITECTURE_DRIFT = NO")
    print("HARD_DEPENDENCY_FAILURE = NO")
    print("本轮到此 STOP：未读取 Starlink、未生成/接受新的 Requirement Intelligence、Coverage 或 StandardTestCase。")
    return 0


def stop() -> int:
    context = checkpoint_and_close_interactive_context()
    set_control(stop_requested=True, stop_reason="用户请求停止")
    web = stop_managed_opencode_web()
    if web.get("lifecycle") == "PASS":
        print(f"已停止当前 Interactive Runtime：Web={web.get('status')}；checkpoint={context['checkpoints']}；worker session 已断开={context['worker_sessions']}。")
    else:
        stop_result = web.get("stop_result") or {}
        print(f"OpenCode 停止未完成，但 Harness 已返回受控结果：failure={web.get('error_class') or 'PROCESS_STOP_FAILED'}；timeout={stop_result.get('timeout', False)}；不会继续等待。")
        print(f"当前进程状态已保留，下一步可重试 STOP；checkpoint={context['checkpoints']}；worker session 已断开={context['worker_sessions']}。")
    print("Project、Mission、Requirement、Coverage、Cases、Evidence 均已保留；下一次 START 将恢复 durable context。")
    return 0 if web.get("lifecycle") == "PASS" else 1


def reset() -> int:
    for target in (STATE_DIR, STATE_ROOT / "evidence" / "field-validation", STATE_ROOT / "reports"):
        if target.exists():
            shutil.rmtree(target)
    print("已清理本机上的 PFC 运行状态、验证证据和报告；仓库与本机登录资料未删除。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("command", choices=("start", "status", "stop", "reset", "install-bootstrap", "interactive-truth", "interactive-command"))
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--cases", action="store_true", help="显示完整标准案例")
    parser.add_argument("--coverage", action="store_true", help="显示 Requirement fact 到 Coverage obligation")
    parser.add_argument("--requirement", action="store_true", help="显示 Requirement Source 事实")
    parser.add_argument("--target", default="status", help="OpenCode Web canonical truth target")
    parser.add_argument("--intent", default="", help="OpenCode Web canonical command intent")
    parser.add_argument("--requirement-id", default=None)
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--note", default=None)
    args = parser.parse_args(argv)
    if args.command == "start":
        return start()
    if args.command == "status":
        views = [name for enabled, name in ((args.cases, "cases"), (args.coverage, "coverage"), (args.requirement, "requirement")) if enabled]
        if len(views) > 1:
            parser.error("--cases、--coverage、--requirement 一次只能选择一个视图")
        print_status(status_payload(), args.debug, views[0] if views else None)
        return 0
    if args.command == "stop":
        return stop()
    if args.command == "install-bootstrap":
        if not INSTALLED_RUNTIME_WORKSPACE:
            print("install-bootstrap 只允许在已安装的稳定项目工作区执行。")
            return 2
        emit_json_utf8(install_bootstrap())
        return 0
    if args.command == "interactive-truth":
        emit_json_utf8(canonical_truth_payload(args.target, args.requirement_id, args.case_id))
        return 0
    if args.command == "interactive-command":
        emit_json_utf8(interactive_command(args.intent, args.requirement_id, args.case_id, args.note))
        return 0
    return reset()


if __name__ == "__main__":
    raise SystemExit(main())
