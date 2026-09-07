"""Approved local Starlink export adapter, persisted in canonical R1/G3."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    workspace = Path(os.environ.get("AITEST_WORKSPACE_ROOT") or Path(__file__).resolve().parents[3]).resolve()
    sys.path.insert(0, str(workspace / "ai-test/runtime"))
    from aitest_runtime.recovery_intake import dispatch
    path = request.get("file_path") or request.get("export_path") or request.get("path")
    if not path or not request.get("mission_id"):
        print(json.dumps({"ok": False, "status": "BANK_BINDING_REQUIRED", "required": "mission_id, export file, and locally approved bindings/starlink.json"}))
        return 1
    try:
        result = dispatch(workspace, "import_current_release", {
            "mission_id": request["mission_id"], "path": path,
            "binding_path": request.get("binding_path") or str(workspace / "bindings/starlink.json"),
        })
    except Exception as exc:
        print(json.dumps({"ok": False, "status": "FAIL", "error_code": getattr(exc, "code", type(exc).__name__), "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
