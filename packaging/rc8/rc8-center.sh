#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

export PYTHONUTF8="${PYTHONUTF8:-1}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

if [[ -n "${RC8_PYTHON:-}" ]]; then
  PYTHON_BIN="$RC8_PYTHON"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "RC8_CENTER_PYTHON_NOT_FOUND" >&2
  exit 3
fi

"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,8), "RC8 requires Python >= 3.8"'
exec "$PYTHON_BIN" -m rc8_center "$@"
