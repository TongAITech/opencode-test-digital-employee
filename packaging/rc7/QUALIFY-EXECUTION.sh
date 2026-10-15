#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATE="${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state/rc7-execution-qualification}"
PYTHON_BIN="${PFC_PYTHON:-}"

if [[ -z "$PYTHON_BIN" && -x "$ROOT/workspace-template/runtime/python/python.exe" ]]; then
  PYTHON_BIN="$ROOT/workspace-template/runtime/python/python.exe"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  printf '%s\n' '{"status":"NOT_PROVEN","reason":"PYTHON_NOT_FOUND"}' >&2
  exit 10
fi

if [[ -z "${PFC_BROWSER_BIN:-}" && -f "$ROOT/workspace-template/runtime/browser/chrome-win64/chrome.exe" ]]; then
  export PFC_BROWSER_BIN="$ROOT/workspace-template/runtime/browser/chrome-win64/chrome.exe"
fi
if [[ -z "${PFC_CHROME_BIN:-}" && -n "${PFC_BROWSER_BIN:-}" ]]; then
  export PFC_CHROME_BIN="$PFC_BROWSER_BIN"
fi

: "${PFC_RC7_SCRIPT_RESULT:?PFC_RC7_SCRIPT_RESULT must point to a strict PASS rc7-dsh-script-result.json}"
: "${PFC_RC7_EXECUTION_ENV_MODULE:?PFC_RC7_EXECUTION_ENV_MODULE must be an importable Python module exposing create_execution_environment()}"
: "${PFC_RC7_EXECUTION_TARGET_ID:?PFC_RC7_EXECUTION_TARGET_ID is the exact admitted target identity}"

mkdir -p "$STATE"
export PFC_AITEST_HOME="$ROOT"
export PFC_AITEST_STATE_DIR="$STATE"
export PFC_WORKSPACE="${PFC_WORKSPACE:-$ROOT}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

TIMEOUT="${PFC_RC7_EXECUTION_TIMEOUT:-300}"
MAX_CYCLES="${PFC_RC7_EXECUTION_MAX_CYCLES:-4}"
MAX_RETRIES="${PFC_RC7_EXECUTION_MAX_TRANSIENT_RETRIES:-2}"

set +e
"$PYTHON_BIN" -m rc7_release.execution_qualification_strict \
  --state-root "$STATE" \
  --workspace "$PFC_WORKSPACE" \
  --script-result "$PFC_RC7_SCRIPT_RESULT" \
  --environment-module "$PFC_RC7_EXECUTION_ENV_MODULE" \
  --target-id "$PFC_RC7_EXECUTION_TARGET_ID" \
  --timeout-seconds "$TIMEOUT" \
  --max-cycles "$MAX_CYCLES" \
  --max-transient-retries "$MAX_RETRIES"
RC=$?
set -e

RESULT="$STATE/qualification/rc7-execution-result.json"
if [[ -f "$RESULT" ]]; then
  printf 'RC7 strict Execution qualification evidence: %s\n' "$RESULT" >&2
else
  printf '%s\n' '{"status":"FAIL","reason":"EXECUTION_QUALIFICATION_RESULT_FILE_MISSING"}' >&2
  exit 11
fi
exit "$RC"