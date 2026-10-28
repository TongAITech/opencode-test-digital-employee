"""Phase 2 additive R1 semantics.

The Phase 1 transition validator intentionally froze only the initial lifecycle
kinds. N7 failure handoff to N8 is not a PASS forward edge and is not a semantic
back-edge, so Phase 2 registers an explicit DIAGNOSIS kind while reusing the
same canonical transition artifact/event type.
"""
from . import rc72_truth as _truth_contract


def install_rc72_phase2_truth_overlay() -> None:
    _truth_contract.install_rc72_truth_overlay()
    _truth_contract._TRANSITION_KINDS.add("DIAGNOSIS")


install_rc72_phase2_truth_overlay()
