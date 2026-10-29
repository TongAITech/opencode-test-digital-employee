#!/usr/bin/env bash
set -euo pipefail

SOURCE_COMMIT=""
RUNNER_KIND=""
RUNNER_IDENTITY=""
OUTPUT=""

usage() {
  cat >&2 <<'EOF'
Usage: Q3-TARGET-LINUX-PROBE.sh --source-commit <40-hex-sha> --runner-kind <kind> --runner-identity <identity> --output <path>
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-commit)
      [[ $# -ge 2 ]] || { usage; exit 64; }
      SOURCE_COMMIT="$2"
      shift 2
      ;;
    --runner-kind)
      [[ $# -ge 2 ]] || { usage; exit 64; }
      RUNNER_KIND="$2"
      shift 2
      ;;
    --runner-identity)
      [[ $# -ge 2 ]] || { usage; exit 64; }
      RUNNER_IDENTITY="$2"
      shift 2
      ;;
    --output)
      [[ $# -ge 2 ]] || { usage; exit 64; }
      OUTPUT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Q3_TARGET_LINUX_PROBE_UNKNOWN_ARGUMENT:$1" >&2
      usage
      exit 64
      ;;
  esac
done

[[ "$SOURCE_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]] || { echo 'Q3_TARGET_LINUX_PROBE_SOURCE_COMMIT_INVALID' >&2; exit 2; }
[[ -n "$RUNNER_KIND" ]] || { echo 'Q3_TARGET_LINUX_PROBE_RUNNER_KIND_REQUIRED' >&2; exit 2; }
[[ -n "$RUNNER_IDENTITY" ]] || { echo 'Q3_TARGET_LINUX_PROBE_RUNNER_IDENTITY_REQUIRED' >&2; exit 2; }
[[ -n "$OUTPUT" ]] || { echo 'Q3_TARGET_LINUX_PROBE_OUTPUT_REQUIRED' >&2; exit 2; }

PLATFORM_FAMILY="Linux"
PLATFORM_RELEASE="unknown"
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  PLATFORM_FAMILY="${NAME:-${ID:-Linux}}"
  PLATFORM_RELEASE="${VERSION_ID:-${VERSION:-unknown}}"
fi

ARCHITECTURE="$(uname -m)"
SHELL_PATH="${SHELL:-/bin/bash}"

if [[ -n "${PFC_RC72_PACKAGE_PYTHON:-}" && -x "${PFC_RC72_PACKAGE_PYTHON}" ]]; then
  PYTHON_BIN="${PFC_RC72_PACKAGE_PYTHON}"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo 'Q3_TARGET_LINUX_PROBE_PYTHON_REQUIRED' >&2
  exit 3
fi
PYTHON_VERSION="$(${PYTHON_BIN} -c 'import platform; print(platform.python_version())')"

mkdir -p "$(dirname "$OUTPUT")"
export SOURCE_COMMIT RUNNER_KIND RUNNER_IDENTITY PLATFORM_FAMILY PLATFORM_RELEASE ARCHITECTURE SHELL_PATH PYTHON_VERSION
"$PYTHON_BIN" - "$OUTPUT" <<'PY'
from __future__ import print_function

import json
import os
import sys

output = sys.argv[1]
payload = {
    "schema": "pfc.aitest.rc7.2.target-linux-observation.v1",
    "source_commit": os.environ["SOURCE_COMMIT"].lower(),
    "platform_family": os.environ["PLATFORM_FAMILY"],
    "platform_release": os.environ["PLATFORM_RELEASE"],
    "architecture": os.environ["ARCHITECTURE"],
    "python_version": os.environ["PYTHON_VERSION"],
    "shell": os.environ["SHELL_PATH"],
    "runner_kind": os.environ["RUNNER_KIND"],
    "runner_identity": os.environ["RUNNER_IDENTITY"],
}
with open(output, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY

echo "Q3_TARGET_LINUX_OBSERVATION_EMITTED output=$OUTPUT"
