"""RC7.1 startup trace.

This traces only RC7-owned startup work. It deliberately does not claim that a
DSH provider/model is ready merely because the DSH host process was launched.
The status file makes that boundary visible to field diagnosis.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict


SCHEMA = "pfc.aitest.rc7.1.startup-trace.v1"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _paths(home: str):
    root = Path(home).expanduser().resolve()
    state = root / "state"
    state.mkdir(parents=True, exist_ok=True)
    return state / "rc71-startup-status.json", state / "rc71-startup-trace.jsonl"


def _read_status(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def init(home: str) -> Dict[str, Any]:
    status_path, trace_path = _paths(home)
    now = _now_ms()
    payload = {
        "schema": SCHEMA,
        "run_id": "START-" + uuid.uuid4().hex,
        "status": "STARTING",
        "started_at_epoch_ms": now,
        "updated_at_epoch_ms": now,
        "elapsed_ms": 0,
        "last_phase": "RC7_BOOTSTRAP",
        "last_event": "START",
        "boundary": "RC7_OWNED_PRESTART",
        "dsh_host_launched": False,
        "model_ready": "NOT_PROBED_BY_RC7",
        "session_ready": "NOT_PROBED_BY_RC7",
    }
    status_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    trace_path.write_text(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def mark(home: str, phase: str, event: str, detail: str = "") -> Dict[str, Any]:
    status_path, trace_path = _paths(home)
    status = _read_status(status_path)
    if not status:
        status = init(home)
    now = _now_ms()
    started = int(status.get("started_at_epoch_ms") or now)
    phase_value = str(phase or "UNKNOWN").strip().upper()
    event_value = str(event or "MARK").strip().upper()
    record = {
        "schema": SCHEMA,
        "run_id": status.get("run_id"),
        "phase": phase_value,
        "event": event_value,
        "detail": str(detail or ""),
        "at_epoch_ms": now,
        "elapsed_ms": max(0, now - started),
    }
    with trace_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    status.update(
        {
            "updated_at_epoch_ms": now,
            "elapsed_ms": record["elapsed_ms"],
            "last_phase": phase_value,
            "last_event": event_value,
            "last_detail": record["detail"],
        }
    )
    if phase_value == "DSH_HOST_LAUNCH" and event_value == "START":
        status["status"] = "RC7_PRESTART_COMPLETE_DSH_OWNED_AFTER_THIS_POINT"
        status["boundary"] = "DSH_HOST_PROVIDER_SESSION"
        status["dsh_host_launched"] = True
    elif event_value == "FAIL":
        status["status"] = "RC7_PRESTART_FAILED"
    status_path.write_text(json.dumps(status, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return status


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init")
    p_init.add_argument("--home", required=True)
    p_mark = sub.add_parser("mark")
    p_mark.add_argument("--home", required=True)
    p_mark.add_argument("--phase", required=True)
    p_mark.add_argument("--event", required=True)
    p_mark.add_argument("--detail", default="")
    args = parser.parse_args(argv)
    if args.command == "init":
        payload = init(args.home)
    else:
        payload = mark(args.home, args.phase, args.event, args.detail)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
