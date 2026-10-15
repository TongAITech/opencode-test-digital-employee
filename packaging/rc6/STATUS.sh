#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="$ROOT/runtime-state"
WORKSPACE="${PFC_WORKSPACE:-/d/PFC}"
TOOL_PROFILE="$WORKSPACE/.dsh/rc6/TOOL_PROFILE.json"
INSTALL_MANIFEST="$WORKSPACE/.dsh/rc6/INSTALL_MANIFEST.json"

proc_status() {
  local pidfile="$1"
  if [[ ! -f "$pidfile" ]]; then printf 'STOPPED|'; return; fi
  local pid="$(tr -d '\r\n ' < "$pidfile")"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then printf 'RUNNING|%s' "$pid"; else printf 'STALE_PID|%s' "$pid"; fi
}
IFS='|' read -r DSH_STATUS DSH_PID <<< "$(proc_status "$STATE/dsh-web.pid")"
IFS='|' read -r ADMIN_STATUS ADMIN_PID <<< "$(proc_status "$STATE/admin-web.pid")"
OVERALL="RUNNING"
if [[ "$DSH_STATUS" != "RUNNING" || "$ADMIN_STATUS" != "RUNNING" ]]; then OVERALL="DEGRADED"; fi
if [[ "$DSH_STATUS" == "STOPPED" && "$ADMIN_STATUS" == "STOPPED" ]]; then OVERALL="STOPPED"; fi
printf 'RC6_STATUS=%s\n' "$OVERALL"
printf 'DSH_STATUS=%s\nDSH_PID=%s\n' "$DSH_STATUS" "$DSH_PID"
printf 'ADMIN_STATUS=%s\nADMIN_PID=%s\n' "$ADMIN_STATUS" "$ADMIN_PID"
printf 'WORKSPACE=%s\n' "$WORKSPACE"
printf 'BUILD_ID=%s\n' "$(cat "$ROOT/BUILD_ID" 2>/dev/null || echo SOURCE_TREE)"
printf 'SOURCE_COMMIT=%s\n' "$(cat "$ROOT/SOURCE_COMMIT" 2>/dev/null || echo UNKNOWN)"
printf 'RELEASE_STATUS=%s\n' "$(cat "$ROOT/RELEASE_STATUS" 2>/dev/null || echo SOURCE_TREE)"
printf 'RC6_PROFILE=%s\n' "$([[ -f "$INSTALL_MANIFEST" ]] && echo INSTALLED || echo NOT_INSTALLED)"
printf 'RC6_STATIC_SKILLS=26\nRC6_PROFESSIONAL_AGENTS=25\n'
printf 'TOOL_PROFILE=%s\n' "$([[ -f "$TOOL_PROFILE" ]] && echo PRESENT || echo NOT_BUILT)"
printf 'TOOL_TARGET_READY=DEFERRED_UNTIL_REAL_MISSION_WORKER_TARGET_BINDING\n'
printf 'DSH_WEB=%s\n' "${PFC_DSH_URL:-http://127.0.0.1:3080}"
printf 'RC6_ADMIN=%s\n' "${PFC_ADMIN_URL:-http://127.0.0.1:${PFC_ADMIN_PORT:-8765}}"
printf 'RC6_ADMIN_TRUTH=R1_EVENT_STREAM_READ_ONLY\n'
PYTHON_BIN="${PFC_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then PYTHON_BIN="$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)"; fi
if [[ -n "$PYTHON_BIN" && -f "$TOOL_PROFILE" ]]; then
  "$PYTHON_BIN" - "$TOOL_PROFILE" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as fh: p=json.load(fh)
s=p.get("summary", {})
for k in ("probe_pass","field_blocked","not_found","probe_fail","target_ready"):
    print("TOOL_%s=%s" % (k.upper(), s.get(k, 0)))
PY
fi
