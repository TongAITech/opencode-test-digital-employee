"""Deterministic RC7.1 Mission -> dsh-agent-teams bootstrap.

R1 stays the only execution DAG authority.  AgentTeams supplies durable team,
member and assignment ownership.  Its tasks are coordination slots, not a
second business-execution scheduler: members are required to use the owner-
declared ``rc7-coordination-only`` tool policy and the governed RC7 child
worker remains the only path allowed to perform professional test side effects.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher

from .closed_loop_control import ClosedLoopControlPlane
from .dsh_worker_bridge import DEFAULT_NODE_POLICIES
from .mission_graph import MissionTaskGraph, MissionTaskGraphCompiler
from .models import Evidence
from .truth_overlay import append_entity


class AgentTeamsBootstrapError(RuntimeError):
    pass


COORDINATION_TOOL_POLICY = "rc7-coordination-only"
ORCHESTRATION_MODE = "TEAM_OWNED_RC7_CHILD_EXECUTION"


@dataclass(frozen=True)
class AgentTeamsBootstrapPlan:
    mission_id: str
    team_name: str
    description: str
    members: Tuple[Mapping[str, Any], ...]
    tasks: Tuple[Mapping[str, Any], ...]
    sha256: str

    def create_args(self) -> Dict[str, Any]:
        return {
            "name": self.team_name,
            "description": self.description,
            "approval": "automatic",
            "plan": {
                "members": [dict(item) for item in self.members],
                "tasks": [dict(item) for item in self.tasks],
            },
        }


@dataclass(frozen=True)
class AgentTeamsBootstrapResult:
    team_id: str
    captain_session_id: str
    state_ref: str
    state_sha256: str
    plan_sha256: str
    reused: bool
    evidence_id: str


def _stable(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class AgentTeamsMissionPlanCompiler:
    """Compile producer Tasks into Team ownership slots without duplicating R1 DAG."""

    _MEMBER_NAMES = {
        "REQUIREMENT_ANALYSIS": "requirements",
        "CODE_ANALYSIS": "code-analysis",
        "TEST_DESIGN": "test-design",
        "SCRIPT_READINESS": "automation",
        "EXECUTION": "execution",
    }

    def compile(self, graph: MissionTaskGraph) -> AgentTeamsBootstrapPlan:
        producer = [
            task for task in graph.tasks
            if graph.stage_ownership.get(task.node) == MissionTaskGraphCompiler.OWNER_PRODUCER
            or task.node in self._MEMBER_NAMES
        ]
        unknown = sorted(task.node for task in producer if task.node not in self._MEMBER_NAMES)
        if unknown:
            raise AgentTeamsBootstrapError("AGENT_TEAMS_PRODUCER_ROLE_UNMAPPED:%s" % ",".join(unknown))
        if not producer:
            raise AgentTeamsBootstrapError("AGENT_TEAMS_PRODUCER_TASKS_REQUIRED")

        members = []
        tasks = []
        for task in producer:
            policy = DEFAULT_NODE_POLICIES.get(task.node)
            if policy is None:
                raise AgentTeamsBootstrapError("AGENT_TEAMS_NODE_POLICY_REQUIRED:%s" % task.node)
            member_name = self._MEMBER_NAMES[task.node]
            members.append({
                "name": member_name,
                "role": "%s coordination owner; delegate professional execution to governed RC7 child worker" % task.node,
                "tool_policy": COORDINATION_TOOL_POLICY,
            })
            deps = list(task.dependency_task_ids)
            tasks.append({
                "id": task.task_id,
                "subject": "RC7_TASK_ID=%s ownership slot for %s" % (task.task_id, task.node),
                "description": (
                    "RC7_COORDINATION_SLOT=true; RC7_NODE=%s; RC7_R1_DEPENDENCIES=%s; "
                    "R1 owns sequencing and acceptance. Do not perform business/test side effects. "
                    "Acknowledge durable ownership only; the governed RC7 lease worker performs the professional work."
                    % (task.node, json.dumps(deps, ensure_ascii=False, separators=(",", ":")))
                ),
                "assignee": member_name,
                # Deliberately empty: R1 is the one execution DAG. Mirroring the
                # same dependencies into AgentTeams would create a second
                # scheduler and a restart race.
                "dependencies": [],
            })

        team_name = "rc7-%s" % hashlib.sha256(graph.mission_id.encode("utf-8")).hexdigest()[:16]
        description = (
            "RC7_MISSION_ID=%s; RC7_ORCHESTRATION_MODE=%s; "
            "AgentTeams owns durable roster/assignment truth; canonical R1 owns execution ordering, evidence and acceptance."
            % (graph.mission_id, ORCHESTRATION_MODE)
        )
        body = {
            "mission_id": graph.mission_id,
            "team_name": team_name,
            "description": description,
            "members": members,
            "tasks": tasks,
        }
        return AgentTeamsBootstrapPlan(
            mission_id=graph.mission_id,
            team_name=team_name,
            description=description,
            members=tuple(members),
            tasks=tuple(tasks),
            sha256="sha256:" + hashlib.sha256(_canonical(body)).hexdigest(),
        )


class DshAgentTeamsMissionBootstrapper:
    def __init__(
        self,
        control: ClosedLoopControlPlane,
        *,
        graph: MissionTaskGraph,
        dsh_bin: str,
        patch_path: str,
        workspace_root: str,
        evidence_root: str,
        timeout_seconds: int = 300,
        command_runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    ) -> None:
        self.control = control
        self.graph = graph
        self.dsh_bin = str(dsh_bin)
        self.patch_path = str(Path(patch_path).expanduser().resolve())
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.state_root = self.workspace_root / ".agent-teams"
        self.evidence_root = Path(evidence_root).expanduser().resolve()
        self.timeout_seconds = int(timeout_seconds)
        self.command_runner = command_runner or subprocess.run
        self.plan = AgentTeamsMissionPlanCompiler().compile(graph)

    def bootstrap(self) -> AgentTeamsBootstrapResult:
        existing = self._read_expected_team()
        if existing is not None:
            state_path, state, digest = existing
            self._validate_topology(state)
            return self._persist_receipt(state_path, state, digest, raw_ref=None, reused=True)

        if not self._dsh_available():
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_DSH_NOT_AVAILABLE")
        if not Path(self.patch_path).is_file():
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_PATCH_REQUIRED")

        args = self.plan.create_args()
        prompt = self._prompt(args)
        command = [self.dsh_bin, "--profile", "headless", "--patch", self.patch_path, "--json", prompt]
        try:
            proc = self.command_runner(
                command,
                cwd=str(self.workspace_root),
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_DSH_LAUNCH_FAILED:%s" % type(exc).__name__) from exc

        raw_ref = self._persist_raw(proc.stdout or "", proc.stderr or "")
        events = tuple(DshHeadlessWorkerLauncher._parse_json_lines(proc.stdout or ""))
        calls = tuple(DshHeadlessWorkerLauncher._tool_calls(events))
        names = [str(item.get("tool_name") or "") for item in calls]
        if "agent_teams_create" not in names:
            raise AgentTeamsBootstrapError("AGENT_TEAMS_CREATE_TOOL_CALL_REQUIRED")
        if int(proc.returncode) != 0:
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_PROCESS_FAILED:%d" % int(proc.returncode))

        created = self._read_expected_team()
        if created is None:
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_STATE_MISSING")
        state_path, state, digest = created
        self._validate_topology(state)
        session_id = DshHeadlessWorkerLauncher._session_id(events)
        if not session_id:
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_CAPTAIN_SESSION_MISSING")
        if state.get("captainSessionId") != session_id:
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_CAPTAIN_SESSION_MISMATCH")
        return self._persist_receipt(state_path, state, digest, raw_ref=raw_ref, reused=False)

    def _prompt(self, args: Mapping[str, Any]) -> str:
        return (
            "/agent-teams RC7 deterministic Mission team bootstrap.\n"
            "You are the orchestration-only Captain. Do not perform requirement analysis, code analysis, test design, "
            "script building, browser/API/database actions, or test execution yourself.\n"
            "Call agent_teams_create exactly once with this exact JSON argument object:\n%s\n"
            "The member tool policy must remain '%s'. Do not widen member tools. The created tasks are coordination "
            "ownership slots only; canonical R1 owns sequencing and the governed RC7 child workers do professional work.\n"
            "After creation, call agent_teams_status as needed until every planned member has a non-empty durable member "
            "session id or an explicit spawn error. Do not delete/recreate the team. End with one compact JSON object "
            "containing team_id and status only."
            % (json.dumps(args, ensure_ascii=False, sort_keys=True), COORDINATION_TOOL_POLICY)
        )

    def _read_expected_team(self):
        path = self.state_root / self.plan.team_name / "team.json"
        if not path.is_file():
            return None
        try:
            raw = path.read_bytes()
            state = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_STATE_INVALID") from exc
        if not isinstance(state, dict):
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_STATE_NOT_OBJECT")
        return path.resolve(), state, hashlib.sha256(raw).hexdigest()

    def _validate_topology(self, state: Mapping[str, Any]) -> None:
        if state.get("id") != self.plan.team_name or state.get("name") != self.plan.team_name:
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_TEAM_IDENTITY_MISMATCH")
        description = str(state.get("description") or "")
        if "RC7_MISSION_ID=%s" % self.plan.mission_id not in description:
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_MISSION_MARKER_MISSING")
        if "RC7_ORCHESTRATION_MODE=%s" % ORCHESTRATION_MODE not in description:
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_MODE_MISMATCH")
        if state.get("phase") not in (None, "running") or state.get("halted") is True:
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_TEAM_NOT_RUNNING")
        captain = state.get("captainSessionId")
        if not isinstance(captain, str) or not captain.strip():
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_CAPTAIN_REQUIRED")

        expected_members = {str(item["name"]): item for item in self.plan.members}
        actual_members = {
            str(item.get("name")): item for item in state.get("members", [])
            if isinstance(item, dict) and item.get("status") != "removed"
        }
        if set(actual_members) != set(expected_members):
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_MEMBER_SET_MISMATCH")
        for name, member in actual_members.items():
            if member.get("toolPolicy") != COORDINATION_TOOL_POLICY:
                raise AgentTeamsBootstrapError("AGENT_TEAMS_COORDINATION_POLICY_REQUIRED:%s" % name)
            if isinstance(member.get("spawnError"), str) and member.get("spawnError").strip():
                raise AgentTeamsBootstrapError("AGENT_TEAMS_MEMBER_SPAWN_FAILED:%s" % name)
            member_id = member.get("id")
            if not isinstance(member_id, str) or not member_id.strip():
                raise AgentTeamsBootstrapError("AGENT_TEAMS_MEMBER_SESSION_NOT_READY:%s" % name)
            if member_id == captain:
                raise AgentTeamsBootstrapError("DIRECTOR_MEMBER_IDENTITY_COLLISION")

        expected_tasks = {str(item["id"]): item for item in self.plan.tasks}
        actual_tasks = {
            str(item.get("profileSeedId")): item for item in state.get("tasks", [])
            if isinstance(item, dict) and isinstance(item.get("profileSeedId"), str)
        }
        if set(actual_tasks) != set(expected_tasks):
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_TASK_SET_MISMATCH")
        for task_id, expected in expected_tasks.items():
            actual = actual_tasks[task_id]
            if actual.get("assignee") != expected.get("assignee"):
                raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_ASSIGNEE_MISMATCH:%s" % task_id)
            if list(actual.get("dependencies") or []) != []:
                raise AgentTeamsBootstrapError("AGENT_TEAMS_SECOND_EXECUTION_DAG_FORBIDDEN:%s" % task_id)
            if "RC7_COORDINATION_SLOT=true" not in str(actual.get("description") or ""):
                raise AgentTeamsBootstrapError("AGENT_TEAMS_COORDINATION_SLOT_MARKER_REQUIRED:%s" % task_id)
            if actual.get("status") in {"failed", "cancelled"}:
                raise AgentTeamsBootstrapError("AGENT_TEAMS_COORDINATION_SLOT_FAILED:%s" % task_id)

    def _persist_raw(self, stdout: str, stderr: str) -> str:
        folder = self.evidence_root / "agent-teams-bootstrap" / self.plan.mission_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (self.plan.team_name + ".jsonl")
        body = stdout + (("\n" + stderr) if stderr else "")
        path.write_text(body, encoding="utf-8", newline="\n")
        return "file://" + str(path.resolve())

    def _persist_receipt(self, path: Path, state: Mapping[str, Any], digest: str, *, raw_ref: Optional[str], reused: bool) -> AgentTeamsBootstrapResult:
        captain = str(state["captainSessionId"])
        evidence_id = _stable("EVD-AGENT-TEAMS-BOOTSTRAP", self.plan.mission_id, self.plan.team_name, self.plan.sha256)
        payload = {
            "schema": "pfc.aitest.rc7.1.agent-teams-bootstrap.v1",
            "mission_id": self.plan.mission_id,
            "team_id": self.plan.team_name,
            "captain_session_id": captain,
            "plan_sha256": self.plan.sha256,
            "team_state_ref": "file://" + str(path),
            "team_state_sha256": "sha256:" + digest,
            "coordination_tool_policy": COORDINATION_TOOL_POLICY,
            "orchestration_mode": ORCHESTRATION_MODE,
            "r1_is_execution_dag_authority": True,
            "director_self_execution_forbidden": True,
            "reused_existing_team": bool(reused),
            **({"raw_bootstrap_ref": raw_ref} if raw_ref else {}),
        }
        folder = self.evidence_root / "agent-teams-bootstrap" / self.plan.mission_id
        folder.mkdir(parents=True, exist_ok=True)
        receipt_path = folder / (evidence_id + ".json")
        body = _canonical(payload)
        if not receipt_path.exists():
            receipt_path.write_bytes(body)
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=self.plan.mission_id,
            kind="DSH_AGENT_TEAMS_BOOTSTRAP",
            source_ref="dsh-agent-teams://%s" % self.plan.team_name,
            content_ref="file://" + str(receipt_path.resolve()),
            subject_refs=[self.plan.team_name] + [str(item["id"]) for item in self.plan.tasks],
            content_hash="sha256:" + hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        )
        existing = self.control.truth.query("rc7_evidence", evidence_id=evidence_id)
        if not existing:
            append_entity(self.control.truth, evidence, release_id=self.control.release_id, artifact_version=1)
        elif len(existing) != 1 or existing[0].get("content_hash") != evidence.content_hash:
            raise AgentTeamsBootstrapError("AGENT_TEAMS_BOOTSTRAP_R1_CONFLICT")
        return AgentTeamsBootstrapResult(
            team_id=self.plan.team_name,
            captain_session_id=captain,
            state_ref="file://" + str(path),
            state_sha256="sha256:" + digest,
            plan_sha256=self.plan.sha256,
            reused=reused,
            evidence_id=evidence_id,
        )

    def _dsh_available(self) -> bool:
        if os.path.isabs(self.dsh_bin) or os.sep in self.dsh_bin or (os.altsep and os.altsep in self.dsh_bin):
            return Path(self.dsh_bin).is_file()
        return shutil.which(self.dsh_bin) is not None
