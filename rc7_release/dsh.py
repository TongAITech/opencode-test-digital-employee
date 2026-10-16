from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Union


TOOL_ENV_KEYS = (
    "PFC_WORKSPACE",
    "PFC_GIT_BIN",
    "PFC_CODEGRAPH_BIN",
    "PFC_GITNEXUS_BIN",
    "PFC_PYTHON",
    "PFC_JAVA_BIN",
    "PFC_MAVEN_BIN",
    "PFC_BROWSERSKILL_BIN",
    "PFC_PLAYWRIGHT_BIN",
    "PFC_CHROMIUM_BIN",
    "PFC_K6_BIN",
    "PFC_ZAP_BIN",
    "PFC_4A_SCRIPT",
    "PFC_CAT_CONFIG",
)


def _yaml_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def write_patch(
    output: Union[str, Path],
    home: Union[str, Path],
    python_executable: Optional[str] = None,
) -> Path:
    target = Path(output)
    root = str(Path(home).resolve())
    python_cmd = python_executable or sys.executable
    state_root = os.environ.get("PFC_AITEST_STATE_DIR") or str(Path(root) / "runtime-state")
    lines = [
        "- insert:",
        "    - id: mcp-pfc-aitest-rc7",
        "      name: '@deepseek-ai/dsh-mcp-client'",
        "      config:",
        "        serverName: pfc_aitest_rc7",
        "        transport: stdio",
        "        command: %s" % _yaml_quote(python_cmd),
        "        args: ['-m', 'rc7_release.mcp_server']",
        "        env:",
        "          PFC_AITEST_HOME: %s" % _yaml_quote(root),
        "          PFC_AITEST_STATE_DIR: %s" % _yaml_quote(state_root),
        "          PYTHONPATH: %s" % _yaml_quote(root),
    ]
    if not os.environ.get("PFC_WORKSPACE"):
        lines.append("          PFC_WORKSPACE: %s" % _yaml_quote(root))
    for key in TOOL_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            lines.append("          %s: %s" % (key, _yaml_quote(value)))
    lines.extend(
        [
            "        cwd: %s" % _yaml_quote(root),
            "        toolCallTimeoutMs: 60000",
            "        failOnStartupError: true",
            "",
        ]
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--python")
    args = parser.parse_args(argv)
    print(write_patch(args.output, args.home, args.python))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
