#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
ARCHIVE="${1:-}"
AUTH="${2:-}"
EXPECTED="${3:-}"
[[ -f "$ARCHIVE" && -f "$AUTH" ]] || { echo "DSH_ALPHA_ARCHIVE_AND_AUTH_RECORD_REQUIRED" >&2; exit 4; }
[[ "$EXPECTED" =~ ^[0-9a-fA-F]{64}$ ]] || { echo "DSH_ALPHA_ARCHIVE_SHA256_REQUIRED" >&2; exit 4; }
if command -v sha256sum >/dev/null 2>&1; then ACTUAL="$(sha256sum "$ARCHIVE" | awk '{print $1}')"; else ACTUAL="$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')"; fi
EXPECTED_LOWER="$(printf '%s' "$EXPECTED" | tr '[:upper:]' '[:lower:]')"
[[ "$ACTUAL" == "$EXPECTED_LOWER" ]] || { echo "DSH_ALPHA_ARCHIVE_SHA256_MISMATCH" >&2; exit 4; }
PY="$ROOT/workspace-template/runtime/python/bin/python3"
"$PY" - "$AUTH" <<'PY'
import json,sys
d=json.load(open(sys.argv[1],encoding="utf-8"))
assert d.get("upstream")=="songofhawk/dsh-alpha"
assert d.get("version")=="0.2.2"
assert d.get("source_commit")=="f417e90ddd0e20f08b82e0b79a8c29fdad45c8f4"
assert d.get("commercial_use_authorized") is True
assert d.get("redistribution_authorized") is True
assert isinstance(d.get("authorization_reference"),str) and d["authorization_reference"].strip()
print("DSH_ALPHA_AUTHORIZATION_RECORD_PASS")
PY
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
tar -xzf "$ARCHIVE" -C "$TMP"
PKG="$(find "$TMP" -type f -name package.json -print -quit)"
[[ -n "$PKG" ]] || { echo "DSH_ALPHA_PACKAGE_JSON_MISSING" >&2; exit 4; }
SRC="$(dirname "$PKG")"
[[ -f "$SRC/SOURCE_COMMIT" ]] || { echo "DSH_ALPHA_SOURCE_COMMIT_MARKER_MISSING" >&2; exit 4; }
[[ -d "$SRC/node_modules/@deepseek-ai/schemastery" ]] || { echo "DSH_ALPHA_OFFLINE_RUNTIME_DEPENDENCIES_MISSING" >&2; exit 4; }
grep -qx 'f417e90ddd0e20f08b82e0b79a8c29fdad45c8f4' "$SRC/SOURCE_COMMIT" || { echo "DSH_ALPHA_SOURCE_COMMIT_MISMATCH" >&2; exit 4; }
"$PY" - "$PKG" <<'PY'
import json,sys
d=json.load(open(sys.argv[1],encoding="utf-8"))
assert d.get("name")=="dsh-alpha"
assert d.get("version")=="0.2.2"
print("DSH_ALPHA_PACKAGE_IDENTITY_PASS")
PY
DEST="$ROOT/workspace-template/runtime/dsh-plugins/dsh-alpha"
mkdir -p "$(dirname "$DEST")"
[[ ! -e "$DEST" ]] || { echo "DSH_ALPHA_TARGET_EXISTS_REFUSE_OVERWRITE" >&2; exit 4; }
cp -R "$SRC" "$DEST"
echo "DSH_ALPHA_STAGED_LICENSE_AUTHORIZED_SOURCE; this is package-local staging only. Install into the selected DSH profile and run the upstream preset/profile setup scripts as a separate bank-approved activation step."
