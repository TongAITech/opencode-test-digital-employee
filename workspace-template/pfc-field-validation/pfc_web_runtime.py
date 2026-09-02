"""Compatibility CLI for OpenCode + G2.1 Control Loop lifecycle.

OpenCode remains a process boundary. The G2.1 Control Loop is a separate
package-owned process that observes/reroutes Sessions from R1 durable truth.
Neither process owns Mission/Plan/Task business truth.
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any

import pfc_control_loop_process as control
import pfc_opencode_process as process


def _emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _wrap(value: dict[str, Any]) -> dict[str, Any]:
    return {
        **value,
        "scope": "OPENCODE_PROCESS_PLUS_G2_1_CONTROL_LOOP",
        "runtime_truth": "R1_EVENT_STREAM",
        "legacy_runtime_write": "FORBIDDEN",
        "agent_owns_session_lifecycle": False,
    }


def start() -> dict[str, Any]:
    web = process.start()
    if web.get("status") != "PASS":
        return {"status": "FAIL", "lifecycle": "OPENCODE_START_FAILED", "opencode": web}
    endpoint = str(web.get("endpoint") or "")
    os.environ["AITEST_OPENCODE_ENDPOINT"] = endpoint
    loop = control.start(endpoint)
    if loop.get("status") != "PASS":
        rollback = process.stop()
        return {
            "status": "FAIL", "lifecycle": "CONTROL_LOOP_START_FAILED",
            "opencode": web, "control_loop": loop, "opencode_rollback": rollback,
        }
    return {
        "status": "PASS", "lifecycle": "STARTED", "opencode": web, "control_loop": loop,
        "endpoint": endpoint, "runtime_admission": loop.get("runtime_admission", "UNKNOWN"),
    }


def status() -> dict[str, Any]:
    web = process.status()
    loop = control.status()
    ok = web.get("status") == "PASS" and loop.get("status") == "PASS"
    return {
        "status": "PASS" if ok else "REPAIR",
        "lifecycle": "RUNNING" if ok else "NOT_HEALTHY",
        "opencode": web,
        "control_loop": loop,
        "endpoint": web.get("endpoint"),
        "runtime_admission": loop.get("runtime_admission", "UNKNOWN"),
    }


def stop() -> dict[str, Any]:
    # Supervisor stops first so it cannot provision/rotate against a server that
    # is concurrently shutting down.
    loop = control.stop()
    web = process.stop()
    ok = loop.get("status") == "PASS" and web.get("status") == "PASS"
    return {
        "status": "PASS" if ok else "REPAIR",
        "lifecycle": "STOPPED" if ok else "STOP_INCOMPLETE",
        "control_loop": loop,
        "opencode": web,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pfc-web-runtime")
    parser.add_argument("command", choices=("start", "status", "stop"))
    args = parser.parse_args(argv)
    value = {"start": start, "status": status, "stop": stop}[args.command]()
    _emit(_wrap(value))
    return 0 if value.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
