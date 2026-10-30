"""RC7.2 N2 Requirement aggregate Delivery and deterministic NodeGate.

Per-Requirement workers and independent reviewers own analysis/review truth.
This module is a runtime-owned aggregate boundary only:

* replay the canonical ReleaseBatch Requirement set and N2 dispatch lineage;
* require every Requirement WorkItem to have a canonical candidate and an
  independent evaluation outcome;
* aggregate reviewed candidates into one N2 NodeDelivery;
* recompute deterministic node criteria from R1 rather than trusting model
  percentages or PASS strings;
* release N3 only through an actual PASS NodeGate.

A REPAIR_REQUIRED Requirement remains visible in the aggregate Delivery as a
known gap and forces NEEDS_REVISION. No Q7, field_verified or BANK_FINAL claim
is made here.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadReader
from .models import ContractError, GapStatus, TaskStatus
from .rc72_domain import (
    AutonomousMissionNode,
    MissionNodeState,
    NodeDelivery,
    NodeGate,
    NodeGateDecision,
)
from .rc72_n2_requirement_dispatch import install_rc72_n2_requirement_dispatch_overlay
from .rc72_state_machine import RC72StateMachine
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_NODE = AutonomousMissionNode.N2_REQUIREMENT
_NEXT_NODE = AutonomousMissionNode.N3_CODE_ANALYSIS
_STAGE = "REQUIREMENT_ANALYSIS"
_PRODUCER = "rc72-runtime-n2-aggregator"
_GATE_WORKER = "rc72-runtime-n2-gate"
_GATE_SESSION = "runtime://rc72/n2-gate/v1"

_TERMINAL_REVIEW_TASK_STATES = {
    TaskStatus.PASS.value,
    TaskStatus.REPAIR_REQUIRED.value,
}
_CLOSED_GAP_STATES = {
    GapStatus.RESOLVED.value,
    GapStatus.WAIVED.value,
    GapStatus.DUPLICATE.value,
    GapStatus.SUPERSEDED.value,
}

_CRITERIA = (
    "N2_CANONICAL_REQUIREMENT_SET_COMPLETE",
    "N2_SOURCE_COMMIT_LINEAGE",
    "N2_ALL_REQUIREMENT_TASKS_PASS",
    "N2_ALL_REQUIREMENT_EVALUATIONS_PASS",
    "N2_CANONICAL_ARTIFACTS_BOUND",
    "N2_SST_IDENTITY_PROVEN",
    "N2_NO_CANDIDATE_UNKNOWNS",
    "N2_NO_CANDIDATE_GAPS",
    "N2_REVIEWER_INDEPENDENT",
    "N2_REVIEW_EVIDENCE_PRESENT",
    "N2_NO_UNRESOLVED_REQUIREMENT_GAPS",
)


class N2CompletionError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N2CompletionError("RC72_N2_COMPLETION_%s_REQUIRED" % name.upper())
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _uniq(values: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _strings(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


class N2DeliveryGateService:
    """Aggregate independently reviewed Requirement truth into the N2 node gate."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc7_truth_overlay()
        install_rc72_truth_overlay()
        install_rc72_n2_requirement_dispatch_overlay()
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.reader = CandidatePayloadReader()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N2CompletionError(
                "RC72_N2_COMPLETION_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _context(
        self, release_batch_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        mission_id = _required(batch.get("mission_id"), "mission_id")
        release_id = _required(batch.get("release_id"), "release_id")
        requirements = list(batch.get("requirement_ids") or [])
        if (
            not requirements
            or not all(isinstance(item, str) and item.strip() for item in requirements)
            or len(set(requirements)) != len(requirements)
        ):
            raise N2CompletionError("RC72_N2_COMPLETION_CANONICAL_REQUIREMENTS_INVALID")

        node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NODE.value
        )
        if node.get("scope_ref") != "release-batch://%s" % release_batch_id:
            raise N2CompletionError("RC72_N2_COMPLETION_NODE_SCOPE_MISMATCH")
        next_node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
        )

        rows = self.truth.query(
            "rc72_n2_requirement_dispatch", release_batch_id=release_batch_id
        )
        dispatches = [
            row
            for row in rows
            if row.get("source_commit") == self.source_commit
            and row.get("mission_id") == mission_id
            and row.get("release_id") == release_id
            and row.get("mission_node_id") == node.get("mission_node_id")
            and row.get("node_type") == _NODE.value
            and row.get("stage") == _STAGE
            and row.get("status") == "READY_FOR_ASSIGNMENT"
        ]
        by_requirement: Dict[str, Dict[str, Any]] = {}
        for row in dispatches:
            requirement_id = _required(row.get("requirement_id"), "requirement_id")
            if requirement_id in by_requirement:
                raise N2CompletionError(
                    "RC72_N2_COMPLETION_DUPLICATE_REQUIREMENT_DISPATCH:%s"
                    % requirement_id
                )
            by_requirement[requirement_id] = row
        if set(by_requirement) != set(requirements) or len(dispatches) != len(requirements):
            raise N2CompletionError(
                "RC72_N2_COMPLETION_REQUIREMENT_DISPATCH_SET_MISMATCH"
            )
        ordered = [by_requirement[requirement_id] for requirement_id in requirements]
        return batch, node, next_node, ordered

    @staticmethod
    def _reviewer_id(evaluation: Mapping[str, Any]) -> str:
        ref = str(evaluation.get("evaluator_ref") or "")
        if not ref.startswith("dsh:"):
            return ""
        return ref[len("dsh:") :].split("+", 1)[0].strip()

    def _evidence_rows(
        self, mission_id: str, evidence_ids: Sequence[str]
    ) -> List[Dict[str, Any]]:
        rows = []
        for evidence_id in _uniq(_strings(list(evidence_ids))):
            evidence = self._one("rc7_evidence", evidence_id=evidence_id)
            if evidence.get("mission_id") != mission_id:
                raise N2CompletionError(
                    "RC72_N2_COMPLETION_EVIDENCE_MISSION_MISMATCH:%s"
                    % evidence_id
                )
            rows.append(evidence)
        return rows

    def _requirement_record(
        self,
        *,
        mission_id: str,
        dispatch: Mapping[str, Any],
    ) -> Dict[str, Any]:
        requirement_id = _required(dispatch.get("requirement_id"), "requirement_id")
        task_id = _required(dispatch.get("workitem_id"), "workitem_id")
        task = self._one("rc7_task", task_id=task_id)
        if (
            task.get("mission_id") != mission_id
            or task.get("node") != _STAGE
            or task.get("state") not in _TERMINAL_REVIEW_TASK_STATES
        ):
            raise N2CompletionError(
                "RC72_N2_COMPLETION_REQUIREMENT_REVIEW_INCOMPLETE:%s:%s"
                % (requirement_id, str(task.get("state") or "UNKNOWN"))
            )

        artifact_refs = list(task.get("output_artifact_refs") or [])
        if len(artifact_refs) != 1:
            raise N2CompletionError(
                "RC72_N2_COMPLETION_REQUIREMENT_OUTPUT_NOT_UNIQUE:%s:%d"
                % (requirement_id, len(artifact_refs))
            )
        artifact_id = _required(artifact_refs[0], "artifact_id")
        artifact = self._one("rc7_artifact", artifact_id=artifact_id)
        if (
            artifact.get("mission_id") != mission_id
            or artifact.get("producer_task_id") != task_id
            or artifact.get("state") != "VALID"
        ):
            raise N2CompletionError(
                "RC72_N2_COMPLETION_ARTIFACT_LINEAGE_MISMATCH:%s" % requirement_id
            )
        candidate = self.reader.load(
            self.truth,
            artifact_id,
            expected_mission_id=mission_id,
            expected_task_id=task_id,
        )
        semantic = dict(candidate.semantic_payload)
        if semantic.get("requirement_id") != requirement_id:
            raise N2CompletionError(
                "RC72_N2_COMPLETION_REQUIREMENT_ID_MISMATCH:%s" % requirement_id
            )

        evaluation_id = _required(task.get("evaluation_id"), "evaluation_id")
        evaluation = self._one("rc7_evaluation", evaluation_id=evaluation_id)
        expected_result = (
            "PASS"
            if task.get("state") == TaskStatus.PASS.value
            else "REPAIR_REQUIRED"
        )
        if (
            evaluation.get("mission_id") != mission_id
            or evaluation.get("node") != _STAGE
            or evaluation.get("result") != expected_result
            or artifact_id not in list(evaluation.get("artifact_refs") or [])
        ):
            raise N2CompletionError(
                "RC72_N2_COMPLETION_EVALUATION_LINEAGE_MISMATCH:%s"
                % requirement_id
            )

        artifact_evidence = self._evidence_rows(
            mission_id, list(artifact.get("evidence_refs") or [])
        )
        evaluation_evidence = self._evidence_rows(
            mission_id, list(evaluation.get("evidence_refs") or [])
        )
        reviewer_id = self._reviewer_id(evaluation)
        analyzer_id = str(task.get("lease_owner") or "")
        reviewer_independent = bool(
            reviewer_id and analyzer_id and reviewer_id != analyzer_id
        )
        reviewer_evidence = [
            row
            for row in evaluation_evidence
            if row.get("kind") == "INDEPENDENT_REQUIREMENT_REVIEW_PROOF"
            and str(row.get("source_ref") or "").startswith("dsh://worker/")
        ]

        gap_ids = _uniq(
            _strings(list(task.get("gap_refs") or []))
            + _strings(list(evaluation.get("gap_refs") or []))
        )
        active_gap_ids: List[str] = []
        for gap_id in gap_ids:
            gap = self._one("rc7_gap", gap_id=gap_id)
            if gap.get("mission_id") != mission_id:
                raise N2CompletionError(
                    "RC72_N2_COMPLETION_GAP_MISSION_MISMATCH:%s" % gap_id
                )
            if str(gap.get("state") or "") not in _CLOSED_GAP_STATES:
                active_gap_ids.append(gap_id)

        sst_ids = semantic.get("sst_ids")
        sst_valid = bool(
            isinstance(sst_ids, list)
            and sst_ids
            and all(isinstance(item, str) and item.strip() for item in sst_ids)
            and len(set(sst_ids)) == len(sst_ids)
        )
        unknowns = semantic.get("candidate_unknowns")
        candidate_gaps = semantic.get("candidate_gaps")
        unknowns_empty = isinstance(unknowns, list) and not unknowns
        candidate_gaps_empty = isinstance(candidate_gaps, list) and not candidate_gaps

        evidence_ids = _uniq(
            [str(row["evidence_id"]) for row in artifact_evidence + evaluation_evidence]
        )
        return {
            "requirement_id": requirement_id,
            "dispatch_id": str(dispatch["dispatch_id"]),
            "task_id": task_id,
            "task_state": str(task["state"]),
            "artifact_id": artifact_id,
            "artifact_hash": str(artifact.get("content_hash") or ""),
            "evaluation_id": evaluation_id,
            "evaluation_result": str(evaluation["result"]),
            "reviewer_id": reviewer_id,
            "reviewer_independent": reviewer_independent,
            "review_evidence_present": bool(reviewer_evidence),
            "sst_valid": sst_valid,
            "unknowns_empty": unknowns_empty,
            "candidate_gaps_empty": candidate_gaps_empty,
            "active_gap_ids": active_gap_ids,
            "evidence_ids": evidence_ids,
            "source_n1_gate_id": str(dispatch.get("source_n1_gate_id") or ""),
            "source_n1_delivery_id": str(dispatch.get("source_n1_delivery_id") or ""),
            "source_commit_ok": dispatch.get("source_commit") == self.source_commit,
        }

    def _records(
        self, release_batch_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
        batch, node, next_node, dispatches = self._context(release_batch_id)
        mission_id = str(batch["mission_id"])
        records = [
            self._requirement_record(mission_id=mission_id, dispatch=row)
            for row in dispatches
        ]
        if len({row["requirement_id"] for row in records}) != len(records):
            raise N2CompletionError("RC72_N2_COMPLETION_REQUIREMENT_SET_NOT_UNIQUE")
        source_gates = {row["source_n1_gate_id"] for row in records}
        source_deliveries = {row["source_n1_delivery_id"] for row in records}
        if len(source_gates) != 1 or "" in source_gates:
            raise N2CompletionError("RC72_N2_COMPLETION_N1_GATE_LINEAGE_MISMATCH")
        if len(source_deliveries) != 1 or "" in source_deliveries:
            raise N2CompletionError(
                "RC72_N2_COMPLETION_N1_DELIVERY_LINEAGE_MISMATCH"
            )
        return batch, node, next_node, records

    @staticmethod
    def _record_signature(records: Sequence[Mapping[str, Any]]) -> str:
        parts = []
        for row in records:
            parts.append(
                "%s:%s:%s:%s"
                % (
                    row["requirement_id"],
                    row["artifact_id"],
                    row["artifact_hash"],
                    row["evaluation_id"],
                )
            )
        return "|".join(parts)

    def admit_delivery(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        batch, node, _next_node, records = self._records(release_batch_id)
        mission_id = str(batch["mission_id"])
        release_id = str(batch["release_id"])
        node_id = str(node["mission_node_id"])
        signature = self._record_signature(records)
        delivery_id = _stable_id(
            "N2DEL", mission_id, release_batch_id, self.source_commit, signature
        )

        existing = self.truth.query("rc72_node_delivery", delivery_id=delivery_id)
        if existing:
            if len(existing) != 1:
                raise N2CompletionError("RC72_N2_COMPLETION_DELIVERY_NOT_UNIQUE")
            return {
                "status": "RESUMED",
                "delivery_id": delivery_id,
                "node_state": self._one(
                    "rc72_mission_node", mission_node_id=node_id
                )["state"],
                "known_gap_ids": list(existing[0].get("known_gaps") or []),
            }

        if node.get("state") != MissionNodeState.RUNNING.value:
            raise N2CompletionError(
                "RC72_N2_COMPLETION_DELIVERY_REQUIRES_RUNNING_NODE:%s"
                % str(node.get("state") or "UNKNOWN")
            )

        existing_deliveries = self.truth.query(
            "rc72_node_delivery", mission_node_id=node_id
        )
        version = (
            max(int(row.get("version") or 0) for row in existing_deliveries) + 1
            if existing_deliveries
            else 1
        )
        workitems = [row["task_id"] for row in records]
        artifacts = [row["artifact_id"] for row in records]
        evidence = _uniq(
            evidence_id for row in records for evidence_id in row["evidence_ids"]
        )
        known_gaps = _uniq(
            gap_id for row in records for gap_id in row["active_gap_ids"]
        )
        input_refs = _uniq(
            ["n1-delivery://%s" % records[0]["source_n1_delivery_id"],
             "n1-gate://%s" % records[0]["source_n1_gate_id"]]
            + ["n2-dispatch://%s" % row["dispatch_id"] for row in records]
            + ["evaluation://%s" % row["evaluation_id"] for row in records]
        )
        passed_count = sum(
            1 for row in records if row["task_state"] == TaskStatus.PASS.value
        )
        delivery = NodeDelivery(
            delivery_id=delivery_id,
            mission_id=mission_id,
            mission_node_id=node_id,
            node_type=_NODE,
            version=version,
            producer_ref=_PRODUCER,
            input_refs=input_refs,
            artifact_refs=artifacts,
            evidence_refs=evidence,
            known_gaps=known_gaps,
            created_by_workitems=workitems,
            sufficiency_score=float(passed_count) / float(len(records)),
        )
        RC72StateMachine(self.truth, release_id=release_id).submit_delivery(delivery)
        return {
            "status": "DELIVERY_ADMITTED",
            "delivery_id": delivery_id,
            "delivery_version": version,
            "node_state": MissionNodeState.REVIEW_PENDING.value,
            "requirement_count": len(records),
            "passed_requirement_count": passed_count,
            "known_gap_ids": known_gaps,
        }

    def _criterion_results(
        self,
        *,
        batch: Mapping[str, Any],
        records: Sequence[Mapping[str, Any]],
    ) -> Dict[str, bool]:
        requirements = list(batch.get("requirement_ids") or [])
        return {
            "N2_CANONICAL_REQUIREMENT_SET_COMPLETE": (
                [row["requirement_id"] for row in records] == requirements
                and len(records) == len(requirements)
            ),
            "N2_SOURCE_COMMIT_LINEAGE": all(
                row["source_commit_ok"] for row in records
            ),
            "N2_ALL_REQUIREMENT_TASKS_PASS": all(
                row["task_state"] == TaskStatus.PASS.value for row in records
            ),
            "N2_ALL_REQUIREMENT_EVALUATIONS_PASS": all(
                row["evaluation_result"] == "PASS" for row in records
            ),
            "N2_CANONICAL_ARTIFACTS_BOUND": all(
                bool(row["artifact_id"] and row["artifact_hash"]) for row in records
            ),
            "N2_SST_IDENTITY_PROVEN": all(row["sst_valid"] for row in records),
            "N2_NO_CANDIDATE_UNKNOWNS": all(
                row["unknowns_empty"] for row in records
            ),
            "N2_NO_CANDIDATE_GAPS": all(
                row["candidate_gaps_empty"] for row in records
            ),
            "N2_REVIEWER_INDEPENDENT": all(
                row["reviewer_independent"] for row in records
            ),
            "N2_REVIEW_EVIDENCE_PRESENT": all(
                row["review_evidence_present"] for row in records
            ),
            "N2_NO_UNRESOLVED_REQUIREMENT_GAPS": all(
                not row["active_gap_ids"] for row in records
            ),
        }

    def apply_gate(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        batch, node, next_node, records = self._records(release_batch_id)
        mission_id = str(batch["mission_id"])
        release_id = str(batch["release_id"])
        node_id = str(node["mission_node_id"])

        active_version = node.get("active_delivery_version")
        if isinstance(active_version, bool) or not isinstance(active_version, int):
            raise N2CompletionError("RC72_N2_COMPLETION_ACTIVE_DELIVERY_REQUIRED")
        deliveries = [
            row
            for row in self.truth.query(
                "rc72_node_delivery", mission_node_id=node_id
            )
            if row.get("version") == active_version
            and row.get("delivery_id") in list(node.get("delivery_refs") or [])
        ]
        if len(deliveries) != 1:
            raise N2CompletionError(
                "RC72_N2_COMPLETION_ACTIVE_DELIVERY_NOT_UNIQUE:%d"
                % len(deliveries)
            )
        delivery = deliveries[0]
        current_artifacts = [row["artifact_id"] for row in records]
        current_workitems = [row["task_id"] for row in records]
        if (
            list(delivery.get("artifact_refs") or []) != current_artifacts
            or list(delivery.get("created_by_workitems") or []) != current_workitems
        ):
            raise N2CompletionError(
                "RC72_N2_COMPLETION_DELIVERY_CURRENT_TRUTH_MISMATCH"
            )

        result = self._criterion_results(batch=batch, records=records)
        passed = [name for name in _CRITERIA if result[name]]
        failed = [name for name in _CRITERIA if not result[name]]
        decision = (
            NodeGateDecision.PASS
            if not failed
            else NodeGateDecision.NEEDS_REVISION
        )
        gate_id = _stable_id(
            "N2GATE",
            str(delivery["delivery_id"]),
            self.source_commit,
            decision.value,
            ",".join(failed),
        )
        evidence_refs = _uniq(
            evidence_id for row in records for evidence_id in row["evidence_ids"]
        )

        existing = self.truth.query("rc72_node_gate", gate_id=gate_id)
        if existing:
            if len(existing) != 1:
                raise N2CompletionError("RC72_N2_COMPLETION_GATE_NOT_UNIQUE")
            current_node = self._one("rc72_mission_node", mission_node_id=node_id)
            current_next = self._one(
                "rc72_mission_node",
                mission_id=mission_id,
                node_type=_NEXT_NODE.value,
            )
            if decision == NodeGateDecision.PASS:
                if current_node.get("state") != MissionNodeState.PASS.value:
                    raise N2CompletionError(
                        "RC72_N2_COMPLETION_EXISTING_PASS_GATE_NODE_NOT_PASS"
                    )
                if current_next.get("state") == MissionNodeState.NOT_STARTED.value:
                    RC72StateMachine(
                        self.truth, release_id=release_id
                    ).forward(
                        _NODE, _NEXT_NODE, source_gate_id=gate_id
                    )
                    current_next = self._one(
                        "rc72_mission_node",
                        mission_id=mission_id,
                        node_type=_NEXT_NODE.value,
                    )
            return {
                "status": "RESUMED",
                "gate_id": gate_id,
                "decision": decision.value,
                "failed": failed,
                "n2_state": current_node["state"],
                "n3_state": current_next["state"],
            }

        if node.get("state") != MissionNodeState.REVIEW_PENDING.value:
            raise N2CompletionError(
                "RC72_N2_COMPLETION_GATE_REQUIRES_REVIEW_PENDING:%s"
                % str(node.get("state") or "UNKNOWN")
            )

        gate = NodeGate(
            gate_id=gate_id,
            mission_id=mission_id,
            mission_node_id=node_id,
            node_type=_NODE,
            delivery_id=str(delivery["delivery_id"]),
            decision=decision,
            reviewer_worker_id=_GATE_WORKER,
            reviewer_session_id=_GATE_SESSION,
            criteria=list(_CRITERIA),
            passed=passed,
            failed=failed,
            evidence_refs=evidence_refs,
            return_node=_NODE if decision == NodeGateDecision.NEEDS_REVISION else None,
            reason=(
                "all canonical Requirement analyses independently accepted"
                if decision == NodeGateDecision.PASS
                else "N2 deterministic criteria failed: %s" % ",".join(failed)
            ),
        )
        runtime = RC72StateMachine(self.truth, release_id=release_id)
        runtime.apply_gate(gate)

        n3_state = next_node["state"]
        if decision == NodeGateDecision.PASS:
            if next_node.get("state") != MissionNodeState.NOT_STARTED.value:
                raise N2CompletionError(
                    "RC72_N2_COMPLETION_N3_PREMATURE_STATE:%s"
                    % str(next_node.get("state") or "UNKNOWN")
                )
            runtime.forward(_NODE, _NEXT_NODE, source_gate_id=gate_id)
            n3_state = MissionNodeState.READY.value

        return {
            "status": "GATE_APPLIED",
            "gate_id": gate_id,
            "decision": decision.value,
            "passed": passed,
            "failed": failed,
            "n2_state": (
                MissionNodeState.PASS.value
                if decision == NodeGateDecision.PASS
                else MissionNodeState.NEEDS_REVISION.value
            ),
            "n3_state": n3_state,
            "known_gap_ids": list(delivery.get("known_gaps") or []),
        }

    def complete(self, *, release_batch_id: str) -> Dict[str, Any]:
        delivery = self.admit_delivery(release_batch_id=release_batch_id)
        gate = self.apply_gate(release_batch_id=release_batch_id)
        return {"delivery": delivery, "gate": gate}
