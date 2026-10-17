"""Bank-field DSH tool-name policy for RC7 autonomous Mission wiring.

DSH reports fully-qualified plugin/MCP tool names (for example
``mcp__pfc_aitest_rc7__git_diff``) to the launcher.  AuthorityRuntime validates
those names *exactly* against the signed lease.  The generic capability labels
used by older unit fakes (``git``, ``filesystem`` and so on) are therefore not
sufficient for a real Bank host.

This module is additive: legacy aliases remain admitted for compatibility, but
field wiring must use these policies so the exact RC7 MCP names are signed into
the Worker lease before a real call occurs.
"""
from __future__ import annotations

from typing import Dict, Iterable, Mapping, Sequence, Tuple

from .dsh_worker_bridge import DshNodePolicy


RC7_MCP_SERVER = "pfc_aitest_rc7"


def mcp_tool(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        raise ValueError("MCP_TOOL_NAME_REQUIRED")
    return "mcp__%s__%s" % (RC7_MCP_SERVER, value)


def _tools(*names: str, legacy: Sequence[str] = ()) -> Tuple[str, ...]:
    values = list(legacy)
    values.extend(mcp_tool(name) for name in names)
    return tuple(dict.fromkeys(values))


RUNTIME_READ_TOOLS = _tools(
    "runtime_status",
    "truth_query",
    legacy=("runtime_status", "truth_query"),
)

REQUIREMENT_PRODUCER_TOOLS = _tools(
    "read_text",
    "truth_query",
    legacy=("filesystem", "read_text", "truth_query"),
)

CODE_PRODUCER_TOOLS = _tools(
    "git_show_revision",
    "git_diff",
    "codegraph_probe",
    "codegraph_query",
    "codegraph_mcp_tools",
    "codegraph_mcp_call",
    legacy=("git", "codegraph"),
)

TEST_DESIGN_PRODUCER_TOOLS = _tools(
    "read_text",
    "truth_query",
    "artifact_record",
    "codegraph_probe",
    "codegraph_query",
    "codegraph_mcp_tools",
    "codegraph_mcp_call",
    legacy=("filesystem", "codegraph", "read_text", "truth_query", "artifact_record"),
)

SCRIPT_PRODUCER_TOOLS = _tools(
    "truth_query",
    "executable_spec_build",
    "automation_reuse_resolve",
    "script_build",
    "script_validate",
    legacy=(
        "filesystem",
        "pytest",
        "junit",
        "truth_query",
        "executable_spec_build",
        "automation_reuse_resolve",
        "script_build",
        "script_validate",
    ),
)

EXECUTION_PRODUCER_TOOLS = _tools(
    "truth_query",
    "case_prepare_plan",
    "case_prepare_execute",
    "runner_execute",
    "attempt_cat_query",
    "failure_diagnose",
    "recovery_decide",
    "recovery_execute",
    "execution_convergence",
    legacy=("api", "browser", "database", "cat"),
)

DEFECT_TOOLS = _tools(
    "truth_query",
    "git_show_revision",
    "git_diff",
    "codegraph_probe",
    "codegraph_query",
    "codegraph_mcp_tools",
    "codegraph_mcp_call",
    "attempt_cat_query",
    legacy=("git", "codegraph", "cat"),
)

RUNTIME_RECOVERY_TOOLS = _tools(
    "runtime_status",
    "truth_query",
    "read_text",
    "recovery_decide",
    "recovery_execute",
    "execution_convergence",
    legacy=("filesystem",),
)

REQUIREMENT_REVIEWER_TOOLS = _tools(
    "runtime_status",
    "truth_query",
    "read_text",
    legacy=("runtime_status", "truth_query", "read_text"),
)

CODE_REVIEWER_TOOLS = _tools(
    "runtime_status",
    "git_show_revision",
    "git_diff",
    "codegraph_probe",
    "codegraph_query",
    "codegraph_mcp_tools",
    "codegraph_mcp_call",
    legacy=("runtime_status", "git", "codegraph"),
)

TEST_DESIGN_REVIEWER_TOOLS = _tools(
    "runtime_status",
    "truth_query",
    "read_text",
    "codegraph_probe",
    "codegraph_query",
    "codegraph_mcp_tools",
    "codegraph_mcp_call",
    legacy=("runtime_status", "truth_query", "read_text", "codegraph"),
)


FIELD_NODE_POLICIES: Mapping[str, DshNodePolicy] = {
    "REQUIREMENT_ANALYSIS": DshNodePolicy(
        agent_id="requirement-analysis",
        role="RC7_REQUIREMENT_WORKER",
        phase="ANALYSIS",
        allowed_artifact_types=("rc7_requirement_candidate",),
        allowed_tools=REQUIREMENT_PRODUCER_TOOLS,
    ),
    "CODE_ANALYSIS": DshNodePolicy(
        agent_id="code-analysis",
        role="RC7_CODE_WORKER",
        phase="ANALYSIS",
        allowed_artifact_types=("rc7_code_candidate",),
        allowed_tools=CODE_PRODUCER_TOOLS,
    ),
    "TEST_DESIGN": DshNodePolicy(
        agent_id="test-design",
        role="RC7_TEST_DESIGN_WORKER",
        phase="DESIGN",
        allowed_artifact_types=("rc7_test_design_candidate",),
        allowed_tools=TEST_DESIGN_PRODUCER_TOOLS,
    ),
    "SCRIPT_READINESS": DshNodePolicy(
        agent_id="test-automation",
        role="RC7_SCRIPT_WORKER",
        phase="AUTOMATION",
        allowed_artifact_types=("rc7_script_candidate",),
        allowed_tools=SCRIPT_PRODUCER_TOOLS,
    ),
    "EXECUTION": DshNodePolicy(
        agent_id="test-execution",
        role="RC7_EXECUTION_WORKER",
        phase="EXECUTION",
        allowed_artifact_types=("rc7_execution_candidate",),
        allowed_tools=EXECUTION_PRODUCER_TOOLS,
    ),
    "DEFECT": DshNodePolicy(
        agent_id="defect-analysis",
        role="RC7_DEFECT_WORKER",
        phase="DIAGNOSIS",
        allowed_artifact_types=("rc7_defect_candidate",),
        allowed_tools=DEFECT_TOOLS,
    ),
    "RUNTIME": DshNodePolicy(
        agent_id="runtime-recovery",
        role="RC7_RUNTIME_RECOVERY_WORKER",
        phase="RECOVERY",
        allowed_artifact_types=("rc7_runtime_candidate",),
        allowed_tools=RUNTIME_RECOVERY_TOOLS,
    ),
}


def extend_policy_tools(
    policies: Mapping[str, DshNodePolicy],
    *,
    node: str,
    exact_tool_names: Iterable[str],
) -> Dict[str, DshNodePolicy]:
    """Return a copy with extra *exact* field-discovered DSH tool names.

    This is intended for optional bank plugins whose tool names cannot be known
    at package-build time.  The caller must supply names obtained from trusted
    runtime discovery; wildcard/prefix authorization is deliberately unsupported.
    """
    output = dict(policies)
    if node not in output:
        raise ValueError("DSH_POLICY_NODE_UNKNOWN:%s" % node)
    extras = []
    for raw in exact_tool_names:
        value = str(raw or "").strip()
        if not value or "*" in value:
            raise ValueError("EXACT_DSH_TOOL_NAME_REQUIRED")
        extras.append(value)
    policy = output[node]
    output[node] = DshNodePolicy(
        agent_id=policy.agent_id,
        role=policy.role,
        phase=policy.phase,
        allowed_artifact_types=policy.allowed_artifact_types,
        allowed_tools=tuple(dict.fromkeys(policy.allowed_tools + tuple(extras))),
    )
    return output
