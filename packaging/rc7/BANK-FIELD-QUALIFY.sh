#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && { pwd -W 2>/dev/null || pwd; })"
PY="${PFC_PYTHON:-$ROOT/workspace-template/runtime/python/python.exe}"
if [[ ! -f "$PY" && "$PY" == "$ROOT/workspace-template/runtime/python/python.exe" ]]; then
  PY="python"
fi

# Single-entry Bank Field qualification. Missing identities are auto-resolved
# only when unique; the launcher never uses a newest/latest heuristic.
exec "$PY" -m rc7_release.bank_field_launcher run --package-root "$ROOT" "$@"
