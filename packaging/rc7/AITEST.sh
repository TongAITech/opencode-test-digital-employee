#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && { pwd -W 2>/dev/null || pwd; })"
PY="$ROOT/workspace-template/runtime/python/python.exe"
[[ -f "$PY" ]] || { echo "[RC7] package-local Python missing: $PY" >&2; exit 2; }

export PYTHONUTF8=1
export PFC_AITEST_HOME="$ROOT"
export PFC_AITEST_STATE_DIR="${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state}"
export PFC_PYTHON="$PY"
export PFC_CODEGRAPH_BIN="$ROOT/workspace-template/runtime/code-intelligence/codegraph/codegraph-server-win32-x64.exe"
export PFC_CHROMIUM_BIN="$ROOT/workspace-template/runtime/browser/chrome-win64/chrome.exe"
export PFC_JAVA_BIN="$ROOT/workspace-template/runtime/java/bin/java.exe"
export PFC_MAVEN_BIN="$ROOT/workspace-template/runtime/maven/bin/mvn.cmd"
export PFC_MAVEN_REPO="$ROOT/workspace-template/runtime/maven-repository"
export PFC_MAVEN_SETTINGS="$ROOT/packaging/rc7/maven-offline-settings.xml"
export MAVEN_ARGS="-o -s \"$PFC_MAVEN_SETTINGS\" -Dmaven.legacyLocalRepo=true -Dmaven.repo.local=\"$PFC_MAVEN_REPO\""
export PFC_K6_BIN="$ROOT/workspace-template/runtime/k6/k6.exe"
export PFC_RC7_DSH_BASE_PROFILE="${PFC_RC7_DSH_BASE_PROFILE:-web}"
export PFC_RC7_DSH_PROFILE="${PFC_RC7_DSH_PROFILE:-rc7-bank}"

PATH_ADD="$ROOT/workspace-template/runtime/node:$ROOT/workspace-template/runtime/maven/bin:$ROOT/workspace-template/runtime/java/bin:$ROOT/workspace-template/runtime/allure/bin:$ROOT/workspace-template/runtime/k6"
BSK="$(find "$ROOT/workspace-template/runtime/browser/browserskill" -name bsk.exe -print -quit 2>/dev/null || true)"
RG="$(find "$ROOT/workspace-template/runtime/ripgrep" -name rg.exe -print -quit 2>/dev/null || true)"
[[ -n "$BSK" ]] && PATH_ADD="$(dirname "$BSK"):$PATH_ADD"
[[ -n "$RG" ]] && PATH_ADD="$(dirname "$RG"):$PATH_ADD"
export PATH="$PATH_ADD:$PATH"

mkdir -p "$PFC_AITEST_STATE_DIR/r1" "$ROOT/state"

if [[ "${PFC_RC7_SKIP_QUALIFY:-0}" != "1" ]]; then
  "$PY" -m rc7_release.package verify --package-root "$ROOT"
fi

"$PY" -m rc7_release.dsh_plugins \
  --home "$ROOT" \
  --profile "$PFC_RC7_DSH_BASE_PROFILE" \
  --dry-run \
  --output "$ROOT/state/dsh-plugin-payload.json"

DSH_SHELL_BIN="$(command -v dsh 2>/dev/null || true)"
if [[ -z "$DSH_SHELL_BIN" ]]; then
  echo "[RC7] Bank DSH host is not on PATH. Bind the bank DSH host and rerun ./packaging/rc7/AITEST.sh." >&2
  exit 3
fi

DSH_NATIVE_BIN="$DSH_SHELL_BIN"
case "${DSH_NATIVE_BIN,,}" in
  *.cmd|*.exe) ;;
  *)
    [[ -f "${DSH_SHELL_BIN}.cmd" ]] && DSH_NATIVE_BIN="${DSH_SHELL_BIN}.cmd"
    [[ "$DSH_NATIVE_BIN" == "$DSH_SHELL_BIN" && -f "${DSH_SHELL_BIN}.exe" ]] && DSH_NATIVE_BIN="${DSH_SHELL_BIN}.exe"
    ;;
esac
if command -v cygpath >/dev/null 2>&1; then
  export PFC_RC7_DSH_BIN="$(cygpath -w "$DSH_NATIVE_BIN")"
else
  export PFC_RC7_DSH_BIN="$DSH_NATIVE_BIN"
fi

if [[ "$PFC_RC7_DSH_PROFILE" == "$PFC_RC7_DSH_BASE_PROFILE" ]]; then
  echo "[RC7] RC7 runtime profile must not be the protected bank profile: $PFC_RC7_DSH_BASE_PROFILE" >&2
  exit 4
fi

"$PY" -m rc7_release.dsh_runtime_profile \
  --home "$ROOT" \
  --base-profile "$PFC_RC7_DSH_BASE_PROFILE" \
  --runtime-profile "$PFC_RC7_DSH_PROFILE" \
  --output "$ROOT/state/rc7-dsh-runtime-profile.json" \
  --require-pass

"$PY" -m rc7_release.dsh \
  --output "$ROOT/state/rc7-dsh.patch.yml" \
  --home "$ROOT" \
  --python "$PY" \
  --require-default-enhancements

echo "[RC7] Protected bank DSH profile: $PFC_RC7_DSH_BASE_PROFILE (read-only source)"
echo "[RC7] RC7 DSH runtime profile: $PFC_RC7_DSH_PROFILE"
echo "[RC7] Vision Router: DEFAULT ON / LOCAL-ONLY / PUBLIC REMOTE FORBIDDEN"
echo "[RC7] Memento: DEFAULT ON / RC7 LOCAL DB / R1 NON-AUTHORITATIVE"
echo "[RC7] Canonical R1: $PFC_AITEST_STATE_DIR/r1/event-stream.jsonl"
echo "[RC7] Maven repo: $PFC_MAVEN_REPO"
echo "[RC7] Starting DSH with RC7 plugin clone + runtime-only enhancement/MCP patch."
exec dsh --profile "$PFC_RC7_DSH_PROFILE" --patch "$ROOT/state/rc7-dsh.patch.yml"
