#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ONLY=0
if [[ "${1:-}" == "--package-only" ]]; then PACKAGE_ONLY=1; fi

PYTHON_BIN="${PFC_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: PYTHON_NOT_FOUND" >&2
  exit 10
fi
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

if [[ -f "$ROOT/PACKAGE_MANIFEST.json" ]]; then
  "$PYTHON_BIN" -m rc6_release.package verify --package-root "$ROOT" >/dev/null
fi
"$PYTHON_BIN" - <<'PY'
from rc6_release.mcp_server import handle
r = handle({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}})
assert r and r["result"]["serverInfo"]["name"] == "pfc-aitest-rc6"
t = handle({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
names = {x["name"] for x in t["result"]["tools"]}
required = {
    "runtime_status", "mission_create", "mission_status", "mission_checkpoint",
    "worker_issue", "worker_rotate", "lease_issue", "tool_authorize",
    "artifact_record", "truth_inventory", "truth_query",
    "reality_list", "reality_get", "reality_upsert", "reality_reconcile", "target_build",
    "capability_discover", "capability_mark_executable", "capability_register",
    "capability_bind_worker", "capability_record_probe", "capability_target_ready",
    "capability_admit", "capability_record_call",
}
missing = sorted(required - names)
assert not missing, "missing governed MCP tools: " + ",".join(missing)
PY

mkdir -p "$ROOT/runtime-state"
"$PYTHON_BIN" -m rc6_release.dsh --output "$ROOT/runtime-state/rc6.cordis.yml" --home "$ROOT" >/dev/null

grep -q "@deepseek-ai/dsh-mcp-client" "$ROOT/runtime-state/rc6.cordis.yml"
grep -q "serverName: pfc_aitest_rc6" "$ROOT/runtime-state/rc6.cordis.yml"
[[ -f "$ROOT/.dsh/skills/pfc-full-chain-test/SKILL.md" ]]

if [[ "$PACKAGE_ONLY" -eq 0 ]]; then
  DSH_BIN="${PFC_DSH_BIN:-}"
  if [[ -z "$DSH_BIN" ]]; then DSH_BIN="$(command -v dsh 2>/dev/null || true)"; fi
  if [[ -z "$DSH_BIN" ]]; then
    echo "ERROR: DSH_NOT_FOUND" >&2
    exit 11
  fi
  "$DSH_BIN" --profile headless --help >/dev/null
  "$DSH_BIN" --profile web --patch "$ROOT/runtime-state/rc6.cordis.yml" --dump-config >/dev/null
fi

echo "RC6_VERIFY=PASS"
echo "RELEASE_STATUS=$(cat "$ROOT/RELEASE_STATUS" 2>/dev/null || echo SOURCE_TREE)"
