#!/usr/bin/env bash
set -euo pipefail
BASE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
PY="$BASE/workspace-template/runtime/python/python.exe"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) ;;
  *) echo "此交付包面向 Windows x64 / Git Bash。请在 Windows 解压后运行 bash AITEST.sh。"; exit 2 ;;
esac
if [ ! -f "$PY" ]; then
  echo "FAIL：缺少包内 Python；请重新校验交付 ZIP，不会联网安装。"
  exit 1
fi
exec "$PY" "$BASE/tools/recovery/launcher.py" "$@"
