"""RC7.2 N3 source-target discovery WorkItem -> fresh AgentTeams assignment.

Each canonical application gets an independent discovery worker. Assignment is
lease truth only: no DSH session, source-target mapping, repository/revision,
CODE_ANALYSIS result, NodeGate or N4 claim may appear here.
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
from .rc72_n3_source_target_dispatch import install_rc72_n3_source_target_dispatch_overlay
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n3_source_target_assignment"
_EVENT = "RC72_N3_SOURCE_TARGET_ASSIGNMENT_UPSERTED"
_BUCKET = "rc72_n3_source_target_assignments"
_NODE_TYPE = AutonomousMissionNode.N3_CODE_ANALYSIS.value
_STAGE = "SOURCE_TARGET_DISCOVERY"
_TASK_TYPE = "RC72_NODE_WORK"
_TEAM_ROLE = "SOURCE_TARGET_DISCOVERY_WORKER"
_AGENT_ID = "source-target-discovery"
_SUBSTRATE = "DSH_AGENT_TEAMS"
_WORKER_POLICY = "FRESH_SESSION_REQUIRED"
_STATUS = "LEASED_FOR_HANDOFF"
_GENERATION = 1


class N3SourceTargetAssignmentError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3SourceTargetAssignmentError(
            "RC72_N3_SOURCE_ASSIGNMENT_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _strings(value: Any, name: str, *, required: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_ASSIGNMENT_%s_INVALID" % name.upper()
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_ASSIGNMENT_%s_INVALID" % name.upper()
        )
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_ASSIGNMENT_%s_DUPLICATE" % name.upper()
        )
    if required and not value:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_ASSIGNMENT_%s_REQUIRED" % name.upper()
        )
    return list(value)


def validate_rc72_n3_source_target_assignment(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "assignment_id", "dispatch_id", "release_id", "mission_id",
        "release_batch_id", "source_commit", "mission_node_id", "node_type",
        "stage", "application_id", "workitem_id", "team_role", "agent_id",
        "execution_substrate", "worker_policy", "worker_instance_id",
        "task_state", "status",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["node_type"] != _NODE_TYPE or out["stage"] != _STAGE:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_ASSIGNMENT_NODE_INVALID")
    if out["team_role"] != _TEAM_ROLE or out["agent_id"] != _AGENT_ID:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_ASSIGNMENT_ROLE_INVALID")
    if out["execution_substrate"] != _SUBSTRATE or out["worker_policy"] != _WORKER_POLICY:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_ASSIGNMENT_SUBSTRATE_INVALID")
    if out["task_state"] != "LEASED" or out["status"] != _STATUS:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_ASSIGNMENT_STATE_INVALID")
    generation = out.get("assignment_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation != _GENERATION:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_ASSIGNMENT_GENERATION_INVALID")
    out["assignment_generation"] = generation
    out["required_capabilities"] = _strings(
        out.get("required_capabilities"), "required_capabilities", required=True
    )
    out["input_refs"] = _strings(out.get("input_refs"), "input_refs", required=True)
    recovered = out.get("recovered_orphan_lease", False)
    if not isinstance(recovered, bool):
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_ASSIGNMENT_RECOVERY_FLAG_INVALID")
    out["recovered_orphan_lease"] = recovered
    for forbidden in (
        "repository", "repository_ref", "source_revision", "head_revision",
        "base_revision", "target_id", "session_id", "dsh_session_id", "attempt_id",
        "output_refs", "evidence_refs", "evaluation", "code_analysis_result",
        "node_gate", "node_pass", "n4_started", "q7_pass", "field_verified",
        "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N3_SOURCE_ASSIGNMENT_EXECUTION_CLAIM_FORBIDDEN:%s" % forbidden
            )
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N3_SOURCE_ASSIGNMENT_%s_INVALID" % name.upper()
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_ASSIGNMENT_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n3_source_target_assignment_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_n3_source_target_dispatch_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n3_source_target_assignment
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


class N3SourceTargetAssignmentService:
    """Lease all N3 discovery WorkItems to distinct assignment-scoped workers."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_n3_source_target_assignment_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")

    @staticmethod
    def _assignment_id(dispatch_id: str, workitem_id: str) -> str:
        raw = "\x1f".join((dispatch_id, workitem_id, "GEN1"))
        return "N3SRCASN-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _worker_id(assignment_id: str) -> str:
        raw = "\x1f".join((assignment_id, "FRESH_SOURCE_DISCOVERY_WORKER"))
        return "RC72N3SRCFW-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _input_refs(dispatch: Mapping[str, Any]) -> List[str]:
        refs = ["application://%s" % str(dispatch["application_id"])]
        refs.extend(str(ref) for ref in list(dispatch.get("source_n1_artifact_refs") or []))
        refs.extend(str(ref) for ref in list(dispatch.get("source_n2_artifact_refs") or []))
        refs.extend((
            "node-delivery://%s" % str(dispatch["source_n1_delivery_id"]),
            "node-gate://%s" % str(dispatch["source_n1_gate_id"]),
            "node-delivery://%s" % str(dispatch["source_n2_delivery_id"]),
            "node-gate://%s" % str(dispatch["source_n2_gate_id"]),
        ))
        return list(dict.fromkeys(refs))

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        keys = (
            "dispatch_id", "release_id", "mission_id", "release_batch_id",
            "source_commit", "mission_node_id", "node_type", "stage",
            "application_id", "workitem_id", "team_role", "agent_id",
            "execution_substrate", "worker_policy", "worker_instance_id",
            "assignment_generation", "task_state", "status",
        )
        result = {key: payload.get(key) for key in keys}
        result["required_capabilities"] = list(payload.get("required_capabilities") or [])
        result["input_refs"] = list(payload.get("input_refs") or [])
        return result

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N3SourceTargetAssignmentError(
                "RC72_N3_SOURCE_ASSIGNMENT_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def assign_all(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        mission_id = str(batch["mission_id"])
        release_id = str(batch["release_id"])
        applications = list(batch.get("application_ids") or [])
        if not applications or len(set(applications)) != len(applications):
            raise N3SourceTargetAssignmentError(
                "RC72_N3_SOURCE_ASSIGNMENT_CANONICAL_APPLICATIONS_REQUIRED"
            )
        node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NODE_TYPE
        )
        if node.get("state") != MissionNodeState.RUNNING.value:
            raise N3SourceTargetAssignmentError("RC72_N3_SOURCE_ASSIGNMENT_N3_NOT_RUNNING")
        rows = self.truth.query(
            "rc72_n3_source_target_dispatch", release_batch_id=release_batch_id
        )
        dispatches = [
            row for row in rows
            if row.get("source_commit") == self.source_commit
            and row.get("node_type") == _NODE_TYPE
            and row.get("stage") == _STAGE
            and row.get("status") == "READY_FOR_ASSIGNMENT"
        ]
        by_app = {str(row.get("application_id")): row for row in dispatches}
        if len(dispatches) != len(applications) or set(by_app) != set(applications):
            raise N3SourceTargetAssignmentError(
                "RC72_N3_SOURCE_ASSIGNMENT_EXACT_DISPATCH_SET_REQUIRED"
            )

        plans = []
        for application_id in applications:
            dispatch = by_app[application_id]
            workitem_id = str(dispatch["workitem_id"])
            task = self._one("rc7_task", task_id=workitem_id)
            if (
                task.get("mission_id") != mission_id
                or task.get("node") != _STAGE
                or task.get("task_type") != _TASK_TYPE
                or list(task.get("required_capabilities") or []) != list(dispatch.get("required_capabilities") or [])
            ):
                raise N3SourceTargetAssignmentError(
                    "RC72_N3_SOURCE_ASSIGNMENT_WORKITEM_LINEAGE_MISMATCH:%s" % workitem_id
                )
            assignment_id = self._assignment_id(str(dispatch["dispatch_id"]), workitem_id)
            worker_id = self._worker_id(assignment_id)
            expected = {
                "assignment_id": assignment_id,
                "dispatch_id": str(dispatch["dispatch_id"]),
                "release_id": release_id,
                "mission_id": mission_id,
                "release_batch_id": release_batch_id,
                "source_commit": self.source_commit,
                "mission_node_id": str(node["mission_node_id"]),
                "node_type": _NODE_TYPE,
                "stage": _STAGE,
                "application_id": application_id,
                "workitem_id": workitem_id,
                "team_role": _TEAM_ROLE,
                "agent_id": _AGENT_ID,
                "execution_substrate": _SUBSTRATE,
                "worker_policy": _WORKER_POLICY,
                "worker_instance_id": worker_id,
                "assignment_generation": _GENERATION,
                "required_capabilities": list(dispatch["required_capabilities"]),
                "input_refs": self._input_refs(dispatch),
                "task_state": "LEASED",
                "status": _STATUS,
            }
            existing = self.truth.query(_ARTIFACT, assignment_id=assignment_id)
            if len(existing) > 1:
                raise N3SourceTargetAssignmentError("RC72_N3_SOURCE_ASSIGNMENT_NOT_UNIQUE")
            state = str(task.get("state") or "UNKNOWN")
            lease_owner = task.get("lease_owner")
            if existing:
                if self._signature(existing[0]) != self._signature(expected):
                    raise N3SourceTargetAssignmentError("RC72_N3_SOURCE_ASSIGNMENT_IDENTITY_CONFLICT")
                if lease_owner != worker_id:
                    raise N3SourceTargetAssignmentError("RC72_N3_SOURCE_ASSIGNMENT_RECEIPT_LEASE_MISMATCH")
                mode = "RESUMED"
            elif state == "LEASED":
                if lease_owner != worker_id:
                    raise N3SourceTargetAssignmentError(
                        "RC72_N3_SOURCE_ASSIGNMENT_COMPETING_LEASE_OWNER:%s" % workitem_id
                    )
                mode = "RECOVER_ORPHAN"
            elif state == "READY" and not lease_owner:
                mode = "NEW"
            else:
                raise N3SourceTargetAssignmentError(
                    "RC72_N3_SOURCE_ASSIGNMENT_WORKITEM_NOT_ASSIGNABLE:%s:%s"
                    % (workitem_id, state)
                )
            plans.append((dispatch, task, expected, mode))

        if all(item[3] == "RESUMED" for item in plans):
            return {
                "status": "RESUMED", "release_batch_id": release_batch_id,
                "mission_id": mission_id,
                "assignments": [item[2] for item in plans],
            }
        if any(item[3] == "RESUMED" for item in plans):
            raise N3SourceTargetAssignmentError("RC72_N3_SOURCE_ASSIGNMENT_PARTIAL_RECEIPT_SET")

        control = ClosedLoopControlPlane(self.truth, release_id, mission_id)
        new_ids = {str(item[1]["task_id"]) for item in plans if item[3] == "NEW"}
        ready = list(control.scheduler.ready_tasks(mission_id))
        foreign = [task.task_id for task in ready if task.task_id not in new_ids]
        if foreign:
            raise N3SourceTargetAssignmentError(
                "RC72_N3_SOURCE_ASSIGNMENT_FOREIGN_READY_TASK_CONFLICT:%s"
                % ",".join(sorted(foreign))
            )
        if {task.task_id for task in ready} != new_ids:
            raise N3SourceTargetAssignmentError("RC72_N3_SOURCE_ASSIGNMENT_READY_SET_MISMATCH")

        by_task = {str(item[1]["task_id"]): item for item in plans}
        for task in ready:
            dispatch, _task, expected, mode = by_task[task.task_id]
            leased = control.lease_next(
                worker_ref=str(expected["worker_instance_id"]),
                capabilities=list(expected["required_capabilities"]),
            )
            if leased is None or leased.task_id != task.task_id:
                raise N3SourceTargetAssignmentError(
                    "RC72_N3_SOURCE_ASSIGNMENT_LEASE_IDENTITY_MISMATCH:%s" % task.task_id
                )
        now = _now()
        for dispatch, task, expected, mode in plans:
            if mode == "RESUMED":
                continue
            payload = dict(expected)
            payload["recovered_orphan_lease"] = mode == "RECOVER_ORPHAN"
            payload.update({"created_at": now, "updated_at": now, "artifact_version": 1})
            self.truth.append_atomic(_EVENT, payload)
        return {
            "status": "ASSIGNED", "release_batch_id": release_batch_id,
            "mission_id": mission_id,
            "assignments": [item[2] for item in plans],
        }


install_rc72_n3_source_target_assignment_overlay()
