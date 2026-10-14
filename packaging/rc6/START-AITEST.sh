#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="$ROOT/runtime-state"
PATCH="$STATE/rc6.cordis.yml"
LOG="$STATE/dsh-web.log"
PIDFILE="$STATE/dsh-web.pid"
mkdir -p "$STATE"

# Verify immutable package/runtime first, then install or upgrade RC6 into the
# real PFC project workspace. Installation is idempotent and backs up legacy
# PFC-managed content before replacement.
"$ROOT/VERIFY.sh"
INSTALL_JSON="$(bash "$ROOT/INSTALL-AITEST.sh")"
echo "$INSTALL_JSON"

WORKSPACE="${PFC_WORKSPACE:-/d/PFC}"
export PFC_WORKSPACE="$WORKSPACE"
export PFC_AITEST_HOME="$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PFC_AITEST_STATE_DIR="$STATE"
bash "$ROOT/VERIFY-RC6-PROFILE.sh" >/dev/null

PYTHON_BIN="${PFC_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: PYTHON_NOT_FOUND" >&2
  exit 10
fi

# Reuse prior offline tools without pretending discovery equals target readiness.
# The bootstrap performs only bounded, non-destructive host probes. Worker/Target
# capability admission still happens later inside the governed RC6 Runtime.
TOOL_JSON="$("$PYTHON_BIN" -m rc6_release.tool_bootstrap bootstrap --workspace "$WORKSPACE")"
echo "$TOOL_JSON"
"$PYTHON_BIN" -m rc6_release.tool_bootstrap verify --workspace "$WORKSPACE" >/dev/null

if [[ -f "$PIDFILE" ]]; then
  PID="$(tr -d '\r\n ' < "$PIDFILE")"
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    echo "RC6 DSH already running (pid=$PID)"
    "$ROOT/STATUS.sh"
    exit 0
  fi
  rm -f "$PIDFILE"
fi

DSH_BIN="${PFC_DSH_BIN:-}"
if [[ -z "$DSH_BIN" ]]; then
  DSH_BIN="$(command -v dsh 2>/dev/null || true)"
fi
if [[ -z "$DSH_BIN" ]]; then
  echo "ERROR: DSH_NOT_FOUND. Set PFC_DSH_BIN or put dsh on PATH." >&2
  exit 20
fi

# DSH local skill discovery is project scoped. Always start from D:\PFC (or the
# explicit PFC_WORKSPACE) so the scanned skills are the RC6 static install.
cd "$WORKSPACE"
nohup "$DSH_BIN" web --patch "$PATCH" --no-open >"$LOG" 2>&1 < /dev/null &
PID=$!
printf '%s\n' "$PID" > "$PIDFILE"
sleep 3
if ! kill -0 "$PID" 2>/dev/null; then
  echo "ERROR: DSH_START_FAILED" >&2
  tail -n 80 "$LOG" >&2 || true
  rm -f "$PIDFILE"
  exit 21
fi

SOURCE_COMMIT="$(tr -d '\r\n ' < "$ROOT/SOURCE_COMMIT")"
echo "RC6 started: pid=$PID"
echo "WORKSPACE=$WORKSPACE"
echo "RC6_SOURCE_COMMIT=$SOURCE_COMMIT"
echo "RC6_STATIC_SKILLS=26"
echo "RC6_PROFESSIONAL_AGENTS=25"
echo "RC6_AGENT_MECHANISM=DSH_HEADLESS_FRESH_AGENT"
echo "RC6_PROFILE_ACTIVE=PASS"
echo "LEGACY_RC5_PFC_ACTIVE=FALSE"
echo "TOOL_PROFILE=$WORKSPACE/.dsh/rc6/TOOL_PROFILE.json"
echo "TOOL_TARGET_READY=DEFERRED_UNTIL_REAL_MISSION_WORKER_TARGET_BINDING"
echo "DSH Web: ${PFC_DSH_URL:-http://127.0.0.1:3080}"
echo "Release status: $(cat "$ROOT/RELEASE_STATUS" 2>/dev/null || echo SOURCE_TREE)"
echo "Use /pfc-full-chain-test in a fresh DSH session."
