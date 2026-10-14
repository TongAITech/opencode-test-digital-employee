from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

TOOL_ENV_KEYS = (
    "PFC_WORKSPACE", "PFC_GIT_BIN", "PFC_CODEGRAPH_BIN", "PFC_GITNEXUS_BIN",
    "PFC_PYTHON", "PFC_JAVA_BIN", "PFC_MAVEN_BIN", "PFC_BROWSERSKILL_BIN",
    "PFC_PLAYWRIGHT_BIN", "PFC_CHROMIUM_BIN", "PFC_K6_BIN", "PFC_ZAP_BIN",
    "PFC_4A_SCRIPT", "PFC_CAT_CONFIG",
)


def _yaml_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def write_patch(output: str | Path, home: str | Path, python_executable: str | None = None) -> Path:
    target = Path(output)
    root = str(Path(home).resolve())
    python_cmd = python_executable or sys.executable
    lines = [
        "- insert:",
        "    - id: mcp-pfc-aitest-rc6",
        "      name: '@deepseek-ai/dsh-mcp-client'",
        "      config:",
        "        serverName: pfc_aitest_rc6",
        "        transport: stdio",
        f"        command: {_yaml_quote(python_cmd)}",
        "        args: ['-m', 'rc6_release.mcp_server']",
        "        env:",
        f"          PFC_AITEST_HOME: {_yaml_quote(root)}",
        f"          PYTHONPATH: {_yaml_quote(root)}",
    ]
    for key in TOOL_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            lines.append(f"          {key}: {_yaml_quote(value)}")
    lines.extend([
        f"        cwd: {_yaml_quote(root)}",
        "        toolCallTimeoutMs: 60000",
        "        failOnStartupError: true",
        "",
    ])
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--python")
    args = parser.parse_args(argv)
    print(write_patch(args.output, args.home, args.python))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
