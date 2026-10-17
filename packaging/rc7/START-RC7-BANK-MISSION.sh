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
mkdir -p "$(dirname "$R1_PATH")"
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH PFC_AITEST_STATE_DIR="$STATE_ROOT"
cd "$ROOT"
echo "[RC7] Mission R1: $R1_PATH"

# Backward compatible environment mode. Otherwise pass normal CLI arguments
# straight to the durable Bank Mission entrypoint, so no prior export commands
# are required.
if [ -n "${PFC_RC7_MISSION_ID:-}" ] && [ -n "${PFC_RC7_RELEASE_ID:-}" ] && [ -n "${PFC_RC7_MISSION_GOAL:-}" ]; then
  exec "$PYTHON_BIN" -m rc7_runtime.bank_mission \
    --r1 "$R1_PATH" \
    --mission-id "$PFC_RC7_MISSION_ID" \
    --release-id "$PFC_RC7_RELEASE_ID" \
    --goal "$PFC_RC7_MISSION_GOAL" \
    "$@"
fi

exec "$PYTHON_BIN" -m rc7_runtime.bank_mission --r1 "$R1_PATH" "$@"
