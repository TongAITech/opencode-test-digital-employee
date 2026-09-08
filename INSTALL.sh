#!/usr/bin/env bash
set -euo pipefail

BASE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
TARGET="/d/PFC/AITest"
case "$(uname -s)" in
  MINGW*|MSYS*) ;;
  *) echo 'FAIL：请在 Windows Git Bash 中运行 ./INSTALL.sh。'; exit 2 ;;
esac
command -v cygpath >/dev/null 2>&1 || { echo 'FAIL：缺少 Git Bash cygpath。'; exit 2; }
if [[ $# -gt 0 ]]; then
  if [[ "$1" == '--target' && $# -eq 2 ]]; then TARGET="$2"
  elif [[ $# -eq 1 && "$1" != --* ]]; then TARGET="$1"
  else echo '用法：./INSTALL.sh [--target 安装目录]（默认 /d/PFC/AITest）'; exit 2
  fi
fi
PY="$BASE/workspace-template/runtime/python/python.exe"
[[ -f "$PY" ]] || { echo 'FAIL：缺少包内 portable Python；请校验完整交付 ZIP。'; exit 1; }
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONUTF8=1
exec "$PY" -I -B -X utf8 "$(cygpath -w "$BASE/tools/recovery/install.py")" \
  --source "$(cygpath -w "$BASE")" --target "$(cygpath -w "$TARGET")" --git-bash
