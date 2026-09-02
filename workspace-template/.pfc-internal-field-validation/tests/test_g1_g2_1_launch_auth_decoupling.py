"""G1 + G2.1 launch/auth admission decoupling construction check.

The HTTP server deliberately behaves like a reachable OpenCode Web whose
Session API first returns 401.  The package-owned background Control Loop must
stay alive in WAITING_AUTH_OR_SESSION_API so the same Web remains available for
human authentication.  Once admission becomes available, the same Control Loop
must converge to READY without restart.

This is a construction contract stub, not evidence of the bank's exact
OpenCode 1.18.3 auth/session payload shape.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = WORKSPACE_ROOT / "ai-test" / "runtime"
FIELD_ROOT = WORKSPACE_ROOT / "pfc-field-validation"
sys.path.insert(0, str(RUNTIME_ROOT))
sys.path.insert(0, str(FIELD_ROOT))

from aitest_runtime.autonomous_orchestration import (  # noqa: E402
    DirectoryScopedOpenCodeSessionProvider,
    OpenCodeSessionAdmissionPending,
)
import pfc_control_loop_process as control  # noqa: E402


class Stub(BaseHTTPRequestHandler):
    admitted = False

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _json(self, code: int, value: object) -> None:
        data = json.dumps(value).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.startswith("/global/health"):
            self._json(200, {"healthy": True})
            return
        if self.path.startswith("/session"):
            if not self.__class__.admitted:
                self._json(401, {"error": "authentication required"})
                return
            self._json(200, [])
            return
        self._json(404, {"error": "unknown"})


def main() -> int:
    checks: dict[str, bool] = {}
    Stub.admitted = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    old = dict(os.environ)
    try:
        with tempfile.TemporaryDirectory(prefix="pfc-g21-auth-decouple-") as td:
            state_root = Path(td)
            spine = state_root / "durable/state/runtime-spine.db"
            endpoint = f"http://127.0.0.1:{server.server_port}"
            os.environ.update({
                "AITEST_WORKSPACE_ROOT": str(WORKSPACE_ROOT),
                "AITEST_RUNTIME_SPINE_DB": str(spine),
                "AITEST_OPENCODE_ENDPOINT": endpoint,
                "PFC_LOCAL_STATE_ROOT": str(state_root),
                "AITEST_CONTROL_LOOP_INTERVAL_SECONDS": "0.15",
            })

            provider = DirectoryScopedOpenCodeSessionProvider(WORKSPACE_ROOT, base_url=endpoint)
            admission_exc = False
            try:
                provider.list_sessions()
            except OpenCodeSessionAdmissionPending:
                admission_exc = True
            checks["session_provider_classifies_401_as_admission_wait_not_fake_empty"] = admission_exc

            started = control.start(endpoint)
            heartbeat = started.get("heartbeat") if isinstance(started, dict) else None
            tick = heartbeat.get("tick") if isinstance(heartbeat, dict) else None
            checks["control_loop_starts_while_session_api_auth_pending"] = (
                started.get("status") == "PASS"
                and isinstance(tick, dict)
                and tick.get("status") == "WAIT"
                and tick.get("runtime_admission") == "WAITING_AUTH_OR_SESSION_API"
                and started.get("runtime_admission") == "WAITING_AUTH_OR_SESSION_API"
            )
            pid = int(started.get("pid") or 0)

            Stub.admitted = True
            converged = False
            deadline = time.time() + 4
            last: dict[str, object] = {}
            while time.time() < deadline:
                last = control.status()
                hb = last.get("heartbeat") if isinstance(last, dict) else None
                tk = hb.get("tick") if isinstance(hb, dict) else None
                if (
                    last.get("status") == "PASS"
                    and int(last.get("pid") or 0) == pid
                    and isinstance(tk, dict)
                    and tk.get("status") == "PASS"
                    and last.get("runtime_admission") == "READY"
                ):
                    converged = True
                    break
                time.sleep(0.1)
            checks["same_control_loop_converges_to_ready_after_auth_without_restart"] = converged
            checks["auth_transition_preserves_same_control_loop_pid"] = converged and int(last.get("pid") or 0) == pid

            stopped = control.stop()
            checks["auth_wait_control_loop_remains_package_owned_and_stoppable"] = stopped.get("status") == "PASS"

        bridge = (FIELD_ROOT / "pfc_web_runtime.py").read_text(encoding="utf-8")
        checks["pfc_web_start_exposes_runtime_admission_separately"] = '"runtime_admission"' in bridge
        checks["pfc_web_rolls_back_only_when_control_process_itself_fails"] = (
            'if loop.get("status") != "PASS"' in bridge
            and 'rollback = process.stop()' in bridge
        )
    finally:
        os.environ.clear()
        os.environ.update(old)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    payload = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "field_validation_boundary": "REAL_BANK_OPENCODE_1_18_3_AUTH_SESSION_PAYLOAD_PENDING",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
