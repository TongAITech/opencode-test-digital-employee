"""Background G2.1 autonomous Runtime Control Loop.

The loop owns no authoritative memory. Every tick reconstructs the canonical
Runtime from the R1 Event Stream, reconciles Session provisioning, observes all
active Sessions, and applies Runtime rotation policy. Restarting this process is
therefore a normal recovery path rather than a loss of orchestration state.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .canonical_runtime import create_canonical_runtime
from .g2_1.managed_orchestration import default_g21_service

_STOP = False


def _handle_stop(_signum: int, _frame: Any) -> None:
    global _STOP
    _STOP = True


def _emit(value: Any) -> None:
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        return
    stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    stream.flush()


def _heartbeat(value: dict[str, Any]) -> None:
    raw = os.environ.get("AITEST_CONTROL_LOOP_HEARTBEAT_PATH")
    if not raw:
        return
    path = Path(raw).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **value,
        "pid": os.getpid(),
        "written_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "truth_source": "R1_EVENT_STREAM",
        "operational_only": True,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def run_tick(workspace_root: Path) -> dict[str, Any]:
    # Rebuild per tick on purpose: no in-memory Session/Mission state can become
    # a second authority or survive independently of the Event Stream.
    runtime = create_canonical_runtime(workspace_root)
    service = default_g21_service(runtime, workspace_root)
    return service.supervise_once()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aitest-control-loop")
    p.add_argument("--workspace-root", required=True)
    p.add_argument("--interval", type=float, default=float(os.environ.get("AITEST_CONTROL_LOOP_INTERVAL_SECONDS", "10")))
    p.add_argument("--once", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = Path(args.workspace_root).expanduser().resolve()
    if not root.is_dir():
        _emit({"status": "FAIL", "error": "WORKSPACE_NOT_FOUND", "workspace": str(root)})
        return 2
    if args.interval <= 0:
        _emit({"status": "FAIL", "error": "INTERVAL_MUST_BE_POSITIVE"})
        return 2
    os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
    signal.signal(signal.SIGTERM, _handle_stop)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, _handle_stop)
    if args.once:
        try:
            value = run_tick(root)
            tick_operational = value.get("status") in {"PASS", "WAIT"}
            _heartbeat({"status": "PASS" if tick_operational else "TICK_FAIL", "component": "G2_1_CONTROL_LOOP", "tick": value})
            _emit(value)
            return 0 if tick_operational else 1
        except Exception as exc:
            failure = {"status": "FAIL", "error": type(exc).__name__, "message": str(exc), "truth_source": "R1_EVENT_STREAM"}
            _heartbeat(failure)
            _emit(failure)
            return 1

    started = {"status": "STARTED", "component": "G2_1_CONTROL_LOOP", "truth_source": "R1_EVENT_STREAM", "interval_seconds": args.interval}
    _heartbeat(started)
    _emit(started)
    while not _STOP:
        try:
            value = run_tick(root)
            tick_operational = value.get("status") in {"PASS", "WAIT"}
            _heartbeat({"status": "PASS" if tick_operational else "TICK_FAIL", "component": "G2_1_CONTROL_LOOP", "tick": value})
            _emit(value)
        except Exception as exc:
            # A tick failure is operational evidence, not a reason to invent a
            # new Mission/Session truth. The next tick reconstructs from R1.
            failure = {"status": "TICK_FAIL", "error": type(exc).__name__, "message": str(exc), "truth_source": "R1_EVENT_STREAM"}
            _heartbeat(failure)
            _emit(failure)
        deadline = time.monotonic() + args.interval
        while not _STOP and time.monotonic() < deadline:
            time.sleep(min(0.25, max(0.01, deadline - time.monotonic())))
    stopped = {"status": "STOPPED", "component": "G2_1_CONTROL_LOOP", "truth_source": "R1_EVENT_STREAM"}
    _heartbeat(stopped)
    _emit(stopped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
