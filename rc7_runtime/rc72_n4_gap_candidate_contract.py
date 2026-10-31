"""RC7.2 N4 explicit-gap candidate compatibility contract.

N4 workers are forbidden to invent a TestCase when parent evidence is
insufficient.  A handoff may therefore legitimately contain obligations plus an
explicit gap and zero cases.  The canonical N4 gate still cannot PASS such a
delivery; this overlay only lets the raw candidate enter the review/repair
loop.

The inherited N4 validator already enforces the desired rule after case
validation: every required obligation not covered by a case requires an
explicit gap.  Its list helper, however, rejects an empty ``cases`` list before
that rule can run.  Patch only that helper call-site semantic: ``cases=[]`` is
allowed to reach the existing uncovered-obligation/gap check.  All other object
lists remain non-empty and all no-gap empty-case candidates still fail closed.
"""
from __future__ import annotations

from typing import Any, Dict, List

from . import rc72_n4_test_design_handoff as _handoff


_ORIGINAL_REQUIRE_OBJECT_LIST = _handoff._require_object_list


def _gap_aware_object_list(value: Any, name: str) -> List[Dict[str, Any]]:
    if name == "cases" and isinstance(value, list) and not value:
        return []
    return _ORIGINAL_REQUIRE_OBJECT_LIST(value, name)


def install_rc72_n4_gap_candidate_contract() -> None:
    """Allow only the existing explicit-gap path to carry zero N4 cases."""

    if _handoff._require_object_list is not _gap_aware_object_list:
        _handoff._require_object_list = _gap_aware_object_list


__all__ = ["install_rc72_n4_gap_candidate_contract"]
