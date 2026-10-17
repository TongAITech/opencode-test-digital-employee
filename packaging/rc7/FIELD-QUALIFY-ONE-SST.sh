#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && { pwd -W 2>/dev/null || pwd; })"
PY="${PFC_PYTHON_BIN:-}"
if [[ -z "$PY" ]]; then
  if [[ -f "$ROOT/workspace-template/runtime/python/python.exe" ]]; then
    PY="$ROOT/workspace-template/runtime/python/python.exe"
  else
    PY="python3"
  fi
fi
export PYTHONUTF8=1
export PFC_AITEST_HOME="${PFC_AITEST_HOME:-$ROOT}"
export PFC_AITEST_STATE_DIR="${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state}"
if [[ -z "${PFC_RC7_SOURCE_COMMIT:-}" && -f "$ROOT/SOURCE_COMMIT" ]]; then
  PFC_RC7_SOURCE_COMMIT="$(tr -d '\r\n' < "$ROOT/SOURCE_COMMIT")"
  export PFC_RC7_SOURCE_COMMIT
fi
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH
cd "$ROOT"
exec "$PY" -m rc7_release.one_sst_field_qualification "$@"
