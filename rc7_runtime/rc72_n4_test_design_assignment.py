"""RC7.2 N4 Requirement x SST WorkItem -> fresh AgentTeams assignment bridge.

N4 dispatch creates one durable TEST_DESIGN WorkItem per Requirement x SST.
This layer gives each WorkItem one deterministic assignment-scoped fresh worker
identity and delegates the actual lease transition to the existing RC7
TaskScheduler.  It deliberately stops before DSH launch: no session, Attempt,
TestObligation, TestCase, output, Delivery, Gate or PASS claim is created here.
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
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_n4_test_design_dispatch import install_rc72_n4_test_design_dispatch_overlay
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n4_test_design_assignment"
_EVENT = "RC72_N4_TEST_DESIGN_ASSIGNMENT_UPSERTED"
_BUCKET = "rc72_n4_test_design_assignments"
_NODE_TYPE = AutonomousMissionNode.N4_TEST_DESIGN.value
_STAGE = "TEST_DESIGN"
_TASK_TYPE = "RC72_NODE_WORK"
_TEAM_ROLE = "TEST_DESIGN_WORKER"
_AGENT_ID = "test-design"
_SUBSTRATE = "DSH_AGENT_TEAMS"
_WORKER_POLICY = "FRESH_SESSION_REQUIRED"
_STATUS = "LEASED_FOR_HANDOFF"
_GENERATION = 1


class N4TestDesignAssignmentError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N4TestDesignAssignmentError(
            "RC72_N4_ASSIGNMENT_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _string_list(value: Any, name: str, *, allow_empty: bool = True) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError(
            "RC72_N4_ASSIGNMENT_%s_INVALID" % name.upper()
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError(
            "RC72_N4_ASSIGNMENT_%s_INVALID" % name.upper()
        )
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError(
            "RC72_N4_ASSIGNMENT_%s_DUPLICATE" % name.upper()
        )
    if not allow_empty and not value:
        raise _contracts.DomainValidationError(
            "RC72_N4_ASSIGNMENT_%s_REQUIRED" % name.upper()
        )
    return list(value)


def validate_rc72_n4_test_design_assignment(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "assignment_id", "dispatch_id", "release_id", "mission_id",
        "release_batch_id", "source_commit", "mission_node_id", "node_type",
        "stage", "requirement_id", "sst_id", "workitem_id", "team_role",
        "agent_id", "execution_substrate", "worker_policy",
        "worker_instance_id", "task_state", "status",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["node_type"] != _NODE_TYPE:
        raise _contracts.DomainValidationError("RC72_N4_ASSIGNMENT_NODE_INVALID")
    if out["stage"] != _STAGE:
        raise _contracts.DomainValidationError("RC72_N4_ASSIGNMENT_STAGE_INVALID")
    if out["team_role"] != _TEAM_ROLE:
        raise _contracts.DomainValidationError("RC72_N4_ASSIGNMENT_TEAM_ROLE_INVALID")
    if out["agent_id"] != _AGENT_ID:
        raise _contracts.DomainValidationError("RC72_N4_ASSIGNMENT_AGENT_ID_INVALID")
    if out["execution_substrate"] != _SUBSTRATE:
        raise _contracts.DomainValidationError("RC72_N4_ASSIGNMENT_SUBSTRATE_INVALID")
    if out["worker_policy"] != _WORKER_POLICY:
        raise _contracts.DomainValidationError("RC72_N4_ASSIGNMENT_WORKER_POLICY_INVALID")
    if out["task_state"] != "LEASED":
        raise _contracts.DomainValidationError("RC72_N4_ASSIGNMENT_TASK_STATE_INVALID")
    if out["status"] != _STATUS:
        raise _contracts.DomainValidationError("RC72_N4_ASSIGNMENT_STATUS_INVALID")
    generation = out.get("assignment_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation != _GENERATION:
        raise _contracts.DomainValidationError("RC72_N4_ASSIGNMENT_GENERATION_INVALID")
    out["assignment_generation"] = generation
    out["required_capabilities"] = _string_list(
        out.get("required_capabilities"), "required_capabilities", allow_empty=False
    )
    out["input_refs"] = _string_list(
        out.get("input_refs"), "input_refs", allow_empty=False
    )
    recovered = out.get("recovered_orphan_lease", False)
    if not isinstance(recovered, bool):
        raise _contracts.DomainValidationError("RC72_N4_ASSIGNMENT_RECOVERY_FLAG_INVALID")
    out["recovered_orphan_lease"] = recovered
    for forbidden in (
        "session_id", "dsh_session_id", "attempt_id", "execution_attempt_id",
        "execution_result", "output_refs", "evidence_refs", "test_cases",
        "obligations", "delivery_id", "node_gate", "node_pass", "n4_pass",
        "n5_ready", "q7_pass", "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N4_ASSIGNMENT_EXECUTION_CLAIM_FORBIDDEN:%s" % forbidden
            )
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N4_ASSIGNMENT_%s_INVALID" % name.upper()
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_N4_ASSIGNMENT_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n4_test_design_assignment_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_n4_test_design_dispatch_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n4_test_design_assignment
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


class N4TestDesignAssignmentService:
    """Lease every governed N4 Requirement x SST WorkItem to a distinct worker."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_n4_test_design_assignment_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")

    @staticmethod
    def _assignment_id(dispatch_id: str, workitem_id: str) -> str:
        raw = "\x1f".join((dispatch_id, workitem_id, "GEN%d" % _GENERATION))
        return "N4ASN-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _worker_instance_id(assignment_id: str) -> str:
        raw = "\x1f".join((assignment_id, "FRESH_TEST_DESIGN_WORKER"))
        return "RC72N4FW-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _input_refs(dispatch: Mapping[str, Any]) -> List[str]:
        refs = [
            "requirement://%s" % str(dispatch["requirement_id"]),
            "sst://%s" % str(dispatch["sst_id"]),
            "n4-parent-snapshot://%s" % str(dispatch["parent_snapshot_id"]),
        ]
        refs.extend(
            "artifact://%s" % str(item)
            for item in list(dispatch.get("parent_artifact_refs") or [])
        )
        refs.extend(
            "obligation-source://%s" % str(item)
            for item in list(dispatch.get("parent_obligation_source_refs") or [])
        )
        refs.extend((
            "node-delivery://%s" % str(dispatch["source_n2_delivery_id"]),
            "node-gate://%s" % str(dispatch["source_n2_gate_id"]),
            "node-delivery://%s" % str(dispatch["source_n3_delivery_id"]),
            "node-gate://%s" % str(dispatch["source_n3_gate_id"]),
        ))
        return refs

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        keys = (
            "dispatch_id", "release_id", "mission_id", "release_batch_id",
            "source_commit", "mission_node_id", "node_type", "stage",
            "requirement_id", "sst_id", "workitem_id", "team_role", "agent_id",
            "execution_substrate", "worker_policy", "worker_instance_id",
            "assignment_generation", "task_state", "status",
        )
        out = {key: payload.get(key) for key in keys}
        out["required_capabilities"] = list(payload.get("required_capabilities") or [])
        out["input_refs"] = list(payload.get("input_refs") or [])
        return out

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N4TestDesignAssignmentError(
                "RC72_N4_ASSIGNMENT_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _preflight(self, release_batch_id: str) -> Tuple[
        str, str, Dict[str, Any], List[Dict[str, Any]]
    ]:
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        mission_id = _required(batch.get("mission_id"), "mission_id")
        release_id = _required(batch.get("release_id"), "release_id")
        node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NODE_TYPE
        )
        if (
            node.get("scope_ref") != "release-batch://%s" % release_batch_id
            or node.get("state") != MissionNodeState.RUNNING.value
        ):
            raise N4TestDesignAssignmentError("RC72_N4_ASSIGNMENT_N4_NOT_RUNNING")
        next_node = self._one(
            "rc72_mission_node",
            mission_id=mission_id,
            node_type=AutonomousMissionNode.N5_TEST_DATA.value,
        )
        if next_node.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N4TestDesignAssignmentError("RC72_N4_ASSIGNMENT_N5_ALREADY_RELEASED")
        mission = self._one("rc7_mission", mission_id=mission_id)
        if mission.get("release_id") != release_id:
            raise N4TestDesignAssignmentError("RC72_N4_ASSIGNMENT_RC7_MISSION_LINEAGE_INVALID")

        dispatches = [
            row for row in self.truth.query(
                "rc72_n4_test_design_dispatch", release_batch_id=release_batch_id
            )
            if row.get("source_commit") == self.source_commit
            and row.get("node_type") == _NODE_TYPE
            and row.get("stage") == _STAGE
            and row.get("execution_substrate") == _SUBSTRATE
            and row.get("worker_policy") == _WORKER_POLICY
            and row.get("status") == "READY_FOR_ASSIGNMENT"
        ]
        if not dispatches:
            raise N4TestDesignAssignmentError("RC72_N4_ASSIGNMENT_DISPATCH_SET_REQUIRED")
        identities = [
            (str(row.get("requirement_id")), str(row.get("sst_id")))
            for row in dispatches
        ]
        if len(identities) != len(set(identities)):
            raise N4TestDesignAssignmentError("RC72_N4_ASSIGNMENT_SCOPE_DUPLICATE")

        plans: List[Dict[str, Any]] = []
        seen_workers = set()
        for dispatch in sorted(
            dispatches,
            key=lambda row: (str(row.get("requirement_id")), str(row.get("sst_id"))),
        ):
            workitem_id = _required(dispatch.get("workitem_id"), "workitem_id")
            dispatch_id = _required(dispatch.get("dispatch_id"), "dispatch_id")
            task = self._one("rc7_task", task_id=workitem_id)
            if (
                task.get("mission_id") != mission_id
                or task.get("node") != _STAGE
                or task.get("task_type") != _TASK_TYPE
            ):
                raise N4TestDesignAssignmentError(
                    "RC72_N4_ASSIGNMENT_WORKITEM_LINEAGE_MISMATCH:%s" % workitem_id
                )
            if set(task.get("input_artifact_refs") or []) != set(dispatch.get("parent_artifact_refs") or []):
                raise N4TestDesignAssignmentError(
                    "RC72_N4_ASSIGNMENT_PARENT_ARTIFACT_DRIFT:%s" % workitem_id
                )
            if set(task.get("dependency_task_ids") or []) != set(dispatch.get("dependency_workitem_refs") or []):
                raise N4TestDesignAssignmentError(
                    "RC72_N4_ASSIGNMENT_DEPENDENCY_DRIFT:%s" % workitem_id
                )
            caps = list(dispatch.get("required_capabilities") or [])
            if not caps or list(task.get("required_capabilities") or []) != caps:
                raise N4TestDesignAssignmentError(
                    "RC72_N4_ASSIGNMENT_CAPABILITY_DRIFT:%s" % workitem_id
                )
            assignment_id = self._assignment_id(dispatch_id, workitem_id)
            worker_id = self._worker_instance_id(assignment_id)
            if worker_id in seen_workers:
                raise N4TestDesignAssignmentError("RC72_N4_ASSIGNMENT_WORKER_ID_COLLISION")
            seen_workers.add(worker_id)
            expected = {
                "assignment_id": assignment_id,
                "dispatch_id": dispatch_id,
                "release_id": release_id,
                "mission_id": mission_id,
                "release_batch_id": release_batch_id,
                "source_commit": self.source_commit,
                "mission_node_id": str(node["mission_node_id"]),
                "node_type": _NODE_TYPE,
                "stage": _STAGE,
                "requirement_id": str(dispatch["requirement_id"]),
                "sst_id": str(dispatch["sst_id"]),
                "workitem_id": workitem_id,
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
                raise N4TestDesignAssignmentError(
                    "RC72_N4_ASSIGNMENT_NOT_UNIQUE:%s" % assignment_id
                )
            state = str(task.get("state") or "UNKNOWN")
            lease_owner = task.get("lease_owner")
            mode = "NEW"
            if existing:
                if self._signature(existing[0]) != self._signature(expected):
                    raise N4TestDesignAssignmentError(
                        "RC72_N4_ASSIGNMENT_IDENTITY_CONFLICT:%s" % assignment_id
                    )
                if lease_owner != worker_id:
                    raise N4TestDesignAssignmentError(
                        "RC72_N4_ASSIGNMENT_RECEIPT_LEASE_MISMATCH:%s" % workitem_id
                    )
                if state not in {
                    "LEASED", "RUNNING", "OUTPUT_PRODUCED", "EVALUATING",
                    "PASS", "REPAIR_REQUIRED", "BLOCKED", "HUMAN_REQUIRED",
                    "FAILED", "STALE",
                }:
                    raise N4TestDesignAssignmentError(
                        "RC72_N4_ASSIGNMENT_RECEIPT_TASK_STATE_INVALID:%s:%s"
                        % (workitem_id, state)
                    )
                mode = "RESUMED"
            elif state == "LEASED":
                if lease_owner != worker_id:
                    raise N4TestDesignAssignmentError(
                        "RC72_N4_ASSIGNMENT_COMPETING_LEASE_OWNER:%s" % workitem_id
                    )
                mode = "RECOVERED"
            elif state == "READY":
                if lease_owner not in {None, ""}:
                    raise N4TestDesignAssignmentError(
                        "RC72_N4_ASSIGNMENT_READY_TASK_HAS_LEASE_OWNER:%s" % workitem_id
                    )
                mode = "NEW"
            else:
                raise N4TestDesignAssignmentError(
                    "RC72_N4_ASSIGNMENT_TASK_STATE_INVALID:%s:%s"
                    % (workitem_id, state)
                )
            plans.append({"dispatch": dispatch, "task": task, "expected": expected, "mode": mode})
        return release_id, mission_id, node, plans

    def _persist_receipt(self, expected: Mapping[str, Any], *, recovered: bool) -> None:
        now = _now()
        payload = dict(expected)
        payload.update({
            "recovered_orphan_lease": recovered,
            "created_at": now,
            "updated_at": now,
            "artifact_version": 1,
        })
        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, assignment_id=str(expected["assignment_id"]))
        if len(rows) != 1:
            raise N4TestDesignAssignmentError(
                "RC72_N4_ASSIGNMENT_PERSISTENCE_FAILED:%s" % str(expected["assignment_id"])
            )

    def assign_all(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        release_id, mission_id, node, plans = self._preflight(release_batch_id)
        control = ClosedLoopControlPlane(self.truth, release_id, mission_id)
        target_ids = {str(plan["expected"]["workitem_id"]) for plan in plans}
        new_ids = {
            str(plan["expected"]["workitem_id"])
            for plan in plans if plan["mode"] == "NEW"
        }

        ready_tasks = list(control.scheduler.ready_tasks(mission_id))
        foreign_ready = [task.task_id for task in ready_tasks if task.task_id not in target_ids]
        if foreign_ready:
            raise N4TestDesignAssignmentError(
                "RC72_N4_ASSIGNMENT_FOREIGN_READY_TASK_CONFLICT:%s"
                % ",".join(sorted(foreign_ready))
            )
        ready_ids = [task.task_id for task in ready_tasks]
        if set(ready_ids) != new_ids:
            missing = sorted(new_ids.difference(ready_ids))
            unexpected = sorted(set(ready_ids).difference(new_ids))
            raise N4TestDesignAssignmentError(
                "RC72_N4_ASSIGNMENT_READY_SET_MISMATCH:missing=%s:unexpected=%s"
                % (",".join(missing), ",".join(unexpected))
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
                results.append({
                    "status": "RESUMED",
                    "assignment_id": expected["assignment_id"],
                    "dispatch_id": expected["dispatch_id"],
                    "requirement_id": expected["requirement_id"],
                    "sst_id": expected["sst_id"],
                    "workitem_id": expected["workitem_id"],
                    "worker_instance_id": expected["worker_instance_id"],
                    "workitem_state": str(current["state"]),
                })
            elif mode == "RECOVERED":
                self._persist_receipt(expected, recovered=True)
                any_recovered = True
                results.append({
                    "status": "RECOVERED",
                    "assignment_id": expected["assignment_id"],
                    "dispatch_id": expected["dispatch_id"],
                    "requirement_id": expected["requirement_id"],
                    "sst_id": expected["sst_id"],
                    "workitem_id": expected["workitem_id"],
                    "worker_instance_id": expected["worker_instance_id"],
                    "workitem_state": "LEASED",
                })

        for workitem_id in ready_ids:
            plan = by_workitem[workitem_id]
            expected = plan["expected"]
            leased = control.lease_next(
                worker_ref=str(expected["worker_instance_id"]),
                capabilities=list(expected["required_capabilities"]),
            )
            if leased is None or leased.task_id != workitem_id:
                observed = "NONE" if leased is None else leased.task_id
                raise N4TestDesignAssignmentError(
                    "RC72_N4_ASSIGNMENT_LEASE_IDENTITY_MISMATCH:expected=%s:observed=%s"
                    % (workitem_id, observed)
                )
            self._persist_receipt(expected, recovered=False)
            any_new = True
            results.append({
                "status": "ASSIGNED",
                "assignment_id": expected["assignment_id"],
                "dispatch_id": expected["dispatch_id"],
                "requirement_id": expected["requirement_id"],
                "sst_id": expected["sst_id"],
                "workitem_id": expected["workitem_id"],
                "worker_instance_id": expected["worker_instance_id"],
                "workitem_state": "LEASED",
            })

        results.sort(key=lambda item: (str(item["requirement_id"]), str(item["sst_id"])))
        if any_new:
            overall = "ASSIGNED"
        elif any_recovered:
            overall = "RECOVERED"
        else:
            overall = "RESUMED"
        return {
            "status": overall,
            "release_batch_id": release_batch_id,
            "mission_id": mission_id,
            "mission_node_id": str(node["mission_node_id"]),
            "node_state": str(node["state"]),
            "assignments": results,
            "execution_substrate": _SUBSTRATE,
            "worker_policy": _WORKER_POLICY,
        }


install_rc72_n4_test_design_assignment_overlay()

__all__ = [
    "N4TestDesignAssignmentError",
    "N4TestDesignAssignmentService",
    "install_rc72_n4_test_design_assignment_overlay",
    "validate_rc72_n4_test_design_assignment",
]
