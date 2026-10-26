from __future__ import annotations

from types import SimpleNamespace

import pytest

from rc7_runtime.agent_teams_execution_binding import AgentTeamsExecutionBindingError
from rc7_runtime.agent_teams_execution_binding_hardening import AgentTeamsExecutionBindingGate
import rc7_runtime.agent_teams_integration as integration


EVENTS = (
    "WORKER_STARTED",
    "WORKER_OUTPUT_PRODUCED",
    "WORKER_COMPLETED",
    "HANDOFF_RETURNED",
)


class _Truth:
    def __init__(self, rows):
        self.rows = rows

    def query(self, entity_type, **filters):
        assert entity_type == "agent_runtime_event"
        return [
            row
            for row in self.rows
            if all(row.get(key) == value for key, value in filters.items())
        ]


class _Control:
    def __init__(self, rows):
        self.truth = _Truth(rows)


def _invocation(session_id="session-current"):
    return SimpleNamespace(
        worker_instance_id="worker-1",
        assignment_id="assignment-1",
        attempt_id="attempt-1",
        lease_id="lease-1",
        parent_worker_id="member-1",
        dsh_session_id=session_id,
    )


def _rows(session_id):
    base = {
        "mission_id": "mission-1",
        "worker_instance_id": "worker-1",
        "assignment_id": "assignment-1",
        "attempt_id": "attempt-1",
        "lease_id": "lease-1",
        "parent_worker_id": "member-1",
        "dsh_session_id": session_id,
    }
    return [dict(base, event_name=name) for name in EVENTS]


def test_terminal_events_from_different_dsh_session_fail_closed(tmp_path) -> None:
    gate = AgentTeamsExecutionBindingGate(
        _Control(_rows("session-stale")), evidence_root=str(tmp_path / "evidence")
    )
    task = SimpleNamespace(mission_id="mission-1")

    with pytest.raises(
        AgentTeamsExecutionBindingError,
        match="AGENT_TEAMS_TERMINAL_DSH_SESSION_MISMATCH:WORKER_STARTED",
    ):
        gate.verify_terminal_and_persist(task, SimpleNamespace(), _invocation())


def test_bank_agent_teams_integration_uses_hardened_session_gate() -> None:
    assert integration.AgentTeamsExecutionBindingGate is AgentTeamsExecutionBindingGate
