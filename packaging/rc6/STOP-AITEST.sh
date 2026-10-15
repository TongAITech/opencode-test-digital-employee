#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="$ROOT/runtime-state"
FAILED=0

stop_one() {
  local name="$1" pidfile="$2"
  if [[ ! -f "$pidfile" ]]; then
    echo "$name already stopped"
    return 0
  fi
  local pid
  pid="$(tr -d '\r\n ' < "$pidfile")"
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pidfile"
    echo "$name already stopped (stale pid removed)"
    return 0
  fi
  kill "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$pidfile"
      echo "$name stopped"
      return 0
    fi
    sleep 0.25
  done
  echo "ERROR: ${name}_STOP_TIMEOUT pid=$pid" >&2
  FAILED=1
}

stop_one "RC6_ADMIN" "$STATE/admin-web.pid"
stop_one "RC6_DSH" "$STATE/dsh-web.pid"
exit "$FAILED"
