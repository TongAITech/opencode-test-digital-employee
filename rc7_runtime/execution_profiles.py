"""RC7.1 execution-profile isolation bound to the shared canonical layer registry.

RC7.1 MUST NOT redefine L1-L7 meanings.  The canonical autonomous-loop contract
uses the historical execution taxonomy: L5 cross-system E2E, L6 performance and
L7 security. API contract is an L3 dimension; capability execution is Runtime
infrastructure. Importing RC7 still never mutates RC6 global defaults.
"""
from __future__ import annotations

from typing import Dict

import rc6_runtime.execution as rc6_execution
from rc6_runtime.execution import LayerExecutionProfile

from .autonomous_contract import canonical_execution_profile_specs


RC7_1_EXECUTION_PROFILES: Dict[str, LayerExecutionProfile] = {
    layer: LayerExecutionProfile(
        layer,
        str(spec["role"]),
        tuple(spec["required_tools"]),
        str(spec["action_kind"]),
    )
    for layer, spec in canonical_execution_profile_specs().items()
}


def _is_rc7_authority(authority: object) -> bool:
    cls = authority.__class__
    return cls.__name__ == "RC7AuthorityRuntime" and cls.__module__ == "rc7_runtime.authority"


def install_rc7_1_execution_profiles() -> None:
    """Inject canonical RC7.1 profiles into RC7-owned ExecutionRuntime only."""
    current = rc6_execution.ExecutionRuntime.__init__
    if getattr(current, "_rc7_1_profile_isolation", False):
        return

    original = current

    def isolated_init(
        self,
        *,
        authority,
        tool_broker,
        oracle_evaluator,
        profiles=None,
    ):
        selected = profiles
        if selected is None and _is_rc7_authority(authority):
            selected = RC7_1_EXECUTION_PROFILES
        original(
            self,
            authority=authority,
            tool_broker=tool_broker,
            oracle_evaluator=oracle_evaluator,
            profiles=selected,
        )

    isolated_init._rc7_1_profile_isolation = True  # type: ignore[attr-defined]
    isolated_init._rc7_1_original_init = original  # type: ignore[attr-defined]
    rc6_execution.ExecutionRuntime.__init__ = isolated_init


def install_rc7_1_runtime_owned_coordinator_profiles() -> None:
    """Bind the RC7 compatibility coordinator to the canonical RC7 registry."""
    from .runtime_execution import RuntimeOwnedExecutionCoordinator

    current = RuntimeOwnedExecutionCoordinator.__init__
    if getattr(current, "_rc7_1_profile_isolation", False):
        return
    original = current

    def isolated_coordinator_init(self, *, evidence_root: str, timeout_seconds: int = 300) -> None:
        original(self, evidence_root=evidence_root, timeout_seconds=timeout_seconds)
        self.profiles = rc6_execution.ExecutionProfileRegistry(RC7_1_EXECUTION_PROFILES)

    isolated_coordinator_init._rc7_1_profile_isolation = True  # type: ignore[attr-defined]
    isolated_coordinator_init._rc7_1_original_init = original  # type: ignore[attr-defined]
    RuntimeOwnedExecutionCoordinator.__init__ = isolated_coordinator_init
