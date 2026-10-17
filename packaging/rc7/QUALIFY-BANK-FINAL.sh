#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && { pwd -W 2>/dev/null || pwd; })"
PY="${PFC_PYTHON:-$ROOT/workspace-template/runtime/python/python.exe}"
if [[ ! -f "$PY" && "$PY" == "$ROOT/workspace-template/runtime/python/python.exe" ]]; then
  PY="python"
fi

# Preserve the strict Bank Final gate while removing manual environment
# stitching. Auto-resolution is unique-only; any Mission/Target ambiguity is
# a HOLD and the launcher never applies a latest/newest heuristic.
if [[ -z "${PFC_RC7_R1_PATH:-}" || -z "${PFC_RC7_MISSION_ID:-}" || -z "${PFC_RC7_BANK_TARGET_ID:-}" ]]; then
  exec "$PY" -m rc7_release.bank_field_launcher run --package-root "$ROOT" "$@"
fi

if [[ ! -f "$PFC_RC7_R1_PATH" ]]; then
  printf '%s\n' '{"status":"HOLD","reason":"R1_EVENT_STREAM_NOT_FOUND"}' >&2
  exit 22
fi

QUAL_DIR="${PFC_RC7_QUALIFICATION_DIR:-}"
if [[ -z "$QUAL_DIR" && -d "$ROOT/qualification" ]]; then
  QUAL_DIR="$ROOT/qualification"
fi
if [[ -z "$QUAL_DIR" && -d "$ROOT/../qualification" ]]; then
  QUAL_DIR="$(cd "$ROOT/../qualification" && pwd)"
fi
if [[ -z "$QUAL_DIR" ]]; then
  printf '%s\n' '{"status":"HOLD","reason":"DELIVERY_QUALIFICATION_DIRECTORY_NOT_FOUND"}' >&2
  exit 23
fi

export PFC_RC7_ENGINEERING_EVIDENCE="${PFC_RC7_ENGINEERING_EVIDENCE:-$QUAL_DIR/engineering.json}"
export PFC_RC7_ADMIN_EVIDENCE="${PFC_RC7_ADMIN_EVIDENCE:-$QUAL_DIR/admin.json}"
export PFC_RC7_DELIVERY_EVIDENCE="${PFC_RC7_DELIVERY_EVIDENCE:-$QUAL_DIR/delivery.json}"

for path in "$PFC_RC7_ENGINEERING_EVIDENCE" "$PFC_RC7_ADMIN_EVIDENCE" "$PFC_RC7_DELIVERY_EVIDENCE"; do
  if [[ ! -f "$path" ]]; then
    printf '{"status":"HOLD","reason":"REQUIRED_PRE_FIELD_EVIDENCE_MISSING","path":"%s"}\n' "$path" >&2
    exit 24
  fi
done

export PFC_AITEST_STATE_DIR="${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state/rc7-bank-final}"

# One Bank Final entrypoint owns the field-service preflight. Read-only probes
# and 4A/CAT/DB_READ are replay-safe. DB_WRITE stops at the mandatory Human
# Gate on the first run; after explicit approval, rerunning this same command
# resumes and never repeats already-qualified capability probes.
"$SCRIPT_DIR/QUALIFY-BANK-SERVICES.sh"

export PFC_RC7_REQUIRE_FINAL_PASS=1
# Bank Final is intentionally stricter than generic final qualification: only
# a new graph-v2 Mission carrying durable node/tool + execution/recovery
# contracts may qualify. Old Missions remain resumable but cannot certify the
# new package as BANK_FIELD_QUALIFIED.
export PFC_RC7_REQUIRE_BANK_FIELD_CONFORMANCE=1

printf 'RC7 BANK FINAL qualification\n'
printf 'Package root: %s\n' "$ROOT"
printf 'Qualification evidence: %s\n' "$QUAL_DIR"
printf 'R1 Event Stream: %s\n' "$PFC_RC7_R1_PATH"
printf 'Mission: %s\n' "$PFC_RC7_MISSION_ID"
printf 'Bank target: %s\n' "$PFC_RC7_BANK_TARGET_ID"

exec "$SCRIPT_DIR/QUALIFY-FINAL.sh"
