#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
PYTHON_BIN=${PFC_PYTHON_BIN:-python3}
STATE_ROOT=${PFC_AITEST_STATE_DIR:-"$ROOT/runtime-state"}
R1_PATH=${PFC_RC7_R1_PATH:-"$STATE_ROOT/r1/event-stream.jsonl"}
HOST=${PFC_RC7_ADMIN_HOST:-127.0.0.1}
PORT=${PFC_RC7_ADMIN_PORT:-4097}
mkdir -p "$(dirname "$R1_PATH")"
cd "$ROOT"
echo "[RC7 ADMIN] Canonical R1: $R1_PATH"
exec "$PYTHON_BIN" -m rc7_admin --r1 "$R1_PATH" --host "$HOST" --port "$PORT"
