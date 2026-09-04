#!/bin/bash
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
case "$(uname -m)" in
  arm64|aarch64)
    export PFC_MAC_CHROME_SHA256="01a23ef9501b2745e0c2944c2e583207e6f6132d8d91c3a87ff65b5079e438ef"
    ;;
  x86_64|amd64|x64)
    export PFC_MAC_CHROME_SHA256="69bcc853db975a2380767e9ff36da17f1d7b782fbbe191a210f676d2d5967d3e"
    ;;
  *)
    printf '[LOCAL MAC PINNED BUILD FAIL] unsupported architecture: %s\n' "$(uname -m)" >&2
    exit 1
    ;;
esac

[[ -f "$HERE/runtime-shell-bash" ]] || {
  printf '[LOCAL MAC PINNED BUILD FAIL] runtime-shell-bash missing\n' >&2
  exit 1
}

BUILD_LOG="$(mktemp "${TMPDIR:-/tmp}/pfc-local-mac-pinned-build.XXXXXX")"
POST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/pfc-local-mac-pinned-post.XXXXXX")"
cleanup() {
  rm -f "$BUILD_LOG"
  rm -rf "$POST_ROOT"
}
trap cleanup EXIT INT TERM

"$HERE/local-mac.sh" build "$@" | tee "$BUILD_LOG"
ARCHIVE="$(sed -n 's/^PACKAGE=//p' "$BUILD_LOG" | tail -n 1)"
[[ -n "$ARCHIVE" && -f "$ARCHIVE" ]] || {
  printf '[LOCAL MAC PINNED BUILD FAIL] lower-level builder did not produce an archive\n' >&2
  exit 1
}

# The lower-level builder is kept unchanged because it already passed native
# arm64/x64 package assembly and G3/G4 regression. Repair only the derived Mac
# package process wrapper: pfc_opencode_process must own the actual OpenCode PID,
# not an intermediate POSIX shell whose child can survive stop().
tar -xzf "$ARCHIVE" -C "$POST_ROOT"
PACKAGE_DIR="$(find "$POST_ROOT" -mindepth 1 -maxdepth 1 -type d -name 'PFC-LOCAL-MAC-R1R4-*' | head -n 1)"
[[ -n "$PACKAGE_DIR" ]] || {
  printf '[LOCAL MAC PINNED BUILD FAIL] extracted package root not found\n' >&2
  exit 1
}

RUNTIME_ROOT="$PACKAGE_DIR/workspace-template/runtime"
PYTHON_BIN="$RUNTIME_ROOT/python/bin/python3"
[[ -x "$PYTHON_BIN" ]] || {
  printf '[LOCAL MAC PINNED BUILD FAIL] package portable Python missing\n' >&2
  exit 1
}
cp "$HERE/runtime-shell-bash" "$RUNTIME_ROOT/shell/bash"
chmod +x "$RUNTIME_ROOT/shell/bash"

RUNTIME_TREE_SHA256="$("$PYTHON_BIN" - "$RUNTIME_ROOT" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
records = []
for path in sorted(root.rglob("*")):
    if not path.is_file():
        continue
    rel = path.relative_to(root).as_posix()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    records.append(f"{digest}  {rel}")
payload = ("\n".join(records) + "\n").encode("utf-8")
print(hashlib.sha256(payload).hexdigest())
PY
)"
[[ "$RUNTIME_TREE_SHA256" =~ ^[0-9a-f]{64}$ ]] || {
  printf '[LOCAL MAC PINNED BUILD FAIL] repaired runtime tree identity invalid\n' >&2
  exit 1
}

"$PYTHON_BIN" - "$PACKAGE_DIR/PACKAGE_MANIFEST.json" "$RUNTIME_TREE_SHA256" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
payload["runtime_tree_sha256"] = sys.argv[2]
payload["opencode_process_wrapper"] = {
    "mode": "POSIX_EXEC_OWNED_PID",
    "status": "PINNED_PACKAGE_REPAIR",
    "purpose": "recorded lifecycle PID is the real OpenCode process",
}
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
os.replace(tmp, path)
PY

PACKAGE_NAME="$(basename "$PACKAGE_DIR")"
rm -f "$ARCHIVE" "$ARCHIVE.sha256"
tar -czf "$ARCHIVE" -C "$POST_ROOT" "$PACKAGE_NAME"
PACKAGE_SHA256="$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')"
printf '%s  %s\n' "$PACKAGE_SHA256" "$(basename "$ARCHIVE")" >"$ARCHIVE.sha256"

printf 'LOCAL_MAC_PINNED_POSTPROCESS=PASS\n'
printf 'PACKAGE=%s\n' "$ARCHIVE"
printf 'PACKAGE_SHA256=%s\n' "$PACKAGE_SHA256"
printf 'RUNTIME_TREE_SHA256=%s\n' "$RUNTIME_TREE_SHA256"
printf 'OPENCODE_PROCESS_WRAPPER=POSIX_EXEC_OWNED_PID\n'
