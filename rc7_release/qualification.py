from __future__ import annotations

from typing import Optional

from . import dsh_bridge_qualification as _base
from .dsh import write_patch as _rc7_write_patch


RC7_RUNTIME_STATUS_TOOL = "mcp__pfc_aitest_rc7__runtime_status"


def _activate_rc7_mcp() -> None:
    # Keep the already-qualified vertical-slice runner intact while replacing
    # only the DSH patch/server surface. This is intentionally explicit so RC6
    # remains frozen and RC7 owns its additive professional tools.
    _base.write_patch = _rc7_write_patch
    _base._RUNTIME_STATUS_TOOL = RC7_RUNTIME_STATUS_TOOL


def run_real_qualification(**kwargs):
    _activate_rc7_mcp()
    return _base.run_real_qualification(**kwargs)


def main(argv: Optional[list] = None) -> int:
    _activate_rc7_mcp()
    return _base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
