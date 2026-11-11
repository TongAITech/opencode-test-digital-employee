#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
PY="$ROOT/workspace-template/runtime/python/bin/python3"
NODE_DIR="$ROOT/workspace-template/runtime/node/bin"
BSK_DIR="$ROOT/workspace-template/runtime/browser/browserskill"
[[ -x "$PY" ]] || { echo "LINUX_PACKAGE_PYTHON_NOT_EXECUTABLE:$PY" >&2; exit 2; }
[[ -x "$NODE_DIR/node" ]] || { echo "LINUX_PACKAGE_NODE_NOT_EXECUTABLE" >&2; exit 2; }
[[ -x "$BSK_DIR/bsk" ]] || { echo "LINUX_PACKAGE_BROWSERSKILL_NOT_EXECUTABLE" >&2; exit 2; }
[[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" ]] || {
  echo "LINUX_X86_64_TARGET_REQUIRED" >&2; exit 2;
}

export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export PFC_AITEST_HOME="$ROOT"
export PFC_AITEST_STATE_DIR="${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state}"
export PFC_RC7_DSH_PROFILE="${PFC_RC72_DSH_PROFILE:-rc7.2-bank-linux}"
export PFC_RC72_TEAM_CAPACITY32=1
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/workspace-template/runtime/browser/pw-browsers"
export PATH="$NODE_DIR:$BSK_DIR:$PATH"

if [[ "$PFC_RC7_DSH_PROFILE" == "${PFC_RC7_DSH_BASE_PROFILE:-web}" ]]; then
  echo "LINUX_PROTECTED_DSH_PROFILE_REFUSED" >&2
  exit 4
fi

SOURCE="$(tr -d '\r\n' < "$ROOT/SOURCE_COMMIT")"
cd "$ROOT"
"$PY" -B -m rc7_release.rc72_linux_field_portable verify \
  --package-root "$ROOT" --expected-source-commit "$SOURCE"

if [[ "${1:-}" == "--verify-only" || "${PFC_RC72_LINUX_PROBE_ONLY:-0}" == "1" ]]; then
  echo "RC72_LINUX_FIELD_PROBE source=$SOURCE node=$("$NODE_DIR/node" --version) profile=$PFC_RC7_DSH_PROFILE q3_target_linux_verified=false field_verified=false bank_final=false"
  exit 0
fi
if [[ "${1:-}" == "--q3-handoff" ]]; then
  shift
  exec bash "$ROOT/packaging/rc7.2/Q3-FIELD-HANDOFF.sh" \
    --package-root "$ROOT" --source-commit "$SOURCE" "$@"
fi

HOST_BIN="${PFC_RC72_DSH_LINUX_HOST_BIN:-}"
if [[ -z "$HOST_BIN" ]]; then
  echo "[RC7.2 Linux] This package contains no DSH CLI. Set PFC_RC72_DSH_LINUX_HOST_BIN to the approved absolute path of a native Linux dsh executable." >&2
  echo "[RC7.2 Linux] Use --verify-only to qualify this package without a DSH host." >&2
  exit 4
fi

BIND_ARGS=(bind --executable "$HOST_BIN" --output "$ROOT/state/dsh-linux-host-binding.json")
if [[ -n "${PFC_RC72_DSH_LINUX_HOST_SHA256:-}" ]]; then
  BIND_ARGS+=(--expected-sha256 "$PFC_RC72_DSH_LINUX_HOST_SHA256")
fi
"$PY" -B -m rc7_release.rc72_linux_field_portable "${BIND_ARGS[@]}"
echo "[RC7.2 Linux] Bound external approved-host candidate; actual bank approval and Q3 remain independent."
exec "$HOST_BIN" "$@"
