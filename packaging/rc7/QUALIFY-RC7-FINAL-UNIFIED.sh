#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd -W 2>/dev/null || cd "$(dirname "$0")/../.." && pwd)"
PY="$ROOT/workspace-template/runtime/python/python.exe"
mkdir -p "$ROOT/state"
exec "$PY" -m rc7_release.final_unified_qualification --home "$ROOT" --output "$ROOT/state/final-unified-qualification.json" --require-pass
