from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .common import AI_ROOT, WORKSPACE_ROOT, load_json, new_id, now_iso, path_within, redact, run_process, runtime_python_command
from .mission import current_step, get_mission, role_for_actor
from .project import get_connector
from .repository import get_repository
from .storage import all_rows, jdump, jload, one, transaction
from .truth import gate_status

CONFIG_PATH = AI_ROOT / "config" / "capabilities.json"


def registry() -> dict[str, dict[str, Any]]:
    data = load_json(CONFIG_PATH, {"capabilities": []})
    return {item["id"]: item for item in data.get("capabilities") or []}


def _audit(mission_id: str | None, step_id: str | None, actor: str, role: str, capability_id: str, decision: str, reason: str, request: dict[str, Any], result: Any = None) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT INTO capability_audit(audit_id,mission_id,step_id,actor,actor_role,capability_id,decision,reason,request_json,result_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("CAP"), mission_id, step_id, actor, role, capability_id, decision, reason, jdump(redact(request)), jdump(redact(result)) if result is not None else None, now_iso()),
        )


def authorize(capability_id: str, actor: str, request: dict[str, Any], *, mission_id: str | None = None, step_id: str | None = None) -> tuple[dict[str, Any], str]:
    item = registry().get(capability_id)
    role = role_for_actor(actor)
    if not item:
        _audit(mission_id, step_id, actor, role, capability_id, "DENY", "CAPABILITY_NOT_REGISTERED", request)
        raise PermissionError("CAPABILITY_NOT_REGISTERED")
    if role not in item.get("roles", []):
        _audit(mission_id, step_id, actor, role, capability_id, "DENY", "ROLE_NOT_ALLOWED", request)
        raise PermissionError(f"ROLE_NOT_ALLOWED:{role}")
    if mission_id:
        mission = get_mission(mission_id, include_steps=False)
        if role == "EXECUTOR":
            if mission["state"] != "EXECUTING":
                _audit(mission_id, step_id, actor, role, capability_id, "DENY", "MISSION_NOT_EXECUTING", request)
                raise PermissionError("MISSION_NOT_EXECUTING")
            step = current_step(mission_id)
            if not step or step["step_id"] != (step_id or step["step_id"]):
                _audit(mission_id, step_id, actor, role, capability_id, "DENY", "CURSOR_MISMATCH", request)
                raise PermissionError("CURSOR_MISMATCH")
            if step.get("capability_id") and step["capability_id"] != capability_id:
                _audit(mission_id, step_id, actor, role, capability_id, "DENY", "CAPABILITY_OUTSIDE_FROZEN_STEP", request)
                raise PermissionError("CAPABILITY_OUTSIDE_FROZEN_STEP")
        required_gate = item.get("requires_gate")
        if required_gate:
            gate = gate_status(mission.get("requirement_id"), required_gate) if mission.get("requirement_id") else None
            if not gate or gate.get("status") != "PASS" or gate.get("decision") not in {"APPROVE", "ACCEPT_RISK"}:
                _audit(mission_id, step_id, actor, role, capability_id, "DENY", f"{required_gate}_NOT_APPROVED", request)
                raise PermissionError(f"{required_gate}_NOT_APPROVED")
    return item, role


def _repo_roots(project_id: str) -> list[Path]:
    return [Path(row["local_path"]).resolve() for row in all_rows("SELECT local_path FROM repositories WHERE project_id=?", (project_id,))]


def _builtin(capability_id: str, request: dict[str, Any], *, mission_id: str | None = None) -> Any:
    if capability_id == "mock.echo":
        return {"echo": request}
    if capability_id == "mock.fail":
        return {"ok": False, "error": request.get("error") or "MOCK_FAILURE"}
    if capability_id == "project.status":
        from .project import project_status
        return project_status(str(request["project_id"]))
    if capability_id.startswith("git."):
        repo = get_repository(str(request["repository_id"]))
        root = Path(repo["local_path"])
        if capability_id == "git.status":
            return run_process(["git", "-C", str(root), "status", "--porcelain=v1", "--branch"], timeout=30)
        if capability_id == "git.diff":
            args = ["git", "-C", str(root), "diff", "--no-ext-diff", "--unified=3"]
            if request.get("range"):
                args.append(str(request["range"]))
            if request.get("path"):
                args.extend(["--", str(request["path"])])
            return run_process(args, timeout=60)
        if capability_id == "git.show":
            ref = str(request.get("ref") or "HEAD")
            return run_process(["git", "-C", str(root), "show", "--stat", "--oneline", "--decorate", ref], timeout=60)
    if capability_id in {"repo.read", "repo.search"}:
        project_id = str(request["project_id"])
        roots = _repo_roots(project_id)
        if capability_id == "repo.read":
            path = Path(str(request["path"])).resolve()
            if not path_within(path, roots):
                raise PermissionError("PATH_OUTSIDE_REGISTERED_REPOSITORIES")
            if path.is_dir() or not path.exists():
                raise ValueError("path must be an existing file")
            max_bytes = min(int(request.get("max_bytes") or 200000), 1000000)
            data = path.read_bytes()[:max_bytes]
            return {"path": str(path), "text": data.decode("utf-8", errors="replace"), "truncated": path.stat().st_size > max_bytes}
        pattern = str(request.get("pattern") or "")
        if not pattern or len(pattern) > 500:
            raise ValueError("invalid search pattern")
        regex = re.compile(pattern)
        limit = min(int(request.get("limit") or 100), 500)
        matches = []
        extensions = set(request.get("extensions") or [".py", ".java", ".kt", ".js", ".ts", ".vue", ".xml", ".yaml", ".yml", ".json", ".sql"])
        for root in roots:
            for path in root.rglob("*"):
                if len(matches) >= limit:
                    break
                if not path.is_file() or path.suffix.lower() not in extensions or any(part in {".git", "node_modules", "target", "dist", "build"} for part in path.parts):
                    continue
                try:
                    for no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                        if regex.search(line):
                            matches.append({"path": str(path), "line": no, "text": line[:500]})
                            if len(matches) >= limit:
                                break
                except OSError:
                    continue
        return {"matches": matches, "count": len(matches)}
    if capability_id == "api.request":
        url = str(request["url"])
        method = str(request.get("method") or "GET").upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("unsupported HTTP method")
        project_id = str(request["project_id"])
        env_id = request.get("environment_id")
        env = one("SELECT * FROM environments WHERE project_id=? AND environment_id=?", (project_id, env_id)) if env_id else None
        allowed = set((jload((env or {}).get("config_json"), {}) or {}).get("allowed_hosts") or [])
        host = urllib.parse.urlparse(url).hostname
        if allowed and host not in allowed:
            raise PermissionError(f"HOST_NOT_ALLOWED:{host}")
        headers = {str(k): str(v) for k, v in (request.get("headers") or {}).items() if not re.search(r"(?i)(authorization|cookie|token|secret)", str(k))}
        body = request.get("body")
        payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        req = urllib.request.Request(url, data=payload, method=method, headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=min(int(request.get("timeout") or 30), 120)) as response:
                raw = response.read(min(int(request.get("max_bytes") or 1000000), 5000000))
                text = raw.decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = text
                return {"ok": 200 <= response.status < 400, "status": response.status, "headers": dict(response.headers.items()), "body": parsed}
        except urllib.error.HTTPError as exc:
            raw = exc.read(1000000).decode("utf-8", errors="replace")
            return {"ok": False, "status": exc.code, "body": raw}
    if capability_id == "browser.launch":
        from .browser import launch_browser
        return launch_browser(**request)
    raise NotImplementedError(capability_id)


def _adapter(capability: dict[str, Any], request: dict[str, Any]) -> Any:
    adapter_name = str(capability.get("adapter") or "")
    path = AI_ROOT / "local" / "adapters" / adapter_name
    if not path.exists():
        raise FileNotFoundError(f"adapter not configured: {path}")
    request_path = AI_ROOT / "local" / "cache" / f"capability-{new_id('REQ')}.json"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(redact(request), ensure_ascii=False, indent=2), encoding="utf-8")
    result = run_process([str(path), "--request", str(request_path)], cwd=AI_ROOT.parent, timeout=int(request.get("timeout") or 120)) if path.suffix.lower() in {".cmd", ".bat", ".exe"} else run_process([*runtime_python_command(), str(path), "--request", str(request_path)], cwd=AI_ROOT.parent, timeout=int(request.get("timeout") or 120))
    if not result["ok"]:
        return {"ok": False, "adapter": adapter_name, "error": result["stderr"], "returncode": result["returncode"]}
    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError:
        return {"ok": True, "adapter": adapter_name, "stdout": result["stdout"]}


def invoke(capability_id: str, actor: str, request: dict[str, Any], *, mission_id: str | None = None, step_id: str | None = None) -> dict[str, Any]:
    capability, role = authorize(capability_id, actor, request, mission_id=mission_id, step_id=step_id)
    try:
        if capability.get("handler") == "builtin":
            result = _builtin(capability_id, request, mission_id=mission_id)
        else:
            result = _adapter(capability, request)
        decision = "ALLOW"
        reason = "AUTHORIZED"
        _audit(mission_id, step_id, actor, role, capability_id, decision, reason, request, result)
        return {"ok": not (isinstance(result, dict) and result.get("ok") is False), "capability_id": capability_id, "actor_role": role, "result": redact(result)}
    except Exception as exc:
        _audit(mission_id, step_id, actor, role, capability_id, "ERROR", f"{type(exc).__name__}:{exc}", request)
        raise
