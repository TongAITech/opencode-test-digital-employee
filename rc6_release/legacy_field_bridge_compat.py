from __future__ import annotations

from typing import List, Optional

from . import legacy_field_bridge as _base

# The historical RC5/G3 offline CodeGraph payload is the pinned CodeGraph
# server asset, not codegraph.exe. Keep this compatibility binding outside the
# generic bootstrap so the RC6 runtime can reuse an already-installed payload
# without changing its graph-only authority contract.
_codegraph = _base.TOOL_BINDINGS['codegraph']
_codegraph['names'] = tuple(dict.fromkeys(tuple(_codegraph['names']) + (
    'codegraph-server-win32-x64.exe',
    'codegraph-server.exe',
)))

build_bindings = _base.build_bindings
write_env = _base.write_env


def main(argv: Optional[List[str]] = None) -> int:
    return _base.main(argv)


if __name__ == '__main__':
    raise SystemExit(main())
