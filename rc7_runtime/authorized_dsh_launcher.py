"""RC7 DSH launcher with signed-lease tool authority enforced end to end.

The base launcher owns fresh-session lifecycle and durable R1 handoff evidence.
This RC7 overlay adds two authority guarantees without changing RC6 semantics:

1. The exact signed-lease tool set is exported to the package-local DSH tool
   policy plugin before the first model step, so generic built-ins are hidden.
2. Every tool call observed in DSH output is re-authorized against the signed
   TaskLease before RC7 accepts the Worker event or handoff.

The DSH-side restriction is preventative.  The post-observation check is
fail-closed defense in depth; MCP calls additionally have their own durable
Mission/Task/node authorization in the RC7 MCP server.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from rc6_runtime.agent_runtime import (
    AgentRuntimeError,
    DshHeadlessWorkerLauncher,
    WorkerAssignment,
    WorkerInvocation,
)
from rc6_runtime.authority import AuthorityError


ALLOWED_TOOLS_ENV = "PFC_RC7_DSH_ALLOWED_TOOLS"


class Rc7AuthorizedDshHeadlessWorkerLauncher(DshHeadlessWorkerLauncher):
    """Run RC7 workers with model-visible and observed-call lease enforcement."""

    def execute(
        self,
        assignment: WorkerAssignment,
        prompt: str,
    ) -> Tuple[WorkerInvocation, Dict[str, Any]]:
        previous = self.env.get(ALLOWED_TOOLS_ENV)
        self.env[ALLOWED_TOOLS_ENV] = json.dumps(
            list(assignment.allowed_tools),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            return super().execute(assignment, prompt)
        finally:
            if previous is None:
                self.env.pop(ALLOWED_TOOLS_ENV, None)
            else:
                self.env[ALLOWED_TOOLS_ENV] = previous

    def _authorize_observed_tool(self, invocation: WorkerInvocation, tool_name: str) -> None:
        if not tool_name:
            self._emit_routing_fail(invocation.mission_id, "TOOL_CALL_NAME_MISSING")
            raise AgentRuntimeError("ROUTING_INTEGRITY_FAIL:TOOL_CALL_NAME_MISSING")
        try:
            self.authority.authorize_tool(
                invocation.worker_instance_id,
                invocation.lease_id,
                tool_name,
            )
        except AuthorityError as exc:
            self._emit_routing_fail(
                invocation.mission_id,
                "LEASE_TOOL_AUTHORIZATION_FAILED:%s" % exc,
            )
            raise AgentRuntimeError(
                "ROUTING_INTEGRITY_FAIL:LEASE_TOOL_AUTHORIZATION_FAILED"
            ) from exc

    def _emit(
        self,
        event_name: str,
        invocation: WorkerInvocation,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if event_name == "WORKER_TOOL_CALLED":
            call = (extra or {}).get("tool_call")
            tool_name = call.get("tool_name") if isinstance(call, dict) else None
            self._authorize_observed_tool(invocation, str(tool_name or ""))
        elif event_name == "HANDOFF_RETURNED":
            for call in invocation.tool_calls:
                tool_name = call.get("tool_name") if isinstance(call, dict) else None
                self._authorize_observed_tool(invocation, str(tool_name or ""))
        return super()._emit(event_name, invocation, extra)
