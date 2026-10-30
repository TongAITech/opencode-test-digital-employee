"""RC7.2 governed N2 per-Requirement revision planning and fresh assignment.

RC7 repair tasks may resolve evidence prerequisites for Requirement gaps, but
RC7.2 never reuses the original Requirement WorkItem as the actual re-analysis.
Once all gaps for an affected Requirement are EVIDENCE_PENDING/RESOLVED, the
old source WorkItem is retired and a new revision WorkItem is leased to a fresh
AgentTeams worker identity.

The receipt is keyed by failed Gate + Requirement. Replaying the same failed
Gate resumes the same generation/worker; only a later failed Gate may allocate
the next generation. This layer stops at LEASED_FOR_HANDOFF and emits no DSH
session, Attempt, output, Evaluation, Delivery, Gate, N3 execution or field
claim.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Mapping, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError, GapStatus, Task, TaskStatus
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_state_machine import RC72StateMachine
from .rc72_truth import install_rc72_truth_overlay
from .state_machine import transition_task
from .truth_overlay import append_entity, install_rc7_truth_overlay


_ARTIFACT = "rc72_n2_revision_receipt"
_EVENT = "RC72_N2_REVISION_RECEIPT_UPSERTED"
_BUCKET = "rc72_n2_revision_receipts"
_NODE = AutonomousMissionNode.N2_REQUIREMENT
_NEXT_NODE = AutonomousMissionNode.N3_CODE_ANALYSIS
_STAGE = "REQUIREMENT_ANALYSIS"
_TASK_TYPE = "RC72_NODE_WORK"
_STATUS = "LEASED_FOR_HANDOFF"
_CAPABILITIES = ("requirement_reasoning",)
_READY_GAP_STATES = {GapStatus.EVIDENCE_PENDING.value, GapStatus.RESOLVED.value}


class N2RevisionError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N2RevisionError("RC72_N2_REVISION_%s_REQUIRED" % name.upper())
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _strings(value: Any, name: str, *, required: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError("RC72_N2_REVISION_%s_INVALID" % name.upper())
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("RC72_N2_REVISION_%s_INVALID" % name.upper())
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError("RC72_N2_REVISION_%s_DUPLICATE" % name.upper())
    if required and not value:
        raise _contracts.DomainValidationError("RC72_N2_REVISION_%s_REQUIRED" % name.upper())
    return list(value)


def validate_rc72_n2_revision_receipt(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "revision_id", "release_id", "mission_id", "release_batch_id", "source_commit",
        "mission_node_id", "requirement_id", "failed_gate_id", "failed_delivery_id",
        "previous_workitem_id", "previous_artifact_id", "revision_workitem_id",
        "revision_worker_instance_id", "status",
    ):
        out[name] = _contracts._require_str(out, name)
    generation = out.get("revision_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 2:
        raise _contracts.DomainValidationError("RC72_N2_REVISION_GENERATION_INVALID")
    out["revision_generation"] = generation
    out["gap_refs"] = _strings(out.get("gap_refs"), "gap_refs", required=True)
    out["input_artifact_refs"] = _strings(
        out.get("input_artifact_refs"), "input_artifact_refs", required=True
    )
    if out["status"] != _STATUS:
        raise _contracts.DomainValidationError("RC72_N2_REVISION_STATUS_INVALID")
    for forbidden in (
        "session_id", "dsh_session_id", "attempt_id", "output_refs", "evidence_refs",
        "evaluation", "node_delivery_id", "node_gate", "node_pass", "n3_started",
        "q7_pass", "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N2_REVISION_EXECUTION_CLAIM_FORBIDDEN:%s" % forbidden
            )
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError("RC72_N2_REVISION_%s_INVALID" % name.upper())
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_N2_REVISION_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n2_revision_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n2_revision_receipt
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "revision_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "revision_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class N2RevisionDispatchService:
    """Create fresh revision WorkItems only for Requirements implicated by the active failed N2 Gate."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_n2_revision_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N2RevisionError(
                "RC72_N2_REVISION_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows))
            )
        return rows[0]

    def _active_failed_cycle(
        self, release_batch_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        mission_id = str(batch["mission_id"])
        node = self._one("rc72_mission_node", mission_id=mission_id, node_type=_NODE.value)
        if node.get("state") not in {
            MissionNodeState.NEEDS_REVISION.value,
            MissionNodeState.RUNNING.value,
        }:
            raise N2RevisionError(
                "RC72_N2_REVISION_NODE_STATE_INVALID:%s" % str(node.get("state") or "UNKNOWN")
            )
        gate_refs = list(node.get("gate_refs") or [])
        if not gate_refs:
            raise N2RevisionError("RC72_N2_REVISION_FAILED_GATE_REQUIRED")
        gate = self._one("rc72_node_gate", gate_id=str(gate_refs[-1]))
        if (
            gate.get("mission_node_id") != node.get("mission_node_id")
            or gate.get("decision") != "NEEDS_REVISION"
        ):
            raise N2RevisionError("RC72_N2_REVISION_ACTIVE_GATE_NOT_FAILED")
        delivery = self._one("rc72_node_delivery", delivery_id=str(gate["delivery_id"]))
        if (
            delivery.get("mission_node_id") != node.get("mission_node_id")
            or delivery.get("version") != node.get("active_delivery_version")
        ):
            raise N2RevisionError("RC72_N2_REVISION_DELIVERY_NOT_ACTIVE")
        n3 = self._one("rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value)
        if n3.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N2RevisionError("RC72_N2_REVISION_N3_ALREADY_RELEASED")
        return batch, node, gate, delivery

    def _requirement_for_workitem(self, workitem_id: str) -> str:
        initial = self.truth.query("rc72_n2_requirement_dispatch", workitem_id=workitem_id)
        if len(initial) == 1:
            return _required(initial[0].get("requirement_id"), "requirement_id")
        revisions = [
            row for row in self.truth.query(_ARTIFACT)
            if row.get("revision_workitem_id") == workitem_id
        ]
        if len(revisions) == 1:
            return _required(revisions[0].get("requirement_id"), "requirement_id")
        raise N2RevisionError(
            "RC72_N2_REVISION_WORKITEM_REQUIREMENT_NOT_UNIQUE:%s" % workitem_id
        )

    def _generation(
        self,
        release_batch_id: str,
        requirement_id: str,
        failed_gate_id: str,
    ) -> int:
        rows = [
            row for row in self.truth.query(_ARTIFACT, release_batch_id=release_batch_id)
            if row.get("source_commit") == self.source_commit
            and row.get("requirement_id") == requirement_id
        ]
        same_gate = [row for row in rows if row.get("failed_gate_id") == failed_gate_id]
        if same_gate:
            if len(same_gate) != 1:
                raise N2RevisionError("RC72_N2_REVISION_FAILED_GATE_RECEIPT_NOT_UNIQUE")
            generation = int(same_gate[0].get("revision_generation") or 0)
            if generation < 2:
                raise N2RevisionError("RC72_N2_REVISION_EXISTING_GENERATION_INVALID")
            return generation
        if not rows:
            return 2
        highest = max(int(row.get("revision_generation") or 0) for row in rows)
        if highest < 2:
            raise N2RevisionError("RC72_N2_REVISION_EXISTING_GENERATION_INVALID")
        if len([row for row in rows if int(row.get("revision_generation") or 0) == highest]) != 1:
            raise N2RevisionError("RC72_N2_REVISION_GENERATION_NOT_UNIQUE")
        return highest + 1

    def _affected(self, delivery: Mapping[str, Any]) -> List[Dict[str, Any]]:
        known_gaps = set(str(item) for item in list(delivery.get("known_gaps") or []))
        if not known_gaps:
            raise N2RevisionError("RC72_N2_REVISION_KNOWN_GAPS_REQUIRED")
        result = []
        for workitem_id in list(delivery.get("created_by_workitems") or []):
            task = self._one("rc7_task", task_id=str(workitem_id))
            relevant = [gap_id for gap_id in list(task.get("gap_refs") or []) if gap_id in known_gaps]
            if not relevant:
                continue
            requirement_id = self._requirement_for_workitem(str(workitem_id))
            artifact_refs = []
            for artifact_id in list(delivery.get("artifact_refs") or []):
                artifact = self._one("rc7_artifact", artifact_id=str(artifact_id))
                if artifact.get("producer_task_id") == workitem_id:
                    artifact_refs.append(str(artifact_id))
            if len(artifact_refs) != 1:
                raise N2RevisionError(
                    "RC72_N2_REVISION_PREVIOUS_ARTIFACT_NOT_UNIQUE:%s" % requirement_id
                )
            gap_rows = [self._one("rc7_gap", gap_id=gap_id) for gap_id in relevant]
            not_ready = [
                row["gap_id"] for row in gap_rows
                if row.get("state") not in _READY_GAP_STATES
            ]
            if not_ready:
                raise N2RevisionError(
                    "RC72_N2_REVISION_REPAIR_EVIDENCE_NOT_READY:%s:%s"
                    % (requirement_id, ",".join(sorted(not_ready)))
                )
            result.append({
                "requirement_id": requirement_id,
                "previous_workitem_id": str(workitem_id),
                "previous_artifact_id": artifact_refs[0],
                "gap_refs": sorted(relevant),
                "previous_task": task,
            })
        if not result:
            raise N2RevisionError("RC72_N2_REVISION_AFFECTED_REQUIREMENT_REQUIRED")
        result.sort(key=lambda item: str(item["requirement_id"]))
        return result

    def _persist_task_stale(self, task_row: Mapping[str, Any], release_id: str) -> None:
        if task_row.get("state") == TaskStatus.STALE.value:
            return
        if task_row.get("state") != TaskStatus.READY.value:
            raise N2RevisionError(
                "RC72_N2_REVISION_SOURCE_TASK_NOT_REACTIVATED:%s:%s"
                % (task_row.get("task_id"), task_row.get("state"))
            )
        control = ClosedLoopControlPlane(self.truth, release_id, str(task_row["mission_id"]))
        task = control.scheduler.task(str(task_row["task_id"]))
        transition_task(task, TaskStatus.STALE)
        append_entity(
            self.truth,
            task,
            release_id=release_id,
            artifact_version=int(task_row.get("artifact_version") or 1) + 1,
        )

    def _expected(
        self,
        *,
        batch: Mapping[str, Any],
        node: Mapping[str, Any],
        gate: Mapping[str, Any],
        delivery: Mapping[str, Any],
        affected: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        mission_id = str(batch["mission_id"])
        release_batch_id = str(batch["release_batch_id"])
        out = []
        for item in affected:
            requirement_id = str(item["requirement_id"])
            generation = self._generation(
                release_batch_id, requirement_id, str(gate["gate_id"])
            )
            revision_id = _stable_id(
                "N2REV", mission_id, str(gate["gate_id"]), requirement_id, "GEN%d" % generation
            )
            workitem_id = _stable_id("WI-N2-REQ-REV", revision_id, "WORKITEM")
            worker_id = _stable_id("RC72N2REVFW", revision_id, "FRESH_WORKER")
            previous_task = item["previous_task"]
            input_refs = []
            for ref in list(previous_task.get("input_artifact_refs") or []) + [str(item["previous_artifact_id"])]:
                if ref not in input_refs:
                    input_refs.append(ref)
            out.append({
                "revision_id": revision_id,
                "release_id": str(batch["release_id"]),
                "mission_id": mission_id,
                "release_batch_id": release_batch_id,
                "source_commit": self.source_commit,
                "mission_node_id": str(node["mission_node_id"]),
                "requirement_id": requirement_id,
                "failed_gate_id": str(gate["gate_id"]),
                "failed_delivery_id": str(delivery["delivery_id"]),
                "revision_generation": generation,
                "previous_workitem_id": str(item["previous_workitem_id"]),
                "previous_artifact_id": str(item["previous_artifact_id"]),
                "revision_workitem_id": workitem_id,
                "revision_worker_instance_id": worker_id,
                "gap_refs": list(item["gap_refs"]),
                "input_artifact_refs": input_refs,
                "status": _STATUS,
            })
        return out

    @staticmethod
    def _receipt_signature(row: Mapping[str, Any]) -> Dict[str, Any]:
        keys = (
            "revision_id", "release_id", "mission_id", "release_batch_id", "source_commit",
            "mission_node_id", "requirement_id", "failed_gate_id", "failed_delivery_id",
            "revision_generation", "previous_workitem_id", "previous_artifact_id",
            "revision_workitem_id", "revision_worker_instance_id", "status",
        )
        result = {key: row.get(key) for key in keys}
        result["gap_refs"] = list(row.get("gap_refs") or [])
        result["input_artifact_refs"] = list(row.get("input_artifact_refs") or [])
        return result

    def plan_and_assign(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        batch, node, gate, delivery = self._active_failed_cycle(release_batch_id)
        release_id = str(batch["release_id"])
        mission_id = str(batch["mission_id"])
        affected = self._affected(delivery)
        expected = self._expected(
            batch=batch, node=node, gate=gate, delivery=delivery, affected=affected
        )
        existing_rows = self.truth.query(_ARTIFACT, release_batch_id=release_batch_id)
        existing = {str(row["revision_id"]): row for row in existing_rows}
        matched = [item for item in expected if item["revision_id"] in existing]
        if matched:
            if len(matched) != len(expected):
                raise N2RevisionError("RC72_N2_REVISION_PARTIAL_RECEIPT_SET")
            for item in expected:
                row = existing[item["revision_id"]]
                if self._receipt_signature(row) != self._receipt_signature(item):
                    raise N2RevisionError("RC72_N2_REVISION_RECEIPT_CONFLICT")
                task = self._one("rc7_task", task_id=str(item["revision_workitem_id"]))
                if (
                    task.get("lease_owner") != item["revision_worker_instance_id"]
                    or task.get("state") not in {
                        TaskStatus.LEASED.value, TaskStatus.RUNNING.value,
                        TaskStatus.OUTPUT_PRODUCED.value, TaskStatus.EVALUATING.value,
                        TaskStatus.PASS.value, TaskStatus.REPAIR_REQUIRED.value,
                    }
                ):
                    raise N2RevisionError("RC72_N2_REVISION_RECEIPT_LEASE_MISMATCH")
            return {
                "status": "RESUMED",
                "release_batch_id": release_batch_id,
                "mission_id": mission_id,
                "mission_node_id": str(node["mission_node_id"]),
                "node_state": self._one(
                    "rc72_mission_node", mission_node_id=str(node["mission_node_id"])
                )["state"],
                "n3_state": self._one(
                    "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
                )["state"],
                "revisions": expected,
            }

        # RC7 repair PASS reactivates the old source task. RC7.2 retires it so
        # generic scheduling cannot accidentally reuse the old WorkItem/session.
        for item in affected:
            source = self._one("rc7_task", task_id=str(item["previous_workitem_id"]))
            self._persist_task_stale(source, release_id)

        control = ClosedLoopControlPlane(self.truth, release_id, mission_id)
        for item in expected:
            if self.truth.query("rc7_task", task_id=str(item["revision_workitem_id"])):
                raise N2RevisionError("RC72_N2_REVISION_WORKITEM_ALREADY_EXISTS")
            control.register_task(Task(
                task_id=str(item["revision_workitem_id"]),
                mission_id=mission_id,
                node=_STAGE,
                task_type=_TASK_TYPE,
                objective=(
                    "Re-analyze canonical requirement %s after repaired gaps from N2 Gate %s using fresh evidence"
                    % (item["requirement_id"], item["failed_gate_id"])
                ),
                required_capabilities=list(_CAPABILITIES),
                input_artifact_refs=list(item["input_artifact_refs"]),
                gap_refs=list(item["gap_refs"]),
                acceptance_criteria=[
                    "re-evaluate repaired gaps with fresh source evidence",
                    "preserve requirement and SST identity",
                    "return explicit unknowns/gaps when evidence remains insufficient",
                    "independent Requirement review is mandatory before PASS",
                ],
                priority=5,
            ))

        target_ids = {str(item["revision_workitem_id"]) for item in expected}
        ready = list(control.scheduler.ready_tasks(mission_id))
        foreign = [task.task_id for task in ready if task.task_id not in target_ids]
        if foreign:
            raise N2RevisionError(
                "RC72_N2_REVISION_FOREIGN_READY_TASK_CONFLICT:%s" % ",".join(sorted(foreign))
            )
        if {task.task_id for task in ready} != target_ids:
            raise N2RevisionError("RC72_N2_REVISION_READY_SET_MISMATCH")
        by_task = {str(item["revision_workitem_id"]): item for item in expected}
        receipts = []
        for ready_task in ready:
            item = by_task[ready_task.task_id]
            leased = control.lease_next(
                worker_ref=str(item["revision_worker_instance_id"]),
                capabilities=list(_CAPABILITIES),
            )
            if leased is None or leased.task_id != ready_task.task_id:
                observed = "NONE" if leased is None else leased.task_id
                raise N2RevisionError(
                    "RC72_N2_REVISION_LEASE_IDENTITY_MISMATCH:%s:%s"
                    % (ready_task.task_id, observed)
                )
            payload = dict(item)
            now = _now()
            payload.update({"created_at": now, "updated_at": now, "artifact_version": 1})
            self.truth.append_atomic(_EVENT, payload)
            receipts.append(dict(item))

        if node.get("state") == MissionNodeState.NEEDS_REVISION.value:
            RC72StateMachine(self.truth, release_id=release_id).transition_state(
                str(node["mission_node_id"]),
                MissionNodeState.RUNNING,
                reason="fresh N2 Requirement revision WorkItems leased",
            )
        n3 = self._one("rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value)
        if n3.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N2RevisionError("RC72_N2_REVISION_N3_PREMATURE_RELEASE")
        return {
            "status": "ASSIGNED",
            "release_batch_id": release_batch_id,
            "mission_id": mission_id,
            "mission_node_id": str(node["mission_node_id"]),
            "node_state": MissionNodeState.RUNNING.value,
            "n3_state": MissionNodeState.NOT_STARTED.value,
            "revisions": receipts,
        }


install_rc72_n2_revision_overlay()
