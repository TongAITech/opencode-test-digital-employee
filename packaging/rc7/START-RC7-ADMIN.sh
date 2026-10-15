#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
PYTHON_BIN=${PFC_PYTHON_BIN:-python3}
R1_PATH=${PFC_RC7_R1_PATH:-"$ROOT/state/rc7-r1.jsonl"}
HOST=${PFC_RC7_ADMIN_HOST:-127.0.0.1}
PORT=${PFC_RC7_ADMIN_PORT:-4097}
mkdir -p "$(dirname "$R1_PATH")"
cd "$ROOT"
exec "$PYTHON_BIN" -m rc7_admin --r1 "$R1_PATH" --host "$HOST" --port "$PORT"
