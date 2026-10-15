#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATE="${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state/rc7-dsh-script-qualification}"
PYTHON_BIN="${PFC_PYTHON:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  printf '%s\n' '{"status":"NOT_PROVEN","reason":"PYTHON_NOT_FOUND"}' >&2
  exit 10
fi

: "${PFC_RC7_TEST_DESIGN_RESULT:?PFC_RC7_TEST_DESIGN_RESULT must point to a strict PASS rc7-dsh-test-design-result.json}"
: "${PFC_RC7_SCRIPT_TC_ID:?PFC_RC7_SCRIPT_TC_ID is the exact TestCase id to freeze and implement}"

mkdir -p "$STATE"
export PFC_AITEST_HOME="$ROOT"
export PFC_AITEST_STATE_DIR="$STATE"
export PFC_WORKSPACE="${PFC_WORKSPACE:-$ROOT}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

ARGS=(
  -m rc7_release.script_qualification_strict
  --state-root "$STATE"
  --workspace "$PFC_WORKSPACE"
  --test-design-result "$PFC_RC7_TEST_DESIGN_RESULT"
  --tc-id "$PFC_RC7_SCRIPT_TC_ID"
)
if [[ -n "${PFC_RC7_SCRIPT_CWD:-}" ]]; then
  ARGS+=(--execution-cwd "$PFC_RC7_SCRIPT_CWD")
fi
if [[ -n "${PFC_DSH_BIN:-}" ]]; then
  ARGS+=(--dsh-bin "$PFC_DSH_BIN")
fi
if [[ -n "${PFC_RC7_DSH_TIMEOUT:-}" ]]; then
  ARGS+=(--timeout-seconds "$PFC_RC7_DSH_TIMEOUT")
fi

set +e
"$PYTHON_BIN" "${ARGS[@]}"
RC=$?
set -e

RESULT="$STATE/qualification/rc7-dsh-script-result.json"
if [[ -f "$RESULT" ]]; then
  printf 'RC7 strict Script readiness qualification evidence: %s\n' "$RESULT" >&2
else
  printf '%s\n' '{"status":"FAIL","reason":"SCRIPT_QUALIFICATION_RESULT_FILE_MISSING"}' >&2
  exit 11
fi
exit "$RC"
