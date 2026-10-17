from __future__ import annotations

import pytest

from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.bank_dsh_tool_policy import (
    CODE_PRODUCER_TOOLS,
    CODE_REVIEWER_TOOLS,
    FIELD_NODE_POLICIES,
    REQUIREMENT_PRODUCER_TOOLS,
    REQUIREMENT_REVIEWER_TOOLS,
    TEST_DESIGN_REVIEWER_TOOLS,
    extend_policy_tools,
    mcp_tool,
)


def test_bank_field_policy_signs_real_rc7_mcp_tool_names() -> None:
    required = {
        "REQUIREMENT_ANALYSIS": ["read_text", "truth_query"],
        "CODE_ANALYSIS": [
            "git_show_revision",
            "git_diff",
            "codegraph_mcp_tools",
            "codegraph_mcp_call",
        ],
        "TEST_DESIGN": ["truth_query", "artifact_record"],
        "SCRIPT_READINESS": [
            "executable_spec_build",
            "automation_reuse_resolve",
            "script_build",
            "script_validate",
        ],
        "EXECUTION": ["runner_execute", "execution_convergence"],
    }
    for node, names in required.items():
        allowed = FIELD_NODE_POLICIES[node].allowed_tools
        for name in names:
            assert mcp_tool(name) in allowed


def test_rc7_authority_accepts_exact_field_tool_from_policy() -> None:
    authority = RC7AuthorityRuntime(b"rc7-bank-field-tool-policy-key")
    policy = FIELD_NODE_POLICIES["CODE_ANALYSIS"]
    identity = authority.issue_identity(
        role=policy.role,
        phase=policy.phase,
        layer=None,
        generation=0,
        session_id="session-field-code",
    )
    lease = authority.issue_lease(
        identity.worker_id,
        scope_ref="TASK-CODE",
        allowed_artifact_types=policy.allowed_artifact_types,
        allowed_tools=policy.allowed_tools,
    )
    authority.authorize_tool(identity.worker_id, lease.lease_id, mcp_tool("git_diff"))
    authority.authorize_tool(identity.worker_id, lease.lease_id, mcp_tool("codegraph_mcp_call"))


def test_field_reviewer_tools_use_rc7_server_names_not_rc6() -> None:
    for tools in (REQUIREMENT_REVIEWER_TOOLS, CODE_REVIEWER_TOOLS, TEST_DESIGN_REVIEWER_TOOLS):
        assert any(name.startswith("mcp__pfc_aitest_rc7__") for name in tools)
        assert not any(name.startswith("mcp__pfc_aitest_rc6__") for name in tools)

    assert mcp_tool("read_text") in REQUIREMENT_REVIEWER_TOOLS
    assert mcp_tool("git_diff") in CODE_REVIEWER_TOOLS
    assert mcp_tool("codegraph_mcp_call") in TEST_DESIGN_REVIEWER_TOOLS


def test_field_policy_retains_legacy_aliases_without_relying_on_them() -> None:
    assert "filesystem" in REQUIREMENT_PRODUCER_TOOLS
    assert mcp_tool("read_text") in REQUIREMENT_PRODUCER_TOOLS
    assert "git" in CODE_PRODUCER_TOOLS
    assert mcp_tool("git_show_revision") in CODE_PRODUCER_TOOLS


def test_dynamic_field_plugin_extension_requires_exact_name() -> None:
    extended = extend_policy_tools(
        FIELD_NODE_POLICIES,
        node="EXECUTION",
        exact_tool_names=["mcp__browser_skill__browser_open"],
    )
    assert "mcp__browser_skill__browser_open" in extended["EXECUTION"].allowed_tools
    assert "mcp__browser_skill__browser_open" not in FIELD_NODE_POLICIES["EXECUTION"].allowed_tools

    with pytest.raises(ValueError, match="EXACT_DSH_TOOL_NAME_REQUIRED"):
        extend_policy_tools(
            FIELD_NODE_POLICIES,
            node="EXECUTION",
            exact_tool_names=["mcp__browser_skill__*"],
        )
