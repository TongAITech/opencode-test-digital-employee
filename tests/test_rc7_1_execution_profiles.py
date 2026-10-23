from __future__ import annotations

from rc6_runtime.execution import ExecutionProfileRegistry
from rc7_runtime.authority import RC7AuthorityRuntime, execution_session_id
from rc7_runtime.execution_profiles import RC7_1_EXECUTION_PROFILES


def test_rc7_runtime_bootstrap_installs_corrected_l4_to_l7_profiles() -> None:
    # Importing rc7_runtime has already installed the process-local overlay.
    registry = ExecutionProfileRegistry()
    assert registry.get("L4") == RC7_1_EXECUTION_PROFILES["L4"]
    assert registry.get("L5") == RC7_1_EXECUTION_PROFILES["L5"]
    assert registry.get("L6") == RC7_1_EXECUTION_PROFILES["L6"]
    assert registry.get("L7") == RC7_1_EXECUTION_PROFILES["L7"]

    assert registry.get("L4").required_tools == ("browser-skill",)
    assert registry.get("L5").required_tools == ("api-runtime",)
    assert registry.get("L6").required_tools == ("capability-runtime",)
    assert registry.get("L7").required_tools == ("e2e-orchestrator",)

    assert registry.get("L5").action_kind == "API_CONTRACT"
    assert registry.get("L6").action_kind == "CAPABILITY_EXECUTION"
    assert registry.get("L7").action_kind == "CROSS_LAYER_E2E"


def test_execution_identity_session_is_runtime_bound_not_caller_authored() -> None:
    authority = RC7AuthorityRuntime(b"rc7-1-session-binding-test-key")
    identity = authority.issue_identity(
        "L5_EXECUTE",
        "EXECUTION",
        "L5",
        0,
        "caller-supplied-session-must-not-win",
    )
    assert identity.session_id == execution_session_id(identity.worker_id)
    assert identity.session_id != "caller-supplied-session-must-not-win"
    assert authority._require_identity(identity.worker_id).session_id == identity.session_id


def test_non_execution_identity_keeps_declared_session_semantics() -> None:
    authority = RC7AuthorityRuntime(b"rc7-1-session-binding-test-key")
    identity = authority.issue_identity(
        "RC7_CODE_WORKER",
        "CODE_ANALYSIS",
        None,
        0,
        "code-session-001",
    )
    assert identity.session_id == "code-session-001"
