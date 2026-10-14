#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PFC_PYTHON:-$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)}"
[[ -n "$PYTHON_BIN" ]] || { echo "ERROR: PYTHON_NOT_FOUND" >&2; exit 10; }
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
WORKSPACE="${PFC_WORKSPACE:-/d/PFC}"
ARGS=(-m rc6_release.workspace_install rollback --workspace "$WORKSPACE")
if [[ -n "${1:-}" ]]; then ARGS+=(--backup "$1"); fi
"$PYTHON_BIN" "${ARGS[@]}"
