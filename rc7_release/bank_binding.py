from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional


BINDINGS = (
    ("DSH_HOST", "DSH_HOME", False),
    ("4A", "PFC_4A_SCRIPT", True),
    ("CAT", "PFC_CAT_CONFIG", True),
    ("TDSQL", "PFC_TDSQL_DSN", False),
    ("OCEANBASE", "PFC_OCEANBASE_DSN", False),
    ("TIDB", "PFC_TIDB_DSN", False),
    ("MAVEN_MIRROR", "PFC_MAVEN_MIRROR_URL", False),
    ("PIP_MIRROR", "PFC_PIP_INDEX_URL", False),
)


def masked(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "***"
    return value[:3] + "***" + value[-3:]


def probe() -> Dict[str, object]:
    result: Dict[str, object] = {"status": "PASS", "bindings": {}, "write_policy": "HUMAN_CONFIRMATION_REQUIRED"}
    for name, env_name, should_be_file in BINDINGS:
        value = os.environ.get(env_name, "").strip()
        bound = bool(value)
        file_ok = None
        if should_be_file and value:
            file_ok = Path(value).expanduser().is_file()
            bound = bound and bool(file_ok)
        result["bindings"][name] = {
            "env": env_name,
            "configured": bool(value),
            "ready": bound,
            "file_ok": file_ok,
            "value_masked": masked(value),
        }
    result["field_ready"] = all(item["ready"] for key, item in result["bindings"].items() if key in ("4A", "CAT", "MAVEN_MIRROR", "PIP_MIRROR"))
    result["real_bank_mission"] = "READY_FOR_FIELD_PROBE" if result["field_ready"] else "HOLD_FIELD_BINDINGS_REQUIRED"
    return result


def run_foura(extra: List[str]) -> int:
    script = os.environ.get("PFC_4A_SCRIPT", "").strip()
    if not script:
        print(json.dumps({"status": "HOLD", "reason": "PFC_4A_SCRIPT_NOT_CONFIGURED"}))
        return 3
    path = Path(script).expanduser().resolve()
    if not path.is_file():
        print(json.dumps({"status": "FAIL", "reason": "PFC_4A_SCRIPT_NOT_FOUND", "path": str(path)}))
        return 2
    proc = subprocess.run([sys.executable, str(path)] + extra)
    return int(proc.returncode)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command")
    check = sub.add_parser("probe")
    check.add_argument("--output")
    foura = sub.add_parser("foura")
    foura.add_argument("args", nargs=argparse.REMAINDER)
    args = p.parse_args(argv)
    if args.command == "probe":
        result = probe()
        text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
        if args.output:
            target = Path(args.output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0
    if args.command == "foura":
        return run_foura(args.args)
    p.error("command required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
