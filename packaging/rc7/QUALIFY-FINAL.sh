#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_BIN="${PFC_PYTHON:-}"
STATE="${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state/rc7-final-qualification}"

if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  printf '%s\n' '{"status":"HOLD","reason":"PYTHON_NOT_FOUND"}' >&2
  exit 10
fi

SOURCE_COMMIT="${PFC_RC7_SOURCE_COMMIT:-}"
if [[ -z "$SOURCE_COMMIT" && -f "$ROOT/SOURCE_COMMIT" ]]; then
  SOURCE_COMMIT="$(tr -d '\r\n' < "$ROOT/SOURCE_COMMIT")"
fi
if [[ -z "$SOURCE_COMMIT" ]] && command -v git >/dev/null 2>&1; then
  SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || true)"
fi
if [[ -z "$SOURCE_COMMIT" ]]; then
  printf '%s\n' '{"status":"HOLD","reason":"SOURCE_COMMIT_NOT_RESOLVED"}' >&2
  exit 11
fi

mkdir -p "$STATE"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

REAL_MISSION_EVIDENCE="${PFC_RC7_REAL_MISSION_EVIDENCE:-}"
if [[ -z "$REAL_MISSION_EVIDENCE" && -n "${PFC_RC7_R1_PATH:-}" && -n "${PFC_RC7_MISSION_ID:-}" ]]; then
  REAL_MISSION_EVIDENCE="$STATE/rc7-real-mission-result.json"
  "$PYTHON_BIN" -m rc7_release.real_mission_qualification_strict \
    --r1 "$PFC_RC7_R1_PATH" \
    --mission-id "$PFC_RC7_MISSION_ID" \
    --source-commit "$SOURCE_COMMIT" \
    --output "$REAL_MISSION_EVIDENCE"
  printf 'RC7 strict real Mission qualification evidence: %s\n' "$REAL_MISSION_EVIDENCE" >&2
fi

ARGS=(
  --source-commit "$SOURCE_COMMIT"
  --output "$STATE/rc7-final-qualification.json"
)
[[ -n "${PFC_RC7_ENGINEERING_EVIDENCE:-}" ]] && ARGS+=(--engineering "$PFC_RC7_ENGINEERING_EVIDENCE")
[[ -n "${PFC_RC7_ADMIN_EVIDENCE:-}" ]] && ARGS+=(--admin "$PFC_RC7_ADMIN_EVIDENCE")
[[ -n "$REAL_MISSION_EVIDENCE" ]] && ARGS+=(--real-mission "$REAL_MISSION_EVIDENCE")
[[ -n "${PFC_RC7_DELIVERY_EVIDENCE:-}" ]] && ARGS+=(--delivery "$PFC_RC7_DELIVERY_EVIDENCE")
[[ "${PFC_RC7_REQUIRE_FINAL_PASS:-0}" == "1" ]] && ARGS+=(--require-pass)

"$PYTHON_BIN" -m rc7_release.final_qualification "${ARGS[@]}"
printf 'RC7 final qualification evidence: %s\n' "$STATE/rc7-final-qualification.json" >&2
