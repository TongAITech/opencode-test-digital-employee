#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

UNAME_S="$(uname -s 2>/dev/null || true)"
case "$UNAME_S" in
  MINGW*|MSYS*|CYGWIN*)
    export RC8_NODE_OS="windows"
    export RC8_NODE_SHELL="git-bash"
    ;;
  Linux*)
    export RC8_NODE_OS="linux"
    export RC8_NODE_SHELL="bash"
    ;;
  *)
    echo "RC8_NODE_UNSUPPORTED_PLATFORM: $UNAME_S" >&2
    exit 2
    ;;
esac

if [[ -n "${RC8_PYTHON:-}" ]]; then
  PYTHON_BIN="$RC8_PYTHON"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "RC8_NODE_PYTHON_NOT_FOUND" >&2
  exit 3
fi

"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,8), "RC8 requires Python >= 3.8"'

exec "$PYTHON_BIN" -m rc8_node "$@"
