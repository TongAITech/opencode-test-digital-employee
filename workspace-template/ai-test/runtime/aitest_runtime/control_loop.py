"""Background G2.1 autonomous Runtime Control Loop.

The loop owns no authoritative memory. Every tick reconstructs the canonical
Runtime from the R1 Event Stream, reconciles Session provisioning, observes all
active Sessions, applies Runtime rotation policy, and invokes package-owned G4
AUTO HumanGate observation. Restarting this process is therefore a normal
recovery path rather than a loss of orchestration state.
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

from .canonical_runtime import create_canonical_runtime, runtime_status
from .g2_1.managed_orchestration import default_g21_service
from .g4.composition import load_provider_bundle
from .g4.service import G4RealExecutionService

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


def _profile(root: Path) -> dict[str, Any]:
    path = root / "PFC_PROJECT_PROFILE.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _g4_background_human_gate_tick(runtime: Any, root: Path) -> dict[str, Any]:
    """Observe AUTO/AUTO_OR_EXPLICIT gates without an LLM or G4 objective tick."""
    try:
        bundle = load_provider_bundle(root, _profile(root))
        service = G4RealExecutionService(
            runtime,
            browser_provider=bundle.browser_provider,
            capability_executors=bundle.capability_executors,
            resume_condition_verifier=bundle.resume_condition_verifier,
        )
        missions = [
            str(item.get("mission_id"))
            for item in (runtime_status(root).get("missions") or [])
            if item.get("mission_id")
        ]
        results = {mission_id: service.auto_resume_human_gates(mission_id) for mission_id in missions}
        resumed = sorted(
            gate_id
            for value in results.values()
            for gate_id in (value.get("resumed_gate_refs") or [])
        )
        waiting = sorted(
            str(item.get("gate_id"))
            for value in results.values()
            for item in (value.get("pending_gate_refs") or [])
            if item.get("gate_id")
        )
        return {
            "status": "RESUMED" if resumed else ("WAITING" if waiting else "PASS"),
            "truth_source": "R1_EVENT_STREAM",
            "component": "G4_HUMAN_GATE_BACKGROUND_OBSERVER",
            "non_llm": True,
            "package_owned": True,
            "objective_control_tick_dependency": False,
            "mission_results": results,
            "resumed_gate_refs": resumed,
            "pending_gate_refs": waiting,
        }
    except Exception as exc:
        return {
            "status": "BLOCKED",
            "truth_source": "R1_EVENT_STREAM",
            "component": "G4_HUMAN_GATE_BACKGROUND_OBSERVER",
            "non_llm": True,
            "package_owned": True,
            "objective_control_tick_dependency": False,
            "error": type(exc).__name__,
            "message": str(exc),
        }


def run_tick(workspace_root: Path) -> dict[str, Any]:
    # Rebuild per tick on purpose: no in-memory Session/Mission/HumanGate state can
    # become a second authority or survive independently of the Event Stream.
    runtime = create_canonical_runtime(workspace_root)
    service = default_g21_service(runtime, workspace_root)
    result = service.supervise_once()
    g4_background = _g4_background_human_gate_tick(runtime, workspace_root)
    return {**result, "g4_human_gate_background": g4_background}


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
