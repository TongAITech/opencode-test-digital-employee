#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd -W 2>/dev/null || cd "$(dirname "$0")/../.." && pwd)"
PY="$ROOT/workspace-template/runtime/python/python.exe"
[[ -f "$PY" ]] || { echo "[RC7] package-local Python missing: $PY" >&2; exit 2; }
export PFC_AITEST_HOME="$ROOT"
export PFC_PYTHON="$PY"
export PFC_CODEGRAPH_BIN="$ROOT/workspace-template/runtime/code-intelligence/codegraph/codegraph-server-win32-x64.exe"
export PFC_CHROMIUM_BIN="$ROOT/workspace-template/runtime/browser/chrome-win64/chrome.exe"
export PFC_JAVA_BIN="$ROOT/workspace-template/runtime/java/bin/java.exe"
export PFC_MAVEN_BIN="$ROOT/workspace-template/runtime/maven/bin/mvn.cmd"
export PFC_K6_BIN="$ROOT/workspace-template/runtime/k6/k6.exe"
PATH_ADD="$ROOT/workspace-template/runtime/node:$ROOT/workspace-template/runtime/maven/bin:$ROOT/workspace-template/runtime/java/bin:$ROOT/workspace-template/runtime/allure/bin:$ROOT/workspace-template/runtime/k6"
BSK="$(find "$ROOT/workspace-template/runtime/browser/browserskill" -name bsk.exe -print -quit 2>/dev/null || true)"
RG="$(find "$ROOT/workspace-template/runtime/ripgrep" -name rg.exe -print -quit 2>/dev/null || true)"
[[ -n "$BSK" ]] && PATH_ADD="$(dirname "$BSK"):$PATH_ADD"
[[ -n "$RG" ]] && PATH_ADD="$(dirname "$RG"):$PATH_ADD"
export PATH="$PATH_ADD:$PATH"
if [[ "${PFC_RC7_SKIP_QUALIFY:-0}" != "1" ]]; then
  "$PY" -m rc7_release.final_unified_qualification --home "$ROOT" --require-pass
fi
mkdir -p "$ROOT/state"
"$PY" -m rc7_release.dsh_plugins --home "$ROOT" --profile web --output "$ROOT/state/dsh-plugin-install.json"
if ! command -v dsh >/dev/null 2>&1; then
  echo "[RC7] Bank DSH host is not on PATH. Bind the bank DSH host and rerun ./packaging/rc7/AITEST.sh." >&2
  exit 3
fi
"$PY" -m rc7_release.dsh --output "$ROOT/state/rc7-dsh.patch.yml" --home "$ROOT" --python "$PY"
exec dsh --profile web --patch "$ROOT/state/rc7-dsh.patch.yml"
