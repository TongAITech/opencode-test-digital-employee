"""Durable RC7 MCP tool authority derived from canonical R1 Task truth.

DSH MCP servers run in a subprocess, so they cannot trust the parent Python
process's in-memory TaskLease registry.  This module reconstructs the execution
authority boundary from the canonical R1 Task row and the frozen Bank-field
node policy before a tool body is allowed to run.
"""
from __future__ import annotations

from typing import Mapping

from rc6_runtime.truth import TruthRuntime

from .bank_dsh_tool_policy import FIELD_NODE_POLICIES, mcp_tool
from .execution_chain_evidence import CHAIN_TOOLS


class McpToolAuthorityError(RuntimeError):
    pass


_CHAIN_TASK_NODES = {"FAILURE_DIAGNOSIS", "RECOVERY_RETRY", "DEFECT_REVIEW"}
_CHAIN_EXTRA_TOOLS = {"attempt_cat_query"}


def _task_row(truth: TruthRuntime, mission_id: str, task_id: str) -> Mapping[str, object]:
    rows = truth.query("rc7_task", task_id=task_id)
    if len(rows) != 1:
        raise McpToolAuthorityError("MCP_AUTH_TASK_NOT_UNIQUE")
    row = rows[0]
    if str(row.get("mission_id") or "") != mission_id:
        raise McpToolAuthorityError("MCP_AUTH_TASK_MISSION_MISMATCH")
    return row


def authorize_mcp_tool(
    truth: TruthRuntime,
    *,
    mission_id: str,
    task_id: str,
    worker_id: str,
    tool_name: str,
) -> Mapping[str, object]:
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

    node = str(row.get("node") or "").strip()
    policy = FIELD_NODE_POLICIES.get(node)
    if policy is not None:
        qualified = mcp_tool(tool_name)
        if qualified not in set(policy.allowed_tools):
            raise McpToolAuthorityError(
                "MCP_AUTH_TOOL_NOT_ALLOWED:%s:%s" % (node, tool_name)
            )
        return row

    if node in _CHAIN_TASK_NODES:
        if tool_name not in set(CHAIN_TOOLS) | _CHAIN_EXTRA_TOOLS:
            raise McpToolAuthorityError(
                "MCP_AUTH_CHAIN_TOOL_NOT_ALLOWED:%s:%s" % (node, tool_name)
            )
        return row

    raise McpToolAuthorityError("MCP_AUTH_NODE_POLICY_REQUIRED:%s" % node)
