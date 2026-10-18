from __future__ import annotations

import argparse
import json
from pathlib import Path

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    text = Path(args.input).read_text(encoding="utf-8", errors="replace")
    events = tuple(DshHeadlessWorkerLauncher._parse_json_lines(text))
    calls = DshHeadlessWorkerLauncher._tool_calls(events)
    final = DshHeadlessWorkerLauncher._final_json(events)
    runtime_calls = [
        call
        for call in calls
        if "runtime_status" in str(call.get("tool_name") or "").lower()
    ]
    final_ok = (
        isinstance(final, dict)
        and str(final.get("status") or "").upper() == "PASS"
        and str(final.get("proof") or "") == "runtime_status_called"
    )
    payload = {
        "status": "PASS" if runtime_calls and final_ok else "FAIL",
        "tool_call_count": len(calls),
        "runtime_status_call_count": len(runtime_calls),
        "observed_tools": [str(call.get("tool_name") or "") for call in calls],
        "final_json": final,
        "final_contract_pass": final_ok,
    }
    Path(args.output).write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
