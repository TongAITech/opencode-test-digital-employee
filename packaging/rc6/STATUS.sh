#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="$ROOT/runtime-state"
PIDFILE="$STATE/dsh-web.pid"
WORKSPACE="${PFC_WORKSPACE:-/d/PFC}"
TOOL_PROFILE="$WORKSPACE/.dsh/rc6/TOOL_PROFILE.json"
INSTALL_MANIFEST="$WORKSPACE/.dsh/rc6/INSTALL_MANIFEST.json"
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
printf 'WORKSPACE=%s\n' "$WORKSPACE"
printf 'BUILD_ID=%s\n' "$(cat "$ROOT/BUILD_ID" 2>/dev/null || echo SOURCE_TREE)"
printf 'SOURCE_COMMIT=%s\n' "$(cat "$ROOT/SOURCE_COMMIT" 2>/dev/null || echo UNKNOWN)"
printf 'RELEASE_STATUS=%s\n' "$(cat "$ROOT/RELEASE_STATUS" 2>/dev/null || echo SOURCE_TREE)"
printf 'RC6_PROFILE=%s\n' "$([[ -f "$INSTALL_MANIFEST" ]] && echo INSTALLED || echo NOT_INSTALLED)"
printf 'RC6_STATIC_SKILLS=%s\n' "26"
printf 'RC6_PROFESSIONAL_AGENTS=%s\n' "25"
printf 'TOOL_PROFILE=%s\n' "$([[ -f "$TOOL_PROFILE" ]] && echo PRESENT || echo NOT_BUILT)"
printf 'TOOL_TARGET_READY=%s\n' "DEFERRED_UNTIL_REAL_MISSION_WORKER_TARGET_BINDING"
printf 'DSH_WEB=%s\n' "${PFC_DSH_URL:-http://127.0.0.1:3080}"

PYTHON_BIN="${PFC_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then PYTHON_BIN="$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)"; fi
if [[ -n "$PYTHON_BIN" && -f "$TOOL_PROFILE" ]]; then
  "$PYTHON_BIN" - "$TOOL_PROFILE" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    p = json.load(fh)
s = p.get("summary", {})
print("TOOL_PROBE_PASS=%s" % s.get("probe_pass", 0))
print("TOOL_FIELD_BLOCKED=%s" % s.get("field_blocked", 0))
print("TOOL_NOT_FOUND=%s" % s.get("not_found", 0))
print("TOOL_PROBE_FAIL=%s" % s.get("probe_fail", 0))
PY
fi
