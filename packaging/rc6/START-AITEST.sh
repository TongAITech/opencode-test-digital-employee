#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="$ROOT/runtime-state"
PATCH="$STATE/rc6.cordis.yml"
LOG="$STATE/dsh-web.log"
PIDFILE="$STATE/dsh-web.pid"
LEGACY_ENV="$STATE/rc6-legacy-field-env.sh"
TOOL_ENV="$STATE/rc6-tool-env.sh"
mkdir -p "$STATE"

"$ROOT/VERIFY.sh"
INSTALL_JSON="$(bash "$ROOT/INSTALL-AITEST.sh")"
echo "$INSTALL_JSON"

WORKSPACE="${PFC_WORKSPACE:-/d/PFC}"
export PFC_WORKSPACE="$WORKSPACE"
export PFC_AITEST_HOME="$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PFC_AITEST_STATE_DIR="$STATE"

PYTHON_BIN="${PFC_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: PYTHON_NOT_FOUND" >&2
  exit 10
fi

# INSTALL-AITEST performs the one and only destructive legacy pfc-* isolation
# and records the backup pointer. Startup verifies it but must not sanitize a
# second time, otherwise the original upgrade backup evidence would be lost.
GUARD_JSON="$("$PYTHON_BIN" -m rc6_release.legacy_skill_guard verify --workspace "$WORKSPACE")"
echo "$GUARD_JSON"
bash "$ROOT/VERIFY-RC6-PROFILE.sh" >/dev/null

# Reuse the authoritative historical field registry and bounded legacy runtime
# roots before host probing. This prevents Workers from guessing tool locations.
BRIDGE_JSON="$("$PYTHON_BIN" -m rc6_release.legacy_field_bridge --workspace "$WORKSPACE" --package-root "$ROOT" --output "$LEGACY_ENV")"
echo "$BRIDGE_JSON"
# shellcheck disable=SC1090
source "$LEGACY_ENV"

# Discover and probe reusable historical/host tools, then export only verified
# executable paths (plus discovered 4A/CAT binding paths) into the DSH host.
# This makes the existing offline tools actually reachable by RC6 Workers.
TOOL_JSON="$("$PYTHON_BIN" -m rc6_release.tool_bootstrap bootstrap --workspace "$WORKSPACE")"
echo "$TOOL_JSON"
"$PYTHON_BIN" -m rc6_release.tool_bootstrap verify --workspace "$WORKSPACE" >/dev/null
"$PYTHON_BIN" -m rc6_release.tool_env --workspace "$WORKSPACE" --output "$TOOL_ENV"
# shellcheck disable=SC1090
source "$TOOL_ENV"

# Rebuild the MCP patch after tool bindings are exported so the RC6 MCP child
# receives the exact workspace/tool-path environment as well.
"$PYTHON_BIN" -m rc6_release.dsh --output "$PATCH" --home "$ROOT" --python "$PYTHON_BIN" >/dev/null

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
echo "LEGACY_PFC_SKILL_GUARD=PASS"
echo "LEGACY_FIELD_BRIDGE=PASS"
echo "TOOL_PROFILE=$WORKSPACE/.dsh/rc6/TOOL_PROFILE.json"
echo "TOOL_ENV_BINDING=PASS"
echo "TOOL_TARGET_READY=DEFERRED_UNTIL_REAL_MISSION_WORKER_TARGET_BINDING"
echo "DSH Web: ${PFC_DSH_URL:-http://127.0.0.1:3080}"
echo "Release status: $(cat "$ROOT/RELEASE_STATUS" 2>/dev/null || echo SOURCE_TREE)"
echo "Use /pfc-full-chain-test in a fresh DSH session."
