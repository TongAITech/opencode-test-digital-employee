"""RC7 DSH launcher with signed-lease tool authority enforced end to end.

The base launcher owns fresh-session lifecycle and durable R1 handoff evidence.
This RC7 overlay adds authority guarantees and timeout diagnostics without
changing the base RC6 worker contract:

1. The exact signed-lease tool set is exported to the package-local DSH tool
   policy plugin before the first model step, so generic built-ins are hidden.
2. Every tool call observed in a completed DSH run is re-authorized against the
   signed TaskLease before RC7 accepts the Worker event or handoff.
3. If DSH times out, any partial stdout/stderr is persisted as failure evidence
   and summarized in R1. Partial calls are diagnostics only; they are never
   promoted to WORKER_TOOL_CALLED or accepted handoff evidence.

The DSH-side restriction is preventative. The post-observation check is
fail-closed defense in depth; MCP calls additionally have their own durable
Mission/Task/node authorization in the RC7 MCP server.
"""
from __future__ import annotations

import json
import subprocess
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
            try:
                return super().execute(assignment, prompt)
            except AgentRuntimeError as exc:
                self._persist_timeout_diagnostic(assignment, exc)
                raise
        finally:
            if previous is None:
                self.env.pop(ALLOWED_TOOLS_ENV, None)
            else:
                self.env[ALLOWED_TOOLS_ENV] = previous

    @staticmethod
    def _partial_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    def _persist_timeout_diagnostic(
        self,
        assignment: WorkerAssignment,
        error: AgentRuntimeError,
    ) -> None:
        """Persist TimeoutExpired partial output without converting it to PASS evidence."""
        cause = error.__cause__
        if not isinstance(cause, subprocess.TimeoutExpired):
            return

        raw_stdout = getattr(cause, "stdout", None)
        if raw_stdout is None:
            raw_stdout = getattr(cause, "output", None)
        stdout = self._partial_text(raw_stdout)
        stderr = self._partial_text(getattr(cause, "stderr", None))
        raw_ref = self._persist_raw_worker_output(assignment, stdout, stderr)
        events = tuple(self._parse_json_lines(stdout))
        calls = self._tool_calls(events)
        session_id = self._session_id(events)
        self.emit_control_event(
            "ROUTING_INTEGRITY_FAIL",
            assignment.mission_id,
            reason="DSH_WORKER_TIMEOUT_PARTIAL",
            worker_instance_id=assignment.worker_instance_id,
            assignment_id=assignment.assignment_id,
            lease_id=assignment.lease.lease_id,
            raw_output_ref=raw_ref,
            timeout_seconds=self.timeout_seconds,
            partial_event_count=len(events),
            partial_tool_call_count=len(calls),
            partial_session_id=session_id,
        )

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
