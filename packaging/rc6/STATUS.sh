#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="$ROOT/runtime-state"
PIDFILE="$STATE/dsh-web.pid"
STATUS="STOPPED"
PID=""
if [[ -f "$PIDFILE" ]]; then
  PID="$(tr -d '\r\n ' < "$PIDFILE")"
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    STATUS="RUNNING"
  else
    STATUS="STALE_PID"
  fi
fi
printf 'RC6_STATUS=%s\n' "$STATUS"
printf 'PID=%s\n' "$PID"
printf 'BUILD_ID=%s\n' "$(cat "$ROOT/BUILD_ID" 2>/dev/null || echo SOURCE_TREE)"
printf 'SOURCE_COMMIT=%s\n' "$(cat "$ROOT/SOURCE_COMMIT" 2>/dev/null || echo UNKNOWN)"
printf 'RELEASE_STATUS=%s\n' "$(cat "$ROOT/RELEASE_STATUS" 2>/dev/null || echo SOURCE_TREE)"
printf 'DSH_WEB=%s\n' "${PFC_DSH_URL:-http://127.0.0.1:3080}"
