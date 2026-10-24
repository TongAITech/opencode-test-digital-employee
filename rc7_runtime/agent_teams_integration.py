"""RC7.1 BANK-only integration for dsh-agent-teams ownership."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agent_teams_bootstrap import (
    AgentTeamsBootstrapError,
    DshAgentTeamsMissionBootstrapper,
)
from .agent_teams_execution_binding import (
    AgentTeamsExecutionBindingError,
    AgentTeamsExecutionBindingGate,
)
from .agent_teams_orchestration import AgentTeamsOrchestrationError, DshAgentTeamsStateGate
from .mission_graph import MissionTaskGraphCompiler
from . import dsh_worker_bridge as _bridge


def _is_bank_launcher(launcher: Any) -> bool:
    cls = launcher.__class__
    return (
        cls.__name__ == "Rc7AuthorizedDshHeadlessWorkerLauncher"
        and cls.__module__ == "rc7_runtime.authorized_dsh_launcher"
    )


def _persisted_graph(control):
    """Recover the canonical root graph version without treating repair Tasks as roots."""
    rows = control.truth.query("rc7_task", mission_id=control.mission_id)
    nodes = {
        str(row.get("node") or "").strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("node") or "").strip()
    }
    graph_version = (
        MissionTaskGraphCompiler.GRAPH_V2
        if "REALITY_RECON" in nodes
        else MissionTaskGraphCompiler.GRAPH_V1
    )
    compiler = MissionTaskGraphCompiler(graph_version)
    graph = compiler.compile(control.mission_id)
    for task in graph.tasks:
        matches = [
            row for row in rows
            if row.get("task_id") == task.task_id and row.get("node") == task.node
        ]
        if len(matches) != 1:
            raise _bridge.DshWorkerBridgeError(
                "AGENT_TEAMS_CANONICAL_TASK_NOT_UNIQUE:%s:%d" % (task.node, len(matches))
            )
    return graph


def install_rc7_1_agent_teams_orchestration() -> None:
    bridge_cls = _bridge.DshTaskWorkerBridge
    if getattr(bridge_cls.__init__, "_rc7_1_agent_teams", False):
        return

    original_init = bridge_cls.__init__
    original_assign = bridge_cls._assign
    original_compile = bridge_cls.compile_prompt
    original_normalize = bridge_cls.normalize_output

    def patched_init(self, control, launcher, *, node_policies=None):
        original_init(self, control, launcher, node_policies=node_policies)
        self._rc7_agent_teams_bindings = {}
        self._rc7_agent_teams_gate = None
        self._rc7_agent_teams_execution_gate = None
        self._rc7_agent_teams_bootstrapper = None
        if _is_bank_launcher(launcher):
            state_root = Path(getattr(launcher, "state_root")).expanduser().resolve()
            workspace_root = Path(getattr(launcher, "cwd")).expanduser().resolve()
            self._rc7_agent_teams_gate = DshAgentTeamsStateGate(
                control,
                workspace_root=str(workspace_root),
                evidence_root=str(state_root / "evidence"),
            )
            self._rc7_agent_teams_execution_gate = AgentTeamsExecutionBindingGate(
                control,
                evidence_root=str(state_root / "evidence"),
            )
            self._rc7_agent_teams_bootstrapper = DshAgentTeamsMissionBootstrapper(
                control,
                graph=_persisted_graph(control),
                dsh_bin=str(getattr(launcher, "dsh_bin")),
                patch_path=str(getattr(launcher, "patch_path")),
                workspace_root=str(workspace_root),
                evidence_root=str(state_root / "evidence"),
                timeout_seconds=int(getattr(launcher, "timeout_seconds", 300)),
                command_runner=getattr(launcher, "command_runner", None),
            )

    def _binding_or_bootstrap(self, task):
        gate = getattr(self, "_rc7_agent_teams_gate", None)
        if gate is None:
            return None
        try:
            return gate.require_binding(task)
        except AgentTeamsOrchestrationError as exc:
            if str(exc) != "AGENT_TEAMS_MISSION_TEAM_REQUIRED":
                raise _bridge.DshWorkerBridgeError(str(exc)) from exc
        bootstrapper = getattr(self, "_rc7_agent_teams_bootstrapper", None)
        if bootstrapper is None:
            raise _bridge.DshWorkerBridgeError("AGENT_TEAMS_BOOTSTRAPPER_REQUIRED")
        try:
            bootstrapper.bootstrap()
        except AgentTeamsBootstrapError as exc:
            raise _bridge.DshWorkerBridgeError("AGENT_TEAMS_BOOTSTRAP_FAILED:%s" % exc) from exc
        try:
            return gate.require_binding(task)
        except AgentTeamsOrchestrationError as exc:
            raise _bridge.DshWorkerBridgeError(
                "AGENT_TEAMS_BINDING_MISSING_AFTER_BOOTSTRAP:%s" % exc
            ) from exc

    def patched_assign(self, task, policy):
        gate = getattr(self, "_rc7_agent_teams_gate", None)
        if gate is None:
            return original_assign(self, task, policy)
        binding = _binding_or_bootstrap(self, task)

        rows = self.control.truth.query("rc7_task", task_id=task.task_id)
        if len(rows) != 1:
            raise _bridge.DshWorkerBridgeError("DSH_TASK_REVISION_NOT_UNIQUE")
        revision = int(rows[0].get("artifact_version", 0))
        attempt_id = _bridge._stable_id(
            "ATT-DSH", task.mission_id, task.task_id, str(revision)
        )
        input_refs = list(task.input_artifact_refs) + [
            "gap://%s" % gap_id for gap_id in task.gap_refs
        ]
        assignment = self.launcher.assign(
            agent_id=policy.agent_id,
            role=policy.role,
            phase=policy.phase,
            mission_id=task.mission_id,
            attempt_id=attempt_id,
            scope="task:%s" % task.task_id,
            input_refs=input_refs,
            allowed_artifact_types=policy.allowed_artifact_types,
            allowed_tools=policy.allowed_tools,
            parent_worker_id=binding.member_id,
        )
        coordinator = str(getattr(self.launcher, "coordinator_instance_id", "") or "").strip()
        if assignment.parent_worker_id != binding.member_id:
            raise _bridge.DshWorkerBridgeError("AGENT_TEAMS_MEMBER_PARENT_BINDING_MISMATCH")
        if assignment.parent_worker_id == coordinator:
            raise _bridge.DshWorkerBridgeError("DIRECTOR_SELF_EXECUTION_FORBIDDEN")
        if assignment.worker_instance_id in {
            binding.member_id,
            binding.captain_session_id,
            coordinator,
        }:
            raise _bridge.DshWorkerBridgeError("AGENT_TEAMS_EXECUTION_IDENTITY_COLLISION")
        try:
            assignment_evidence = gate.persist_assignment_receipt(
                task,
                binding,
                worker_instance_id=assignment.worker_instance_id,
                worker_assignment_id=assignment.assignment_id,
                parent_worker_id=assignment.parent_worker_id,
            )
            execution_gate = getattr(self, "_rc7_agent_teams_execution_gate", None)
            if execution_gate is None:
                raise AgentTeamsExecutionBindingError("AGENT_TEAMS_EXECUTION_GATE_REQUIRED")
            execution_gate.persist_binding(
                task,
                binding,
                assignment,
                assignment_evidence_id=assignment_evidence.evidence_id,
            )
        except (AgentTeamsOrchestrationError, AgentTeamsExecutionBindingError) as exc:
            raise _bridge.DshWorkerBridgeError(str(exc)) from exc
        self._rc7_agent_teams_bindings[assignment.assignment_id] = binding
        return assignment

    def patched_compile(self, task, assignment):
        prompt = original_compile(self, task, assignment)
        if getattr(self, "_rc7_agent_teams_gate", None) is None:
            return prompt
        assignment_id = str(getattr(assignment, "assignment_id", "") or "").strip()
        if not assignment_id:
            raise _bridge.DshWorkerBridgeError("AGENT_TEAMS_ASSIGNMENT_ID_REQUIRED")
        binding = getattr(self, "_rc7_agent_teams_bindings", {}).get(assignment_id)
        if binding is None:
            raise _bridge.DshWorkerBridgeError("AGENT_TEAMS_PROMPT_BINDING_REQUIRED")
        return prompt + "\nTEAM_ASSIGNMENT_CONTRACT=" + json.dumps(
            binding.as_contract(), ensure_ascii=False, sort_keys=True
        )

    def patched_normalize(self, task, invocation, raw_output):
        gate = getattr(self, "_rc7_agent_teams_gate", None)
        binding = None
        if gate is not None:
            assignment_id = str(getattr(invocation, "assignment_id", "") or "").strip()
            binding = getattr(self, "_rc7_agent_teams_bindings", {}).get(assignment_id)
            if binding is None:
                raise _bridge.DshWorkerBridgeError("AGENT_TEAMS_INVOCATION_BINDING_REQUIRED")
            if getattr(invocation, "parent_worker_id", None) != binding.member_id:
                raise _bridge.DshWorkerBridgeError("AGENT_TEAMS_INVOCATION_MEMBER_MISMATCH")

        normalized = original_normalize(self, task, invocation, raw_output)
        if gate is not None:
            execution_gate = getattr(self, "_rc7_agent_teams_execution_gate", None)
            if execution_gate is None:
                raise _bridge.DshWorkerBridgeError("AGENT_TEAMS_EXECUTION_GATE_REQUIRED")
            try:
                execution_gate.verify_terminal_and_persist(task, binding, invocation)
            except AgentTeamsExecutionBindingError as exc:
                raise _bridge.DshWorkerBridgeError(str(exc)) from exc
        return normalized

    patched_init._rc7_1_agent_teams = True
    bridge_cls.__init__ = patched_init
    bridge_cls._assign = patched_assign
    bridge_cls.compile_prompt = patched_compile
    bridge_cls.normalize_output = patched_normalize
