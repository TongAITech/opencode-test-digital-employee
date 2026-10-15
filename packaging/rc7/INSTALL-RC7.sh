#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd -W 2>/dev/null || cd "$(dirname "$0")/../.." && pwd)"
PY="$ROOT/workspace-template/runtime/python/python.exe"
TARGET="${1:-D:/PFC/AITest-RC7}"
MODE=()
[[ -e "$TARGET" ]] && MODE=(--upgrade)
"$PY" -m rc7_release.workspace_install --source "$ROOT" --target "$TARGET" "${MODE[@]}"
echo "[RC7] Installed at $TARGET"
echo "[RC7] Start with $TARGET/packaging/rc7/AITEST.sh"
