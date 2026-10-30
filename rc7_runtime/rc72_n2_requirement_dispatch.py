"""RC7.2 N2 Requirement Analysis dispatch bridge.

N2 is not one batch-sized prompt. This bridge fans a governed N1 PASS into
one durable RC7 WorkItem per canonical Requirement. It consumes only the
active N1 Delivery, the PASS Gate for that Delivery, canonical VALID RC7
artifacts, and source-commit-aligned N1 dispatch lineage.

It does not launch a worker, create a DSH session/Attempt, fabricate requirement
artifacts, or make a NodeGate decision. N2 becomes RUNNING only after all
requirement WorkItems are durably scheduler-ready.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Mapping, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError, Task
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_n1_completion import install_rc72_n1_completion_overlay
from .rc72_state_machine import RC72StateMachine
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n2_requirement_dispatch"
_EVENT = "RC72_N2_REQUIREMENT_DISPATCH_UPSERTED"
_BUCKET = "rc72_n2_requirement_dispatches"

_NODE = AutonomousMissionNode.N2_REQUIREMENT
_SOURCE_NODE = AutonomousMissionNode.N1_REALITY
_STAGE = "REQUIREMENT_ANALYSIS"
_TASK_TYPE = "RC72_NODE_WORK"
_TEAM_ROLE = "REQUIREMENT_ANALYSIS_WORKER"
_SUBSTRATE = "DSH_AGENT_TEAMS"
_WORKER_POLICY = "FRESH_SESSION_REQUIRED"
_STATUS = "READY_FOR_ASSIGNMENT"
_CAPABILITIES = ("requirement_reasoning",)


class N2RequirementDispatchError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N2RequirementDispatchError("RC72_N2_DISPATCH_%s_REQUIRED" % name.upper())
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _string_list(value: Any, name: str, *, allow_empty: bool = True) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError("RC72_N2_DISPATCH_%s_INVALID" % name.upper())
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("RC72_N2_DISPATCH_%s_INVALID" % name.upper())
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError("RC72_N2_DISPATCH_%s_DUPLICATE" % name.upper())
    if not allow_empty and not value:
        raise _contracts.DomainValidationError("RC72_N2_DISPATCH_%s_REQUIRED" % name.upper())
    return list(value)


def validate_rc72_n2_requirement_dispatch(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "dispatch_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "mission_node_id", "node_type", "stage",
        "requirement_id", "workitem_id", "team_role", "execution_substrate",
        "worker_policy", "source_n1_node_id", "source_n1_delivery_id",
        "source_n1_gate_id", "status",
    ):
        out[name] = _contracts._require_str(out, name)

    if out["node_type"] != _NODE.value:
        raise _contracts.DomainValidationError("RC72_N2_DISPATCH_NODE_INVALID")
    if out["stage"] != _STAGE:
        raise _contracts.DomainValidationError("RC72_N2_DISPATCH_STAGE_INVALID")
    if out["team_role"] != _TEAM_ROLE:
        raise _contracts.DomainValidationError("RC72_N2_DISPATCH_TEAM_ROLE_INVALID")
    if out["execution_substrate"] != _SUBSTRATE:
        raise _contracts.DomainValidationError("RC72_N2_DISPATCH_SUBSTRATE_INVALID")
    if out["worker_policy"] != _WORKER_POLICY:
        raise _contracts.DomainValidationError("RC72_N2_DISPATCH_WORKER_POLICY_INVALID")
    if out["status"] != _STATUS:
        raise _contracts.DomainValidationError("RC72_N2_DISPATCH_STATUS_INVALID")

    for name in (
        "source_n1_workitem_refs", "source_n1_artifact_refs",
        "source_n1_evidence_refs", "required_capabilities",
    ):
        out[name] = _string_list(out.get(name), name, allow_empty=False)

    for forbidden in (
        "worker_id", "worker_instance_id", "session_id", "dsh_session_id",
        "attempt_id", "execution_attempt_id", "execution_result", "output_refs",
        "delivery_id", "node_gate", "node_pass", "q7_pass", "field_verified",
        "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N2_DISPATCH_EXECUTION_CLAIM_FORBIDDEN:%s" % forbidden
            )

    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N2_DISPATCH_%s_INVALID" % name.upper()
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_N2_DISPATCH_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n2_requirement_dispatch_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_n1_completion_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n2_requirement_dispatch
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "dispatch_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "dispatch_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class N2RequirementDispatchService:
    """Fan out active canonical N1 PASS into one N2 WorkItem per Requirement."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_n2_requirement_dispatch_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N2RequirementDispatchError(
                "RC72_N2_DISPATCH_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _active_n1_pass(
        self, mission_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        n1 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_SOURCE_NODE.value
        )
        if n1.get("state") != MissionNodeState.PASS.value:
            raise N2RequirementDispatchError("RC72_N2_DISPATCH_N1_NOT_PASS")
        active_version = n1.get("active_delivery_version")
        if isinstance(active_version, bool) or not isinstance(active_version, int):
            raise N2RequirementDispatchError(
                "RC72_N2_DISPATCH_N1_ACTIVE_DELIVERY_REQUIRED"
            )
        deliveries = [
            row for row in self.truth.query(
                "rc72_node_delivery", mission_node_id=str(n1["mission_node_id"])
            )
            if row.get("version") == active_version
            and row.get("delivery_id") in list(n1.get("delivery_refs") or [])
        ]
        if len(deliveries) != 1:
            raise N2RequirementDispatchError(
                "RC72_N2_DISPATCH_N1_ACTIVE_DELIVERY_NOT_UNIQUE:%d" % len(deliveries)
            )
        delivery = deliveries[0]
        gates = [
            row for row in self.truth.query(
                "rc72_node_gate", mission_node_id=str(n1["mission_node_id"])
            )
            if row.get("gate_id") in list(n1.get("gate_refs") or [])
            and row.get("delivery_id") == delivery.get("delivery_id")
            and row.get("decision") == "PASS"
        ]
        if len(gates) != 1:
            raise N2RequirementDispatchError(
                "RC72_N2_DISPATCH_N1_PASS_GATE_NOT_UNIQUE:%d" % len(gates)
            )
        return n1, delivery, gates[0]

    def _validate_source_lineage(
        self, *, mission_id: str, delivery: Mapping[str, Any]
    ) -> Tuple[List[str], List[str], List[str]]:
        workitem_refs = list(delivery.get("created_by_workitems") or [])
        artifact_refs = list(delivery.get("artifact_refs") or [])
        evidence_refs = list(delivery.get("evidence_refs") or [])
        if not workitem_refs:
            raise N2RequirementDispatchError(
                "RC72_N2_DISPATCH_N1_WORKITEM_LINEAGE_REQUIRED"
            )
        if not artifact_refs:
            raise N2RequirementDispatchError(
                "RC72_N2_DISPATCH_N1_ARTIFACT_LINEAGE_REQUIRED"
            )
        if not evidence_refs:
            raise N2RequirementDispatchError(
                "RC72_N2_DISPATCH_N1_EVIDENCE_LINEAGE_REQUIRED"
            )

        source_tasks: Dict[str, Dict[str, Any]] = {}
        for workitem_id in workitem_refs:
            task = self._one("rc7_task", task_id=workitem_id)
            if task.get("mission_id") != mission_id or task.get("state") != "PASS":
                raise N2RequirementDispatchError(
                    "RC72_N2_DISPATCH_N1_WORKITEM_NOT_PASS:%s" % workitem_id
                )
            dispatch = self._one("rc72_mission_node_dispatch", workitem_id=workitem_id)
            if (
                dispatch.get("mission_id") != mission_id
                or dispatch.get("node_type") != _SOURCE_NODE.value
                or dispatch.get("source_commit") != self.source_commit
            ):
                raise N2RequirementDispatchError(
                    "RC72_N2_DISPATCH_N1_SOURCE_COMMIT_LINEAGE_MISMATCH"
                )
            source_tasks[workitem_id] = task

        for artifact_id in artifact_refs:
            artifact = self._one("rc7_artifact", artifact_id=artifact_id)
            producer = artifact.get("producer_task_id")
            if (
                artifact.get("mission_id") != mission_id
                or artifact.get("state") != "VALID"
                or producer not in source_tasks
            ):
                raise N2RequirementDispatchError(
                    "RC72_N2_DISPATCH_N1_ARTIFACT_INVALID:%s" % artifact_id
                )
        for evidence_id in evidence_refs:
            evidence = self._one("rc7_evidence", evidence_id=evidence_id)
            if evidence.get("mission_id") != mission_id:
                raise N2RequirementDispatchError(
                    "RC72_N2_DISPATCH_N1_EVIDENCE_INVALID:%s" % evidence_id
                )
        return workitem_refs, artifact_refs, evidence_refs

    @staticmethod
    def _workitem_id(mission_id: str, release_batch_id: str, requirement_id: str) -> str:
        return _stable_id("WI-N2-REQ", mission_id, release_batch_id, requirement_id)

    @staticmethod
    def _dispatch_id(
        mission_id: str,
        release_batch_id: str,
        requirement_id: str,
        source_gate_id: str,
        source_commit: str,
    ) -> str:
        return _stable_id(
            "N2DISP-REQ", mission_id, release_batch_id, requirement_id,
            source_gate_id, source_commit,
        )

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        keys = (
            "release_id", "mission_id", "release_batch_id", "source_commit",
            "mission_node_id", "node_type", "stage", "requirement_id",
            "workitem_id", "team_role", "execution_substrate", "worker_policy",
            "source_n1_node_id", "source_n1_delivery_id", "source_n1_gate_id",
            "status",
        )
        out = {key: payload.get(key) for key in keys}
        for key in (
            "source_n1_workitem_refs", "source_n1_artifact_refs",
            "source_n1_evidence_refs", "required_capabilities",
        ):
            out[key] = list(payload.get(key) or [])
        return out

    def _preflight(
        self, release_batch_id: str
    ) -> Tuple[
        Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
        List[str], List[str], List[str],
    ]:
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        mission_id = _required(batch.get("mission_id"), "mission_id")
        release_id = _required(batch.get("release_id"), "release_id")
        requirement_ids = list(batch.get("requirement_ids") or [])
        if (
            not requirement_ids
            or not all(isinstance(item, str) and item.strip() for item in requirement_ids)
            or len(set(requirement_ids)) != len(requirement_ids)
        ):
            raise N2RequirementDispatchError(
                "RC72_N2_DISPATCH_CANONICAL_REQUIREMENTS_REQUIRED"
            )

        mission = self._one("rc7_mission", mission_id=mission_id)
        if mission.get("release_id") != release_id:
            raise N2RequirementDispatchError(
                "RC72_N2_DISPATCH_RC7_MISSION_LINEAGE_MISMATCH"
            )
        n2 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NODE.value
        )
        if n2.get("scope_ref") != "release-batch://%s" % release_batch_id:
            raise N2RequirementDispatchError("RC72_N2_DISPATCH_N2_SCOPE_MISMATCH")
        if n2.get("state") not in {
            MissionNodeState.READY.value, MissionNodeState.RUNNING.value,
        }:
            raise N2RequirementDispatchError(
                "RC72_N2_DISPATCH_N2_STATE_INVALID:%s"
                % str(n2.get("state") or "UNKNOWN")
            )
        n3 = self._one(
            "rc72_mission_node",
            mission_id=mission_id,
            node_type=AutonomousMissionNode.N3_CODE_ANALYSIS.value,
        )
        if n3.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N2RequirementDispatchError("RC72_N2_DISPATCH_N3_ALREADY_RELEASED")

        n1, delivery, gate = self._active_n1_pass(mission_id)
        workitems, artifacts, evidence = self._validate_source_lineage(
            mission_id=mission_id, delivery=delivery
        )
        return batch, n2, n1, gate, workitems, artifacts, evidence

    def dispatch(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        (
            batch, n2, n1, gate, source_workitems, source_artifacts, source_evidence,
        ) = self._preflight(release_batch_id)
        release_id = str(batch["release_id"])
        mission_id = str(batch["mission_id"])
        requirement_ids = list(batch.get("requirement_ids") or [])
        source_delivery_id = str(gate["delivery_id"])
        source_gate_id = str(gate["gate_id"])
        node_id = str(n2["mission_node_id"])

        expected_rows: List[Dict[str, Any]] = []
        for requirement_id in requirement_ids:
            workitem_id = self._workitem_id(mission_id, release_batch_id, requirement_id)
            dispatch_id = self._dispatch_id(
                mission_id, release_batch_id, requirement_id,
                source_gate_id, self.source_commit,
            )
            expected_rows.append({
                "dispatch_id": dispatch_id,
                "release_id": release_id,
                "mission_id": mission_id,
                "release_batch_id": release_batch_id,
                "source_commit": self.source_commit,
                "mission_node_id": node_id,
                "node_type": _NODE.value,
                "stage": _STAGE,
                "requirement_id": requirement_id,
                "workitem_id": workitem_id,
                "team_role": _TEAM_ROLE,
                "execution_substrate": _SUBSTRATE,
                "worker_policy": _WORKER_POLICY,
                "source_n1_node_id": str(n1["mission_node_id"]),
                "source_n1_delivery_id": source_delivery_id,
                "source_n1_gate_id": source_gate_id,
                "source_n1_workitem_refs": list(source_workitems),
                "source_n1_artifact_refs": list(source_artifacts),
                "source_n1_evidence_refs": list(source_evidence),
                "required_capabilities": list(_CAPABILITIES),
                "status": _STATUS,
            })

        existing = self.truth.query(_ARTIFACT, release_batch_id=release_batch_id)
        if existing:
            if len(existing) != len(expected_rows):
                raise N2RequirementDispatchError(
                    "RC72_N2_DISPATCH_SET_CONFLICT:%d!=%d"
                    % (len(existing), len(expected_rows))
                )
            by_id = {str(row["dispatch_id"]): row for row in existing}
            for expected in expected_rows:
                current = by_id.get(str(expected["dispatch_id"]))
                if current is None or self._signature(current) != self._signature(expected):
                    raise N2RequirementDispatchError(
                        "RC72_N2_DISPATCH_SET_IDENTITY_CONFLICT"
                    )
                task = self._one("rc7_task", task_id=str(expected["workitem_id"]))
                if task.get("state") not in {
                    "READY", "LEASED", "RUNNING", "OUTPUT_PRODUCED",
                    "EVALUATING", "PASS", "REPAIR_REQUIRED",
                }:
                    raise N2RequirementDispatchError(
                        "RC72_N2_DISPATCH_RECEIPT_TASK_STATE_INVALID:%s"
                        % str(task.get("state") or "UNKNOWN")
                    )
            if n2.get("state") != MissionNodeState.RUNNING.value:
                raise N2RequirementDispatchError(
                    "RC72_N2_DISPATCH_RECEIPT_NODE_NOT_RUNNING"
                )
            return {
                "status": "RESUMED",
                "release_batch_id": release_batch_id,
                "mission_id": mission_id,
                "mission_node_id": node_id,
                "node_state": MissionNodeState.RUNNING.value,
                "source_n1_gate_id": source_gate_id,
                "source_n1_delivery_id": source_delivery_id,
                "dispatch_ids": [row["dispatch_id"] for row in expected_rows],
                "workitem_ids": [row["workitem_id"] for row in expected_rows],
                "requirement_ids": requirement_ids,
                "execution_substrate": _SUBSTRATE,
                "worker_policy": _WORKER_POLICY,
            }

        if n2.get("state") != MissionNodeState.READY.value:
            raise N2RequirementDispatchError(
                "RC72_N2_DISPATCH_RUNNING_WITHOUT_RECEIPTS"
            )

        control = ClosedLoopControlPlane(self.truth, release_id, mission_id)
        for expected in expected_rows:
            workitem_id = str(expected["workitem_id"])
            if self.truth.query("rc7_task", task_id=workitem_id):
                raise N2RequirementDispatchError(
                    "RC72_N2_DISPATCH_WORKITEM_EXISTS_WITHOUT_RECEIPT:%s" % workitem_id
                )
            control.register_task(Task(
                task_id=workitem_id,
                mission_id=mission_id,
                node=_STAGE,
                task_type=_TASK_TYPE,
                objective=(
                    "Analyze canonical requirement %s for ReleaseBatch %s into "
                    "evidence-backed BR/SR/TR, business/state/negative/boundary/"
                    "permission/data rule assets"
                    % (expected["requirement_id"], release_batch_id)
                ),
                required_capabilities=list(_CAPABILITIES),
                dependency_task_ids=list(source_workitems),
                input_artifact_refs=list(source_artifacts),
                acceptance_criteria=[
                    "requirement identity and source references are explicit",
                    "BR/SR/TR and business rules are evidence-backed",
                    "roles, states and state transitions are explicit",
                    "negative, boundary, permission and data rules are explicit or evidence-backed N/A",
                    "unresolved unknowns remain explicit and prevent PASS",
                ],
                priority=10,
            ))
            task = self._one("rc7_task", task_id=workitem_id)
            if task.get("state") != "READY":
                raise N2RequirementDispatchError(
                    "RC72_N2_DISPATCH_WORKITEM_NOT_READY:%s:%s"
                    % (workitem_id, str(task.get("state") or "UNKNOWN"))
                )

        RC72StateMachine(self.truth, release_id=release_id).transition_state(
            node_id,
            MissionNodeState.RUNNING,
            reason="canonical N2 requirement WorkItems materialized",
        )

        now = _now()
        for expected in expected_rows:
            payload = dict(expected)
            payload.update({"created_at": now, "updated_at": now, "artifact_version": 1})
            self.truth.append_atomic(_EVENT, payload)
        persisted = self.truth.query(_ARTIFACT, release_batch_id=release_batch_id)
        if len(persisted) != len(expected_rows):
            raise N2RequirementDispatchError("RC72_N2_DISPATCH_PERSISTENCE_FAILED")

        return {
            "status": "DISPATCHED",
            "release_batch_id": release_batch_id,
            "mission_id": mission_id,
            "mission_node_id": node_id,
            "node_state": MissionNodeState.RUNNING.value,
            "source_n1_gate_id": source_gate_id,
            "source_n1_delivery_id": source_delivery_id,
            "dispatch_ids": [row["dispatch_id"] for row in expected_rows],
            "workitem_ids": [row["workitem_id"] for row in expected_rows],
            "requirement_ids": requirement_ids,
            "execution_substrate": _SUBSTRATE,
            "worker_policy": _WORKER_POLICY,
            "team_role": _TEAM_ROLE,
        }


install_rc72_n2_requirement_dispatch_overlay()
