#!/usr/bin/env bash
set -euo pipefail
BASE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
PY="$BASE/runtime/python/python.exe"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) ;;
  *) echo "此交付包面向 Windows x64 / Git Bash。请在 Windows 解压后运行 bash AITEST.sh。"; exit 2 ;;
esac
if [ ! -f "$PY" ]; then
  echo "INSTALL_REQUIRED：请先从解压包运行 INSTALL.sh，再进入安装后的工作目录。"
  exit 1
fi
unset AITEST_HOST_OPENCODE
HOST_OPENCODE="$(command -v opencode || true)"
if [[ -n "$HOST_OPENCODE" && -f "$HOST_OPENCODE" ]]; then
  export AITEST_HOST_OPENCODE="$(cygpath -aw "$HOST_OPENCODE")"
fi
export AITEST_GIT_BASH="$(cygpath -aw "$BASH")"
exec "$PY" -X utf8 "$BASE/tools/recovery/launcher.py" "$@"
