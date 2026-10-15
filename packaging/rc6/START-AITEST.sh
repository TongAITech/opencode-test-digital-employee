#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="$ROOT/runtime-state"
PATCH="$STATE/rc6.cordis.yml"
DSH_LOG="$STATE/dsh-web.log"
DSH_PIDFILE="$STATE/dsh-web.pid"
ADMIN_LOG="$STATE/admin-web.log"
ADMIN_PIDFILE="$STATE/admin-web.pid"
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
export PFC_ADMIN_HOST="${PFC_ADMIN_HOST:-127.0.0.1}"
export PFC_ADMIN_PORT="${PFC_ADMIN_PORT:-8765}"
ADMIN_URL="http://$PFC_ADMIN_HOST:$PFC_ADMIN_PORT"

PYTHON_BIN="${PFC_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: PYTHON_NOT_FOUND" >&2
  exit 10
fi

GUARD_JSON="$("$PYTHON_BIN" -m rc6_release.legacy_skill_guard verify --workspace "$WORKSPACE")"
echo "$GUARD_JSON"
bash "$ROOT/VERIFY-RC6-PROFILE.sh" >/dev/null

BRIDGE_JSON="$("$PYTHON_BIN" -m rc6_release.legacy_field_bridge_compat --workspace "$WORKSPACE" --package-root "$ROOT" --output "$LEGACY_ENV")"
echo "$BRIDGE_JSON"
# shellcheck disable=SC1090
source "$LEGACY_ENV"

TOOL_JSON="$("$PYTHON_BIN" -m rc6_release.tool_bootstrap bootstrap --workspace "$WORKSPACE")"
echo "$TOOL_JSON"
"$PYTHON_BIN" -m rc6_release.tool_bootstrap verify --workspace "$WORKSPACE" >/dev/null
"$PYTHON_BIN" -m rc6_release.tool_env --workspace "$WORKSPACE" --output "$TOOL_ENV"
# shellcheck disable=SC1090
source "$TOOL_ENV"

"$PYTHON_BIN" -m rc6_release.dsh --output "$PATCH" --home "$ROOT" --python "$PYTHON_BIN" >/dev/null

DSH_STARTED_HERE=0
DSH_PID=""
if [[ -f "$DSH_PIDFILE" ]]; then
  DSH_PID="$(tr -d '\r\n ' < "$DSH_PIDFILE")"
  if [[ -z "$DSH_PID" ]] || ! kill -0 "$DSH_PID" 2>/dev/null; then
    rm -f "$DSH_PIDFILE"
    DSH_PID=""
  fi
fi

if [[ -z "$DSH_PID" ]]; then
  DSH_BIN="${PFC_DSH_BIN:-}"
  if [[ -z "$DSH_BIN" ]]; then DSH_BIN="$(command -v dsh 2>/dev/null || true)"; fi
  if [[ -z "$DSH_BIN" ]]; then
    echo "ERROR: DSH_NOT_FOUND. Set PFC_DSH_BIN or put dsh on PATH." >&2
    exit 20
  fi
  cd "$WORKSPACE"
  nohup "$DSH_BIN" web --patch "$PATCH" --no-open >"$DSH_LOG" 2>&1 < /dev/null &
  DSH_PID=$!
  printf '%s\n' "$DSH_PID" > "$DSH_PIDFILE"
  DSH_STARTED_HERE=1
  sleep 3
  if ! kill -0 "$DSH_PID" 2>/dev/null; then
    echo "ERROR: DSH_START_FAILED" >&2
    tail -n 80 "$DSH_LOG" >&2 || true
    rm -f "$DSH_PIDFILE"
    exit 21
  fi
fi

ADMIN_PID=""
if [[ -f "$ADMIN_PIDFILE" ]]; then
  ADMIN_PID="$(tr -d '\r\n ' < "$ADMIN_PIDFILE")"
  if [[ -z "$ADMIN_PID" ]] || ! kill -0 "$ADMIN_PID" 2>/dev/null; then
    rm -f "$ADMIN_PIDFILE"
    ADMIN_PID=""
  fi
fi

if [[ -z "$ADMIN_PID" ]]; then
  cd "$ROOT"
  nohup "$PYTHON_BIN" -m rc6_release.admin_server --host "$PFC_ADMIN_HOST" --port "$PFC_ADMIN_PORT" >"$ADMIN_LOG" 2>&1 < /dev/null &
  ADMIN_PID=$!
  printf '%s\n' "$ADMIN_PID" > "$ADMIN_PIDFILE"
fi

ADMIN_READY=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if ! kill -0 "$ADMIN_PID" 2>/dev/null; then break; fi
  if "$PYTHON_BIN" - "$ADMIN_URL/api/health" <<'PY' >/dev/null 2>&1
import json, sys
try:
    try:
        from urllib.request import urlopen
    except ImportError:
        from urllib2 import urlopen
    with urlopen(sys.argv[1], timeout=1) as r:
        data = json.loads(r.read().decode("utf-8"))
    raise SystemExit(0 if data.get("status") == "PASS" and data.get("service") == "RC6_ADMIN" else 1)
except Exception:
    raise SystemExit(1)
PY
  then
    ADMIN_READY=1
    break
  fi
  sleep 0.5
done

if [[ "$ADMIN_READY" != "1" ]]; then
  echo "ERROR: RC6_ADMIN_START_FAILED" >&2
  tail -n 80 "$ADMIN_LOG" >&2 || true
  if [[ -n "$ADMIN_PID" ]] && kill -0 "$ADMIN_PID" 2>/dev/null; then kill "$ADMIN_PID" 2>/dev/null || true; fi
  rm -f "$ADMIN_PIDFILE"
  if [[ "$DSH_STARTED_HERE" == "1" ]] && kill -0 "$DSH_PID" 2>/dev/null; then
    kill "$DSH_PID" 2>/dev/null || true
    rm -f "$DSH_PIDFILE"
  fi
  exit 22
fi

SOURCE_COMMIT="$(tr -d '\r\n ' < "$ROOT/SOURCE_COMMIT")"
echo "RC6 started: dsh_pid=$DSH_PID admin_pid=$ADMIN_PID"
echo "WORKSPACE=$WORKSPACE"
echo "RC6_SOURCE_COMMIT=$SOURCE_COMMIT"
echo "RC6_STATIC_SKILLS=26"
echo "RC6_PROFESSIONAL_AGENTS=25"
echo "RC6_AGENT_MECHANISM=DSH_HEADLESS_FRESH_AGENT"
echo "RC6_PROFILE_ACTIVE=PASS"
echo "LEGACY_RC5_PFC_ACTIVE=FALSE"
echo "LEGACY_MANAGED_ASSET_GUARD=PASS"
echo "LEGACY_FIELD_BRIDGE=PASS"
echo "TOOL_PROFILE=$WORKSPACE/.dsh/rc6/TOOL_PROFILE.json"
echo "TOOL_ENV_BINDING=PASS"
echo "TOOL_TARGET_READY=DEFERRED_UNTIL_REAL_MISSION_WORKER_TARGET_BINDING"
echo "DSH Web: ${PFC_DSH_URL:-http://127.0.0.1:3080}"
echo "RC6 Admin: $ADMIN_URL"
echo "RC6_ADMIN_TRUTH=R1_EVENT_STREAM_READ_ONLY"
echo "Release status: $(cat "$ROOT/RELEASE_STATUS" 2>/dev/null || echo SOURCE_TREE)"
echo "Use /pfc-full-chain-test in a fresh DSH session."
