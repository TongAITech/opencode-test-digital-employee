"""RC7 DSH launcher with signed-lease tool authority enforced end to end.

The base launcher owns fresh-session lifecycle and durable R1 handoff evidence.
This RC7 overlay adds authority guarantees and timeout diagnostics without
changing the base RC6 worker contract:

1. The exact signed-lease tool set is exported to the package-local DSH tool
   policy plugin before the first model step, so generic built-ins are hidden.
2. The runtime-issued worker/mission/task/lease identity is projected into the
   DSH/MCP subprocess environment and into the prompt. Model-supplied identity
   is never authority; it must match this trusted projection.
3. Every tool call observed in a completed DSH run is re-authorized against the
   signed TaskLease before RC7 accepts the Worker event or handoff.
4. If DSH times out, any partial stdout/stderr is persisted as failure evidence
   and summarized in R1. Partial calls are diagnostics only; they are never
   promoted to WORKER_TOOL_CALLED or accepted handoff evidence.
5. If a provider explicitly returns an HTTP rate-limit error before strict JSON
   handoff, preserve that external failure class in R1 instead of mislabeling it
   as a model JSON-format failure.

The DSH-side restriction and MCP pre-execution check are preventative. The
post-observation signed-lease check is fail-closed defense in depth.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from rc6_runtime.agent_runtime import (
    AgentRuntimeError,
    DshHeadlessWorkerLauncher,
    WorkerAssignment,
    WorkerInvocation,
)
from rc6_runtime.authority import AuthorityError


ALLOWED_TOOLS_ENV = "PFC_RC7_DSH_ALLOWED_TOOLS"
MCP_MISSION_ID_ENV = "PFC_RC7_MCP_MISSION_ID"
MCP_TASK_ID_ENV = "PFC_RC7_MCP_TASK_ID"
MCP_WORKER_ID_ENV = "PFC_RC7_MCP_WORKER_ID"
MCP_LEASE_ID_ENV = "PFC_RC7_MCP_LEASE_ID"
MCP_SCOPE_REF_ENV = "PFC_RC7_MCP_SCOPE_REF"

_PROVIDER_RATE_LIMIT_MARKERS = (
    "rate_limit",
    "free_daily_limit",
    "free_global_rate_limited",
    "too many requests",
)


class Rc7AuthorizedDshHeadlessWorkerLauncher(DshHeadlessWorkerLauncher):
    """Run RC7 workers with model-visible and observed-call lease enforcement."""

    def _runtime_task_id(self, assignment: WorkerAssignment) -> str:
        scope = str(assignment.scope or "").strip()
        if scope.startswith("task:") and scope[len("task:") :].strip():
            return scope[len("task:") :].strip()
        rows = self.truth.query("rc7_artifact", artifact_id=scope) if scope else []
        if len(rows) == 1:
            task_id = str(rows[0].get("producer_task_id") or "").strip()
            if task_id:
                return task_id
        return ""

    @staticmethod
    def _bind_runtime_identity_prompt(
        prompt: str,
        assignment: WorkerAssignment,
        task_id: str,
    ) -> str:
        if not task_id:
            return prompt
        context = {
            "mission_id": assignment.mission_id,
            "task_id": task_id,
            "worker_id": assignment.worker_instance_id,
        }
        return (
            "RC7_RUNTIME_MISSION_CONTEXT="
            + json.dumps(context, ensure_ascii=False, sort_keys=True)
            + "\nFor every allowed mcp__pfc_aitest_rc7__* native tool call, include "
            "mission_context exactly equal to RC7_RUNTIME_MISSION_CONTEXT. Never invent, "
            "abbreviate, substitute, or reuse a logical role name as worker_id. If an embedded "
            "MANDATORY_FIRST_ACTION omits mission_context, augment only its arguments with this "
            "exact mission_context; do not change the tool name or any other argument.\n"
            + prompt
        )

    def execute(
        self,
        assignment: WorkerAssignment,
        prompt: str,
    ) -> Tuple[WorkerInvocation, Dict[str, Any]]:
        task_id = self._runtime_task_id(assignment)
        projected = {
            ALLOWED_TOOLS_ENV: json.dumps(
                list(assignment.allowed_tools),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            MCP_MISSION_ID_ENV: assignment.mission_id,
            MCP_TASK_ID_ENV: task_id,
            MCP_WORKER_ID_ENV: assignment.worker_instance_id,
            MCP_LEASE_ID_ENV: assignment.lease.lease_id,
            MCP_SCOPE_REF_ENV: assignment.lease.scope_ref,
        }
        previous = {key: self.env.get(key) for key in projected}
        self.env.update(projected)
        bound_prompt = self._bind_runtime_identity_prompt(prompt, assignment, task_id)
        try:
            try:
                return super().execute(assignment, bound_prompt)
            except AgentRuntimeError as exc:
                self._persist_timeout_diagnostic(assignment, exc)
                raise
        finally:
            for key, value in previous.items():
                if value is None:
                    self.env.pop(key, None)
                else:
                    self.env[key] = value

    @staticmethod
    def _partial_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    @staticmethod
    def _provider_failure_reason_from_text(text: str) -> str:
        """Classify only explicit provider 429/rate-limit evidence.

        Do not infer provider failure from missing JSON alone. Requiring both a
        429 signal and an explicit rate-limit marker keeps ordinary model-format
        failures classified as STRICT_JSON_OUTPUT_MISSING.
        """
        lowered = str(text or "").lower()
        if "429" not in lowered:
            return ""
        if any(marker in lowered for marker in _PROVIDER_RATE_LIMIT_MARKERS):
            return "MODEL_PROVIDER_RATE_LIMIT"
        return ""

    def _raw_failure_text(self, raw_ref: str) -> str:
        """Read only this launcher's already-persisted evidence under state_root."""
        if not isinstance(raw_ref, str) or not raw_ref.startswith("file://"):
            return ""
        path = Path(raw_ref[len("file://") :]).expanduser().resolve()
        try:
            path.relative_to(self.state_root)
        except ValueError:
            return ""
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _fail_invocation(
        self,
        invocation: WorkerInvocation,
        exit_code: int,
        raw_ref: str,
        reason: str,
    ) -> None:
        mapped_reason = reason
        if reason == "STRICT_JSON_OUTPUT_MISSING":
            provider_reason = self._provider_failure_reason_from_text(
                self._raw_failure_text(raw_ref)
            )
            if provider_reason:
                mapped_reason = provider_reason
                self.emit_control_event(
                    "ROUTING_INTEGRITY_FAIL",
                    invocation.mission_id,
                    reason=provider_reason,
                    worker_instance_id=invocation.worker_instance_id,
                    assignment_id=invocation.assignment_id,
                    lease_id=invocation.lease_id,
                    raw_output_ref=raw_ref,
                    original_failure=reason,
                )
        return super()._fail_invocation(
            invocation,
            exit_code,
            raw_ref,
            mapped_reason,
        )

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
