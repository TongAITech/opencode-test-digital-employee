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

if [[ "$PFC_RC7_DSH_PROFILE" == "${PFC_RC7_DSH_BASE_PROFILE:-web}" ]]; then
  echo "[RC7.2] runtime profile must not equal protected bank base profile" >&2
  exit 4
fi

echo "[RC7.2] Package identity verified: $SOURCE_COMMIT"
echo "[RC7.2] Delegating to mature RC7 DSH bootstrap with isolated profile: $PFC_RC7_DSH_PROFILE"
exec "$ROOT/packaging/rc7/AITEST.sh"
