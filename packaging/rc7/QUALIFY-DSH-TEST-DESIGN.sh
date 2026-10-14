#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATE="${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state/rc7-dsh-test-design-qualification}"
PYTHON_BIN="${PFC_PYTHON:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  printf '%s\n' '{"status":"NOT_PROVEN","reason":"PYTHON_NOT_FOUND"}' >&2
  exit 10
fi

: "${PFC_RC7_REQUIREMENT_RESULT:?PFC_RC7_REQUIREMENT_RESULT must point to a PASS rc7-dsh-bridge-result.json}"
: "${PFC_RC7_CODE_RESULT:?PFC_RC7_CODE_RESULT must point to a strict PASS rc7-dsh-code-result.json}"
: "${PFC_RC7_CODE_REPO:?PFC_RC7_CODE_REPO is required and must be relative to PFC_WORKSPACE}"
: "${PFC_RC7_CODEGRAPH_QUERY_ARGS_JSON:?PFC_RC7_CODEGRAPH_QUERY_ARGS_JSON is required}"
: "${PFC_CODEGRAPH_BIN:?PFC_CODEGRAPH_BIN is required}"

mkdir -p "$STATE"
export PFC_AITEST_HOME="$ROOT"
export PFC_AITEST_STATE_DIR="$STATE"
export PFC_WORKSPACE="${PFC_WORKSPACE:-$ROOT}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

ARGS=(
  -m rc7_release.test_design_qualification
  --state-root "$STATE"
  --workspace "$PFC_WORKSPACE"
  --requirement-result "$PFC_RC7_REQUIREMENT_RESULT"
  --code-result "$PFC_RC7_CODE_RESULT"
  --repo-path "$PFC_RC7_CODE_REPO"
  --codegraph-args-json "$PFC_RC7_CODEGRAPH_QUERY_ARGS_JSON"
)
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

RESULT="$STATE/qualification/rc7-dsh-test-design-result.json"
if [[ -f "$RESULT" ]]; then
  printf 'RC7 Test Design qualification evidence: %s\n' "$RESULT" >&2
else
  printf '%s\n' '{"status":"FAIL","reason":"TEST_DESIGN_QUALIFICATION_RESULT_FILE_MISSING"}' >&2
  exit 11
fi
exit "$RC"
