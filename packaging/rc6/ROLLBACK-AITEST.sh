#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PFC_PYTHON:-$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)}"
[[ -n "$PYTHON_BIN" ]] || { echo "ERROR: PYTHON_NOT_FOUND" >&2; exit 10; }
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
WORKSPACE="${PFC_WORKSPACE:-/d/PFC}"

# Restore historical .opencode pfc-* definitions before workspace rollback can
# replace/remove the RC6 profile state that records the guard backup path.
"$PYTHON_BIN" -m rc6_release.legacy_skill_guard rollback --workspace "$WORKSPACE"

ARGS=(-m rc6_release.workspace_install rollback --workspace "$WORKSPACE")
if [[ -n "${1:-}" ]]; then ARGS+=(--backup "$1"); fi
"$PYTHON_BIN" "${ARGS[@]}"
