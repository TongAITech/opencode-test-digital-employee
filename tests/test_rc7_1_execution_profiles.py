from __future__ import annotations

from pathlib import Path

from rc6_runtime.authority import AuthorityRuntime
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.execution import (
    DEFAULT_EXECUTION_PROFILES,
    ExecutionProfileRegistry,
    ExecutionRuntime,
    LayerExecutionProfile,
)
from rc7_runtime.authority import RC7AuthorityRuntime, execution_session_id
from rc7_runtime.execution_profiles import RC7_1_EXECUTION_PROFILES
from rc7_runtime.runtime_execution import RuntimeOwnedExecutionCoordinator


def _oracle(*_args, **_kwargs):
    return {"passed": False}


def test_importing_rc7_does_not_mutate_rc6_default_profiles() -> None:
    registry = ExecutionProfileRegistry()

    assert DEFAULT_EXECUTION_PROFILES["L4"].required_tools == ("browser-skill",)
    assert DEFAULT_EXECUTION_PROFILES["L5"].required_tools == ("e2e-orchestrator",)
    assert DEFAULT_EXECUTION_PROFILES["L6"].required_tools == ("k6",)
    assert DEFAULT_EXECUTION_PROFILES["L7"].required_tools == ("zap",)
    assert DEFAULT_EXECUTION_PROFILES["L5"].action_kind == "CROSS_SYSTEM_E2E"
    assert DEFAULT_EXECUTION_PROFILES["L6"].action_kind == "PERFORMANCE"
    assert DEFAULT_EXECUTION_PROFILES["L7"].action_kind == "SECURITY"

    assert registry.get("L5") == DEFAULT_EXECUTION_PROFILES["L5"]
    assert registry.get("L6") == DEFAULT_EXECUTION_PROFILES["L6"]
    assert registry.get("L7") == DEFAULT_EXECUTION_PROFILES["L7"]


def test_plain_rc6_runtime_keeps_rc6_profiles_after_rc7_import() -> None:
    runtime = ExecutionRuntime(
        authority=AuthorityRuntime(b"rc6-profile-isolation-key"),
        tool_broker=ToolCapabilityBroker(),
        oracle_evaluator=_oracle,
    )
    assert runtime.profiles.get("L5") == DEFAULT_EXECUTION_PROFILES["L5"]
    assert runtime.profiles.get("L6") == DEFAULT_EXECUTION_PROFILES["L6"]
    assert runtime.profiles.get("L7") == DEFAULT_EXECUTION_PROFILES["L7"]


def test_rc7_runtime_gets_corrected_profiles_without_global_mutation() -> None:
    runtime = ExecutionRuntime(
        authority=RC7AuthorityRuntime(b"rc7-profile-isolation-key"),
        tool_broker=ToolCapabilityBroker(),
        oracle_evaluator=_oracle,
    )
    for layer in ("L4", "L5", "L6", "L7"):
        assert runtime.profiles.get(layer) == RC7_1_EXECUTION_PROFILES[layer]

    assert runtime.profiles.get("L5").required_tools == ("api-runtime",)
    assert runtime.profiles.get("L6").required_tools == ("capability-runtime",)
    assert runtime.profiles.get("L7").required_tools == ("e2e-orchestrator",)
    assert runtime.profiles.get("L5").action_kind == "API_CONTRACT"
    assert runtime.profiles.get("L6").action_kind == "CAPABILITY_EXECUTION"
    assert runtime.profiles.get("L7").action_kind == "CROSS_LAYER_E2E"

    # Creating an RC7 runtime must still leave RC6 defaults untouched.
    assert DEFAULT_EXECUTION_PROFILES["L5"].required_tools == ("e2e-orchestrator",)
    assert DEFAULT_EXECUTION_PROFILES["L6"].required_tools == ("k6",)
    assert DEFAULT_EXECUTION_PROFILES["L7"].required_tools == ("zap",)


def test_explicit_profiles_are_never_overridden_by_rc7_injection() -> None:
    explicit = dict(RC7_1_EXECUTION_PROFILES)
    explicit["L5"] = LayerExecutionProfile(
        "L5",
        "L5_EXECUTE",
        ("explicit-api-runtime",),
        "EXPLICIT_API_CONTRACT",
    )
    runtime = ExecutionRuntime(
        authority=RC7AuthorityRuntime(b"rc7-explicit-profile-key"),
        tool_broker=ToolCapabilityBroker(),
        oracle_evaluator=_oracle,
        profiles=explicit,
    )
    assert runtime.profiles.get("L5") == explicit["L5"]


def test_runtime_owned_coordinator_uses_rc7_profiles_without_touching_rc6(tmp_path: Path) -> None:
    coordinator = RuntimeOwnedExecutionCoordinator(evidence_root=str(tmp_path))
    assert coordinator.profiles.get("L5") == RC7_1_EXECUTION_PROFILES["L5"]
    assert coordinator.profiles.get("L6") == RC7_1_EXECUTION_PROFILES["L6"]
    assert coordinator.profiles.get("L7") == RC7_1_EXECUTION_PROFILES["L7"]
    assert DEFAULT_EXECUTION_PROFILES["L6"].required_tools == ("k6",)


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
