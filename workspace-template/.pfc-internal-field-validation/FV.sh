#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$ROOT/ai-test/runtime${PYTHONPATH:+:$PYTHONPATH}"
PORTABLE_PYTHON="$ROOT/runtime/python/python.exe"
if [ ! -x "$PORTABLE_PYTHON" ]; then
  echo "PORTABLE_PYTHON_NOT_FOUND: $PORTABLE_PYTHON" >&2
  exit 86
fi
exec "$PORTABLE_PYTHON" "$ROOT/.pfc-internal-field-validation/tools/fv_tool.py" "$@"
