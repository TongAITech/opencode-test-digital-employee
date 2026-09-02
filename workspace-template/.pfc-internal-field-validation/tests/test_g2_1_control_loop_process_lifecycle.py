"""G2.1 package-owned Control Loop process lifecycle checks."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
FIELD_ROOT = WORKSPACE_ROOT / "pfc-field-validation"
sys.path.insert(0, str(FIELD_ROOT))

import pfc_control_loop_process as control  # noqa: E402


class Stub(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None: return
    def _json(self, value: object) -> None:
        data=json.dumps(value).encode(); self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self) -> None:
        if self.path.startswith("/session"): self._json([]); return
        if self.path.startswith("/global/health"): self._json({"healthy":True}); return
        self._json({})


def main() -> int:
    checks: dict[str,bool] = {}
    server=ThreadingHTTPServer(("127.0.0.1",0),Stub); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    server2=ThreadingHTTPServer(("127.0.0.1",0),Stub); thread2=threading.Thread(target=server2.serve_forever,daemon=True); thread2.start()
    old=dict(os.environ)
    try:
        with tempfile.TemporaryDirectory(prefix="pfc-g21-process-") as td:
            state=Path(td); spine=state/"runtime-spine.db"
            os.environ["AITEST_WORKSPACE_ROOT"]=str(WORKSPACE_ROOT)
            os.environ["AITEST_RUNTIME_SPINE_DB"]=str(spine)
            os.environ["PFC_LOCAL_STATE_ROOT"]=str(state)
            os.environ["AITEST_CONTROL_LOOP_INTERVAL_SECONDS"]="0.2"
            endpoint=f"http://127.0.0.1:{server.server_port}"
            endpoint2=f"http://127.0.0.1:{server2.server_port}"
            started=control.start(endpoint); status=control.status()
            same=control.start(endpoint)
            first_pid=int(started["pid"])
            switched=control.start(endpoint2); switched_status=control.status()
            old_pid_stopped=not control._pid_running(first_pid)
            stopped=control.stop(); final=control.status()
            checks["control_loop_wrapper_start_status_stop"]=(started["status"]=="PASS" and status["status"]=="PASS" and stopped["status"]=="PASS" and final["status"]=="REPAIR")
            checks["same_endpoint_reuses_proven_owned_control_loop"]=(same.get("lifecycle")=="ALREADY_RUNNING" and int(same.get("pid") or 0)==first_pid)
            checks["endpoint_change_replaces_old_control_loop_without_orphan"]=(switched.get("status")=="PASS" and switched.get("endpoint")==endpoint2 and switched_status.get("status")=="PASS" and old_pid_stopped)
            checks["control_loop_uses_package_python_process"]=(started.get("python")==sys.executable and started.get("endpoint")==endpoint)
            checks["control_loop_operational_state_is_outside_business_db"]=(state/"state/aitest-control-loop.json").is_file() and spine.is_file()
        wrapper=(FIELD_ROOT/"pfc_control_loop_process.py").read_text(encoding="utf-8")
        bridge=(FIELD_ROOT/"pfc_web_runtime.py").read_text(encoding="utf-8")
        checks["control_loop_windows_stop_is_pid_scoped_no_tree_kill"]=('"taskkill", "/PID", str(number), "/F"' in wrapper and '"/T"' not in wrapper)
        checks["control_loop_requires_fresh_heartbeat_before_kill_or_adopt"]=("STOP_OWNERSHIP_UNVERIFIED" in wrapper and "RUNNING_PROCESS_OWNERSHIP_UNVERIFIED" in wrapper and "_heartbeat_owned" in wrapper)
        checks["pfc_stop_orders_control_loop_before_opencode"]=(bridge.find("loop = control.stop()") < bridge.find("web = process.stop()"))
        checks["pfc_status_requires_opencode_and_control_loop"]=('web.get("status") == "PASS" and loop.get("status") == "PASS"' in bridge)
    finally:
        os.environ.clear(); os.environ.update(old)
        server.shutdown(); server.server_close(); thread.join(timeout=2)
        server2.shutdown(); server2.server_close(); thread2.join(timeout=2)
    payload={"status":"PASS" if all(checks.values()) else "FAIL","checks":checks}
    print(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True)); return 0 if payload["status"]=="PASS" else 1

if __name__=="__main__": raise SystemExit(main())
