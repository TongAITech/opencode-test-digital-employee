#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state}"
PATCH="$STATE/rc6.cordis.yml"
mkdir -p "$STATE"

PYTHON_BIN="${PFC_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo '{"status":"NOT_PROVEN","reason":"PYTHON_NOT_FOUND"}' >&2
  exit 10
fi

export PFC_AITEST_HOME="$ROOT"
export PFC_AITEST_STATE_DIR="$STATE"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PFC_WORKSPACE="${PFC_WORKSPACE:-/d/PFC}"

# BANK_FINAL qualification may not run against a stale RC5 profile. Package
# integrity is checked first, then the RC6 workspace profile is installed or
# repaired and hash-verified before DSH worker evidence is accepted.
bash "$ROOT/VERIFY.sh" --package-only >/dev/null
bash "$ROOT/INSTALL-AITEST.sh" >/dev/null
bash "$ROOT/VERIFY-RC6-PROFILE.sh" >/dev/null

DSH_BIN="${PFC_DSH_BIN:-}"
if [[ -z "$DSH_BIN" ]]; then
  DSH_BIN="$(command -v dsh 2>/dev/null || true)"
fi

ARGS=(
  -m rc6_release.agent_qualification
  --home "$ROOT"
  --patch "$PATCH"
)
if [[ -n "$DSH_BIN" ]]; then
  ARGS+=(--dsh "$DSH_BIN")
fi
if [[ -n "${PFC_COORDINATOR_INSTANCE_ID:-}" ]]; then
  ARGS+=(--coordinator-instance-id "$PFC_COORDINATOR_INSTANCE_ID")
fi
if [[ -n "${PFC_AGENT_QUALIFICATION_TIMEOUT:-}" ]]; then
  ARGS+=(--timeout "$PFC_AGENT_QUALIFICATION_TIMEOUT")
fi

"$PYTHON_BIN" "${ARGS[@]}"
