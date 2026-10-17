#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_BIN="${PFC_PYTHON:-}"
STATE="${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state/rc7-bank-services}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -f "$ROOT/workspace-template/runtime/python/python.exe" ]]; then
    PYTHON_BIN="$ROOT/workspace-template/runtime/python/python.exe"
  else
    PYTHON_BIN="$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)"
  fi
fi
[[ -n "$PYTHON_BIN" ]] || { echo '{"status":"HOLD","reason":"PYTHON_NOT_FOUND"}' >&2; exit 10; }

: "${PFC_RC7_R1_PATH:?PFC_RC7_R1_PATH is required}"
: "${PFC_RC7_MISSION_ID:?PFC_RC7_MISSION_ID is required}"
: "${PFC_RC7_BANK_TARGET_ID:?PFC_RC7_BANK_TARGET_ID is required}"

PROVIDER_CONFIG="${PFC_RC7_BANK_SERVICE_PROVIDER_CONFIG:-${PFC_RC7_CASE_PROVIDER_CONFIG:-$ROOT/state/bank-field-providers.json}}"
if [[ ! -f "$PROVIDER_CONFIG" ]]; then
  printf '{"status":"FIELD_REQUIRED","reason":"BANK_SERVICE_PROVIDER_CONFIG_NOT_FOUND","path":"%s"}\n' "$PROVIDER_CONFIG" >&2
  exit 2
fi
mkdir -p "$STATE"
OUTPUT="$STATE/rc7-bank-service-probe.json"

set +e
"$PYTHON_BIN" -m rc7_runtime.bank_field_services probe \
  --r1 "$PFC_RC7_R1_PATH" \
  --state-root "$STATE" \
  --provider-config "$PROVIDER_CONFIG" \
  --mission-id "$PFC_RC7_MISSION_ID" \
  --target-id "$PFC_RC7_BANK_TARGET_ID" \
  --output "$OUTPUT" \
  --require-pass
RC=$?
set -e

if [[ $RC -eq 3 ]]; then
  REQUEST_ID="$($PYTHON_BIN -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8")).get("db_write_gate_request_id") or "")' "$OUTPUT")"
  echo "RC7 bank services: DB_WRITE Human Gate required." >&2
  echo "Request: $REQUEST_ID" >&2
  echo "Approve explicitly, then rerun this script:" >&2
  printf '%q -m rc7_runtime.bank_field_services approve-db-write --r1 %q --state-root %q --mission-id %q --target-id %q --request-id %q --actor-ref <YOUR_OPERATOR_REF> --reason <YOUR_REASON>\n' \
    "$PYTHON_BIN" "$PFC_RC7_R1_PATH" "$STATE" "$PFC_RC7_MISSION_ID" "$PFC_RC7_BANK_TARGET_ID" "$REQUEST_ID" >&2
  exit 3
fi
[[ $RC -eq 0 ]] || exit "$RC"

echo "RC7 bank service probes: PASS"
echo "Evidence: $OUTPUT"
