"""RC7.1 bridge to the real dsh-agent-teams durable orchestration truth.

This module deliberately does not emulate AgentTeams. Production dispatch reads
its canonical file-backed state under ``<workspace>/.agent-teams/<teamId>/team.json``
and refuses to launch a professional RC7 worker unless the Mission Task is owned
by a durable non-captain team member.

AgentTeams remains the team/member/task orchestration authority. RC7 remains the
R1, lease, evidence and acceptance authority. The binding receipt below is the
immutable seam between those two truths and is persisted into canonical R1 as
Evidence. No caller supplied ``team_id`` or ``member_id`` can force admission.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from .closed_loop_control import ClosedLoopControlPlane
from .models import Evidence, Task
from .truth_overlay import append_entity


class AgentTeamsOrchestrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentTeamsTaskBinding:
    team_id: str
    team_name: str
    captain_session_id: str
    member_id: str
    member_name: str
    member_role: str
    team_task_id: str
    team_task_status: str
    team_attempt: Optional[int]
    team_attempt_id: Optional[str]
    state_ref: str
    state_sha256: str

    def as_contract(self) -> Dict[str, Any]:
        return {
            "team_id": self.team_id,
            "team_name": self.team_name,
            "captain_session_id": self.captain_session_id,
            "member_id": self.member_id,
            "member_name": self.member_name,
            "member_role": self.member_role,
            "team_task_id": self.team_task_id,
            "team_task_status": self.team_task_status,
            "team_attempt": self.team_attempt,
            "team_attempt_id": self.team_attempt_id,
            "state_ref": self.state_ref,
            "state_sha256": self.state_sha256,
        }


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _required_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentTeamsOrchestrationError(code)
    return value.strip()


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class DshAgentTeamsStateGate:
    """Fail-closed admission gate backed by real dsh-agent-teams disk truth."""

    ACTIVE_TASK_STATES = frozenset({"pending", "claimed", "in_progress"})
    COORDINATION_TERMINAL_STATE = "completed"
    COORDINATION_MARKER = "RC7_COORDINATION_SLOT=true"

    def __init__(
        self,
        control: ClosedLoopControlPlane,
        *,
        workspace_root: str,
        evidence_root: str,
    ) -> None:
        self.control = control
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.state_root = self.workspace_root / ".agent-teams"
        self.evidence_root = Path(evidence_root).expanduser().resolve()

    @classmethod
    def _dispatchable_status(cls, team_task: Mapping[str, Any], status: str) -> bool:
        if status in cls.ACTIVE_TASK_STATES:
            return True
        if status != cls.COORDINATION_TERMINAL_STATE:
            return False
        # A completed AgentTeams coordination slot only proves durable ownership
        # handoff. It never proves RC7 business execution PASS. The governed
        # child worker must still execute and produce canonical R1 evidence.
        return cls.COORDINATION_MARKER in str(team_task.get("description") or "")

    def require_binding(self, task: Task) -> AgentTeamsTaskBinding:
        if task.mission_id != self.control.mission_id:
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_TASK_MISSION_MISMATCH")
        teams = tuple(self._matching_teams(task.mission_id))
        if not teams:
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_MISSION_TEAM_REQUIRED")
        if len(teams) != 1:
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_MISSION_TEAM_NOT_UNIQUE")
        state_path, state, digest = teams[0]

        phase = state.get("phase")
        if phase not in (None, "running"):
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_TEAM_NOT_RUNNING")
        if state.get("halted") is True:
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_TEAM_HALTED")
        if state.get("escalated") is True:
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_TEAM_ESCALATED")

        team_tasks = [item for item in state.get("tasks", []) if self._task_matches(item, task.task_id)]
        if not team_tasks:
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_TASK_ASSIGNMENT_REQUIRED")
        if len(team_tasks) != 1:
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_TASK_ASSIGNMENT_NOT_UNIQUE")
        team_task = team_tasks[0]
        status = _required_text(team_task.get("status"), "AGENT_TEAMS_TASK_STATUS_REQUIRED")
        if not self._dispatchable_status(team_task, status):
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_TASK_NOT_DISPATCHABLE:%s" % status)

        assignee = _required_text(team_task.get("assignee"), "AGENT_TEAMS_TASK_ASSIGNEE_REQUIRED")
        if assignee == "captain":
            raise AgentTeamsOrchestrationError("DIRECTOR_SELF_EXECUTION_FORBIDDEN")

        members = [item for item in state.get("members", []) if isinstance(item, dict) and item.get("name") == assignee]
        if len(members) != 1:
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_ASSIGNEE_MEMBER_NOT_UNIQUE")
        member = members[0]
        member_id = _required_text(member.get("id"), "AGENT_TEAMS_MEMBER_SESSION_REQUIRED")
        if member_id == _required_text(state.get("captainSessionId"), "AGENT_TEAMS_CAPTAIN_SESSION_REQUIRED"):
            raise AgentTeamsOrchestrationError("DIRECTOR_MEMBER_IDENTITY_COLLISION")
        if member.get("status") == "removed":
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_MEMBER_REMOVED")
        if member.get("stopping") is True:
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_MEMBER_STOPPING")
        if isinstance(member.get("spawnError"), str) and member.get("spawnError").strip():
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_MEMBER_SPAWN_FAILED")

        attempt = team_task.get("attempt")
        if attempt is not None and (not isinstance(attempt, int) or attempt < 1):
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_ATTEMPT_INVALID")
        attempt_id = team_task.get("attemptId")
        if attempt_id is not None:
            attempt_id = _required_text(attempt_id, "AGENT_TEAMS_ATTEMPT_ID_INVALID")
        if status in {"claimed", "in_progress"} and not attempt_id:
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_ACTIVE_ATTEMPT_ID_REQUIRED")

        return AgentTeamsTaskBinding(
            team_id=_required_text(state.get("id"), "AGENT_TEAMS_TEAM_ID_REQUIRED"),
            team_name=_required_text(state.get("name"), "AGENT_TEAMS_TEAM_NAME_REQUIRED"),
            captain_session_id=_required_text(state.get("captainSessionId"), "AGENT_TEAMS_CAPTAIN_SESSION_REQUIRED"),
            member_id=member_id,
            member_name=assignee,
            member_role=str(member.get("role") or ""),
            team_task_id=_required_text(team_task.get("id"), "AGENT_TEAMS_TEAM_TASK_ID_REQUIRED"),
            team_task_status=status,
            team_attempt=attempt,
            team_attempt_id=attempt_id,
            state_ref="file://" + str(state_path),
            state_sha256="sha256:" + digest,
        )

    def persist_assignment_receipt(
        self,
        task: Task,
        binding: AgentTeamsTaskBinding,
        *,
        worker_instance_id: str,
        worker_assignment_id: str,
        parent_worker_id: str,
    ) -> Evidence:
        worker = _required_text(worker_instance_id, "AGENT_TEAMS_WORKER_INSTANCE_REQUIRED")
        assignment = _required_text(worker_assignment_id, "AGENT_TEAMS_WORKER_ASSIGNMENT_REQUIRED")
        parent = _required_text(parent_worker_id, "AGENT_TEAMS_PARENT_WORKER_REQUIRED")
        if parent != binding.member_id:
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_MEMBER_PARENT_BINDING_MISMATCH")
        if worker in {binding.member_id, binding.captain_session_id}:
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_EXECUTION_IDENTITY_COLLISION")

        payload = {
            "schema": "pfc.aitest.rc7.1.dsh-agent-teams-assignment.v1",
            "mission_id": task.mission_id,
            "task_id": task.task_id,
            "node": task.node,
            "team": binding.as_contract(),
            "worker_instance_id": worker,
            "worker_assignment_id": assignment,
            "parent_worker_id": parent,
            "director_self_execution_forbidden": True,
            "local_fallback_forbidden": True,
        }
        body = _canonical_json_bytes(payload)
        digest = hashlib.sha256(body).hexdigest()
        evidence_id = _stable_id(
            "EVD-AGENT-TEAMS",
            task.mission_id,
            task.task_id,
            binding.team_id,
            binding.team_task_id,
            binding.member_id,
            assignment,
            digest,
        )
        folder = self.evidence_root / "agent-teams" / task.mission_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (evidence_id + ".json")
        if path.exists() and path.read_bytes() != body:
            raise AgentTeamsOrchestrationError("AGENT_TEAMS_ASSIGNMENT_RECEIPT_IMMUTABILITY_CONFLICT")
        if not path.exists():
            path.write_bytes(body)

        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=task.mission_id,
            kind="DSH_AGENT_TEAMS_ASSIGNMENT",
            source_ref="dsh-agent-teams://%s/%s" % (binding.team_id, binding.team_task_id),
            content_ref="file://" + str(path),
            subject_refs=[
                task.task_id,
                task.node,
                binding.team_id,
                binding.team_task_id,
                binding.member_id,
                worker,
                assignment,
            ],
            content_hash="sha256:" + digest,
        )
        existing = self.control.truth.query("rc7_evidence", evidence_id=evidence_id)
        if existing:
            if len(existing) != 1:
                raise AgentTeamsOrchestrationError("AGENT_TEAMS_ASSIGNMENT_R1_NOT_UNIQUE")
            row = existing[0]
            if row.get("content_ref") != evidence.content_ref or row.get("content_hash") != evidence.content_hash:
                raise AgentTeamsOrchestrationError("AGENT_TEAMS_ASSIGNMENT_R1_CONFLICT")
            return evidence
        append_entity(
            self.control.truth,
            evidence,
            release_id=self.control.release_id,
            artifact_version=1,
        )
        return evidence

    def _matching_teams(self, mission_id: str) -> Iterable[Tuple[Path, Dict[str, Any], str]]:
        marker = "RC7_MISSION_ID=%s" % mission_id
        if not self.state_root.is_dir():
            return ()
        rows = []
        for path in sorted(self.state_root.glob("*/team.json")):
            if "archive" in path.parts:
                continue
            try:
                raw = path.read_bytes()
                payload = json.loads(raw.decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AgentTeamsOrchestrationError("AGENT_TEAMS_STATE_INVALID:%s" % path) from exc
            if not isinstance(payload, dict):
                raise AgentTeamsOrchestrationError("AGENT_TEAMS_STATE_NOT_OBJECT:%s" % path)
            profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
            searchable = [
                payload.get("description"),
                profile.get("description"),
                profile.get("protocol"),
            ]
            if any(isinstance(value, str) and marker in value for value in searchable):
                rows.append((path.resolve(), payload, hashlib.sha256(raw).hexdigest()))
        return tuple(rows)

    @staticmethod
    def _task_matches(team_task: Any, task_id: str) -> bool:
        if not isinstance(team_task, dict):
            return False
        if team_task.get("id") == task_id or team_task.get("profileSeedId") == task_id:
            return True
        marker = "RC7_TASK_ID=%s" % task_id
        return any(
            isinstance(team_task.get(field), str) and marker in team_task.get(field)
            for field in ("subject", "description", "objective")
        )
