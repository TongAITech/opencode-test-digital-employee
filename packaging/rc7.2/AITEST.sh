#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && { pwd -W 2>/dev/null || pwd; })"
PY="$ROOT/workspace-template/runtime/python/python.exe"
[[ -f "$PY" ]] || { echo "[RC7.2] package-local Python missing: $PY" >&2; exit 2; }

SOURCE_COMMIT="$(tr -d '\r\n' < "$ROOT/SOURCE_COMMIT")"
[[ -n "$SOURCE_COMMIT" ]] || { echo "[RC7.2] SOURCE_COMMIT missing" >&2; exit 2; }

export PYTHONUTF8=1
export PFC_AITEST_HOME="$ROOT"
export PFC_AITEST_STATE_DIR="${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state}"
export PFC_PYTHON="$PY"

"$PY" -m rc7_release.rc72_package verify --package-root "$ROOT" --expected-source-commit "$SOURCE_COMMIT"

# The mature RC7 launcher remains the single DSH/tool bootstrap implementation.
# RC7.2 verifies its own package first, then skips only the inherited RC7
# identity verifier while retaining every other startup safety check.
export PFC_RC7_SKIP_QUALIFY=1
export PFC_RC7_DSH_PROFILE="${PFC_RC72_DSH_PROFILE:-rc7.2-bank}"
export PFC_RC72_TEAM_CAPACITY32=1

if [[ "$PFC_RC7_DSH_PROFILE" == "${PFC_RC7_DSH_BASE_PROFILE:-web}" ]]; then
  echo "[RC7.2] runtime profile must not equal protected bank base profile" >&2
  exit 4
fi

DELEGATE="$ROOT/packaging/rc7/AITEST.sh"
[[ -f "$DELEGATE" ]] || { echo "[RC7.2] mature RC7 delegate launcher missing: $DELEGATE" >&2; exit 2; }

echo "[RC7.2] Package identity verified: $SOURCE_COMMIT"

# Q2 engineering probe: verify the real Git Bash entrypoint and isolated
# profile without claiming DSH binding, Q4 payload or bank Field acceptance.
if [[ "${PFC_RC72_LAUNCHER_PROBE_ONLY:-0}" == "1" ]]; then
  echo "RC72_LAUNCH_PLAN profile=$PFC_RC7_DSH_PROFILE delegate=packaging/rc7/AITEST.sh field_verified=false bank_final=false offline_payload_verified=false"
  exit 0
fi

# Prefer a DSH executable physically carried by a fully qualified C12 package.
# A field-validation package deliberately omits that controlled binary and
# instead binds an explicitly supplied bank-host DSH executable.
DSH_MAIN="$ROOT/workspace-template/runtime/dsh/dsh.exe"
DSH_BIND_SOURCE="PACKAGE_LOCAL"
DSH_BIND_PATH="$DSH_MAIN"
if [[ ! -f "$DSH_MAIN" ]]; then
  DSH_BIND_SOURCE="EXTERNAL_BANK_HOST"
  DSH_BIND_PATH="${PFC_RC72_DSH_HOST_BIN:-}"
  [[ -n "$DSH_BIND_PATH" ]] || {
    echo "[RC7.2] C12: package has no DSH main; set PFC_RC72_DSH_HOST_BIN to the bank-approved dsh.exe path" >&2
    exit 4
  }
fi

DSH_BIND_ARGS=(--executable "$DSH_BIND_PATH" --output "$ROOT/state/dsh-host-binding.json")
if [[ -n "${PFC_RC72_DSH_HOST_SHA256:-}" ]]; then
  DSH_BIND_ARGS+=(--expected-sha256 "$PFC_RC72_DSH_HOST_SHA256")
fi
"$PY" -m rc7_release.rc72_dsh_host_binding "${DSH_BIND_ARGS[@]}"

command -v cygpath >/dev/null 2>&1 || {
  echo "[RC7.2] Git Bash cygpath is required for exact DSH host binding" >&2
  exit 4
}
DSH_BIND_POSIX="$(cygpath -u "$DSH_BIND_PATH")"
[[ "$(basename "$DSH_BIND_POSIX" | tr '[:upper:]' '[:lower:]')" == "dsh.exe" ]] || {
  echo "[RC7.2] C12: bound host executable must be named dsh.exe" >&2
  exit 4
}
DSH_PATH_DIR="$(dirname "$DSH_BIND_POSIX")"
export PATH="$DSH_PATH_DIR:$PATH"
DSH_RESOLVED="$(command -v dsh 2>/dev/null || true)"
[[ -n "$DSH_RESOLVED" ]] || {
  echo "[RC7.2] C12: bound DSH executable is not resolvable as dsh in Git Bash" >&2
  exit 4
}
DSH_EXPECTED_NATIVE="$(cygpath -aw "$DSH_BIND_POSIX" | tr '[:upper:]' '[:lower:]')"
DSH_RESOLVED_NATIVE="$(cygpath -aw "$DSH_RESOLVED" | tr '[:upper:]' '[:lower:]')"
[[ "$DSH_EXPECTED_NATIVE" == "$DSH_RESOLVED_NATIVE" ]] || {
  echo "[RC7.2] C12: PATH resolved a different DSH executable than the explicitly bound file" >&2
  exit 4
}
export PFC_RC72_DSH_BIND_SOURCE="$DSH_BIND_SOURCE"
echo "[RC7.2] DSH binding source: $DSH_BIND_SOURCE"
echo "[RC7.2] DSH binary SHA256 is recorded in state/dsh-host-binding.json; this is not an authorization or Field PASS"
echo "[RC7.2] Delegating to mature RC7 DSH bootstrap with isolated profile: $PFC_RC7_DSH_PROFILE"
exec "$DELEGATE"
