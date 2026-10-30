"""RC7.2 governed N1 revision cycle.

A failed N1 NodeGate is not a prompt to let the same worker "try again".  It is
persisted control-plane truth that creates a new WorkItem, a new AgentTeams
worker identity and a new DSH session while retaining the failed Attempt,
Delivery and Gate as immutable history.

Revision generation starts at Delivery v2.  Every subsequent failed Gate can
produce v3/v4... through the same contract.  Only the independent N1 Gate may
PASS the node and release N2.  This module never claims field_verified, Q7 PASS
or BANK_FINAL.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime

from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError, Task, TaskStatus
from .rc72_domain import AutonomousMissionNode, MissionNodeState, NodeDelivery
from .rc72_mission_node_assignment import install_rc72_mission_node_assignment_overlay
from .rc72_mission_node_dispatch import install_rc72_mission_node_dispatch_overlay
from .rc72_mission_node_handoff import N1DshHandoffService
from .rc72_n1_completion import (
    N1DeliveryGateService,
    N1EvidenceAnchorService,
    _gap_strings,
    _uniq,
    install_rc72_n1_completion_overlay,
)
from .rc72_state_machine import RC72StateMachine
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n1_revision_receipt"
_EVENT = "RC72_N1_REVISION_RECEIPT_UPSERTED"
_BUCKET = "rc72_n1_revision_receipts"

_NODE_TYPE = AutonomousMissionNode.N1_REALITY.value
_STAGE = "REALITY_RECON"
_TASK_TYPE = "RC72_NODE_WORK"
_TEAM_ROLE = "REALITY_RECON_WORKER"
_AGENT_ID = "reality-recon"
_SUBSTRATE = "DSH_AGENT_TEAMS"
_WORKER_POLICY = "FRESH_SESSION_REQUIRED"
_CAPABILITIES = ("reality_recon", "field_evidence")
_STATUS = "LEASED_FOR_HANDOFF"


class N1RevisionError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N1RevisionError("RC72_N1_REVISION_%s_REQUIRED" % name.upper())
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def validate_rc72_n1_revision_receipt(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "revision_id",
        "release_id",
        "mission_id",
        "release_batch_id",
        "source_commit",
        "mission_node_id",
        "failed_gate_id",
        "failed_delivery_id",
        "previous_workitem_id",
        "revision_workitem_id",
        "revision_dispatch_id",
        "revision_assignment_id",
        "revision_worker_instance_id",
        "status",
    ):
        out[name] = _contracts._require_str(out, name)
    generation = out.get("revision_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 2:
        raise _contracts.DomainValidationError("RC72_N1_REVISION_GENERATION_INVALID")
    out["revision_generation"] = generation
    refs = out.get("input_artifact_refs")
    if not isinstance(refs, list) or not refs or not all(isinstance(item, str) and item.strip() for item in refs):
        raise _contracts.DomainValidationError("RC72_N1_REVISION_INPUT_ARTIFACTS_REQUIRED")
    if len(set(refs)) != len(refs):
        raise _contracts.DomainValidationError("RC72_N1_REVISION_INPUT_ARTIFACTS_DUPLICATE")
    out["input_artifact_refs"] = list(refs)
    failed = out.get("failed_criteria")
    if not isinstance(failed, list) or not failed or not all(isinstance(item, str) and item.strip() for item in failed):
        raise _contracts.DomainValidationError("RC72_N1_REVISION_FAILED_CRITERIA_REQUIRED")
    out["failed_criteria"] = list(failed)
    if out["status"] != _STATUS:
        raise _contracts.DomainValidationError("RC72_N1_REVISION_STATUS_INVALID")
    for flag in ("field_verified", "bank_final"):
        if out.get(flag, False) is not False:
            raise _contracts.DomainValidationError("RC72_N1_REVISION_%s_FORBIDDEN" % flag.upper())
        out[flag] = False
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError("RC72_N1_REVISION_%s_INVALID" % name.upper())
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_N1_REVISION_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n1_revision_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_mission_node_dispatch_overlay()
    install_rc72_mission_node_assignment_overlay()
    install_rc72_n1_completion_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n1_revision_receipt
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


def _latest_revision(truth: TruthRuntime, release_batch_id: str, source_commit: str) -> Dict[str, Any]:
    rows = [
        row
        for row in truth.query(_ARTIFACT, release_batch_id=release_batch_id)
        if row.get("source_commit") == source_commit
    ]
    if not rows:
        raise N1RevisionError("RC72_N1_REVISION_RECEIPT_REQUIRED")
    rows.sort(key=lambda row: int(row.get("revision_generation") or 0))
    latest = rows[-1]
    if len([row for row in rows if row.get("revision_generation") == latest.get("revision_generation")]) != 1:
        raise N1RevisionError("RC72_N1_REVISION_GENERATION_NOT_UNIQUE")
    return latest


class N1RevisionDispatchService:
    """Materialize and lease one new N1 WorkItem from the active failed Gate."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_n1_revision_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N1RevisionError("RC72_N1_REVISION_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows)))
        return rows[0]

    def _failed_cycle(self, release_batch_id: str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        node = self._one(
            "rc72_mission_node",
            mission_id=str(batch["mission_id"]),
            node_type=_NODE_TYPE,
        )
        if node.get("state") not in {MissionNodeState.NEEDS_REVISION.value, MissionNodeState.RUNNING.value}:
            raise N1RevisionError("RC72_N1_REVISION_NODE_STATE_INVALID:%s" % str(node.get("state") or "UNKNOWN"))
        gate_refs = list(node.get("gate_refs") or [])
        if not gate_refs:
            raise N1RevisionError("RC72_N1_REVISION_FAILED_GATE_REQUIRED")
        gate = self._one("rc72_node_gate", gate_id=gate_refs[-1])
        if gate.get("decision") != "NEEDS_REVISION" or gate.get("mission_node_id") != node.get("mission_node_id"):
            raise N1RevisionError("RC72_N1_REVISION_ACTIVE_GATE_NOT_FAILED")
        failed_criteria = list(gate.get("failed") or [])
        if not failed_criteria:
            raise N1RevisionError("RC72_N1_REVISION_FAILED_CRITERIA_REQUIRED")
        delivery = self._one("rc72_node_delivery", delivery_id=str(gate["delivery_id"]))
        if (
            delivery.get("mission_node_id") != node.get("mission_node_id")
            or delivery.get("version") != node.get("active_delivery_version")
        ):
            raise N1RevisionError("RC72_N1_REVISION_DELIVERY_NOT_ACTIVE")
        workitems = list(delivery.get("created_by_workitems") or [])
        if len(workitems) != 1:
            raise N1RevisionError("RC72_N1_REVISION_SOURCE_WORKITEM_REQUIRED")
        previous_task = self._one("rc7_task", task_id=workitems[0])
        if previous_task.get("state") != TaskStatus.OUTPUT_PRODUCED.value:
            raise N1RevisionError("RC72_N1_REVISION_SOURCE_WORKITEM_NOT_OUTPUT_PRODUCED")
        artifact_refs = list(delivery.get("artifact_refs") or [])
        if not artifact_refs:
            raise N1RevisionError("RC72_N1_REVISION_SOURCE_ARTIFACT_REQUIRED")
        for artifact_id in artifact_refs:
            artifact = self._one("rc7_artifact", artifact_id=artifact_id)
            if artifact.get("mission_id") != batch.get("mission_id") or artifact.get("state") != "VALID":
                raise N1RevisionError("RC72_N1_REVISION_SOURCE_ARTIFACT_INVALID")
        source_dispatch = self._one("rc72_mission_node_dispatch", workitem_id=workitems[0])
        if source_dispatch.get("source_commit") != self.source_commit:
            raise N1RevisionError("RC72_N1_REVISION_SOURCE_COMMIT_MISMATCH")
        return batch, node, gate, delivery, source_dispatch

    def plan_and_assign(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        batch, node, gate, delivery, source_dispatch = self._failed_cycle(release_batch_id)
        release_id = str(batch["release_id"])
        mission_id = str(batch["mission_id"])
        node_id = str(node["mission_node_id"])
        generation = int(delivery["version"]) + 1
        failed_gate_id = str(gate["gate_id"])
        failed_delivery_id = str(delivery["delivery_id"])
        previous_workitem_id = str(list(delivery["created_by_workitems"])[0])
        input_artifact_refs = list(delivery.get("artifact_refs") or [])

        revision_id = _stable_id("N1REV", mission_id, failed_gate_id, "GEN%d" % generation)
        workitem_id = _stable_id("WI-N1-REV", revision_id, "WORKITEM")
        dispatch_id = _stable_id("N1DISP-REV", revision_id, workitem_id)
        assignment_id = _stable_id("N1ASN-REV", dispatch_id, workitem_id)
        worker_id = _stable_id("RC72FW", assignment_id, "FRESH_WORKER")

        expected_receipt = {
            "revision_id": revision_id,
            "release_id": release_id,
            "mission_id": mission_id,
            "release_batch_id": release_batch_id,
            "source_commit": self.source_commit,
            "mission_node_id": node_id,
            "failed_gate_id": failed_gate_id,
            "failed_delivery_id": failed_delivery_id,
            "previous_workitem_id": previous_workitem_id,
            "revision_generation": generation,
            "revision_workitem_id": workitem_id,
            "revision_dispatch_id": dispatch_id,
            "revision_assignment_id": assignment_id,
            "revision_worker_instance_id": worker_id,
            "input_artifact_refs": input_artifact_refs,
            "failed_criteria": list(gate.get("failed") or []),
            "status": _STATUS,
            "field_verified": False,
            "bank_final": False,
        }
        existing_receipt = self.truth.query(_ARTIFACT, revision_id=revision_id)
        if existing_receipt:
            if len(existing_receipt) != 1:
                raise N1RevisionError("RC72_N1_REVISION_RECEIPT_NOT_UNIQUE")
            for key, value in expected_receipt.items():
                if existing_receipt[0].get(key) != value:
                    raise N1RevisionError("RC72_N1_REVISION_RECEIPT_CONFLICT:%s" % key)
            task = self._one("rc7_task", task_id=workitem_id)
            assignment = self._one("rc72_mission_node_worker_assignment", assignment_id=assignment_id)
            if task.get("lease_owner") != worker_id or assignment.get("worker_instance_id") != worker_id:
                raise N1RevisionError("RC72_N1_REVISION_RECEIPT_LEASE_MISMATCH")
            return {
                "status": "RESUMED",
                "revision_id": revision_id,
                "revision_generation": generation,
                "workitem_id": workitem_id,
                "dispatch_id": dispatch_id,
                "assignment_id": assignment_id,
                "worker_instance_id": worker_id,
                "workitem_state": str(task.get("state") or "UNKNOWN"),
                "node_state": self._one("rc72_mission_node", mission_node_id=node_id)["state"],
            }

        control = ClosedLoopControlPlane(self.truth, release_id, mission_id)
        task_rows = self.truth.query("rc7_task", task_id=workitem_id)
        if not task_rows:
            task = Task(
                task_id=workitem_id,
                mission_id=mission_id,
                node=_STAGE,
                task_type=_TASK_TYPE,
                objective=(
                    "Revise N1 reality candidate after failed Gate %s; correct only evidence-backed "
                    "criteria and preserve unresolved gaps" % failed_gate_id
                ),
                required_capabilities=list(_CAPABILITIES),
                input_artifact_refs=input_artifact_refs,
                acceptance_criteria=[
                    "correct failed gate criteria: %s" % ",".join(list(gate.get("failed") or [])),
                    "use fresh real environment/deployment/capability observations",
                    "preserve unknowns/gaps when evidence is insufficient",
                ],
                priority=0,
            )
            control.register_task(task)
            task_rows = self.truth.query("rc7_task", task_id=workitem_id)
        if len(task_rows) != 1 or task_rows[0].get("state") not in {"READY", "LEASED"}:
            observed = task_rows[0].get("state") if len(task_rows) == 1 else "NOT_UNIQUE:%d" % len(task_rows)
            raise N1RevisionError("RC72_N1_REVISION_WORKITEM_NOT_ASSIGNABLE:%s" % observed)

        dispatch_payload = {
            "dispatch_id": dispatch_id,
            "release_id": release_id,
            "mission_id": mission_id,
            "release_batch_id": release_batch_id,
            "source_commit": self.source_commit,
            "field_start_receipt_id": str(source_dispatch["field_start_receipt_id"]),
            "mission_node_id": node_id,
            "node_type": _NODE_TYPE,
            "stage": _STAGE,
            "workitem_id": workitem_id,
            "team_role": _TEAM_ROLE,
            "execution_substrate": _SUBSTRATE,
            "worker_policy": _WORKER_POLICY,
            "required_capabilities": list(_CAPABILITIES),
            "input_refs": [
                "node-delivery://%s" % failed_delivery_id,
                "node-gate://%s" % failed_gate_id,
            ] + ["rc7-artifact://%s" % ref for ref in input_artifact_refs],
            "status": "READY_FOR_ASSIGNMENT",
            "revision_id": revision_id,
            "revision_generation": generation,
            "supersedes_gate_id": failed_gate_id,
            "supersedes_delivery_id": failed_delivery_id,
        }
        existing_dispatch = self.truth.query("rc72_mission_node_dispatch", dispatch_id=dispatch_id)
        if not existing_dispatch:
            now = _now()
            persisted = dict(dispatch_payload)
            persisted.update({"created_at": now, "updated_at": now, "artifact_version": 1})
            self.truth.append_atomic("RC72_MISSION_NODE_DISPATCH_UPSERTED", persisted)
        elif len(existing_dispatch) != 1:
            raise N1RevisionError("RC72_N1_REVISION_DISPATCH_NOT_UNIQUE")

        current_node = self._one("rc72_mission_node", mission_node_id=node_id)
        if current_node.get("state") == MissionNodeState.NEEDS_REVISION.value:
            RC72StateMachine(self.truth, release_id=release_id).transition_state(
                node_id,
                MissionNodeState.RUNNING,
                reason="governed N1 revision WorkItem materialized from failed Gate",
            )
        elif current_node.get("state") != MissionNodeState.RUNNING.value:
            raise N1RevisionError("RC72_N1_REVISION_NODE_NOT_RUNNING")

        task = self._one("rc7_task", task_id=workitem_id)
        recovered = False
        if task.get("state") == "READY":
            ready = [row for row in self.truth.query("rc7_task", mission_id=mission_id) if row.get("state") == "READY"]
            if len(ready) != 1 or ready[0].get("task_id") != workitem_id:
                raise N1RevisionError("RC72_N1_REVISION_READY_TASK_CONFLICT")
            leased = control.lease_next(worker_ref=worker_id, capabilities=_CAPABILITIES)
            if leased is None or leased.task_id != workitem_id:
                raise N1RevisionError("RC72_N1_REVISION_LEASE_FAILED")
        elif task.get("state") == "LEASED" and task.get("lease_owner") == worker_id:
            recovered = True
        else:
            raise N1RevisionError("RC72_N1_REVISION_COMPETING_LEASE")

        assignment_payload = {
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
            "worker_instance_id": worker_id,
            "assignment_generation": 1,
            "required_capabilities": list(_CAPABILITIES),
            "input_refs": list(dispatch_payload["input_refs"]),
            "task_state": "LEASED",
            "status": _STATUS,
            "recovered_orphan_lease": recovered,
            "revision_id": revision_id,
            "revision_generation": generation,
        }
        existing_assignment = self.truth.query("rc72_mission_node_worker_assignment", assignment_id=assignment_id)
        if not existing_assignment:
            now = _now()
            persisted = dict(assignment_payload)
            persisted.update({"created_at": now, "updated_at": now, "artifact_version": 1})
            self.truth.append_atomic("RC72_MISSION_NODE_WORKER_ASSIGNMENT_UPSERTED", persisted)
        elif len(existing_assignment) != 1 or existing_assignment[0].get("worker_instance_id") != worker_id:
            raise N1RevisionError("RC72_N1_REVISION_ASSIGNMENT_CONFLICT")

        now = _now()
        receipt = dict(expected_receipt)
        receipt.update({"created_at": now, "updated_at": now, "artifact_version": 1})
        self.truth.append_atomic(_EVENT, receipt)
        return {
            "status": "ASSIGNED",
            "revision_id": revision_id,
            "revision_generation": generation,
            "failed_gate_id": failed_gate_id,
            "workitem_id": workitem_id,
            "dispatch_id": dispatch_id,
            "assignment_id": assignment_id,
            "worker_instance_id": worker_id,
            "workitem_state": "LEASED",
            "node_state": MissionNodeState.RUNNING.value,
            "field_verified": False,
            "bank_final": False,
        }


class N1RevisionDshHandoffService(N1DshHandoffService):
    """Run only the latest persisted revision assignment through real DSH."""

    def _receipt(self, release_batch_id: str) -> Dict[str, Any]:
        return _latest_revision(self.truth, release_batch_id, self.source_commit)

    def _preflight(self, release_batch_id: str):
        receipt = self._receipt(release_batch_id)
        assignment = self._one(
            "rc72_mission_node_worker_assignment",
            assignment_id=str(receipt["revision_assignment_id"]),
        )
        task = self._one("rc7_task", task_id=str(receipt["revision_workitem_id"]))
        dispatch = self._one("rc72_mission_node_dispatch", dispatch_id=str(receipt["revision_dispatch_id"]))
        node = self._one("rc72_mission_node", mission_node_id=str(receipt["mission_node_id"]))
        if (
            assignment.get("worker_instance_id") != receipt.get("revision_worker_instance_id")
            or assignment.get("workitem_id") != receipt.get("revision_workitem_id")
            or assignment.get("dispatch_id") != receipt.get("revision_dispatch_id")
            or dispatch.get("workitem_id") != receipt.get("revision_workitem_id")
            or dispatch.get("revision_id") != receipt.get("revision_id")
            or node.get("state") != MissionNodeState.RUNNING.value
            or task.get("state") != "LEASED"
            or task.get("lease_owner") != receipt.get("revision_worker_instance_id")
        ):
            raise N1RevisionError("RC72_N1_REVISION_HANDOFF_LINEAGE_MISMATCH")
        return assignment, task

    def _prompt(self, assignment: Mapping[str, Any]) -> str:
        receipts = self.truth.query(_ARTIFACT, revision_assignment_id=str(assignment["assignment_id"]))
        if len(receipts) != 1:
            raise N1RevisionError("RC72_N1_REVISION_PROMPT_RECEIPT_NOT_UNIQUE")
        receipt = receipts[0]
        gate = self._one("rc72_node_gate", gate_id=str(receipt["failed_gate_id"]))
        body = {
            "mission_id": assignment["mission_id"],
            "release_batch_id": assignment["release_batch_id"],
            "mission_node_id": assignment["mission_node_id"],
            "workitem_id": assignment["workitem_id"],
            "revision_generation": receipt["revision_generation"],
            "supersedes_gate_id": receipt["failed_gate_id"],
            "failed_criteria": list(receipt.get("failed_criteria") or []),
            "gate_reason": gate.get("reason"),
            "input_refs": list(assignment.get("input_refs") or []),
            "authorized_tools": list(self.allowed_tools),
        }
        return (
            "You are a fresh dsh-agent-teams REALITY_RECON_WORKER for an N1 revision. "
            "The previous independent Gate failed. Re-observe real deployment/environment/capability reality; "
            "do not copy the previous candidate as truth. Correct the failed criteria only when tool evidence supports it. "
            "Do not claim NodeGate PASS, Q7 PASS, field_verified or BANK_FINAL. Preserve every unresolved unknown/gap. "
            "Return strict JSON with keys status,facts,unknowns,gaps. RevisionContext="
            + json.dumps(body, ensure_ascii=False, sort_keys=True)
        )


class N1RevisionEvidenceAnchorService(N1EvidenceAnchorService):
    def _attempt(self, release_batch_id: str) -> Dict[str, Any]:
        receipt = _latest_revision(self.truth, release_batch_id, self.source_commit)
        rows = self.truth.query("rc72_mission_node_worker_attempt", release_batch_id=release_batch_id)
        exact = [
            row for row in rows
            if row.get("source_commit") == self.source_commit
            and row.get("workitem_id") == receipt.get("revision_workitem_id")
            and row.get("state") == "WORKER_COMPLETED_PENDING_DELIVERY"
            and row.get("handoff_status") == "DSH_SESSION_OBSERVED"
            and row.get("process_outcome") == "SUCCEEDED"
        ]
        if len(exact) != 1:
            raise N1RevisionError("RC72_N1_REVISION_EXACT_ATTEMPT_REQUIRED:%d" % len(exact))
        return exact[0]


class N1RevisionGovernedHandoffService:
    def __init__(
        self,
        truth: TruthRuntime,
        *,
        source_commit: str,
        launcher: DshHeadlessWorkerLauncher,
        allowed_tools: Sequence[str],
    ) -> None:
        install_rc72_n1_revision_overlay()
        self.handoff_service = N1RevisionDshHandoffService(
            truth,
            source_commit=source_commit,
            launcher=launcher,
            allowed_tools=allowed_tools,
        )
        self.anchor_service = N1RevisionEvidenceAnchorService(
            truth, source_commit=source_commit
        )

    def handoff(self, *, release_batch_id: str) -> Dict[str, Any]:
        result = self.handoff_service.handoff(release_batch_id=release_batch_id)
        anchor = self.anchor_service.anchor(release_batch_id=release_batch_id)
        out = dict(result)
        out.update(
            {
                "evidence_anchor_id": anchor["anchor_id"],
                "raw_output_sha256": anchor["raw_output_sha256"],
            }
        )
        return out


class N1RevisionDeliveryGateService(N1DeliveryGateService):
    """Admit Delivery v2+ from the latest revision Attempt, then reuse the independent Gate."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_n1_revision_overlay()
        super().__init__(truth, source_commit=source_commit)

    def _receipt(self, release_batch_id: str) -> Dict[str, Any]:
        return _latest_revision(self.truth, release_batch_id, self.source_commit)

    def _attempt(self, release_batch_id: str) -> Dict[str, Any]:
        return N1RevisionEvidenceAnchorService(
            self.truth, source_commit=self.source_commit
        )._attempt(release_batch_id)

    def admit_delivery(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        receipt = self._receipt(release_batch_id)
        attempt = self._attempt(release_batch_id)
        anchor = self._anchor(attempt)
        _batch, node, assignment, _task = self._lineage(attempt)
        candidate, content_ref, raw_hash, _calls = self._raw_candidate(attempt, anchor)
        artifact_id, evidence_id = self._canonical_output(
            attempt,
            assignment,
            content_ref=content_ref,
            raw_hash=raw_hash,
        )
        delivery_id = self._delivery_id(str(attempt["attempt_id"]), raw_hash)
        existing = self.truth.query("rc72_node_delivery", delivery_id=delivery_id)
        if existing:
            if len(existing) != 1:
                raise N1RevisionError("RC72_N1_REVISION_DELIVERY_NOT_UNIQUE")
            return {
                "status": "RESUMED",
                "delivery_id": delivery_id,
                "artifact_id": artifact_id,
                "evidence_id": evidence_id,
                "node_state": self._one("rc72_mission_node", mission_node_id=str(attempt["mission_node_id"]))["state"],
                "workitem_state": self._one("rc7_task", task_id=str(attempt["workitem_id"]))["state"],
            }
        if node.get("state") != MissionNodeState.RUNNING.value:
            raise N1RevisionError("RC72_N1_REVISION_DELIVERY_REQUIRES_RUNNING_NODE:%s" % node.get("state"))
        generation = int(receipt["revision_generation"])
        if generation <= int(node.get("active_delivery_version") or 0):
            raise N1RevisionError("RC72_N1_REVISION_DELIVERY_VERSION_NOT_ADVANCING")
        known_gaps = _uniq(_gap_strings(candidate.get("unknowns")) + _gap_strings(candidate.get("gaps")))
        delivery = NodeDelivery(
            delivery_id=delivery_id,
            mission_id=str(attempt["mission_id"]),
            mission_node_id=str(attempt["mission_node_id"]),
            node_type=AutonomousMissionNode.N1_REALITY,
            version=generation,
            producer_ref=str(attempt["worker_instance_id"]),
            input_refs=_uniq(
                list(assignment.get("input_refs") or [])
                + [
                    "rc72-attempt://%s" % str(attempt["attempt_id"]),
                    "rc72-anchor://%s" % str(anchor["anchor_id"]),
                    "n1-revision://%s" % str(receipt["revision_id"]),
                    str(attempt["candidate_output_ref"]),
                ]
            ),
            artifact_refs=[artifact_id],
            evidence_refs=[evidence_id],
            known_gaps=known_gaps,
            created_by_workitems=[str(attempt["workitem_id"])],
        )
        RC72StateMachine(self.truth, release_id=str(attempt["release_id"])).submit_delivery(delivery)
        return {
            "status": "DELIVERY_ADMITTED",
            "delivery_id": delivery_id,
            "delivery_version": generation,
            "artifact_id": artifact_id,
            "evidence_id": evidence_id,
            "raw_hash": raw_hash,
            "node_state": MissionNodeState.REVIEW_PENDING.value,
            "workitem_state": TaskStatus.OUTPUT_PRODUCED.value,
        }


install_rc72_n1_revision_overlay()
