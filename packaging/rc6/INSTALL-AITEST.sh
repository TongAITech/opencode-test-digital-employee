#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PFC_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: PYTHON_NOT_FOUND" >&2
  exit 10
fi
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
WORKSPACE="${PFC_WORKSPACE:-/d/PFC}"
"$PYTHON_BIN" -m rc6_release.workspace_install install --package-root "$ROOT" --workspace "$WORKSPACE"
