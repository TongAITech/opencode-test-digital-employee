"""RC7.1 production execution-profile isolation.

RC6's historical defaults intentionally remain frozen: L5 cross-system E2E,
L6 k6 performance and L7 ZAP security. RC7.1 uses a different layer taxonomy
for its autonomous execution product path. Importing RC7 must therefore never
rewrite ``rc6_runtime.execution.DEFAULT_EXECUTION_PROFILES`` for the whole
process.

The primary installer is deliberately narrow. It wraps ``ExecutionRuntime``
once and injects RC7.1 profiles only when the runtime is owned by
``RC7AuthorityRuntime`` and the caller did not explicitly provide profiles.
Ordinary RC6 runtimes and explicit custom registries remain in control of their
own semantics.

RC7 also retains ``RuntimeOwnedExecutionCoordinator`` as a compatibility/formal
execution entry point. Its local registry is isolated separately after that
module has loaded, so it cannot fall back to RC6's L5/L6/L7 taxonomy once the
global mutation is removed.
"""
from __future__ import annotations

from typing import Dict

import rc6_runtime.execution as rc6_execution
from rc6_runtime.execution import LayerExecutionProfile


RC7_1_EXECUTION_PROFILES: Dict[str, LayerExecutionProfile] = {
    "L1": LayerExecutionProfile("L1", "L1_EXECUTE", ("maven", "junit"), "CODE_UNIT"),
    "L2": LayerExecutionProfile("L2", "L2_EXECUTE", ("database",), "DB_COMPONENT"),
    "L3": LayerExecutionProfile("L3", "L3_EXECUTE", ("api-runtime",), "API_SERVICE"),
    "L4": LayerExecutionProfile("L4", "L4_EXECUTE", ("browser-skill",), "UI_BROWSER"),
    "L5": LayerExecutionProfile("L5", "L5_EXECUTE", ("api-runtime",), "API_CONTRACT"),
    "L6": LayerExecutionProfile("L6", "L6_EXECUTE", ("capability-runtime",), "CAPABILITY_EXECUTION"),
    "L7": LayerExecutionProfile("L7", "L7_EXECUTE", ("e2e-orchestrator",), "CROSS_LAYER_E2E"),
}


def _is_rc7_authority(authority: object) -> bool:
    cls = authority.__class__
    return cls.__name__ == "RC7AuthorityRuntime" and cls.__module__ == "rc7_runtime.authority"


def install_rc7_1_execution_profiles() -> None:
    """Inject RC7.1 profiles into RC7-owned ExecutionRuntime instances only."""
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
    """Bind the RC7 compatibility coordinator to an RC7-only profile registry."""
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
