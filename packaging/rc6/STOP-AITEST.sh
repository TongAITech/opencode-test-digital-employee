#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDFILE="$ROOT/runtime-state/dsh-web.pid"
if [[ ! -f "$PIDFILE" ]]; then
  echo "RC6 already stopped"
  exit 0
fi
PID="$(tr -d '\r\n ' < "$PIDFILE")"
if [[ -z "$PID" ]] || ! kill -0 "$PID" 2>/dev/null; then
  rm -f "$PIDFILE"
  echo "RC6 already stopped (stale pid removed)"
  exit 0
fi
kill "$PID"
for _ in {1..20}; do
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PIDFILE"
    echo "RC6 stopped"
    exit 0
  fi
  sleep 0.25
done
echo "ERROR: DSH_STOP_TIMEOUT pid=$PID" >&2
exit 30
