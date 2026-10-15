#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
PYTHON_BIN=${PFC_PYTHON_BIN:-python3}
if [ -x "$ROOT/workspace-template/runtime/python/python.exe" ] && [ -z "${PFC_PYTHON_BIN:-}" ]; then
  PYTHON_BIN="$ROOT/workspace-template/runtime/python/python.exe"
fi
R1_PATH=${PFC_RC7_R1_PATH:-"$ROOT/state/rc7-r1.jsonl"}
if [ -z "${PFC_RC7_SOURCE_COMMIT:-}" ] && [ -f "$ROOT/SOURCE_COMMIT" ]; then
  PFC_RC7_SOURCE_COMMIT=$(tr -d '\r\n' < "$ROOT/SOURCE_COMMIT")
  export PFC_RC7_SOURCE_COMMIT
fi
: "${PFC_RC7_MISSION_ID:?PFC_RC7_MISSION_ID is required}"
: "${PFC_RC7_RELEASE_ID:?PFC_RC7_RELEASE_ID is required}"
: "${PFC_RC7_MISSION_GOAL:?PFC_RC7_MISSION_GOAL is required}"
mkdir -p "$(dirname "$R1_PATH")"
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH
cd "$ROOT"
echo "[RC7] Mission R1: $R1_PATH"
exec "$PYTHON_BIN" -m rc7_runtime.bank_mission \
  --r1 "$R1_PATH" \
  --mission-id "$PFC_RC7_MISSION_ID" \
  --release-id "$PFC_RC7_RELEASE_ID" \
  --goal "$PFC_RC7_MISSION_GOAL" \
  "$@"
