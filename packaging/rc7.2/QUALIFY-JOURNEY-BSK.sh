#!/usr/bin/env bash
# Read-only C09 BrowserSkill onsite qualification. No SUT mutation.
# B group must first supply an authorized, BSK-owned session and tab.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && { pwd -W 2>/dev/null || pwd; })"
PY="$ROOT/workspace-template/runtime/python/python.exe"
[[ -f "$PY" ]] || { echo "[C09] package-local Python missing: $PY" >&2; exit 2; }
[[ -f "$ROOT/SOURCE_COMMIT" ]] || { echo "[C09] SOURCE_COMMIT missing" >&2; exit 2; }

: "${PFC_RC72_BSK_BIN:?Set PFC_RC72_BSK_BIN to the exact BSK executable inside the extracted RC7.2 package}"
: "${PFC_RC72_BSK_SESSION_ID:?Set PFC_RC72_BSK_SESSION_ID to a B-issued, already active BrowserSkill session}"
: "${PFC_RC72_BSK_TAB_ID:?Set PFC_RC72_BSK_TAB_ID to the exact B-issued tab id}"

case "$PFC_RC72_BSK_TAB_ID" in
  ''|*[!0-9]*) echo "[C09] BSK tab id must be positive decimal" >&2; exit 2;;
  0) echo "[C09] BSK tab id must be nonzero" >&2; exit 2;;
esac

REPORT_ROOT="${PFC_RC72_C09_REPORT_ROOT:-$ROOT/runtime-state/field-qualification/c09-bsk-readonly}"
export PYTHONUTF8=1
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "[C09] Read-only BSK+Extension browser probe (does not grant Field approval)"
"$PY" -m rc7_release.rc72_journey_bsk_qualify \
  --package-root "$ROOT" \
  --bsk-bin "$PFC_RC72_BSK_BIN" \
  --session "$PFC_RC72_BSK_SESSION_ID" \
  --tab-id "$PFC_RC72_BSK_TAB_ID" \
  --output-root "$REPORT_ROOT"
echo "[C09] Evidence: $REPORT_ROOT/c09-bsk-probe.json"
