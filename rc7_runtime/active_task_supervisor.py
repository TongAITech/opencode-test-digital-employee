"""RC7.1 R1-native ACTIVE_TASK supervisor.

A process/session restart must not require the user to type ``continue``.  The
supervisor consumes only canonical Task truth and either:

* returns an orphaned LEASED Task to READY before any worker was started;
* fences an orphaned read-only RUNNING DSH worker through SessionHandoff and
  relaunches the same durable Task in a fresh worker/session; or
* stops fail-closed at a HUMAN_REQUIRED ``SIDE_EFFECT_UNCERTAIN`` boundary when
  replay could duplicate a business/local mutation.

No second supervisor state store exists.  Late output from the predecessor
worker is rejected because SessionContinuity changes the canonical lease owner.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional, Tuple

from .closed_loop_control import ClosedLoopControlPlane
from .dsh_worker_bridge import DshTaskRunResult, DshTaskWorkerBridge, DshWorkerBridgeError
from .models import Evaluation, EvaluationResult, Evidence, Gap, GapSeverity, MissionStatus, Task, TaskStatus
from .state_machine import transition_mission, transition_task
from .truth_overlay import append_entity


class ActiveTaskSupervisorError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


class RecoverableDshTaskWorkerBridge(DshTaskWorkerBridge):
    """Resume one already-active DSH producer under a fresh fenced worker."""

    def resume_active(self, task: Task) -> DshTaskRunResult:
        current = self.control.scheduler.task(task.task_id)
        if current.state not in {TaskStatus.LEASED, TaskStatus.RUNNING}:
            raise DshWorkerBridgeError(
                "DSH_ACTIVE_RESUME_REQUIRES_LEASED_OR_RUNNING:%s" % current.state.value
            )
        policy = self.node_policies.get(current.node)
        if policy is None:
            raise DshWorkerBridgeError("ACTIVE_TASK_HAS_NO_DSH_POLICY:%s" % current.node)
        predecessor = str(current.lease_owner or "").strip()
        if not predecessor:
            raise DshWorkerBridgeError("ACTIVE_TASK_PREDECESSOR_LEASE_REQUIRED")

        # Assignment is created before the R1 handoff so its exact worker id can
        # become the successor lease owner.  A reused worker id is forbidden.
        assignment = self._assign(current, policy)
        successor = str(assignment.worker_instance_id or "").strip()
        if not successor or successor == predecessor:
            raise DshWorkerBridgeError("ACTIVE_TASK_SUCCESSOR_WORKER_MUST_BE_FRESH")

        handoff = self.control.sessions.prepare(
            mission_id=current.mission_id,
            task_id=current.task_id,
            predecessor_session_ref=predecessor,
            artifact_refs=tuple(current.output_artifact_refs),
            gap_refs=tuple(current.gap_refs),
        )
        self.control.sessions.activate(handoff.handoff_id, successor)
        resumed = self.control.scheduler.task(current.task_id)
        if resumed.lease_owner != successor:
            raise DshWorkerBridgeError("ACTIVE_TASK_SUCCESSOR_LEASE_NOT_ACTIVE")
        if resumed.state == TaskStatus.LEASED:
            resumed = self.control.start(resumed.task_id, worker_ref=successor)
        if resumed.state != TaskStatus.RUNNING:
            raise DshWorkerBridgeError("ACTIVE_TASK_SUCCESSOR_NOT_RUNNING")

        prompt = self.compile_prompt(resumed, assignment)
        invocation, raw_output = self.launcher.execute(assignment, prompt)
        worker_output = self.normalize_output(resumed, invocation, raw_output)
        candidate = self.control.submit_worker_output(worker_output)
        if candidate.state != TaskStatus.OUTPUT_PRODUCED:
            raise DshWorkerBridgeError("DSH_RECOVERED_WORKER_MUST_STOP_AT_OUTPUT_PRODUCED")
        raw_output_ref = next(
            (ref for ref in invocation.evidence_refs if isinstance(ref, str) and ref.startswith("file://")),
            "",
        )
        return DshTaskRunResult(
            task_id=resumed.task_id,
            worker_instance_id=successor,
            dsh_session_id=invocation.dsh_session_id or "",
            tool_call_count=len(invocation.tool_calls),
            raw_output_ref=raw_output_ref,
            output_artifact_ids=tuple(candidate.output_artifact_refs),
            evidence_ids=tuple(item.evidence_id for item in worker_output.evidence),
            task_state=candidate.state.value,
        )


class MissionActiveTaskSupervisor:
    """Deterministic recovery authority for orphaned LEASED/RUNNING tasks."""

    # These production field policies contain only source/truth/code discovery
    # reads/probes.  TEST_DESIGN is intentionally excluded because its field
    # tool set contains artifact_record; SCRIPT contains build/validate runners;
    # RUNTIME contains recovery_execute; EXECUTION is business side-effecting.
    REPLAY_SAFE_RUNNING_NODES = frozenset({"REQUIREMENT_ANALYSIS", "CODE_ANALYSIS"})

    def __init__(
        self,
        control: ClosedLoopControlPlane,
        bridge: RecoverableDshTaskWorkerBridge,
        *,
        evidence_root: str,
    ) -> None:
        if bridge.control is not control:
            raise ActiveTaskSupervisorError("SUPERVISOR_BRIDGE_CONTROL_MISMATCH")
        self.control = control
        self.bridge = bridge
        self.evidence_root = Path(evidence_root).expanduser().resolve()

    def handle(self, task: Task):
        current = self.control.scheduler.task(task.task_id)
        if current.state == TaskStatus.LEASED:
            return self._reset_unstarted_lease(current)
        if current.state == TaskStatus.RUNNING:
            if current.node in self.REPLAY_SAFE_RUNNING_NODES and not current.output_artifact_refs:
                return self.bridge.resume_active(current)
            return self._human_side_effect_boundary(current, reason="RUNNING_TASK_SIDE_EFFECT_STATE_UNCERTAIN")
        if current.state == TaskStatus.EVALUATING:
            return self._human_side_effect_boundary(current, reason="EVALUATION_COMMIT_STATE_UNCERTAIN")
        raise ActiveTaskSupervisorError(
            "SUPERVISOR_ACTIVE_STATE_UNSUPPORTED:%s:%s" % (current.task_id, current.state.value)
        )

    def _reset_unstarted_lease(self, task: Task) -> Task:
        # The control plane always moves LEASED -> RUNNING before invoking a
        # worker/runtime process.  Therefore a durable LEASED row is safe to
        # return to READY after coordinator death: no worker has been started by
        # this Task state yet.
        row = self.control.truth.query("rc7_task", task_id=task.task_id)
        if len(row) != 1:
            raise ActiveTaskSupervisorError("LEASE_RESET_TASK_NOT_UNIQUE")
        predecessor = str(task.lease_owner or "").strip()
        if not predecessor:
            raise ActiveTaskSupervisorError("LEASE_RESET_PREDECESSOR_REQUIRED")
        evidence = self._recovery_evidence(
            task,
            action="RESET_LEASED_TO_READY",
            reason="ORPHANED_BEFORE_WORKER_START",
            predecessor=predecessor,
        )
        append_entity(self.control.truth, evidence, release_id=self.control.release_id, artifact_version=1)
        transition_task(task, TaskStatus.READY)
        self.control.scheduler._persist_task(task, int(row[0]["artifact_version"]) + 1)
        self.control._sync_mission(self.control._mission())
        return self.control.scheduler.task(task.task_id)

    def _human_side_effect_boundary(self, task: Task, *, reason: str) -> Task:
        predecessor = str(task.lease_owner or "").strip()
        evidence = self._recovery_evidence(
            task,
            action="SIDE_EFFECT_UNCERTAIN",
            reason=reason,
            predecessor=predecessor,
        )
        append_entity(self.control.truth, evidence, release_id=self.control.release_id, artifact_version=1)
        gap = Gap(
            gap_id=_stable_id("GAP-ACTIVE-UNCERTAIN", task.mission_id, task.task_id, task.state.value, reason),
            mission_id=task.mission_id,
            source_node=task.node,
            category="RESIDUAL_RISK_REQUIRES_ACCEPTANCE",
            severity=GapSeverity.BLOCKER,
            target_node="HUMAN_GATE",
            description=(
                "Active task ownership was lost after work may have started; automatic replay is forbidden "
                "until side effects are proven absent or reconciled from durable evidence."
            ),
            subject_refs=[task.task_id, task.node, task.state.value],
            evidence_refs=[evidence.evidence_id],
            acceptance_criteria=[
                "prove predecessor produced no side effect, or reconcile the exact side effect from durable evidence",
                "only then return the same Mission/Task lineage to READY; never blind-replay the predecessor attempt",
            ],
        )
        # Route policy is checked before any state mutation.
        self.control.gap_planner.router.route(gap)
        evaluation = Evaluation(
            evaluation_id=_stable_id("EVAL-ACTIVE-UNCERTAIN", task.mission_id, task.task_id, task.state.value, reason),
            mission_id=task.mission_id,
            node=task.node,
            artifact_refs=list(task.output_artifact_refs),
            result=EvaluationResult.HUMAN_REQUIRED,
            evaluator_ref="rc7.1-active-task-supervisor",
            dimensions={
                "recovery_action": "SIDE_EFFECT_UNCERTAIN",
                "predecessor_lease_owner": predecessor or None,
                "active_state": task.state.value,
                "blind_replay_forbidden": True,
            },
            gap_refs=[gap.gap_id],
            evidence_refs=[evidence.evidence_id],
        )
        append_entity(self.control.truth, evaluation, release_id=self.control.release_id, artifact_version=1)
        if gap.gap_id not in task.gap_refs:
            task.gap_refs.append(gap.gap_id)
        transition_task(task, TaskStatus.HUMAN_REQUIRED, evaluation_id=evaluation.evaluation_id)
        self.control.scheduler.persist_evaluated_task(task)
        # HUMAN_GATE routing persists the Gap directly as HUMAN_REQUIRED and
        # deliberately creates no executable repair worker.
        self.control.gap_planner.plan(gap)
        mission = self.control._mission()
        if mission.state in {MissionStatus.RUNNING, MissionStatus.REPAIRING, MissionStatus.EVALUATING}:
            transition_mission(mission, MissionStatus.WAITING_HUMAN)
        self.control._sync_mission(mission)
        return self.control.scheduler.task(task.task_id)

    def _recovery_evidence(self, task: Task, *, action: str, reason: str, predecessor: str) -> Evidence:
        payload = {
            "schema": "pfc.aitest.rc7.1.active-task-recovery.v1",
            "mission_id": task.mission_id,
            "task_id": task.task_id,
            "node": task.node,
            "task_type": task.task_type,
            "active_state": task.state.value,
            "predecessor_lease_owner": predecessor or None,
            "action": action,
            "reason": reason,
            "output_artifact_refs": list(task.output_artifact_refs),
            "gap_refs": list(task.gap_refs),
        }
        folder = self.evidence_root / "active-task-recovery" / task.mission_id
        folder.mkdir(parents=True, exist_ok=True)
        body = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        evidence_id = _stable_id("EVD-ACTIVE-RECOVERY", task.mission_id, task.task_id, action, digest)
        path = folder / (evidence_id + ".json")
        if path.exists() and path.read_bytes() != body:
            raise ActiveTaskSupervisorError("ACTIVE_TASK_RECOVERY_EVIDENCE_IMMUTABILITY_CONFLICT")
        if not path.exists():
            path.write_bytes(body)
        return Evidence(
            evidence_id=evidence_id,
            mission_id=task.mission_id,
            kind="ACTIVE_TASK_RECOVERY",
            source_ref="runtime://rc7.1-active-task-supervisor",
            content_ref="file://" + str(path),
            subject_refs=[task.task_id, task.node, action],
            content_hash="sha256:" + digest,
        )
