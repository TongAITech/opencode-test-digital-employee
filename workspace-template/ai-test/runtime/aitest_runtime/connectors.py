from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import AI_ROOT, now_iso, redact, run_process, runtime_python_command
from .project import get_connector
from .storage import jdump, jload, transaction


def invoke(connector_id: str, request: dict[str, Any], *, timeout: int = 120) -> dict[str, Any]:
    connector = get_connector(connector_id)
    adapter = connector.get("adapter_path")
    if not adapter:
        return {"ok": False, "status": "NOT_CONFIGURED", "connector_id": connector_id}
    path = Path(adapter)
    if not path.is_absolute():
        path = (AI_ROOT.parent / path).resolve()
    if not path.exists():
        return {"ok": False, "status": "ADAPTER_NOT_FOUND", "connector_id": connector_id, "path": str(path)}
    cache = AI_ROOT / "local" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    req_path = cache / f"connector-{connector_id}-{now_iso().replace(':','').replace('+','_')}.json"
    req_path.write_text(json.dumps(redact(request), ensure_ascii=False, indent=2), encoding="utf-8")
    args = [str(path), "--request", str(req_path)] if path.suffix.lower() in {".exe", ".cmd", ".bat"} else [*runtime_python_command(), str(path), "--request", str(req_path)]
    result = run_process(args, cwd=AI_ROOT.parent, timeout=timeout)
    if result["ok"]:
        try:
            payload = json.loads(result["stdout"] or "{}")
        except json.JSONDecodeError:
            payload = {"ok": True, "stdout": result["stdout"]}
        status, error = "READY", None
    else:
        payload = {"ok": False, "status": "ADAPTER_FAILED", "stderr": result["stderr"], "returncode": result["returncode"]}
        status, error = "ERROR", result["stderr"][:2000]
    with transaction() as conn:
        conn.execute("UPDATE connectors SET status=?,last_checked_at=?,last_error=? WHERE connector_id=?", (status, now_iso(), error, connector_id))
    return {"connector_id": connector_id, "connector": connector, "result": payload}


def check(connector_id: str) -> dict[str, Any]:
    return invoke(connector_id, {"action": "health"}, timeout=30)
