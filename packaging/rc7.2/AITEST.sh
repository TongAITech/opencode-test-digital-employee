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

"$PY" -m rc7_release.rc72_package verify \
  --package-root "$ROOT" \
  --expected-source-commit "$SOURCE_COMMIT"

# The mature RC7 launcher remains the single DSH/tool bootstrap implementation.
# RC7.2 performs its own package verification above, then explicitly skips the
# RC7 identity verifier while retaining every other RC7 startup safety check.
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

# Q2 engineering probe: prove the real Git Bash entrypoint, RC7.2 identity,
# isolated profile, and delegate path without pretending that the Q4 offline
# plugin/tool payload has already been qualified. Default startup does NOT use
# this branch and still execs the mature RC7 bootstrap below.
if [[ "${PFC_RC72_LAUNCHER_PROBE_ONLY:-0}" == "1" ]]; then
  echo "RC72_LAUNCH_PLAN profile=$PFC_RC7_DSH_PROFILE delegate=packaging/rc7/AITEST.sh field_verified=false bank_final=false offline_payload_verified=false"
  exit 0
fi

# Field startup is only valid when the same verified package carries the
# actual native DSH executable. Do not silently resolve an unrelated PATH
# installation (or treat the bundled DSH plugin directory as the engine).
DSH_MAIN="$ROOT/workspace-template/runtime/dsh/dsh.exe"
[[ -f "$DSH_MAIN" ]] || {
  echo "[RC7.2] C12: approved package-local DSH main executable missing" >&2
  exit 4
}
if command -v cygpath >/dev/null 2>&1; then
  DSH_PATH_DIR="$(cygpath -u "$ROOT/workspace-template/runtime/dsh")"
else
  DSH_PATH_DIR="$ROOT/workspace-template/runtime/dsh"
fi
export PATH="$DSH_PATH_DIR:$PATH"
DSH_RESOLVED="$(command -v dsh 2>/dev/null || true)"
[[ -n "$DSH_RESOLVED" ]] || {
  echo "[RC7.2] C12: package-local DSH is not executable in Git Bash" >&2
  exit 4
}
echo "[RC7.2] Package-local DSH bound; physical verification is not bank Field acceptance"

echo "[RC7.2] Delegating to mature RC7 DSH bootstrap with isolated profile: $PFC_RC7_DSH_PROFILE"
exec "$DELEGATE"
