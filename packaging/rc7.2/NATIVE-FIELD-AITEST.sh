#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "\${BASH_SOURCE[0]}")/../.." && pwd -P)"
PY="$ROOT/workspace-template/runtime/python/bin/python3"
NODE="$ROOT/workspace-template/runtime/node/bin/node"
BSK="$ROOT/workspace-template/runtime/browser/browserskill/bsk"
[[ -x "$PY" ]] || { echo "NATIVE_PACKAGE_PYTHON_MISSING:$PY" >&2; exit 2; }
[[ -x "$NODE" ]] || { echo "NATIVE_PACKAGE_NODE_MISSING:$NODE" >&2; exit 2; }
[[ -x "$BSK" ]] || { echo "NATIVE_PACKAGE_BROWSERSKILL_MISSING:$BSK" >&2; exit 2; }

case "$(uname -s):$(uname -m)" in
  Linux:x86_64|Linux:aarch64|Darwin:x86_64|Darwin:arm64) ;;
  *) echo "NATIVE_PACKAGE_PLATFORM_UNSUPPORTED:$(uname -s):$(uname -m)" >&2; exit 2 ;;
esac

export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export PFC_AITEST_HOME="$ROOT"
export PFC_AITEST_STATE_DIR="\${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state}"
export PFC_RC7_DSH_PROFILE="\${PFC_RC72_DSH_PROFILE:-rc7.2-bank-native}"
export PFC_RC72_TEAM_CAPACITY32=1
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/workspace-template/runtime/browser/pw-browsers"
export PFC_PYTHON="$PY"
export PFC_NODE_BIN="$NODE"
export PFC_BROWSERSKILL_BIN="$BSK"
if [[ "$(uname -s)" == "Linux" ]]; then
  CHROMIUM="$(find "$ROOT/workspace-template/runtime/browser/pw-browsers" -type f -name chrome -print -quit)"
else
  CHROMIUM="$(find "$ROOT/workspace-template/runtime/browser/pw-browsers" -type f -name Chromium -print -quit)"
fi
[[ -n "$CHROMIUM" ]] || { echo "NATIVE_CHROMIUM_MISSING" >&2; exit 2; }
export PFC_CHROMIUM_BIN="$CHROMIUM"
CODEGRAPH="$(find "$ROOT/workspace-template/runtime/code-intelligence/codegraph" -maxdepth 1 -type f -name 'codegraph-server-*' -print -quit)"
[[ -n "$CODEGRAPH" ]] || { echo "NATIVE_CODEGRAPH_MISSING" >&2; exit 2; }
export PFC_CODEGRAPH_BIN="$CODEGRAPH"
export PFC_RIPGREP_BIN="$ROOT/workspace-template/runtime/ripgrep/rg"
export PFC_JAVA_BIN="$ROOT/workspace-template/runtime/java/bin/java"
export PFC_MAVEN_BIN="$ROOT/workspace-template/runtime/maven/bin/mvn"
export PFC_ALLURE_BIN="$ROOT/workspace-template/runtime/allure/bin/allure"
export PFC_K6_BIN="$ROOT/workspace-template/runtime/k6/k6"
export PFC_ZAP_BIN="$(find "$ROOT/workspace-template/runtime/zap" -type f -name zap.sh -print -quit)"
export PFC_MAVEN_REPO="$ROOT/workspace-template/runtime/maven-repository"
export PFC_MAVEN_SETTINGS="$ROOT/packaging/rc7/maven-offline-settings.xml"
export MAVEN_ARGS="-o -s \"$PFC_MAVEN_SETTINGS\" -Dmaven.legacyLocalRepo=true -Dmaven.repo.local=\"$PFC_MAVEN_REPO\""
export JAVA_HOME="$ROOT/workspace-template/runtime/java"
export MAVEN_HOME="$ROOT/workspace-template/runtime/maven"
export PATH="$ROOT/workspace-template/runtime/node/bin:$ROOT/workspace-template/runtime/browser/browserskill:$ROOT/workspace-template/runtime/ripgrep:$ROOT/workspace-template/runtime/java/bin:$ROOT/workspace-template/runtime/maven/bin:$ROOT/workspace-template/runtime/allure/bin:$ROOT/workspace-template/runtime/k6:$PATH"

if [[ "$(uname -s)" == "Linux" ]]; then
  export LD_LIBRARY_PATH="$ROOT/workspace-template/runtime/syslib\${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

SOURCE="$(tr -d '\r\n' < "$ROOT/SOURCE_COMMIT")"
cd "$ROOT"
"$PY" -B -m rc7_release.rc72_native_field_portable verify --package-root "$ROOT" --expected-source-commit "$SOURCE"

if [[ "\${1:-}" == "--verify-only" || "\${PFC_RC72_NATIVE_PROBE_ONLY:-0}" == "1" ]]; then
  echo "RC72_NATIVE_FIELD_PROBE source=$SOURCE platform=$(uname -s) arch=$(uname -m) node=$("$NODE" --version) bsk=$("$BSK" --version) field_verified=false bank_final=false"
  exit 0
fi

if [[ "$PFC_RC7_DSH_PROFILE" == "\${PFC_RC7_DSH_BASE_PROFILE:-web}" ]]; then
  echo "NATIVE_PROTECTED_DSH_PROFILE_REFUSED" >&2
  exit 4
fi

HOST_BIN="\${PFC_RC72_DSH_HOST_BIN:-}"
if [[ -z "$HOST_BIN" || ! -f "$HOST_BIN" || ! -x "$HOST_BIN" ]]; then
  echo "[RC7.2] Set PFC_RC72_DSH_HOST_BIN to the absolute path of the bank-approved native DSH CLI." >&2
  echo "[RC7.2] This package does not redistribute the DSH main executable." >&2
  exit 4
fi
case "$(uname -s)" in
  Linux)
    file "$HOST_BIN" | grep -q 'ELF 64-bit' || { echo "DSH_HOST_NOT_NATIVE_ELF64" >&2; exit 4; }
    ;;
  Darwin)
    file "$HOST_BIN" | grep -q 'Mach-O' || { echo "DSH_HOST_NOT_NATIVE_MACHO" >&2; exit 4; }
    ;;
esac
if [[ -n "\${PFC_RC72_DSH_HOST_SHA256:-}" ]]; then
  if command -v sha256sum >/dev/null 2>&1; then ACTUAL="$(sha256sum "$HOST_BIN" | awk '{print $1}')"; else ACTUAL="$(shasum -a 256 "$HOST_BIN" | awk '{print $1}')"; fi
  EXPECTED="$(printf '%s' "$PFC_RC72_DSH_HOST_SHA256" | tr '[:upper:]' '[:lower:]')"
  [[ "$ACTUAL" == "$EXPECTED" ]] || { echo "DSH_HOST_SHA256_MISMATCH" >&2; exit 4; }
fi

echo "[RC7.2] Package verified. Starting external bank-approved DSH with profile $PFC_RC7_DSH_PROFILE."
exec "$HOST_BIN" --profile "$PFC_RC7_DSH_PROFILE" "$@"
