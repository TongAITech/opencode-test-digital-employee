"""RC7.2 MissionNode WorkItem -> fresh AgentTeams assignment/lease bridge.

This layer consumes a governed MissionNode dispatch and grants exactly one
assignment-scoped worker identity a durable rc7_task lease. It deliberately
stops before DSH launch: no DSH session, Attempt, output, evidence, or NodeGate
decision is fabricated here.

The existing RC7 TaskScheduler remains the sole WorkItem lease authority.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Mapping

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_mission_node_dispatch import install_rc72_mission_node_dispatch_overlay
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_mission_node_worker_assignment"
_EVENT = "RC72_MISSION_NODE_WORKER_ASSIGNMENT_UPSERTED"
_BUCKET = "rc72_mission_node_worker_assignments"
_SUBSTRATE = "DSH_AGENT_TEAMS"
_WORKER_POLICY = "FRESH_SESSION_REQUIRED"
_STATUS = "LEASED_FOR_HANDOFF"
_NODE_TYPE = AutonomousMissionNode.N1_REALITY.value
_STAGE = "REALITY_RECON"
_TASK_TYPE = "RC72_NODE_WORK"
_TEAM_ROLE = "REALITY_RECON_WORKER"
_AGENT_ID = "reality-recon"
_GENERATION = 1


class MissionNodeAssignmentError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MissionNodeAssignmentError("RC72_ASSIGNMENT_%s_REQUIRED" % name.upper())
    return value.strip()


def _string_list(value: Any, name: str, *, allow_empty: bool = True) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError("RC72_ASSIGNMENT_%s_INVALID" % name.upper())
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("RC72_ASSIGNMENT_%s_INVALID" % name.upper())
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError("RC72_ASSIGNMENT_%s_DUPLICATE" % name.upper())
    if not allow_empty and not value:
        raise _contracts.DomainValidationError("RC72_ASSIGNMENT_%s_REQUIRED" % name.upper())
    return list(value)


def validate_rc72_mission_node_worker_assignment(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "assignment_id", "dispatch_id", "release_id", "mission_id",
        "release_batch_id", "source_commit", "mission_node_id", "node_type",
        "stage", "workitem_id", "team_role", "agent_id", "execution_substrate",
        "worker_policy", "worker_instance_id", "task_state", "status",
    ):
        out[name] = _contracts._require_str(out, name)

    if out["node_type"] != _NODE_TYPE:
        raise _contracts.DomainValidationError("RC72_ASSIGNMENT_NODE_NOT_SUPPORTED")
    if out["stage"] != _STAGE:
        raise _contracts.DomainValidationError("RC72_ASSIGNMENT_STAGE_INVALID")
    if out["team_role"] != _TEAM_ROLE:
        raise _contracts.DomainValidationError("RC72_ASSIGNMENT_TEAM_ROLE_INVALID")
    if out["agent_id"] != _AGENT_ID:
        raise _contracts.DomainValidationError("RC72_ASSIGNMENT_AGENT_ID_INVALID")
    if out["execution_substrate"] != _SUBSTRATE:
        raise _contracts.DomainValidationError("RC72_ASSIGNMENT_SUBSTRATE_INVALID")
    if out["worker_policy"] != _WORKER_POLICY:
        raise _contracts.DomainValidationError("RC72_ASSIGNMENT_WORKER_POLICY_INVALID")
    if out["task_state"] != "LEASED":
        raise _contracts.DomainValidationError("RC72_ASSIGNMENT_TASK_STATE_INVALID")
    if out["status"] != _STATUS:
        raise _contracts.DomainValidationError("RC72_ASSIGNMENT_STATUS_INVALID")

    generation = out.get("assignment_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation != _GENERATION:
        raise _contracts.DomainValidationError("RC72_ASSIGNMENT_GENERATION_INVALID")
    out["assignment_generation"] = generation
    out["required_capabilities"] = _string_list(
        out.get("required_capabilities"), "required_capabilities", allow_empty=False
    )
    out["input_refs"] = _string_list(
        out.get("input_refs"), "input_refs", allow_empty=False
    )
    recovered = out.get("recovered_orphan_lease", False)
    if not isinstance(recovered, bool):
        raise _contracts.DomainValidationError("RC72_ASSIGNMENT_RECOVERY_FLAG_INVALID")
    out["recovered_orphan_lease"] = recovered

    # Assignment/lease truth is not execution truth. An assignment-scoped
    # worker identity is allowed; a DSH session or Attempt is not.
    for forbidden in (
        "session_id", "dsh_session_id", "attempt_id", "execution_attempt_id",
        "execution_result", "output_refs", "evidence_refs", "node_gate",
        "q7_pass", "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_ASSIGNMENT_EXECUTION_CLAIM_FORBIDDEN:%s" % forbidden
            )

    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError("RC72_ASSIGNMENT_%s_INVALID" % name.upper())
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_ASSIGNMENT_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_mission_node_assignment_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_mission_node_dispatch_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_mission_node_worker_assignment
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "assignment_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "assignment_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class N1AgentTeamsAssignmentService:
    """Lease the governed N1 WorkItem to one assignment-scoped fresh worker."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_mission_node_assignment_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")

    @staticmethod
    def _assignment_id(dispatch_id: str, workitem_id: str) -> str:
        raw = "\x1f".join((dispatch_id, workitem_id, "GEN%d" % _GENERATION))
        return "N1ASN-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _worker_instance_id(assignment_id: str) -> str:
        raw = "\x1f".join((assignment_id, "FRESH_WORKER"))
        return "RC72FW-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _exact_dispatch(self, release_batch_id: str) -> Dict[str, Any]:
        rows = self.truth.query(
            "rc72_mission_node_dispatch", release_batch_id=release_batch_id
        )
        exact = [
            row for row in rows
            if row.get("source_commit") == self.source_commit
            and row.get("status") == "READY_FOR_ASSIGNMENT"
            and row.get("node_type") == _NODE_TYPE
            and row.get("stage") == _STAGE
            and row.get("execution_substrate") == _SUBSTRATE
            and row.get("worker_policy") == _WORKER_POLICY
        ]
        if len(exact) != 1:
            raise MissionNodeAssignmentError(
                "RC72_ASSIGNMENT_EXACT_DISPATCH_REQUIRED:%d" % len(exact)
            )
        return exact[0]

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "dispatch_id": payload.get("dispatch_id"),
            "release_id": payload.get("release_id"),
            "mission_id": payload.get("mission_id"),
            "release_batch_id": payload.get("release_batch_id"),
            "source_commit": payload.get("source_commit"),
            "mission_node_id": payload.get("mission_node_id"),
            "node_type": payload.get("node_type"),
            "stage": payload.get("stage"),
            "workitem_id": payload.get("workitem_id"),
            "team_role": payload.get("team_role"),
            "agent_id": payload.get("agent_id"),
            "execution_substrate": payload.get("execution_substrate"),
            "worker_policy": payload.get("worker_policy"),
            "worker_instance_id": payload.get("worker_instance_id"),
            "assignment_generation": payload.get("assignment_generation"),
            "required_capabilities": list(payload.get("required_capabilities") or []),
            "input_refs": list(payload.get("input_refs") or []),
            "task_state": payload.get("task_state"),
            "status": payload.get("status"),
        }

    def _preflight(self, release_batch_id: str) -> tuple:
        dispatch = self._exact_dispatch(release_batch_id)
        mission_id = _required(dispatch.get("mission_id"), "mission_id")
        release_id = _required(dispatch.get("release_id"), "release_id")
        node_id = _required(dispatch.get("mission_node_id"), "mission_node_id")
        workitem_id = _required(dispatch.get("workitem_id"), "workitem_id")

        batch_rows = self.truth.query("rc72_release_batch", release_batch_id=release_batch_id)
        if len(batch_rows) != 1:
            raise MissionNodeAssignmentError(
                "RC72_ASSIGNMENT_RELEASE_BATCH_NOT_UNIQUE:%d" % len(batch_rows)
            )
        batch = batch_rows[0]
        if batch.get("mission_id") != mission_id or batch.get("release_id") != release_id:
            raise MissionNodeAssignmentError("RC72_ASSIGNMENT_RELEASE_BATCH_LINEAGE_MISMATCH")

        node_rows = self.truth.query("rc72_mission_node", mission_node_id=node_id)
        if len(node_rows) != 1:
            raise MissionNodeAssignmentError(
                "RC72_ASSIGNMENT_MISSION_NODE_NOT_UNIQUE:%d" % len(node_rows)
            )
        node = node_rows[0]
        if (
            node.get("mission_id") != mission_id
            or node.get("node_type") != _NODE_TYPE
            or node.get("scope_ref") != "release-batch://%s" % release_batch_id
        ):
            raise MissionNodeAssignmentError("RC72_ASSIGNMENT_MISSION_NODE_LINEAGE_MISMATCH")
        if node.get("state") != MissionNodeState.RUNNING.value:
            raise MissionNodeAssignmentError(
                "RC72_ASSIGNMENT_N1_NOT_RUNNING:%s" % str(node.get("state") or "UNKNOWN")
            )

        task_rows = self.truth.query("rc7_task", task_id=workitem_id)
        if len(task_rows) != 1:
            raise MissionNodeAssignmentError(
                "RC72_ASSIGNMENT_WORKITEM_NOT_UNIQUE:%d" % len(task_rows)
            )
        task = task_rows[0]
        if (
            task.get("mission_id") != mission_id
            or task.get("node") != _STAGE
            or task.get("task_type") != _TASK_TYPE
        ):
            raise MissionNodeAssignmentError("RC72_ASSIGNMENT_WORKITEM_LINEAGE_MISMATCH")
        dispatch_caps = list(dispatch.get("required_capabilities") or [])
        task_caps = list(task.get("required_capabilities") or [])
        if task_caps != dispatch_caps or not task_caps:
            raise MissionNodeAssignmentError("RC72_ASSIGNMENT_CAPABILITY_DRIFT")

        mission_rows = self.truth.query("rc7_mission", mission_id=mission_id)
        if len(mission_rows) != 1 or mission_rows[0].get("release_id") != release_id:
            raise MissionNodeAssignmentError("RC72_ASSIGNMENT_RC7_MISSION_LINEAGE_INVALID")
        return dispatch, task, node

    def assign(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        dispatch, task, node = self._preflight(release_batch_id)
        mission_id = str(dispatch["mission_id"])
        release_id = str(dispatch["release_id"])
        workitem_id = str(dispatch["workitem_id"])
        dispatch_id = str(dispatch["dispatch_id"])
        node_id = str(dispatch["mission_node_id"])
        assignment_id = self._assignment_id(dispatch_id, workitem_id)
        worker_instance_id = self._worker_instance_id(assignment_id)

        expected_payload = {
            "assignment_id": assignment_id,
            "dispatch_id": dispatch_id,
            "release_id": release_id,
            "mission_id": mission_id,
            "release_batch_id": release_batch_id,
            "source_commit": self.source_commit,
            "mission_node_id": node_id,
            "node_type": _NODE_TYPE,
            "stage": _STAGE,
            "workitem_id": workitem_id,
            "team_role": _TEAM_ROLE,
            "agent_id": _AGENT_ID,
            "execution_substrate": _SUBSTRATE,
            "worker_policy": _WORKER_POLICY,
            "worker_instance_id": worker_instance_id,
            "assignment_generation": _GENERATION,
            "required_capabilities": list(dispatch.get("required_capabilities") or []),
            "input_refs": list(dispatch.get("input_refs") or []),
            "task_state": "LEASED",
            "status": _STATUS,
        }

        existing = self.truth.query(_ARTIFACT, assignment_id=assignment_id)
        if len(existing) > 1:
            raise MissionNodeAssignmentError("RC72_ASSIGNMENT_NOT_UNIQUE")
        if existing:
            if self._signature(existing[0]) != self._signature(expected_payload):
                raise MissionNodeAssignmentError("RC72_ASSIGNMENT_IDENTITY_CONFLICT")
            current = self.truth.query("rc7_task", task_id=workitem_id)
            if len(current) != 1 or current[0].get("lease_owner") != worker_instance_id:
                raise MissionNodeAssignmentError("RC72_ASSIGNMENT_RECEIPT_LEASE_MISMATCH")
            if current[0].get("state") not in {
                "LEASED", "RUNNING", "OUTPUT_PRODUCED", "EVALUATING", "PASS"
            }:
                raise MissionNodeAssignmentError(
                    "RC72_ASSIGNMENT_RECEIPT_TASK_STATE_INVALID:%s"
                    % str(current[0].get("state") or "UNKNOWN")
                )
            return {
                "status": "RESUMED",
                "assignment_id": assignment_id,
                "dispatch_id": dispatch_id,
                "workitem_id": workitem_id,
                "worker_instance_id": worker_instance_id,
                "workitem_state": str(current[0]["state"]),
                "mission_node_id": node_id,
                "node_state": str(node["state"]),
                "execution_substrate": _SUBSTRATE,
                "worker_policy": _WORKER_POLICY,
            }

        state = str(task.get("state") or "UNKNOWN")
        lease_owner = task.get("lease_owner")
        recovered_orphan = False
        if state == "LEASED":
            if lease_owner != worker_instance_id:
                raise MissionNodeAssignmentError("RC72_ASSIGNMENT_COMPETING_LEASE_OWNER")
            recovered_orphan = True
        elif state == "READY":
            if lease_owner:
                raise MissionNodeAssignmentError("RC72_ASSIGNMENT_READY_TASK_HAS_LEASE_OWNER")
            control = ClosedLoopControlPlane(self.truth, release_id, mission_id)
            ready = control.scheduler.ready_tasks(mission_id)
            if not ready or ready[0].task_id != workitem_id:
                observed = ready[0].task_id if ready else "NONE"
                raise MissionNodeAssignmentError(
                    "RC72_ASSIGNMENT_TARGET_NOT_NEXT_READY:%s" % observed
                )
            leased = control.lease_next(
                worker_ref=worker_instance_id,
                capabilities=expected_payload["required_capabilities"],
            )
            if leased is None or leased.task_id != workitem_id:
                raise MissionNodeAssignmentError("RC72_ASSIGNMENT_LEASE_MISMATCH")
        else:
            raise MissionNodeAssignmentError(
                "RC72_ASSIGNMENT_WORKITEM_NOT_ASSIGNABLE:%s" % state
            )

        current = self.truth.query("rc7_task", task_id=workitem_id)
        if len(current) != 1:
            raise MissionNodeAssignmentError("RC72_ASSIGNMENT_LEASE_PERSISTENCE_FAILED")
        if current[0].get("state") != "LEASED" or current[0].get("lease_owner") != worker_instance_id:
            raise MissionNodeAssignmentError("RC72_ASSIGNMENT_LEASE_NOT_OWNED")

        now = _now()
        payload = dict(expected_payload)
        payload.update(
            {
                "recovered_orphan_lease": recovered_orphan,
                "created_at": now,
                "updated_at": now,
                "artifact_version": 1,
            }
        )
        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, assignment_id=assignment_id)
        if len(rows) != 1:
            raise MissionNodeAssignmentError("RC72_ASSIGNMENT_PERSISTENCE_FAILED")

        return {
            "status": "RECOVERED" if recovered_orphan else "ASSIGNED",
            "assignment_id": assignment_id,
            "dispatch_id": dispatch_id,
            "workitem_id": workitem_id,
            "worker_instance_id": worker_instance_id,
            "workitem_state": "LEASED",
            "mission_node_id": node_id,
            "node_state": str(node["state"]),
            "execution_substrate": _SUBSTRATE,
            "worker_policy": _WORKER_POLICY,
            "team_role": _TEAM_ROLE,
            "agent_id": _AGENT_ID,
        }


install_rc72_mission_node_assignment_overlay()
