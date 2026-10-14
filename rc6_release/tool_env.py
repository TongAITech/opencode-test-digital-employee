from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from .tool_bootstrap import PROFILE_REL, TOOL_SPECS

SPECIAL_ENV = {"4a": "PFC_4A_SCRIPT", "cat": "PFC_CAT_CONFIG"}


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def bindings(workspace: str | Path) -> Dict[str, str]:
    work = Path(workspace).resolve()
    path = work / PROFILE_REL
    if not path.is_file():
        raise RuntimeError("RC6_TOOL_PROFILE_MISSING")
    profile = json.loads(path.read_text(encoding="utf-8"))
    result: Dict[str, str] = {"PFC_WORKSPACE": str(work)}
    for item in profile.get("tools") or []:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        tool_id = item.get("tool_id")
        status = item.get("status")
        if tool_id in TOOL_SPECS and status == "PROBE_PASS":
            result[TOOL_SPECS[tool_id]["env"]] = str(item["path"])
        elif tool_id in SPECIAL_ENV and str(status).startswith("BLOCKED_FIELD_"):
            result[SPECIAL_ENV[tool_id]] = str(item["path"])
    return result


def shell_exports(workspace: str | Path) -> str:
    values = bindings(workspace)
    return "\n".join("export %s=%s" % (key, _quote(values[key])) for key in sorted(values)) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rc6_release.tool_env")
    parser.add_argument("--workspace", default=os.environ.get("PFC_WORKSPACE") or (r"D:\PFC" if os.name == "nt" else "/d/PFC"))
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    text = shell_exports(args.workspace)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
