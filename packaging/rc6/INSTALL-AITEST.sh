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

# Install/upgrade the immutable RC6 .dsh skill payload first.
"$PYTHON_BIN" -m rc6_release.workspace_install install --package-root "$ROOT" --workspace "$WORKSPACE"

# DSH can also scan historical .opencode roots. Back up and isolate only
# legacy pfc-* definitions so RC5 cannot shadow or contaminate the RC6 profile.
"$PYTHON_BIN" -m rc6_release.legacy_skill_guard sanitize --workspace "$WORKSPACE"

# An install is not complete until both the immutable RC6 profile and the
# legacy-scan isolation gate verify successfully.
"$PYTHON_BIN" -m rc6_release.workspace_install verify --package-root "$ROOT" --workspace "$WORKSPACE" >/dev/null
"$PYTHON_BIN" -m rc6_release.legacy_skill_guard verify --workspace "$WORKSPACE" >/dev/null
