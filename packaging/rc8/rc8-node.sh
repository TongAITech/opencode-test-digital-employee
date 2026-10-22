#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

# Windows Python inherits the host console code page by default. RC8 CLI and
# product text are Chinese-first, so force UTF-8 consistently in Git Bash and
# Linux instead of degrading user-facing text to ASCII/English.
export PYTHONUTF8="${PYTHONUTF8:-1}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

UNAME_S="$(uname -s 2>/dev/null || true)"
case "$UNAME_S" in
  MINGW*|MSYS*|CYGWIN*)
    export RC8_NODE_OS="windows"
    export RC8_NODE_SHELL="git-bash"
    ;;
  Linux*)
    export RC8_NODE_OS="linux"
    export RC8_NODE_SHELL="bash"
    ;;
  *)
    echo "RC8_NODE_UNSUPPORTED_PLATFORM: $UNAME_S" >&2
    exit 2
    ;;
esac

if [[ -n "${RC8_PYTHON:-}" ]]; then
  PYTHON_BIN="$RC8_PYTHON"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "RC8_NODE_PYTHON_NOT_FOUND" >&2
  exit 3
fi

"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,8), "RC8 requires Python >= 3.8"'

# A Node identity is durable state and must survive package replacement.
# Support the legacy RC8_NODE_STATE variable used by the bank verification
# flow, normalize it to RC8_NODE_STATE_DIR, and reject accidental divergence
# from an explicitly supplied --state-dir before Center sees a second identity.
STATE_ENV="${RC8_NODE_STATE_DIR:-${RC8_NODE_STATE:-}}"
STATE_ARG=""
EXPECT_STATE=0
for ARG in "$@"; do
  if [[ "$EXPECT_STATE" == "1" ]]; then
    STATE_ARG="$ARG"
    EXPECT_STATE=0
    continue
  fi
  case "$ARG" in
    --state-dir)
      EXPECT_STATE=1
      ;;
    --state-dir=*)
      STATE_ARG="${ARG#--state-dir=}"
      ;;
  esac
done

normalize_state_dir() {
  "$PYTHON_BIN" - "$1" <<'PY'
import os, sys
print(os.path.normcase(os.path.realpath(os.path.expanduser(sys.argv[1]))))
PY
}

if [[ -n "$STATE_ENV" ]]; then
  export RC8_NODE_STATE_DIR="$STATE_ENV"
  if [[ -n "$STATE_ARG" ]]; then
    ENV_NORM="$(normalize_state_dir "$STATE_ENV")"
    ARG_NORM="$(normalize_state_dir "$STATE_ARG")"
    if [[ "$ENV_NORM" != "$ARG_NORM" ]]; then
      echo "RC8_NODE_STATE_CONFLICT: exported stable state '$STATE_ENV' differs from --state-dir '$STATE_ARG'; reuse the stable node identity directory" >&2
      exit 4
    fi
  else
    set -- --state-dir "$STATE_ENV" "$@"
  fi
fi

exec "$PYTHON_BIN" -m rc8_node "$@"
