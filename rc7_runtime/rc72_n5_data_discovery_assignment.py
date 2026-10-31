"""RC7.2 N5 data-discovery WorkItem -> fresh AgentTeams assignment.

Discovery dispatch creates one durable TEST_DATA WorkItem per unresolved
DataRequirement.  This layer leases each WorkItem to one deterministic,
assignment-scoped fresh DATA_PREPARER identity using the canonical RC7
scheduler.  It deliberately stops before DSH launch: no session, Attempt, DB
query, DataRef, binding, DataLease, NodeDelivery, Gate or PASS claim is created.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Mapping, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError
from .rc72_n5_data_discovery_dispatch import (
    install_rc72_n5_data_discovery_dispatch_overlay,
)
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n5_data_discovery_assignment"
_EVENT = "RC72_N5_DATA_DISCOVERY_ASSIGNMENT_UPSERTED"
_BUCKET = "rc72_n5_data_discovery_assignments"
_STAGE = "TEST_DATA"
_TASK_TYPE = "RC72_NODE_WORK"
_TEAM_ROLE = "DATA_PREPARER"
_AGENT_ID = "data-preparer"
_SUBSTRATE = "DSH_AGENT_TEAMS"
_WORKER_POLICY = "FRESH_SESSION_REQUIRED"
_STATUS = "LEASED_FOR_HANDOFF"
_GENERATION = 1
_INSTALLED = False


class N5DataDiscoveryAssignmentError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N5DataDiscoveryAssignmentError(
            "RC72_N5_DISCOVERY_ASSIGNMENT_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _string_list(value: Any, name: str, *, allow_empty: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ASSIGNMENT_%s_INVALID" % name.upper()
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ASSIGNMENT_%s_INVALID" % name.upper()
        )
    if len(value) != len(set(value)):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ASSIGNMENT_%s_DUPLICATE" % name.upper()
        )
    if not allow_empty and not value:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ASSIGNMENT_%s_REQUIRED" % name.upper()
        )
    return list(value)


def validate_rc72_n5_data_discovery_assignment(
    payload: Dict[str, Any]
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "assignment_id",
        "dispatch_id",
        "release_id",
        "mission_id",
        "release_batch_id",
        "source_commit",
        "mission_node_id",
        "data_requirement_id",
        "resolution_plan_id",
        "source_case_sha256",
        "requirement_id",
        "sst_id",
        "obligation_id",
        "case_id",
        "workitem_id",
        "stage",
        "team_role",
        "agent_id",
        "execution_substrate",
        "worker_policy",
        "worker_instance_id",
        "task_state",
        "status",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["stage"] != _STAGE:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ASSIGNMENT_STAGE_INVALID"
        )
    if out["team_role"] != _TEAM_ROLE or out["agent_id"] != _AGENT_ID:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ASSIGNMENT_ROLE_INVALID"
        )
    if out["execution_substrate"] != _SUBSTRATE:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ASSIGNMENT_SUBSTRATE_INVALID"
        )
    if out["worker_policy"] != _WORKER_POLICY:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ASSIGNMENT_WORKER_POLICY_INVALID"
        )
    if out["task_state"] != "LEASED" or out["status"] != _STATUS:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ASSIGNMENT_STATE_INVALID"
        )
    generation = out.get("assignment_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation != _GENERATION:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ASSIGNMENT_GENERATION_INVALID"
        )
    out["assignment_generation"] = generation
    out["required_capabilities"] = _string_list(
        out.get("required_capabilities"), "required_capabilities"
    )
    out["input_refs"] = _string_list(out.get("input_refs"), "input_refs")
    recovered = out.get("recovered_orphan_lease", False)
    if not isinstance(recovered, bool):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ASSIGNMENT_RECOVERY_FLAG_INVALID"
        )
    out["recovered_orphan_lease"] = recovered
    for forbidden in (
        "session_id",
        "dsh_session_id",
        "attempt_id",
        "execution_result",
        "output_refs",
        "evidence_refs",
        "data_ref",
        "binding_id",
        "verification",
        "verified",
        "reserved",
        "data_lease_id",
        "node_pass",
        "n5_pass",
        "n6_ready",
        "field_verified",
        "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N5_DISCOVERY_ASSIGNMENT_EXECUTION_CLAIM_FORBIDDEN:%s"
                % forbidden
            )
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N5_DISCOVERY_ASSIGNMENT_%s_INVALID" % name.upper()
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ASSIGNMENT_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n5_data_discovery_assignment_overlay() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    install_rc7_truth_overlay()
    install_rc72_n5_data_discovery_dispatch_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n5_data_discovery_assignment
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "assignment_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "assignment_id")
    _INSTALLED = True


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class N5DataDiscoveryAssignmentService:
    """Lease all N5 discovery WorkItems to distinct fresh worker identities."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        source_commit: str,
    ) -> None:
        install_rc72_n5_data_discovery_assignment_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.release_id = _required(release_id, "release_id")
        self.source_commit = _required(source_commit, "source_commit")

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N5DataDiscoveryAssignmentError(
                "RC72_N5_DISCOVERY_ASSIGNMENT_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    @staticmethod
    def _assignment_id(dispatch_id: str, workitem_id: str) -> str:
        return "N5DASN-%s" % hashlib.sha256(
            (dispatch_id + "\x1f" + workitem_id + "\x1fGEN1").encode("utf-8")
        ).hexdigest()[:24]

    @staticmethod
    def _worker_instance_id(assignment_id: str) -> str:
        return "RC72N5DFW-%s" % hashlib.sha256(
            (assignment_id + "\x1fFRESH_DATA_DISCOVERY_WORKER").encode("utf-8")
        ).hexdigest()[:24]

    @staticmethod
    def _input_refs(dispatch: Mapping[str, Any]) -> List[str]:
        refs = [
            "data-requirement://%s" % str(dispatch["data_requirement_id"]),
            "data-resolution-plan://%s" % str(dispatch["resolution_plan_id"]),
            "requirement://%s" % str(dispatch["requirement_id"]),
            "sst://%s" % str(dispatch["sst_id"]),
            "obligation://%s" % str(dispatch["obligation_id"]),
            "case://%s" % str(dispatch["case_id"]),
        ]
        refs.extend(
            "artifact://%s" % str(item)
            for item in list(dispatch.get("parent_artifact_refs") or [])
        )
        return refs

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        scalars = (
            "dispatch_id",
            "release_id",
            "mission_id",
            "release_batch_id",
            "source_commit",
            "mission_node_id",
            "data_requirement_id",
            "resolution_plan_id",
            "source_case_sha256",
            "requirement_id",
            "sst_id",
            "obligation_id",
            "case_id",
            "workitem_id",
            "stage",
            "team_role",
            "agent_id",
            "execution_substrate",
            "worker_policy",
            "worker_instance_id",
            "assignment_generation",
            "task_state",
            "status",
        )
        out = {name: payload.get(name) for name in scalars}
        out["required_capabilities"] = list(payload.get("required_capabilities") or [])
        out["input_refs"] = list(payload.get("input_refs") or [])
        return out

    def _preflight(
        self, release_batch_id: str
    ) -> Tuple[str, str, Dict[str, Any], List[Dict[str, Any]]]:
        snapshot = self._one(
            "rc72_n5_data_inventory_snapshot", release_batch_id=release_batch_id
        )
        mission_id = _required(snapshot.get("mission_id"), "mission_id")
        release_id = _required(snapshot.get("release_id"), "release_id")
        if release_id != self.release_id or snapshot.get("source_commit") != self.source_commit:
            raise N5DataDiscoveryAssignmentError(
                "RC72_N5_DISCOVERY_ASSIGNMENT_SNAPSHOT_LINEAGE_INVALID"
            )
        node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type="N5_TEST_DATA"
        )
        next_node = self._one(
            "rc72_mission_node",
            mission_id=mission_id,
            node_type="N6_EXECUTABLE_READINESS",
        )
        if node.get("state") != "RUNNING":
            raise N5DataDiscoveryAssignmentError(
                "RC72_N5_DISCOVERY_ASSIGNMENT_N5_RUNNING_REQUIRED"
            )
        if next_node.get("state") != "NOT_STARTED":
            raise N5DataDiscoveryAssignmentError(
                "RC72_N5_DISCOVERY_ASSIGNMENT_N6_ALREADY_RELEASED"
            )

        dispatches = [
            row
            for row in self.truth.query(
                "rc72_n5_data_discovery_dispatch", release_batch_id=release_batch_id
            )
            if row.get("source_commit") == self.source_commit
            and row.get("stage") == _STAGE
            and row.get("team_role") == _TEAM_ROLE
            and row.get("execution_substrate") == _SUBSTRATE
            and row.get("worker_policy") == _WORKER_POLICY
            and row.get("status") == "READY_FOR_ASSIGNMENT"
        ]
        if not dispatches:
            plans = self.truth.query(
                "rc72_n5_data_resolution_plan", release_batch_id=release_batch_id
            )
            expected_ids = set(str(item) for item in snapshot.get("data_requirement_ids") or [])
            if not plans or {
                str(row.get("data_requirement_id")) for row in plans
            } != expected_ids or any(row.get("status") != "REUSE_VERIFIED" for row in plans):
                raise N5DataDiscoveryAssignmentError(
                    "RC72_N5_DISCOVERY_ASSIGNMENT_DISPATCH_SET_REQUIRED"
                )
            return release_id, mission_id, node, []

        identities = [str(row.get("data_requirement_id")) for row in dispatches]
        if len(identities) != len(set(identities)):
            raise N5DataDiscoveryAssignmentError(
                "RC72_N5_DISCOVERY_ASSIGNMENT_REQUIREMENT_DUPLICATE"
            )
        plans: List[Dict[str, Any]] = []
        seen_workers = set()
        for dispatch in sorted(
            dispatches, key=lambda row: str(row.get("data_requirement_id"))
        ):
            workitem_id = _required(dispatch.get("workitem_id"), "workitem_id")
            dispatch_id = _required(dispatch.get("dispatch_id"), "dispatch_id")
            task = self._one("rc7_task", task_id=workitem_id)
            if (
                task.get("mission_id") != mission_id
                or task.get("node") != _STAGE
                or task.get("task_type") != _TASK_TYPE
            ):
                raise N5DataDiscoveryAssignmentError(
                    "RC72_N5_DISCOVERY_ASSIGNMENT_WORKITEM_LINEAGE_MISMATCH:%s"
                    % workitem_id
                )
            if list(task.get("input_artifact_refs") or []) != list(
                dispatch.get("parent_artifact_refs") or []
            ):
                raise N5DataDiscoveryAssignmentError(
                    "RC72_N5_DISCOVERY_ASSIGNMENT_PARENT_ARTIFACT_DRIFT:%s"
                    % workitem_id
                )
            if set(task.get("dependency_task_ids") or []) != set(
                dispatch.get("dependency_workitem_refs") or []
            ):
                raise N5DataDiscoveryAssignmentError(
                    "RC72_N5_DISCOVERY_ASSIGNMENT_DEPENDENCY_DRIFT:%s" % workitem_id
                )
            caps = list(dispatch.get("required_capabilities") or [])
            if not caps or list(task.get("required_capabilities") or []) != caps:
                raise N5DataDiscoveryAssignmentError(
                    "RC72_N5_DISCOVERY_ASSIGNMENT_CAPABILITY_DRIFT:%s" % workitem_id
                )
            assignment_id = self._assignment_id(dispatch_id, workitem_id)
            worker_id = self._worker_instance_id(assignment_id)
            if worker_id in seen_workers:
                raise N5DataDiscoveryAssignmentError(
                    "RC72_N5_DISCOVERY_ASSIGNMENT_WORKER_COLLISION"
                )
            seen_workers.add(worker_id)
            expected = {
                "assignment_id": assignment_id,
                "dispatch_id": dispatch_id,
                "release_id": release_id,
                "mission_id": mission_id,
                "release_batch_id": release_batch_id,
                "source_commit": self.source_commit,
                "mission_node_id": str(node["mission_node_id"]),
                "data_requirement_id": str(dispatch["data_requirement_id"]),
                "resolution_plan_id": str(dispatch["resolution_plan_id"]),
                "source_case_sha256": str(dispatch["source_case_sha256"]),
                "requirement_id": str(dispatch["requirement_id"]),
                "sst_id": str(dispatch["sst_id"]),
                "obligation_id": str(dispatch["obligation_id"]),
                "case_id": str(dispatch["case_id"]),
                "workitem_id": workitem_id,
                "stage": _STAGE,
                "team_role": _TEAM_ROLE,
                "agent_id": _AGENT_ID,
                "execution_substrate": _SUBSTRATE,
                "worker_policy": _WORKER_POLICY,
                "worker_instance_id": worker_id,
                "assignment_generation": _GENERATION,
                "required_capabilities": caps,
                "input_refs": self._input_refs(dispatch),
                "task_state": "LEASED",
                "status": _STATUS,
            }
            existing = self.truth.query(_ARTIFACT, assignment_id=assignment_id)
            if len(existing) > 1:
                raise N5DataDiscoveryAssignmentError(
                    "RC72_N5_DISCOVERY_ASSIGNMENT_NOT_UNIQUE:%s" % assignment_id
                )
            state = str(task.get("state") or "UNKNOWN")
            owner = task.get("lease_owner")
            if existing:
                if self._signature(existing[0]) != self._signature(expected):
                    raise N5DataDiscoveryAssignmentError(
                        "RC72_N5_DISCOVERY_ASSIGNMENT_IDENTITY_CONFLICT:%s"
                        % assignment_id
                    )
                if owner != worker_id:
                    raise N5DataDiscoveryAssignmentError(
                        "RC72_N5_DISCOVERY_ASSIGNMENT_RECEIPT_LEASE_MISMATCH:%s"
                        % workitem_id
                    )
                mode = "RESUMED"
            elif state == "LEASED":
                if owner != worker_id:
                    raise N5DataDiscoveryAssignmentError(
                        "RC72_N5_DISCOVERY_ASSIGNMENT_COMPETING_LEASE_OWNER:%s"
                        % workitem_id
                    )
                mode = "RECOVERED"
            elif state == "READY":
                if owner not in {None, ""}:
                    raise N5DataDiscoveryAssignmentError(
                        "RC72_N5_DISCOVERY_ASSIGNMENT_READY_HAS_LEASE_OWNER:%s"
                        % workitem_id
                    )
                mode = "NEW"
            else:
                raise N5DataDiscoveryAssignmentError(
                    "RC72_N5_DISCOVERY_ASSIGNMENT_TASK_STATE_INVALID:%s:%s"
                    % (workitem_id, state)
                )
            plans.append({"expected": expected, "mode": mode})
        return release_id, mission_id, node, plans

    def _persist(self, expected: Mapping[str, Any], *, recovered: bool) -> None:
        now = _now()
        payload = dict(expected)
        payload.update(
            {
                "recovered_orphan_lease": recovered,
                "created_at": now,
                "updated_at": now,
                "artifact_version": 1,
            }
        )
        self.truth.append_atomic(_EVENT, payload)
        if len(
            self.truth.query(_ARTIFACT, assignment_id=str(expected["assignment_id"]))
        ) != 1:
            raise N5DataDiscoveryAssignmentError(
                "RC72_N5_DISCOVERY_ASSIGNMENT_PERSISTENCE_FAILED"
            )

    def assign_all(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        release_id, mission_id, node, plans = self._preflight(release_batch_id)
        if not plans:
            return {
                "status": "NO_ASSIGNMENT_REQUIRED",
                "release_batch_id": release_batch_id,
                "mission_id": mission_id,
                "mission_node_id": str(node["mission_node_id"]),
                "node_state": "RUNNING",
                "assignments": [],
                "execution_substrate": _SUBSTRATE,
                "worker_policy": _WORKER_POLICY,
                "n6_state": "NOT_STARTED",
            }

        control = ClosedLoopControlPlane(self.truth, release_id, mission_id)
        target_ids = {str(plan["expected"]["workitem_id"]) for plan in plans}
        new_ids = {
            str(plan["expected"]["workitem_id"])
            for plan in plans
            if plan["mode"] == "NEW"
        }
        ready_tasks = list(control.scheduler.ready_tasks(mission_id))
        foreign_ready = [task.task_id for task in ready_tasks if task.task_id not in target_ids]
        if foreign_ready:
            raise N5DataDiscoveryAssignmentError(
                "RC72_N5_DISCOVERY_ASSIGNMENT_FOREIGN_READY_CONFLICT:%s"
                % ",".join(sorted(foreign_ready))
            )
        ready_ids = [task.task_id for task in ready_tasks]
        if set(ready_ids) != new_ids:
            raise N5DataDiscoveryAssignmentError(
                "RC72_N5_DISCOVERY_ASSIGNMENT_READY_SET_MISMATCH"
            )

        by_workitem = {
            str(plan["expected"]["workitem_id"]): plan for plan in plans
        }
        results: List[Dict[str, Any]] = []
        any_new = False
        any_recovered = False
        for plan in plans:
            expected = plan["expected"]
            mode = str(plan["mode"])
            if mode == "RESUMED":
                current = self._one("rc7_task", task_id=str(expected["workitem_id"]))
                results.append(
                    {
                        "status": "RESUMED",
                        "assignment_id": expected["assignment_id"],
                        "dispatch_id": expected["dispatch_id"],
                        "data_requirement_id": expected["data_requirement_id"],
                        "workitem_id": expected["workitem_id"],
                        "worker_instance_id": expected["worker_instance_id"],
                        "workitem_state": str(current["state"]),
                    }
                )
            elif mode == "RECOVERED":
                self._persist(expected, recovered=True)
                any_recovered = True
                results.append(
                    {
                        "status": "RECOVERED",
                        "assignment_id": expected["assignment_id"],
                        "dispatch_id": expected["dispatch_id"],
                        "data_requirement_id": expected["data_requirement_id"],
                        "workitem_id": expected["workitem_id"],
                        "worker_instance_id": expected["worker_instance_id"],
                        "workitem_state": "LEASED",
                    }
                )

        for workitem_id in ready_ids:
            plan = by_workitem[workitem_id]
            expected = plan["expected"]
            leased = control.lease_next(
                worker_ref=str(expected["worker_instance_id"]),
                capabilities=list(expected["required_capabilities"]),
            )
            if leased is None or leased.task_id != workitem_id:
                observed = "NONE" if leased is None else leased.task_id
                raise N5DataDiscoveryAssignmentError(
                    "RC72_N5_DISCOVERY_ASSIGNMENT_LEASE_IDENTITY_MISMATCH:expected=%s:observed=%s"
                    % (workitem_id, observed)
                )
            self._persist(expected, recovered=False)
            any_new = True
            results.append(
                {
                    "status": "ASSIGNED",
                    "assignment_id": expected["assignment_id"],
                    "dispatch_id": expected["dispatch_id"],
                    "data_requirement_id": expected["data_requirement_id"],
                    "workitem_id": expected["workitem_id"],
                    "worker_instance_id": expected["worker_instance_id"],
                    "workitem_state": "LEASED",
                }
            )
        results.sort(key=lambda row: str(row["data_requirement_id"]))
        status = "ASSIGNED" if any_new else "RECOVERED" if any_recovered else "RESUMED"
        n6 = self._one(
            "rc72_mission_node",
            mission_id=mission_id,
            node_type="N6_EXECUTABLE_READINESS",
        )
        if n6.get("state") != "NOT_STARTED":
            raise N5DataDiscoveryAssignmentError(
                "RC72_N5_DISCOVERY_ASSIGNMENT_RELEASED_N6"
            )
        return {
            "status": status,
            "release_batch_id": release_batch_id,
            "mission_id": mission_id,
            "mission_node_id": str(node["mission_node_id"]),
            "node_state": "RUNNING",
            "assignments": results,
            "execution_substrate": _SUBSTRATE,
            "worker_policy": _WORKER_POLICY,
            "n6_state": "NOT_STARTED",
        }


install_rc72_n5_data_discovery_assignment_overlay()

__all__ = [
    "N5DataDiscoveryAssignmentError",
    "N5DataDiscoveryAssignmentService",
    "install_rc72_n5_data_discovery_assignment_overlay",
    "validate_rc72_n5_data_discovery_assignment",
]
