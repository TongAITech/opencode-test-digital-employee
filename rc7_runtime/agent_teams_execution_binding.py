"""Fail-closed binding between AgentTeams ownership and RC7 specialist execution."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from .agent_teams_orchestration import AgentTeamsTaskBinding
from .closed_loop_control import ClosedLoopControlPlane
from .models import Evidence, Task
from .truth_overlay import append_entity


class AgentTeamsExecutionBindingError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _required_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentTeamsExecutionBindingError(code)
    return value.strip()


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


@dataclass(frozen=True)
class AgentTeamsExecutionBinding:
    evidence_id: str
    mission_id: str
    task_id: str
    team_id: str
    team_task_id: str
    member_id: str
    worker_instance_id: str
    worker_assignment_id: str
    attempt_id: str
    lease_id: str
    parent_worker_id: str
    assignment_evidence_id: str
    content_ref: str
    content_hash: str


class AgentTeamsExecutionBindingGate:
    """Require one immutable identity chain from Team assignment through handoff."""

    REQUIRED_TERMINAL_EVENTS: Tuple[str, ...] = (
        "WORKER_STARTED",
        "WORKER_OUTPUT_PRODUCED",
        "WORKER_COMPLETED",
        "HANDOFF_RETURNED",
    )

    def __init__(self, control: ClosedLoopControlPlane, *, evidence_root: str) -> None:
        self.control = control
        self.evidence_root = Path(evidence_root).expanduser().resolve()

    def persist_binding(
        self,
        task: Task,
        team_binding: AgentTeamsTaskBinding,
        assignment: Any,
        *,
        assignment_evidence_id: str,
    ) -> AgentTeamsExecutionBinding:
        mission_id = _required_text(
            getattr(assignment, "mission_id", None), "AGENT_TEAMS_EXECUTION_MISSION_REQUIRED"
        )
        if mission_id != task.mission_id:
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_EXECUTION_MISSION_MISMATCH")
        worker = _required_text(
            getattr(assignment, "worker_instance_id", None), "AGENT_TEAMS_EXECUTION_WORKER_REQUIRED"
        )
        worker_assignment_id = _required_text(
            getattr(assignment, "assignment_id", None), "AGENT_TEAMS_EXECUTION_ASSIGNMENT_REQUIRED"
        )
        attempt_id = _required_text(
            getattr(assignment, "attempt_id", None), "AGENT_TEAMS_EXECUTION_ATTEMPT_REQUIRED"
        )
        parent = _required_text(
            getattr(assignment, "parent_worker_id", None), "AGENT_TEAMS_EXECUTION_PARENT_REQUIRED"
        )
        scope = _required_text(
            getattr(assignment, "scope", None), "AGENT_TEAMS_EXECUTION_SCOPE_REQUIRED"
        )
        lease_id = _required_text(
            getattr(getattr(assignment, "lease", None), "lease_id", None),
            "AGENT_TEAMS_EXECUTION_LEASE_REQUIRED",
        )
        if parent != team_binding.member_id:
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_EXECUTION_MEMBER_MISMATCH")
        if worker in {team_binding.member_id, team_binding.captain_session_id}:
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_EXECUTION_IDENTITY_COLLISION")
        if scope != "task:%s" % task.task_id:
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_EXECUTION_TASK_SCOPE_MISMATCH")

        assignment_evidence = self._require_assignment_evidence(
            task,
            team_binding,
            assignment_evidence_id=assignment_evidence_id,
            worker_instance_id=worker,
            worker_assignment_id=worker_assignment_id,
        )
        payload = {
            "schema": "pfc.aitest.rc7.1.agent-teams-execution-binding.v1",
            "mission_id": task.mission_id,
            "task_id": task.task_id,
            "node": task.node,
            "team_id": team_binding.team_id,
            "team_task_id": team_binding.team_task_id,
            "member_id": team_binding.member_id,
            "team_state_ref": team_binding.state_ref,
            "team_state_sha256": team_binding.state_sha256,
            "worker_instance_id": worker,
            "worker_assignment_id": worker_assignment_id,
            "attempt_id": attempt_id,
            "lease_id": lease_id,
            "parent_worker_id": parent,
            "scope": scope,
            "assignment_evidence_id": assignment_evidence["evidence_id"],
            "director_self_execution_forbidden": True,
            "local_execution_fallback_forbidden": True,
        }
        evidence = self._persist(
            task,
            kind="DSH_AGENT_TEAMS_EXECUTION_BINDING",
            prefix="EVD-AT-EXEC-BIND",
            payload=payload,
            stable_parts=(
                task.mission_id,
                task.task_id,
                team_binding.team_id,
                team_binding.team_task_id,
                team_binding.member_id,
                worker_assignment_id,
                attempt_id,
                lease_id,
            ),
            subjects=(
                task.task_id,
                task.node,
                team_binding.team_id,
                team_binding.team_task_id,
                team_binding.member_id,
                worker,
                worker_assignment_id,
                attempt_id,
                lease_id,
                assignment_evidence["evidence_id"],
            ),
            source_ref="dsh-agent-teams://%s/%s/execution"
            % (team_binding.team_id, team_binding.team_task_id),
        )
        return AgentTeamsExecutionBinding(
            evidence_id=evidence.evidence_id,
            mission_id=task.mission_id,
            task_id=task.task_id,
            team_id=team_binding.team_id,
            team_task_id=team_binding.team_task_id,
            member_id=team_binding.member_id,
            worker_instance_id=worker,
            worker_assignment_id=worker_assignment_id,
            attempt_id=attempt_id,
            lease_id=lease_id,
            parent_worker_id=parent,
            assignment_evidence_id=assignment_evidence["evidence_id"],
            content_ref=evidence.content_ref,
            content_hash=evidence.content_hash or "",
        )

    def verify_terminal_and_persist(
        self,
        task: Task,
        team_binding: AgentTeamsTaskBinding,
        invocation: Any,
    ) -> Evidence:
        assignment_id = _required_text(
            getattr(invocation, "assignment_id", None), "AGENT_TEAMS_TERMINAL_ASSIGNMENT_REQUIRED"
        )
        execution = self._require_execution_binding(task.mission_id, assignment_id)
        expected = {
            "mission_id": task.mission_id,
            "task_id": task.task_id,
            "team_id": team_binding.team_id,
            "team_task_id": team_binding.team_task_id,
            "member_id": team_binding.member_id,
            "worker_instance_id": _required_text(
                getattr(invocation, "worker_instance_id", None), "AGENT_TEAMS_TERMINAL_WORKER_REQUIRED"
            ),
            "worker_assignment_id": assignment_id,
            "attempt_id": _required_text(
                getattr(invocation, "attempt_id", None), "AGENT_TEAMS_TERMINAL_ATTEMPT_REQUIRED"
            ),
            "lease_id": _required_text(
                getattr(invocation, "lease_id", None), "AGENT_TEAMS_TERMINAL_LEASE_REQUIRED"
            ),
            "parent_worker_id": _required_text(
                getattr(invocation, "parent_worker_id", None), "AGENT_TEAMS_TERMINAL_PARENT_REQUIRED"
            ),
        }
        for field, value in expected.items():
            if execution.get(field) != value:
                raise AgentTeamsExecutionBindingError(
                    "AGENT_TEAMS_TERMINAL_%s_MISMATCH" % field.upper()
                )
        if expected["parent_worker_id"] != team_binding.member_id:
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_TERMINAL_MEMBER_MISMATCH")
        if str(getattr(invocation, "result", "") or "").upper() != "PASS":
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_TERMINAL_PASS_REQUIRED")
        dsh_session_id = _required_text(
            getattr(invocation, "dsh_session_id", None), "AGENT_TEAMS_TERMINAL_DSH_SESSION_REQUIRED"
        )

        rows = self.control.truth.query("agent_runtime_event", mission_id=task.mission_id)
        matched: Dict[str, Dict[str, Any]] = {}
        for event_name in self.REQUIRED_TERMINAL_EVENTS:
            matches = [row for row in rows if self._event_matches(row, event_name, expected)]
            if len(matches) != 1:
                raise AgentTeamsExecutionBindingError(
                    "AGENT_TEAMS_TERMINAL_EVENT_NOT_UNIQUE:%s:%d" % (event_name, len(matches))
                )
            matched[event_name] = matches[0]
        if str(matched["WORKER_COMPLETED"].get("result") or "").upper() != "PASS":
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_WORKER_COMPLETED_NOT_PASS")
        if str(matched["HANDOFF_RETURNED"].get("result") or "").upper() != "PASS":
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_HANDOFF_NOT_PASS")
        if int(matched["WORKER_COMPLETED"].get("finished_at") or 0) <= 0:
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_TERMINAL_FINISH_TIME_REQUIRED")
        if int(matched["HANDOFF_RETURNED"].get("finished_at") or 0) <= 0:
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_TERMINAL_FINISH_TIME_REQUIRED")

        payload = {
            "schema": "pfc.aitest.rc7.1.agent-teams-terminal-binding.v1",
            "mission_id": task.mission_id,
            "task_id": task.task_id,
            "node": task.node,
            "team_id": team_binding.team_id,
            "team_task_id": team_binding.team_task_id,
            "member_id": team_binding.member_id,
            "worker_instance_id": expected["worker_instance_id"],
            "worker_assignment_id": assignment_id,
            "attempt_id": expected["attempt_id"],
            "lease_id": expected["lease_id"],
            "parent_worker_id": expected["parent_worker_id"],
            "execution_binding_evidence_id": execution["_evidence_id"],
            "dsh_session_id": dsh_session_id,
            "result": "PASS",
            "terminal_event_ids": {
                name: matched[name].get("id") for name in self.REQUIRED_TERMINAL_EVENTS
            },
            "director_self_execution_forbidden": True,
            "local_execution_fallback_forbidden": True,
        }
        return self._persist(
            task,
            kind="DSH_AGENT_TEAMS_TERMINAL_BINDING",
            prefix="EVD-AT-TERMINAL",
            payload=payload,
            stable_parts=(
                task.mission_id,
                task.task_id,
                team_binding.team_id,
                team_binding.team_task_id,
                team_binding.member_id,
                assignment_id,
                expected["attempt_id"],
                expected["lease_id"],
                dsh_session_id,
            ),
            subjects=(
                task.task_id,
                task.node,
                team_binding.team_id,
                team_binding.team_task_id,
                team_binding.member_id,
                expected["worker_instance_id"],
                assignment_id,
                expected["attempt_id"],
                expected["lease_id"],
                execution["_evidence_id"],
            ),
            source_ref="dsh-agent-teams://%s/%s/terminal"
            % (team_binding.team_id, team_binding.team_task_id),
        )

    def _require_assignment_evidence(
        self,
        task: Task,
        team_binding: AgentTeamsTaskBinding,
        *,
        assignment_evidence_id: str,
        worker_instance_id: str,
        worker_assignment_id: str,
    ) -> Dict[str, Any]:
        evidence_id = _required_text(
            assignment_evidence_id, "AGENT_TEAMS_ASSIGNMENT_EVIDENCE_REQUIRED"
        )
        rows = self.control.truth.query("rc7_evidence", evidence_id=evidence_id)
        if len(rows) != 1:
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_ASSIGNMENT_EVIDENCE_NOT_UNIQUE")
        row = rows[0]
        if row.get("mission_id") != task.mission_id or row.get("kind") != "DSH_AGENT_TEAMS_ASSIGNMENT":
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_ASSIGNMENT_EVIDENCE_INVALID")
        payload = self._verified_payload(row, "AGENT_TEAMS_ASSIGNMENT_EVIDENCE")
        team = payload.get("team") if isinstance(payload.get("team"), dict) else {}
        if payload.get("task_id") != task.task_id:
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_ASSIGNMENT_TASK_MISMATCH")
        if team.get("team_id") != team_binding.team_id or team.get("team_task_id") != team_binding.team_task_id:
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_ASSIGNMENT_TEAM_MISMATCH")
        if team.get("member_id") != team_binding.member_id:
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_ASSIGNMENT_MEMBER_MISMATCH")
        if payload.get("worker_instance_id") != worker_instance_id:
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_ASSIGNMENT_WORKER_MISMATCH")
        if payload.get("worker_assignment_id") != worker_assignment_id:
            raise AgentTeamsExecutionBindingError("AGENT_TEAMS_ASSIGNMENT_WORKER_MISMATCH")
        payload["evidence_id"] = evidence_id
        return payload

    def _require_execution_binding(self, mission_id: str, assignment_id: str) -> Dict[str, Any]:
        rows = [
            row
            for row in self.control.truth.query("rc7_evidence", mission_id=mission_id)
            if row.get("kind") == "DSH_AGENT_TEAMS_EXECUTION_BINDING"
            and assignment_id in (row.get("subject_refs") or [])
        ]
        if len(rows) != 1:
            raise AgentTeamsExecutionBindingError(
                "AGENT_TEAMS_EXECUTION_BINDING_NOT_UNIQUE:%d" % len(rows)
            )
        payload = self._verified_payload(rows[0], "AGENT_TEAMS_EXECUTION_BINDING")
        payload["_evidence_id"] = rows[0].get("evidence_id")
        return payload

    @staticmethod
    def _event_matches(
        row: Mapping[str, Any], event_name: str, expected: Mapping[str, str]
    ) -> bool:
        if row.get("event_name") != event_name:
            return False
        event_to_binding = {
            "mission_id": "mission_id",
            "worker_instance_id": "worker_instance_id",
            "assignment_id": "worker_assignment_id",
            "attempt_id": "attempt_id",
            "lease_id": "lease_id",
            "parent_worker_id": "parent_worker_id",
        }
        return all(
            row.get(event_field) == expected[binding_field]
            for event_field, binding_field in event_to_binding.items()
        )

    @staticmethod
    def _verified_payload(row: Mapping[str, Any], code: str) -> Dict[str, Any]:
        ref = _required_text(row.get("content_ref"), code + "_CONTENT_REF_REQUIRED")
        if not ref.startswith("file://"):
            raise AgentTeamsExecutionBindingError(code + "_FILE_REF_REQUIRED")
        path = Path(ref[len("file://") :])
        try:
            body = path.read_bytes()
            payload = json.loads(body.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AgentTeamsExecutionBindingError(code + "_UNREADABLE") from exc
        if not isinstance(payload, dict):
            raise AgentTeamsExecutionBindingError(code + "_NOT_OBJECT")
        if row.get("content_hash") != "sha256:" + hashlib.sha256(body).hexdigest():
            raise AgentTeamsExecutionBindingError(code + "_HASH_MISMATCH")
        return payload

    def _persist(
        self,
        task: Task,
        *,
        kind: str,
        prefix: str,
        payload: Dict[str, Any],
        stable_parts: Tuple[str, ...],
        subjects: Sequence[str],
        source_ref: str,
    ) -> Evidence:
        body = _canonical_bytes(payload)
        digest = hashlib.sha256(body).hexdigest()
        evidence_id = _stable_id(prefix, *(stable_parts + (digest,)))
        folder = self.evidence_root / "agent-teams-execution" / task.mission_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (evidence_id + ".json")
        if path.exists() and path.read_bytes() != body:
            raise AgentTeamsExecutionBindingError(
                "AGENT_TEAMS_EXECUTION_RECEIPT_IMMUTABILITY_CONFLICT"
            )
        if not path.exists():
            path.write_bytes(body)
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=task.mission_id,
            kind=kind,
            source_ref=source_ref,
            content_ref="file://" + str(path),
            subject_refs=list(subjects),
            content_hash="sha256:" + digest,
        )
        existing = self.control.truth.query("rc7_evidence", evidence_id=evidence_id)
        if existing:
            if len(existing) != 1:
                raise AgentTeamsExecutionBindingError("AGENT_TEAMS_EXECUTION_R1_NOT_UNIQUE")
            row = existing[0]
            if row.get("content_ref") != evidence.content_ref:
                raise AgentTeamsExecutionBindingError("AGENT_TEAMS_EXECUTION_R1_CONFLICT")
            if row.get("content_hash") != evidence.content_hash:
                raise AgentTeamsExecutionBindingError("AGENT_TEAMS_EXECUTION_R1_CONFLICT")
            return evidence
        append_entity(
            self.control.truth,
            evidence,
            release_id=self.control.release_id,
            artifact_version=1,
        )
        return evidence
