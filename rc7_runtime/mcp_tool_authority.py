"""Durable RC7 MCP tool authority derived from canonical R1 truth.

DSH MCP servers run in a subprocess, so they cannot trust model-supplied
identity. Producer calls can still be checked against the scheduler lease owner
for compatibility. Real field DSH calls additionally use a trusted runtime
projection created by the parent launcher from its signed TaskLease; that
projection is cross-checked against R1 WORKER_ADMITTED evidence, scope, and the
frozen node producer/reviewer tool policy before the tool body may execute.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from rc6_runtime.truth import TruthRuntime

from .bank_dsh_tool_policy import (
    CODE_REVIEWER_TOOLS,
    FIELD_NODE_POLICIES,
    REQUIREMENT_REVIEWER_TOOLS,
    TEST_DESIGN_REVIEWER_TOOLS,
    mcp_tool,
)
from .execution_chain_evidence import CHAIN_TOOLS


class McpToolAuthorityError(RuntimeError):
    pass


_CHAIN_TASK_NODES = {"FAILURE_DIAGNOSIS", "RECOVERY_RETRY", "DEFECT_REVIEW"}
_CHAIN_EXTRA_TOOLS = {"attempt_cat_query"}
_ACTIVE_RUNTIME_STATES = {"LEASED", "RUNNING", "OUTPUT_PRODUCED"}
_REVIEWER_TOOLS_BY_NODE = {
    "REQUIREMENT_ANALYSIS": REQUIREMENT_REVIEWER_TOOLS,
    "CODE_ANALYSIS": CODE_REVIEWER_TOOLS,
    "TEST_DESIGN": TEST_DESIGN_REVIEWER_TOOLS,
}


def _task_row(truth: TruthRuntime, mission_id: str, task_id: str) -> Mapping[str, object]:
    rows = truth.query("rc7_task", task_id=task_id)
    if len(rows) != 1:
        raise McpToolAuthorityError("MCP_AUTH_TASK_NOT_UNIQUE")
    row = rows[0]
    if str(row.get("mission_id") or "") != mission_id:
        raise McpToolAuthorityError("MCP_AUTH_TASK_MISSION_MISMATCH")
    return row


def _producer_node_tool_set(row: Mapping[str, object]) -> set[str]:
    node = str(row.get("node") or "").strip()
    policy = FIELD_NODE_POLICIES.get(node)
    if policy is not None:
        return set(policy.allowed_tools)
    if node in _CHAIN_TASK_NODES:
        return set(CHAIN_TOOLS) | _CHAIN_EXTRA_TOOLS
    raise McpToolAuthorityError("MCP_AUTH_NODE_POLICY_REQUIRED:%s" % node)


def _runtime_node_tool_set(row: Mapping[str, object]) -> set[str]:
    node = str(row.get("node") or "").strip()
    allowed = _producer_node_tool_set(row)
    allowed.update(_REVIEWER_TOOLS_BY_NODE.get(node, ()))
    return allowed


def _require_tool_in_policy(row: Mapping[str, object], tool_name: str, allowed: set[str]) -> None:
    node = str(row.get("node") or "").strip()
    qualified = mcp_tool(tool_name)
    if qualified in allowed or tool_name in allowed:
        return
    if node in _CHAIN_TASK_NODES:
        raise McpToolAuthorityError(
            "MCP_AUTH_CHAIN_TOOL_NOT_ALLOWED:%s:%s" % (node, tool_name)
        )
    raise McpToolAuthorityError(
        "MCP_AUTH_TOOL_NOT_ALLOWED:%s:%s" % (node, tool_name)
    )


def authorize_mcp_tool(
    truth: TruthRuntime,
    *,
    mission_id: str,
    task_id: str,
    worker_id: str,
    tool_name: str,
) -> Mapping[str, object]:
    """Compatibility path: authorize the current scheduler lease owner."""
    mission_id = str(mission_id or "").strip()
    task_id = str(task_id or "").strip()
    worker_id = str(worker_id or "").strip()
    tool_name = str(tool_name or "").strip()
    if not mission_id or not task_id or not worker_id or not tool_name:
        raise McpToolAuthorityError("MCP_AUTH_CONTEXT_AND_TOOL_REQUIRED")

    row = _task_row(truth, mission_id, task_id)
    state = str(row.get("state") or "").upper()
    if state not in {"LEASED", "RUNNING"}:
        raise McpToolAuthorityError("MCP_AUTH_ACTIVE_TASK_REQUIRED:%s" % state)
    lease_owner = str(row.get("lease_owner") or "").strip()
    if not lease_owner or lease_owner != worker_id:
        raise McpToolAuthorityError("MCP_AUTH_WORKER_NOT_LEASE_OWNER")

    _require_tool_in_policy(row, tool_name, _producer_node_tool_set(row))
    return row


def _runtime_admission(
    truth: TruthRuntime,
    *,
    mission_id: str,
    worker_id: str,
    lease_id: str,
    scope_ref: str,
) -> Mapping[str, object]:
    rows = truth.query(
        "agent_runtime_event",
        mission_id=mission_id,
        event_name="WORKER_ADMITTED",
        worker_instance_id=worker_id,
        lease_id=lease_id,
    )
    matching = [row for row in rows if str(row.get("scope") or "") == scope_ref]
    if len(matching) != 1:
        raise McpToolAuthorityError("MCP_AUTH_RUNTIME_ADMISSION_NOT_UNIQUE")
    return matching[0]


def _scope_authorizes_task(
    truth: TruthRuntime,
    *,
    mission_id: str,
    task_id: str,
    scope_ref: str,
) -> None:
    if scope_ref == "task:%s" % task_id:
        return

    artifacts = truth.query("rc7_artifact", artifact_id=scope_ref)
    if len(artifacts) != 1:
        raise McpToolAuthorityError("MCP_AUTH_SCOPE_ARTIFACT_NOT_UNIQUE")
    artifact = artifacts[0]
    if str(artifact.get("mission_id") or "") != mission_id:
        raise McpToolAuthorityError("MCP_AUTH_SCOPE_MISSION_MISMATCH")
    if str(artifact.get("producer_task_id") or "") != task_id:
        raise McpToolAuthorityError("MCP_AUTH_SCOPE_TASK_MISMATCH")


def authorize_mcp_tool_with_runtime_lease(
    truth: TruthRuntime,
    *,
    mission_id: str,
    task_id: str,
    worker_id: str,
    lease_id: str,
    scope_ref: str,
    allowed_tools: Iterable[str],
    tool_name: str,
) -> Mapping[str, object]:
    """Pre-execution authorization for a DSH child using parent-projected lease facts.

    The child does not possess the HMAC signing key. The parent is the only
    issuer/verifier of the signed TaskLease and projects its immutable facts into
    the child environment. Here we bind that projection back to durable R1
    admission + scope + node policy. After execution, the parent launcher again
    verifies every observed tool against the original signed TaskLease.
    """
    mission_id = str(mission_id or "").strip()
    task_id = str(task_id or "").strip()
    worker_id = str(worker_id or "").strip()
    lease_id = str(lease_id or "").strip()
    scope_ref = str(scope_ref or "").strip()
    tool_name = str(tool_name or "").strip()
    tools = tuple(str(value or "").strip() for value in allowed_tools)
    if (
        not mission_id
        or not task_id
        or not worker_id
        or not lease_id
        or not scope_ref
        or not tool_name
        or not tools
        or any(not value for value in tools)
    ):
        raise McpToolAuthorityError("MCP_AUTH_RUNTIME_LEASE_CONTEXT_REQUIRED")

    row = _task_row(truth, mission_id, task_id)
    state = str(row.get("state") or "").upper()
    if state not in _ACTIVE_RUNTIME_STATES:
        raise McpToolAuthorityError("MCP_AUTH_ACTIVE_RUNTIME_TASK_REQUIRED:%s" % state)

    _runtime_admission(
        truth,
        mission_id=mission_id,
        worker_id=worker_id,
        lease_id=lease_id,
        scope_ref=scope_ref,
    )
    _scope_authorizes_task(
        truth,
        mission_id=mission_id,
        task_id=task_id,
        scope_ref=scope_ref,
    )

    qualified = mcp_tool(tool_name)
    if qualified not in set(tools) and tool_name not in set(tools):
        raise McpToolAuthorityError("MCP_AUTH_RUNTIME_LEASE_TOOL_NOT_ALLOWED:%s" % tool_name)
    _require_tool_in_policy(row, tool_name, _runtime_node_tool_set(row))
    return row
