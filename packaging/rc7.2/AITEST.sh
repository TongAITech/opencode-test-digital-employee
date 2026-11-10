#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR_POSIX="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

_is_rc72_package_root() {
  local candidate="$1"
  [[ -d "$candidate" ]] || return 1
  [[ -f "$candidate/SOURCE_COMMIT" ]] || return 1
  [[ -f "$candidate/PACKAGE_MANIFEST.json" ]] || return 1
  [[ -f "$candidate/RC72_RELEASE_IDENTITY.json" ]] || return 1
  [[ -f "$candidate/workspace-template/runtime/python/python.exe" ]] || return 1
  [[ -f "$candidate/packaging/rc7.2/AITEST.sh" ]] || return 1
  return 0
}

# Resolve from the launcher location, not the caller's working directory.
# This supports a normal extraction and an additional outer folder created
# when the ZIP is unpacked into a directory with the same package name.
ROOT_POSIX=""
candidate="$SCRIPT_DIR_POSIX"
for _depth in 0 1 2 3 4 5 6 7 8 9 10; do
  if _is_rc72_package_root "$candidate"; then
    ROOT_POSIX="$(cd -- "$candidate" && pwd -P)"
    break
  fi
  parent="$(dirname -- "$candidate")"
  [[ "$parent" == "$candidate" ]] && break
  candidate="$parent"
done

if [[ -z "$ROOT_POSIX" ]]; then
  nested_roots=()
  while IFS= read -r -d '' identity_file; do
    candidate="$(dirname -- "$identity_file")"
    if _is_rc72_package_root "$candidate"; then
      nested_roots+=("$(cd -- "$candidate" && pwd -P)")
    fi
  done < <(find "$SCRIPT_DIR_POSIX" -mindepth 1 -maxdepth 4 -type f -name "RC72_RELEASE_IDENTITY.json" -print0 2>/dev/null || true)
  if [[ "${#nested_roots[@]}" -ne 1 ]]; then
    echo "[RC7.2] package root not uniquely identifiable from launcher path (matches=${#nested_roots[@]})" >&2
    exit 2
  fi
  ROOT_POSIX="${nested_roots[0]}"
fi

ROOT="$(cd -- "$ROOT_POSIX" && { pwd -W 2>/dev/null || pwd; })"

# A narrow, non-mutating hook used by Windows Git Bash and Linux shell CI to
# verify path canonicalization before package-local Python is required.
if [[ "${PFC_RC72_ROOT_PROBE_ONLY:-0}" == "1" ]]; then
  printf 'RC72_PACKAGE_ROOT=%s\n' "$ROOT"
  printf 'RC72_PACKAGE_ROOT_POSIX=%s\n' "$ROOT_POSIX"
  exit 0
fi

PY="$ROOT/workspace-template/runtime/python/python.exe"
[[ -f "$PY" ]] || { echo "[RC7.2] package-local Python missing: $PY" >&2; exit 2; }

SOURCE_COMMIT="$(tr -d '\r\n' < "$ROOT/SOURCE_COMMIT")"
[[ -n "$SOURCE_COMMIT" ]] || { echo "[RC7.2] SOURCE_COMMIT missing" >&2; exit 2; }

export PYTHONUTF8=1
export PFC_AITEST_HOME="$ROOT"
export PFC_AITEST_STATE_DIR="${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state}"
export PFC_PYTHON="$PY"

# Mnemon Native is a local dependency of dsh-mnemon. Prefer the bundled,
# SHA-verified platform binary; never silently fall back to a user/global CLI.
if [[ -f "$ROOT/workspace-template/runtime/mnemon/mnemon.exe" ]]; then
  export MNEMON_CLI_PATH="$ROOT/workspace-template/runtime/mnemon/mnemon.exe"
  export PATH="$ROOT/workspace-template/runtime/mnemon:$PATH"
elif [[ -f "$ROOT/workspace-template/runtime/mnemon/mnemon" ]]; then
  export MNEMON_CLI_PATH="$ROOT/workspace-template/runtime/mnemon/mnemon"
  export PATH="$ROOT/workspace-template/runtime/mnemon:$PATH"
fi

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
