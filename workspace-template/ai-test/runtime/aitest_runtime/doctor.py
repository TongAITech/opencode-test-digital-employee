from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

from .browser import _find_browser
from .common import AI_ROOT, DB_PATH, VERSION, WORKSPACE_ROOT, runtime_python_command
from .project import list_projects, project_status
from .storage import initialize


def _check(name: str, ok: bool, detail: Any = None, severity: str = "REQUIRED") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "status": "PASS" if ok else "FAIL", "severity": severity, "detail": detail}


def _version_baseline() -> dict[str, Any]:
    """Resolve the expected package version from runtime metadata, never a stale literal."""
    sources: dict[str, str] = {}
    version_files = [
        Path(os.environ["AITEST_RUNTIME_VERSION_FILE"]) if os.environ.get("AITEST_RUNTIME_VERSION_FILE") else None,
        WORKSPACE_ROOT / "VERSION",
        WORKSPACE_ROOT.parent / "VERSION",
    ]
    for path in version_files:
        if path is None or not path.exists() or not path.is_file():
            continue
        value = path.read_text(encoding="utf-8").strip()
        if value:
            sources[str(path)] = value

    manifest_candidates = [
        Path(os.environ["AITEST_PACKAGE_MANIFEST"]) if os.environ.get("AITEST_PACKAGE_MANIFEST") else None,
        WORKSPACE_ROOT / "PACKAGE_MANIFEST.json",
        WORKSPACE_ROOT.parent / "PACKAGE_MANIFEST.json",
    ]
    for path in manifest_candidates:
        if path is None or not path.exists() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        value = payload.get("version") if isinstance(payload, dict) else None
        if isinstance(value, str) and value.strip():
            sources[str(path)] = value.strip()

    observed = sorted(set(sources.values()))
    expected = observed[0] if len(observed) == 1 else None
    return {
        "expected": expected,
        "actual": VERSION,
        "sources": sources,
        "observed_versions": observed,
        "consistent": len(observed) == 1 and expected == VERSION,
    }


def _field_validation_profile(path_text: str | None) -> dict[str, Any] | None:
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "INVALID", "path": str(path), "error": type(exc).__name__}
    if not isinstance(payload, dict):
        return {"status": "INVALID", "path": str(path), "error": "PROFILE_NOT_OBJECT"}
    bindings = payload.get("bindings")
    if not isinstance(bindings, dict):
        return {"status": "INVALID", "path": str(path), "error": "BINDINGS_NOT_OBJECT"}
    expected_profile_version = payload.get("package_version")
    version_ok = expected_profile_version in (None, VERSION)
    resolved: dict[str, Any] = {}
    for name, spec in bindings.items():
        if not isinstance(spec, dict):
            resolved[str(name)] = {"status": "MISCONFIGURED", "configuration_status": "INVALID"}
            continue
        env_name = spec.get("env")
        env_configured = bool(env_name and os.environ.get(str(env_name)))
        relative_path = spec.get("relative_path")
        relative_configured = bool(relative_path and (WORKSPACE_ROOT / str(relative_path)).exists())
        default_configured = bool(spec.get("default"))
        configured = env_configured or relative_configured or default_configured
        if relative_configured:
            availability_status = "AVAILABLE"
            availability_reason = "WORKSPACE_RELATIVE_PATH_EXISTS"
        elif configured:
            # External systems are intentionally not contacted by Doctor. A configured
            # binding therefore remains a human-action gate until the field run probes it.
            availability_status = "HUMAN_ACTION_REQUIRED"
            availability_reason = "CONFIGURED_BUT_NOT_PROBED"
        else:
            availability_status = "HUMAN_ACTION_REQUIRED"
            availability_reason = "BINDING_NOT_CONFIGURED"
        resolved[str(name)] = {
            "status": availability_status,
            "configuration_status": "CONFIGURED" if configured else "NOT_CONFIGURED",
            "availability_reason": availability_reason,
            "binding_class": spec.get("binding_class", "FIELD_VALIDATION_ENVIRONMENT_BINDING"),
            "source": "ENVIRONMENT" if env_configured else ("WORKSPACE_RELATIVE_PATH" if relative_configured else ("PROFILE_DEFAULT" if default_configured else "NONE")),
            "env": str(env_name) if env_name else None,
            "relative_path": str(relative_path) if relative_path else None,
        }
    return {
        "status": "PARSED" if version_ok and all(v.get("configuration_status") != "INVALID" for v in resolved.values()) else "INVALID",
        "path": str(path),
        "package_version": expected_profile_version,
        "package_version_matches_runtime": version_ok,
        "bindings": resolved,
    }


def _probe_command(command: str | None, args: list[str]) -> dict[str, Any]:
    if not command:
        return {"status": "UNAVAILABLE", "command": None, "args": args, "output": None}
    try:
        completed = subprocess.run(
            [command, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "UNAVAILABLE", "command": command, "args": args, "output": None, "error": type(exc).__name__}
    output = (completed.stdout or completed.stderr or "").strip()
    return {"status": "AVAILABLE" if completed.returncode == 0 else "UNAVAILABLE", "command": command, "args": args, "returncode": completed.returncode, "output": output[:240]}


def _opencode_runtime_probe() -> dict[str, Any]:
    command = os.environ.get("AITEST_OPENCODE_BIN") or shutil.which("opencode")
    version = _probe_command(command, ["--version"])
    help_probe = _probe_command(command, ["--help"])
    config_path = Path(os.environ.get("AITEST_OPENCODE_CONFIG") or (WORKSPACE_ROOT / "opencode.json"))
    config: dict[str, Any] | None = None
    config_error: str | None = None
    if config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            config = payload if isinstance(payload, dict) else None
            if config is None:
                config_error = "CONFIG_NOT_OBJECT"
        except (OSError, json.JSONDecodeError) as exc:
            config_error = type(exc).__name__
    else:
        config_error = "CONFIG_NOT_FOUND"
    help_text = str(help_probe.get("output") or "").lower()
    capabilities = {name: token in help_text for name, token in {"serve": "serve", "run": "run"}.items()}
    model_configured = bool(os.environ.get("AITEST_OPENCODE_MODEL") or (config or {}).get("model") or (config or {}).get("default_model"))
    provider_configured = bool(os.environ.get("AITEST_OPENCODE_PROVIDER") or (config or {}).get("provider") or (config or {}).get("default_provider"))
    if not command:
        status = "UNAVAILABLE"
    elif config_error:
        status = "MISCONFIGURED"
    elif version["status"] != "AVAILABLE" or help_probe["status"] != "AVAILABLE" or not all(capabilities.values()):
        status = "MISCONFIGURED"
    elif not model_configured or not provider_configured:
        status = "HUMAN_ACTION_REQUIRED"
    else:
        status = "AVAILABLE"
    return {
        "status": status,
        "command_configured": bool(command),
        "version": {"status": version["status"], "output": version.get("output")},
        "required_command_runtime_capabilities": capabilities,
        "configuration": {"path": str(config_path), "status": "AVAILABLE" if config is not None else "MISCONFIGURED", "error": config_error},
        "model_provider": {"status": "AVAILABLE" if model_configured and provider_configured else "HUMAN_ACTION_REQUIRED", "model_configured": model_configured, "provider_configured": provider_configured},
    }


def _git_runtime_probe() -> dict[str, Any]:
    command = shutil.which("git")
    version = _probe_command(command, ["--version"])
    repository_root = Path(os.environ.get("AITEST_TARGET_REPOSITORY") or WORKSPACE_ROOT).expanduser()
    if not command:
        return {"status": "UNAVAILABLE", "version": version, "repository": {"path": str(repository_root), "status": "UNAVAILABLE"}}
    if not repository_root.exists():
        return {"status": "MISCONFIGURED", "version": version, "repository": {"path": str(repository_root), "status": "MISCONFIGURED", "error": "REPOSITORY_NOT_FOUND"}}
    inside = _probe_command(command, ["-C", str(repository_root), "rev-parse", "--is-inside-work-tree"])
    branch = _probe_command(command, ["-C", str(repository_root), "branch", "--show-current"])
    readable = _probe_command(command, ["-C", str(repository_root), "show", "-s", "--format=%H", "HEAD"])
    if inside["status"] != "AVAILABLE":
        status = "HUMAN_ACTION_REQUIRED"
    elif branch["status"] != "AVAILABLE" or readable["status"] != "AVAILABLE":
        status = "MISCONFIGURED"
    else:
        status = "AVAILABLE"
    return {
        "status": status,
        "version": {"status": version["status"], "output": version.get("output")},
        "repository": {"path": str(repository_root), "status": status, "inside_work_tree": inside["status"] == "AVAILABLE", "branch_readable": branch["status"] == "AVAILABLE", "head_readable": readable["status"] == "AVAILABLE"},
    }


def _browser_runtime_probe() -> dict[str, Any]:
    executable = os.environ.get("AITEST_BROWSER_EXECUTABLE") or _find_browser()
    version = _probe_command(executable, ["--version"])
    endpoint = os.environ.get("AITEST_BROWSER_CDP_ENDPOINT")
    endpoint_shape_ok = False
    if endpoint:
        parsed = urlparse(endpoint.replace("{debug_port}", "9222"))
        endpoint_shape_ok = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    profile_dir = os.environ.get("AITEST_BROWSER_PROFILE_DIR")
    profile_status = "AVAILABLE" if profile_dir and Path(profile_dir).is_dir() else "HUMAN_ACTION_REQUIRED"
    four_a_status = "AVAILABLE" if os.environ.get("AITEST_4A_GATE_REF") else "HUMAN_ACTION_REQUIRED"
    cdp_status = "AVAILABLE" if endpoint_shape_ok and os.environ.get("AITEST_BROWSER_CDP_PROBE") == "1" else ("HUMAN_ACTION_REQUIRED" if endpoint_shape_ok else "UNAVAILABLE")
    if not executable:
        status = "UNAVAILABLE"
    elif version["status"] != "AVAILABLE":
        status = "MISCONFIGURED"
    elif cdp_status != "AVAILABLE" or profile_status != "AVAILABLE" or four_a_status != "AVAILABLE":
        status = "HUMAN_ACTION_REQUIRED"
    else:
        status = "AVAILABLE"
    return {
        "status": status,
        "executable": {"status": "AVAILABLE" if executable else "UNAVAILABLE", "configured": bool(executable)},
        "version": {"status": version["status"], "output": version.get("output")},
        "cdp": {"status": cdp_status, "endpoint_configured": endpoint_shape_ok, "probe_requested": os.environ.get("AITEST_BROWSER_CDP_PROBE") == "1"},
        "profile_data_dir": {"status": profile_status, "configured": bool(profile_dir)},
        "four_a_auth_reuse": {"status": four_a_status, "configured": bool(os.environ.get("AITEST_4A_GATE_REF"))},
    }


def run(project_id: str | None = None, field_validation_profile: str | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    initialize()
    version_baseline = _version_baseline()
    checks.append(_check("PACKAGE_VERSION", bool(version_baseline["consistent"]), version_baseline))
    checks.append(_check("PYTHON", bool(runtime_python_command()), runtime_python_command()))
    checks.append(_check("SQLITE", sqlite3.sqlite_version_info >= (3, 24, 0), sqlite3.sqlite_version))
    checks.append(_check("DATABASE", DB_PATH.exists(), str(DB_PATH)))
    checks.append(_check("CAPABILITY_CONFIG", (AI_ROOT / "config" / "capabilities.json").exists()))
    checks.append(_check("TEST_LAYER_CONFIG", (AI_ROOT / "config" / "test-layers.json").exists()))
    checks.append(_check("OPENCODE_CONFIG", (WORKSPACE_ROOT / "opencode.json").exists()))
    checks.append(_check("OPENCODE_CLI", shutil.which("opencode") is not None, shutil.which("opencode"), "OPTIONAL"))
    checks.append(_check("GIT", shutil.which("git") is not None, shutil.which("git"), "REQUIRED"))
    opencode_runtime = _opencode_runtime_probe()
    git_runtime = _git_runtime_probe()
    browser_runtime = _browser_runtime_probe()
    checks.append(_check("OPENCODE_RUNTIME", opencode_runtime["status"] == "AVAILABLE", opencode_runtime, "OPTIONAL"))
    checks.append(_check("GIT_RUNTIME", git_runtime["status"] == "AVAILABLE", git_runtime, "OPTIONAL"))
    checks.append(_check("CONTROLLED_BROWSER_RUNTIME", browser_runtime["status"] == "AVAILABLE", browser_runtime, "OPTIONAL"))
    extension = AI_ROOT / "control-plane" / "browser-extension"
    checks.append(_check("CONTROLLED_BROWSER_EXTENSION", (extension / "manifest.json").exists()))
    checks.append(_check("WEB_CONTROL_PLANE", (AI_ROOT / "control-plane" / "web" / "index.html").exists()))
    profile = _field_validation_profile(field_validation_profile)
    if field_validation_profile:
        checks.append(_check("FIELD_VALIDATION_RUNTIME_PROFILE", bool(profile and profile.get("status") == "PARSED"), profile, "OPTIONAL"))
    # The package ships adapter code, but the secrets directory must stay empty.
    secret_root = AI_ROOT / "local" / "secrets"
    secret_files = [p for p in secret_root.rglob("*") if p.is_file()] if secret_root.exists() else []
    checks.append(_check("NO_BUNDLED_SECRETS", not secret_files, [str(p) for p in secret_files]))
    if project_id:
        try:
            status = project_status(project_id)
            checks.append(_check("PROJECT_REGISTERED", True, status))
            checks.append(_check("PROJECT_REPOSITORIES", status.get("repositories", 0) > 0, status.get("repositories"), "PILOT"))
            checks.append(_check("PROJECT_ENVIRONMENTS", status.get("environments", 0) > 0, status.get("environments"), "PILOT"))
        except Exception as exc:
            checks.append(_check("PROJECT_REGISTERED", False, str(exc), "PILOT"))
    required_ok = all(c["ok"] for c in checks if c["severity"] == "REQUIRED")
    pilot_ok = required_ok and all(c["ok"] for c in checks if c["severity"] == "PILOT")
    return {
        "version": VERSION,
        "version_baseline": version_baseline,
        "field_validation_profile": profile,
        "opencode_runtime": opencode_runtime,
        "git_runtime": git_runtime,
        "browser_runtime": browser_runtime,
        "status": "PILOT_READY" if pilot_ok else ("PACKAGE_READY" if required_ok else "NOT_READY"),
        "required_ok": required_ok,
        "pilot_ok": pilot_ok,
        "checks": checks,
        "projects": [p["project_id"] for p in list_projects()],
    }
