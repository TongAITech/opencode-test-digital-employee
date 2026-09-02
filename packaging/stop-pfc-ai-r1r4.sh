#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_WORKSPACE="${PFC_RUNTIME_WORKSPACE:-$PROJECT_ROOT/cfg-ai-test-workspace-r1r4}"
CONTROL_ROOT="${PFC_CONTROL_ROOT:-$PROJECT_ROOT/.pfc-r1r4}"
CURRENT_POINTER="$CONTROL_ROOT/current.json"
EXPECTED_PACKAGE_ID='PFC_R1_R4_G2_1_SESSION_ROUTER_CONTROL_LOOP_1_18_3_CONSTRUCTION'
EXPECTED_OPENCODE_VERSION='1.18.3'

fail() { printf '[PFC STOP FAIL] %s\n' "$1" >&2; exit 1; }

# Bank package policy: portable Python only.  System Python is never a runtime fallback.
BOOTSTRAP_PYTHON="${PFC_PYTHON:-$RUNTIME_WORKSPACE/runtime/python/python.exe}"
[[ -f "$BOOTSTRAP_PYTHON" ]] || fail "PFC_PORTABLE_PYTHON_NOT_FOUND: $BOOTSTRAP_PYTHON"
"$BOOTSTRAP_PYTHON" -c 'import sys' >/dev/null 2>&1 || fail 'portable Python cannot execute'
PYTHON_BIN="$BOOTSTRAP_PYTHON"

[[ -f "$CURRENT_POINTER" ]] || fail 'current.json 缺失；安装未提交。'
POINTER_VALUES="$("$PYTHON_BIN" - "$CURRENT_POINTER" <<'PY'
import json, sys
from pathlib import Path
payload=json.loads(Path(sys.argv[1]).read_bytes().decode('utf-8'))
for key in ('active_workspace','durable_root','package_id','workspace_identity'):
    if not payload.get(key): raise SystemExit(f'current.json missing {key}')
print(str(Path(payload['active_workspace']).resolve()))
print(str(Path(payload['durable_root']).resolve()))
print(payload['package_id'])
print(payload['workspace_identity'])
PY
)" || fail 'current.json 无法验证。'
WORKSPACE="$(printf '%s\n' "$POINTER_VALUES" | sed -n '1p')"
DURABLE_ROOT="$(printf '%s\n' "$POINTER_VALUES" | sed -n '2p')"
POINTER_PACKAGE_ID="$(printf '%s\n' "$POINTER_VALUES" | sed -n '3p')"
POINTER_WORKSPACE_ID="$(printf '%s\n' "$POINTER_VALUES" | sed -n '4p')"
[[ "$POINTER_PACKAGE_ID" == "$EXPECTED_PACKAGE_ID" ]] || fail 'current.json package identity 不匹配。'
[[ "$POINTER_WORKSPACE_ID" == 'PFC_R1_R4_FIELD_VALIDATION_WORKSPACE' ]] || fail 'current.json workspace identity 不匹配。'
[[ -d "$WORKSPACE" ]] || fail 'active workspace 不存在。'
[[ -f "$WORKSPACE/.PFC_READY" ]] || fail '.PFC_READY 缺失。'
[[ ! -e "$WORKSPACE/.PFC_INSTALLING" ]] || fail '.PFC_INSTALLING 仍存在。'

# Prefer the active workspace portable runtime after current pointer resolution.
[[ -f "$WORKSPACE/runtime/python/python.exe" ]] || fail "PFC_PORTABLE_PYTHON_NOT_FOUND: $WORKSPACE/runtime/python/python.exe"
PYTHON_BIN="$WORKSPACE/runtime/python/python.exe"

export AITEST_WORKSPACE_ROOT="$WORKSPACE"
export AITEST_RUNTIME_SPINE_DB="$DURABLE_ROOT/state/runtime-spine.db"
export PFC_LOCAL_STATE_ROOT="$DURABLE_ROOT"
export PFC_REPO_ROOT="$PROJECT_ROOT"
export PYTHONPATH="$WORKSPACE/ai-test/runtime${PYTHONPATH:+:$PYTHONPATH}"
cd "$WORKSPACE"

for required in   'AGENTS.md'   'opencode.json'   'PFC_PROJECT_PROFILE.json'   '.opencode/agents/aitest-director.md'   '.opencode/tools/pfc.ts'   'ai-test/runtime/aitest_runtime/canonical_runtime.py'   'ai-test/runtime/aitest_runtime/autonomous_orchestration.py'   'ai-test/runtime/aitest_runtime/product_entry.py'   'ai-test/runtime/aitest_runtime/control_loop.py'   'ai-test/runtime/aitest_runtime/g2_1/managed_orchestration.py'   'pfc-field-validation/pfc_web_runtime.py'   'pfc-field-validation/pfc_opencode_process.py'   'pfc-field-validation/pfc_control_loop_process.py'; do
  [[ -f "$WORKSPACE/$required" ]] || fail "缺少 $required"
done
[[ -f "$AITEST_RUNTIME_SPINE_DB" ]] || fail "R1 Event Stream 缺失：$AITEST_RUNTIME_SPINE_DB"

TRUTH_TMP="$DURABLE_ROOT/state/canonical-truth-stop.tmp.json"
"$PYTHON_BIN" -m aitest_runtime.product_entry interactive-truth --target status >"$TRUTH_TMP" || fail 'R1 Event Stream truth preflight failed'
"$PYTHON_BIN" - "$TRUTH_TMP" <<'PY'
import json, sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
if p.get('truth_source') != 'R1_EVENT_STREAM' or p.get('conversation_is_not_truth') is not True:
    raise SystemExit('canonical truth contract failed')
if (p.get('legacy_store') or {}).get('product_runtime_writes_allowed') is not False:
    raise SystemExit('legacy runtime write guard failed')
PY
rm -f "$TRUTH_TMP"

OPEN_VERSION_OUTPUT="$(opencode --version 2>/dev/null || true)"
OPEN_VERSION="$(printf '%s\n' "$OPEN_VERSION_OUTPUT" | tr -d '\r' | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)"
[[ "$OPEN_VERSION" == "$EXPECTED_OPENCODE_VERSION" ]] || fail "OpenCode 版本不符：要求 $EXPECTED_OPENCODE_VERSION；当前 ${OPEN_VERSION:-UNAVAILABLE}"
printf 'PFC_CANONICAL_RUNTIME=PASS\n'
printf 'PFC_RUNTIME_TRUTH=R1_EVENT_STREAM\n'
printf 'PFC_LEGACY_RUNTIME_WRITE=FORBIDDEN\n'
printf 'OpenCode=%s\n' "$OPEN_VERSION"

exec "$PYTHON_BIN" "$WORKSPACE/pfc-field-validation/pfc_web_runtime.py" stop "$@"
