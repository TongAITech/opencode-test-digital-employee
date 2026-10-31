"""RC7.2 strict DSH final-JSON extraction overlay.

The inherited headless launcher scans every ``{`` in a final text event and
previously returned the last decodable mapping.  For nested strict JSON this can
select the last inner object (for example a coverage-link) instead of the outer
candidate contract.  RC7.2 N4 requires nested TestObligation/TestCase/Oracle
objects, so that behavior is unsafe and fails closed at the wrong boundary.

This overlay preserves the inherited launcher API and changes only object
selection: choose the decodable mapping whose JSON span ends furthest to the
right.  That selects the last complete outer object while still supporting
prose followed by JSON or multiple JSON objects in one final message.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher


def _last_complete_outer_json_object(text: str) -> Optional[Dict[str, Any]]:
    decoder = json.JSONDecoder()
    best: Optional[Tuple[int, int, Dict[str, Any]]] = None
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, relative_end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        absolute_end = start + relative_end
        candidate = (absolute_end, -start, value)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    return None if best is None else best[2]


def install_rc72_dsh_json_output_contract() -> None:
    """Install the RC7.2 nested strict-JSON selection rule package-wide."""

    DshHeadlessWorkerLauncher._last_json_object = staticmethod(
        _last_complete_outer_json_object
    )


__all__ = [
    "install_rc72_dsh_json_output_contract",
]
