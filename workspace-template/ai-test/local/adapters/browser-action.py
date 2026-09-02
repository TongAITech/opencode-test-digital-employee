from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parents[2] / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

def load_request():
    p=argparse.ArgumentParser(); p.add_argument('--request',required=True); a=p.parse_args()
    return json.loads(Path(a.request).read_text(encoding='utf-8'))

def emit(value):
    print(json.dumps(value, ensure_ascii=False))

def main():
    req = load_request()
    if req.get("mock_result") is not None:
        return emit({
            "ok": False,
            "status": "R3_E3_MOCK_NOT_ACCEPTED",
            "error": "mock_result cannot satisfy a real Browser action",
        })
    try:
        from aitest_runtime.r3_e3 import BrowserActionRequest, ControlledBrowserRuntime

        runtime = ControlledBrowserRuntime(
            environment_config=req.get("environment_config") or {},
            environment_id=str(req.get("environment_id") or "UNKNOWN"),
        )
        session = runtime.create_or_lookup_session(req)
        action = BrowserActionRequest.from_mapping(req)
        if action.action_kind == "NAVIGATE":
            receipt = runtime.navigate(
                session.browser_context_ref,
                action.target,
                request_id=action.request_id,
                idempotency_key=action.idempotency_key,
            )
        else:
            value = req.get("non_secret_value") if not req.get("sensitive") else None
            receipt = runtime.execute_action(session.browser_context_ref, action, value=value)
        return emit({"ok": True, "status": receipt.outcome, "receipt": receipt.to_dict(), "capability_report": runtime.capability_report().to_dict()})
    except Exception as exc:
        code = getattr(exc, "code", type(exc).__name__)
        return emit({"ok": False, "status": code, "error": str(exc)})


if __name__ == "__main__":
    main()
