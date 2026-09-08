#!/usr/bin/env bash
set -euo pipefail

BASE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
TARGET="${PWD}/AITest-Workspace"
case "$(uname -s)" in
  MINGW*|MSYS*) ;;
  *) echo 'FAIL：请在 Windows Git Bash 中运行 ./INSTALL.sh。'; exit 2 ;;
esac
command -v cygpath >/dev/null 2>&1 || { echo 'FAIL：缺少 Git Bash cygpath。'; exit 2; }
if [[ $# -gt 0 ]]; then
  if [[ "$1" == '--target' && $# -eq 2 ]]; then
    TARGET="$2"
    [[ "$TARGET" == /* || "$TARGET" =~ ^[A-Za-z]:[/\\] ]] || { echo 'FAIL：--target 需要绝对路径。'; exit 2; }
  elif [[ $# -ge 1 && $# -le 2 && "$1" != --* ]]; then
    NAME="${2:-AITest-Workspace}"
    [[ "$NAME" != '.' && "$NAME" != '..' && "$NAME" != *[/\\:]* && -n "$NAME" ]] || { echo 'FAIL：工作目录名称无效。'; exit 2; }
    TARGET="${1%/}/$NAME"
  else echo '用法：./INSTALL.sh <父目录> [工作目录名称] 或 ./INSTALL.sh --target <完整目标路径>'; exit 2
  fi
fi
PY="$BASE/workspace-template/runtime/python/python.exe"
[[ -f "$PY" ]] || { echo 'FAIL：缺少包内 portable Python；请校验完整交付 ZIP。'; exit 1; }
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONUTF8=1
exec "$PY" -I -B -X utf8 "$(cygpath -w "$BASE/tools/recovery/install.py")" \
  --source "$(cygpath -w "$BASE")" --target "$(cygpath -w "$TARGET")" --git-bash
