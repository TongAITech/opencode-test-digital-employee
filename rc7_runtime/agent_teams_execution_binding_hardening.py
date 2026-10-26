"""RC7.1 hardening for immutable DSH-session terminal provenance."""
from __future__ import annotations

from typing import Any, Dict, Mapping

from .agent_teams_execution_binding import (
    AgentTeamsExecutionBindingError,
    AgentTeamsExecutionBindingGate as _BaseAgentTeamsExecutionBindingGate,
)


class AgentTeamsExecutionBindingGate(_BaseAgentTeamsExecutionBindingGate):
    """Fail closed when terminal R1 events drift across DSH sessions."""

    def verify_terminal_and_persist(self, task: Any, team_binding: Any, invocation: Any):
        dsh_session_id = getattr(invocation, "dsh_session_id", None)
        if not isinstance(dsh_session_id, str) or not dsh_session_id.strip():
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_TERMINAL_DSH_SESSION_REQUIRED")
        expected_session = dsh_session_id.strip()
        expected_identity: Dict[str, str] = {
            "mission_id": task.mission_id,
            "worker_instance_id": str(getattr(invocation, "worker_instance_id", "") or ""),
            "assignment_id": str(getattr(invocation, "assignment_id", "") or ""),
            "attempt_id": str(getattr(invocation, "attempt_id", "") or ""),
            "lease_id": str(getattr(invocation, "lease_id", "") or ""),
            "parent_worker_id": str(getattr(invocation, "parent_worker_id", "") or ""),
        }
        rows = self.control.truth.query("agent_runtime_event", mission_id=task.mission_id)
        for event_name in self.REQUIRED_TERMINAL_EVENTS:
            identity_matches = [
                row
                for row in rows
                if self._terminal_identity_matches(row, event_name, expected_identity)
            ]
            if len(identity_matches) != 1:
                raise AgentTeamsExecutionBindingError(
                    "AGENT_TEAMS_TERMINAL_EVENT_NOT_UNIQUE:%s:%d"
                    % (event_name, len(identity_matches))
                )
            event_session = identity_matches[0].get("dsh_session_id")
            if event_session != expected_session:
                raise AgentTeamsExecutionBindingError(
                    "AGENT_TEAMS_TERMINAL_DSH_SESSION_MISMATCH:%s" % event_name
                )
        return super().verify_terminal_and_persist(task, team_binding, invocation)

    @staticmethod
    def _terminal_identity_matches(
        row: Mapping[str, Any], event_name: str, expected: Mapping[str, str]
    ) -> bool:
        if row.get("event_name") != event_name:
            return False
        return all(row.get(field) == value for field, value in expected.items())
