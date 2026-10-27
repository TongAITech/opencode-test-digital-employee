#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -d "$SCRIPT_DIR/rc7_release" ]]; then
  ROOT="$SCRIPT_DIR"
elif [[ -d "$SCRIPT_DIR/../../rc7_release" ]]; then
  ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
else
  echo "RC7.1_START_ROOT_NOT_FOUND: $SCRIPT_DIR" >&2
  exit 21
fi

PROFILE="${PFC_RC7_DSH_PROFILE:-rc7-bank-rc71-field}"
DSH_HOME_EFFECTIVE="${DSH_HOME:-${HOME:-}/.dsh}"
if command -v cygpath >/dev/null 2>&1 && [[ "$DSH_HOME_EFFECTIVE" =~ ^[A-Za-z]:[\\/].* ]]; then
  DSH_HOME_EFFECTIVE="$(cygpath -u "$DSH_HOME_EFFECTIVE")"
fi
PROFILE_DIR="$DSH_HOME_EFFECTIVE/profiles/$PROFILE"
PATCH="$ROOT/state/rc7-dsh.patch.yml"
FIELD_POLICY="$ROOT/rc7_release/rc71_field_tool_policy.ts"

if [[ -f "$ROOT/workspace-template/runtime/python/python.exe" ]]; then
  PY="$ROOT/workspace-template/runtime/python/python.exe"
elif command -v python.exe >/dev/null 2>&1; then
  PY="$(command -v python.exe)"
elif command -v python >/dev/null 2>&1; then
  PY="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "RC7.1_START_PYTHON_NOT_FOUND" >&2
  exit 22
fi

if [[ -n "${PFC_DSH_BIN:-}" ]]; then
  DSH="$PFC_DSH_BIN"
elif command -v dsh >/dev/null 2>&1; then
  DSH="$(command -v dsh)"
elif command -v dsh.cmd >/dev/null 2>&1; then
  DSH="$(command -v dsh.cmd)"
else
  echo "RC7.1_START_DSH_NOT_FOUND: set PFC_DSH_BIN or put dsh on PATH" >&2
  exit 23
fi

if [[ ! -d "$PROFILE_DIR" ]]; then
  echo "RC7.1_START_PROFILE_NOT_FOUND: $PROFILE_DIR" >&2
  echo "Expected existing bank field profile: $PROFILE" >&2
  echo "This launcher will not clone, install, or modify the protected web profile." >&2
  exit 24
fi
if [[ ! -f "$FIELD_POLICY" ]]; then
  echo "RC7.1_START_FIELD_POLICY_MISSING: $FIELD_POLICY" >&2
  exit 25
fi

mkdir -p "$ROOT/state" "$ROOT/runtime-state"

# A Field coordinator must never start with stale Worker identity from a reused
# shell. Worker launchers project fresh signed-lease identity into their child.
unset PFC_RC7_DSH_ALLOWED_TOOLS || true
unset PFC_RC7_MCP_MISSION_ID || true
unset PFC_RC7_MCP_TASK_ID || true
unset PFC_RC7_MCP_WORKER_ID || true
unset PFC_RC7_MCP_LEASE_ID || true
unset PFC_RC7_MCP_SCOPE_REF || true

export PFC_RC7_DSH_SESSION_MODE="INTERACTIVE_CONTROL"
export PFC_AITEST_HOME="$ROOT"
export PFC_AITEST_STATE_DIR="${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

# Rebuild every launch. The patch contains absolute package-local paths, so a
# package copied to another drive/directory remains relocatable without manual
# editing. No npm/pnpm/pip/install/provisioning is performed here.
"$PY" -m rc7_release.dsh \
  --output "$PATCH" \
  --home "$ROOT" \
  --python "$PY" \
  --require-default-enhancements >/dev/null

cp -f "$FIELD_POLICY" "$ROOT/state/rc7-tool-policy.ts"

# The standard generator intentionally points at the strict Worker MCP server.
# Field startup switches only this generated runtime patch to the registry-bound
# coordinator wrapper. Worker calls detected by lease projection still delegate
# to the original strict authority path.
"$PY" - "$PATCH" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
text = p.read_text(encoding="utf-8")
old = "rc7_release.mcp_server_authorized"
new = "rc7_release.mcp_server_field_validation"
if old not in text and new not in text:
    raise SystemExit("RC7.1_START_MCP_ENTRY_NOT_FOUND")
with p.open("w", encoding="utf-8", newline="\n") as handle:
    handle.write(text.replace(old, new))
PY

cat > "$ROOT/state/rc7.1-field-startup.json" <<EOF
{
  "schema": "pfc.aitest.rc7.1.field-startup.v1",
  "status": "READY_TO_LAUNCH",
  "auth_mode": "INTERACTIVE_CONTROL_REGISTRY_BOUND",
  "worker_mode": "LEASE_BOUND_WORKER_FAIL_CLOSED",
  "profile": "$PROFILE",
  "patch": "state/rc7-dsh.patch.yml",
  "startup_entry": "start-rc7.1.sh"
}
EOF

echo "[RC7.1] root=$ROOT"
echo "[RC7.1] profile=$PROFILE"
echo "[RC7.1] auth=INTERACTIVE_CONTROL (live registry, exact names, no wildcard)"
echo "[RC7.1] worker=LEASE_BOUND_WORKER (signed lease, fail-closed)"
echo "[RC7.1] launching DSH..."

exec "$DSH" --profile "$PROFILE" --patch "$PATCH" "$@"
