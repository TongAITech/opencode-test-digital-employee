"""RC7.2 N3 source-target discovery dispatch.

N3 must not guess repository names or source revisions from application ids.
This bridge therefore creates one governed SOURCE_TARGET_DISCOVERY WorkItem per
canonical ReleaseBatch application after N2 has a real PASS Gate. The WorkItems
consume only canonical N1/N2 artifacts and are responsible for discovering an
evidence-backed application -> source target mapping in a later fresh DSH step.

This layer deliberately does not contain repository/ref/revision fields, launch
a worker, create a DSH session, emit a code-analysis result, or advance N4.
N3 moves READY -> RUNNING only after every discovery WorkItem is durably READY.
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
from .rc72_state_machine import RC72StateMachine
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n3_source_target_dispatch"
_EVENT = "RC72_N3_SOURCE_TARGET_DISPATCH_UPSERTED"
_BUCKET = "rc72_n3_source_target_dispatches"
_NODE = AutonomousMissionNode.N3_CODE_ANALYSIS
_SOURCE_NODE = AutonomousMissionNode.N2_REQUIREMENT
_REALITY_NODE = AutonomousMissionNode.N1_REALITY
_NEXT_NODE = AutonomousMissionNode.N4_TEST_DESIGN
_STAGE = "SOURCE_TARGET_DISCOVERY"
_TASK_TYPE = "RC72_NODE_WORK"
_TEAM_ROLE = "SOURCE_TARGET_DISCOVERY_WORKER"
_SUBSTRATE = "DSH_AGENT_TEAMS"
_WORKER_POLICY = "FRESH_SESSION_REQUIRED"
_STATUS = "READY_FOR_ASSIGNMENT"
_CAPABILITIES = ("source_target_discovery",)


class N3SourceTargetDispatchError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3SourceTargetDispatchError(
            "RC72_N3_SOURCE_DISPATCH_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _strings(value: Any, name: str, *, required: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_DISPATCH_%s_INVALID" % name.upper()
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_DISPATCH_%s_INVALID" % name.upper()
        )
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_DISPATCH_%s_DUPLICATE" % name.upper()
        )
    if required and not value:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_DISPATCH_%s_REQUIRED" % name.upper()
        )
    return list(value)


def validate_rc72_n3_source_target_dispatch(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "dispatch_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "mission_node_id", "node_type", "stage",
        "application_id", "workitem_id", "team_role", "execution_substrate",
        "worker_policy", "source_n1_node_id", "source_n1_delivery_id",
        "source_n1_gate_id", "source_n2_node_id", "source_n2_delivery_id",
        "source_n2_gate_id", "status",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["node_type"] != _NODE.value:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_DISPATCH_NODE_INVALID")
    if out["stage"] != _STAGE:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_DISPATCH_STAGE_INVALID")
    if out["team_role"] != _TEAM_ROLE:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_DISPATCH_TEAM_ROLE_INVALID")
    if out["execution_substrate"] != _SUBSTRATE:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_DISPATCH_SUBSTRATE_INVALID")
    if out["worker_policy"] != _WORKER_POLICY:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_DISPATCH_WORKER_POLICY_INVALID")
    if out["status"] != _STATUS:
        raise _contracts.DomainValidationError("RC72_N3_SOURCE_DISPATCH_STATUS_INVALID")
    for name in (
        "source_n1_artifact_refs", "source_n1_evidence_refs",
        "source_n2_artifact_refs", "source_n2_evidence_refs",
        "required_capabilities",
    ):
        out[name] = _strings(out.get(name), name, required=True)
    # A dispatch is only permission to discover source targets. Any repository
    # identity/revision in this row would be coordinator-fabricated truth.
    for forbidden in (
        "repository", "repository_id", "repository_ref", "repo", "repo_ref",
        "source_revision", "base_revision", "head_revision", "branch",
        "target_id", "changed_files", "changed_symbols", "codegraph_result",
        "worker_id", "worker_instance_id", "session_id", "dsh_session_id",
        "attempt_id", "output_refs", "evaluation", "node_delivery_id",
        "node_gate", "node_pass", "n4_started", "q7_pass", "field_verified",
        "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N3_SOURCE_DISPATCH_PREMATURE_SOURCE_CLAIM_FORBIDDEN:%s"
                % forbidden
            )
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N3_SOURCE_DISPATCH_%s_INVALID" % name.upper()
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_DISPATCH_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n3_source_target_dispatch_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n3_source_target_dispatch
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


class N3SourceTargetDispatchService:
    """Fan out N3 source-target discovery without inventing source identity."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_n3_source_target_dispatch_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N3SourceTargetDispatchError(
                "RC72_N3_SOURCE_DISPATCH_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _active_pass(
        self, mission_id: str, node_type: AutonomousMissionNode
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=node_type.value
        )
        if node.get("state") != MissionNodeState.PASS.value:
            raise N3SourceTargetDispatchError(
                "RC72_N3_SOURCE_DISPATCH_%s_NOT_PASS" % node_type.value
            )
        active_version = node.get("active_delivery_version")
        if isinstance(active_version, bool) or not isinstance(active_version, int):
            raise N3SourceTargetDispatchError(
                "RC72_N3_SOURCE_DISPATCH_%s_ACTIVE_DELIVERY_REQUIRED"
                % node_type.value
            )
        deliveries = [
            row for row in self.truth.query(
                "rc72_node_delivery", mission_node_id=str(node["mission_node_id"])
            )
            if row.get("version") == active_version
            and row.get("delivery_id") in list(node.get("delivery_refs") or [])
        ]
        if len(deliveries) != 1:
            raise N3SourceTargetDispatchError(
                "RC72_N3_SOURCE_DISPATCH_%s_ACTIVE_DELIVERY_NOT_UNIQUE:%d"
                % (node_type.value, len(deliveries))
            )
        delivery = deliveries[0]
        gates = [
            row for row in self.truth.query(
                "rc72_node_gate", mission_node_id=str(node["mission_node_id"])
            )
            if row.get("gate_id") in list(node.get("gate_refs") or [])
            and row.get("delivery_id") == delivery.get("delivery_id")
            and row.get("decision") == "PASS"
        ]
        if len(gates) != 1:
            raise N3SourceTargetDispatchError(
                "RC72_N3_SOURCE_DISPATCH_%s_PASS_GATE_NOT_UNIQUE:%d"
                % (node_type.value, len(gates))
            )
        return node, delivery, gates[0]

    def _canonical_refs(
        self, mission_id: str, delivery: Mapping[str, Any], label: str
    ) -> Tuple[List[str], List[str]]:
        artifact_refs = list(delivery.get("artifact_refs") or [])
        evidence_refs = list(delivery.get("evidence_refs") or [])
        if not artifact_refs or not evidence_refs:
            raise N3SourceTargetDispatchError(
                "RC72_N3_SOURCE_DISPATCH_%s_CANONICAL_REFS_REQUIRED" % label
            )
        for artifact_id in artifact_refs:
            artifact = self._one("rc7_artifact", artifact_id=str(artifact_id))
            if artifact.get("mission_id") != mission_id or artifact.get("state") != "VALID":
                raise N3SourceTargetDispatchError(
                    "RC72_N3_SOURCE_DISPATCH_%s_ARTIFACT_INVALID:%s"
                    % (label, artifact_id)
                )
        for evidence_id in evidence_refs:
            evidence = self._one("rc7_evidence", evidence_id=str(evidence_id))
            if evidence.get("mission_id") != mission_id:
                raise N3SourceTargetDispatchError(
                    "RC72_N3_SOURCE_DISPATCH_%s_EVIDENCE_INVALID:%s"
                    % (label, evidence_id)
                )
        return artifact_refs, evidence_refs

    @staticmethod
    def _workitem_id(mission_id: str, release_batch_id: str, application_id: str) -> str:
        return _stable_id(
            "WI-N3-SOURCE", mission_id, release_batch_id, application_id
        )

    @staticmethod
    def _dispatch_id(
        mission_id: str,
        release_batch_id: str,
        application_id: str,
        n2_gate_id: str,
        source_commit: str,
    ) -> str:
        return _stable_id(
            "N3DISP-SOURCE", mission_id, release_batch_id, application_id,
            n2_gate_id, source_commit,
        )

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        keys = (
            "release_id", "mission_id", "release_batch_id", "source_commit",
            "mission_node_id", "node_type", "stage", "application_id",
            "workitem_id", "team_role", "execution_substrate", "worker_policy",
            "source_n1_node_id", "source_n1_delivery_id", "source_n1_gate_id",
            "source_n2_node_id", "source_n2_delivery_id", "source_n2_gate_id",
            "status",
        )
        result = {key: payload.get(key) for key in keys}
        for key in (
            "source_n1_artifact_refs", "source_n1_evidence_refs",
            "source_n2_artifact_refs", "source_n2_evidence_refs",
            "required_capabilities",
        ):
            result[key] = list(payload.get(key) or [])
        return result

    def _preflight(
        self, release_batch_id: str
    ) -> Tuple[
        Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
        Dict[str, Any], Dict[str, Any], List[str], List[str], List[str], List[str],
    ]:
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        mission_id = _required(batch.get("mission_id"), "mission_id")
        release_id = _required(batch.get("release_id"), "release_id")
        application_ids = list(batch.get("application_ids") or [])
        if (
            not application_ids
            or not all(isinstance(item, str) and item.strip() for item in application_ids)
            or len(set(application_ids)) != len(application_ids)
        ):
            raise N3SourceTargetDispatchError(
                "RC72_N3_SOURCE_DISPATCH_CANONICAL_APPLICATIONS_REQUIRED"
            )
        mission = self._one("rc7_mission", mission_id=mission_id)
        if mission.get("release_id") != release_id:
            raise N3SourceTargetDispatchError(
                "RC72_N3_SOURCE_DISPATCH_RC7_MISSION_LINEAGE_MISMATCH"
            )
        n3 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NODE.value
        )
        if n3.get("scope_ref") != "release-batch://%s" % release_batch_id:
            raise N3SourceTargetDispatchError(
                "RC72_N3_SOURCE_DISPATCH_N3_SCOPE_MISMATCH"
            )
        if n3.get("state") not in {
            MissionNodeState.READY.value, MissionNodeState.RUNNING.value,
        }:
            raise N3SourceTargetDispatchError(
                "RC72_N3_SOURCE_DISPATCH_N3_STATE_INVALID:%s"
                % str(n3.get("state") or "UNKNOWN")
            )
        n4 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
        )
        if n4.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N3SourceTargetDispatchError(
                "RC72_N3_SOURCE_DISPATCH_N4_ALREADY_RELEASED"
            )
        n1, n1_delivery, n1_gate = self._active_pass(mission_id, _REALITY_NODE)
        n2, n2_delivery, n2_gate = self._active_pass(mission_id, _SOURCE_NODE)
        n1_artifacts, n1_evidence = self._canonical_refs(
            mission_id, n1_delivery, "N1"
        )
        n2_artifacts, n2_evidence = self._canonical_refs(
            mission_id, n2_delivery, "N2"
        )
        return (
            batch, n3, n1, n1_gate, n2, n2_gate,
            n1_artifacts, n1_evidence, n2_artifacts, n2_evidence,
        )

    def dispatch(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        (
            batch, n3, n1, n1_gate, n2, n2_gate,
            n1_artifacts, n1_evidence, n2_artifacts, n2_evidence,
        ) = self._preflight(release_batch_id)
        release_id = str(batch["release_id"])
        mission_id = str(batch["mission_id"])
        applications = list(batch.get("application_ids") or [])
        n1_delivery_id = str(n1_gate["delivery_id"])
        n2_delivery_id = str(n2_gate["delivery_id"])

        expected = []
        for application_id in applications:
            workitem_id = self._workitem_id(
                mission_id, release_batch_id, application_id
            )
            dispatch_id = self._dispatch_id(
                mission_id, release_batch_id, application_id,
                str(n2_gate["gate_id"]), self.source_commit,
            )
            expected.append({
                "dispatch_id": dispatch_id,
                "release_id": release_id,
                "mission_id": mission_id,
                "release_batch_id": release_batch_id,
                "source_commit": self.source_commit,
                "mission_node_id": str(n3["mission_node_id"]),
                "node_type": _NODE.value,
                "stage": _STAGE,
                "application_id": application_id,
                "workitem_id": workitem_id,
                "team_role": _TEAM_ROLE,
                "execution_substrate": _SUBSTRATE,
                "worker_policy": _WORKER_POLICY,
                "source_n1_node_id": str(n1["mission_node_id"]),
                "source_n1_delivery_id": n1_delivery_id,
                "source_n1_gate_id": str(n1_gate["gate_id"]),
                "source_n1_artifact_refs": list(n1_artifacts),
                "source_n1_evidence_refs": list(n1_evidence),
                "source_n2_node_id": str(n2["mission_node_id"]),
                "source_n2_delivery_id": n2_delivery_id,
                "source_n2_gate_id": str(n2_gate["gate_id"]),
                "source_n2_artifact_refs": list(n2_artifacts),
                "source_n2_evidence_refs": list(n2_evidence),
                "required_capabilities": list(_CAPABILITIES),
                "status": _STATUS,
            })

        existing = self.truth.query(
            _ARTIFACT, release_batch_id=release_batch_id
        )
        if existing:
            if len(existing) != len(expected):
                raise N3SourceTargetDispatchError(
                    "RC72_N3_SOURCE_DISPATCH_PARTIAL_SET"
                )
            by_id = {str(row["dispatch_id"]): row for row in existing}
            if set(by_id) != {str(item["dispatch_id"]) for item in expected}:
                raise N3SourceTargetDispatchError(
                    "RC72_N3_SOURCE_DISPATCH_SET_CONFLICT"
                )
            for item in expected:
                row = by_id[item["dispatch_id"]]
                if self._signature(row) != self._signature(item):
                    raise N3SourceTargetDispatchError(
                        "RC72_N3_SOURCE_DISPATCH_RECEIPT_CONFLICT"
                    )
                task = self._one("rc7_task", task_id=str(item["workitem_id"]))
                if task.get("state") not in {"READY", "LEASED", "RUNNING", "OUTPUT_PRODUCED", "EVALUATING", "PASS", "REPAIR_REQUIRED"}:
                    raise N3SourceTargetDispatchError(
                        "RC72_N3_SOURCE_DISPATCH_WORKITEM_STATE_INVALID"
                    )
            return {
                "status": "RESUMED",
                "release_batch_id": release_batch_id,
                "mission_id": mission_id,
                "mission_node_id": str(n3["mission_node_id"]),
                "node_state": self._one(
                    "rc72_mission_node", mission_node_id=str(n3["mission_node_id"])
                )["state"],
                "dispatches": expected,
            }

        control = ClosedLoopControlPlane(self.truth, release_id, mission_id)
        input_refs = list(dict.fromkeys(n1_artifacts + n2_artifacts))
        for item in expected:
            if self.truth.query("rc7_task", task_id=str(item["workitem_id"])):
                raise N3SourceTargetDispatchError(
                    "RC72_N3_SOURCE_DISPATCH_WORKITEM_ALREADY_EXISTS"
                )
            control.register_task(Task(
                task_id=str(item["workitem_id"]),
                mission_id=mission_id,
                node=_STAGE,
                task_type=_TASK_TYPE,
                objective=(
                    "Discover evidence-backed source repository and exact source revision(s) for application %s; never infer repository identity from application name"
                    % item["application_id"]
                ),
                required_capabilities=list(_CAPABILITIES),
                input_artifact_refs=list(input_refs),
                acceptance_criteria=[
                    "application identity matches canonical ReleaseBatch",
                    "repository/source target identity is proven by real tool evidence",
                    "base/head or deployed source revision is explicit and evidence-backed",
                    "unknown or ambiguous mapping is returned as a gap, never guessed",
                    "no CODE_ANALYSIS PASS claim is produced by discovery",
                ],
                priority=0,
            ))
        ready = list(control.scheduler.ready_tasks(mission_id))
        expected_ids = {str(item["workitem_id"]) for item in expected}
        actual_ids = {task.task_id for task in ready if task.node == _STAGE}
        if actual_ids != expected_ids:
            raise N3SourceTargetDispatchError(
                "RC72_N3_SOURCE_DISPATCH_READY_SET_MISMATCH"
            )
        foreign = [
            task.task_id for task in ready
            if task.node != _STAGE and task.task_id not in expected_ids
        ]
        if foreign:
            raise N3SourceTargetDispatchError(
                "RC72_N3_SOURCE_DISPATCH_FOREIGN_READY_TASK_CONFLICT:%s"
                % ",".join(sorted(foreign))
            )
        now = _now()
        for item in expected:
            payload = dict(item)
            payload.update({"created_at": now, "updated_at": now, "artifact_version": 1})
            self.truth.append_atomic(_EVENT, payload)
        if n3.get("state") == MissionNodeState.READY.value:
            RC72StateMachine(self.truth, release_id=release_id).transition_state(
                str(n3["mission_node_id"]),
                MissionNodeState.RUNNING,
                reason="source target discovery WorkItems ready",
            )
        return {
            "status": "DISPATCHED",
            "release_batch_id": release_batch_id,
            "mission_id": mission_id,
            "mission_node_id": str(n3["mission_node_id"]),
            "node_state": MissionNodeState.RUNNING.value,
            "n4_state": MissionNodeState.NOT_STARTED.value,
            "dispatches": expected,
        }


install_rc72_n3_source_target_dispatch_overlay()
