#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
PYTHON_BIN=${PFC_PYTHON_BIN:-python3}
if [ -x "$ROOT/workspace-template/runtime/python/python.exe" ] && [ -z "${PFC_PYTHON_BIN:-}" ]; then
  PYTHON_BIN="$ROOT/workspace-template/runtime/python/python.exe"
fi
STATE_ROOT=${PFC_AITEST_STATE_DIR:-"$ROOT/runtime-state"}
R1_PATH=${PFC_RC7_R1_PATH:-"$STATE_ROOT/r1/event-stream.jsonl"}
if [ -z "${PFC_RC7_SOURCE_COMMIT:-}" ] && [ -f "$ROOT/SOURCE_COMMIT" ]; then
  PFC_RC7_SOURCE_COMMIT=$(tr -d '\r\n' < "$ROOT/SOURCE_COMMIT")
  export PFC_RC7_SOURCE_COMMIT
fi
if [ -z "${PFC_RC7_SOURCE_REVISION:-}" ] && [ -n "${PFC_RC7_SOURCE_COMMIT:-}" ]; then
  PFC_RC7_SOURCE_REVISION=$PFC_RC7_SOURCE_COMMIT
  export PFC_RC7_SOURCE_REVISION
fi
mkdir -p "$(dirname "$R1_PATH")"
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH PFC_AITEST_STATE_DIR="$STATE_ROOT"
cd "$ROOT"
echo "[RC7.1] Mission Autopilot R1: $R1_PATH"

# Backward-compatible environment mode. The durable Mission is resumed and then
# immediately driven from canonical R1; no manual follow-up "continue" is needed.
if [ -n "${PFC_RC7_MISSION_ID:-}" ] && [ -n "${PFC_RC7_RELEASE_ID:-}" ] && [ -n "${PFC_RC7_MISSION_GOAL:-}" ]; then
  exec "$PYTHON_BIN" -m rc7_runtime.bank_mission_start \
    --r1 "$R1_PATH" \
    --package-root "$ROOT" \
    --mission-id "$PFC_RC7_MISSION_ID" \
    --release-id "$PFC_RC7_RELEASE_ID" \
    --goal "$PFC_RC7_MISSION_GOAL" \
    "$@"
fi

# CLI mode preserves historical --graph-version and repeatable --input NODE=REF
# arguments and accepts the new Autopilot runtime options on the same entry.
exec "$PYTHON_BIN" -m rc7_runtime.bank_mission_start \
  --r1 "$R1_PATH" \
  --package-root "$ROOT" \
  "$@"
