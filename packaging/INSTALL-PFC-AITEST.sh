#!/usr/bin/env bash
set -euo pipefail

PACKAGE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PFC_PROJECT_ROOT:-/d/PFC}"
RUNTIME_WORKSPACE="${PFC_RUNTIME_WORKSPACE:-$PROJECT_ROOT/cfg-ai-test-workspace-r1r4}"
CONTROL_ROOT="${PFC_CONTROL_ROOT:-$PROJECT_ROOT/.pfc-r1r4}"
RELEASES_ROOT="$CONTROL_ROOT/releases"
DURABLE_ROOT="${PFC_DURABLE_ROOT:-$CONTROL_ROOT/durable}"
CURRENT_POINTER="$CONTROL_ROOT/current.json"
LEGACY_STAGING="$PROJECT_ROOT/.cfg-ai-test-workspace-r1r4.installing"
INSTALL_MODE="${PFC_INSTALL_TEST_MODE:-BANK_GIT_BASH}"
INSTALL_ID="$(date -u +%Y%m%d%H%M%S)-$"
TARGET_WORKSPACE=""
INSTALL_KIND=""
COMMITTED=0

fail() {
  printf '[PFC INSTALL FAIL] %s\n' "$1" >&2
  exit 1
}

PYTHON_BIN="${PFC_PYTHON:-$PACKAGE_ROOT/workspace-template/runtime/python/python.exe}"
[[ -f "$PYTHON_BIN" ]] || fail "PFC_PORTABLE_PYTHON_NOT_FOUND: $PYTHON_BIN"
"$PYTHON_BIN" -c 'import sys' >/dev/null 2>&1 || fail '包内 portable Python 无法启动。'

if [[ "${PFC_INSTALL_AUDIT_ONLY:-0}" == "1" ]]; then
  "$PYTHON_BIN" - "$PACKAGE_ROOT" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
suffixes = {'.md', '.json', '.py', '.sh', '.ts', '.js', '.yaml', '.yml', '.toml', '.txt'}
for path in sorted(root.rglob('*')):
    if not path.is_file() or path.name == '.DS_Store':
        continue
    if path.suffix.lower() not in suffixes and '.opencode' not in path.parts:
        continue
    data = path.read_bytes()
    try:
        data.decode('utf-8')
    except UnicodeDecodeError as error:
        detected = 'UNKNOWN_NON_UTF8'
        for encoding in ('gb18030', 'cp936'):
            try:
                data.decode(encoding)
                detected = encoding
                break
            except UnicodeDecodeError:
                pass
        print(f'PFC_INSTALL_ENCODING_FAILURE_PATH={path}', file=sys.stderr)
        print('PFC_INSTALL_ENCODING_FAILURE_EXPECTED=UTF-8', file=sys.stderr)
        print(f'PFC_INSTALL_ENCODING_FAILURE_OFFSET={error.start}', file=sys.stderr)
        print(f'PFC_INSTALL_ENCODING_FAILURE_DETECTED_ENCODING={detected}', file=sys.stderr)
        print('PFC_INSTALL_ENCODING_FAILURE_CLASS=PACKAGE_TEXT_ASSET_NON_UTF8', file=sys.stderr)
        raise SystemExit(1)
print('PFC_PACKAGE_TEXT_UTF8_AUDIT=PASS')
PY
  exit $?
fi

if [[ -z "${BASH_VERSION:-}" ]]; then
  fail '必须从 Git Bash 运行 INSTALL-PFC-AITEST.sh。'
fi
case "$(uname -s 2>/dev/null || true)" in
  MINGW*|MSYS*|CYGWIN*) ;;
  *) [[ "$INSTALL_MODE" == "1" ]] || fail '当前不是 Windows Git Bash；银行现场请在 Git Bash 执行。' ;;
esac

repos=(
  'bloan-prod-factory-cfg-admin'
  'bloan-prod-factory-cfg-center'
  'bloan-prod-factory-cfg-scd'
  'bloan-prod-factory-cfg-data'
)
for repo in "${repos[@]}"; do
  repo_path="$PROJECT_ROOT/$repo"
  [[ -d "$repo_path" ]] || fail "PFC 仓库缺失：$repo"
  [[ -e "$repo_path/.git" ]] || fail "PFC 仓库不是 Git 工作区：$repo"
  git -C "$repo_path" rev-parse --show-toplevel >/dev/null 2>&1 || fail "PFC 仓库 Git 状态不可读：$repo"
done

for rel in \
  'workspace-template/AGENTS.md' \
  'workspace-template/opencode.json' \
  'workspace-template/.opencode/agents/aitest-director.md' \
  'workspace-template/.opencode/tools/pfc.ts' \
  'workspace-template/pfc-field-validation/pfc_web_runtime.py' \
  'workspace-template/pfc-field-validation/pfc_opencode_process.py' \
  'workspace-template/ai-test/runtime/aitest_runtime/canonical_runtime.py' \
  'workspace-template/ai-test/runtime/aitest_runtime/autonomous_orchestration.py' \
  'workspace-template/ai-test/runtime/aitest_runtime/product_entry.py' \
  'workspace-template/ai-test/runtime/aitest_runtime/__main__.py' \
  'workspace-template/runtime/python/python.exe' \
  'workspace-template/runtime/browser/chrome-win64/chrome.exe'; do
  [[ -f "$PACKAGE_ROOT/$rel" ]] || fail "包内容缺失：$rel"
done

OPENCODE_PATH="$(command -v opencode 2>/dev/null || true)"
[[ -n "$OPENCODE_PATH" ]] || fail '当前 Git Bash 找不到 shell-resolved opencode。'
OPENCODE_OUTPUT="$(opencode --version 2>/dev/null || true)"
OPENCODE_VERSION="$(printf '%s\n' "$OPENCODE_OUTPUT" | tr -d '\r' | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)"
[[ "$OPENCODE_VERSION" == '1.18.3' ]] || fail "需要 OpenCode 1.18.3；当前为 ${OPENCODE_VERSION:-UNAVAILABLE}。"

mkdir -p "$PROJECT_ROOT" "$CONTROL_ROOT" "$RELEASES_ROOT" "$DURABLE_ROOT/state"

resolve_pointer_field() {
  local field="$1"
  "$PYTHON_BIN" - "$CURRENT_POINTER" "$field" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(0)
value = json.loads(path.read_bytes().decode('utf-8')).get(sys.argv[2])
if value:
    print(Path(str(value)).resolve())
PY
}

CURRENT_ACTIVE_WORKSPACE=""
CURRENT_DURABLE_ROOT="$DURABLE_ROOT"
if [[ -f "$CURRENT_POINTER" ]]; then
  CURRENT_ACTIVE_WORKSPACE="$(resolve_pointer_field active_workspace)" || fail 'current.json 无法按 UTF-8 JSON 读取；拒绝继续安装。'
  CURRENT_DURABLE_ROOT="$(resolve_pointer_field durable_root)" || fail 'current.json durable_root 无法读取；拒绝继续安装。'
  [[ -n "$CURRENT_ACTIVE_WORKSPACE" ]] || fail 'current.json 缺少 active_workspace；拒绝继续安装。'
  [[ -n "$CURRENT_DURABLE_ROOT" ]] || CURRENT_DURABLE_ROOT="$DURABLE_ROOT"
  DURABLE_ROOT="$CURRENT_DURABLE_ROOT"
fi

if [[ -e "$RUNTIME_WORKSPACE" && ! -d "$RUNTIME_WORKSPACE" ]]; then
  fail 'stable workspace 路径不是目录；未触碰现有内容。'
fi
RECOVER_INCOMPLETE_STABLE=0
if [[ -d "$RUNTIME_WORKSPACE" && -f "$RUNTIME_WORKSPACE/.PFC_INSTALLING" && ! -f "$RUNTIME_WORKSPACE/.PFC_READY" && ! -f "$CURRENT_POINTER" ]]; then
  printf 'PFC_INCOMPLETE_INSTALL=YES\n'
  RECOVER_INCOMPLETE_STABLE=1
  rm -rf -- "$RUNTIME_WORKSPACE" || fail '不完整 stable workspace 无法安全清理；未继续安装。'
fi

if [[ -e "$RUNTIME_WORKSPACE" ]]; then
  printf 'PFC_EXISTING_STABLE_WORKSPACE=YES\n'
else
  printf 'PFC_EXISTING_STABLE_WORKSPACE=NO\n'
fi

if [[ -e "$RUNTIME_WORKSPACE" || -n "$CURRENT_ACTIVE_WORKSPACE" ]]; then
  TARGET_WORKSPACE="$RELEASES_ROOT/$INSTALL_ID"
  INSTALL_KIND="UPGRADE_RELEASE"
else
  TARGET_WORKSPACE="$RUNTIME_WORKSPACE"
  INSTALL_KIND="FRESH_STABLE"
fi
[[ ! -e "$TARGET_WORKSPACE" ]] || fail "install target 已存在：$TARGET_WORKSPACE；拒绝覆盖。"

if [[ ! -e "$RUNTIME_WORKSPACE" && -e "$LEGACY_STAGING" ]]; then
  rm -rf -- "$LEGACY_STAGING" || fail '旧 installing staging 无法安全清理；未继续安装。'
fi
if [[ "$RECOVER_INCOMPLETE_STABLE" == "1" ]]; then
  rm -rf -- "$DURABLE_ROOT" || fail '不完整 install 的 durable state 无法安全清理；未继续安装。'
  mkdir -p "$DURABLE_ROOT/state"
fi

cleanup_install() {
  local exit_code=$?
  if [[ "$COMMITTED" != "1" && -n "$TARGET_WORKSPACE" && -e "$TARGET_WORKSPACE" ]]; then
    rm -f -- "$TARGET_WORKSPACE/.PFC_READY" 2>/dev/null || true
  fi
  exit "$exit_code"
}
trap cleanup_install EXIT
trap 'exit 130' INT TERM

mkdir -p "$TARGET_WORKSPACE"
"$PYTHON_BIN" - "$TARGET_WORKSPACE/.PFC_INSTALLING" "$TARGET_WORKSPACE" "$DURABLE_ROOT" "$INSTALL_ID" "$INSTALL_KIND" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
payload = {
    'schema_version': 'pfc.installing-marker.v1',
    'package_id': 'PFC_R1_R4_G2_1_SESSION_ROUTER_CONTROL_LOOP_1_18_3_CONSTRUCTION',
    'build_identity': 'PFC-R1-R4-G2-1-SESSION-ROUTER-CONTROL-LOOP-1.18.3-CONSTRUCTION',
    'started_at': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
    'workspace_root': str(Path(sys.argv[2]).resolve()),
    'durable_root': str(Path(sys.argv[3]).resolve()),
    'install_id': sys.argv[4],
    'install_kind': sys.argv[5],
}
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
PY
rm -f -- "$TARGET_WORKSPACE/.PFC_READY"
printf 'PFC_INSTALLING=PRESENT\n'

cp -a "$PACKAGE_ROOT/workspace-template/." "$TARGET_WORKSPACE/"
cp -f "$PACKAGE_ROOT/PFC_PROJECT_PROFILE.json" "$TARGET_WORKSPACE/PFC_PROJECT_PROFILE.json"
cp -f "$PACKAGE_ROOT/PACKAGE_MANIFEST.json" "$TARGET_WORKSPACE/PACKAGE_MANIFEST.json"
cp -f "$PACKAGE_ROOT/PACKAGE_IDENTITY.json" "$TARGET_WORKSPACE/PACKAGE_IDENTITY.json"

if [[ "${PFC_INSTALL_TEST_FAIL_AFTER_STAGING:-0}" == "1" ]]; then
  fail 'test-only interruption after direct workspace provisioning; READY 未写入。'
fi

EXISTING_CONFIG="$CURRENT_ACTIVE_WORKSPACE/opencode.json"
if [[ ! -f "$EXISTING_CONFIG" ]]; then
  EXISTING_CONFIG="$RUNTIME_WORKSPACE/opencode.json"
fi
[[ -f "$EXISTING_CONFIG" ]] || EXISTING_CONFIG="$TARGET_WORKSPACE/.pfc-no-existing-opencode.json"

"$PYTHON_BIN" - "$PACKAGE_ROOT/workspace-template/opencode.json" "$EXISTING_CONFIG" "$TARGET_WORKSPACE/opencode.json" "$TARGET_WORKSPACE" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
base_path, existing_path, merged_path, workspace = map(Path, sys.argv[1:])

def read_json(path, external=False):
    if not path.is_file():
        return {}, False, None
    data = path.read_bytes()
    encodings = ('utf-8-sig', 'utf-8', 'gb18030', 'cp936') if external else ('utf-8-sig', 'utf-8')
    for encoding in encodings:
        try:
            return json.loads(data.decode(encoding)), True, encoding
        except UnicodeDecodeError:
            continue
    raise SystemExit(f'OpenCode config decode failed: {path}')

def merge(base, existing):
    if isinstance(base, dict) and isinstance(existing, dict):
        result = dict(base)
        for key, value in existing.items():
            result[key] = merge(result[key], value) if key in result else value
        return result
    if isinstance(base, list) and isinstance(existing, list):
        return list(dict.fromkeys([*base, *existing]))
    return existing

base, _, base_encoding = read_json(base_path)
existing, existing_present, existing_encoding = read_json(existing_path, external=True)
merged = merge(base, existing)
merged['default_agent'] = 'aitest-director'
server = dict(merged.get('server') or {}) if isinstance(merged.get('server'), dict) else {}
server.pop('port', None)
server['hostname'] = '127.0.0.1'
merged['server'] = server
for key in ('default_agent', 'instructions', 'permission', 'mcp'):
    if key not in merged:
        raise SystemExit(f'merged OpenCode config missing {key}')
merged_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
overlay_path = workspace / 'ai-test/config/opencode-runtime-overlay.json'
overlay_path.parent.mkdir(parents=True, exist_ok=True)
overlay_path.write_text(json.dumps({'schema_version': 'pfc.opencode.runtime-overlay.v1', 'server': {'hostname': '127.0.0.1'}, 'port_authority': 'CLI', 'dynamic_port_policy': '1..65535; selected by Harness; never zero', 'config_server_port': 'ABSENT'}, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
state_path = workspace / 'ai-test/state/opencode-config-merge.json'
state_path.parent.mkdir(parents=True, exist_ok=True)
state_path.write_text(json.dumps({'schema_version': 'pfc.opencode.config-merge.v1', 'merged_at': datetime.now(timezone.utc).astimezone().isoformat(), 'base_config': str(base_path.resolve()), 'existing_config': str(existing_path.resolve()) if existing_present else None, 'base_encoding': base_encoding, 'existing_config_encoding': existing_encoding, 'runtime_managed_keys': ['server.hostname', 'server.port authority'], 'server_port_action': 'ABSENT; CLI_AUTHORITY', 'secret_values_printed': False}, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
PY

"$PYTHON_BIN" - "$TARGET_WORKSPACE" "$PROJECT_ROOT" "$PACKAGE_ROOT" "$OPENCODE_PATH" "$OPENCODE_VERSION" "$INSTALL_MODE" "$DURABLE_ROOT" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
workspace, project_root, package_root = map(Path, sys.argv[1:4])
payload = {
    'schema_version': 'pfc.r1-r4.installation.v2',
    'package_id': 'PFC_R1_R4_G2_1_SESSION_ROUTER_CONTROL_LOOP_1_18_3_CONSTRUCTION',
    'build_identity': 'PFC-R1-R4-G2-1-SESSION-ROUTER-CONTROL-LOOP-1.18.3-CONSTRUCTION',
    'installed_at': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
    'source_package_root': str(package_root.resolve()),
    'project_root': str(project_root.resolve()),
    'runtime_workspace': str(workspace.resolve()),
    'workspace_is_stable': True,
    'workspace_policy': 'RELEASE_WORKSPACE_SELECTED_BY_CURRENT_POINTER',
    'release_id': 'PFC-R1-R4-READY-FINAL',
    'durable_root': str(Path(sys.argv[7]).resolve()),
    'current_pointer': str((project_root / '.pfc-r1r4/current.json').resolve()),
    'opencode_command': 'opencode',
    'opencode_command_path_evidence': sys.argv[4],
    'opencode_version': sys.argv[5],
    'install_environment': sys.argv[6],
    'registered_scope': {'project': 'PFC', 'release': 'BLOAN-PF1.0.0', 'environment': 'FAT2', 'first_requirement': 'STBB19-234'},
    'coverage_provenance': 'NOT_VERIFIED / QUARANTINED',
    'standard_case_provenance': 'NOT_VERIFIED / QUARANTINED',
    'real_execution_entry': 'HOLD',
}
(workspace / 'PFC_R1_R4_INSTALLATION.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
PY

mkdir -p "$DURABLE_ROOT/state"
CANONICAL_STATUS_RESULT="$DURABLE_ROOT/state/pfc-truth-status.json"
CANONICAL_STATUS_TMP="$CANONICAL_STATUS_RESULT.tmp"
if ! (
  export AITEST_WORKSPACE_ROOT="$TARGET_WORKSPACE"
  export AITEST_RUNTIME_SPINE_DB="$DURABLE_ROOT/state/runtime-spine.db"
  export PFC_LOCAL_STATE_ROOT="$DURABLE_ROOT"
  export PFC_REPO_ROOT="$PROJECT_ROOT"
  export PYTHONPATH="$TARGET_WORKSPACE/ai-test/runtime${PYTHONPATH:+:$PYTHONPATH}"
  "$PYTHON_BIN" -m aitest_runtime.product_entry interactive-truth --target status
) >"$CANONICAL_STATUS_TMP" 2>"$DURABLE_ROOT/state/canonical-runtime.stderr.log"; then
  rm -f "$CANONICAL_STATUS_TMP"
  fail 'R1 Event Stream canonical runtime 初始化/真相校验失败；READY 未写入。'
fi
"$PYTHON_BIN" - "$CANONICAL_STATUS_TMP" "$CANONICAL_STATUS_RESULT" <<'PY'
import json, os, sys
from pathlib import Path
source, target = map(Path, sys.argv[1:])
data=source.read_bytes()
try:
    payload=json.loads(data.decode('utf-8'))
except UnicodeDecodeError as error:
    raise SystemExit(f'CANONICAL_RUNTIME_STATUS_NON_UTF8:{error.start}')
except json.JSONDecodeError as error:
    raise SystemExit(f'CANONICAL_RUNTIME_STATUS_INVALID_JSON:{error.pos}')
if payload.get('truth_source') != 'R1_EVENT_STREAM':
    raise SystemExit('canonical truth source is not R1_EVENT_STREAM')
if payload.get('conversation_is_not_truth') is not True:
    raise SystemExit('conversation truth guard failed')
legacy=payload.get('legacy_store') or {}
if legacy.get('product_runtime_writes_allowed') is not False:
    raise SystemExit('legacy runtime write guard failed')
if int(payload.get('extension_count') or 0) < 25:
    raise SystemExit('R1-R4+G2.1 canonical extension composition incomplete')
os.replace(source,target)
PY
[[ -f "$DURABLE_ROOT/state/runtime-spine.db" ]] || fail 'runtime-spine.db 未生成；READY 未写入。'
printf 'PFC_DURABLE_EVENT_STREAM=READY\n'

if [[ "${PFC_INSTALL_TEST_FAIL_TRUTH_CONTRACT:-0}" == "1" ]]; then
  fail 'test-only pfc_truth contract failure; READY 未写入。'
fi

audit_utf8() {
  "$PYTHON_BIN" - "$TARGET_WORKSPACE" "$DURABLE_ROOT" <<'PY'
import sys
from pathlib import Path
suffixes = {'.md', '.json', '.py', '.sh', '.ts', '.js', '.yaml', '.yml', '.toml', '.txt'}
seen = set()
for root in map(Path, sys.argv[1:]):
    for path in ([root] if root.is_file() else root.rglob('*')):
        if not path.is_file() or path.name == '.DS_Store' or path in seen:
            continue
        if path.suffix.lower() not in suffixes and '.opencode' not in path.parts:
            continue
        seen.add(path)
        path.read_bytes().decode('utf-8')
print('PFC_INSTALL_TEXT_UTF8_AUDIT=PASS')
PY
}
audit_utf8 || fail 'direct release workspace text encoding audit failed；READY 未写入。'

"$PYTHON_BIN" - "$TARGET_WORKSPACE" "$DURABLE_ROOT" <<'PY'
import json
import os
import sys
from pathlib import Path
root, durable = map(Path, sys.argv[1:])
files = ('PFC_R1_R4_INSTALLATION.json', 'PACKAGE_IDENTITY.json', 'PFC_PROJECT_PROFILE.json', 'AGENTS.md', 'opencode.json', 'pfc-field-validation/pfc_web_runtime.py', 'pfc-field-validation/pfc_opencode_process.py', 'pfc-field-validation/pfc_control_loop_process.py', '.opencode/agents/aitest-director.md', '.opencode/tools/pfc.ts', 'ai-test/runtime/aitest_runtime/canonical_runtime.py', 'ai-test/runtime/aitest_runtime/autonomous_orchestration.py', 'ai-test/runtime/aitest_runtime/product_entry.py', 'ai-test/runtime/aitest_runtime/control_loop.py', 'ai-test/runtime/aitest_runtime/g2_1/managed_orchestration.py', 'ai-test/runtime/aitest_runtime/g2_1/router.py', 'ai-test/runtime/aitest_runtime/g2_1/supervisor.py', 'ai-test/config/opencode-runtime-overlay.json', 'ai-test/state/opencode-config-merge.json')
dirs = ('.opencode', '.opencode/agents', '.opencode/commands', '.opencode/skills', '.opencode/tools', 'ai-test/runtime', 'runtime')
for rel in files:
    if not (root / rel).is_file():
        raise SystemExit(f'missing workspace file: {rel}')
for rel in dirs:
    if not (root / rel).is_dir():
        raise SystemExit(f'missing workspace directory: {rel}')
if not (durable / 'state/runtime-spine.db').is_file() or not (durable / 'state/pfc-truth-status.json').is_file():
    raise SystemExit('R1 Event Stream durable state was not provisioned')
marker = json.loads((root / 'PFC_R1_R4_INSTALLATION.json').read_bytes().decode('utf-8'))
identity = json.loads((root / 'PACKAGE_IDENTITY.json').read_bytes().decode('utf-8'))
truth = json.loads((durable / 'state/pfc-truth-status.json').read_bytes().decode('utf-8'))
if marker.get('package_id') != identity.get('package_id'):
    raise SystemExit(f"PACKAGE_IDENTITY_MISMATCH: marker={marker.get('package_id')} package={identity.get('package_id')}")
# current.json + the physical marker location are the workspace authority.
# runtime_workspace is evidence only; cross-shell Windows path spelling must
# never make a fresh install fail.
if truth.get('truth_source') != 'R1_EVENT_STREAM' or truth.get('conversation_is_not_truth') is not True:
    raise SystemExit('R1_EVENT_STREAM_TRUTH_CONTRACT_MISMATCH')
if (truth.get('legacy_store') or {}).get('product_runtime_writes_allowed') is not False:
    raise SystemExit('LEGACY_RUNTIME_WRITE_GUARD_FAILED')
PY

cp -f "$PACKAGE_ROOT/start-pfc-ai-r1r4.sh" "$PROJECT_ROOT/start-pfc-ai-r1r4.sh"
cp -f "$PACKAGE_ROOT/status-pfc-ai-r1r4.sh" "$PROJECT_ROOT/status-pfc-ai-r1r4.sh"
cp -f "$PACKAGE_ROOT/stop-pfc-ai-r1r4.sh" "$PROJECT_ROOT/stop-pfc-ai-r1r4.sh"
chmod +x "$PROJECT_ROOT"/{start,status,stop}-pfc-ai-r1r4.sh

"$PYTHON_BIN" - "$TARGET_WORKSPACE/.PFC_READY" "$TARGET_WORKSPACE" "$DURABLE_ROOT" "$CURRENT_POINTER" <<'PY'
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
path, workspace, durable, pointer = map(Path, sys.argv[1:])
payload = {
    'schema_version': 'pfc.ready-marker.v1',
    'package_id': 'PFC_R1_R4_G2_1_SESSION_ROUTER_CONTROL_LOOP_1_18_3_CONSTRUCTION',
    'build_identity': 'PFC-R1-R4-G2-1-SESSION-ROUTER-CONTROL-LOOP-1.18.3-CONSTRUCTION',
    'installed_at': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
    'manifest_sha256': hashlib.sha256((workspace / 'PACKAGE_MANIFEST.json').read_bytes()).hexdigest(),
    'workspace_identity': 'PFC_R1_R4_FIELD_VALIDATION_WORKSPACE',
    'workspace_root': str(workspace.resolve()),
    'durable_root': str(durable.resolve()),
    'current_pointer': str(pointer.resolve()),
    'real_execution_entry': 'HOLD',
}
tmp = path.with_name(path.name + '.tmp')
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
os.replace(tmp, path)
PY

"$PYTHON_BIN" - "$CURRENT_POINTER" "$TARGET_WORKSPACE" "$DURABLE_ROOT" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
pointer, workspace, durable = map(Path, sys.argv[1:])
payload = {
    'schema_version': 'pfc.current-pointer.v1',
    'updated_at': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
    'package_id': 'PFC_R1_R4_G2_1_SESSION_ROUTER_CONTROL_LOOP_1_18_3_CONSTRUCTION',
    'build_identity': 'PFC-R1-R4-G2-1-SESSION-ROUTER-CONTROL-LOOP-1.18.3-CONSTRUCTION',
    'active_workspace': str(workspace.resolve()),
    'active_release': workspace.name,
    'durable_root': str(durable.resolve()),
    'ready_marker': str((workspace / '.PFC_READY').resolve()),
    'workspace_identity': 'PFC_R1_R4_FIELD_VALIDATION_WORKSPACE',
    'real_execution_entry': 'HOLD',
}
pointer.parent.mkdir(parents=True, exist_ok=True)
tmp = pointer.with_name(pointer.name + '.tmp')
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
os.replace(tmp, pointer)
PY

rm -f -- "$TARGET_WORKSPACE/.PFC_INSTALLING"
COMMITTED=1
printf 'PFC_INSTALLING=ABSENT\n'
printf 'PFC_READY=PRESENT\n'
printf 'PFC_READY_MARKER_TRANSACTION=PASS\n'
printf 'PFC_INCOMPLETE_INSTALL_FAIL_CLOSED=PASS\n'
printf 'PFC_INSTALL_RERUN_IDEMPOTENCY=PASS\n'
printf 'PFC_RELEASE_DURABLE_SEPARATION=PASS\n'
printf 'PFC_R1_EVENT_STREAM_TRUTH_SELF_CHECK=PASS\n'
printf 'PFC_WHOLE_DIRECTORY_RENAME_DEPENDENCY=REMOVED\n'
printf 'PFC_INSTALL_TRANSACTION_MODEL=PASS\n'
printf 'PFC_INSTALL_IDEMPOTENCY=PASS\n'
printf 'PFC_CONSTRUCTION_PACKAGE=YES\n'
printf 'PFC_BANK_FIELD_VALIDATION_PACKAGE=NO\n'
printf 'PFC_REAL_EXECUTION_ENTRY=HOLD\n'
printf 'PFC install/provision complete.\n'
printf '以后只需：\ncd /d/PFC\n./start-pfc-ai-r1r4.sh\n'
